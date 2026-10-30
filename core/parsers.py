"""
Parsers y splitter heurístico de fixture_type_raw.

Estrategia: cascada regex → mode_dict → model_dict → None.
"""

import json
import re
from pathlib import Path


MODE_DICT = {
    "extended": 25, "extended 2": 32, "basic": 16,
    "standard": 20, "vector": 29, "pixel": 48,
    "tour": 31, "performance": 28,
}

MODEL_DICT = {
    "sharpy plus": 31, "sharpy": 16, "pointe": 31,
    "robin pointe": 31, "megapointe": 34, "ledbeam 12": 12,
    "mac aura xb": 25, "mac aura": 19, "beam 230w": 12,
    "beam 7r": 16, "moving head wash 19x15": 24,
    "moving head beam 380": 17,
}


def split_fixture_type_string(raw: str) -> dict:
    raw = raw.strip()
    original = raw
    channel_count = None
    source = "unresolved"

    m = re.search(r"(?i)(\d+)\s*ch\b", raw)
    if m:
        channel_count = int(m.group(1))
        source = "regex"
        raw = re.sub(r"(?i)\d+\s*ch\b", "", raw).strip()

    raw = re.sub(r"\s+", " ", raw).strip(" ,;-")
    tokens = raw.split()

    if not tokens:
        return {
            "manufacturer": "Generic", "model": "Unknown", "mode": None,
            "channel_count": channel_count, "channel_count_source": source,
            "raw": original,
        }

    manufacturer = tokens[0]
    rest_tokens = tokens[1:]
    model = None
    mode_tokens = []

    if rest_tokens:
        rest = " ".join(rest_tokens)
        lowered = rest.lower()
        candidates = sorted(MODEL_DICT.keys(), key=len, reverse=True)
        for cand in candidates:
            idx = lowered.find(cand)
            # Descarta matches que caen en mitad de un token (p.ej. "beam"
            # dentro de "ledbeam"): el modelo es una secuencia de palabras.
            if idx == -1 or (idx > 0 and rest[idx - 1].isalnum()):
                continue
            # El match se proyecta sobre el texto original para no perder el
            # casing del fabricante ("MAC Aura XB", no "mac aura xb").
            end = idx + len(cand)
            while end < len(rest) and not rest[end].isspace():
                end += 1
            model = rest[idx:end].strip()
            after = rest[end:].strip(" ,;-")
            if after:
                mode_tokens = after.split()
            break

        if model is None:
            if re.match(r"(?i)^v?\d+(\.\d+)?$", rest_tokens[-1]) and len(rest_tokens) > 1:
                mode_tokens = [rest_tokens[-1]]
                model = " ".join(rest_tokens[:-1])
            elif re.match(r"(?i)^(mode|ch|v)", rest_tokens[-1]) and len(rest_tokens) > 1:
                mode_tokens = [rest_tokens[-1]]
                model = " ".join(rest_tokens[:-1])
            else:
                model = " ".join(rest_tokens)

    if model is None:
        model = "Unknown"
    mode = " ".join(mode_tokens) if mode_tokens else None

    if channel_count is None and mode:
        mode_key = mode.lower().strip()
        if mode_key in MODE_DICT:
            channel_count = MODE_DICT[mode_key]
            source = "mode_dict"

    if channel_count is None and model != "Unknown":
        model_key = model.lower().strip()
        if model_key in MODEL_DICT:
            channel_count = MODEL_DICT[model_key]
            source = "model_dict"

    if channel_count is None and "plus" in model.lower():
        base_key = model.lower().replace(" plus", "").strip()
        if base_key in MODEL_DICT:
            channel_count = MODEL_DICT[base_key] + 5
            source = "model_dict"

    # Último recurso: índice local de fixtures (ChamSys Fixture Finder).
    # Va al final a propósito: el contrato congela lo que resuelven regex y
    # diccionarios, y este índice es una hipótesis más amplia, no más autorizada.
    if channel_count is None:
        library_count = _channel_count_from_library(manufacturer, model, mode)
        if library_count is not None:
            channel_count = library_count
            source = "library"

    return {
        "manufacturer": manufacturer, "model": model, "mode": mode,
        "channel_count": channel_count, "channel_count_source": source,
        "raw": original,
    }


