"""Fingerprinting heurístico de robótica DMX desconocida (Fase 2).

Problema real: un cliente trae cabezas clonadas chinas sin manual, sin perfil
de librería y sin etiquetas en el patch. Hay que deducir qué canal hace qué.

No hay ML ni dependencias: estadística descriptiva sobre una secuencia de
fotogramas DMX (snapshots de 512 canales, 0..255). El resultado es una hipótesis
puntuada, no una verdad: por eso cada rol lleva su evidencia y hay `warnings`.

Convenio de índices: los roles se expresan en número de canal DMX (1..512), que
es lo que el técnico ve en la consola. `pan_fine` es pan+1 en pares de 16 bits.
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence

__all__ = ["fingerprint", "analyze_raw_dmx_stream", "DMX_CHANNELS"]

DMX_CHANNELS = 512

# Perfiles de referencia para puntuar candidatos. Ampliable sin tocar la lógica:
# sólo se comparan footprint y patrón de roles detectado.
PROFILES: tuple[dict, ...] = (
    {"model": "ClayPaky Sharpy", "channels": 16, "expects_pan_tilt": True, "expects_dimmer": True},
    {"model": "Robe Pointe", "channels": 31, "expects_pan_tilt": True, "expects_dimmer": True},
    {"model": "Beam 230W (clon)", "channels": 12, "expects_pan_tilt": True, "expects_dimmer": True},
    {"model": "Beam 7R (clon)", "channels": 16, "expects_pan_tilt": True, "expects_dimmer": True},
    {"model": "Wash 19x15 (clon)", "channels": 24, "expects_pan_tilt": True, "expects_dimmer": True},
    {"model": "LED PAR 7ch", "channels": 7, "expects_pan_tilt": False, "expects_dimmer": True},
)


def _coerce_frames(channels) -> tuple[list[list[int]], list[str]]:
    """Normaliza la entrada a lista de fotogramas de 512 ints, sin reventar."""
    warnings: list[str] = []
    if channels is None:
        return [], ["Entrada vacía: no hay fotogramas que analizar."]

    if isinstance(channels, (bytes, bytearray)):
        frames = [list(channels)]
    elif isinstance(channels, (list, tuple)) and channels and isinstance(channels[0], (int, float)):
        frames = [list(channels)]
    elif isinstance(channels, Iterable):
        frames = [list(frame) for frame in channels if frame is not None]
    else:
        return [], [f"Tipo de entrada no soportado: {type(channels).__name__}"]

    clean: list[list[int]] = []
    for frame in frames:
        values = []
        for value in frame:
            try:
                number = int(round(float(value)))
            except (TypeError, ValueError):
                number = 0
            values.append(max(0, min(255, number)))
        if len(values) != DMX_CHANNELS:
            warnings.append(
                f"Fotograma de {len(values)} canales; se normaliza a {DMX_CHANNELS}."
            )
            values = (values + [0] * DMX_CHANNELS)[:DMX_CHANNELS]
        clean.append(values)
    return clean, warnings


def _series(frames: Sequence[Sequence[int]], index: int) -> list[int]:
    return [frame[index] for frame in frames]


def _range(values: Sequence[int]) -> int:
    return max(values) - min(values) if values else 0


def _monotonic_score(values: Sequence[int]) -> float:
    """1.0 = estrictamente monótona; 0.0 = sin tendencia o plana."""
    diffs = [b - a for a, b in zip(values, values[1:]) if b != a]
    if not diffs:
        return 0.0
    positive = sum(1 for d in diffs if d > 0)
    negative = sum(1 for d in diffs if d < 0)
    return max(positive, negative) / len(diffs)


def _pearson(a: Sequence[float], b: Sequence[float]) -> float:
    n = len(a)
    if n < 2 or len(b) != n:
        return 0.0
    mean_a, mean_b = sum(a) / n, sum(b) / n
    var_a = sum((x - mean_a) ** 2 for x in a)
    var_b = sum((x - mean_b) ** 2 for x in b)
    if var_a == 0 or var_b == 0:
        return 0.0
    cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
    return cov / math.sqrt(var_a * var_b)


def _plateau_fraction(values: Sequence[int]) -> float:
    """Proporción de canales cuyo valor se repite respecto al fotograma previo."""
    if len(values) < 2:
        return 0.0
    stable = sum(1 for a, b in zip(values, values[1:]) if a == b)
    return stable / (len(values) - 1)


def _active_bounds(frames: Sequence[Sequence[int]]) -> tuple[int, int]:
    active = [i for i in range(DMX_CHANNELS) if max(frame[i] for frame in frames) > 0]
    if not active:
        return -1, -1
    return active[0], active[-1]


def fingerprint(frames) -> dict:
    """Analiza fotogramas DMX y devuelve roles probables + candidatos de modelo.

    Acepta uno o varios fotogramas. Con un único fotograma el análisis temporal
    (pan/tilt, strobe) no es fiable: se devuelve confidence baja y un warning.
    """
    warnings: list[str] = []
    evidence: list[str] = []
    normalized, coerce_warnings = _coerce_frames(frames)
    warnings.extend(coerce_warnings)

    if not normalized:
        return {
            "channel_count": 0,
            "confidence": 0.0,
            "roles": {},
            "candidates": [],
            "evidence": ["Sin datos."],
            "warnings": warnings or ["Sin datos."],
        }

    first_active, last_active = _active_bounds(normalized)
    if first_active < 0:
        return {
            "channel_count": 0,
            "confidence": 0.0,
            "roles": {},
            "candidates": [],
            "evidence": ["Todos los canales a cero: no hay fixture activo."],
            "warnings": warnings + ["Frame completamente a cero."],
        }

    raw_footprint = last_active - first_active + 1
    channel_count = raw_footprint + (raw_footprint % 2)  # los perfiles DMX son pares
    evidence.append(
        f"Canales activos {first_active + 1}..{last_active + 1} "
        f"({raw_footprint} canales, footprint estimado {channel_count})."
    )
    if len(normalized) < 2:
        warnings.append(
            "Un solo fotograma: pan/tilt y strobe no son observables; "
            "captura al menos 3 fotogramas moviendo el fixture."
        )

    roles: dict[str, int] = {}
    used: set[int] = set()

    # --- Pan/Tilt de 16 bits: pares adyacentes con progresión monótona suave ---
    pair_candidates: list[tuple[float, int]] = []
    if len(normalized) >= 2:
        for index in range(first_active, last_active):
            coarse = _series(normalized, index)
            fine = _series(normalized, index + 1)
            if _range(coarse) == 0 and _range(fine) == 0:
                continue
            combined = [c * 256 + f for c, f in zip(coarse, fine)]
            score = _monotonic_score(combined)
            if score >= 0.9 and _range(combined) >= 2048:
                quality = score * min(1.0, _range(combined) / 8192)
                pair_candidates.append((quality, index))

    pair_candidates.sort(key=lambda item: (-item[0], item[1]))
    chosen: list[tuple[float, int]] = []
    for quality, index in pair_candidates:
        if any(abs(index - other) < 2 for _, other in chosen):
            continue
        chosen.append((quality, index))
        if len(chosen) == 2:
            break

    if chosen:
        roles["pan"] = chosen[0][1] + 1
        roles["pan_fine"] = chosen[0][1] + 2
        used.update({chosen[0][1], chosen[0][1] + 1})
        evidence.append(
            f"Pan 16-bit en canales {chosen[0][1] + 1}-{chosen[0][1] + 2} "
            f"(monotonía {chosen[0][0]:.2f})."
        )
    if len(chosen) > 1:
        roles["tilt"] = chosen[1][1] + 1
        roles["tilt_fine"] = chosen[1][1] + 2
        used.update({chosen[1][1], chosen[1][1] + 1})
        evidence.append(
            f"Tilt 16-bit en canales {chosen[1][1] + 1}-{chosen[1][1] + 2}."
        )
    elif len(normalized) >= 2:
        warnings.append("No se detectó Tilt de 16 bits; revisa si el perfil es de 8 bits.")

    remaining = [
        i
        for i in range(first_active, last_active + 1)
        if i not in used and _range(_series(normalized, i)) > 0
    ]

    # --- Dimmer: correlación con la intensidad total del rig ---
    if len(normalized) >= 2 and remaining:
        totals = [sum(frame[i] for i in range(first_active, last_active + 1)) for frame in normalized]
        scored = [
            (_pearson(_series(normalized, i), totals), i) for i in remaining
        ]
        scored.sort(key=lambda item: (-item[0], item[1]))
        best_corr, best_index = scored[0]
        best_values = _series(normalized, best_index)
        if best_corr >= 0.6 and _range(best_values) >= 128:
            roles["dimmer"] = best_index + 1
            used.add(best_index)
            remaining.remove(best_index)
            evidence.append(
                f"Dimmer probable en canal {best_index + 1} "
                f"(r={best_corr:.2f} con la intensidad total)."
            )

    # --- Shutter/Strobe: conmutación brusca entre extremos ---
    for index in list(remaining):
        values = _series(normalized, index)
        transitions = sum(
            1
            for a, b in zip(values, values[1:])
            if abs(a - b) >= 200 and {a, b} & {min(values), max(values)}
        )
        if transitions >= 2 and len(set(values)) <= 4:
            roles["shutter"] = index + 1
            used.add(index)
            remaining.remove(index)
            evidence.append(
                f"Shutter/strobe probable en canal {index + 1} "
                f"({transitions} conmutaciones, {len(set(values))} niveles)."
            )
            break

    # --- Ruedas: pocos niveles discretos con mesetas estables ---
    wheel_slot = 0
    for index in list(remaining):
        values = _series(normalized, index)
        distinct = len(set(values))
        if 2 <= distinct <= 10 and _plateau_fraction(values) >= 0.5:
            wheel_slot += 1
            roles[f"wheel_{wheel_slot}"] = index + 1
            used.add(index)
            remaining.remove(index)
            if wheel_slot >= 3:
                break
    if wheel_slot:
        evidence.append(f"{wheel_slot} canales con perfil de rueda (niveles discretos).")

    # --- Color: canales que se mueven en bloque entre sí ---
    color_channels: list[int] = []
    for index in remaining:
        values = _series(normalized, index)
        for other in color_channels:
            if _pearson(values, _series(normalized, other)) >= 0.9 and _range(values) >= 64:
                roles["color"] = index + 1
                color_channels.append(index)
                break
    if color_channels:
        evidence.append(f"Grupo de color correlacionado ({len(color_channels) + 1} canales).")

    # --- Candidatos de modelo ---
    candidates = []
    for profile in PROFILES:
        fit = 1.0 - min(1.0, abs(profile["channels"] - channel_count) / max(channel_count, 1))
        score = fit * 0.7
        reasons = [f"footprint {channel_count} vs {profile['channels']}"]
        if profile["expects_pan_tilt"]:
            if "pan" in roles and "tilt" in roles:
                score += 0.2
                reasons.append("pan/tilt 16-bit presentes")
            else:
                score -= 0.1
                reasons.append("sin pan/tilt completo")
        if profile["expects_dimmer"] and "dimmer" in roles:
            score += 0.1
            reasons.append("dimmer presente")
        candidates.append(
            {
                "model": profile["model"],
                "score": round(max(0.0, min(1.0, score)), 2),
                "reason": ", ".join(reasons),
            }
        )
    candidates.sort(key=lambda item: (-item["score"], item["model"]))

    confidence = 0.0
    confidence += 0.4 if {"pan", "tilt"} <= set(roles) else 0.0
    confidence += 0.2 if "dimmer" in roles else 0.0
    confidence += 0.15 if len(normalized) >= 4 else 0.0
    confidence += 0.15 if channel_count > 2 else 0.0
    confidence += 0.1 if "shutter" in roles or "wheel_1" in roles else 0.0
    confidence = round(min(1.0, confidence), 2)

    return {
        "channel_count": channel_count,
        "confidence": confidence,
        "roles": roles,
        "candidates": candidates[:3],
        "evidence": evidence,
        "warnings": warnings,
    }


def analyze_raw_dmx_stream(channels) -> dict:
    """Alias compatible: acepta un frame (list[int]) o una lista de frames."""
    return fingerprint(channels)


if __name__ == "__main__":  # demo rápida con un rig sintético
    import json

    demo = []
    for step in range(8):
        frame = [0] * DMX_CHANNELS
        value = step * 9000  # pan 16-bit
        frame[0], frame[1] = value >> 8, value & 0xFF
        frame[2], frame[3] = 128, step * 30  # tilt
        frame[4] = 40 + step * 25  # dimmer
        frame[6] = 255 if step % 2 else 0  # strobe
        demo.append(frame)
    print(json.dumps(fingerprint(demo), indent=2, ensure_ascii=False))
