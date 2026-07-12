---
name: organizing-project-agent-rules
description: Use when a repository is missing a root AGENTS.md, has scattered, duplicate, conflicting, oversized, or incomplete Agent rules, or needs to create, migrate, repair, audit, or normalize project Agent rule routing.
---

# Organizing Project Agent Rules

## Outcome

建立、迁移、规范化和验证项目的 Agent 规则系统。统一产出“项目基本属性 + 最小执行内核 + 直接规则路由器”，并让根级、嵌套、override、fallback 和按需规则各有唯一权威位置。

只修改项目指令与规则文档。除非用户另有明确要求，不修改业务代码、依赖、构建、CI、部署配置或生产环境；不提交或推送。

## Required resources

1. 每次执行前完整读取 [policy-spec.md](references/policy-spec.md)，把它作为授权、风险、路由、验证、可选工作流和优先级的权威政策。
2. 修改根文件前读取 [root-agents-template.md](references/root-agents-template.md)，把它当覆盖与预算参考，不机械套用。
3. 创建或重写叶子规则前读取 [routed-rule-template.md](references/routed-rule-template.md)。
4. 建立账本前读取 [migration-ledger-template.md](references/migration-ledger-template.md)。
5. 模式确定后只读取对应内部流程：[bootstrap](references/bootstrap-workflow.md)、[migrate](references/migration-workflow.md)、[repair](references/repair-workflow.md) 或 [audit](references/audit-workflow.md)。四种模式共享前述政策与模板。
6. 仅在评测或维护本 Skill 时读取 [eval-scenarios.md](references/eval-scenarios.md)；正常仓库治理无需加载。

使用本 Skill 目录中两个纯标准库、只读脚本：

- `scripts/inventory_agent_rules.py`：列出指令文件、fallback、Markdown 引用图、大小、Git 状态、规则候选和证据源。
- `scripts/validate_agent_rules.py`：检查根预算、必要章节、链接、空文件、强制路由深度、可选工作流误启用和账本覆盖。

运行 `python3 <script> --help` 查看参数。把 `SKILL_DIR` 设为当前已加载 Skill 的绝对目录；不要假设仓库当前目录就是 Skill 目录。

## Inputs and outputs

### Inputs

- 目标目录：默认取当前 Git 仓库根；不在 Git 仓库中时取当前工作目录。
- 用户当前目标、范围、只读限制和明确事实。
- 仓库中的指令、代码、清单、配置、测试、CI 和文档证据。

### Outputs

- 必要时更新的根 `AGENTS.md`、保留的嵌套/override 指令和实际需要的叶子规则。
- 修改发生时的逐条迁移账本；无修改时保留仓库外工作账本并报告 no-op，不为流程形式新增文件。
- 最终验证结果和固定格式的迁移报告摘要。

## Workflow

严格按顺序执行。不得从“压缩根文件”直接开始。

### 1. Determine scope, inventory, and select mode

1. 把 `SKILL_DIR` 设为当前 Skill 目录。把用户指定目录设为 `TARGET`；未指定时使用当前目录。若 `git -C "$TARGET" rev-parse --show-toplevel` 成功，把其输出设为 `REPO` 并标记 `IS_GIT=1`；否则把 `TARGET` 的物理绝对路径设为 `REPO` 并标记 `IS_GIT=0`。
2. Git 仓库立即运行 `git -C "$REPO" status --short`，记录已有修改、未跟踪规则文件和允许修改的路径。非 Git 目录在仓库外临时目录保存所有原始指令/规则文件的相对路径内容副本和全仓文件 SHA-256 清单。
3. 明确本次不修改业务代码、依赖、构建、CI、部署或生产状态。若用户只要求分析，保持全程只读。
4. 使用可审查的增量修改，不做无依据的全量替换。非 Git 目录使用原子写入；不要在仓库中遗留 `.bak` 或临时快照。
5. 保留用户未提交修改。不得 reset、checkout、回滚、覆盖或把工作树替换为 HEAD。
6. 运行盘点器自动选择模式；用户指定模式时传入 `--mode`，检查 `mode_applicable`，不适用时说明证据后改用自动模式或集中请求用户确认：
   - `bootstrap`：根 `AGENTS.md` 缺失；这是合法输入，不是盘点失败。
   - `migrate`：根存在但尚无规范直接路由，需要压缩或迁移。
   - `repair`：已有部分路由结构，但有悬空引用、结构缺口、冲突、重复或预算问题。
   - `audit`：直接路由完整；先验证，validator 通过且无语义问题时保持 no-op。

