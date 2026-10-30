"""Tests de core.commands y bridges.ma_bridge.emitter."""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bridges.ma_bridge.emitter import (  # noqa: E402
    GENERATED_HEADER,
    escape_lua_string,
    lua_script,
    osc_messages,
)
from core.commands import (  # noqa: E402
    MA3_ALLOWED_VERBS,
    TARGET_CHAMSYS,
    TARGET_MA3,
    _check_ma3_command,
    _filter_ma3,
    to_chamsys,
    to_ma3,
    translate,
)

LUA_CMD_LINE = re.compile(r'^    gma\.cmd\("(?:[^"\\]|\\.)*"\)$')


def contract_show() -> dict:
    """Show mínimo del contrato (tools/contract_test.py, test 4)."""
    return {
        "schema_version": "1.0.0",
        "source": {"system": "grandMA3", "extracted_at": "2026-10-30T14:22:11Z"},
        "fixtures": [{
            "id": "11",
            "name": "Beam_1",
            "type": {"manufacturer": "Robe", "model": "Pointe", "mode": "Extended", "channel_count": 31},
            "patch": {"universe": 3, "address": 1, "dmx_footprint": 31},
            "position": {"x": -3.0, "y": 0.0, "z": 4.0},
            "semantic": {"bearing_deg": 0.0, "calculated_pan": 0.0},
        }],
    }


class TestMA3Commands(unittest.TestCase):
    """Sintaxis nativa MA3 y reglas de escapado/allowlist."""

    def test_tres_comandos_exactos_del_contrato(self):
        self.assertEqual(to_ma3(contract_show()), [
            "Patch Fixture 11 At 3.1",
            'Label Fixture 11 "Beam_1"',
            'Set Fixture 11 Attribute "PAN" At 0.0',
        ])

    def test_orden_patch_label_set(self):
        comandos = to_ma3(contract_show())
        self.assertEqual([c.split()[0] for c in comandos], ["Patch", "Label", "Set"])

    def test_label_con_comilla_doble_no_rompe_el_comando(self):
        show = contract_show()
        show["fixtures"][0]["name"] = 'Beam "A"'
        label = to_ma3(show)[1]
        self.assertEqual(label, "Label Fixture 11 'Beam \"A\"'")
        # El argumento va entre comillas simples: las dobles internas no cierran
        # el argumento, así que el comando sigue siendo de un solo label.
        self.assertTrue(label.endswith("'") and "'Beam" in label)

    def test_label_con_ambas_comillas_se_degrada_y_avisa(self):
        show = contract_show()
        show["fixtures"][0]["name"] = "Beam \"A\" 'B'"
        resultado = translate(show, "ma3")
        label = resultado["commands"][1]
        self.assertTrue(label.startswith('Label Fixture 11 "'), label)
        self.assertEqual(label.count('"'), 2)
        interior = label[len('Label Fixture 11 "'):-1]
        self.assertNotIn('"', interior)
        self.assertTrue(any("degradaron" in w for w in resultado["warnings"]), resultado["warnings"])

    def test_patch_invalido_se_omite_con_warning(self):
        show = contract_show()
        show["fixtures"][0]["patch"] = {"universe": 3, "address": 600}
        resultado = translate(show, "grandMA3")
        self.assertEqual(resultado["commands"], [])
        self.assertTrue(resultado["warnings"])

    def test_allowlist_rechaza_verbos_fuera_de_lista(self):
        for verbo in MA3_ALLOWED_VERBS:
            ok, motivo = _check_ma3_command(f'{verbo} Fixture 11 At 3.1')
            self.assertTrue(ok, f"{verbo} debería estar permitido: {motivo}")

        for invalido in ("At Fixture 11", "DMX 255 At 3.1", "Run Macro 1", ""):
            ok, motivo = _check_ma3_command(invalido)
            self.assertFalse(ok, f"{invalido!r} no debería pasar")
            self.assertTrue(motivo)

    def test_filtro_descarta_y_reporta(self):
        warnings = []
        kept = _filter_ma3(
            ["Patch Fixture 11 At 3.1", "DMX 255 At 3.1", "Label Fixture 11 \"x\""],
            warnings,
        )
        self.assertEqual(kept, ["Patch Fixture 11 At 3.1", 'Label Fixture 11 "x"'])
        self.assertEqual(len(warnings), 1)
        self.assertIn("DMX 255", warnings[0])

    def test_nunca_emite_dmx_crudo(self):
        for comando in to_ma3(contract_show()):
            self.assertNotRegex(comando.upper(), r"\bDMX\b")

    def test_pan_con_offset_de_modelo(self):
        show = contract_show()
        show["fixtures"][0]["type"] = {"manufacturer": "Robe", "model": "LEDBeam 12"}
        show["fixtures"][0]["semantic"] = {
            "bearing_deg": None, "calculated_pan": -157.38, "pan_offset_deg": 90.0,
        }
        pan = to_ma3(show)[-1]
        # apply_pan_offset(-157.38, "Robe_LEDBeam_12") = -157.38 + 90.0
        self.assertEqual(pan, 'Set Fixture 11 Attribute "PAN" At -67.38')

    def test_sin_pan_offset_deg_el_valor_se_emite_literal(self):
        show = contract_show()
        show["fixtures"][0]["semantic"] = {"calculated_pan": -157.38}
        self.assertEqual(
            to_ma3(show)[-1], 'Set Fixture 11 Attribute "PAN" At -157.38'
        )

    def test_semantic_sin_calculated_pan_no_emite_set(self):
        show = contract_show()
        show["fixtures"][0]["semantic"] = {"calculated_pan": None}
        comandos = to_ma3(show)
        self.assertEqual(len(comandos), 2)
        self.assertFalse(any(c.startswith("Set ") for c in comandos))


