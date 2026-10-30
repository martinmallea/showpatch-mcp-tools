"""Fase 3: geometría de rig y Pan semántico sobre unified_show-1.0.0.

Diferencias deliberadas con el prototipo del que nace este módulo:

1. Opera sobre el contrato congelado (``position``/``patch`` anidados), no sobre
   claves planas ``pos_x``/``patch:"3.1"``.
2. Separa lo que es geometría de lo que es Pan utilizable:
   ``bearing_deg`` es el ángulo hacia el objetivo; ``calculated_pan`` es ese
   ángulo más el offset de calibración del modelo (yugo invertido, tope físico).
   Un moving head NO apunta con el bearing desnudo.
3. No inventa ``mount_type``: si hay rotación física y el parser no lo trajo,
   lo marca como ``default`` para que la decisión quede auditable.
4. No escribe en disco ni habla por red: es cálculo puro y testeable.
"""

from __future__ import annotations

import copy
import math
from typing import Iterable

from core.pan_offsets import apply_pan_offset, get_pan_offset, normalize_fixture_key

__all__ = [
    "bearing_to",
    "normalize_pan",
    "pan_for",
    "adapt",
    "horseshoe",
    "style_profile",
    "ShowIntelligence",
]

GENERATOR = "showpatch/1.0.0"


def _position(fixture: dict) -> dict:
    position = fixture.get("position")
    return position if isinstance(position, dict) else {}


def bearing_to(position: dict, target: tuple[float, float] = (0.0, 0.0)) -> float:
    """Ángulo en grados desde la posición del fixture hacia ``target``.

    Convenio del contrato: origen en el centro del escenario, ``+y`` hacia
    upstage. ``bearing 0°`` apunta a ``-x``; el rango es (-180, 180].
    """
    x = float(position.get("x", 0.0))
    y = float(position.get("y", 0.0))
    dx = float(target[0]) - x
    dy = float(target[1]) - y
    if dx == 0.0 and dy == 0.0:
        return 0.0
    return round(math.degrees(math.atan2(dy, dx)), 2)


def normalize_pan(pan: float) -> float:
    """Normaliza Pan al rango físico (-270, 270] que usan los yugos reales."""
    value = float(pan)
    while value > 270.0:
        value -= 540.0
    while value < -270.0:
        value += 540.0
    return round(value, 2)


def _fixture_key(fixture: dict) -> str:
    type_info = fixture.get("type") or {}
    return normalize_fixture_key(
        str(type_info.get("manufacturer", "")), str(type_info.get("model", ""))
    )


def pan_for(
    fixture: dict, target: tuple[float, float] = (0.0, 0.0), *, apply_offsets: bool = True
) -> dict:
    """Devuelve bearing, offset de modelo y Pan corregido para un fixture."""
    position = _position(fixture)
    bearing = bearing_to(position, target)
    key = _fixture_key(fixture)
    offset = get_pan_offset(key)
    pan = apply_pan_offset(bearing, key) if apply_offsets else normalize_pan(bearing)
    return {
        "bearing_deg": bearing,
        "pan_offset_deg": offset,
        "calculated_pan": pan,
        "fixture_key": key,
        "model_known": key != "__default__",
    }


def _ensure_mount_type(fixture: dict) -> None:
    """Coherencia contractual: rotación no nula exige mount_type explícito."""
    position = _position(fixture)
    rotation = position.get("rotation") or {}
    has_rotation = any(float(rotation.get(k, 0.0) or 0.0) != 0.0 for k in ("pan_deg", "tilt_deg", "roll_deg"))
    if has_rotation and "mount_type" not in position:
        position["mount_type"] = "truss"
        position["mount_type_source"] = "default"


def _header(show: dict, operation: str, params: dict) -> dict:
    result = copy.deepcopy(show)
    result.setdefault("schema_version", "1.0.0")
    result.setdefault("fixtures", [])
    metadata = result.setdefault("metadata", {})
    metadata["intelligence"] = {
        "operation": operation,
        "params": params,
        "generated_by": GENERATOR,
    }
    return result


def adapt(
    show: dict,
    matrix: dict | None = None,
    *,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
    scale_z: float = 1.0,
    rotate_z_deg: float = 0.0,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
) -> dict:
    """Aplica una transformación afín a las posiciones 3D del rig.

    Sirve para lo que rompe un bolo: el escenario del festival es un 30% más
    pequeño que el de la gira. Escala → rotación → traslación, en ese orden.

    La rotación física de cada fixture (``position.rotation``) NO se toca: es
    orientación de montaje, no dirección de apuntado. Mezclarlas es el error que
    descuadra los shows.
    """
    matrix = matrix or {}
    sx = float(matrix.get("scale_x", scale_x))
    sy = float(matrix.get("scale_y", scale_y))
    sz = float(matrix.get("scale_z", scale_z))
    rotate = math.radians(float(matrix.get("rotate_z", rotate_z_deg)))
    ox = float(matrix.get("offset_x", offset_x))
    oy = float(matrix.get("offset_y", offset_y))

    cos_r, sin_r = math.cos(rotate), math.sin(rotate)
    result = _header(
        show,
        "affine",
        {
            "scale_x": sx,
            "scale_y": sy,
            "scale_z": sz,
            "rotate_z": round(math.degrees(rotate), 4),
            "offset_x": ox,
            "offset_y": oy,
        },
    )

    for fixture in result["fixtures"]:
        position = _position(fixture)
        x = float(position.get("x", 0.0)) * sx
        y = float(position.get("y", 0.0)) * sy
        position["x"] = round(x * cos_r - y * sin_r + ox, 3)
        position["y"] = round(x * sin_r + y * cos_r + oy, 3)
        position["z"] = round(float(position.get("z", 0.0)) * sz, 3)
        position.setdefault("unit", "meters")
        _ensure_mount_type(fixture)

    return result


