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
SCRIPT = SKILL_DIR / "scripts" / "validate_agent_rules.py"


def load_module():
    spec = importlib.util.spec_from_file_location("validate_agent_rules", SCRIPT)
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


def root_document(
    extra: str = "", route_target: str = "docs/agent/domains/backend.md"
) -> str:
    return f"""# Repository Agent Rules

## Basic conventions
- Preserve user changes.
- Keep changes scoped.

## Project context
- This repository contains a Python API.

## Risk and change scale
- Classify by actual data, security, contract, and infrastructure impact.

## Technology and documentation
- Python 3.12 is declared in `pyproject.toml`.

## Rule routing
- API work: [backend rules]({route_target}).

## Documentation and checkpoints
- Update affected behavior documentation; checkpoints are internal checks.

## Minimum verification
- Inspect the final diff and run the narrowest relevant checks.

## Prohibitions
- Do not change production state without a separately scoped request.

## Architecture guardrails
- The API is the only database writer.

## Optional workflows and rule precedence
- Optional workflows require an explicit user request.
- Platform constraints outrank current user scope, root rules, routed rules, and convention.
{extra}
"""


def ledger(rows: list[str]) -> str:
    header = (
        "| Source ID | Source | Location | Semantic summary | Category | "
        "Authority target | Status | Evidence | Semantics changed | Conflict / notes |\n"
        "|---|---|---|---|---|---|---|---|---|---|\n"
    )
    return "# Rule migration ledger\n\n" + header + "\n".join(rows) + "\n"


