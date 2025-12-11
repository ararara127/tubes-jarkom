#!/usr/bin/env python3
import socket
import threading
import logging
import argparse
import os
import time
from queue import Queue

HOST = "0.0.0.0"
HTTP_PORT = 8000
UDP_PORT = 9000
WWW_ROOT = "./www"
WORKER_COUNT = 5
SOCKET_TIMEOUT = 5  # detik

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WEB-SERVER] %(levelname)s: %(message)s"
)


def build_http_response(status_code=200, body=b"", content_type="text/html"):
    if status_code == 200:
        status_line = "HTTP/1.1 200 OK\r\n"
    elif status_code == 404:
        status_line = "HTTP/1.1 404 Not Found\r\n"
    else:
        status_line = f"HTTP/1.1 {status_code} ERROR\r\n"

    headers = [
        status_line,
        f"Content-Type: {content_type}\r\n",
        f"Content-Length: {len(body)}\r\n",
        "Connection: close\r\n",
        "\r\n",
    ]
    return "".join(headers).encode() + body


def handle_http_client(conn, addr):
    start_time = time.time()
    conn.settimeout(SOCKET_TIMEOUT)

    try:
        request = conn.recv(4096).decode(errors="ignore")
        if not request:
            return

        first_line = request.split("\r\n")[0]
        parts = first_line.split()
        if len(parts) < 2:
            conn.sendall(build_http_response(400, b"Bad Request"))
            return

        method, path = parts[0], parts[1]
        if path == "/":
            path = "/index.html"

        file_path = os.path.join(WWW_ROOT, path.lstrip("/"))
        logging.info(f"[HTTP] Request from {addr[0]}:{addr[1]} -> {method} {path}")

        if os.path.isfile(file_path):
            with open(file_path, "rb") as f:
                body = f.read()

            if file_path.endswith(".html"):
                ctype = "text/html"
            elif file_path.endswith(".jpg") or file_path.endswith(".jpeg"):
                ctype = "image/jpeg"
            elif file_path.endswith(".png"):
                ctype = "image/png"
            elif file_path.endswith(".css"):
                ctype = "text/css"
            else:
                ctype = "application/octet-stream"

            resp = build_http_response(200, body, ctype)
        else:
            body = b"<h1>404 Not Found</h1>"
            resp = build_http_response(404, body)

        conn.sendall(resp)
        duration_ms = (time.time() - start_time) * 1000
        logging.info(
            f"[HTTP] Sent response to {addr[0]}:{addr[1]} "
            f"size={len(resp)} bytes time={duration_ms:.2f} ms"
        )

    except socket.timeout:
        logging.warning(f"[HTTP] Timeout handling client {addr}")
    except Exception as e:
        logging.error(f"[HTTP] Error handling client {addr}: {e}")
    finally:
        conn.close()


def http_server_single_thread():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, HTTP_PORT))
        s.listen(5)
        logging.info(f"[HTTP] Single thread server listening on {HOST}:{HTTP_PORT}")

        while True:
            conn, addr = s.accept()
            logging.info(f"[HTTP] Connection from {addr}")
            handle_http_client(conn, addr)


def worker_thread(queue: Queue):
    while True:
        conn, addr = queue.get()
        if conn is None:
            queue.task_done()
            break
        handle_http_client(conn, addr)
        queue.task_done()


def http_server_threaded():
    work_queue = Queue()
    workers = []

    for _ in range(WORKER_COUNT):
        t = threading.Thread(target=worker_thread, args=(work_queue,), daemon=True)
        t.start()
        workers.append(t)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, HTTP_PORT))
        s.listen(20)
        logging.info(
            f"[HTTP] Threaded server listening on {HOST}:{HTTP_PORT} "
            f"with {WORKER_COUNT} workers"
        )

        try:
            while True:
                conn, addr = s.accept()
                logging.info(f"[HTTP] Connection from {addr}")
                work_queue.put((conn, addr))
        except KeyboardInterrupt:
            logging.info("[HTTP] Shutting down server")
        finally:
            for _ in workers:
                work_queue.put((None, None))
            work_queue.join()


def udp_echo_server():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind((HOST, UDP_PORT))
        logging.info(f"[UDP] Echo server listening on {HOST}:{UDP_PORT}")
        while True:
            try:
                data, addr = s.recvfrom(65535)
                logging.info(f"[UDP] Received {len(data)} bytes from {addr}, echo back")
                s.sendto(data, addr)
            except Exception as e:
                logging.error(f"[UDP] Error: {e}")


def main():
    parser = argparse.ArgumentParser(description="Simple Web Server plus UDP Echo")
    parser.add_argument(
        "--mode",
        choices=["single", "threaded"],
        default="threaded",
        help="HTTP server mode: single or threaded",
    )
    args = parser.parse_args()

    # start UDP server in background thread
    t_udp = threading.Thread(target=udp_echo_server, daemon=True)
    t_udp.start()

    if args.mode == "single":
        http_server_single_thread()
    else:
        http_server_threaded()


if __name__ == "__main__":
    os.makedirs(WWW_ROOT, exist_ok=True)
    index_path = os.path.join(WWW_ROOT, "index.html")
    if not os.path.isfile(index_path):
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(
                "<html><body>"
                "<h1>Selamat Web Server Anda Berhasil!</h1>"
                "<h2>Kelompok Tugas Besar Jaringan Komputer</h2>"
                "<ul>"
                "<li>Ahmad Refi Widi Katibin- 103012300231</li>"
                "<li>Azzahra Indah - 103012300238</li>"
                "</ul>"
                "</body></html>"
            )
    main()
