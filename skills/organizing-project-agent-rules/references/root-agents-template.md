# 根 `AGENTS.md` 结构模板

把本模板当作覆盖清单和压缩参考，不要机械复制。使用项目语言、真实路径、真实命令和仓库证据替换 `{{...}}`；可合并相邻章节，但必须保留十类项目属性并让验证器能识别对应标题。不要把未确认事实、`TODO` 或 `TBD` 写入生效规则。

```markdown
# {{PROJECT_NAME}} Agent Rules

## Basic conventions / 基本约定

- {{LANGUAGE_OR_COMMUNICATION_RULE}}
- 明确修改请求授权在当前范围内连续实施；明确只读限制优先。
- 开始前检查工作树并保留用户已有修改；保持改动聚焦。

## Project context / 项目背景

- {{ONE_OR_TWO_SENTENCES_ABOUT_PRODUCT_AND_REPOSITORY}}
- {{PRIMARY_COMPONENTS_AND_OWNERSHIP_BOUNDARIES}}

## Risk and change scale / 风险与改动规模

- R1：局部、可逆且不改变公共契约、数据、安全边界或基础设施；直接实施并做最低验证。
- R2：跨领域、共享契约、依赖、构建、CI 或基础设施；先写微计划，再连续实施并验证集成边界。
- R3：迁移、数据、安全、生产、不可逆或破坏性兼容风险；做风险分析、强化验证和恢复设计，不重复索取当前范围授权。
- 超过 3 个领域/组件或约 100 行手写代码只触发重新评估，不自动启用复杂工作流。

## Technology and documentation / 技术栈与文档

- {{RUNTIME_AND_FRAMEWORK_FROM_EXECUTABLE_MANIFESTS}}
- 权威版本与命令来源：{{MANIFEST_OR_CONFIG_PATHS}}。
- 项目文档：{{README_ADR_API_OR_OPERATOR_INDEX_LINKS}}。

## Rule routing / 领域规则路由

同时按用户目标、涉及路径和实际影响加载命中的规则并集：

- {{ROUTE_CONDITION}} → [{{RULE_NAME}}]({{DIRECT_LEAF_PATH}})
- {{ROUTE_CONDITION}} → [{{RULE_NAME}}]({{DIRECT_LEAF_PATH}})

路径只是证据；进入新影响领域时增量加载。根文件直接链接叶子规则，不要求叶子继续强制加载下一层。

## Documentation and checkpoints / 文档与检查点

- 改变公共行为、API、配置、部署、数据格式或架构边界时同步更新对应文档。
- 检查点是内部自检；除真正硬阻断外，不中断已授权的连续实施。
- 不为流程形式创建与任务无关的计划、日志或报告。

## Minimum verification / 最低验证

- 检查最终 diff，并运行最窄且直接相关的测试、类型检查、构建、lint、配置或文档校验。
- R2 覆盖受影响领域及直接集成边界；R3 额外覆盖兼容性、数据、安全和恢复路径。
- 未运行的检查不得声称通过；报告失败、跳过项和原因。

## Prohibitions / 禁止事项

- 不回滚、覆盖或重置用户工作；不手改生成文件。
- 不自动执行生产操作、数据删除、破坏性契约删除或降低安全保护。
- {{PROJECT_SPECIFIC_PROHIBITIONS}}

## Architecture guardrails / 架构护栏

- {{PROJECT_SPECIFIC_INVARIANT}}
- {{SECURITY_OR_DATA_INVARIANT}}
- {{DEPENDENCY_DIRECTION_INVARIANT}}

## Optional workflows and rule precedence / 可选工作流入口与规则优先级

- AgentHub 仅在用户明确要求多 Agent 或已批准范围明确包含多 Agent 时加载。
- 用户运行时配置、固定模型矩阵、上下文/压缩/价格阈值和不可见 rollout 字段不属于项目规则；旧内容外置到非运行时迁移记录。
- Harness 仅在用户明确要求或已批准范围明确包含 Harness 时加载；两者互不自动启用。
- 单项技能按任务意图加载；不要把总入口或全部技能设为默认流程。
- 优先级：平台/沙箱/命令/CI > 当前用户范围 > 根内核 > 架构/安全/数据不变量 > 命中领域规则 > 可选工作流 > 仓库惯例。
```

## 压缩规则

- 目标不超过 4 KiB，硬上限 6 KiB；以 UTF-8 实际字节数计算。
- 40～80 行是软目标，不得用极端缩写、删除项目背景或模糊语义来追求行数。
- 根文件保留不变量和入口；把领域操作细节、长清单、例子、设计理由和可选工作流全过程下沉。
- 同一规则只保留一个权威来源；根摘要不得成为叶子完整规则的第二份副本。
