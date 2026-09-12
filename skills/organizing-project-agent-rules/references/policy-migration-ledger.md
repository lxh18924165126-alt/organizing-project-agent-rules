# Skill 政策迁移账本

本文件只供维护时核对历史，不作为生效规则，不复制到项目默认路由。以下原文来自 2026-09-12 修改前的 Skill；当前用户明确要求主动委派、全部子代理使用 `gpt-5.6-luna / max`、按需定数量、等待全部完成并核对证据后汇总。

| Source ID | Source | Location | Source type | Confidence | Existing explicit rule | Inferred from repository | User confirmed | Semantic summary | Category | Authority target | Status | Evidence | Semantics changed | Conflict / notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MA-01 | references/policy-spec.md | 原第 75 行，AgentHub | explicit-rule | high | yes | no | yes | 默认关闭，只有用户明确要求多 Agent、Agent 分工、并行代理，或已批准任务明确包含多 Agent 时才加载。 | 多 Agent | references/policy-spec.md#子代理 | superseded-by-current-user-policy | 用户当前三条子代理政策 | yes | 原生委派改为按独立实质分支主动触发；AgentHub 完整工作流的可选边界另行保留 |
| MA-02 | references/policy-spec.md | 原第 77 行，AgentHub | explicit-rule | high | yes | no | yes | 启用后按任务歧义、失败成本、责任和整合难度选择 Agent 数量、角色、模型和推理强度，而不是只按代码行数。 | 多 Agent | references/policy-spec.md#子代理 | superseded-by-current-user-policy | 用户当前三条子代理政策 | yes | 数量和角色仍按任务确定；模型与强度不可再按难度自由选择 |
| MA-03 | references/policy-spec.md | 原第 165 行，AgentHub 能力层级与回退 | explicit-rule | high | yes | no | yes | 深度/关键能力层级用于高歧义、架构、安全、迁移、集成和审查，当前可映射 Sol high/xhigh，max 仅用于最困难任务；均衡实现能力层级用于代码、测试、重构和缺陷，当前可映射 Terra medium/high；快速确定性能力层级用于日志、扫描、提取和机械转换，当前可映射 Luna low/medium。 | 多 Agent | references/policy-spec.md#子代理 | superseded-by-current-user-policy | 用户当前三条子代理政策 | yes | 多型号/多强度矩阵与统一 gpt-5.6-luna / max 冲突 |
| MA-04 | references/policy-spec.md | 原第 166 行，AgentHub 能力层级与回退 | explicit-rule | high | yes | no | yes | 按歧义、失败成本、推理、集成和验证需要选择最低可靠能力，而不是代码行数。模型名只是当前映射；不可用时回退到最近可用能力并报告，不使用 `ROUTING_HOLD`。仅用户明确要求某个不可替代模型且确认不可用时阻断。 | 多 Agent | references/policy-spec.md#子代理 | superseded-by-current-user-policy | 用户当前三条子代理政策 | yes | 禁止无当前用户明确指定的模型/强度回退；不可用时主代理继续可独立完成工作并报告 |
| MA-05 | references/policy-spec.md | 原第 174 行，权限、写入与删除 | explicit-rule | high | yes | no | yes | 共享工作区默认单写者；并行写入只在显式 AgentHub、隔离 worktree/仓库、不重叠可写根和明确所有权下使用。共享契约、schema、锁文件、全局配置只有一个所有者；唯一 Integrator 负责最终集成、实际 diff 与验证，发现重叠即停止并行写入。 | 多 Agent | references/policy-spec.md#权限写入与删除 | superseded-by-current-user-policy | 用户当前三条子代理政策 | yes | 保留所有权与隔离约束；移除必须先启用 AgentHub 的前置条件，补齐等待全部完成与证据核对 |
| MA-06 | references/root-agents-template.md | 原第 69 行，可选工作流 | explicit-rule | high | yes | no | yes | AgentHub 仅在用户明确要求多 Agent 或已批准范围明确包含多 Agent 时加载。 | 多 Agent | references/policy-spec.md#子代理 | superseded-by-current-user-policy | 用户当前三条子代理政策 | yes | 根加入主动原生委派；AgentHub 完整工作流另保留显式入口 |
| MA-07 | references/routed-rule-template.md | 原第 53 行，AgentHub 工作流叶子 | explicit-rule | high | yes | no | yes | 能力层级：深度/关键、均衡实现、快速确定性；按歧义和失败成本选择最低可靠层级，模型名仅作当前映射，并回退到最近可用能力而非 `ROUTING_HOLD`。 | 多 Agent | references/policy-spec.md#子代理 | superseded-by-current-user-policy | 用户当前三条子代理政策 | yes | 改用统一型号/强度和仅当前用户可指定例外；不允许自动回退 |

上述来源共 7 条，均为 `superseded-by-current-user-policy`。原验证器对三层模型和能力回退的强制检查，以及评测场景 11、15 的旧预期，随 MA-03/MA-04/MA-07 更新；权限、单写者、隔离所有权与 Superpower default-deny 继续保留。
