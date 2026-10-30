"""Listener OSC para sincronización bidireccional con grandMA3."""

import socket
import threading
import struct
from datetime import datetime


class StateListener:
    def __init__(self, bind_ip="0.0.0.0", port=8001):
        self.bind_ip = bind_ip
        self.port = port
        self.state = {}
        self.lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    @staticmethod
    def _read_osc_string(data, offset):
        end = data.index(b"\x00", offset)
        value = data[offset:end].decode("utf-8", errors="replace")
        consumed = end - offset + 1
        padding = (4 - (consumed % 4)) % 4
        return value, end + 1 + padding

    @classmethod
    def decode_osc(cls, data):
        address, offset = cls._read_osc_string(data, 0)
        args = []
        if offset < len(data) and data[offset:offset + 1] == b",":
            type_tags, offset = cls._read_osc_string(data, offset)
            for tag in type_tags[1:]:
                if tag == "s":
                    v, offset = cls._read_osc_string(data, offset)
                    args.append(v)
                elif tag == "i":
                    args.append(struct.unpack(">i", data[offset:offset + 4])[0])
                    offset += 4
                elif tag == "f":
                    args.append(struct.unpack(">f", data[offset:offset + 4])[0])
                    offset += 4
        return {"address": address, "args": args}

    def _handle_event(self, raw):
        parts = raw.split("|", 5)
        if len(parts) != 6 or parts[0] != "EVENT":
            return
        _, ts, obj, attr, value, fid = parts
        with self.lock:
            self.state[(obj, fid, attr)] = {
                "value": value, "timestamp": ts,
                "received_at": datetime.now().isoformat(),
            }

    def get_state(self):
        with self.lock:
            return dict(self.state)

    def _run(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind((self.bind_ip, self.port))
            sock.settimeout(1.0)
            while not self._stop.is_set():
                try:
                    data, _ = sock.recvfrom(65535)
                except socket.timeout:
                    continue
                except OSError:
                    break
                try:
                    msg = self.decode_osc(data)
                    if msg["address"] == "/mcp/state" and msg["args"]:
                        self._handle_event(msg["args"][0])
                except (ValueError, IndexError):
                    continue

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
