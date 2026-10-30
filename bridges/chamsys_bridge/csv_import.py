"""
Importación de un export CSV de ChamSys a unified_show-1.0.0.

El export de ChamSys (``File > Export > CSV``) no tiene un formato único: según
la versión cambian el nombre y el orden de las columnas. Este módulo normaliza
las cabeceras (minúsculas, separadores colapsados) y las resuelve contra una
tabla de alias, de modo que ``Head``/``ID``/``Fixture`` son la misma columna y
``Type``/``Fixture Type`` también. Las columnas que no aparecen se sustituyen
por valores neutros y **nunca** se inventan datos semánticos: ``semantic`` sale
vacío (``bearing_deg`` y ``calculated_pan`` en ``None``) porque el CSV no
contiene información de dirección, sólo de patch y plot.

Montaje: ChamSys no exporta el tipo de montaje. Si no hay columna
``Mount``/``Mount Type`` reconocible se emite ``mount_type = "truss"`` con
``mount_type_source = "default"``, que es exactamente la señal de "valor por
defecto, no extraído". Si la columna existe y es válida, se usa con
``mount_type_source = "extractor"``.
"""

import csv
import io
import re
from datetime import datetime, timezone

from core.parsers import normalize_patch_string, split_fixture_type_string

SCHEMA_VERSION = "1.0.0"
SOURCE_SYSTEM = "ChamSys"
SESSION_NAME = "chamsys_csv_import"
COORDINATE_SYSTEM = "stage_center_origin"
VALID_MOUNTS = ("floor", "truss", "wall", "moving")

# Alias de cabecera ya normalizados (ver _normalize_header).
COLUMN_ALIASES = {
    "id": ("head", "head id", "head no", "head number", "id", "fixture",
           "fixture id", "fixture number", "chan", "channel"),
    "name": ("name", "head name", "fixture name", "label", "description"),
    "universe": ("universe", "univ", "uni", "universo"),
    "address": ("address", "addr", "dmx address", "patch", "patch address"),
    "type": ("type", "fixture type", "head type", "fixturetype", "profile"),
    "mode": ("mode", "fixture mode", "head mode"),
    "channel_count": ("channels", "channel count", "dmx footprint", "footprint",
                      "channel qty", "num channels"),
    "x": ("x", "plot x", "pos x", "position x", "x pos"),
    "y": ("y", "plot y", "pos y", "position y", "y pos"),
    "z": ("z", "plot z", "pos z", "position z", "z pos"),
    "mount": ("mount", "mount type", "position type"),
}


def _normalize_header(text) -> str:
    """Minúsculas y separadores colapsados: ``Head/ID`` -> ``head id``."""
    return re.sub(r"[^a-z0-9]+", " ", str(text).strip().lower()).strip()


_ALIAS_LOOKUP = {}
for _field, _aliases in COLUMN_ALIASES.items():
    for _alias in _aliases:
        _ALIAS_LOOKUP.setdefault(_normalize_header(_alias), _field)


def _utc_now() -> str:
    """Timestamp ISO-8601 UTC con segundos, como exige el schema (date-time)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _empty_show() -> dict:
    """Documento válido con cero fixtures (cabecera desconocida o CSV vacío)."""
    return {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "system": SOURCE_SYSTEM,
            "session_name": SESSION_NAME,
            "extracted_at": _utc_now(),
            "coordinate_system": COORDINATE_SYSTEM,
        },
        "fixtures": [],
        "metadata": {},
    }


def _detect_delimiter(text: str) -> str:
    """Detecta coma, punto y coma o tabulador; cae a coma si no hay pistas."""
    muestra = text[:4096]
    try:
        return csv.Sniffer().sniff(muestra, delimiters=",;\t").delimiter
    except csv.Error:
        return ","


def _map_columns(header) -> dict:
    """Mapea cada columna conocida a su índice; ignora las desconocidas."""
    index_by_field = {}
    for index, cell in enumerate(header):
        field = _ALIAS_LOOKUP.get(_normalize_header(cell))
        if field and field not in index_by_field:
            index_by_field[field] = index
    return index_by_field


def _cell(row, index_by_field: dict, field: str) -> str:
    """Devuelve el texto de una columna, o ``""`` si no existe en el export."""
    index = index_by_field.get(field)
    if index is None or index >= len(row):
        return ""
    return str(row[index]).strip()


def _clean_id(raw: str) -> str:
    """Normaliza el ID: ``Head 11`` / ``#11`` / ``$11`` -> ``11``."""
    text = re.sub(r"(?i)^\s*(head|fixture|chan|channel)?\s*", "", str(raw))
    return text.strip().lstrip("#$").strip()


def _to_float(raw: str, default: float = 0.0) -> float:
    """Convierte a float tolerando coma decimal y celdas vacías."""
    text = str(raw).strip().replace(" ", "")
    if not text:
        return default
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    return float(text)


def _to_int(raw: str):
    """Convierte a int tolerando ``31.0``; devuelve ``None`` si no es numérico."""
    text = str(raw).strip()
    if not text:
        return None
    return int(float(text.replace(",", ".")))


