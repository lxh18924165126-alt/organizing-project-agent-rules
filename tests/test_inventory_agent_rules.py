from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "inventory_agent_rules.py"


def load_module():
    spec = importlib.util.spec_from_file_location("inventory_agent_rules", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest_tree(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            result[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return result


class InventoryAgentRulesTests(unittest.TestCase):
    def make_repo(self, root: Path) -> None:
        (root / ".codex" / "rules").mkdir(parents=True)
        (root / "services" / "api").mkdir(parents=True)
        (root / "docs" / "agent").mkdir(parents=True)
        (root / "src").mkdir(parents=True)
        (root / "generated").mkdir(parents=True)
        (root / "AGENTS.md").write_text(
            "# Rules\n\n"
            "- Preserve user changes.\n"
            "- Read [API rules][api-rules].\n"
            "- Read [missing rules](docs/agent/missing.md).\n",
            encoding="utf-8",
        )
        (root / "services" / "api" / "AGENTS.override.md").write_text(
            "# API override\n\n- Never log tokens.\n", encoding="utf-8"
        )
        (root / "TEAM_RULES.md").write_text(
            "# Team rules\n\n- Run focused tests.\n", encoding="utf-8"
        )
        (root / "ALT_RULES.md").write_text(
            "# Alternate rules\n\nNever log secrets.\n\n"
            "| Area | Rule |\n|---|---|\n| Data | Preserve tenant isolation. |\n\n"
            "- Keep generated clients read-only\n  and regenerate them from schemas.\n",
            encoding="utf-8",
        )
        (root / "docs" / "agent" / "api.md").write_text(
            "# API rules\n\n- Keep handlers thin.\n", encoding="utf-8"
        )
        (root / "docs" / "backend-guidance.md").write_text(
            "# Backend guidance\n\nNever log tokens.\n", encoding="utf-8"
        )
        (root / "docs" / "backend.md").write_text(
            "# Backend\n\n- All requests require authorization.\n", encoding="utf-8"
        )
        (root / ".codex" / "config.toml").write_text(
            "project_doc_fallback_filenames = [\n"
            '  "TEAM_RULES.md",\n'
            '  "ALT_RULES.md",\n'
            "]\n",
            encoding="utf-8",
        )
        (root / ".codex" / "rules" / "safe.rules").write_text(
            "forbid production apply\n", encoding="utf-8"
        )
        (root / "package.json").write_text(
            '{"name":"fixture","engines":{"node":">=20"}}\n', encoding="utf-8"
        )
        (root / ".nvmrc").write_text("20\n", encoding="utf-8")
        (root / "README.md").write_text(
            "# Product\n\n- Marketing feature list, not an Agent rule.\n",
            encoding="utf-8",
        )
        (root / "src" / "main.py").write_text("def main():\n    return 0\n", encoding="utf-8")
        (root / "generated" / "client.generated.ts").write_text(
            "// generated\n", encoding="utf-8"
        )
        with (root / "AGENTS.md").open("a", encoding="utf-8") as handle:
            handle.write(
                "- Read [README](README.md) for project context.\n"
                "- Backend work: [backend guidance](docs/backend-guidance.md).\n"
                "\n## Rule routing\n"
                "- Backend: [Backend](docs/backend.md).\n"
                "\n[api-rules]: docs/agent/api.md\n"
            )

    def test_collects_instruction_graph_sources_and_rule_candidates(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.make_repo(root)

            report = module.collect_inventory(root)

            instruction_paths = {item["path"] for item in report["instruction_files"]}
            self.assertEqual(
                instruction_paths,
                {
                    "AGENTS.md",
                    "services/api/AGENTS.override.md",
                    "TEAM_RULES.md",
                    "ALT_RULES.md",
                },
            )
            self.assertIn(
                {"source": "AGENTS.md", "target": "docs/agent/api.md", "exists": True},
                report["link_graph"],
            )
            self.assertIn(
                {"source": "AGENTS.md", "target": "docs/agent/missing.md", "exists": False},
                report["link_graph"],
            )
            referenced_paths = {item["path"] for item in report["referenced_documents"]}
            self.assertIn("docs/agent/api.md", referenced_paths)
            self.assertIn("docs/backend-guidance.md", referenced_paths)
            self.assertIn("docs/backend.md", referenced_paths)
            self.assertIn("README.md", referenced_paths)
            self.assertTrue(
                all(item["bytes"] > 0 and item["lines"] > 0 for item in report["referenced_documents"])
            )
            self.assertIn("package.json", report["candidate_sources"])
            self.assertIn(".nvmrc", report["candidate_sources"])
            self.assertIn(".codex/rules/safe.rules", report["candidate_sources"])
            self.assertIn("README.md", report["candidate_sources"])
            self.assertIn("src/main.py", report["candidate_sources"])
            self.assertIn("generated/client.generated.ts", report["candidate_sources"])
            self.assertTrue(
                any(item["text"] == "Preserve user changes." for item in report["rule_candidates"])
            )
            self.assertTrue(
                any(item["text"] == "Never log secrets." for item in report["rule_candidates"])
            )
            self.assertTrue(
                any(item["text"] == "Never log tokens." for item in report["rule_candidates"])
            )
            self.assertTrue(
                any(
                    item["text"] == "All requests require authorization."
                    for item in report["rule_candidates"]
                )
            )
            self.assertTrue(
                any("Preserve tenant isolation" in item["text"] for item in report["rule_candidates"])
            )
            self.assertTrue(
                any(
                    item["text"]
                    == "Keep generated clients read-only and regenerate them from schemas."
                    for item in report["rule_candidates"]
                )
            )
            self.assertFalse(
                any("Marketing feature list" in item["text"] for item in report["rule_candidates"])
            )
            self.assertTrue(
                any("missing.md" in warning for warning in report["warnings"])
            )

    def test_json_cli_is_read_only_and_emits_stable_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.make_repo(root)
            before = digest_tree(root)

            command = [sys.executable, str(SCRIPT), "--repo", str(root), "--json"]
            completed = subprocess.run(command, check=False, capture_output=True, text=True)
            repeated = subprocess.run(command, check=False, capture_output=True, text=True)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertEqual(completed.stdout, repeated.stdout)
            report = json.loads(completed.stdout)
            self.assertEqual(report["schema_version"], 1)
            self.assertEqual(Path(report["root"]), root.resolve())
            self.assertIn("instruction_files", report)
            self.assertIn("rule_candidates", report)
            self.assertEqual(before, digest_tree(root))

    def test_flags_runtime_config_only_inside_repository_rule_documents(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            home = Path(temp_dir) / "home"
            root.mkdir()
            (home / ".codex").mkdir(parents=True)
            (home / ".codex" / "config.toml").write_text(
                "model_context_window = 999999\nHOME_ONLY_SENTINEL = true\n",
                encoding="utf-8",
            )
            (root / "AGENTS.md").write_text(
                "# Rules\n\n- Set model_context_window = 272000.\n"
                "- Copy ~/.codex/config.toml before work.\n",
                encoding="utf-8",
            )

            report = module.collect_inventory(root)

            findings = report["suspected_runtime_config"]
            self.assertEqual({item["source"] for item in findings}, {"AGENTS.md"})
            self.assertTrue(any(item["kind"] == "context-window" for item in findings))
            self.assertTrue(any(item["kind"] == "user-config-path" for item in findings))
            self.assertFalse(any("HOME_ONLY_SENTINEL" in str(item) for item in findings))


if __name__ == "__main__":
    unittest.main()