class ValidateAgentRulesTests(unittest.TestCase):
    def make_valid_repo(self, root: Path) -> tuple[Path, Path]:
        domain = root / "docs" / "agent" / "domains"
        reference = root / "docs" / "agent" / "reference"
        domain.mkdir(parents=True)
        reference.mkdir(parents=True)
        (root / "AGENTS.md").write_text(root_document(), encoding="utf-8")
        (domain / "backend.md").write_text(
            "# Backend rules\n\n"
            "## Applies to\n`services/api/**` and API behavior.\n\n"
            "## Does not apply to\nFrontend-only presentation work.\n\n"
            "## Authoritative rules\n- Keep handlers thin.\n- Never log tokens.\n\n"
            "## Verification\n- Run focused API tests.\n",
            encoding="utf-8",
        )
        ledger_path = reference / "rule-migration-report.md"
        ledger_path.write_text(
            ledger(
                [
                    "| R-one | AGENTS.md | L10 | Keep handlers thin | backend | docs/agent/domains/backend.md | migrated | services/api | no | - |",
                    "| R-two | AGENTS.md | L11 | Never log tokens | security | docs/agent/domains/backend.md | migrated | ADR-1 | no | - |",
                ]
            ),
            encoding="utf-8",
        )
        baseline_path = root / "baseline.json"
        baseline_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "rule_candidates": [
                        {"id": "R-one", "source": "AGENTS.md", "line": 10, "text": "Keep handlers thin"},
                        {"id": "R-two", "source": "AGENTS.md", "line": 11, "text": "Never log tokens"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        return ledger_path, baseline_path

    def test_accepts_complete_single_hop_structure_without_frontend_route(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ledger_path, baseline_path = self.make_valid_repo(root)

            report = module.validate_repository(root, ledger_path, baseline_path)

            self.assertTrue(report["valid"], report["errors"])
            self.assertEqual(report["metrics"]["route_depth"], 1)
            self.assertEqual(report["ledger"]["covered_candidates"], 2)
            self.assertFalse(
                any("frontend" in item["message"].lower() for item in report["errors"])
            )

    def test_reports_size_sections_links_empty_routes_depth_and_ledger_gaps(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "docs" / "agent" / "domains").mkdir(parents=True)
            (root / "docs" / "agent" / "reference").mkdir(parents=True)
            (root / "AGENTS.md").write_text(
                "# Rules\n\n"
                "## Rule routing\n"
                "- [missing](docs/agent/domains/missing.md)\n"
                "- [empty](docs/agent/domains/empty.md)\n"
                "- [leaf](docs/agent/domains/leaf.md)\n"
                + ("compression filler without a rule\n" * 260),
                encoding="utf-8",
            )
            (root / "docs" / "agent" / "domains" / "empty.md").write_text(
                "# Empty\n", encoding="utf-8"
            )
            (root / "docs" / "agent" / "domains" / "leaf.md").write_text(
                "# Leaf\n\n## Applies to\nAPI.\n\n## Does not apply to\nUI.\n\n"
                "## Authoritative rules\n- Must read [deep rules](deep.md).\n",
                encoding="utf-8",
            )
            (root / "docs" / "agent" / "domains" / "deep.md").write_text(
                "# Deep\n\n- Hidden rule.\n", encoding="utf-8"
            )
            ledger_path = root / "docs" / "agent" / "reference" / "rule-migration-report.md"
            ledger_path.write_text(
                ledger(
                    [
                        "| R-one | AGENTS.md | L1 | First rule | root | AGENTS.md | kept | root file | no | - |"
                    ]
                ),
                encoding="utf-8",
            )
            baseline_path = root / "baseline.json"
            baseline_path.write_text(
                json.dumps(
                    {
                        "rule_candidates": [
                            {"id": "R-one", "source": "AGENTS.md", "line": 1, "text": "First"},
                            {"id": "R-two", "source": "AGENTS.md", "line": 2, "text": "Second"},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            report = module.validate_repository(root, ledger_path, baseline_path)
            codes = {item["code"] for item in report["errors"]}

            self.assertFalse(report["valid"])
            self.assertTrue(
                {
                    "root_over_hard_limit",
                    "missing_required_section",
                    "dangling_markdown_link",
                    "empty_rule_file",
                    "mandatory_route_too_deep",
                    "ledger_missing_coverage",
                }.issubset(codes),
                codes,
            )

    def test_rejects_plan_mode_and_automatic_optional_workflows(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ledger_path, baseline_path = self.make_valid_repo(root)
            (root / "AGENTS.md").write_text(
                root_document(
                    "- Always start AgentHub for R2 work.\n"
                    "- Use AgentHub by default.\n"
                    "- Enter plan mode before changing two files.\n"
                ),
                encoding="utf-8",
            )

            report = module.validate_repository(root, ledger_path, baseline_path)
            codes = {item["code"] for item in report["errors"]}

            self.assertIn("automatic_optional_workflow", codes)
            self.assertIn("plan_mode_rule", codes)

    def test_accepts_negative_optional_workflow_statement(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ledger_path, baseline_path = self.make_valid_repo(root)
            (root / "AGENTS.md").write_text(
                root_document(
                    "- AgentHub is not automatically enabled.\n"
                    "- Never start AgentHub automatically.\n"
                    "- AgentHub is automatically disabled.\n"
                    "- Use AgentHub only when the user explicitly requests multi-agent work.\n"
                    "```text\nAlways start AgentHub.\n```\n"
                ),
                encoding="utf-8",
            )

            report = module.validate_repository(root, ledger_path, baseline_path)

            self.assertTrue(report["valid"], report["errors"])

    def test_rejects_optional_workflow_enabled_by_default(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ledger_path, baseline_path = self.make_valid_repo(root)
            (root / "AGENTS.md").write_text(
                root_document("- Use AgentHub by default.\n"), encoding="utf-8"
            )

            report = module.validate_repository(root, ledger_path, baseline_path)
            codes = {item["code"] for item in report["errors"]}

            self.assertIn("automatic_optional_workflow", codes)

    def test_rejects_unscoped_workflow_enablement_phrases(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ledger_path, baseline_path = self.make_valid_repo(root)
            (root / "AGENTS.md").write_text(
                root_document(
                    "- Start AgentHub for every task.\n"
                    "- Enable AgentHub as the standard workflow.\n"
                    "- AgentHub starts for all work.\n"
                ),
                encoding="utf-8",
            )

            report = module.validate_repository(root, ledger_path, baseline_path)
            matches = [
                item
                for item in report["errors"]
                if item["code"] == "automatic_optional_workflow"
            ]

            self.assertEqual(len(matches), 3, report["errors"])

    def test_detects_custom_route_directory_and_plain_read_second_hop(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            custom = root / "custom-guidance"
            reference = root / "docs" / "agent" / "reference"
            custom.mkdir(parents=True)
            reference.mkdir(parents=True)
            (root / "AGENTS.md").write_text(
                root_document(route_target="custom-guidance/backend.md"),
                encoding="utf-8",
            )
            (custom / "backend.md").write_text(
                "# Backend\n\n## Applies to\nAPI.\n\n## Does not apply to\nUI.\n\n"
                "## Authoritative rules\n- Read [deep](deep.md) before editing.\n",
                encoding="utf-8",
            )
            (custom / "deep.md").write_text("# Deep\n\n- Hidden rule.\n", encoding="utf-8")

            report = module.validate_repository(root)
            codes = {item["code"] for item in report["errors"]}

            self.assertIn("custom-guidance/backend.md", report["routed_rule_files"])
            self.assertEqual(report["metrics"]["route_depth"], 2)
            self.assertIn("mandatory_route_too_deep", codes)

    def test_allows_optional_background_link_without_increasing_route_depth(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ledger_path, baseline_path = self.make_valid_repo(root)
            route = root / "docs" / "agent" / "domains" / "backend.md"
            (route.parent / "adr.md").write_text("# ADR\n\nBackground only.\n", encoding="utf-8")
            with route.open("a", encoding="utf-8") as handle:
                handle.write("\nFor optional background, you may read [ADR](adr.md).\n")

            report = module.validate_repository(root, ledger_path, baseline_path)

            self.assertTrue(report["valid"], report["errors"])
            self.assertEqual(report["metrics"]["route_depth"], 1)

    def test_rejects_bare_imperative_second_hop(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ledger_path, baseline_path = self.make_valid_repo(root)
            route = root / "docs" / "agent" / "domains" / "backend.md"
            (route.parent / "deep.md").write_text("# Deep\n\n- Hidden rule.\n", encoding="utf-8")
            with route.open("a", encoding="utf-8") as handle:
                handle.write("\nRead [deep rules](deep.md).\n")

            report = module.validate_repository(root, ledger_path, baseline_path)
            codes = {item["code"] for item in report["errors"]}

            self.assertIn("mandatory_route_too_deep", codes)

    def test_allows_runtime_data_migration_rule_file(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            route = root / "docs" / "agent" / "domains" / "data-migration.md"
            reference = root / "docs" / "agent" / "reference"
            route.parent.mkdir(parents=True)
            reference.mkdir(parents=True)
            (root / "AGENTS.md").write_text(
                root_document(route_target="docs/agent/domains/data-migration.md"),
                encoding="utf-8",
            )
            route.write_text(
                "# Data migration\n\n## Applies to\nSchema and backfill work.\n\n"
                "## Does not apply to\nRead-only queries.\n\n"
                "## Authoritative rules\n- Preserve rollback paths.\n",
                encoding="utf-8",
            )
            ledger_path = reference / "rule-migration-report.md"
            ledger_path.write_text(
                ledger(
                    [
                        "| R-one | AGENTS.md | L10 | Preserve rollback | database | docs/agent/domains/data-migration.md | migrated | ADR | no | - |"
                    ]
                ),
                encoding="utf-8",
            )
            baseline_path = root / "baseline.json"
            baseline_path.write_text(
                json.dumps(
                    {
                        "rule_candidates": [
                            {"id": "R-one", "source": "AGENTS.md", "line": 10, "text": "Preserve rollback"}
                        ]
                    }
                ),
                encoding="utf-8",
            )

            report = module.validate_repository(root, ledger_path, baseline_path)

            self.assertTrue(report["valid"], report["errors"])

    def test_validates_ledger_authority_targets_and_semantic_change_fields(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ledger_path, baseline_path = self.make_valid_repo(root)
            ledger_path.write_text(
                ledger(
                    [
                        "| R-one | AGENTS.md | L10 | First | backend | does/not/exist.md | migrated | code | no | - |",
                        "| R-two | AGENTS.md | L11 | Second | security | docs/agent/reference/rule-migration-report.md | migrated | policy | maybe | - |",
                    ]
                ),
                encoding="utf-8",
            )

            report = module.validate_repository(root, ledger_path, baseline_path)
            codes = {item["code"] for item in report["errors"]}

            self.assertIn("ledger_authority_target_missing", codes)
            self.assertIn("ledger_authority_target_not_runtime", codes)
            self.assertIn("invalid_semantics_changed", codes)

    def test_hard_limit_cannot_be_relaxed(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ledger_path, baseline_path = self.make_valid_repo(root)
            (root / "AGENTS.md").write_text(
                root_document() + ("oversize content\n" * 500), encoding="utf-8"
            )

            report = module.validate_repository(
                root, ledger_path, baseline_path, hard_root_bytes=999_999
            )
            codes = {item["code"] for item in report["errors"]}

            self.assertIn("root_over_hard_limit", codes)

    def test_rejects_empty_placeholder_sections_and_fenced_fake_headings(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "AGENTS.md").write_text(
                "# Rules\n\n```markdown\n"
                "## Basic conventions\n## Project context\n## Risk and change scale\n"
                "## Technology and documentation\n## Rule routing\n"
                "## Documentation and checkpoints\n## Minimum verification\n"
                "## Prohibitions\n## Architecture guardrails\n"
                "## Optional workflows and rule precedence\n```\n",
                encoding="utf-8",
            )

            report = module.validate_repository(root)
            missing = [
                item for item in report["errors"] if item["code"] == "missing_required_section"
            ]

            self.assertEqual(len(missing), 10)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ledger_path, baseline_path = self.make_valid_repo(root)
            (root / "AGENTS.md").write_text(
                root_document().replace(
                    "- This repository contains a Python API.", "{{PROJECT_CONTEXT}}"
                ),
                encoding="utf-8",
            )

            report = module.validate_repository(root, ledger_path, baseline_path)
            codes = {item["code"] for item in report["errors"]}

            self.assertIn("empty_or_placeholder_section", codes)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ledger_path, baseline_path = self.make_valid_repo(root)
            (root / "AGENTS.md").write_text(
                root_document()
                .replace("- This repository contains a Python API.", "$PROJECT_CONTEXT")
                .replace(
                    "- Do not change production state without a separately scoped request.",
                    "- Do not leave TODO placeholders in active rules.",
                ),
                encoding="utf-8",
            )

            report = module.validate_repository(root, ledger_path, baseline_path)
            codes = {item["code"] for item in report["errors"]}

            self.assertIn("empty_or_placeholder_section", codes)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ledger_path, baseline_path = self.make_valid_repo(root)
            (root / "AGENTS.md").write_text(
                root_document().replace(
                    "- This repository contains a Python API.", "See README."
                ),
                encoding="utf-8",
            )

            report = module.validate_repository(root, ledger_path, baseline_path)
            codes = {item["code"] for item in report["errors"]}

            self.assertIn("empty_or_placeholder_section", codes)

    def test_accepts_todo_prohibition_when_section_is_real(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ledger_path, baseline_path = self.make_valid_repo(root)
            (root / "AGENTS.md").write_text(
                root_document().replace(
                    "- Do not change production state without a separately scoped request.",
                    "- Do not leave TODO placeholders in active rules.",
                ),
                encoding="utf-8",
            )

            report = module.validate_repository(root, ledger_path, baseline_path)

            self.assertTrue(report["valid"], report["errors"])

    def test_requires_content_in_each_scoped_route_section(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ledger_path, baseline_path = self.make_valid_repo(root)
            route = root / "docs" / "agent" / "domains" / "backend.md"
            route.write_text(
                "# Backend rules\n\n"
                "## Applies to\n{{SCOPE}}\n\n"
                "## Does not apply to\nUI.\n\n"
                "## Authoritative rules\nTODO\n",
                encoding="utf-8",
            )

            report = module.validate_repository(root, ledger_path, baseline_path)
            codes = {item["code"] for item in report["errors"]}

            self.assertIn("route_section_empty", codes)

    def test_rejects_missing_authority_anchor(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ledger_path, baseline_path = self.make_valid_repo(root)
            text = ledger_path.read_text(encoding="utf-8").replace(
                "docs/agent/domains/backend.md | migrated | services/api",
                "docs/agent/domains/backend.md#not-real | migrated | services/api",
                1,
            )
            ledger_path.write_text(text, encoding="utf-8")

            report = module.validate_repository(root, ledger_path, baseline_path)
            codes = {item["code"] for item in report["errors"]}

            self.assertIn("ledger_authority_anchor_missing", codes)

    def test_cli_is_read_only_and_returns_nonzero_for_invalid_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "AGENTS.md").write_text("# Rules\n", encoding="utf-8")
            before = digest_tree(root)

            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo", str(root), "--json"],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 1, completed.stderr)
            report = json.loads(completed.stdout)
            self.assertFalse(report["valid"])
            self.assertEqual(before, digest_tree(root))

    def test_rejects_runtime_config_and_unstable_agenthub_details_in_root_only(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ledger_path, baseline_path = self.make_valid_repo(root)
            (root / "AGENTS.md").write_text(
                root_document(
                    "- Set model_context_window = 272000 in ~/.codex/config.toml.\n"
                    "- Sol=xhigh, Terra=medium, Luna=low; otherwise ROUTING_HOLD.\n"
                    "- Inspect rollout.model, rollout.effort, and parent_thread_id.\n"
                ), encoding="utf-8"
            )
            report = module.validate_repository(root, ledger_path, baseline_path)
            codes = {item["code"] for item in report["errors"]}
            self.assertIn("user_runtime_config_in_root", codes)
            self.assertIn("unstable_agenthub_detail_in_root", codes)

            ledger_path.write_text(
                ledger([
                    "| R-one | AGENTS.md | L10 | model_context_window = 272000 | operator-runtime-config | docs/agent/reference/operator-runtime-config.md | externalized-runtime-config | original text | no | not auto-applied |",
                    "| R-two | AGENTS.md | L11 | rollout.model ROUTING_HOLD | operator-runtime-config | docs/agent/reference/operator-runtime-config.md | externalized-runtime-config | original text | no | not auto-applied |",
                ]), encoding="utf-8"
            )
            (root / "docs" / "agent" / "reference" / "operator-runtime-config.md").write_text(
                "# Operator runtime config\n\nHistorical text: model_context_window = 272000 and rollout.model.\n",
                encoding="utf-8",
            )
            (root / "AGENTS.md").write_text(root_document(), encoding="utf-8")
            report = module.validate_repository(root, ledger_path, baseline_path)
            self.assertTrue(report["valid"], report["errors"])

    def test_rejects_multiline_root_model_matrix(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ledger_path, baseline_path = self.make_valid_repo(root)
            (root / "AGENTS.md").write_text(
                root_document(
                    "- Sol handles architecture.\n- Terra implements.\n- Luna scans logs.\n"
                ), encoding="utf-8"
            )
            report = module.validate_repository(root, ledger_path, baseline_path)
            self.assertIn(
                "unstable_agenthub_detail_in_root",
                {item["code"] for item in report["errors"]},
            )

    def test_agenthub_leaf_requires_tiers_fallback_permissions_and_write_ownership(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ledger_path, baseline_path = self.make_valid_repo(root)
            workflow = root / "docs" / "agent" / "workflows" / "agenthub.md"
            workflow.parent.mkdir(parents=True)
            ledger_path.write_text(
                ledger([
                    "| R-one | AGENTS.md | L10 | Keep handlers thin | root | AGENTS.md | kept | root | no | - |",
                    "| R-two | AGENTS.md | L11 | Never log tokens | root | AGENTS.md | kept | root | no | - |",
                ]), encoding="utf-8"
            )
            (root / "AGENTS.md").write_text(
                root_document(route_target="docs/agent/workflows/agenthub.md").replace(
                    "- Optional workflows require an explicit user request.",
                    "- Use AgentHub only when the user explicitly requests multi-agent work."
                ), encoding="utf-8"
            )
            workflow.write_text(
                "# AgentHub\n\n## Applies to\nExplicit multi-agent work.\n\n"
                "## Does not apply to\nNormal R3 work.\n\n## Authoritative rules\n"
                "- Sol=xhigh, Terra=medium, Luna=low.\n",
                encoding="utf-8",
            )
            report = module.validate_repository(root, ledger_path, baseline_path)
            codes = {item["code"] for item in report["errors"]}
            self.assertIn("agenthub_fixed_mapping_without_policy", codes)
            self.assertIn("agenthub_write_governance_missing", codes)
            self.assertIn("agenthub_permission_governance_missing", codes)

            workflow.write_text(
                "# AgentHub\n\n## Applies to\nExplicit multi-agent work.\n\n"
                "## Does not apply to\nNormal R3 work.\n\n## Authoritative rules\n"
                "- Deep/critical capability tier: Sol high/xhigh; max only for the hardest work.\n"
                "- Balanced implementation tier: Terra medium/high.\n"
                "- Fast deterministic tier: Luna low/medium. These names are current mappings; fall back to the nearest available capability without ROUTING_HOLD.\n"
                "- Shared workspace uses one writer; parallel writers require isolated worktrees, non-overlapping writable roots, explicit ownership, and one Integrator as the sole final integrator.\n"
                "- Explorer, Reviewer, Advisor, and read verification roles are read-only; Worker gets workspace-write only within ownership. danger-full-access requires separate explicit per-task user authorization and only when the platform allows it.\n",
                encoding="utf-8",
            )
            report = module.validate_repository(root, ledger_path, baseline_path)
            self.assertTrue(report["valid"], report["errors"])

            workflow.write_text(
                "# AgentHub\n\n## Applies to\nExplicit multi-agent work.\n\n"
                "## Does not apply to\nNormal work.\n\n## Authoritative rules\n"
                "- Deep/critical capability tier uses Sol; fall back to nearest available capability.\n"
                "- Explorer is read-only; Worker uses workspace-write. danger-full-access needs separate explicit user authorization.\n"
                "- One writer; isolated worktrees; one Integrator is sole final integrator.\n",
                encoding="utf-8",
            )
            report = module.validate_repository(root, ledger_path, baseline_path)
            codes = {item["code"] for item in report["errors"]}
            self.assertIn("agenthub_capability_tiers_incomplete", codes)
            self.assertIn("agenthub_write_governance_missing", codes)
            self.assertIn("agenthub_permission_governance_missing", codes)

    def test_risk_classification_does_not_grant_danger_full_access(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ledger_path, baseline_path = self.make_valid_repo(root)
            (root / "AGENTS.md").write_text(
                root_document("- R3 or direct-start work grants danger-full-access.\n"),
                encoding="utf-8",
            )
            report = module.validate_repository(root, ledger_path, baseline_path)
            self.assertIn(
                "danger_full_access_without_explicit_authorization",
                {item["code"] for item in report["errors"]},
            )

    def test_allows_scoped_repository_deletion_but_rejects_blanket_ban(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ledger_path, baseline_path = self.make_valid_repo(root)
            (root / "AGENTS.md").write_text(
                root_document("- Never delete any files.\n"), encoding="utf-8"
            )
            report = module.validate_repository(root, ledger_path, baseline_path)
            self.assertIn(
                "overbroad_file_deletion_ban",
                {item["code"] for item in report["errors"]},
            )


if __name__ == "__main__":
    unittest.main()
