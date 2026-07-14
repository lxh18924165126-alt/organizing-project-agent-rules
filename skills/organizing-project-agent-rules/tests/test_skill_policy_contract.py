from pathlib import Path
import unittest


SKILL_DIR = Path(__file__).resolve().parents[1]


class SkillPolicyContractTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (SKILL_DIR / relative).read_text(encoding="utf-8")

    def test_runtime_agenthub_and_permission_policy_is_authoritative(self) -> None:
        policy = self.read("references/policy-spec.md")
        for marker in (
            "operator-runtime-config", "externalized-runtime-config",
            "model_context_window", "model_auto_compact_token_limit",
            "能力层级", "最近可用能力", "danger-full-access",
            "单写者", "Integrator", "删除",
        ):
            self.assertIn(marker, policy)

    def test_templates_and_eval_matrix_cover_new_contract(self) -> None:
        root = self.read("references/root-agents-template.md")
        routed = self.read("references/routed-rule-template.md")
        ledger = self.read("references/migration-ledger-template.md")
        scenarios = self.read("references/eval-scenarios.md")
        self.assertIn("用户运行时配置", root)
        self.assertIn("能力层级", routed)
        self.assertIn("并行写入", routed)
        self.assertIn("externalized-runtime-config", ledger)
        for number in range(10, 20):
            self.assertIn(f"### 场景 {number}", scenarios)

    def test_skill_remains_explicit_only(self) -> None:
        self.assertIn(
            "allow_implicit_invocation: false",
            self.read("agents/openai.yaml"),
        )
        skill = self.read("SKILL.md")
        self.assertGreaterEqual(skill.count("externalized-runtime-config"), 3)
        routed = self.read("references/routed-rule-template.md")
        self.assertIn("Advisor", routed)
        self.assertIn("平台允许", routed)

    def test_single_skill_supports_four_modes_and_bootstrap_evidence_policy(self) -> None:
        skill = self.read("SKILL.md")
        description = skill.split("---", 2)[1]
        for marker in ("missing", "scattered", "duplicate", "conflict", "oversized", "create", "migrate", "normalize"):
            self.assertIn(marker, description.lower())
        workflow_files = {
            "bootstrap": "bootstrap-workflow.md",
            "migrate": "migration-workflow.md",
            "repair": "repair-workflow.md",
            "audit": "audit-workflow.md",
        }
        for mode, filename in workflow_files.items():
            self.assertIn(mode, skill)
            self.assertTrue((SKILL_DIR / "references" / filename).is_file())
        self.assertIn("集中提问", self.read("references/bootstrap-workflow.md"))
        self.assertIn("单一代码模式", self.read("references/bootstrap-workflow.md"))
        self.assertIn("no-op", self.read("references/repair-workflow.md"))
        self.assertNotIn("allow_implicit_invocation: true", self.read("agents/openai.yaml"))

    def test_eval_scenarios_cover_bootstrap_repair_audit_and_idempotency(self) -> None:
        scenarios = self.read("references/eval-scenarios.md")
        for number in range(20, 34):
            self.assertIn(f"### 场景 {number}", scenarios)
        for marker in ("bootstrap", "migrate", "repair", "audit", "集中询问", "幂等"):
            self.assertIn(marker, scenarios)

    def test_superpower_default_deny_policy_is_authoritative(self) -> None:
        skill = self.read("SKILL.md")
        policy = self.read("references/policy-spec.md")
        root = self.read("references/root-agents-template.md")
        ledger = self.read("references/migration-ledger-template.md")
        scenarios = self.read("references/eval-scenarios.md")

        for marker in (
            "Superpower 默认禁止",
            "R3",
            "工程化设计",
            "工程化实施",
            "Harness",
            "只解除禁令",
            "using-superpowers",
            "explicit no-superpower > allowed gates > default deny",
        ):
            self.assertIn(marker, policy)
        self.assertIn("Superpower default-deny policy", skill)
        self.assertIn("superseded-by-current-user-policy", skill)
        self.assertIn("superseded-by-current-user-policy", ledger)
        self.assertIn("## Superpower", root)
        self.assertNotIn("复杂且根因未知的故障可使用 systematic-debugging", root)
        self.assertNotIn("用户明确要求 TDD 时可使用 test-driven-development", root)
        for number in range(34, 46):
            self.assertIn(f"### 场景 {number}", scenarios)


if __name__ == "__main__":
    unittest.main()
