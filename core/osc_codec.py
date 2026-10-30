"""Codec OSC 1.0 mínimo, sin dependencias externas.

Existe para que el servidor MCP, los emisores y las herramientas compartan UNA
sola implementación del framing. El prototipo construía el type-tag string a
mano (`b',' + b's'*n + b'\x00'`) y funcionaba por casualidad; aquí el padding se
aplica siempre con `osc_pad`, que es la regla real de OSC 1.0: toda cadena va
terminada en NUL y rellenada hasta múltiplo de 4 bytes.

Referencia: OSC 1.0 (CNMAT) — "OSC-string": secuencia de caracteres ASCII
terminada en NUL, seguida de 1 a 3 bytes NUL hasta alinear a 4.
"""

from __future__ import annotations

import socket
import struct

__all__ = [
    "osc_pad",
    "encode_message",
    "decode_message",
    "send_message",
    "ALLOWED_ADDRESS_PREFIXES",
]

# Direcciones que este puente acepta. Nunca DMX crudo: la IA manipula el
# Command Line de la consola, no valores de canal (jitter y latencia rompen el
# ritmo del show).
#
# El prefijo OSC de grandMA3 es configurable en Menu → In & Out → OSC: el valor
# por defecto es `gma3`, pero herramientas del mercado usan `grandMA3` (G3Link)
# o el que decida el operador. Aceptamos los dos habituales en lugar de imponer
# uno: rechazar una dirección válida por un prefijo es un fallo silencioso.
ALLOWED_ADDRESS_PREFIXES = ("/gma3/", "/grandMA3/", "/chamsys/", "/mcp/")


def osc_pad(data: bytes) -> bytes:
    """Rellena con NUL hasta el siguiente múltiplo de 4 bytes."""
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("osc_pad espera bytes")
    remainder = len(data) % 4
    return bytes(data) if remainder == 0 else bytes(data) + b"\x00" * (4 - remainder)


def _osc_string(text: str) -> bytes:
    """Codifica una cadena OSC: texto + NUL y después padding a múltiplo de 4.

    El terminador NO es opcional: si la cadena mide un múltiplo de 4 (p. ej. el
    type-tag ",sif"), `osc_pad` por sí solo no añadiría ningún byte y el
    decodificador se comería el argumento siguiente.
    """
    return osc_pad(text.encode("utf-8") + b"\x00")


def _encode_arg(arg) -> tuple[bytes, str]:
    if isinstance(arg, bool):
        # bool es subclase de int: se trata antes para no emitir 'i'.
        raise TypeError("OSC no tiene tipo booleano; usa int 0/1")
    if isinstance(arg, int):
        return struct.pack(">i", arg), "i"
    if isinstance(arg, float):
        return struct.pack(">f", arg), "f"
    return _osc_string(str(arg)), "s"


def encode_message(address: str, args=()) -> bytes:
    """Construye un mensaje OSC con type tags deducidos de los argumentos."""
    if not isinstance(address, str) or not address.startswith("/"):
        raise ValueError("La dirección OSC debe empezar por '/'")
    if any(ch in address for ch in "\x00 ,#*?[]{}\n\r"):
        raise ValueError(f"Dirección OSC con caracteres no válidos: {address!r}")

    payload = _osc_string(address)
    if not args:
        return payload + _osc_string(",")

    encoded: list[bytes] = []
    tags = ","
    for arg in args:
        blob, tag = _encode_arg(arg)
        encoded.append(blob)
        tags += tag
    payload += _osc_string(tags)
    for blob in encoded:
        payload += blob
    return payload


def _read_string(data: bytes, offset: int) -> tuple[str, int]:
    end = data.index(b"\x00", offset)
    text = data[offset:end].decode("utf-8", errors="replace")
    consumed = end - offset + 1
    return text, end + 1 + ((4 - consumed % 4) % 4)


def decode_message(data: bytes) -> dict:
    """Decodifica un datagrama OSC. Lanza ValueError si el framing es inválido."""
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("decode_message espera bytes")
    data = bytes(data)
    if not data or len(data) % 4 != 0:
        raise ValueError(f"Tamaño de paquete OSC inválido: {len(data)} bytes")
    address, offset = _read_string(data, 0)
    if not address.startswith("/"):
        raise ValueError("La dirección OSC debe empezar por '/'")

    result = {"address": address, "args": [], "type_tags": "", "raw_size": len(data)}
    if offset >= len(data) or data[offset : offset + 1] != b",":
        return result

    type_tags, offset = _read_string(data, offset)
    result["type_tags"] = type_tags
    for tag in type_tags[1:]:
        if tag == "s":
            value, offset = _read_string(data, offset)
            result["args"].append(value)
        elif tag == "i":
            if offset + 4 > len(data):
                raise ValueError("Argumento 'i' truncado")
            result["args"].append(struct.unpack(">i", data[offset : offset + 4])[0])
            offset += 4
        elif tag == "f":
            if offset + 4 > len(data):
                raise ValueError("Argumento 'f' truncado")
            result["args"].append(struct.unpack(">f", data[offset : offset + 4])[0])
            offset += 4
        else:
            raise ValueError(f"Type tag no soportado: {tag!r}")
    return result


def send_message(
    ip: str,
    port: int,
    address: str,
    args=(),
    *,
    dry_run: bool = True,
    timeout: float = 1.0,
) -> dict:
    """Envía (o simula) un mensaje OSC.

    UDP no tiene ACK: un `sent=True` significa "el datagrama salió de la NIC",
    no "la consola lo aplicó". La confirmación real se obtiene con el listener
    de estado (`core.osc_listener`) o con el plugin Lua residente.
    """
    if not isinstance(port, int) or not (1 <= port <= 65535):
        raise ValueError(f"Puerto inválido: {port!r}")
    payload = encode_message(address, args)
    info = {
        "target": f"{ip}:{port}",
        "address": address,
        "args": list(args),
        "bytes": len(payload),
        "hex": payload.hex(),
        "dry_run": dry_run,
        "sent": False,
        "acknowledged": False,
    }
    if dry_run:
        return info

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            sock.sendto(payload, (ip, port))
        info["sent"] = True
    except OSError as exc:  # incluye timeout, red inalcanzable, DNS
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info
