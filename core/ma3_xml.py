"""
Parser tolerante de exports XML de grandMA3 → documento unified_show-1.0.0.

El XML real de MA3 llega en formas muy distintas según la versión del desk y el
plugin que exporta: namespaces distintos, atributos renombrados (``nr`` vs
``id``, ``label`` vs ``name``) y coordenadas que aparecen como atributos del
propio fixture o como nodos hijos anidados. El parser no asume un esquema fijo:
localiza los nodos de fixture por nombre local y resuelve cada campo por alias
case-insensitive.

Los fixtures irrecuperables (sin id o sin patch parseable) no interrumpen la
conversión: se descartan y se cuentan en
``metadata.extensions.ma3.discarded_fixtures``.
"""

import re
import xml.etree.ElementTree as ET
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from core.parsers import normalize_patch_string, split_fixture_type_string

SCHEMA_VERSION = "1.0.0"
SOURCE_SYSTEM = "grandMA3"
COORDINATE_SYSTEM = "stage_center_origin"

#: Nombres locales que pueden representar un fixture según la versión de MA3.
#: ``Layer`` se acepta porque algunos exports cuelgan la geometría de una capa.
FIXTURE_LOCAL_NAMES = frozenset({"fixture", "fixturenode", "layer"})

#: Contenedores de canales, excluidos al indexar atributos para que un
#: ``<Channel nr="1">`` no se confunda con el id del fixture.
CHANNEL_LOCAL_NAMES = frozenset({"channel", "channels"})

MOUNT_TYPES = frozenset({"floor", "truss", "wall", "moving"})

#: Alias de atributo por campo lógico, en orden de prioridad.
FIELD_ALIASES = {
    "id": ("id", "nr", "number"),
    "name": ("name", "label"),
    "type": ("fixture_type", "fixturetype", "type"),
    "patch": ("patch", "address", "dmx"),
    "x": ("x", "x_pos", "posx"),
    "y": ("y", "y_pos", "posy"),
    "z": ("z", "z_pos", "posz"),
    "rot_z": ("rot_z", "rotation", "rz"),
    "mount_type": ("mount_type", "mounttype", "mount"),
    "channels": ("channels", "channel_list"),
    "session": ("session", "session_name", "sessionname"),
}


def _local_name(tag):
    """Devuelve el nombre local de una etiqueta, sin namespace."""
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1] if tag.startswith("{") else tag


def _normalize_token(value):
    """Normaliza un nombre de atributo o nodo para compararlo por alias."""
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _subtree_attributes(node):
    """Índice ``{token: valor}`` con los atributos del subárbol del nodo.

    Recorre en anchura para que los atributos del propio fixture ganen sobre
    los de sus descendientes. Los subárboles de canales quedan fuera.
    """
    index = {}
    queue = deque([node])
    while queue:
        current = queue.popleft()
        if current is not node and _local_name(current.tag).lower() in CHANNEL_LOCAL_NAMES:
            continue
        for raw_key, raw_value in current.attrib.items():
            index.setdefault(_normalize_token(raw_key), raw_value)
        queue.extend(list(current))
    return index


def _lookup(index, field):
    """Primer valor no vacío entre los alias del campo, o ``None``."""
    for alias in FIELD_ALIASES[field]:
        value = index.get(_normalize_token(alias))
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _to_float(value, default=0.0):
    """Convierte a float tolerando comas decimales y valores ausentes."""
    if value is None:
        return default
    text = str(value).strip()
    try:
        return float(text)
    except ValueError:
        pass
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return default


def _collect_fixture_nodes(node, found):
    """Acumula en ``found`` los nodos candidatos a fixture, en orden de documento."""
    for child in node:
        if _local_name(child.tag).lower() in FIXTURE_LOCAL_NAMES:
            found.append(child)
        _collect_fixture_nodes(child, found)


def _is_container_node(node):
    """``True`` si el nodo envuelve fixtures con id propio (es un contenedor).

    Evita que un ``<Layer>`` contenedor se parsee como fixture fantasma y que
    un fixture envolvente duplique a sus nodos hijos.
    """
    nested = []
    _collect_fixture_nodes(node, nested)
    for candidate in nested:
        if _lookup(_subtree_attributes(candidate), "id"):
            return True
    return False


def _channel_value(node):
    """Valor de un canal: su ``nr``/``id``/``index`` o, si no hay, su texto."""
    index = {_normalize_token(key): value for key, value in node.attrib.items()}
    for alias in ("nr", "id", "index", "number"):
        value = index.get(_normalize_token(alias))
        if value is not None and str(value).strip():
            text = str(value).strip()
            return int(text) if text.isdigit() else text
    text = (node.text or "").strip()
    if text:
        return int(text) if text.isdigit() else text
    return None


def _collect_channels(node, found):
    """Recorre el subárbol acumulando canales declarados."""
    for child in node:
        local = _local_name(child.tag).lower()
        if local == "channels":
            for sub in child:
                if _local_name(sub.tag).lower() == "channel":
                    value = _channel_value(sub)
                    if value is not None:
                        found.append(value)
        elif local == "channel":
            value = _channel_value(child)
            if value is not None:
                found.append(value)
        else:
            _collect_channels(child, found)


def _read_channels(node):
    """Canales declarados por el XML, o ``None`` si el export no los lista."""
    channels = []
    _collect_channels(node, channels)
    if channels:
        return channels
    raw = _lookup(_subtree_attributes(node), "channels")
    if not raw:
        return None
    tokens = [token for token in re.split(r"[\s,;]+", raw) if token]
    parsed = [int(token) if token.isdigit() else token for token in tokens]
    return parsed or None


