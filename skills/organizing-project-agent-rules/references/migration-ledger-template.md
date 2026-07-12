# 规则迁移账本模板

在修改任何生效规则前建立账本。先把 `inventory_agent_rules.py --json` 的输出保存在仓库外临时文件中，再把每条具有约束意义的旧规则映射到一行。`Source ID` 使用基线 JSON 中的 `rule_candidates[].id`，以便 `validate_agent_rules.py` 自动核对覆盖率。

```markdown
# Rule migration ledger

## Scope

- Repository: `{{REPOSITORY_ROOT}}`
- Baseline inventory: `{{TEMP_BASELINE_JSON}}`
- Audited sources: {{SOURCE_PATHS}}
- Audit timestamp: {{TIMESTAMP_WITH_TIMEZONE}}

## Entries

| Source ID | Source | Location | Semantic summary | Category | Authority target | Status | Evidence | Semantics changed | Conflict / notes |
|---|---|---|---|---|---|---|---|---|---|
| R-0123456789ab | AGENTS.md | Backend rules, line 42 | API handlers delegate business decisions to services | backend | docs/agent/domains/backend.md | migrated | services/api structure and tests | no | - |

## Coverage summary

- Baseline rule candidates: {{COUNT}}
- Kept: {{COUNT}}
- Migrated: {{COUNT}}
- Merged duplicates: {{COUNT}}
- Conflicts: {{COUNT}}
- Needs user input: {{COUNT}}
- Uncovered: 0
```

## 字段规则

- `Source ID`：使用修改前基线清单中的稳定 ID；一条来源规则只出现一次。
- `Source` 与 `Location`：给出原文件和可复核的章节/行号，不只写“旧规则”。
- `Semantic summary`：保留原约束强度、适用条件、禁止项和例外，不只摘关键词。
- `Category`：至少支持根级基本约定、项目背景、风险与执行路由、技术栈和文档索引、文档与检查点、禁止事项、架构护栏、前端、后端、契约、数据库、安全、基础设施、R3/强化验证、AgentHub、Harness、专项技能、维护者说明/历史、机械约束、`operator-runtime-config`。
- `Authority target`：给出仓库内实际存在的唯一生效文件及可选锚点。Markdown 叶子必须由根直接路由；嵌套 `AGENTS.md` 或机械执行文件必须处于其真实生效位置。不得指向 legacy、archive、Git 历史或本迁移报告。
- `Status`：只使用 `kept`、`migrated`、`merged-duplicate`、`conflict`、`needs-user-input`、`externalized-runtime-config`。
- `externalized-runtime-config` 仅配合 `operator-runtime-config` 使用；此时 `Authority target` 指向非运行时迁移/操作者记录，保留原文、来源与“不自动应用”说明，不得由根路由。
- `Evidence`：引用清单、配置、测试、代码边界、README、ADR、CI 或用户明确输入；不要写无来源猜测。
- `Semantics changed`：通常为 `no`。只有用户明确改变规则或有已解决冲突时才写 `yes`，并在最后一列说明授权与新语义；无法确认时写 `unknown` 且状态为 `needs-user-input`。
- `Conflict / notes`：记录冲突双方、证据优先级、合并关系或需要用户回答的问题；无内容写 `-`。

## 完成门

- 不得以“已复制到迁移报告”“仍在 Git 历史中”或“看起来重复”代替权威位置映射。
- 合并重复项时，为每个旧 `Source ID` 各保留一行，并让它们指向同一权威规则。
- 删除嵌套 `AGENTS.md` 前，账本必须覆盖其中每条有效规则并记录去重证据。
- 账本仍有未覆盖候选、空字段、非法状态或无权威目标时，不得宣称迁移完成。
