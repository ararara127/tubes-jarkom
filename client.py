#!/usr/bin/env python3
"""
Tugas Besar Jaringan Komputer
Client (Laptop B)

Client ini digunakan untuk melakukan pengujian:
1. HTTP single request
2. HTTP multi client (parallel)
3. UDP QoS test (loss, RTT, jitter, throughput)
4. Browser mode (save HTML dan buka di browser)

Client akan berkomunikasi dengan:
- Web server langsung (port 8000 / 9000)
- Proxy server (port 8080 / 9090)
"""

import socket
import threading
import argparse
import time
import csv
import os
import webbrowser
import logging

# Konfigurasi logging agar output terminal rapi dan mudah dibaca
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [CLIENT] %(levelname)s: %(message)s"
)


def http_request(
    host: str,
    port: int,
    path: str = "/",
    save_as: str | None = None,
    open_browser: bool = False
) -> tuple[float, int]:
    """
    Fungsi untuk mengirim satu HTTP GET request ke server.

    Parameter:
    - host        : IP tujuan (Laptop A)
    - port        : Port tujuan (8000 atau 8080)
    - path        : Path HTTP (default "/")
    - save_as     : Nama file HTML jika ingin disimpan
    - open_browser: Jika True, file HTML akan langsung dibuka di browser

    Return:
    - durasi request (detik)
    - ukuran response (byte)
    """

    addr = (host, port)
    logging.info(f"Connecting to {addr} ...")
    start = time.time()

    # Membuat socket TCP
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(8.0)
        s.connect(addr)

        # Request HTTP sederhana
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"Connection: close\r\n\r\n"
        )
        s.sendall(req.encode())

        # Menerima response sampai koneksi ditutup server
        response = b""
        while True:
            data = s.recv(4096)
            if not data:
                break
            response += data

    duration = time.time() - start
    logging.info(f"Received {len(response)} bytes in {duration:.4f} s")

    # Memisahkan HTTP header dan body
    try:
        _, body = response.split(b"\r\n\r\n", 1)
    except ValueError:
        body = b""

    # Jika diminta save file
    if save_as:
        with open(save_as, "wb") as f:
            f.write(body)
        logging.info(f"HTML body saved to {save_as}")

        # Membuka file HTML di browser lokal
        if open_browser:
            abs_path = os.path.abspath(save_as)
            webbrowser.open(f"file://{abs_path}")

    return duration, len(response)


def http_worker(host: str, port: int, path: str, idx: int) -> None:
    """
    Worker thread untuk HTTP multi client.
    Satu worker melakukan satu HTTP request.
    """
    d, size = http_request(host, port, path)
    logging.info(f"[HTTP-CLIENT-{idx}] done: {size} bytes, {d:.4f} s")


def http_multi_client(
    host: str,
    port: int,
    path: str = "/",
    num_clients: int = 5
) -> None:
    """
    Menjalankan beberapa HTTP client secara paralel menggunakan thread.
    Digunakan untuk menguji kemampuan server dalam menangani banyak koneksi.
    """

    threads: list[threading.Thread] = []

    for i in range(num_clients):
        t = threading.Thread(
            target=http_worker,
            args=(host, port, path, i + 1),
            daemon=True
        )
        t.start()
        threads.append(t)

    # Menunggu semua thread selesai
    for t in threads:
        t.join()