def _parse_patch(index_by_field: dict, row) -> dict:
    """Resuelve universo/dirección desde columnas separadas o patch ``3.1``."""
    universe_raw = _cell(row, index_by_field, "universe")
    address_raw = _cell(row, index_by_field, "address")
    if not universe_raw and not address_raw:
        raise ValueError("fila sin datos de patch")
    if "." in address_raw:
        # Formato compacto "3.1" (universo.dirección).
        patch = normalize_patch_string(address_raw)
    elif universe_raw:
        patch = {
            "universe": _to_int(universe_raw),
            "address": _to_int(address_raw) if address_raw else 1,
        }
    else:
        # Sólo dirección: el export no trae universo, se asume el 1.
        patch = {"universe": 1, "address": _to_int(address_raw)}
    if patch["universe"] is None or patch["address"] is None:
        raise ValueError(f"patch no numérico: {patch}")
    if patch["universe"] < 1 or not 1 <= patch["address"] <= 512:
        raise ValueError(f"patch fuera de rango: {patch}")
    return patch


def _build_fixture(index_by_field: dict, row) -> dict:
    """Construye un fixture válido desde una fila; lanza ``ValueError`` si no sirve."""
    fixture_id = _clean_id(_cell(row, index_by_field, "id"))
    if not fixture_id:
        raise ValueError("fila sin id de head")

    patch = _parse_patch(index_by_field, row)

    type_raw = _cell(row, index_by_field, "type")
    type_info = split_fixture_type_string(type_raw) if type_raw else None
    manufacturer = (type_info or {}).get("manufacturer") or "Generic"
    model = (type_info or {}).get("model") or "Unknown"
    mode = _cell(row, index_by_field, "mode") or (type_info or {}).get("mode")
    channel_count = _to_int(_cell(row, index_by_field, "channel_count"))
    if channel_count is None:
        channel_count = (type_info or {}).get("channel_count") or 0

    mount_raw = _cell(row, index_by_field, "mount").lower()
    if mount_raw in VALID_MOUNTS:
        mount_type, mount_source = mount_raw, "extractor"
    else:
        mount_type, mount_source = "truss", "default"

    name = _cell(row, index_by_field, "name") or f"Head_{fixture_id}"

    return {
        "id": fixture_id,
        "name": name,
        "type": {
            "manufacturer": manufacturer,
            "model": model,
            "mode": mode or "default",
            "channel_count": channel_count,
        },
        "patch": {
            "universe": patch["universe"],
            "address": patch["address"],
            "dmx_footprint": channel_count,
        },
        "position": {
            "x": _to_float(_cell(row, index_by_field, "x")),
            "y": _to_float(_cell(row, index_by_field, "y")),
            "z": _to_float(_cell(row, index_by_field, "z")),
            "unit": "meters",
            "mount_type": mount_type,
            "mount_type_source": mount_source,
            "rotation": {"pan_deg": 0.0, "tilt_deg": 0.0, "roll_deg": 0.0},
        },
        "semantic": {
            "bearing_deg": None,
            "calculated_pan": None,
            "pan_offset_deg": 0.0,
        },
    }


def parse_chamsys_csv(text: str) -> dict:
    """Importa un export CSV de ChamSys y devuelve un unified_show-1.0.0.

    Tolera mayúsculas, separadores distintos y columnas ausentes. Si la cabecera
    no contiene ninguna columna de ID reconocible, devuelve el documento con
    ``fixtures`` vacío en lugar de lanzar una excepción.
    """
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    limpio = str(text or "").lstrip("\ufeff")
    if not limpio.strip():
        return _empty_show()

    delimiter = _detect_delimiter(limpio)
    rows = list(csv.reader(io.StringIO(limpio, newline=""), delimiter=delimiter))
    if not rows:
        return _empty_show()

    index_by_field = _map_columns(rows[0])
    if "id" not in index_by_field:
        return _empty_show()

    show = _empty_show()
    for row in rows[1:]:
        if not any(str(cell).strip() for cell in row):
            continue
        try:
            show["fixtures"].append(_build_fixture(index_by_field, row))
        except (ValueError, TypeError):
            # Fila incompleta o corrupta: se descarta sin abortar el import.
            continue
    return show


if __name__ == "__main__":
    from core.schema_validator import validate_show

    DEMO_CSV = (
        "Head,Name,Universe,Address,Type,X,Y,Z\n"
        "11,Beam_1,3,1,Robe Pointe Extended,-3.0,0.0,4.0\n"
        "12,Beam_2,3,32,Robe Pointe Extended,3.0,0.0,4.0\n"
    )
    demo = parse_chamsys_csv(DEMO_CSV)
    print(f"fixtures: {len(demo['fixtures'])}")
    for demo_fixture in demo["fixtures"]:
        print(f"  {demo_fixture['id']} {demo_fixture['name']} {demo_fixture['type']}")
    print(f"errores de validación: {validate_show(demo)}")
