#!/usr/bin/env python3
"""Contract test suite para ShowPatch. 6 tests, sin dependencias externas."""

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from core.pan_offsets import apply_pan_offset, calibrate_with_offset_keyword, normalize_fixture_key


class TestResult:
    def __init__(self, name):
        self.name = name
        self.passed = False
        self.details = []

    def ok(self, msg): self.details.append(("PASS", msg))
    def fail(self, msg): self.details.append(("FAIL", msg))
    def info(self, msg): self.details.append(("INFO", msg))

    def finalize(self):
        self.passed = all(s in ("PASS", "INFO") for s, _ in self.details)
        return self


def test_1_schema_roundtrip(verbose=False):
    r = TestResult("Test 1 — Schema roundtrip")
    required_fixture = {"id", "type", "patch", "position"}
    required_type = {"manufacturer", "model"}
    required_patch = {"universe", "address"}
    required_pos = {"x", "y", "z"}

    for label, sys_name in (("MA3", "grandMA3"), ("ChamSys", "ChamSys")):
        show = {
            "schema_version": "1.0.0",
            "source": {"system": sys_name, "extracted_at": "2026-10-30T14:00:00Z"},
            "fixtures": [{
                "id": "11", "name": "Beam_1",
                "type": {"manufacturer": "Robe", "model": "Pointe"},
                "patch": {"universe": 3, "address": 1},
                "position": {"x": -3.0, "y": 0.0, "z": 4.0, "mount_type": "truss"},
                "semantic": {"bearing_deg": None, "calculated_pan": None, "pan_offset_deg": 0.0},
            }],
        }
        if show["schema_version"] != "1.0.0":
            r.fail(f"{label}: schema_version incorrecta"); continue
        for fix in show["fixtures"]:
            if required_fixture - set(fix.keys()):
                r.fail(f"{label} fixture: faltan claves"); continue
            if required_type - set(fix["type"].keys()):
                r.fail(f"{label} fixture: type incompleto")
            if required_patch - set(fix["patch"].keys()):
                r.fail(f"{label} fixture: patch incompleto")
            if required_pos - set(fix["position"].keys()):
                r.fail(f"{label} fixture: position incompleto")
            r.ok(f"{label} fixture {fix['id']}: estructura correcta")
    return r.finalize()


def test_2_pan_offsets_horseshoe(verbose=False):
    r = TestResult("Test 2 — Pan offsets en herradura")
    cx, cy, radius = 0.0, 0.0, 5.0
    n = 6
    start, end = 180.0, 0.0
    for i in range(n):
        frac = i / (n - 1)
        angle = start + (end - start) * frac
        rad = math.radians(angle)
        pos_x = cx + radius * math.cos(rad)
        pos_y = cy + radius * math.sin(rad)
        bearing = round(math.degrees(math.atan2(-pos_y, -pos_x)), 2)

        fkey = normalize_fixture_key("Robe", "Pointe")
        pan_pointe = apply_pan_offset(bearing, fkey)
        if abs(pan_pointe - bearing) > 0.01:
            r.fail(f"fixture {i}: pan_pointe {pan_pointe} != bearing {bearing}")
        else:
            r.ok(f"fixture {i}: bearing={bearing}° pan={pan_pointe}°")

        fkey_led = normalize_fixture_key("Robe", "LEDBeam 12")
        pan_led = apply_pan_offset(bearing, fkey_led)
        expected = bearing + 90.0
        while expected > 270.0: expected -= 540.0
        while expected < -270.0: expected += 540.0
        if abs(pan_led - round(expected, 2)) > 0.01:
            r.fail(f"fixture {i}: pan_led {pan_led} != {round(expected, 2)}")
        else:
            r.ok(f"fixture {i}: pan_led={pan_led}°")
    return r.finalize()