def horseshoe(
    show: dict,
    *,
    center_x: float = 0.0,
    center_y: float = 0.0,
    radius: float = 5.0,
    start_deg: float = 180.0,
    end_deg: float = 0.0,
    target: tuple[float, float] = (0.0, 0.0),
    apply_offsets: bool = True,
    preserve_order: bool = True,
) -> dict:
    """Distribuye los fixtures en herradura y recalcula el Pan hacia el centro.

    Los aparatos se reparten uniformemente en el arco ``start_deg → end_deg``
    (por orden de lista, o por su ``id`` si ``preserve_order=False``). La altura
    ``z`` y la rotación física se conservan.

    Idempotente: ejecutarla dos veces con los mismos parámetros da el mismo
    resultado, porque la posición depende sólo del índice y del arco.
    """
    fixtures = show.get("fixtures") or []
    result = _header(
        show,
        "horseshoe",
        {
            "center_x": center_x,
            "center_y": center_y,
            "radius": radius,
            "start_deg": start_deg,
            "end_deg": end_deg,
            "target": list(target),
            "apply_offsets": apply_offsets,
        },
    )
    result["fixtures"] = []

    if len(fixtures) < 2:
        result["metadata"]["intelligence"]["warnings"] = [
            "Menos de 2 fixtures: la herradura no se aplica (se devuelve copia)."
        ]
        result["fixtures"] = copy.deepcopy(fixtures)
        return result

    ordered = list(fixtures)
    if not preserve_order:
        ordered.sort(key=lambda f: str(f.get("id", "")))
    total = len(ordered)

    for index, fixture in enumerate(ordered):
        cloned = copy.deepcopy(fixture)
        position = _position(cloned)
        fraction = index / (total - 1)
        angle = math.radians(start_deg + (end_deg - start_deg) * fraction)
        position["x"] = round(center_x + radius * math.cos(angle), 3)
        position["y"] = round(center_y + radius * math.sin(angle), 3)
        position["z"] = round(float(position.get("z", 0.0)), 3)
        position.setdefault("unit", "meters")

        computed = pan_for(cloned, target, apply_offsets=apply_offsets)
        semantic = cloned.setdefault("semantic", {})
        semantic["bearing_deg"] = computed["bearing_deg"]
        semantic["calculated_pan"] = computed["calculated_pan"]
        semantic["pan_offset_deg"] = computed["pan_offset_deg"]
        if not computed["model_known"]:
            result["metadata"]["intelligence"].setdefault("warnings", []).append(
                f"Fixture {cloned.get('id', '?')}: modelo sin offset calibrado "
                f"({computed['fixture_key']}); Pan = bearing."
            )
        _ensure_mount_type(cloned)
        result["fixtures"].append(cloned)

    return result


def style_profile(show: dict) -> dict:
    """Huella estilística determinista del rig (sin azar, sin reloj)."""
    fixtures = show.get("fixtures") or []
    count = len(fixtures)
    color_systems: dict[str, int] = {}
    zones: set[str] = set()
    roles: dict[str, int] = {}

    for fixture in fixtures:
        capabilities = fixture.get("capabilities") or {}
        color = capabilities.get("color_system")
        if color:
            color_systems[color] = color_systems.get(color, 0) + 1
        semantic = fixture.get("semantic") or {}
        if semantic.get("zone"):
            zones.add(str(semantic["zone"]))
        if semantic.get("role"):
            roles[str(semantic["role"])] = roles.get(str(semantic["role"]), 0) + 1

    dominant_color = (
        sorted(color_systems.items(), key=lambda item: (-item[1], item[0]))[0][0]
        if color_systems
        else "UNKNOWN"
    )
    # Firma temporal: más aparatos → decisiones más cortas (clusters densos).
    timing = int(max(800, min(1800, round((1800 - 10 * count) / 50.0) * 50)))

    return {
        "programmer_dna": {
            "density_cluster": "High-Profile" if count > 50 else "Compact-Rig",
            "color_space_preference": f"{dominant_color}_Dominant" if dominant_color != "UNKNOWN" else "UNKNOWN",
            "timing_signature_ms": timing,
        },
        "rig": {
            "fixture_count": count,
            "color_systems": dict(sorted(color_systems.items())),
            "roles": dict(sorted(roles.items())),
            "zones": sorted(zones),
        },
    }


class ShowIntelligence:
    """Fachada con los nombres del prototipo, ya sobre el contrato v1.0.0.

    Se mantiene para no romper llamadas existentes; la API recomendada son las
    funciones del módulo. ``translate_cross_platform`` delega en
    ``core.commands`` para que exista una única fuente de sintaxis nativa.
    """

    @staticmethod
    def geometric_cloner_3d(show: dict, matrix: dict) -> dict:
        return adapt(show, matrix)

    @staticmethod
    def generate_horseshoes_layout(
        show: dict, center_x: float = 0.0, center_y: float = 0.0, radius: float = 5.0,
        start_angle: float = 180.0, end_angle: float = 0.0,
    ) -> dict:
        return horseshoe(
            show,
            center_x=center_x,
            center_y=center_y,
            radius=radius,
            start_deg=start_angle,
            end_deg=end_angle,
        )

    @staticmethod
    def translate_cross_platform(show: dict, target_system: str) -> dict:
        from core.commands import translate

        return translate(show, target_system)

    @staticmethod
    def generate_style_profile(show: dict) -> dict:
        return style_profile(show)
