"""Monitor DMX por red: escucha Art-Net y sACN y muestra qué se está moviendo.

Para qué sirve, en una frase: saber si la consola **emite**, si el cableado de red
llega y qué canales están vivos, sin comprar un ArtNetominator ni interponerse en
la línea DMX.

Qué hace y qué no:

- **Escucha** (pasivo). No emite DMX, no cambia nada, no interfiere.
- Entiende **Art-Net** (UDP 6454) y **sACN/E1.31** (UDP 5568).
- Calcula fps por universo, canales activos, pico y último paquete.
- Puede **grabar** los frames recibidos en memoria para revisarlos (`record`).

Límite honesto: sACN por multicast requiere unirse al grupo (239.255.x.x). Aquí se
une sólo a los universos que se pidan; si la consola emite por unicast o Art-Net
no hace falta nada.
"""

from __future__ import annotations

import socket
import struct
import threading
import time
from dataclasses import dataclass, field

DMX_SIZE = 512
ARTNET_PORT = 6454
SACN_PORT = 5568


@dataclass
class Frame:
    universe: int
    channels: tuple[int, ...]
    source: str
    protocol: str
    sequence: int = 0
    received_at: float = field(default_factory=time.time)


def parse_artnet(data: bytes, source: str = "") -> Frame | None:
    """ArtDmx: 'Art-Net\\0' + opcode 0x5000 + net/subuni + longitud + datos."""
    if len(data) < 18 or data[:8] != b"Art-Net\x00":
        return None
    opcode = data[8] | (data[9] << 8)
    if opcode != 0x5000:
        return None
    sequence = data[12]
    sub_uni = data[14]
    net = data[15]
    length = (data[16] << 8) | data[17]
    if length == 0 or length > DMX_SIZE:
        return None
    payload = data[18 : 18 + length]
    if len(payload) < length:
        return None
    channels = tuple(payload) + (0,) * (DMX_SIZE - length)
    universe = ((net & 0x7F) << 8) | (sub_uni & 0x0F)
    return Frame(universe=universe, channels=channels, source=source, protocol="artnet", sequence=sequence)


def parse_sacn(data: bytes, source: str = "") -> Frame | None:
    """E1.31: preamble + ACN identifier, y el universo en el offset 113."""
    if len(data) < 126 or data[:2] != b"\x00\x10":
        return None
    if data[4:16] != b"ASC-E1.17\x00\x00\x00":
        return None
    universe = (data[113] << 8) | data[114]
    count = ((data[123] & 0x0F) << 8) | data[124]
    if count < 1 or count > DMX_SIZE + 1:
        return None
    start_code = data[125]
    if start_code != 0x00:
        return None  # sólo DMX, no RDM ni textos
    slots = data[126 : 126 + count - 1]
    channels = tuple(slots) + (0,) * (DMX_SIZE - len(slots))
    return Frame(
        universe=universe,
        channels=channels,
        source=source,
        protocol="sacn",
        sequence=data[111],
    )


class DmxMonitor:
    """Estado vivo: último frame por universo, fps, y grabación opcional."""

    def __init__(self, *, max_universes: int = 64):
        self._lock = threading.Lock()
        self._latest: dict[int, Frame] = {}
        self._arrivals: dict[int, list[float]] = {}
        self.frames_total = 0
        self.errors: list[str] = []
        self._recording: list[Frame] | None = None
        self._record_started = 0.0
        self._max_universes = max_universes

    # --- entrada

    def feed(self, data: bytes, source: str = "") -> Frame | None:
        frame = parse_artnet(data, source) or parse_sacn(data, source)
        if frame is None:
            return None
        now = time.time()
        with self._lock:
            self.frames_total += 1
            self._latest[frame.universe] = frame
            arrivals = self._arrivals.setdefault(frame.universe, [])
            arrivals.append(now)
            self._arrivals[frame.universe] = [t for t in arrivals if now - t <= 1.0]
            if self._recording is not None and len(self._recording) < 50_000:
                self._recording.append(frame)
        return frame

    # --- grabación

    def record_start(self) -> None:
        with self._lock:
            self._recording = []
            self._record_started = time.time()

    def record_stop(self) -> dict:
        with self._lock:
            frames = self._recording or []
            seconds = max(0.0, time.time() - self._record_started) if self._recording is not None else 0.0
            self._recording = None
        universes = sorted({frame.universe for frame in frames})
        return {"frames": len(frames), "seconds": round(seconds, 2), "universes": universes}

    def recording(self) -> dict:
        with self._lock:
            on = self._recording is not None
            return {
                "on": on,
                "frames": len(self._recording or []),
                "seconds": round(max(0.0, time.time() - self._record_started), 2) if on else 0.0,
            }

    # --- salida

    def snapshot(self, *, full: bool = False) -> dict:
        now = time.time()
        with self._lock:
            universes = []
            for universe, frame in sorted(self._latest.items()):
                active = [i + 1 for i, value in enumerate(frame.channels) if value]
                universes.append(
                    {
                        "universe": universe,
                        "protocol": frame.protocol,
                        "source": frame.source,
                        "fps": len(self._arrivals.get(universe, [])),
                        "active": len(active),
                        "peak": max(frame.channels) if frame.channels else 0,
                        "age": round(now - frame.received_at, 2),
                        "channels": list(frame.channels) if full else None,
                    }
                )
            return {
                "universes": universes,
                "frames_total": self.frames_total,
                "recording": {
                    "on": self._recording is not None,
                    "frames": len(self._recording or []),
                    "seconds": round(max(0.0, time.time() - self._record_started), 2)
                    if self._recording is not None
                    else 0.0,
                },
                "errors": list(self.errors),
                "listening": {"artnet": ARTNET_PORT, "sacn": SACN_PORT},
            }