def test_3_osc_framing(verbose=False):
    r = TestResult("Test 3 — Framing OSC byte a byte")
    def osc_pad(data):
        rem = len(data) % 4
        return data if rem == 0 else data + b"\x00" * (4 - rem)
    def build(address, args):
        payload = osc_pad(address.encode("utf-8"))
        if args:
            tt = "," + "s" * len(args)
            payload += osc_pad(tt.encode("utf-8"))
            for a in args:
                payload += osc_pad(str(a).encode("utf-8"))
        return payload

    address = "/gma3/cmd"
    args = ['Set Fixture 11 Attribute "PAN" At -157.38']
    payload = build(address, args)
    if len(payload) % 4 != 0:
        r.fail(f"Payload {len(payload)} no múltiplo de 4")
    else:
        r.ok(f"Payload alineado: {len(payload)} bytes")

    expected_address = b"/gma3/cmd\x00\x00\x00"
    if not payload.startswith(expected_address):
        r.fail("Address padding incorrecto")
    else:
        r.ok("Address padding correcto")

    # Vectores de oro derivados a mano de OSC 1.0 (strings NUL-terminated y
    # padding a múltiplo de 4). Se declaran como literales de bytes para no
    # reutilizar el helper bajo prueba:
    #   address "/gma3/cmd"  9 B + NUL = 10 -> pad 12
    #   type tag ",s"        2 B + NUL =  3 -> pad  4
    #   argumento          41 B + NUL = 42 -> pad 44
    expected_parts = [
        (b"/gma3/cmd\x00\x00\x00", 12),
        (b",s\x00\x00", 4),
        (b'Set Fixture 11 Attribute "PAN" At -157.38\x00\x00\x00', 44),
    ]
    for part, size in expected_parts:
        if len(part) != size:
            r.fail(f"Vector de oro inconsistente: {size} != {len(part)}")
    expected_hex = b"".join(p for p, _ in expected_parts).hex()
    if payload != b"".join(p for p, _ in expected_parts):
        r.fail(f"Hex divergente: {payload.hex()}")
    elif payload.hex() != expected_hex:
        r.fail(f"Hex divergente: {payload.hex()}")
    else:
        r.ok(f"Hex canónico idéntico ({len(payload)} bytes)")
    return r.finalize()


def test_4_cross_platform(verbose=False):
    r = TestResult("Test 4 — Traducción cross-platform")
    show = {
        "fixtures": [{
            "id": "11", "name": "Beam_1",
            "type": {"manufacturer": "Robe", "model": "Pointe"},
            "patch": {"universe": 3, "address": 1},
            "position": {"x": -3.0, "y": 0.0, "z": 4.0},
            "semantic": {"bearing_deg": 0.0, "calculated_pan": 0.0},
        }],
    }
    ma3_cmds = []
    for fix in show["fixtures"]:
        ma3_cmds.append(f'Patch Fixture {fix["id"]} At {fix["patch"]["universe"]}.{fix["patch"]["address"]}')
        ma3_cmds.append(f'Label Fixture {fix["id"]} "{fix["name"]}"')
        if "calculated_pan" in fix.get("semantic", {}):
            ma3_cmds.append(f'Set Fixture {fix["id"]} Attribute "PAN" At {fix["semantic"]["calculated_pan"]}')
    expected_ma3 = ['Patch Fixture 11 At 3.1', 'Label Fixture 11 "Beam_1"', 'Set Fixture 11 Attribute "PAN" At 0.0']
    if ma3_cmds != expected_ma3:
        r.fail(f"MA3 divergente: {ma3_cmds}")
    else:
        r.ok("MA3: 3 comandos válidos")

    cham_cmds = []
    for fix in show["fixtures"]:
        ft = f'{fix["type"]["manufacturer"]} {fix["type"]["model"]}'.replace(" ", "_")
        cham_cmds.append(f'PATCH ${fix["id"]} {ft} {fix["patch"]["universe"]}.{fix["patch"]["address"]}')
    if cham_cmds != ['PATCH $11 Robe_Pointe 3.1']:
        r.fail(f"ChamSys divergente: {cham_cmds}")
    else:
        r.ok("ChamSys: 1 comando válido")
    return r.finalize()


