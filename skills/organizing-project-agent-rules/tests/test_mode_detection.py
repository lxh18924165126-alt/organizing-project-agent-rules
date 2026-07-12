from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "inventory_agent_rules.py"


def load_module():
    spec = importlib.util.spec_from_file_location("inventory_mode", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ModeDetectionTests(unittest.TestCase):
    def test_bootstrap_for_small_repo_without_agents(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
            report = module.collect_inventory(root)
            self.assertEqual(report["mode"], "bootstrap")
            self.assertFalse(report["root_agents_exists"])
            candidates = report["evidence_candidates"]
            self.assertTrue(any(item["source"] == "pyproject.toml" for item in candidates))
            self.assertTrue(all(item["id"].startswith("E-") for item in candidates))
            self.assertTrue(all(item["existing_explicit_rule"] is False for item in candidates))

    def test_bootstrap_preserves_nested_agents_and_detects_monorepo_domains(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "apps" / "web").mkdir(parents=True)
            (root / "services" / "api").mkdir(parents=True)
            (root / "packages" / "contracts").mkdir(parents=True)
            (root / "services" / "api" / "AGENTS.md").write_text(
                "# API rules\n\n- Never log tokens.\n", encoding="utf-8"
            )
            (root / "apps" / "web" / "package.json").write_text(
                '{"dependencies":{"react":"latest"}}', encoding="utf-8"
            )
            (root / "services" / "api" / "main.py").write_text("pass\n", encoding="utf-8")
            (root / "packages" / "contracts" / "schema.json").write_text("{}\n", encoding="utf-8")
            report = module.collect_inventory(root)
            self.assertEqual(report["mode"], "bootstrap")
            self.assertIn("services/api/AGENTS.md", {x["path"] for x in report["instruction_files"]})
            self.assertTrue(report["domain_signals"]["frontend"])
            self.assertTrue(report["domain_signals"]["backend"])
            self.assertTrue(report["domain_signals"]["contracts"])
            self.assertIn(
                "packages/contracts/schema.json",
                {item["source"] for item in report["evidence_candidates"]},
            )

    def test_migrate_repair_and_audit_modes(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "AGENTS.md").write_text("# Rules\n\n- Keep changes scoped.\n", encoding="utf-8")
            self.assertEqual(module.collect_inventory(root)["mode"], "migrate")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "docs" / "agent" / "domains").mkdir(parents=True)
            (root / "AGENTS.md").write_text(
                "# Rules\n\n## Rule routing\n- [backend](docs/agent/domains/missing.md)\n",
                encoding="utf-8",
            )
            self.assertEqual(module.collect_inventory(root)["mode"], "repair")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            route = root / "docs" / "agent" / "domains" / "backend.md"
            route.parent.mkdir(parents=True)
            route.write_text("# Backend\n\n- Keep handlers thin.\n", encoding="utf-8")
            (root / "AGENTS.md").write_text(
                "# Rules\n\n## Basic conventions\n- Keep changes scoped.\n\n"
                "## Project context\n- Python API.\n\n## Risk and change scale\n- Use impact.\n\n"
                "## Technology and documentation\n- See manifests.\n\n"
                "## Rule routing\n- [backend](docs/agent/domains/backend.md)\n\n"
                "## Documentation and checkpoints\n- Update affected docs.\n\n"
                "## Minimum verification\n- Run focused checks.\n\n## Prohibitions\n- No production changes.\n\n"
                "## Architecture guardrails\n- Keep boundaries.\n\n"
                "## Optional workflows and rule precedence\n- Explicit only.\n",
                encoding="utf-8",
            )
            self.assertEqual(module.collect_inventory(root)["mode"], "audit")

    def test_detects_anomalous_instruction_names_without_treating_them_as_authority(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "Agents.md").write_text("# Maybe rules\n", encoding="utf-8")
            (root / "CLAUDE.md").write_text("# Other assistant\n", encoding="utf-8")
            report = module.collect_inventory(root)
            self.assertIn("Agents.md", report["anomalous_instruction_files"])
            self.assertIn("CLAUDE.md", report["assistant_evidence_files"])
            self.assertEqual(report["instruction_files"], [])

    def test_requested_mode_reports_applicability_and_inventory_is_idempotent(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            first = module.collect_inventory(root, requested_mode="audit")
            second = module.collect_inventory(root, requested_mode="audit")
            self.assertEqual(first, second)
            self.assertEqual(first["mode"], "audit")
            self.assertFalse(first["mode_applicable"])
            self.assertFalse(first["domain_signals"]["frontend"])
            self.assertFalse(first["domain_signals"]["database"])

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "AGENTS.md").write_text("# Rules\n\n- Keep changes scoped.\n", encoding="utf-8")
            requested = module.collect_inventory(root, requested_mode="audit")
            self.assertEqual(requested["mode"], "audit")
            self.assertFalse(requested["mode_applicable"])
            self.assertTrue(any("automatic mode is migrate" in reason for reason in requested["mode_reasons"]))

    def test_single_client_directory_is_not_sufficient_frontend_evidence(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "client").mkdir()
            (root / "client" / "sdk.py").write_text("class ApiClient: pass\n", encoding="utf-8")
            report = module.collect_inventory(root)
            self.assertFalse(report["domain_signals"]["frontend"])

    def test_existing_routing_over_hard_budget_enters_repair(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            route = root / "docs" / "agent" / "domains" / "backend.md"
            route.parent.mkdir(parents=True)
            route.write_text("# Backend\n\n- Keep handlers thin.\n", encoding="utf-8")
            (root / "AGENTS.md").write_text(
                "# Rules\n\n## Rule routing\n- [backend](docs/agent/domains/backend.md)\n" + "x" * 7000,
                encoding="utf-8",
            )
            self.assertEqual(module.collect_inventory(root)["mode"], "repair")


if __name__ == "__main__":
    unittest.main()
