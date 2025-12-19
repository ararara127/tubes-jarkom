#!/usr/bin/env python3
"""
Tugas Besar Jaringan Komputer
Client (Laptop B) - Menu Version
"""

import socket
import threading
import argparse
import time
import csv
import os
import webbrowser
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [CLIENT] %(levelname)s: %(message)s"
)

DEFAULT_HOST = "10.60.231.83"
HTTP_SERVER_PORT = 8000
HTTP_PROXY_PORT = 8080
UDP_SERVER_PORT = 9000
UDP_PROXY_PORT = 9090


# =========================
# HTTP FUNCTION
# =========================
def http_request(host, port, path="/", save_as=None, open_browser=False):
    start = time.time()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:

        s.settimeout(8)
        s.connect((host, port))
        req = f"GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n"
        s.sendall(req.encode())

        response = b""
        while True:
            data = s.recv(4096)
            if not data:
                break
            response += data

    duration = time.time() - start
    logging.info(f"Received {len(response)} bytes in {duration:.4f} s")

    try:
        _, body = response.split(b"\r\n\r\n", 1)
    except ValueError:
        body = b""

    if save_as:
        with open(save_as, "wb") as f:
            f.write(body)
        logging.info(f"Saved to {save_as}")
        if open_browser:
            webbrowser.open(f"file://{os.path.abspath(save_as)}")


def http_multi_client(host, port, path="/", num_clients=5):
    def worker(idx):
        http_request(host, port, path)
        logging.info(f"Thread-{idx} selesai")

    threads = []
    for i in range(num_clients):
        t = threading.Thread(target=worker, args=(i + 1,), daemon=True)
        t.start()
        threads.append(t)

    for t in threads:
        t.join()


# =========================
# UDP FUNCTION
# =========================
def udp_qos_test(host, port, csv_file):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(1)

    rtts = []
    start = time.time()

    for seq in range(1, 51):
        payload = f"{seq};{time.time()}".encode()
        sock.sendto(payload, (host, port))
        try:
            data, _ = sock.recvfrom(4096)
            recv_time = time.time()
            rtt = recv_time - start
            rtts.append((seq, rtt))
            logging.info(f"Seq {seq} RTT {rtt*1000:.2f} ms")
        except socket.timeout:
            logging.warning(f"Seq {seq} timeout")

        time.sleep(0.05)

    sock.close()

    if csv_file:
        with open(csv_file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["seq", "rtt_ms"])
            for seq, rtt in rtts:
                writer.writerow([seq, rtt * 1000])
        logging.info(f"CSV disimpan: {csv_file}")


# =========================
# MENU
# =========================
def show_menu():
    print("\n=== CLIENT MENU ===")
    print("1. HTTP Single")
    print("2. HTTP Multi")
    print("3. Browser Mode (Save HTML)")
    print("4. UDP Direct (tanpa proxy)")
    print("5. UDP via Proxy")
    print("0. Keluar")


def main():
    while True:
        show_menu()
        choice = input("Pilih menu: ").strip()

        if choice == "1":
            print("HTTP Single")
            print("1. Direct (8000)")
            print("2. Via Proxy (8080)")
            sub = input("Pilih: ")

            port = HTTP_SERVER_PORT if sub == "1" else HTTP_PROXY_PORT
            http_request(DEFAULT_HOST, port)

        elif choice == "2":
            print("HTTP Multi (5 client via proxy)")
            http_multi_client(DEFAULT_HOST, HTTP_PROXY_PORT)

        elif choice == "3":
            print("Browser Mode")
            http_request(
                DEFAULT_HOST,
                HTTP_PROXY_PORT,
                save_as="hasil.html",
                open_browser=True
            )

        elif choice == "4":
            print("UDP Direct")
            udp_qos_test(DEFAULT_HOST, UDP_SERVER_PORT, "direct.csv")

        elif choice == "5":
            print("UDP via Proxy")
            udp_qos_test(DEFAULT_HOST, UDP_PROXY_PORT, "via_proxy.csv")

        elif choice == "0":
            print("Keluar...")
            break

        else:
            print("Pilihan tidak valid")


if __name__ == "__main__":
    main()