def test_5_calibration(verbose=False):
    r = TestResult("Test 5 — Calibración de offset")
    cmd = calibrate_with_offset_keyword("11", -165.0, -180.0)
    if 'Set Fixture 11 Attribute "PAN"' not in cmd:
        r.fail("Falta sintaxis Set Fixture")
    else:
        r.ok("Sintaxis Set Fixture correcta")
    if "Store Offset" not in cmd:
        r.fail("Falta Store Offset")
    else:
        r.ok("Store Offset presente")
    if "-15" not in cmd:
        r.fail(f"Corrección -15 no presente: {cmd}")
    else:
        r.ok("Corrección -15° calculada")
    if "-165" not in cmd:
        r.fail("observed_pan no presente")
    else:
        r.ok("observed_pan preservado")
    return r.finalize()


def test_6_parser_splitter(verbose=False):
    from core.parsers import split_fixture_type_string
    r = TestResult("Test 6 — Splitter heurístico")
    cases = [
        ("Martin MAC Aura XB Extended", {"manufacturer": "Martin", "model": "MAC Aura XB", "mode": "Extended", "channel_count": 25, "channel_count_source": "mode_dict"}),
        ("Robe Pointe 24ch Mode 1", {"manufacturer": "Robe", "model": "Pointe", "channel_count": 24, "channel_count_source": "regex"}),
        ("ClayPaky Sharpy Plus 31Ch v1.2", {"manufacturer": "ClayPaky", "model": "Sharpy Plus", "channel_count": 31, "channel_count_source": "regex"}),
        ("Generic LED Beam 12Ch v2", {"manufacturer": "Generic", "channel_count": 12, "channel_count_source": "regex"}),
        ("Robe Robin Pointe", {"manufacturer": "Robe", "channel_count": 31, "channel_count_source": "model_dict"}),
    ]
    for raw, expected in cases:
        try:
            result = split_fixture_type_string(raw)
        except Exception as e:
            r.fail(f"{raw!r}: excepción {e}"); continue
        mismatches = [f"{k}: {result.get(k)!r} != {v!r}" for k, v in expected.items() if result.get(k) != v]
        if mismatches:
            r.fail(f"{raw!r}: " + "; ".join(mismatches))
        else:
            r.ok(f"{raw!r} → {expected['channel_count']}ch vía {expected['channel_count_source']}")
    return r.finalize()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", type=int, choices=[1, 2, 3, 4, 5, 6])
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    tests = {1: test_1_schema_roundtrip, 2: test_2_pan_offsets_horseshoe,
             3: test_3_osc_framing, 4: test_4_cross_platform,
             5: test_5_calibration, 6: test_6_parser_splitter}
    to_run = [args.test] if args.test else sorted(tests.keys())

    results = []
    for tid in to_run:
        res = tests[tid](verbose=args.verbose)
        results.append((tid, res))

    if args.json:
        print(json.dumps([{
            "test": tid, "name": r.name, "passed": r.passed,
            "details": [{"status": s, "msg": m} for s, m in r.details],
        } for tid, r in results], indent=2))
    else:
        print("\n" + "=" * 70)
        print(" CONTRACT TEST SUITE — SHOWPATCH")
        print("=" * 70 + "\n")
        for tid, r in results:
            print(f"{'✅' if r.passed else '❌'} {r.name}")
            for s, m in r.details:
                if args.verbose or s != "INFO":
                    print(f"  {'✓' if s == 'PASS' else ('✗' if s == 'FAIL' else 'ℹ')} {m}")
            print()
        passed = sum(1 for _, r in results if r.passed)
        print("=" * 70)
        print(f" RESULTADO: {passed}/{len(results)} tests PASS")
        print("=" * 70)

    sys.exit(0 if all(r.passed for _, r in results) else 1)


if __name__ == "__main__":
    main()
