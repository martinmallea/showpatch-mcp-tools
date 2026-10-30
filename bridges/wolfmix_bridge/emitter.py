"""Puente a Wolfmix por MIDI: acciones de consola sin adivinar números.

Wolfmix no habla OSC. Se controla por MIDI, y el mapa lo define el operador en su
equipo. Este puente traduce acciones legibles ("group_3", "dimmer 60") a mensajes
MIDI usando ese mapa.

Por defecto **no envía**: ``MidiOut(dry_run=True)`` registra lo que saldría. Para
enviar de verdad hace falta ``live=True`` y un mapa comprobado.
"""

from __future__ import annotations

from core.midi import MidiOut, cc, note_on
from bridges.wolfmix_bridge.mapping import load_mapping, resolve


class WolfmixBridge:
    def __init__(self, mapping: dict, *, port: int = 0, live: bool = False):
        self.mapping = mapping
        self.midi = MidiOut(port, dry_run=not live)
        self.live = live

    @classmethod
    def from_file(cls, path, *, port: int = 0, live: bool = False) -> "WolfmixBridge":
        return cls(load_mapping(path), port=port, live=live)

    def trigger(self, action: str, value: int = 100) -> int:
        """Dispara una acción mapeada. Devuelve el mensaje MIDI enviado."""
        kind, number, channel = resolve(self.mapping, action)
        if kind == "cc":
            message = cc(channel, number, max(0, min(127, int(value))))
        else:
            message = note_on(channel, number, max(1, min(127, int(value))))
        if not self.midi.send(message):
            raise RuntimeError(f"No se pudo enviar {action}: {self.midi.error}")
        return message

    # --- atajos con nombre de consola

    def group(self, number: int, velocity: int = 100) -> int:
        if not 1 <= number <= 8:
            raise ValueError("Los grupos van de 1 a 8")
        return self.trigger(f"group_{number}", velocity)

    def dimmer(self, percent: float) -> int:
        if not 0 <= percent <= 100:
            raise ValueError("El dimmer va de 0 a 100%")
        return self.trigger("dimmer", round(percent / 100 * 127))

    def go(self) -> int:
        return self.trigger("go", 127)

    def blackout(self) -> int:
        return self.trigger("blackout", 127)

    def close(self) -> None:
        self.midi.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def log(self) -> list[str]:
        return self.midi.hex_sent()
