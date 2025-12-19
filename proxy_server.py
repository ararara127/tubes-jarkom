#!/usr/bin/env python3
"""
Tugas Besar Jaringan Komputer
Proxy Server (Laptop A)

Anggota:
1) Ahmad Refi   - 103012300231
2) Azzahra Indah - 103012300238

Fungsi proxy:
- TCP proxy: laptop B konek ke port 8080 (proxy), lalu proxy forward ke web server port 8000
  Sekalian ada cache sederhana (biar kelihatan HIT / MISS)
- UDP proxy: laptop B kirim UDP ke port 9090 (proxy), lalu proxy terusin ke web server UDP port 9000
  Proxy balikin response ke client, sambil log RTT versi proxy

Port default:
- Proxy TCP : 8080/tcp
- Proxy UDP : 9090/udp

Cara run (Laptop A):
  python proxy_server.py --target-host 192.168.1.3

Catatan penting:
- target-host itu IP Laptop A yang dipakai web_server.py (biasanya IPv4 Wi-Fi)
- Jangan lupa web_server.py harus sudah jalan dulu (HTTP 8000 dan UDP 9000)
"""

import socket
import threading
import logging
import time
import argparse

HOST = "0.0.0.0"
TCP_PORT = 8080          # proxy untuk HTTP
UDP_PORT = 9090          # proxy untuk UDP QoS

# Default target (web server di Laptop A). Bisa dioverride lewat argumen.
WEB_SERVER_IP = "10.189.19.36"
WEB_SERVER_HTTP_PORT = 8000
WEB_SERVER_UDP_PORT = 9000

SOCKET_TIMEOUT = 8

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [PROXY] %(levelname)s: %(message)s"
)

# Cache sederhana untuk response HTTP (key: request bytes, value: response bytes)
HTTP_CACHE: dict[bytes, bytes] = {}
CACHE_LOCK = threading.Lock()


def handle_tcp_client(client_conn: socket.socket, client_addr: tuple[str, int], target_host: str) -> None:
    """
    Handler koneksi TCP dari client (Laptop B).
    Alur:
    1) terima request dari client
    2) cek cache
    3) kalau MISS -> konek ke web server (target_host:8000), forward request, terima response
    4) kirim response balik ke client
    """
    client_conn.settimeout(SOCKET_TIMEOUT)

    try:
        req = b""
        while True:
            chunk = client_conn.recv(4096)
            if not chunk:
                break
            req += chunk
            # Request HTTP biasanya berhenti saat ketemu header end
            if b"\r\n\r\n" in req:
                break

        if not req:
            return

        # Cek cache
        with CACHE_LOCK:
            cached = HTTP_CACHE.get(req)

        if cached is not None:
            client_conn.sendall(cached)
            logging.info(f"[TCP] {client_addr} -> {target_host}:{WEB_SERVER_HTTP_PORT} cache=HIT bytes={len(cached)}")
            return

        # Cache MISS: forward ke web server
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(SOCKET_TIMEOUT)
            s.connect((target_host, WEB_SERVER_HTTP_PORT))
            s.sendall(req)

            resp = b""
            while True:
                data = s.recv(4096)
                if not data:
                    break
                resp += data

        # Simpan ke cache
        with CACHE_LOCK:
            HTTP_CACHE[req] = resp

        client_conn.sendall(resp)
        logging.info(f"[TCP] {client_addr} -> {target_host}:{WEB_SERVER_HTTP_PORT} cache=MISS bytes={len(resp)}")

    except Exception as e:
        logging.error(f"[TCP] Error forwarding to web server: {e}")
    finally:
        try:
            client_conn.close()
        except Exception:
            pass


def tcp_proxy_server(target_host: str) -> None:
    """
    Server TCP proxy.
    Nunggu koneksi dari client (Laptop B) di 0.0.0.0:8080.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, TCP_PORT))
        s.listen(50)

        logging.info(f"[TCP] Proxy listening on {HOST}:{TCP_PORT} -> target {target_host}:{WEB_SERVER_HTTP_PORT}")

        while True:
            client_conn, client_addr = s.accept()
            t = threading.Thread(target=handle_tcp_client, args=(client_conn, client_addr, target_host), daemon=True)
            t.start()
            logging.info(f"[TCP] New client {client_addr}")


def udp_proxy_server(target_host: str) -> None:
    """
    Server UDP proxy.
    - Terima paket dari client (Laptop B) di port 9090
    - Forward ke web server UDP port 9000
    - Terima echo dari web server, balikin lagi ke client

    Log RTT versi proxy:
    - RTT dihitung dari waktu proxy kirim ke web server sampai proxy terima balasan.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind((HOST, UDP_PORT))
        s.settimeout(SOCKET_TIMEOUT)
        logging.info(f"[UDP] Proxy listening on {HOST}:{UDP_PORT} -> target {target_host}:{WEB_SERVER_UDP_PORT}")

        while True:
            # 1) Nunggu paket dari client. Kalau timeout, jangan crash, lanjut nunggu lagi.
            try:
                data, client_addr = s.recvfrom(65535)
            except socket.timeout:
                # Normal kalau belum ada client ngirim UDP
                continue
            except Exception as e:
                logging.error(f"[UDP] recvfrom(client) error: {e}")
                continue

            # 2) Forward ke web server, hitung RTT versi proxy (proxy <-> web server)
            t0 = time.time()
            try:
                s.sendto(data, (target_host, WEB_SERVER_UDP_PORT))
            except Exception as e:
                logging.error(f"[UDP] sendto(webserver) error: {e}")
                continue

            # 3) Terima balasan dari web server, lalu kirim balik ke client
            try:
                resp, server_addr = s.recvfrom(65535)
                t1 = time.time()

                s.sendto(resp, client_addr)

                rtt_ms = (t1 - t0) * 1000
                logging.info(f"[UDP] {client_addr} -> {server_addr} bytes={len(data)} RTT={rtt_ms:.2f} ms")
            except socket.timeout:
                logging.warning(f"[UDP] Timeout from web server for client {client_addr}")
            except Exception as e:
                logging.error(f"[UDP] recvfrom(webserver)/sendto(client) error: {e}")


def main() -> None:
    """
    Entry point.
    Nyalain TCP dan UDP proxy barengan (thread).
    """
    parser = argparse.ArgumentParser(
        description="Proxy Server (Laptop A)",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Panduan cepat:\n"
            "  Jalankan proxy : python proxy_server.py --target-host <IP_LAPTOP_A>\n"
            "  Client HTTP via proxy: python client.py http --host <IP_LAPTOP_A> --port 8080 --path /\n"
            "  Client UDP via proxy : python client.py udp-test --host <IP_LAPTOP_A> --port 9090 --num 50 --size 100 --interval 0.05 --csv via_proxy.csv\n"
        )
    )
    parser.add_argument("--target-host", default=WEB_SERVER_IP, help="IP web_server.py (Laptop A)")

    args = parser.parse_args()

    t_tcp = threading.Thread(target=tcp_proxy_server, args=(args.target_host,), daemon=True)
    t_udp = threading.Thread(target=udp_proxy_server, args=(args.target_host,), daemon=True)
    t_tcp.start()
    t_udp.start()

    logging.info(f"[PROXY] Ready. TCP:{TCP_PORT} UDP:{UDP_PORT}")

    # Biar main thread ga selesai
    t_tcp.join()
    t_udp.join()


if __name__ == "__main__":
    main()
