"""Calculadora de color: RGB, CMY, HSV, RGBW, HEX, DMX y porcentajes.

Convenios que hay que dejar escritos porque se confunden a diario:

- **RGB** y **DMX** son lo mismo en 8 bits (0..255). El porcentaje es la lectura
  humana de ese valor: 255 = 100 %.
- **CMY** aquí es la inversa aditiva del RGB (C = 100 − R%), no la mezcla
  sustractiva de filtros reales. Sirve para leer una consola CMY, no para predecir
  el color de un filtro físico. Se dice en la salida.
- **HSV** es útil para "dame un ámbar": H 35, S 100, V 100.
- **RGBW**: se extrae el blanco como mínimo de los tres canales. Es una convención
  (la más común en consolas), no la única posible; un fixture con blanco separado
  puede responder distinto.
"""

from __future__ import annotations

import colorsys

BYTE = 255


def _byte(value, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} debe ser numérico")
    number = int(round(float(value)))
    if not 0 <= number <= BYTE:
        raise ValueError(f"{name} fuera de 0..255: {value!r}")
    return number


def rgb(values) -> tuple[int, int, int]:
    if isinstance(values, str):
        return hex_to_rgb(values)
    if not isinstance(values, (list, tuple)) or len(values) != 3:
        raise ValueError("RGB debe ser una terna [r, g, b]")
    return tuple(_byte(value, "canal") for value in values)  # type: ignore[return-value]


def hex_to_rgb(text: str) -> tuple[int, int, int]:
    value = (text or "").strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        raise ValueError(f"HEX inválido: {text!r}")
    try:
        return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError as exc:
        raise ValueError(f"HEX inválido: {text!r}") from exc


def rgb_to_hex(color) -> str:
    r, g, b = rgb(color)
    return f"#{r:02x}{g:02x}{b:02x}"


def rgb_to_dmx(color) -> dict:
    r, g, b = rgb(color)
    return {
        "r": r,
        "g": g,
        "b": b,
        "percent": [round(r / BYTE * 100, 1), round(g / BYTE * 100, 1), round(b / BYTE * 100, 1)],
    }


def rgb_to_cmy(color) -> tuple[float, float, float]:
    r, g, b = rgb(color)
    return (
        round((1 - r / BYTE) * 100, 1),
        round((1 - g / BYTE) * 100, 1),
        round((1 - b / BYTE) * 100, 1),
    )


def cmy_to_rgb(cmy) -> tuple[int, int, int]:
    if not isinstance(cmy, (list, tuple)) or len(cmy) != 3:
        raise ValueError("CMY debe ser una terna [c, m, y] en porcentaje")
    values = []
    for value in cmy:
        if not 0 <= float(value) <= 100:
            raise ValueError(f"CMY fuera de 0..100: {value!r}")
        values.append(int(round((1 - float(value) / 100) * BYTE)))
    return values[0], values[1], values[2]


def rgb_to_hsv(color) -> tuple[float, float, float]:
    r, g, b = rgb(color)
    hue, saturation, value = colorsys.rgb_to_hsv(r / BYTE, g / BYTE, b / BYTE)
    return round(hue * 360, 1), round(saturation * 100, 1), round(value * 100, 1)


def hsv_to_rgb(hue: float, saturation: float, value: float) -> tuple[int, int, int]:
    if not 0 <= float(hue) <= 360:
        raise ValueError("H va de 0 a 360")
    if not 0 <= float(saturation) <= 100 or not 0 <= float(value) <= 100:
        raise ValueError("S y V van de 0 a 100")
    r, g, b = colorsys.hsv_to_rgb(float(hue) / 360, float(saturation) / 100, float(value) / 100)
    return int(round(r * BYTE)), int(round(g * BYTE)), int(round(b * BYTE))


def rgb_to_rgbw(color) -> tuple[int, int, int, int]:
    """Extrae blanco como mínimo de R,G,B (convención documentada)."""
    r, g, b = rgb(color)
    white = min(r, g, b)
    return r - white, g - white, b - white, white


def rgbw_to_rgb(r, g, b, w) -> tuple[int, int, int]:
    return (
        min(BYTE, _byte(r, "r") + _byte(w, "w")),
        min(BYTE, _byte(g, "g") + _byte(w, "w")),
        min(BYTE, _byte(b, "b") + _byte(w, "w")),
    )


def from_percent(percentages) -> tuple[int, int, int]:
    if not isinstance(percentages, (list, tuple)) or len(percentages) != 3:
        raise ValueError("El porcentaje debe ser una terna [r, g, b]")
    values = []
    for value in percentages:
        if not 0 <= float(value) <= 100:
            raise ValueError(f"Porcentaje fuera de 0..100: {value!r}")
        values.append(int(round(float(value) / 100 * BYTE)))
    return values[0], values[1], values[2]


def convert(color) -> dict:
    """Acepta HEX, [r,g,b], {"percent": [...]}, {"cmy": [...]}, {"hsv": [...]}."""
    if isinstance(color, dict):
        if "hex" in color:
            base = hex_to_rgb(color["hex"])
        elif "rgb" in color:
            base = rgb(color["rgb"])
        elif "percent" in color:
            base = from_percent(color["percent"])
        elif "cmy" in color:
            base = cmy_to_rgb(color["cmy"])
        elif "hsv" in color:
            base = hsv_to_rgb(*color["hsv"])
        else:
            raise ValueError("Formato de color no reconocido")
    else:
        base = rgb(color)

    r, g, b = base
    c, m, y = rgb_to_cmy(base)
    h, s, v = rgb_to_hsv(base)
    wr, wg, wb, white = rgb_to_rgbw(base)
    return {
        "hex": rgb_to_hex(base),
        "rgb": [r, g, b],
        "percent": [round(r / BYTE * 100, 1), round(g / BYTE * 100, 1), round(b / BYTE * 100, 1)],
        "cmy": [c, m, y],
        "hsv": [h, s, v],
        "rgbw": [wr, wg, wb, white],
        "note": "CMY es la inversa del RGB (lectura de consola), no mezcla de filtros reales.",
    }
