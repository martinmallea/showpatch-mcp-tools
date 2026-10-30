"""Mapa MIDI de Wolfmix: qué mensaje dispara cada acción.

Wolfmix no publica un mapa fijo: se configura en su propia interfaz. Por eso aquí
no hay números inventados. El puente carga un JSON con el mapa real del operador y,
si una acción no está mapeada, **falla con un mensaje claro** en vez de adivinar.

Formato (`mapping.json`):

    {
      "channel": 0,
      "actions": {
        "group_1":  {"type": "note", "number": 36},
        "dimmer":   {"type": "cc",   "control": 1},
        "go":       {"type": "note", "number": 40}
      }
    }
"""

from __future__ import annotations

import json
from pathlib import Path

ACTIONS = (
    "group_1", "group_2", "group_3", "group_4",
    "group_5", "group_6", "group_7", "group_8",
    "dimmer", "speed", "go", "blackout", "strobe",
)

EXAMPLE = {
    "channel": 0,
    "note": "Rellena esto con el mapa MIDI que hayas configurado en Wolf OS. "
            "Los números de abajo son de ejemplo y NO funcionan por defecto.",
    "actions": {
        "group_1": {"type": "note", "number": 36},
        "group_2": {"type": "note", "number": 37},
        "dimmer": {"type": "cc", "control": 1},
        "speed": {"type": "cc", "control": 2},
        "go": {"type": "note", "number": 40},
        "blackout": {"type": "note", "number": 41},
    },
}


def load_mapping(path: str | Path) -> dict:
    """Carga y valida el mapa. Un JSON roto debe doler ahora, no en el bolo."""
    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(f"No existe el mapa MIDI: {target}")
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("El mapa debe ser un objeto JSON")
    channel = data.get("channel", 0)
    if not isinstance(channel, int) or not 0 <= channel <= 15:
        raise ValueError("'channel' debe ser un entero de 0 a 15")
    actions = data.get("actions")
    if not isinstance(actions, dict) or not actions:
        raise ValueError("Falta 'actions' o está vacío")
    for name, spec in actions.items():
        if not isinstance(spec, dict) or spec.get("type") not in ("cc", "note"):
            raise ValueError(f"Acción {name!r}: 'type' debe ser 'cc' o 'note'")
        key = "control" if spec["type"] == "cc" else "number"
        value = spec.get(key)
        if not isinstance(value, int) or not 0 <= value <= 127:
            raise ValueError(f"Acción {name!r}: '{key}' debe ser 0..127")
    return {"channel": channel, "actions": actions}


def resolve(mapping: dict, action: str) -> tuple[str, int, int]:
    """Devuelve (tipo, número, canal) para una acción, o falla explicando qué falta."""
    spec = (mapping.get("actions") or {}).get(action)
    if spec is None:
        disponibles = ", ".join(sorted(mapping.get("actions") or {})) or "ninguna"
        raise KeyError(f"La acción {action!r} no está en el mapa MIDI. Mapeadas: {disponibles}")
    if spec["type"] == "cc":
        return "cc", int(spec["control"]), int(mapping.get("channel", 0))
    return "note", int(spec["number"]), int(mapping.get("channel", 0))


def write_example(path: str | Path) -> Path:
    target = Path(path)
    target.write_text(json.dumps(EXAMPLE, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return target
