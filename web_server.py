#!/usr/bin/env python3
"""
web_server.py

Web Server sederhana untuk Tugas Besar Jaringan Komputer:
1) HTTP file server (TCP) pada port 8000
   - mode single (1 client per waktu)
   - mode threaded (pakai thread pool)
2) UDP Echo server pada port 9000
   - balikin payload yang diterima (buat uji QoS/RTT dari client)

Cara run (Laptop A):
- HTTP single:
  python web_server.py --mode single --host 0.0.0.0 --http-port 8000 --www www

- HTTP threaded:
  python web_server.py --mode threaded --host 0.0.0.0 --http-port 8000 --www www --workers 5

Catatan:
- Kalau kalian akses dari Laptop B, host yang dipakai di client adalah IP Laptop A (contoh: 192.168.1.3)
- File HTML taruh di folder www (default: www/index.html)
"""

import os
import socket
import threading
import argparse
import logging
import mimetypes
import time
from queue import Queue

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WEB-SERVER] %(levelname)s: %(message)s"
)

# =========================================================
# Bagian A: util untuk HTTP
# =========================================================

def read_http_request(conn: socket.socket) -> bytes:
    """
    Baca request HTTP dari client sampai header selesai (\r\n\r\n).
    Return: raw bytes request.
    """
    conn.settimeout(5.0)
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(4096)
        if not chunk:
            break
        data += chunk
        if len(data) > 64 * 1024:
            break
    return data


def parse_http_request(raw: bytes):
    """
    Parsing minimal request HTTP.
    Return: (method, path, version)
    Jika gagal, return (None, None, None)
    """
    try:
        text = raw.decode(errors="ignore")
        lines = text.split("\r\n")
        request_line = lines[0].strip()
        parts = request_line.split()
        if len(parts) != 3:
            return None, None, None
        method, path, version = parts
        return method.upper(), path, version
    except Exception:
        return None, None, None


def safe_join_www(www_root: str, url_path: str) -> str:
    """
    Ubah URL path menjadi path file lokal yang aman (mencegah path traversal).
    Contoh:
      "/" -> "index.html"
      "/index.html" -> "index.html"
      "/assets/a.png" -> "assets/a.png"
    """
    # Buang query string kalau ada: "/index.html?x=1" -> "/index.html"
    clean = url_path.split("?", 1)[0]

    # Normalisasi
    clean = clean.lstrip("/")
    if clean == "":
        clean = "index.html"

    # Gabungkan dan normalkan
    joined = os.path.normpath(os.path.join(www_root, clean))

    # Pastikan masih di dalam folder www_root
    www_abs = os.path.abspath(www_root)
    joined_abs = os.path.abspath(joined)
    if not joined_abs.startswith(www_abs):
        return ""  # invalid
    return joined_abs


def build_http_response(status_code: int, body: bytes, content_type: str = "text/html; charset=utf-8") -> bytes:
    """
    Bikin response HTTP sederhana.
    """
    reason = {
        200: "OK",
        400: "Bad Request",
        403: "Forbidden",
        404: "Not Found",
        405: "Method Not Allowed",
        500: "Internal Server Error",
    }.get(status_code, "OK")

    headers = [
        f"HTTP/1.1 {status_code} {reason}",
        f"Content-Length: {len(body)}",
        f"Content-Type: {content_type}",
        "Connection: close",
        "\r\n"
    ]
    header_bytes = "\r\n".join(headers).encode()
    return header_bytes + body


def guess_content_type(file_path: str) -> str:
    """
    Tebak Content-Type berdasarkan ekstensi file.
    """
    ctype, _ = mimetypes.guess_type(file_path)
    if not ctype:
        ctype = "application/octet-stream"
    return ctype


def handle_http_client(conn: socket.socket, addr, www_root: str):
    """
    Handler 1 koneksi TCP:
    - baca request
    - hanya support GET
    - ambil file dari www_root
    - kirim response
    """
    start = time.time()
    try:
        raw = read_http_request(conn)
        method, path, _version = parse_http_request(raw)

        if not method or not path:
            body = b"<h1>400 Bad Request</h1>"
            conn.sendall(build_http_response(400, body))
            return

        if method != "GET":
            body = b"<h1>405 Method Not Allowed</h1>"
            conn.sendall(build_http_response(405, body))
            return

        file_path = safe_join_www(www_root, path)
        if file_path == "":
            body = b"<h1>403 Forbidden</h1>"
            conn.sendall(build_http_response(403, body))
            return

        if not os.path.exists(file_path) or not os.path.isfile(file_path):
            body = b"<h1>404 Not Found</h1>"
            conn.sendall(build_http_response(404, body))
            return

        with open(file_path, "rb") as f:
            body = f.read()

        ctype = guess_content_type(file_path)
        conn.sendall(build_http_response(200, body, ctype))

        elapsed = (time.time() - start) * 1000.0
        logging.info(f"[HTTP] Request from {addr[0]}:{addr[1]} -> GET {path}")
        logging.info(f"[HTTP] Sent response to {addr[0]}:{addr[1]} file={os.path.basename(file_path)} size={len(body)} bytes time={elapsed:.2f} ms")

    except Exception as e:
        logging.error(f"[HTTP] Error handling client {addr}: {e}")
        try:
            body = b"<h1>500 Internal Server Error</h1>"
            conn.sendall(build_http_response(500, body))
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


