"""Tests de core.ma3_xml: parser tolerante de exports XML de grandMA3."""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.ma3_xml import parse_ma3_xml, parse_ma3_xml_string
from core.schema_validator import validate_show

SAMPLE_XML = ROOT / "tests" / "fixtures" / "ma3_export_sample.xml"

ISO_UTC_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class TestMuestraMa3(unittest.TestCase):
    """Casos sobre el fixture XML de muestra (5 nodos, 1 descartable)."""

    @classmethod
    def setUpClass(cls):
        cls.show = parse_ma3_xml(SAMPLE_XML)
        cls.by_id = {fixture["id"]: fixture for fixture in cls.show["fixtures"]}

    def test_fixture_completo_sin_rotacion(self):
        fixture = self.by_id["101"]
        self.assertEqual(fixture["name"], "Beam_1")
        self.assertEqual(
            fixture["type"],
            {"manufacturer": "Robe", "model": "Pointe", "mode": "Mode 1", "channel_count": 24},
        )
        self.assertEqual(fixture["patch"], {"universe": 3, "address": 1, "dmx_footprint": 24})
        position = fixture["position"]
        self.assertEqual((position["x"], position["y"], position["z"]), (-3.0, 0.0, 4.0))
        self.assertEqual(position["unit"], "meters")
        self.assertEqual(
            position["rotation"], {"pan_deg": 0.0, "tilt_deg": 0.0, "roll_deg": 0.0}
        )
        # Sin rotación no se declara montaje.
        self.assertNotIn("mount_type", position)
        self.assertNotIn("mount_type_source", position)
        self.assertEqual(fixture["channels"], [1, 2, 3])
        self.assertEqual(
            fixture["semantic"],
            {"bearing_deg": None, "calculated_pan": None, "pan_offset_deg": 0.0},
        )

    def test_alias_de_atributos(self):
        # nr/label/type/address/Coordinates + Rotation en nodos hijos.
        fixture = self.by_id["102"]
        self.assertEqual(fixture["name"], "Wash_1")
        self.assertEqual(fixture["type"]["manufacturer"], "Martin")
        self.assertEqual(fixture["type"]["model"], "MAC Aura XB")
        self.assertEqual(fixture["type"]["mode"], "Extended")
        self.assertEqual(fixture["type"]["channel_count"], 25)
        self.assertEqual(fixture["patch"]["universe"], 3)
        self.assertEqual(fixture["patch"]["address"], 25)
        self.assertEqual(fixture["position"]["rotation"]["pan_deg"], 90.0)
        self.assertEqual(fixture["position"]["mount_type"], "truss")
        self.assertEqual(fixture["position"]["mount_type_source"], "extractor")

    def test_rotacion_sin_mount_type_usa_truss_por_defecto(self):
        fixture = self.by_id["105"]
        self.assertEqual(fixture["position"]["rotation"]["pan_deg"], -45.0)
        self.assertEqual(fixture["position"]["mount_type"], "truss")
        self.assertEqual(fixture["position"]["mount_type_source"], "default")
        self.assertEqual(
            (fixture["position"]["x"], fixture["position"]["y"], fixture["position"]["z"]),
            (1.5, -2.0, 5.5),
        )

    def test_tipo_sin_canal_declarado_se_resuelve_a_cero(self):
        fixture = self.by_id["103"]
        self.assertEqual(fixture["type"]["manufacturer"], "Acme")
        self.assertEqual(fixture["type"]["channel_count"], 0)
        self.assertEqual(fixture["patch"]["dmx_footprint"], 0)
        self.assertNotIn("channels", fixture)

    def test_patch_invalido_descarta_y_cuenta(self):
        ids = [fixture["id"] for fixture in self.show["fixtures"]]
        self.assertEqual(ids, ["101", "102", "103", "105"])
        self.assertNotIn("104", self.by_id)
        self.assertEqual(
            self.show["metadata"]["extensions"]["ma3"]["discarded_fixtures"], 1
        )

    def test_cabecera_del_documento(self):
        source = self.show["source"]
        self.assertEqual(self.show["schema_version"], "1.0.0")
        self.assertEqual(source["system"], "grandMA3")
        self.assertEqual(source["session_name"], "Tour_2026_Act1")
        self.assertEqual(source["coordinate_system"], "stage_center_origin")
        self.assertRegex(source["extracted_at"], ISO_UTC_Z)
        self.assertEqual(
            self.show["metadata"]["extensions"]["ma3"]["session_name"], "Tour_2026_Act1"
        )

    def test_documento_de_muestra_pasa_validacion(self):
        self.assertEqual(validate_show(self.show), [])


class TestParseoDefensivo(unittest.TestCase):
    """Entradas degeneradas: no deben lanzar excepción."""

    def test_patch_inexistente_descarta_y_cuenta(self):
        xml = """
        <MA3 session_name="Tests">
          <Fixture id="201" name="Sin_Patch" fixture_type="Robe Pointe"/>
          <Fixture name="Sin_ID" patch="1.1"/>
          <FixtureNode nr="202" label="Ok" type="Generic Beam 7R" patch="1.1"/>
        </MA3>
        """
        show = parse_ma3_xml_string(xml)
        self.assertEqual([fixture["id"] for fixture in show["fixtures"]], ["202"])
        self.assertEqual(
            show["metadata"]["extensions"]["ma3"]["discarded_fixtures"], 2
        )
        self.assertEqual(validate_show(show), [])

    def test_xml_vacio_devuelve_lista_vacia(self):
        for xml in ("", "   ", "\n"):
            with self.subTest(xml=xml):
                show = parse_ma3_xml_string(xml)
                self.assertEqual(show["fixtures"], [])
                self.assertNotIn("session_name", show["source"])
                self.assertEqual(
                    show["metadata"]["extensions"]["ma3"]["discarded_fixtures"], 0
                )

    def test_xml_truncado_no_lanza_y_anota_el_error(self):
        show = parse_ma3_xml_string("<MA3><Fixture id='1' patch='1.1'>")
        self.assertEqual(show["fixtures"], [])
        self.assertIn("parse_error", show["metadata"]["extensions"]["ma3"])

    def test_sesion_explicita_gana_sobre_la_raiz(self):
        show = parse_ma3_xml_string('<MA3 session_name="Raiz"/>', session_name="Override")
        self.assertEqual(show["source"]["session_name"], "Override")


if __name__ == "__main__":
    unittest.main(verbosity=2)