def _parse_fixture(node):
    """Convierte un nodo XML en fixture unificado.

    Devuelve ``(fixture, None)`` si el nodo es válido y ``(None, motivo)`` si
    hay que descartarlo (sin id, sin patch o patch ilegible).
    """
    attributes = _subtree_attributes(node)

    fixture_id = _lookup(attributes, "id")
    if not fixture_id:
        return None, "sin_id"

    patch_raw = _lookup(attributes, "patch")
    if not patch_raw:
        return None, "sin_patch"
    try:
        patch = normalize_patch_string(patch_raw)
    except (TypeError, ValueError):
        return None, "patch_invalido"

    type_info = split_fixture_type_string(_lookup(attributes, "type") or "")
    channel_count = type_info["channel_count"] or 0

    rotation_z = _to_float(_lookup(attributes, "rot_z"))
    position = {
        "x": _to_float(_lookup(attributes, "x")),
        "y": _to_float(_lookup(attributes, "y")),
        "z": _to_float(_lookup(attributes, "z")),
        "unit": "meters",
        "rotation": {"pan_deg": rotation_z, "tilt_deg": 0.0, "roll_deg": 0.0},
    }

    mount_raw = _lookup(attributes, "mount_type")
    mount_type = mount_raw.lower() if mount_raw else None
    if mount_type not in MOUNT_TYPES:
        mount_type = None
    # Sin rotación no hay dato de montaje que inferir: la clave se omite.
    if rotation_z != 0.0:
        if mount_type:
            position["mount_type"] = mount_type
            position["mount_type_source"] = "extractor"
        else:
            position["mount_type"] = "truss"
            position["mount_type_source"] = "default"

    fixture = {
        "id": fixture_id,
        "name": _lookup(attributes, "name") or f"Fixture_{fixture_id}",
        "type": {
            "manufacturer": type_info["manufacturer"],
            "model": type_info["model"],
            "mode": type_info["mode"] or "default",
            "channel_count": channel_count,
        },
        "patch": {
            "universe": patch["universe"],
            "address": patch["address"],
            "dmx_footprint": channel_count,
        },
        "position": position,
        "optics": {},
        "capabilities": {},
        "semantic": {
            "bearing_deg": None,
            "calculated_pan": None,
            "pan_offset_deg": 0.0,
        },
    }

    channels = _read_channels(node)
    if channels:
        fixture["channels"] = channels
    return fixture, None


def _utc_timestamp():
    """Marca temporal ISO-8601 UTC terminada en ``Z``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_document(fixtures, session_name, discarded, parse_error=None):
    """Ensambla el documento unified_show-1.0.0 completo."""
    source = {"system": SOURCE_SYSTEM}
    if session_name:
        source["session_name"] = session_name
    source["extracted_at"] = _utc_timestamp()
    source["coordinate_system"] = COORDINATE_SYSTEM

    ma3_metadata = {"session_name": session_name, "discarded_fixtures": discarded}
    if parse_error:
        ma3_metadata["parse_error"] = parse_error

    return {
        "schema_version": SCHEMA_VERSION,
        "source": source,
        "stage": {},
        "fixtures": fixtures,
        "metadata": {"extensions": {"ma3": ma3_metadata}},
    }


def _document_from_root(root, session_name):
    """Extrae fixtures de un elemento raíz ya parseado."""
    root_attributes = {_normalize_token(key): value for key, value in root.attrib.items()}
    resolved_session = session_name or _lookup(root_attributes, "session")

    candidates = []
    _collect_fixture_nodes(root, candidates)

    fixtures = []
    discarded = 0
    for node in candidates:
        if _is_container_node(node):
            continue
        fixture, _reason = _parse_fixture(node)
        if fixture is None:
            discarded += 1
            continue
        fixtures.append(fixture)

    return _build_document(fixtures, resolved_session, discarded)


def parse_ma3_xml_string(xml_text, session_name=None):
    """Convierte un export XML de grandMA3 (texto) a unified_show-1.0.0.

    Un texto vacío o un XML truncado no lanzan excepción: devuelven un
    documento sin fixtures (el error de parseo queda anotado en
    ``metadata.extensions.ma3.parse_error``).
    """
    text = (xml_text or "").lstrip("\ufeff").strip()
    if not text:
        return _build_document([], session_name, 0)
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        return _build_document([], session_name, 0, parse_error=str(exc))
    return _document_from_root(root, session_name)


def parse_ma3_xml(path):
    """Convierte un archivo XML de grandMA3 a unified_show-1.0.0.

    El nombre de sesión sale del atributo de la raíz; si el export no lo trae
    se usa el nombre del archivo.
    """
    source_path = Path(path)
    text = source_path.read_text(encoding="utf-8-sig", errors="replace")
    document = parse_ma3_xml_string(text)
    if "session_name" not in document["source"]:
        document["source"]["session_name"] = source_path.stem
        document["metadata"]["extensions"]["ma3"]["session_name"] = source_path.stem
    return document


if __name__ == "__main__":
    from core.schema_validator import validate_show

    sample = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "ma3_export_sample.xml"
    if not sample.exists():
        print(f"Fixture de muestra no encontrado: {sample}")
        raise SystemExit(1)

    show = parse_ma3_xml(sample)
    ma3 = show["metadata"]["extensions"]["ma3"]
    print(f"Sesión: {show['source'].get('session_name')} | fixtures: {len(show['fixtures'])} | descartados: {ma3['discarded_fixtures']}")
    for fixture in show["fixtures"]:
        patch = fixture["patch"]
        print(f"  {fixture['id']:>4} {fixture['name']:<12} {fixture['type']['manufacturer']} {fixture['type']['model']} @ {patch['universe']}.{patch['address']}")
    errors = validate_show(show)
    print("validate_show:", "OK" if not errors else errors)