class TestChamSysCommands(unittest.TestCase):
    """Sintaxis PATCH de ChamSys."""

    def test_comando_exacto_del_contrato(self):
        self.assertEqual(to_chamsys(contract_show()), ["PATCH $11 Robe_Pointe 3.1"])

    def test_tipo_con_espacios_usa_guiones_bajos(self):
        show = contract_show()
        show["fixtures"][0]["type"] = {"manufacturer": "Martin", "model": "MAC Aura XB"}
        self.assertEqual(to_chamsys(show), ["PATCH $11 Martin_MAC_Aura_XB 3.1"])

    def test_dos_fixtures_dos_comandos(self):
        show = contract_show()
        show["fixtures"].append({
            "id": "12", "name": "Beam_2",
            "type": {"manufacturer": "Robe", "model": "Pointe"},
            "patch": {"universe": 3, "address": 32},
        })
        self.assertEqual(to_chamsys(show), [
            "PATCH $11 Robe_Pointe 3.1",
            "PATCH $12 Robe_Pointe 3.32",
        ])


class TestTranslate(unittest.TestCase):
    """Contrato de translate()."""

    def test_forma_de_la_respuesta(self):
        resultado = translate(contract_show(), "grandMA3")
        self.assertEqual(set(resultado), {"target", "commands", "warnings"})
        self.assertEqual(resultado["target"], TARGET_MA3)
        self.assertIsInstance(resultado["warnings"], list)

    def test_alias_ma3_y_ma(self):
        for alias in ("ma3", "MA", "GrandMA3", " grandma3 "):
            self.assertEqual(translate(contract_show(), alias)["target"], TARGET_MA3)

    def test_target_chamsys(self):
        resultado = translate(contract_show(), "chamsys")
        self.assertEqual(resultado["target"], TARGET_CHAMSYS)
        self.assertEqual(resultado["commands"], ["PATCH $11 Robe_Pointe 3.1"])

    def test_target_invalido_lanza_value_error(self):
        with self.assertRaises(ValueError):
            translate(contract_show(), "obs")


class TestOscMessages(unittest.TestCase):
    """Mensajes OSC derivados de to_ma3."""

    def test_un_mensaje_por_comando(self):
        mensajes = osc_messages(contract_show())
        self.assertEqual(len(mensajes), 3)
        self.assertEqual(mensajes[0], {
            "address": "/gma3/cmd", "args": ["Patch Fixture 11 At 3.1"],
        })
        self.assertEqual([m["args"][0] for m in mensajes], to_ma3(contract_show()))

    def test_prefix_personalizado(self):
        mensajes = osc_messages(contract_show(), prefix="/gma3/cmd/custom")
        self.assertTrue(all(m["address"] == "/gma3/cmd/custom" for m in mensajes))


class TestLuaScript(unittest.TestCase):
    """Plugin MA3 generado: cabecera, cuerpo y escapado."""

    def _show_con_caracteres_especiales(self) -> dict:
        show = contract_show()
        show["fixtures"][0]["name"] = 'Beam "A" \\ B'
        return show

    def test_cabecera_y_estructura(self):
        script = lua_script(contract_show(), "WP05_demo")
        self.assertTrue(script.startswith(GENERATED_HEADER + "\n"), script[:80])
        self.assertEqual(script.count("return function()"), 1)
        self.assertTrue(script.endswith("end\n"))

    def test_una_linea_gma_cmd_por_comando(self):
        comandos = to_ma3(contract_show())
        script = lua_script(contract_show(), "WP05_demo")
        self.assertEqual(script.count("gma.cmd("), len(comandos))
        self.assertEqual(
            [line for line in script.splitlines() if "gma.cmd(" in line],
            [f'    gma.cmd("{escape_lua_string(c)}")' for c in comandos],
        )

    def test_escapa_comilla_y_barra_invertida(self):
        script = lua_script(self._show_con_caracteres_especiales(), 'macro "x" \\ y')
        self.assertIn('\\"', script)
        self.assertIn("\\\\", script)
        self.assertEqual(script.count("gma.cmd("), 3)
        self.assertIn(
            '    gma.cmd("Label Fixture 11 \'Beam \\"A\\" \\\\ B\'")',
            script.splitlines(),
        )

    def test_todas_las_lineas_de_comando_son_lua_valido(self):
        script = lua_script(self._show_con_caracteres_especiales(), "WP05_demo")
        lineas_cmd = [ln for ln in script.splitlines() if "gma.cmd(" in ln]
        self.assertTrue(lineas_cmd)
        for linea in lineas_cmd:
            self.assertRegex(linea, LUA_CMD_LINE)
        # Un string Lua por línea: no hay saltos de línea crudos dentro de un
        # literal, por eso el número de comillas es par.
        for linea in lineas_cmd:
            self.assertEqual(linea.count('"') % 2, 0, linea)

    def test_salto_de_linea_en_label_se_escapa(self):
        show = contract_show()
        show["fixtures"][0]["name"] = "Beam\n1"
        script = lua_script(show, "WP05_demo")
        for linea in script.splitlines():
            self.assertTrue(LUA_CMD_LINE.match(linea) or not linea.strip().startswith("gma.cmd("))

    def test_escapado_de_orden_correcto(self):
        self.assertEqual(escape_lua_string('a\\b"c\nd'), 'a\\\\b\\"c\\nd')


if __name__ == "__main__":
    unittest.main(verbosity=2)