# =========================================================
# Bagian B: HTTP server (single dan threaded)
# =========================================================

def http_server_single(host: str, port: int, www_root: str):
    """
    Mode single:
    - accept() satu-satu
    - handle langsung di main thread
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        # Reuse port supaya gampang restart
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        s.bind((host, port))
        s.listen(50)

        logging.info(f"[HTTP] Single server listening on {host}:{port} (www={www_root})")

        while True:
            conn, addr = s.accept()
            logging.info(f"[HTTP] Connection from {addr}")
            handle_http_client(conn, addr, www_root)


def http_worker_loop(job_queue: Queue, www_root: str):
    """
    Loop worker thread:
    - ambil job dari queue
    - job isinya (conn, addr)
    """
    while True:
        conn, addr = job_queue.get()
        try:
            handle_http_client(conn, addr, www_root)
        finally:
            job_queue.task_done()


def http_server_threaded(host: str, port: int, www_root: str, workers: int = 5):
    """
    Mode threaded:
    - main thread hanya accept() lalu masukin (conn, addr) ke queue
    - worker threads yang proses request
    """
    job_queue = Queue()

    # Start thread pool
    for i in range(workers):
        t = threading.Thread(target=http_worker_loop, args=(job_queue, www_root), daemon=True)
        t.start()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        s.bind((host, port))
        s.listen(50)

        logging.info(f"[HTTP] Threaded server listening on {host}:{port} with {workers} workers (www={www_root})")

        while True:
            conn, addr = s.accept()
            job_queue.put((conn, addr))


# =========================================================
# Bagian C: UDP Echo server (untuk pengujian QoS/RTT)
# =========================================================

def udp_echo_server(host: str, port: int):
    """
    UDP Echo server:
    - terima datagram
    - kirim balik ke pengirim (echo)
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind((host, port))
        logging.info(f"[UDP] Echo server listening on {host}:{port}")

        while True:
            data, addr = s.recvfrom(65535)
            # Log singkat biar ga spam banget, tapi masih kebaca
            logging.info(f"[UDP] Received {len(data)} bytes from {addr}, echo back")
            s.sendto(data, addr)


# =========================================================
# Bagian D: main() + argumen CLI
# =========================================================

def build_parser() -> argparse.ArgumentParser:
    """
    Parser CLI biar gampang run dan gampang ditulis di laporan.
    """
    parser = argparse.ArgumentParser(
        description="Web Server (HTTP single/threaded) + UDP Echo server for Final Project"
    )
    parser.add_argument("--mode", choices=["single", "threaded"], default="single",
                        help='Mode HTTP server. "single" untuk 1 koneksi per waktu, "threaded" untuk concurrent.')
    parser.add_argument("--host", default="0.0.0.0", help="Bind address. Pakai 0.0.0.0 biar bisa diakses dari laptop lain.")
    parser.add_argument("--http-port", type=int, default=8000, help="Port HTTP server (TCP). Default 8000.")
    parser.add_argument("--udp-port", type=int, default=9000, help="Port UDP echo server. Default 9000.")
    parser.add_argument("--www", default="www", help="Folder root untuk file web (default: www).")
    parser.add_argument("--workers", type=int, default=5, help="Jumlah worker thread saat mode threaded.")

    return parser


def print_quick_commands():
    """
    Ini cuma buat ngingetin sintaks run yang umum.
    Bisa kalian copy ke laporan bagian 'Proses Pengujian'.
    """
    logging.info("===== QUICK COMMANDS (Laptop A) =====")
    logging.info('HTTP single   : python web_server.py --mode single --host 0.0.0.0 --http-port 8000 --www www')
    logging.info('HTTP threaded : python web_server.py --mode threaded --host 0.0.0.0 --http-port 8000 --www www --workers 5')
    logging.info('UDP echo port : default 9000 (jalan otomatis bareng HTTP)')
    logging.info("=====================================")


def main():
    parser = build_parser()
    args = parser.parse_args()

    # Pastikan folder www ada
    www_root = args.www
    os.makedirs(www_root, exist_ok=True)

    # Info singkat command yang sering dipakai
    print_quick_commands()

    # UDP echo server jalan di thread sendiri supaya barengan sama HTTP
    udp_thread = threading.Thread(
        target=udp_echo_server,
        args=(args.host, args.udp_port),
        daemon=True
    )
    udp_thread.start()

    # Jalankan HTTP sesuai mode
    if args.mode == "single":
        http_server_single(args.host, args.http_port, www_root)
    else:
        http_server_threaded(args.host, args.http_port, www_root, workers=args.workers)


if __name__ == "__main__":
    main()