### 2. Inventory and read all governing sources

先生成仓库外基线 JSON；重定向目标必须位于临时目录：

```bash
BASELINE_JSON="$(mktemp "${TMPDIR:-/tmp}/agent-rules-inventory.XXXXXX")"
LEDGER_WORK="$(mktemp "${TMPDIR:-/tmp}/agent-rules-ledger.XXXXXX")"
LEDGER="$LEDGER_WORK"
python3 "$SKILL_DIR/scripts/inventory_agent_rules.py" --repo "$REPO" --json > "$BASELINE_JSON"
```

把清单当作索引而非阅读替代品。盘点并读取：

- 根级和嵌套 `AGENTS.md`、`AGENTS.override.md`；
- 项目配置声明的 fallback 指令文件；
- 指令文件引用的 Markdown 规则及其链接关系；
- `.agents/skills/`、项目内 Agent 配置和相关工作流文档；
- `.codex/rules/`、lint、架构测试、CI 和生成文件标记中的硬约束；
- README、CONTRIBUTING、ADR、架构、API 和运维文档；
- 包清单、锁文件、构建/工作区配置、入口和测试目录。
- 大小写或命名异常的 Agent 指令，以及其他助手说明文件；后者只作证据，不自动成为 Codex 权威规则。

不要假设嵌套 `AGENTS.md` 从仓库根启动时必然加载。把关键领域规则设计为根可直接路由，或明确保留为适用目录的局部覆盖。

### 3. Build the migration ledger before editing

按 [migration-ledger-template.md](references/migration-ledger-template.md) 建立统一规则证据账本。修改前记录来源类型、置信度、是否为现有明确规则/仓库推断/用户确认、语义摘要、分类、唯一权威目标、状态、证据、语义是否变化及冲突。bootstrap 的候选事实与已有局部规则使用同一账本。

至少分类：

- 根级约定、项目背景、风险/执行路由、技术栈/文档索引、文档/检查点、禁止事项、架构护栏；
- 前端、后端、契约、数据库、安全、基础设施等领域；
- R3/强化验证、AgentHub、Harness、专项技能等可选工作流；
- 操作者运行时配置：上下文窗口、自动压缩阈值、账户/价格阈值和用户级 Codex 配置只登记为 `operator-runtime-config`，不得写入生效项目规则；
- 维护者说明、案例、历史背景；
- 应由 `.codex/rules/`、lint、测试或 CI 强制的机械约束。

优先使用 `preserved-in-root`、`migrated`、`merged-equivalent`、`inferred-high-confidence`、`user-confirmed`、`unresolved-needs-user`、`omitted-not-a-rule`、`externalized-runtime-config`；兼容旧账本状态但新账本不得混用同义状态。相似措辞不自动等于重复；合并时仍为每个 Rule ID 保留覆盖记录。

### 4. Infer missing project attributes and batch questions

按以下优先级取证：用户当前明确信息 > 已有明确规则文档 > CI/lint/构建/schema 等机器强制配置 > 多个相互印证的代码/目录信号 > 单一代码模式。

1. 可执行配置和清单；
2. 架构测试、lint、CI 和代码边界；
3. 当前代码与测试的多个相互印证模式；
4. README、ADR 和维护文档；
5. 命名、目录等弱信号。

可推断技术栈、权威版本来源、常用命令、模块边界、生成文件、测试方式和明显依赖。不得仅凭现状臆造业务目标、审批流程、生产政策、未来架构、合规要求或团队制度。

单一代码模式不得升级为硬规则。完成初步审计后，只把无法可靠获取、会实质影响根禁止项/架构护栏/路由且不问就只能编造的未知项集中提问一次。用户暂不回答时继续安全部分，把未确认项留在账本和最终报告；不要把猜测、`TODO` 或 `TBD` 写入生效规则，也不重复询问已经回答的问题。

