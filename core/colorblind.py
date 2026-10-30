"""Daltonismo aplicado a iluminación: simular, nombrar y detectar confusiones.

Tres usos reales:

1. **Simular** cómo ve el operador (protanopía, deuteranopía, tritanopía) para no
   aprobar un look que sólo funciona con visión típica.
2. **Nombrar** el color ("ámbar", no #ff9a3c) para que la interfaz no dependa sólo
   del matiz.
3. **Detectar pares confundibles**: dos colores distintos que, simulados, se
   vuelven casi iguales. Eso es lo que hace que un técnico no distinga "rojo" de
   "verde" en la paleta.

La simulación trabaja en luz lineal (sRGB → lineal → matriz → sRGB). Aplicar la
matriz directamente sobre los bytes es la aproximación barata y desafina en
medios tonos.
"""

from __future__ import annotations

from core.color_calc import rgb as _rgb

__all__ = [
    "MODES",
    "simulate",
    "simulate_all",
    "name_color",
    "luminance",
    "contrast_ratio",
    "confusable_pairs",
    "report",
]

MODES = {
    "protanopia": ((0.567, 0.433, 0.0), (0.558, 0.442, 0.0), (0.0, 0.242, 0.758)),
    "deuteranopia": ((0.625, 0.375, 0.0), (0.700, 0.300, 0.0), (0.0, 0.300, 0.700)),
    "tritanopia": ((0.950, 0.050, 0.0), (0.0, 0.433, 0.567), (0.0, 0.475, 0.525)),
}


def _to_linear(channel: int) -> float:
    value = channel / 255
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _to_srgb(value: float) -> int:
    value = max(0.0, min(1.0, value))
    encoded = 12.92 * value if value <= 0.0031308 else 1.055 * (value ** (1 / 2.4)) - 0.055
    return int(round(encoded * 255))


def simulate(color, mode: str = "deuteranopia") -> tuple[int, int, int]:
    """Color aproximado que percibe alguien con esa dicromacia."""
    if mode not in MODES:
        raise ValueError(f"Modo no soportado: {mode}. Usa {sorted(MODES)}")
    r, g, b = _rgb(color)
    linear = (_to_linear(r), _to_linear(g), _to_linear(b))
    matrix = MODES[mode]
    out = [sum(row[i] * linear[i] for i in range(3)) for row in matrix]
    return _to_srgb(out[0]), _to_srgb(out[1]), _to_srgb(out[2])


def simulate_all(color) -> dict:
    return {mode: list(simulate(color, mode)) for mode in MODES}


def _hsv(color) -> tuple[float, float, float]:
    import colorsys

    r, g, b = _rgb(color)
    hue, saturation, value = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    return hue * 360, saturation * 100, value * 100


def name_color(color) -> str:
    """Nombre en español, útil cuando el color no puede ser la única señal."""
    hue, saturation, value = _hsv(color)
    if value < 10:
        return "negro"
    if saturation < 12:
        return "blanco" if value > 92 else "gris"
    if 15 <= hue < 40:
        return "naranja"
    if 40 <= hue < 65:
        return "ámbar"
    if 65 <= hue < 90:
        return "amarillo"
    if 90 <= hue < 150:
        return "verde"
    if 150 <= hue < 200:
        return "verde cian"
    if 200 <= hue < 235:
        return "cian"
    if 235 <= hue < 260:
        return "azul"
    if 260 <= hue < 290:
        return "violeta"
    if 290 <= hue < 330:
        return "magenta"
    if 330 <= hue < 345:
        return "rosa"
    return "rojo"


def luminance(color) -> float:
    r, g, b = _rgb(color)
    return 0.2126 * _to_linear(r) + 0.7152 * _to_linear(g) + 0.0722 * _to_linear(b)


def contrast_ratio(first, second) -> float:
    """Contraste WCAG entre dos colores (1 a 21)."""
    a, b = luminance(first), luminance(second)
    lighter, darker = max(a, b), min(a, b)
    return round((lighter + 0.05) / (darker + 0.05), 2)


def _distance(first, second) -> float:
    return sum((x - y) ** 2 for x, y in zip(first, second)) ** 0.5


def confusable_pairs(colors: list, mode: str = "deuteranopia", threshold: float = 40.0) -> list[dict]:
    """Pares que se distinguen hoy y se confunden con esa dicromacia."""
    if mode not in MODES:
        raise ValueError(f"Modo no soportado: {mode}")
    prepared = [_rgb(color) for color in colors]
    pairs = []
    for i in range(len(prepared)):
        for j in range(i + 1, len(prepared)):
            original = _distance(prepared[i], prepared[j])
            seen = _distance(simulate(prepared[i], mode), simulate(prepared[j], mode))
            if original > threshold and seen < threshold:
                pairs.append(
                    {
                        "indices": [i, j],
                        "original_distance": round(original, 1),
                        "simulated_distance": round(seen, 1),
                        "names": [name_color(prepared[i]), name_color(prepared[j])],
                    }
                )
    return pairs


def report(colors: list) -> dict:
    """Informe de accesibilidad de una paleta."""
    prepared = [_rgb(color) for color in colors]
    return {
        "colors": [
            {"rgb": list(color), "name": name_color(color), "simulated": simulate_all(color), "luminance": round(luminance(color), 3)}
            for color in prepared
        ],
        "confusable": {mode: confusable_pairs(prepared, mode) for mode in MODES},
        "advice": "Si dos colores se confunden, añade forma, posición o etiqueta; no sólo un tono distinto.",
    }