def _channel_count_from_library(manufacturer: str, model: str, mode: str | None) -> int | None:
    """Consulta el índice local de fixtures; nunca rompe el parseo si falta."""
    try:
        from core.fixture_library import resolve

        hit = resolve(manufacturer, model, mode)
    except (ImportError, OSError, ValueError):
        return None
    if not hit or not hit.get("channels"):
        return None
    return int(hit["channels"])


def normalize_patch_string(patch) -> dict:
    if isinstance(patch, dict):
        return {"universe": int(patch.get("universe", 1)), "address": int(patch.get("address", 1))}
    patch = str(patch).strip()
    m = re.match(r"^\D*(\d+)\D+(\d+)\D*$", patch)
    if not m:
        raise ValueError(f"Cannot parse patch string: {patch!r}")
    return {"universe": int(m.group(1)), "address": int(m.group(2))}


def _empty_semantic():
    return {"bearing_deg": None, "calculated_pan": None, "pan_offset_deg": 0.0}


def normalize_ma3_fixture(raw: dict) -> dict:
    type_info = split_fixture_type_string(raw.get("fixture_type_raw", "Generic Unknown"))
    patch = normalize_patch_string(raw.get("patch_string", "1.1"))
    coords = raw.get("coordinates", {})
    orientation = raw.get("orientation", {})
    rot_z = float(orientation.get("rot_z", 0.0))

    position = {
        "x": float(coords.get("x_pos", 0.0)),
        "y": float(coords.get("y_pos", 0.0)),
        "z": float(coords.get("z_pos", 0.0)),
        "unit": "meters",
        "rotation": {"pan_deg": rot_z, "tilt_deg": 0.0, "roll_deg": 0.0},
    }

    if any(v != 0.0 for v in position["rotation"].values()):
        if "mount_type" in raw:
            position["mount_type"] = raw["mount_type"]
            position["mount_type_source"] = "extractor"
        else:
            position["mount_type"] = "truss"
            position["mount_type_source"] = "default"

    return {
        "id": str(raw.get("id", "0")),
        "name": raw.get("name", "Unnamed"),
        "type": {
            "manufacturer": type_info["manufacturer"],
            "model": type_info["model"],
            "mode": type_info["mode"] or "default",
            "channel_count": type_info["channel_count"] or 0,
        },
        "patch": {
            "universe": patch["universe"], "address": patch["address"],
            "dmx_footprint": type_info["channel_count"] or 0,
        },
        "position": position,
        "semantic": _empty_semantic(),
    }


def normalize_chamsys_fixture(raw: dict) -> dict:
    return normalize_ma3_fixture(raw)


def validate_mount_type_consistency(show: dict) -> list:
    errors = []
    for fix in show.get("fixtures", []):
        pos = fix.get("position", {})
        rot = pos.get("rotation", {})
        has_rotation = any(rot.get(k, 0.0) != 0.0 for k in ("pan_deg", "tilt_deg", "roll_deg"))
        if has_rotation and "mount_type" not in pos:
            errors.append(f"Fixture {fix.get('id', '?')} has non-zero rotation but missing position.mount_type")
    return errors


if __name__ == "__main__":
    cases_file = Path(__file__).parent.parent / "tests" / "fixtures" / "test_parser_cases.json"
    if not cases_file.exists():
        print(f"Casos no encontrados: {cases_file}")
        raise SystemExit(1)
    cases = json.loads(cases_file.read_text())
    for case in cases:
        result = split_fixture_type_string(case["input"])
        expected = case["expected"]
        ok = all(result.get(k) == v for k, v in expected.items())
        print(f"{'✅' if ok else '❌'} {case['input']!r} → {result}")
        if not ok:
            print(f"   esperado: {expected}")
