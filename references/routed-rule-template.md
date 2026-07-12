# 路由规则文件模板

每个叶子文件只承担一个实际存在的领域、政策或可选工作流。使用项目真实名称、路径、命令和证据；没有对应领域就不要创建文件。根 `AGENTS.md` 必须能直接路由到本文件。

```markdown
# {{DOMAIN_OR_POLICY_NAME}}

## Applies to / 适用范围

- 用户目标：{{GOALS_OR_IMPACT_CONDITIONS}}
- 路径信号：`{{PATH_GLOB}}`
- 实际影响：{{CONTRACT_DATA_SECURITY_OR_INFRA_BOUNDARY}}

## Does not apply to / 不适用范围

- {{NEARBY_BUT_OUT_OF_SCOPE_WORK}}
- 只读浏览本目录且不影响决策时，不因路径本身自动加载全部领域规则。

## Authoritative rules / 权威规则

- {{PROJECT_SPECIFIC_RULE}}
- {{PROJECT_SPECIFIC_RULE}}
- {{ARCHITECTURE_OR_SECURITY_INVARIANT_IF_THIS_FILE_OWNS_IT}}

## Required verification / 必要验证

- {{NARROW_PROJECT_COMMAND_OR_CHECK}}
- {{DIRECT_INTEGRATION_BOUNDARY_CHECK}}
- 对高风险变化验证{{COMPATIBILITY_DATA_SECURITY_OR_RECOVERY_PATH}}。

## Prohibitions / 禁止事项

- {{DOMAIN_SPECIFIC_PROHIBITION}}

## Evidence / 证据来源

- `{{MANIFEST_CONFIG_TEST_ADR_OR_CODE_PATH}}`：{{WHAT_IT_PROVES}}
```

## 约束

- 让文件自包含：读取本文件后即可执行该领域任务。
- 默认只允许 `AGENTS.md → 本文件` 一层强制引用。证据链接可以存在，但不得要求继续读取一串下游规则。
- 多领域任务由根路由直接加载多个叶子文件的并集。
- 不重复根级授权、通用风险模型、通用验证、规则优先级或其他叶子的完整规则。
- 根可保留一行不变量摘要，叶子保存执行细节；两处不得形成语义不同的双重权威。
- 不写与项目无关的通用最佳实践，不把历史说明当成运行时规则。

## 可选：AgentHub 工作流叶子

仅当根规则显式触发 AgentHub 时使用：

- 能力层级：深度/关键、均衡实现、快速确定性；按歧义和失败成本选择最低可靠层级，模型名仅作当前映射，并回退到最近可用能力而非 `ROUTING_HOLD`。
- 权限：Explorer、Reviewer、Advisor 与资料核验角色只读，Worker 仅在所有权内 `workspace-write`；`danger-full-access` 需当前任务的单独明确用户授权且平台允许。
- 写入：共享工作区默认单写者；并行写入必须使用隔离 worktree/仓库、不重叠可写根和明确所有权，且只有一个 Integrator 负责最终集成、diff 和验证。
- 外部动作：不读取密钥，不自动 commit、push、publish、deploy；子 Agent 不扩大权限。
- 可选工作流文件必须明确其显式触发条件和默认关闭状态，且不得覆盖上层约束。