### 5. Design the target routing structure

优先沿用项目已有且清晰的规则目录；没有时，按实际需要从下列候选中选择，不要全部创建：

```text
docs/agent/
├── project.md
├── architecture.md
├── domains/{frontend,backend,contracts,database,security,infrastructure}.md
├── policies/{r3-execution,verification-deep}.md
├── workflows/{agenthub,harness}.md
└── reference/rule-migration-report.md
```

应用以下结构约束：

- 只创建由现有规则、仓库证据或用户明确需求支持的文件；不创建空领域文件。
- 默认只允许一层强制引用：`AGENTS.md → 叶子规则文件`。
- 由根直接加载多领域规则并集；叶子不得强制串联下游规则。
- 同一规则只有一个权威来源；根可保留不变量摘要，但不复制叶子完整规则。
- 对每个嵌套文件明确选择：保留局部覆盖、迁移为根可路由规则，或完整去重后移除。把决定写入账本。

### 6. Rewrite the root only when needed

先检查现有根文件是否已低于 4 KiB、覆盖完整、路由清晰且语义一致。若已合理，避免无意义重写，只修复有证据的缺陷。

需要修改时，让根文件包含项目特定且可执行的十类属性：

1. 基本约定；
2. 项目背景；
3. 风险与改动规模判断；
4. 技术栈说明与项目文档索引；
5. 领域规则路由；
6. 文档与检查点；
7. 最低验证；
8. 禁止事项；
9. 架构护栏；
10. 可选工作流入口与规则优先级。

以 UTF-8 字节计算：4 KiB 为优化目标，6 KiB 为硬上限，40～80 行为软目标。超过 4 KiB 时先下沉解释、例子和操作细节；超过 6 KiB 必须继续重构。不得通过极端缩写、删除项目属性或模糊措辞过预算门。

### 7. Write self-contained routed rules

按 [routed-rule-template.md](references/routed-rule-template.md) 编写每个实际叶子文件：

- 明确 `Applies to`、`Does not apply to` 和 `Authoritative rules`；
- 使用真实命令、路径、技术栈和证据；
- 保留或完整迁移旧规则的适用条件、约束强度、例外、验证和禁止项；
- 只描述本领域，不重复根级授权、通用风险、通用验证或其他领域规则；
- 不把历史说明变成运行时规则，不堆砌通用最佳实践。

AgentHub、Harness 和专项技能属于默认关闭的可选入口。不要自动启用它们，不要让 Harness 自动启用 AgentHub，不要加载全部 Superpower，不要在项目规则中管理 Codex 计划模式。

若旧规则混入用户或机器级 Codex 运行时配置，将原文迁入非运行时操作记录，账本状态标为 `externalized-runtime-config`；不得读取、备份或修改用户配置，也不得把固定上下文、价格或当前模型映射重新包装成项目规则。AgentHub 细节仅在明确启用时进入直接路由的工作流叶子。

### 8. Validate, repair, and report

修改发生时，把工作账本保存到项目已有的规则参考位置；没有合适位置时使用 `docs/agent/reference/rule-migration-report.md`，并把 `LEDGER` 更新为该路径。无修改时继续使用仓库外 `LEDGER_WORK`。账本只证明迁移覆盖，不承载被移除规则的生效语义。

运行：

```bash
python3 "$SKILL_DIR/scripts/inventory_agent_rules.py" --repo "$REPO"
python3 "$SKILL_DIR/scripts/validate_agent_rules.py" \
  --repo "$REPO" \
  --ledger "$LEDGER" \
  --baseline-inventory "$BASELINE_JSON"
```

若 `IS_GIT=1`，再运行 `git diff --check`、规则系统范围的 `git diff` 和最终 `git status --short`；根据实际规则目录补充 pathspec。若 `IS_GIT=0`，在仓库外重建同范围内容副本和 SHA-256 清单，与阶段 1 快照执行 `diff -ru` 和清单差异比较，逐项确认只有规则系统文件变化。修复所有错误后重新运行；警告必须逐项解释。

