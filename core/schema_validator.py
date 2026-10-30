"""Validación de reglas de negocio sobre unified_show-1.0.0."""

import json
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent.parent / "spec" / "unified_show.schema.json"


def load_schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_mount_type_consistency(show):
    errors = []
    valid_mounts = {"floor", "truss", "wall", "moving"}
    for fix in show.get("fixtures", []):
        pos = fix.get("position", {})
        rot = pos.get("rotation", {})
        has_rotation = any(rot.get(k, 0.0) != 0.0 for k in ("pan_deg", "tilt_deg", "roll_deg"))
        if has_rotation:
            if "mount_type" not in pos:
                errors.append(f"Fixture {fix.get('id', '?')}: rotation no nula requiere position.mount_type")
            elif pos["mount_type"] not in valid_mounts:
                errors.append(f"Fixture {fix.get('id', '?')}: mount_type {pos['mount_type']!r} inválido")
    return errors


def validate_patch_ranges(show):
    errors = []
    for fix in show.get("fixtures", []):
        patch = fix.get("patch", {})
        u, a = patch.get("universe"), patch.get("address")
        if not isinstance(u, int) or u < 1:
            errors.append(f"Fixture {fix.get('id', '?')}: universe inválido {u!r}")
        if not isinstance(a, int) or not (1 <= a <= 512):
            errors.append(f"Fixture {fix.get('id', '?')}: address inválido {a!r}")
    return errors


def validate_semantic_ownership(show, require_empty=True):
    errors = []
    for fix in show.get("fixtures", []):
        sem = fix.get("semantic", {})
        if require_empty:
            for key in ("bearing_deg", "calculated_pan"):
                if sem.get(key) is not None:
                    errors.append(f"Fixture {fix.get('id', '?')}: semantic.{key} debe ser None tras parser")
        else:
            for key in ("bearing_deg", "calculated_pan"):
                v = sem.get(key)
                if v is not None and not isinstance(v, (int, float)):
                    errors.append(f"Fixture {fix.get('id', '?')}: semantic.{key} debe ser numérico o None")
    return errors


def validate_show(show, post_parser=True):
    errors = []
    errors.extend(validate_mount_type_consistency(show))
    errors.extend(validate_patch_ranges(show))
    errors.extend(validate_semantic_ownership(show, require_empty=post_parser))
    return errors
