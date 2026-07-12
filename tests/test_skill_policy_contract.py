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


if __name__ == "__main__":
    unittest.main()
