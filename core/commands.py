"""
Emisores de comandos nativos MA3 y ChamSys desde un unified_show-1.0.0.

Sintaxis emitida (fijada por tools/contract_test.py, test 4 — no cambiar):

    Patch Fixture 11 At 3.1
    Label Fixture 11 "Beam_1"
    Set Fixture 11 Attribute "PAN" At -157.38
    PATCH $11 Robe_Pointe 3.1          (ChamSys: tipo con espacios -> guiones bajos)

Reglas duras que aplica este módulo:

- Todo comando MA3 pasa por ``MA3_ALLOWED_VERBS``; lo que caiga fuera se
  descarta y el motivo se reporta en ``translate()["warnings"]``.
- Nunca se emite DMX crudo: la traducción trabaja sobre fixtures, atributos y
  patch, jamás sobre números de canal ni valores 0-255.
- Los labels MA3 que contienen comillas dobles se emiten con comillas simples;
  si el nombre trae ambas, las dobles se degradan a simples (MA3 no admite
  comillas dobles escapadas dentro de un argumento) y se emite un warning.

Limitación conocida de ``calculated_pan``
-----------------------------------------
El pan calculado por ``intelligence.py`` es un rumbo geométrico (bearing). El
cabezal físico añade un offset propio del modelo (p.ej. Robe LEDBeam 12 gira
90° respecto del bearing). Ese offset no vive en el documento: vive en la tabla
de ``core/pan_offsets.py``. Por eso sólo se compensa cuando el fixture declara
``semantic.pan_offset_deg`` además de ``calculated_pan``; en ese caso se aplica
``core.pan_offsets.apply_pan_offset()`` con la clave del modelo. Si el modelo no
está tabulado, ``apply_pan_offset()`` cae a ``__default__`` (0.0), el valor se
emite sin compensar y queda pendiente la calibración in-situ. Un documento sin
``pan_offset_deg`` se emite literal, tal como exige el contrato.
"""

from core.pan_offsets import apply_pan_offset, normalize_fixture_key

MA3_ALLOWED_VERBS = (
    "Patch", "Label", "Set", "Group", "Clear", "Store", "Delete", "Move", "Copy",
)

TARGET_MA3 = "grandMA3"
TARGET_CHAMSYS = "ChamSys"

_TARGET_ALIASES = {
    "grandma3": TARGET_MA3,
    "grandma2": TARGET_MA3,
    "ma3": TARGET_MA3,
    "ma": TARGET_MA3,
    "chamsys": TARGET_CHAMSYS,
    "cs": TARGET_CHAMSYS,
}

DEFAULT_CHAMSYS_TYPE = "Generic_Unknown"


def normalize_target(target) -> str:
    """Devuelve el nombre canónico del sistema destino (``grandMA3``/``ChamSys``)."""
    key = str(target or "").strip().lower()
    if key in _TARGET_ALIASES:
        return _TARGET_ALIASES[key]
    raise ValueError(
        f"target no soportado: {target!r}; usar {TARGET_MA3!r} o {TARGET_CHAMSYS!r} "
        f"(alias: ma3, ma, cs)"
    )


def _format_number(value) -> str:
    """Serializa un número conservando el sufijo decimal cuando es float."""
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    return str(float(value))


def _quote_ma3(text) -> tuple:
    """Entrecomilla un label para MA3. Devuelve ``(literal, warning|None)``."""
    raw = str(text)
    clean = raw.replace("\r", " ").replace("\n", " ")
    warning = None
    if clean != raw:
        warning = "label con salto de línea aplanado a espacio"
    if '"' not in clean:
        return f'"{clean}"', warning
    if "'" not in clean:
        return f"'{clean}'", warning
    degradado = clean.replace('"', "'")
    nota = (
        "label con comillas dobles y simples: las dobles se degradaron a "
        "simples (MA3 no admite comillas dobles dentro del argumento)"
    )
    warning = f"{warning}; {nota}" if warning else nota
    return f'"{degradado}"', warning


def _check_ma3_command(command: str) -> tuple:
    """Valida un comando MA3 contra la allowlist. Devuelve ``(ok, motivo)``."""
    text = command.strip()
    if not text:
        return False, "comando vacío"
    if any(ch in text for ch in "\r\n\t"):
        return False, "caracteres de control"
    verb = text.split()[0]
    if verb not in MA3_ALLOWED_VERBS:
        return False, f"verbo {verb!r} fuera de la allowlist MA3"
    if text.upper().startswith("DMX "):
        return False, "DMX crudo prohibido"
    return True, ""


def _filter_ma3(commands, warnings) -> list:
    """Descarta los comandos que no pasan la allowlist y anota el motivo."""
    kept = []
    for command in commands:
        ok, reason = _check_ma3_command(command)
        if ok:
            kept.append(command)
        else:
            warnings.append(f"comando descartado ({reason}): {command!r}")
    return kept


