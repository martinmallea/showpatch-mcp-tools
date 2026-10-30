"""Tests de bridges.chamsys_bridge.csv_import."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bridges.chamsys_bridge.csv_import import parse_chamsys_csv  # noqa: E402
from core.schema_validator import validate_show  # noqa: E402

CSV_COMPLETO = (
    "Head,Name,Universe,Address,Fixture Type,X,Y,Z,Mount\n"
    "11,Beam_1,3,1,Robe Pointe Extended,-3.0,0.0,4.0,truss\n"
    "12,Beam_2,3,32,Robe Pointe Extended,3.0,0.0,4.0,truss\n"
)


class TestCsvImport(unittest.TestCase):
    """Importación tolerante de exports ChamSys."""

    def test_dos_filas_completas(self):
        show = parse_chamsys_csv(CSV_COMPLETO)
        self.assertEqual(len(show["fixtures"]), 2)
        self.assertEqual([f["id"] for f in show["fixtures"]], ["11", "12"])
        self.assertEqual(show["fixtures"][0]["name"], "Beam_1")
        self.assertEqual(show["fixtures"][0]["patch"]["universe"], 3)
        self.assertEqual(show["fixtures"][1]["patch"]["address"], 32)
        self.assertEqual(show["fixtures"][0]["type"]["manufacturer"], "Robe")
        self.assertEqual(show["fixtures"][0]["type"]["model"], "Pointe")
        self.assertEqual(show["fixtures"][0]["position"]["z"], 4.0)
        self.assertEqual(validate_show(show), [])

    def test_columna_ausente_no_rompe_el_import(self):
        # Sin las columnas Z ni Fixture Type ni Mount.
        csv_sin_columnas = (
            "Head,Name,Universe,Address,X,Y\n"
            "11,Beam_1,3,1,-3.0,0.0\n"
            "12,Beam_2,3,32,3.0,0.0\n"
        )
        show = parse_chamsys_csv(csv_sin_columnas)
        self.assertEqual(len(show["fixtures"]), 2)
        for fixture in show["fixtures"]:
            self.assertEqual(fixture["position"]["z"], 0.0)
            self.assertEqual(fixture["position"]["mount_type"], "truss")
            self.assertEqual(fixture["position"]["mount_type_source"], "default")
            self.assertEqual(fixture["type"]["manufacturer"], "Generic")
            self.assertEqual(fixture["type"]["model"], "Unknown")
        self.assertEqual(validate_show(show), [])

    def test_cabecera_desconocida_devuelve_lista_vacia(self):
        show = parse_chamsys_csv("Foo,Bar,Baz\n1,2,3\n4,5,6\n")
        self.assertEqual(show["fixtures"], [])
        self.assertEqual(show["schema_version"], "1.0.0")
        self.assertEqual(validate_show(show), [])

    def test_texto_vacio_no_lanza(self):
        for vacio in ("", "   ", None, "\ufeff"):
            self.assertEqual(parse_chamsys_csv(vacio)["fixtures"], [])

    def test_cabeceras_mayusculas_y_alias(self):
        csv_alias = (
            "ID,NAME,UNIV,ADDR,TYPE\n"
            "21,Fr_1,2,101,Martin MAC Aura XB Extended\n"
        )
        show = parse_chamsys_csv(csv_alias)
        self.assertEqual(len(show["fixtures"]), 1)
        fixture = show["fixtures"][0]
        self.assertEqual(fixture["id"], "21")
        self.assertEqual(fixture["patch"], {"universe": 2, "address": 101, "dmx_footprint": 25})

    def test_patch_compacto_y_separador_punto_y_coma(self):
        csv_compacto = "Head;Universe;Address;Fixture Type\n11;3;1;Robe Pointe\n"
        show = parse_chamsys_csv(csv_compacto)
        self.assertEqual(show["fixtures"][0]["patch"]["universe"], 3)
        self.assertEqual(show["fixtures"][0]["patch"]["address"], 1)

        csv_punto = "Head,Address,Fixture Type\n11,3.1,Robe Pointe\n"
        show_punto = parse_chamsys_csv(csv_punto)
        self.assertEqual(show_punto["fixtures"][0]["patch"]["universe"], 3)
        self.assertEqual(show_punto["fixtures"][0]["patch"]["address"], 1)

    def test_metadatos_de_origen(self):
        show = parse_chamsys_csv(CSV_COMPLETO)
        self.assertEqual(show["schema_version"], "1.0.0")
        self.assertEqual(show["source"]["system"], "ChamSys")
        self.assertEqual(show["source"]["coordinate_system"], "stage_center_origin")
        self.assertRegex(show["source"]["extracted_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_semantic_vacio(self):
        for fixture in parse_chamsys_csv(CSV_COMPLETO)["fixtures"]:
            self.assertIsNone(fixture["semantic"]["bearing_deg"])
            self.assertIsNone(fixture["semantic"]["calculated_pan"])
            self.assertEqual(fixture["semantic"]["pan_offset_deg"], 0.0)

    def test_fila_sin_id_se_descarta(self):
        csv_con_hueco = (
            "Head,Name,Universe,Address,Fixture Type\n"
            "11,Beam_1,3,1,Robe Pointe\n"
            ",Huerfano,3,32,Robe Pointe\n"
        )
        show = parse_chamsys_csv(csv_con_hueco)
        self.assertEqual([f["id"] for f in show["fixtures"]], ["11"])

    def test_patch_invalido_se_descarta(self):
        csv_fuera_rango = (
            "Head,Name,Universe,Address,Fixture Type\n"
            "11,Beam_1,3,700,Robe Pointe\n"
            "12,Beam_2,3,32,Robe Pointe\n"
        )
        show = parse_chamsys_csv(csv_fuera_rango)
        self.assertEqual([f["id"] for f in show["fixtures"]], ["12"])
        self.assertEqual(validate_show(show), [])

    def test_acepta_bytes(self):
        show = parse_chamsys_csv(CSV_COMPLETO.encode("utf-8"))
        self.assertEqual(len(show["fixtures"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
