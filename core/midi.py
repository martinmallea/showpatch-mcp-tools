"""MIDI mínimo para Windows, sin dependencias.

Para qué: Wolfmix no habla OSC ni HTTP; se controla por MIDI (MK2 y superiores).
Aquí está lo justo para enviar CC y notas por el puerto que elija el operador.

Qué no hace: no enumera nombres de dispositivos (la API de Windows para eso es
una estructura de 200 bytes que cambia entre versiones) ni abre puertos virtuales.
Devuelve índices; el nombre lo pone el operador.

Regla: todo es **dry-run por defecto**. Un mensaje MIDI mal dirigido puede cambiar
el look en vivo, así que enviar es una decisión explícita.
"""

from __future__ import annotations

import ctypes
import os

__all__ = ["cc", "note_on", "note_off", "program_change", "MidiOut", "list_outputs", "available"]

IS_WINDOWS = os.name == "nt"
STATUS_CC = 0xB0
STATUS_NOTE_ON = 0x90
STATUS_NOTE_OFF = 0x80
STATUS_PROGRAM = 0xC0


def _status(base: int, channel: int) -> int:
    if not 0 <= channel <= 15:
        raise ValueError("El canal MIDI va de 0 a 15")
    return base | channel


def _byte(value: int, name: str) -> int:
    number = int(value)
    if not 0 <= number <= 127:
        raise ValueError(f"{name} debe estar entre 0 y 127")
    return number


def cc(channel: int, control: int, value: int) -> int:
    """Mensaje Control Change empaquetado en 3 bytes (status, control, valor)."""
    return (_status(STATUS_CC, channel) << 16) | (_byte(control, "control") << 8) | _byte(value, "value")


def note_on(channel: int, note: int, velocity: int = 100) -> int:
    return (_status(STATUS_NOTE_ON, channel) << 16) | (_byte(note, "note") << 8) | _byte(velocity, "velocity")


def note_off(channel: int, note: int, velocity: int = 0) -> int:
    return (_status(STATUS_NOTE_OFF, channel) << 16) | (_byte(note, "note") << 8) | _byte(velocity, "velocity")


def program_change(channel: int, program: int) -> int:
    return (_status(STATUS_PROGRAM, channel) << 16) | _byte(program, "program")


def available() -> bool:
    return IS_WINDOWS


def _load_winmm():
    if not IS_WINDOWS:
        return None
    return ctypes.WinDLL("winmm")


def list_outputs() -> list[dict]:
    """Índices de salidas MIDI disponibles. Sin nombres: Windows no los da gratis."""
    winmm = _load_winmm()
    if winmm is None:
        return []
    count = winmm.midiOutGetNumDevs()
    return [{"index": index, "name": f"MIDI out {index}"} for index in range(int(count))]


class MidiOut:
    """Salida MIDI. Con ``dry_run=True`` (por defecto) sólo registra lo que enviaría."""

    def __init__(self, device_index: int = 0, *, dry_run: bool = True):
        self.device_index = int(device_index)
        self.dry_run = dry_run
        self.sent: list[int] = []
        self.error: str | None = None
        self._handle = None
        self._winmm = None

        if dry_run:
            return
        winmm = _load_winmm()
        if winmm is None:
            raise RuntimeError("MIDI real sólo está implementado para Windows")
        handle = ctypes.c_void_p()
        result = winmm.midiOutOpen(ctypes.byref(handle), self.device_index, 0, 0, 0)
        if result != 0:
            raise RuntimeError(f"No se pudo abrir la salida MIDI {self.device_index} (código {result})")
        self._winmm = winmm
        self._handle = handle

    def send(self, message: int) -> bool:
        """Envía un mensaje ya empaquetado. Devuelve True si salió (o si era dry-run)."""
        if not isinstance(message, int) or not 0 <= message <= 0xFFFFFF:
            raise ValueError("Mensaje MIDI inválido")
        self.sent.append(message)
        if self.dry_run:
            return True
        if self._winmm is None or self._handle is None:
            self.error = "puerto cerrado"
            return False
        result = self._winmm.midiOutShortMsg(self._handle, ctypes.c_uint(message))
        if result != 0:
            self.error = f"error {result}"
            return False
        return True

    def close(self) -> None:
        if self._winmm is not None and self._handle is not None:
            self._winmm.midiOutClose(self._handle)
            self._handle = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def hex_sent(self) -> list[str]:
        return [f"{message:06X}" for message in self.sent]