def _listen_udp(monitor: DmxMonitor, port: int, *, join_universes: tuple[int, ...] = ()) -> socket.socket | None:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", port))
    except OSError as exc:
        monitor.errors.append(f"no se pudo abrir UDP {port}: {exc}")
        return None

    for universe in join_universes:
        try:
            group = socket.inet_aton(f"239.255.{universe >> 8}.{universe & 0xFF}")
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, group + socket.inet_aton("0.0.0.0"))
        except OSError as exc:
            monitor.errors.append(f"multicast universo {universe}: {exc}")

    def loop() -> None:
        while True:
            try:
                data, address = sock.recvfrom(2048)
            except OSError:
                return
            monitor.feed(data, source=address[0])

    threading.Thread(target=loop, daemon=True, name=f"dmx-{port}").start()
    return sock


def start_listeners(monitor: DmxMonitor, *, join_universes: tuple[int, ...] = ()) -> list[socket.socket]:
    """Arranca los dos puertos. Devuelve los sockets vivos (para cerrarlos en tests)."""
    sockets = []
    for port, join in ((ARTNET_PORT, ()), (SACN_PORT, join_universes)):
        sock = _listen_udp(monitor, port, join_universes=join)
        if sock is not None:
            sockets.append(sock)
    return sockets


def artnet_packet(universe: int, channels: list[int], sequence: int = 1) -> bytes:
    """Construye un ArtDmx válido. Existe para pruebas y para simular tráfico."""
    net = (universe >> 8) & 0x7F
    sub = universe & 0x0F
    payload = bytes(channels[:DMX_SIZE])
    header = b"Art-Net\x00" + struct.pack("<H", 0x5000) + struct.pack(">H", 14)
    header += bytes([sequence & 0xFF, 0, sub, net])
    header += struct.pack(">H", len(payload))
    return header + payload


def sacn_packet(universe: int, channels: list[int], sequence: int = 1, source_name: str = "test") -> bytes:
    """Construye un E1.31 de datos. Sólo para pruebas y simulador."""
    slots = bytes(channels[:DMX_SIZE])
    count = len(slots) + 1
    packet = bytearray(b"\x00\x10\x00\x00ASC-E1.17\x00\x00\x00")
    packet += struct.pack(">H", 0x7000 | 0x000E)
    packet += struct.pack(">I", 0x00000004)
    packet += bytes(16)  # CID
    packet += struct.pack(">H", 0x7000 | 0x0026)
    packet += struct.pack(">I", 0x00000002)
    packet += source_name.encode("utf-8")[:63].ljust(64, b"\x00")
    packet += bytes([100, 0, 0, sequence & 0xFF, 0])
    packet += struct.pack(">H", universe)
    packet += struct.pack(">H", 0x7000 | 0x000B)
    packet += bytes([0x02, 0xA1])
    packet += struct.pack(">H", 0x0000)
    packet += struct.pack(">H", 0x0001)
    packet += struct.pack(">H", count)
    packet += b"\x00"  # start code
    packet += slots
    return bytes(packet)