逐条确认：

- 基线规则候选全部进入账本且每条有效规则有权威去向；
- 根引用都存在，无空规则、悬空链接或不必要的强制二级路由；
- 根不超过 6 KiB，十类属性齐全；
- 未引入项目计划模式规则，未自动启用 AgentHub、Harness 或全部 Superpower；
- 用户已有修改和非规则文件保持原样；
- 未运行的检查未被声称通过。
- 相同输入再次运行时结构、Rule ID 和路由稳定；不重复创建、迁移、提问、排序或改写。validator 通过且无语义问题时 diff 必须为空。

## Decision gates

| Condition | Action |
|---|---|
| 根文件已合理且低于 4 KiB | 审计并验证；无证据缺陷时报告 no-op，不为套模板改写 |
| 根 `AGENTS.md` 缺失 | 进入 bootstrap；调查仓库和局部规则后创建根与实际需要的叶子，不把缺失当错误 |
| 规则疑似重复 | 比较适用条件、强度、例外和权威性；为每个 Source ID 建账 |
| 仓库证据冲突 | 按证据优先级处理；重要且低置信度的政策冲突记为 `needs-user-input` |
| 嵌套规则不可从根到达 | 保留局部覆盖并增加根路由，或完整迁移；不要假设自动加载 |
| 发现范围外新增 R3 | 保护数据、兼容和可逆性；不自动执行危险外部动作，继续安全部分 |
| 完成目标必须修改非规则文件 | 停止该扩展，报告所需新授权；不要顺手扩大范围 |

## Common failure patterns

| Rationalization | Required correction |
|---|---|
| “根文件已低于预算，所以迁移完成” | 预算只是一个门；账本覆盖、语义保真、路由和验证必须同时通过 |
| “旧规则仍在 Git 历史/迁移报告” | 历史不是生效权威；把规则保留或完整迁移到会被正确加载的位置 |
| “这些规则看起来重复” | 逐条比较强度、条件、例外和验证；用 `merged-equivalent` 映射每个来源 |
| “嵌套 AGENTS.md 会自己加载” | 从根启动行为不可假设；关键领域必须根可路由或明确局部覆盖 |
| “模板完整，所以先创建所有领域文件” | 只创建实际存在的领域；空文件和无关最佳实践是失败 |
| “无法确认的事实可以先写 TODO” | 不把猜测写入生效规则；集中询问并在账本/最终报告保留未确认项 |
| “代码里出现一次，所以这是架构政策” | 单一模式只记低置信度候选；需要多源印证或用户确认才进入硬规则 |
| “validator 已通过，顺便统一措辞” | audit 应 no-op；无语义缺陷不得制造 diff |

## Red flags

出现任一项就停止宣称完成并返回对应阶段修复：

- 在迁移账本完成前修改生效规则；
- 基线 Source ID 未覆盖，或账本只有主题级汇总；
- 删除、弱化、扩大或改变规则但没有用户授权与账本记录；
- 只在 legacy、archive、Git 历史或迁移报告保留规则；
- 根超过 6 KiB、引用不存在、叶子为空或存在强制二级路由；
- 用户未提交修改被覆盖；
- 仍有验证错误却声称完成。
- audit 模式在 validator 通过时仍产生无意义 diff，或第二次运行重复规则、迁移记录或问题。

## Completion report

只在所有完成门通过后报告：

- 根 `AGENTS.md` 的 UTF-8 字节数和行数；
- 创建、修改、保留和移除的规则文件；
- 各证据来源类型、置信度与处理状态数量，包括 `externalized-runtime-config`；
- 从仓库推断的内容及证据、用户明确提供的内容；
- 冲突、未确认事项和推迟的危险步骤；
- 实际运行的清单、验证、diff 和项目检查，以及未运行项。

## Invocation example

```text
$organizing-project-agent-rules
审计并重构当前仓库的项目 Agent 规则系统。保留或完整迁移所有现有规则；从代码和项目文档补充可可靠推断的缺失内容；只对无法推断且会实质影响规则的事实集中询问我。不要修改业务代码。
```
