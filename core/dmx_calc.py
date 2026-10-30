"""Calculadora DMX: direcciones, solapes, huecos y DIP switches.

Convenios, explícitos porque de ellos dependen los errores de patch:

- Una dirección es 1..512 dentro de un universo.
- Un aparato con footprint ``n`` en la dirección ``a`` ocupa ``a .. a+n-1``.
- El universo es un dato aparte del show; la dirección no lo implica. Aquí se
  calcula el universo "absoluto" sólo como utilidad (``(address-1)//512 + 1``),
  nunca para reescribir el patch.
- Un solape es el fallo más caro del preproducción: dos aparatos en el mismo
  canal se pisan y el segundo gana. Se detecta, no se "arregla" solo.
"""

from __future__ import annotations

UNIVERSE_SIZE = 512


def _as_int(value, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} debe ser un número entero")
    number = int(value)
    if number != value:
        raise ValueError(f"{name} debe ser entero (recibido {value!r})")
    return number


def address_range(address: int, footprint: int = 1) -> tuple[int, int]:
    """Rango inclusivo de canales que ocupa un aparato."""
    start = _as_int(address, "address")
    size = _as_int(footprint, "footprint")
    if size < 1:
        raise ValueError("El footprint debe ser al menos 1")
    if not 1 <= start <= UNIVERSE_SIZE:
        raise ValueError(f"Dirección fuera de 1..{UNIVERSE_SIZE}: {start}")
    end = start + size - 1
    if end > UNIVERSE_SIZE:
        raise ValueError(
            f"El aparato se sale del universo: {start}+{size - 1}={end} > {UNIVERSE_SIZE}"
        )
    return start, end


def universe_of(address: int) -> int:
    """Universo absoluto (1-based) de una dirección global 1..∞."""
    address = _as_int(address, "address")
    if address < 1:
        raise ValueError("La dirección debe ser >= 1")
    return (address - 1) // UNIVERSE_SIZE + 1


def capacity(footprint: int, universe_size: int = UNIVERSE_SIZE) -> int:
    """Cuántos aparatos de ese footprint caben en un universo."""
    size = _as_int(footprint, "footprint")
    if size < 1:
        raise ValueError("El footprint debe ser al menos 1")
    return universe_size // size


def dip_switches(address: int) -> list[int]:
    """Switches DIP que hay que subir para una dirección (1 = 1, 2 = 2, 3 = 4…).

    Se devuelven los números de switch activos, no un binario. Una dirección 512
    necesita el switch 10; si tu tira sólo tiene 9, no puedes con ella y es mejor
    saberlo aquí que en el bolo.
    """
    value = _as_int(address, "address")
    if value < 1:
        raise ValueError("La dirección debe ser >= 1")
    switches = []
    bit = 1
    while value:
        if value & 1:
            switches.append(bit)
        value >>= 1
        bit += 1
    return switches


def next_free(occupied: list[tuple[int, int]], footprint: int = 1, universe_size: int = UNIVERSE_SIZE) -> int | None:
    """Primera dirección libre que cabe entera. ``None`` si no hay hueco."""
    size = _as_int(footprint, "footprint")
    if size < 1 or size > universe_size:
        raise ValueError("Footprint inválido para este universo")

    ranges = []
    for start, end in occupied:
        start, end = int(start), int(end)
        if start > end:
            start, end = end, start
        ranges.append((max(1, start), min(universe_size, end)))
    ranges.sort()

    candidate = 1
    for start, end in ranges:
        if start - candidate >= size:
            return candidate
        candidate = max(candidate, end + 1)
        if candidate + size - 1 > universe_size:
            return None
    if candidate + size - 1 <= universe_size:
        return candidate
    return None


def find_conflicts(fixtures: list[dict]) -> list[dict]:
    """Solapes entre aparatos, agrupados por universo.

    Cada fixture: {"id", "universe", "address", "footprint"}. Devuelve una lista
    de conflictos con los dos ids y el rango compartido.
    """
    by_universe: dict[int, list[tuple[int, int, str]]] = {}
    for fixture in fixtures:
        universe = _as_int(fixture.get("universe", 1), "universe")
        start, end = address_range(
            fixture.get("address", 1), fixture.get("footprint", fixture.get("dmx_footprint", 1))
        )
        by_universe.setdefault(universe, []).append((start, end, str(fixture.get("id", "?"))))

    conflicts = []
    for universe, rows in by_universe.items():
        rows.sort()
        for index in range(len(rows) - 1):
            start_a, end_a, id_a = rows[index]
            start_b, end_b, id_b = rows[index + 1]
            if start_b <= end_a:
                conflicts.append(
                    {
                        "universe": universe,
                        "fixtures": [id_a, id_b],
                        "overlap": [start_b, min(end_a, end_b)],
                        "channels": min(end_a, end_b) - start_b + 1,
                    }
                )
    return conflicts


def summarize(show: dict) -> dict:
    """Estado de patch por universo: ocupación, hueco mayor y conflictos."""
    fixtures = show.get("fixtures", []) or []
    rows = []
    for fixture in fixtures:
        patch = fixture.get("patch") or {}
        rows.append(
            {
                "id": fixture.get("id", "?"),
                "universe": patch.get("universe", 1),
                "address": patch.get("address", 1),
                "footprint": patch.get("dmx_footprint")
                or (fixture.get("type") or {}).get("channel_count")
                or 1,
            }
        )

    universes: dict[int, list[tuple[int, int]]] = {}
    for row in rows:
        start, end = address_range(row["address"], row["footprint"])
        universes.setdefault(row["universe"], []).append((start, end))

    report = []
    for universe, ranges in sorted(universes.items()):
        ranges.sort()
        used = 0
        widest_gap = 0
        cursor = 1
        for start, end in ranges:
            if start > cursor:
                widest_gap = max(widest_gap, start - cursor)
            used += end - max(start, cursor) + 1 if end >= cursor else 0
            cursor = max(cursor, end + 1)
        if cursor <= UNIVERSE_SIZE:
            widest_gap = max(widest_gap, UNIVERSE_SIZE - cursor + 1)
        report.append(
            {
                "universe": universe,
                "fixtures": len(ranges),
                "channels_used": used,
                "usage_percent": round(used / UNIVERSE_SIZE * 100, 1),
                "largest_gap": widest_gap,
                "next_free_address": next_free(ranges),
            }
        )

    conflicts = find_conflicts(rows)
    return {
        "universes": report,
        "conflicts": conflicts,
        "has_conflicts": bool(conflicts),
        "fixture_count": len(rows),
    }


def percent_from_dmx(value: int) -> float:
    value = _as_int(value, "value")
    if not 0 <= value <= 255:
        raise ValueError("El valor DMX va de 0 a 255")
    return round(value / 255 * 100, 1)


def dmx_from_percent(percent: float) -> int:
    if isinstance(percent, bool) or not isinstance(percent, (int, float)):
        raise ValueError("El porcentaje debe ser numérico")
    if not 0 <= percent <= 100:
        raise ValueError("El porcentaje va de 0 a 100")
    return int(round(percent / 100 * 255))
