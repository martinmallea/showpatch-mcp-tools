"""Tests del orquestador: el DAG, los gates y la evidencia deben ser fiables."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from orchestrator import state as state_store  # noqa: E402
from orchestrator.cli import render_brief  # noqa: E402
from orchestrator.evidence import fingerprint, run_gate  # noqa: E402
from orchestrator.plan import (  # noqa: E402
    PlanError,
    is_ready,
    load_plan,
    ready_ids,
    topological_order,
    validate_plan,
    work_packages,
)


def synthetic_plan(dependencies: dict[str, list[str]], owners: dict[str, str] | None = None) -> dict:
    owners = owners or {}
    return {
        "work_packages": [
            {
                "id": wid,
                "title": wid,
                "owner": owners.get(wid, "SUB-QA"),
                "depends_on": deps,
                "gates": [{"id": f"G-{wid}", "type": "file", "path": "README.md"}],
            }
            for wid, deps in dependencies.items()
        ]
    }


class TestRealPlan(unittest.TestCase):
    def test_plan_is_valid(self):
        plan = load_plan()
        self.assertEqual(validate_plan(plan), [])
        self.assertGreaterEqual(len(plan["work_packages"]), 10)

    def test_every_package_has_gates_and_owner(self):
        for wid, package in work_packages(load_plan()).items():
            self.assertTrue(package["gates"], f"{wid} sin gates")
            self.assertTrue(package["owner"].startswith(("ORQ", "SUB-")), f"{wid} owner raro")

    def test_topological_order_puts_dependencies_first(self):
        plan = load_plan()
        order = topological_order(plan)
        position = {wid: i for i, wid in enumerate(order)}
        for wid, package in work_packages(plan).items():
            for dependency in package.get("depends_on") or []:
                self.assertLess(position[dependency], position[wid], f"{dependency} debe ir antes que {wid}")

    def test_only_roots_ready_at_start(self):
        """Sin estado previo sólo están listos los WP sin dependencias."""
        plan = load_plan()
        state = {"work_packages": {}}
        roots = sorted(wid for wid, pkg in work_packages(plan).items() if not pkg.get("depends_on"))
        self.assertEqual(sorted(ready_ids(plan, state)), roots)


class TestPlanValidation(unittest.TestCase):
    def test_detects_cycle(self):
        problems = validate_plan(synthetic_plan({"A": ["B"], "B": ["A"]}))
        self.assertTrue(any("Ciclo" in p for p in problems))

    def test_detects_unknown_dependency(self):
        problems = validate_plan(synthetic_plan({"A": ["Z"]}))
        self.assertTrue(any("no existe" in p for p in problems))

    def test_detects_unknown_owner(self):
        problems = validate_plan(synthetic_plan({"A": []}, {"A": "PIRATA"}))
        self.assertTrue(any("owner desconocido" in p for p in problems))

    def test_detects_duplicate_ids(self):
        plan = synthetic_plan({"A": []})
        plan["work_packages"].append(dict(plan["work_packages"][0]))
        self.assertTrue(any("duplicado" in p for p in validate_plan(plan)))

    def test_rejects_empty_package_without_gates(self):
        plan = synthetic_plan({"A": []})
        plan["work_packages"][0]["gates"] = []
        self.assertTrue(any("sin gates" in p for p in validate_plan(plan)))

    def test_cycle_raises_on_order(self):
        with self.assertRaises(PlanError):
            topological_order(synthetic_plan({"A": ["B"], "B": ["A"]}))


class TestReadiness(unittest.TestCase):
    def test_blocked_until_dependency_done(self):
        plan = load_plan()
        state = {"work_packages": {"WP-01": {"status": "done"}}}
        self.assertTrue(is_ready(plan, state, "WP-02"))
        self.assertFalse(is_ready(plan, state, "WP-06"))
        self.assertIn("WP-03", ready_ids(plan, state))

    def test_done_package_is_not_ready(self):
        plan = load_plan()
        state = {"work_packages": {"WP-01": {"status": "done"}}}
        self.assertFalse(is_ready(plan, state, "WP-01"))


class TestGates(unittest.TestCase):
    def test_file_gate(self):
        self.assertTrue(run_gate({"id": "G", "type": "file", "path": "README.md"})["ok"])
        self.assertFalse(run_gate({"id": "G", "type": "file", "path": "no_existe.md"})["ok"])

    def test_command_gate_ok(self):
        result = run_gate({"id": "G", "type": "command", "argv": ["{python}", "-c", "print('ok')"]})
        self.assertTrue(result["ok"])
        self.assertEqual(result["exit"], 0)
        self.assertIn("ok", result["stdout_tail"])
        self.assertEqual(result["argv"][0], sys.executable)

    def test_command_gate_failure_is_reported_not_raised(self):
        result = run_gate({"id": "G", "type": "command", "argv": ["{python}", "-c", "raise SystemExit(7)"]})
        self.assertFalse(result["ok"])
        self.assertEqual(result["exit"], 7)


class TestEvidenceAndState(unittest.TestCase):
    def test_fingerprint_is_stable_and_sized(self):
        self.assertEqual(fingerprint(), fingerprint())
        self.assertEqual(len(fingerprint()), 64)

    def test_state_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            state = state_store.load_state(path)
            self.assertEqual(state["work_packages"], {})
            state_store.set_status(state, "WP-01", "in_progress")
            state_store.set_status(state, "WP-01", "done", evidence="evidence/x.json")
            state_store.save_state(state, path)
            reloaded = state_store.load_state(path)
            record = reloaded["work_packages"]["WP-01"]
            self.assertEqual(record["status"], "done")
            self.assertEqual(record["attempts"], 1)
            self.assertEqual(record["evidence"], ["evidence/x.json"])

    def test_state_rejects_unknown_status(self):
        state = state_store.load_state(Path("no_existe.json"))
        with self.assertRaises(ValueError):
            state_store.set_status(state, "WP-01", "inventado")


class TestBrief(unittest.TestCase):
    def test_brief_is_self_contained(self):
        plan = load_plan()
        brief = render_brief(plan, {"work_packages": {"WP-01": {"status": "done"}}}, "WP-03")
        self.assertIn("WP-03", brief)
        self.assertIn("SUB-GEOMETRY", brief)
        self.assertIn("WP-01 (done)", brief)
        self.assertIn("core/intelligence.py", brief)
        self.assertIn("python bridge.py orchestrate gate WP-03", brief)
        self.assertIn("[ ]", brief)

    def test_every_brief_renders(self):
        plan = load_plan()
        for wid in plan["work_packages"]:
            brief = render_brief(plan, {"work_packages": {}}, wid["id"])
            self.assertGreater(len(brief), 200)


class TestPlanFileIsJSON(unittest.TestCase):
    def test_plan_serializes(self):
        text = (ROOT / "orchestration" / "work_packages.json").read_text(encoding="utf-8")
        self.assertIn("work_packages", json.loads(text))


if __name__ == "__main__":
    unittest.main()
