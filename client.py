#!/usr/bin/env python3
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


def http_request(host, port, path="/", save_as=None, open_browser=False):
    addr = (host, port)
    logging.info(f"Connecting to {addr} ...")
    start = time.time()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect(addr)
        req = f"GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n"
        s.sendall(req.encode())

        response = b""
        while True:
            data = s.recv(4096)
            if not data:
                break
            response += data

    end = time.time()
    duration = end - start
    logging.info(f"Received {len(response)} bytes in {duration:.4f} s")

    try:
        header, body = response.split(b"\r\n\r\n", 1)
    except ValueError:
        header, body = response, b""

    if save_as:
        with open(save_as, "wb") as f:
            f.write(body)
        logging.info(f"HTML body saved to {save_as}")
        if open_browser:
            abs_path = os.path.abspath(save_as)
            webbrowser.open(f"file://{abs_path}")

    return duration, len(response)


def http_worker(host, port, path, idx):
    d, size = http_request(host, port, path)
    logging.info(f"[HTTP-CLIENT-{idx}] done: {size} bytes, {d:.4f} s")


def http_multi_client(host, port, path="/", num_clients=5):
    threads = []
    for i in range(num_clients):
        t = threading.Thread(
            target=http_worker,
            args=(host, port, path, i + 1),
            daemon=True,
        )
        t.start()
        threads.append(t)

    for t in threads:
        t.join()


def udp_qos_test(host, port, num_packets=50, packet_size=100,
                 interval=0.05, csv_file=None):
    addr = (host, port)
    logging.info(
        f"Starting UDP QoS test to {addr} "
        f"(N={num_packets}, size={packet_size}, interval={interval}s)"
    )

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(2.0)

    send_times = {}
    rtt_list = []
    recv_count = 0

    start_test = time.time()

    for seq in range(1, num_packets + 1):
        payload = f"{seq};{time.time()}".encode()
        if len(payload) < packet_size:
            payload = payload + b"x" * (packet_size - len(payload))

        send_time = time.time()
        send_times[seq] = send_time

        try:
            sock.sendto(payload, addr)
        except Exception as e:
            logging.error(f"Error sending packet {seq}: {e}")
            continue

        try:
            sock.settimeout(interval * 2)
            data, server_addr = sock.recvfrom(65535)
            recv_time = time.time()

            try:
                resp_text = data.decode(errors="ignore")
                resp_seq = int(resp_text.split(";", 1)[0])
            except Exception:
                resp_seq = None

            if resp_seq in send_times:
                rtt = recv_time - send_times[resp_seq]
                rtt_list.append(rtt)
                recv_count += 1
                logging.info(
                    f"Recv echo seq={resp_seq} from {server_addr}, "
                    f"RTT={rtt * 1000:.2f} ms"
                )
        except socket.timeout:
            logging.warning(f"Timeout waiting echo for seq={seq}")
        except Exception as e:
            logging.error(f"Error receiving echo for seq={seq}: {e}")

        elapsed = time.time() - send_time
        if elapsed < interval:
            time.sleep(interval - elapsed)

    end_test = time.time()
    total_time = end_test - start_test
    sock.close()

    sent_count = num_packets
    lost_count = sent_count - recv_count
    packet_loss = (lost_count / sent_count) * 100.0

    if rtt_list:
        avg_latency = sum(rtt_list) / len(rtt_list)
        diffs = [
            abs(rtt_list[i] - rtt_list[i - 1])
            for i in range(1, len(rtt_list))
        ]
        jitter = sum(diffs) / len(diffs) if diffs else 0.0
    else:
        avg_latency = 0.0
        jitter = 0.0

    total_bytes = recv_count * packet_size
    throughput_bps = total_bytes * 8 / total_time if total_time > 0 else 0

    logging.info("===== QoS RESULT =====")
    logging.info(f"Sent packets     : {sent_count}")
    logging.info(f"Received packets : {recv_count}")
    logging.info(f"Packet loss      : {packet_loss:.2f} %")
    logging.info(f"Avg latency (RTT): {avg_latency * 1000:.2f} ms")
    logging.info(f"Jitter           : {jitter * 1000:.2f} ms")
    logging.info(f"Throughput       : {throughput_bps:.2f} bps")

    if csv_file:
        with open(csv_file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["seq", "rtt_ms"])
            for i, r in enumerate(rtt_list, start=1):
                writer.writerow([i, r * 1000])
        logging.info(f"RTT detail saved to {csv_file}")

    return {
        "sent": sent_count,
        "received": recv_count,
        "loss_percent": packet_loss,
        "avg_latency_ms": avg_latency * 1000,
        "jitter_ms": jitter * 1000,
        "throughput_bps": throughput_bps,
    }


def main():
    parser = argparse.ArgumentParser(description="Client for HTTP and UDP QoS test")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    p_http = subparsers.add_parser("http", help="Single HTTP request")
    p_http.add_argument("--host", required=True)
    p_http.add_argument("--port", type=int, required=True)
    p_http.add_argument("--path", default="/")
    p_http.add_argument("--save", help="Save HTML body to file")
    p_http.add_argument("--browser", action="store_true", help="Open result in browser")

    p_multi = subparsers.add_parser("http-multi", help="Multiple HTTP clients")
    p_multi.add_argument("--host", required=True)
    p_multi.add_argument("--port", type=int, required=True)
    p_multi.add_argument("--path", default="/")
    p_multi.add_argument("--num", type=int, default=5, help="Number of clients")

    p_udp = subparsers.add_parser("udp-test", help="UDP QoS test")
    p_udp.add_argument("--host", required=True)
    p_udp.add_argument("--port", type=int, required=True)
    p_udp.add_argument("--num", type=int, default=50)
    p_udp.add_argument("--size", type=int, default=100)
    p_udp.add_argument("--interval", type=float, default=0.05)
    p_udp.add_argument("--csv", help="Save RTT data to CSV")

    args = parser.parse_args()

    if args.mode == "http":
        http_request(
            host=args.host,
            port=args.port,
            path=args.path,
            save_as=args.save,
            open_browser=args.browser,
        )
    elif args.mode == "http-multi":
        http_multi_client(
            host=args.host,
            port=args.port,
            path=args.path,
            num_clients=args.num,
        )
    elif args.mode == "udp-test":
        udp_qos_test(
            host=args.host,
            port=args.port,
            num_packets=args.num,
            packet_size=args.size,
            interval=args.interval,
            csv_file=args.csv,
        )


if __name__ == "__main__":
    main()