def _pan_value(fixture: dict, warnings) -> object:
    """Resuelve el PAN a emitir, compensando el offset del modelo si procede."""
    semantic = fixture.get("semantic") or {}
    pan = semantic.get("calculated_pan")
    if pan is None:
        return None
    if "pan_offset_deg" not in semantic:
        return pan
    ftype = fixture.get("type") or {}
    key = normalize_fixture_key(ftype.get("manufacturer", ""), ftype.get("model", ""))
    compensated = apply_pan_offset(float(pan), key)
    if key == "__default__" and semantic.get("pan_offset_deg"):
        warnings.append(
            f"fixture {fixture.get('id')}: modelo sin offset tabulado, "
            f"PAN emitido sin compensar (pan_offset_deg declarado "
            f"{semantic['pan_offset_deg']})"
        )
    return compensated


def _ma3_commands(show: dict) -> tuple:
    """Genera comandos MA3. Devuelve ``(commands, warnings)``."""
    commands, warnings = [], []
    for fixture in show.get("fixtures", []) or []:
        fid = str(fixture.get("id", "")).strip()
        if not fid:
            warnings.append("fixture sin id: se omite")
            continue
        patch = fixture.get("patch") or {}
        universe, address = patch.get("universe"), patch.get("address")
        if isinstance(universe, bool) or not isinstance(universe, int) or universe < 1:
            warnings.append(f"fixture {fid}: universe inválido {universe!r}: se omite")
            continue
        if isinstance(address, bool) or not isinstance(address, int) or not 1 <= address <= 512:
            warnings.append(f"fixture {fid}: address inválido {address!r}: se omite")
            continue

        commands.append(f"Patch Fixture {fid} At {universe}.{address}")

        name = fixture.get("name")
        if name:
            quoted, warning = _quote_ma3(name)
            if warning:
                warnings.append(f"fixture {fid}: {warning}")
            commands.append(f"Label Fixture {fid} {quoted}")

        pan = _pan_value(fixture, warnings)
        if pan is not None:
            commands.append(
                f'Set Fixture {fid} Attribute "PAN" At {_format_number(pan)}'
            )

    return _filter_ma3(commands, warnings), warnings


def _chamsys_type(ftype: dict) -> str:
    """Compone el nombre de tipo ChamSys: espacios -> guiones bajos."""
    manufacturer = str(ftype.get("manufacturer") or "").strip()
    model = str(ftype.get("model") or "").strip()
    if not manufacturer and not model:
        return DEFAULT_CHAMSYS_TYPE
    return f"{manufacturer} {model}".strip().replace(" ", "_")


def _chamsys_commands(show: dict) -> tuple:
    """Genera comandos ChamSys. Devuelve ``(commands, warnings)``."""
    commands, warnings = [], []
    for fixture in show.get("fixtures", []) or []:
        fid = str(fixture.get("id", "")).strip()
        if not fid:
            warnings.append("fixture sin id: se omite")
            continue
        patch = fixture.get("patch") or {}
        universe, address = patch.get("universe"), patch.get("address")
        if isinstance(universe, bool) or not isinstance(universe, int) or universe < 1:
            warnings.append(f"fixture {fid}: universe inválido {universe!r}: se omite")
            continue
        if isinstance(address, bool) or not isinstance(address, int) or not 1 <= address <= 512:
            warnings.append(f"fixture {fid}: address inválido {address!r}: se omite")
            continue
        type_name = _chamsys_type(fixture.get("type") or {})
        commands.append(f"PATCH ${fid} {type_name} {universe}.{address}")
    return commands, warnings


def to_ma3(show: dict) -> list:
    """Traduce el show a la lista de comandos nativos grandMA3."""
    return _ma3_commands(show)[0]


def to_chamsys(show: dict) -> list:
    """Traduce el show a la lista de comandos nativos ChamSys."""
    return _chamsys_commands(show)[0]


def translate(show: dict, target) -> dict:
    """Traduce el show al sistema destino.

    Devuelve ``{"target", "commands", "warnings"}``; ``warnings`` incluye los
    comandos descartados por la allowlist y los labels reescritos.
    """
    canonical = normalize_target(target)
    if canonical == TARGET_MA3:
        commands, warnings = _ma3_commands(show)
    else:
        commands, warnings = _chamsys_commands(show)
    return {"target": canonical, "commands": commands, "warnings": warnings}


if __name__ == "__main__":
    import json
    from pathlib import Path

    example = Path(__file__).resolve().parent.parent / "spec" / "unified_show-1.0.0.example.json"
    demo_show = json.loads(example.read_text(encoding="utf-8"))
    for demo_target in (TARGET_MA3, TARGET_CHAMSYS):
        result = translate(demo_show, demo_target)
        print(f"[{result['target']}] {len(result['commands'])} comandos")
        for comando in result["commands"]:
            print(f"  {comando}")
        for aviso in result["warnings"]:
            print(f"  ! {aviso}")