def udp_qos_test(
    host: str,
    port: int,
    num_packets: int = 50,
    packet_size: int = 100,
    interval: float = 0.05,
    csv_file: str | None = None
) -> dict:
    """
    Melakukan pengujian QoS menggunakan UDP echo.

    Parameter:
    - num_packets : jumlah paket UDP yang dikirim
    - packet_size: ukuran payload UDP (byte)
    - interval   : jeda antar paket
    - csv_file   : nama file CSV untuk menyimpan RTT

    Hasil pengujian:
    - packet loss
    - average RTT
    - jitter
    - throughput
    """

    addr = (host, port)
    logging.info(
        f"Starting UDP QoS test to {addr} "
        f"(N={num_packets}, size={packet_size}, interval={interval}s)"
    )

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(1.0)

    send_times: dict[int, float] = {}
    rtt_results: list[tuple[int, float]] = []
    recv_count = 0

    start_test = time.time()

    for seq in range(1, num_packets + 1):
        # Payload berisi sequence number dan timestamp
        payload = f"{seq};{time.time()}".encode()

        # Padding agar ukuran paket konsisten
        if len(payload) < packet_size:
            payload += b"x" * (packet_size - len(payload))

        send_time = time.time()
        send_times[seq] = send_time

        try:
            sock.sendto(payload, addr)
        except Exception as e:
            logging.error(f"Error sending packet {seq}: {e}")
            continue

        try:
            sock.settimeout(max(1.0, interval * 2))
            data, server_addr = sock.recvfrom(65535)
            recv_time = time.time()

            # Ambil sequence number dari response
            try:
                resp_text = data.decode(errors="ignore")
                resp_seq = int(resp_text.split(";", 1)[0])
            except Exception:
                resp_seq = None

            if resp_seq in send_times:
                rtt = recv_time - send_times[resp_seq]
                rtt_results.append((resp_seq, rtt))
                recv_count += 1
                logging.info(
                    f"Recv echo seq={resp_seq} from {server_addr}, "
                    f"RTT={rtt * 1000:.2f} ms"
                )

        except socket.timeout:
            logging.warning(f"Timeout waiting echo for seq={seq}")

        # Menjaga interval pengiriman paket
        elapsed = time.time() - send_time
        if elapsed < interval:
            time.sleep(interval - elapsed)

    total_time = time.time() - start_test
    sock.close()

    sent_count = num_packets
    lost_count = sent_count - recv_count
    packet_loss = (lost_count / sent_count) * 100.0

    if rtt_results:
        rtts = [r for _, r in rtt_results]
        avg_latency = sum(rtts) / len(rtts)
        diffs = [abs(rtts[i] - rtts[i - 1]) for i in range(1, len(rtts))]
        jitter = sum(diffs) / len(diffs) if diffs else 0.0
    else:
        avg_latency = 0.0
        jitter = 0.0

    total_bytes = recv_count * packet_size
    throughput_bps = (total_bytes * 8 / total_time) if total_time > 0 else 0.0

    logging.info("===== QoS RESULT =====")
    logging.info(f"Sent packets     : {sent_count}")
    logging.info(f"Received packets : {recv_count}")
    logging.info(f"Packet loss      : {packet_loss:.2f} %")
    logging.info(f"Avg latency (RTT): {avg_latency * 1000:.2f} ms")
    logging.info(f"Jitter           : {jitter * 1000:.2f} ms")
    logging.info(f"Throughput       : {throughput_bps:.2f} bps")

    # Simpan RTT ke file CSV jika diminta
    if csv_file:
        with open(csv_file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["seq", "rtt_ms"])
            for seq, rtt in rtt_results:
                writer.writerow([seq, rtt * 1000])
        logging.info(f"RTT detail saved to {csv_file}")

    return {
        "sent": sent_count,
        "received": recv_count,
        "loss_percent": packet_loss,
        "avg_latency_ms": avg_latency * 1000,
        "jitter_ms": jitter * 1000,
        "throughput_bps": throughput_bps,
    }


def main() -> None:
    """
    Fungsi utama program client.
    Mengatur parsing argumen dan pemilihan mode pengujian.
    """

    parser = argparse.ArgumentParser(
        description="Client HTTP dan UDP untuk pengujian Tubes Jarkom",
        formatter_class=argparse.RawTextHelpFormatter
    )

    subparsers = parser.add_subparsers(dest="mode", required=True)

    # Mode HTTP single
    p_http = subparsers.add_parser("http", help="Single HTTP request")
    p_http.add_argument("--host", required=True)
    p_http.add_argument("--port", type=int, required=True)
    p_http.add_argument("--path", default="/")
    p_http.add_argument("--save")
    p_http.add_argument("--browser", action="store_true")

    # Mode HTTP multi
    p_multi = subparsers.add_parser("http-multi", help="HTTP multi client")
    p_multi.add_argument("--host", required=True)
    p_multi.add_argument("--port", type=int, required=True)
    p_multi.add_argument("--path", default="/")
    p_multi.add_argument("--num", type=int, default=5)

    # Mode UDP QoS
    p_udp = subparsers.add_parser("udp-test", help="UDP QoS test")
    p_udp.add_argument("--host", required=True)
    p_udp.add_argument("--port", type=int, required=True)
    p_udp.add_argument("--num", type=int, default=50)
    p_udp.add_argument("--size", type=int, default=100)
    p_udp.add_argument("--interval", type=float, default=0.05)
    p_udp.add_argument("--csv")

    args = parser.parse_args()

    if args.mode == "http":
        http_request(args.host, args.port, args.path, args.save, args.browser)
    elif args.mode == "http-multi":
        http_multi_client(args.host, args.port, args.path, args.num)
    elif args.mode == "udp-test":
        udp_qos_test(args.host, args.port, args.num, args.size, args.interval, args.csv)


if __name__ == "__main__":
    main()
