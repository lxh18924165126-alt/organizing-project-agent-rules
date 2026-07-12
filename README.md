# organizing-project-agent-rules

一个默认只能显式调用的 Codex Skill，用于审计、重构和维护仓库级 Agent 规则系统。

## 安装

在已登录同一 GitHub 账号的新电脑上，使用 Codex 的 `$skill-installer`，指定：

- 仓库：`lxh18924165126-alt/organizing-project-agent-rules`
- 路径：`skills/organizing-project-agent-rules`

也可以运行：

```bash
python3 "$CODEX_HOME/skills/.system/skill-installer/scripts/install-skill-from-github.py" \
  --repo lxh18924165126-alt/organizing-project-agent-rules \
  --path skills/organizing-project-agent-rules
```

安装后在下一轮 Codex 对话中显式调用 `$organizing-project-agent-rules`。

## 验证

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

该 Skill 保持 `allow_implicit_invocation: false`。
