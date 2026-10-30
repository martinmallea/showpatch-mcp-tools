#!/usr/bin/env python3
"""Verificador OSC para grandMA3 (listen / send)."""

import argparse
import socket
import struct
import sys
from datetime import datetime


def osc_pad(data):
    """Padding a múltiplo de 4 bytes (OSC 1.0 spec)."""
    remainder = len(data) % 4
    return data if remainder == 0 else data + b"\x00" * (4 - remainder)


def encode_osc_message(address, args):
    if not address.startswith("/"):
        raise ValueError("OSC address must start with '/'")
    payload = osc_pad(address.encode("utf-8"))
    if args:
        type_tag = "," + "s" * len(args)
        payload += osc_pad(type_tag.encode("utf-8"))
        for arg in args:
            payload += osc_pad(str(arg).encode("utf-8"))
    return payload


def _read_osc_string(data, offset):
    end = data.index(b"\x00", offset)
    value = data[offset:end].decode("utf-8", errors="replace")
    consumed = end - offset + 1
    padding = (4 - (consumed % 4)) % 4
    return value, end + 1 + padding


def decode_osc_message(data):
    if len(data) % 4 != 0:
        raise ValueError(f"OSC packet size {len(data)} not multiple of 4")
    address, offset = _read_osc_string(data, 0)
    if not address.startswith("/"):
        raise ValueError("Address must start with '/'")
    result = {"address": address, "args": [], "type_tags": "", "raw_size": len(data)}
    if offset >= len(data) or data[offset:offset + 1] != b",":
        return result
    type_tags, offset = _read_osc_string(data, offset)
    result["type_tags"] = type_tags
    for tag in type_tags[1:]:
        if tag == "s":
            v, offset = _read_osc_string(data, offset)
            result["args"].append(v)
        elif tag == "i":
            result["args"].append(struct.unpack(">i", data[offset:offset + 4])[0])
            offset += 4
        elif tag == "f":
            result["args"].append(struct.unpack(">f", data[offset:offset + 4])[0])
            offset += 4
    return result


def run_listener(bind_ip, port):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind((bind_ip, port))
        print(f"[LISTEN] {bind_ip}:{port} (Ctrl+C para salir)\n")
        try:
            while True:
                data, addr = sock.recvfrom(65535)
                ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                print(f"[{ts}] ← {addr[0]}:{addr[1]} ({len(data)} bytes)")
                try:
                    msg = decode_osc_message(data)
                    print(f"    address  : {msg['address']}")
                    print(f"    type_tags: {msg['type_tags'] or '(none)'}")
                    print(f"    args     : {msg['args']}")
                    print(f"    raw_hex  : {data.hex()}\n")
                except (ValueError, IndexError) as e:
                    print(f"    ⚠️ Framing inválido: {e}")
                    print(f"    raw_hex  : {data.hex()}\n")
        except KeyboardInterrupt:
            print("\n[LISTEN] Detenido.")


def run_sender(ip, port, address, args):
    payload = encode_osc_message(address, args)
    print(f"[SEND] → {ip}:{port}")
    print(f"  address: {address}")
    print(f"  args   : {args}")
    print(f"  bytes  : {len(payload)}")
    print(f"  hex    : {payload.hex()}")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.sendto(payload, (ip, port))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["listen", "send"], required=True)
    parser.add_argument("--ip", default="127.0.0.1")
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--address", default="/gma3/cmd")
    parser.add_argument("--arg", action="append", default=[])
    args = parser.parse_args()
    if args.mode == "listen":
        run_listener(args.bind, args.port)
    else:
        run_sender(args.ip, args.port, args.address, args.arg)


if __name__ == "__main__":
    main()
