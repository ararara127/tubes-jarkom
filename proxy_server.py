#!/usr/bin/env python3
import socket
import threading
import logging
import time

HOST = "0.0.0.0"
TCP_PORT = 8080          # proxy untuk HTTP
UDP_PORT = 9090          # proxy untuk UDP QoS

# IP web server di Laptop A
# kalau IP Laptop A berubah, ganti nilai ini
WEB_SERVER_IP = "192.168.1.11"   # atau "127.0.0.1" kalau mau pakai localhost
WEB_SERVER_HTTP_PORT = 8000
WEB_SERVER_UDP_PORT = 9000

SOCKET_TIMEOUT = 8
MAX_CONNECTIONS = 50

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [PROXY] %(levelname)s: %(message)s"
)

cache = {}
cache_lock = threading.Lock()


def handle_tcp_client(client_sock, client_addr):
    client_sock.settimeout(SOCKET_TIMEOUT)
    try:
        request = b""
        while True:
            chunk = client_sock.recv(4096)
            if not chunk:
                break
            request += chunk
            if b"\r\n\r\n" in request:
                break

        if not request:
            client_sock.close()
            return

        first_line = request.split(b"\r\n", 1)[0].decode(errors="ignore")
        cache_key = first_line

        # baca cache tanpa nested lock
        with cache_lock:
            cached_response = cache.get(cache_key)

        if cached_response is not None:
            status_cache = "HIT"
            response = cached_response
        else:
            status_cache = "MISS"
            try:
                upstream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                upstream.settimeout(SOCKET_TIMEOUT)
                upstream.connect((WEB_SERVER_IP, WEB_SERVER_HTTP_PORT))
                upstream.sendall(request)

                response = b""
                while True:
                    data = upstream.recv(4096)
                    if not data:
                        break
                    response += data
                upstream.close()

                with cache_lock:
                    cache[cache_key] = response

            except socket.timeout:
                logging.warning("Timeout connecting to web server")
                response = (
                    "HTTP/1.1 504 Gateway Timeout\r\n"
                    "Content-Type: text/html\r\n"
                    "Content-Length: 0\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
            except Exception as e:
                logging.error(f"Error forwarding to web server: {e}")
                response = (
                    "HTTP/1.1 502 Bad Gateway\r\n"
                    "Content-Type: text/html\r\n"
                    "Content-Length: 0\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()

        client_sock.sendall(response)
        logging.info(
            f"[TCP] {client_addr} -> {WEB_SERVER_IP}:{WEB_SERVER_HTTP_PORT} "
            f"cache={status_cache} bytes={len(response)}"
        )

    except socket.timeout:
        logging.warning(f"[TCP] Timeout with client {client_addr}")
    except Exception as e:
        logging.error(f"[TCP] Error with client {client_addr}: {e}")
    finally:
        client_sock.close()


def tcp_proxy_server():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, TCP_PORT))
        s.listen(MAX_CONNECTIONS)
        logging.info(f"[TCP] Proxy listening on {HOST}:{TCP_PORT}")

        while True:
            client_sock, client_addr = s.accept()
            logging.info(f"[TCP] New client {client_addr}")
            t = threading.Thread(
                target=handle_tcp_client,
                args=(client_sock, client_addr),
                daemon=True,
            )
            t.start()


def udp_proxy_server():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind((HOST, UDP_PORT))
        logging.info(f"[UDP] Proxy listening on {HOST}:{UDP_PORT}")

        while True:
            try:
                data, client_addr = s.recvfrom(65535)
                recv_time = time.time()

                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as upstream:
                    upstream.settimeout(SOCKET_TIMEOUT)
                    upstream.sendto(data, (WEB_SERVER_IP, WEB_SERVER_UDP_PORT))
                    try:
                        resp, srv_addr = upstream.recvfrom(65535)
                        send_time = time.time()
                        s.sendto(resp, client_addr)
                        rtt_ms = (send_time - recv_time) * 1000
                        logging.info(
                            f"[UDP] {client_addr} -> {srv_addr} "
                            f"bytes={len(data)} RTT={rtt_ms:.2f} ms"
                        )
                    except socket.timeout:
                        logging.warning(
                            f"[UDP] Timeout waiting echo from server for {client_addr}"
                        )
            except Exception as e:
                logging.error(f"[UDP] Error: {e}")


def main():
    t_udp = threading.Thread(target=udp_proxy_server, daemon=True)
    t_udp.start()
    tcp_proxy_server()


if __name__ == "__main__":
    main()
