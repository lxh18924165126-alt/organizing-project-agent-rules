#!/usr/bin/env python3
"""Read-only structural validation for a routed repository Agent rule system."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote


sys.dont_write_bytecode = True
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from inventory_agent_rules import (  # noqa: E402
    extract_markdown_links,
    resolve_markdown_target,
    resolve_root,
)


SCHEMA_VERSION = 1
TARGET_ROOT_BYTES = 4096
HARD_ROOT_BYTES = 6144
SOFT_MIN_LINES = 40
SOFT_MAX_LINES = 80
ALLOWED_STATUSES = {
    "kept",
    "migrated",
    "merged-duplicate",
    "conflict",
    "needs-user-input",
    "externalized-runtime-config",
}
REQUIRED_LEDGER_COLUMNS = (
    "source id",
    "source",
    "location",
    "semantic summary",
    "category",
    "authority target",
    "status",
    "evidence",
    "semantics changed",
    "conflict notes",
)
REQUIRED_ROOT_SECTIONS = (
    ("basic_conventions", ("basic conventions", "general conventions", "基本约定", "通用约定", "基础约定")),
    ("project_context", ("project context", "project background", "项目背景", "项目上下文")),
    ("risk_and_change_scale", ("risk and change scale", "risk and scope", "风险与改动规模", "风险与执行", "风险判断")),
    ("technology_and_documentation", ("technology and documentation", "tech stack and documentation", "技术栈与文档", "技术栈说明与项目相关文档", "技术与文档")),
    ("rule_routing", ("rule routing", "domain rule routing", "规则路由", "领域规则路由")),
    ("documentation_and_checkpoints", ("documentation and checkpoints", "docs and checkpoints", "文档与检查点")),
    ("minimum_verification", ("minimum verification", "minimum validation", "最低验证", "最小验证")),
    ("prohibitions", ("prohibitions", "forbidden", "禁止事项", "禁止")),
    ("architecture_guardrails", ("architecture guardrails", "architecture invariants", "架构护栏", "架构不变量")),
    (
        "optional_workflows_and_precedence",
        (
            "optional workflows and rule precedence",
            "optional workflows and precedence",
            "可选工作流入口与规则优先级",
            "可选工作流与规则优先级",
        ),
    ),
)
SCOPED_ROUTE_SECTIONS = (
    ("applies_to", ("applies to", "适用范围", "适用于")),
    ("does_not_apply_to", ("does not apply to", "不适用范围", "不适用于")),
    ("authoritative_rules", ("authoritative rules", "权威规则")),
)
MANDATORY_LINK_RE = re.compile(
    r"(?i)\bmust\b|\brequired\b|\bmandatory\b|必须|务必|强制"
)
OPTIONAL_LINK_RE = re.compile(
    r"(?i)\b(?:may|can|optional|background|reference)\b|可选|参考|背景"
)
PLAN_MODE_RE = re.compile(r"(?i)\bplan\s+mode\b|计划模式|规划模式")
PLACEHOLDER_LINE_RE = re.compile(
    r"(?i)^(?:\{\{[^}]+\}\}|\$[A-Z][A-Z0-9_]*|"
    r"\[?(?:TODO|TBD|PLACEHOLDER)\]?|<[A-Z][A-Z0-9_ -]*>)\.?$"
)
AUTOMATIC_WORKFLOW_PATTERNS = (
    re.compile(r"(?i)\balways\b.*\b(agenthub|harness)\b"),
    re.compile(r"(?i)\b(agenthub|harness)\b.*\b(always|automatically|default(?:s)?\s+on)\b"),
    re.compile(r"(?i)\b(r2|r3)\b.*\b(start|enable|invoke|use)\b.*\b(agenthub|harness)\b"),
    re.compile(r"(?i)\bharness\b.*\b(enable|start|invoke)s?\b.*\bagenthub\b"),
    re.compile(r"(?i)\b(all|every)\b.*\bsuperpowers?\b"),
    re.compile(r"(?i)\b(agenthub|harness)\b.*\bby\s+default\b"),
    re.compile(r"(?:每次|始终|总是|默认|自动).*(?:AgentHub|Harness)"),
    re.compile(r"(?:R2|R3).*(?:启用|启动|调用).*(?:AgentHub|Harness)", re.IGNORECASE),
    re.compile(r"Harness.*(?:启用|启动|调用).*AgentHub", re.IGNORECASE),
    re.compile(r"(?:全部|所有).*Superpower", re.IGNORECASE),
)
ROOT_RUNTIME_CONFIG_PATTERNS = (
    re.compile(r"\bmodel_context_window\b", re.IGNORECASE),
    re.compile(r"\bmodel_auto_compact_token_limit\b", re.IGNORECASE),
    re.compile(r"~\/\.codex\/config\.toml|\$CODEX_HOME\/[\w.-]*\.config\.toml", re.IGNORECASE),
    re.compile(r"\b(?:272000|240000|258400)\b"),
    re.compile(r"(?:price|pricing|价格|倍率|multiplier).{0,30}\b\d+(?:\.\d+)?x\b", re.IGNORECASE),
)
ROOT_UNSTABLE_AGENTHUB_PATTERNS = (
    re.compile(r"\bROUTING_HOLD\b", re.IGNORECASE),
    re.compile(r"\bparent_thread_id\b", re.IGNORECASE),
    re.compile(r"\brollout\.(?:model|effort)\b", re.IGNORECASE),
    re.compile(r"\bSol\b.{0,30}\bTerra\b.{0,30}\bLuna\b", re.IGNORECASE),
)


def issue(code: str, message: str, path: str = "", line: int | None = None) -> dict[str, object]:
    result: dict[str, object] = {"code": code, "message": message}
    if path:
        result["path"] = path
    if line is not None:
        result["line"] = line
    return result


def normalize_heading(value: str) -> str:
    value = re.sub(r"[`*_]", "", value).strip().lower()
    value = re.sub(r"[^\w\u4e00-\u9fff]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def document_sections(text: str) -> list[dict[str, object]]:
    lines = text.splitlines()
    heading_rows: list[tuple[int, int, str]] = []
    in_fence = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$", line)
        if match:
            heading_rows.append((index, len(match.group(1)), normalize_heading(match.group(2))))
    sections: list[dict[str, object]] = []
    for position, (index, level, heading) in enumerate(heading_rows):
        end = len(lines)
        for next_index, next_level, _ in heading_rows[position + 1 :]:
            if next_level <= level:
                end = next_index
                break
        body = lines[index + 1 : end]
        sections.append(
            {
                "heading": heading,
                "level": level,
                "line": index + 1,
                "start": index + 2,
                "end": end,
                "body": body,
            }
        )
    return sections


def matching_sections(
    sections: Iterable[dict[str, object]], aliases: Iterable[str]
) -> list[dict[str, object]]:
    normalized_aliases = [normalize_heading(alias) for alias in aliases]
    return [
        section
        for section in sections
        if any(
            alias == str(section["heading"]) or alias in str(section["heading"])
            for alias in normalized_aliases
        )
    ]


def section_has_meaningful_content(
    section: dict[str, object], *, reject_reference_shell: bool = False
) -> bool:
    body = "\n".join(str(line) for line in section.get("body", []))
    cleaned: list[str] = []
    in_fence = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence or not stripped or stripped.startswith("<!--"):
            continue
        stripped = re.sub(r"^(?:[-*+]|\d+[.)])\s+", "", stripped)
        cleaned.append(stripped)
    if not cleaned or any(PLACEHOLDER_LINE_RE.fullmatch(line) for line in cleaned):
        return False
    if reject_reference_shell:
        reference_shell = re.compile(
            r"(?i)^(?:(?:see|read|refer\s+to)\s+)?"
            r"(?:\[[^\]]+\]\([^)]+\)|`?[A-Z0-9_./-]+(?:\.md)?`?)\.?$|"
            r"^(?:详见|参见|见|请阅读)\s*.+$"
        )
        if all(reference_shell.fullmatch(line) for line in cleaned):
            return False
    return len(re.sub(r"\s+", " ", " ".join(cleaned)).strip()) >= 5


def meaningful_rule_content(text: str) -> bool:
    content: list[str] = []
    in_fence = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not stripped or stripped.startswith("#") or stripped.startswith("<!--"):
            continue
        content.append(stripped)
    return len(" ".join(content)) >= 12


def resolve_optional_path(root: Path, value: Path | str | None) -> Path | None:
    if value is None:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def split_markdown_row(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return []
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def is_separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def parse_ledger(path: Path) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    errors: list[dict[str, object]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return [], [issue("unreadable_migration_ledger", str(exc), str(path))]
    header_index = -1
    header: list[str] = []
    for index, line in enumerate(lines):
        cells = [normalize_heading(cell) for cell in split_markdown_row(line)]
        if "source id" in cells and "status" in cells:
            header_index = index
            header = cells
            break
    if header_index < 0:
        return [], [
            issue(
                "invalid_migration_ledger",
                "Migration ledger must contain the canonical rule table.",
                str(path),
            )
        ]
    missing_columns = [column for column in REQUIRED_LEDGER_COLUMNS if column not in header]
    if missing_columns:
        errors.append(
            issue(
                "invalid_migration_ledger",
                "Missing ledger columns: " + ", ".join(missing_columns),
                str(path),
                header_index + 1,
            )
        )
        return [], errors
    entries: list[dict[str, str]] = []
    for line_number, line in enumerate(lines[header_index + 1 :], start=header_index + 2):
        cells = split_markdown_row(line)
        if not cells or is_separator_row(cells):
            continue
        if len(cells) != len(header):
            errors.append(
                issue(
                    "invalid_migration_ledger_row",
                    f"Expected {len(header)} cells, found {len(cells)}.",
                    str(path),
                    line_number,
                )
            )
            continue
        entry = dict(zip(header, cells))
        entry["_line"] = str(line_number)
        entries.append(entry)
        required_values = [column for column in REQUIRED_LEDGER_COLUMNS if not entry.get(column, "").strip()]
        if required_values:
            errors.append(
                issue(
                    "incomplete_migration_ledger_row",
                    "Empty ledger fields: " + ", ".join(required_values),
                    str(path),
                    line_number,
                )
            )
        status = entry.get("status", "").strip().lower()
        if status and status not in ALLOWED_STATUSES:
            errors.append(
                issue(
                    "invalid_migration_status",
                    f"Unsupported status: {status}",
                    str(path),
                    line_number,
                )
            )
        semantic_value = entry.get("semantics changed", "").strip().casefold()
        semantic_aliases = {
            "yes": "yes",
            "y": "yes",
            "true": "yes",
            "是": "yes",
            "no": "no",
            "n": "no",
            "false": "no",
            "否": "no",
            "unknown": "unknown",
            "未知": "unknown",
        }
        normalized_semantic = semantic_aliases.get(semantic_value)
        if semantic_value and normalized_semantic is None:
            errors.append(
                issue(
                    "invalid_semantics_changed",
                    f"Unsupported Semantics changed value: {semantic_value}",
                    str(path),
                    line_number,
                )
            )
        elif normalized_semantic == "yes" and entry.get("conflict notes", "").strip() in {"", "-"}:
            errors.append(
                issue(
                    "semantic_change_missing_authorization",
                    "Semantic changes require an authorization or conflict note.",
                    str(path),
                    line_number,
                )
            )
        elif normalized_semantic == "unknown" and status not in {"conflict", "needs-user-input"}:
            errors.append(
                issue(
                    "semantic_change_status_mismatch",
                    "Unknown semantic change requires conflict or needs-user-input status.",
                    str(path),
                    line_number,
                )
            )
    ids = [entry.get("source id", "").strip() for entry in entries if entry.get("source id", "").strip()]
    duplicates = sorted({entry_id for entry_id in ids if ids.count(entry_id) > 1})
    if duplicates:
        errors.append(
            issue(
                "duplicate_migration_source_id",
                "Duplicate Source ID values: " + ", ".join(duplicates),
                str(path),
            )
        )
    return entries, errors


def load_baseline(path: Path) -> tuple[set[str], list[dict[str, object]]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return set(), [issue("invalid_baseline_inventory", str(exc), str(path))]
    candidates = data.get("rule_candidates") if isinstance(data, dict) else None
    if not isinstance(candidates, list):
        return set(), [
            issue(
                "invalid_baseline_inventory",
                "Baseline inventory has no rule_candidates list.",
                str(path),
            )
        ]
    ids = {
        str(item.get("id", "")).strip()
        for item in candidates
        if isinstance(item, dict) and str(item.get("id", "")).strip()
    }
    return ids, []


def is_scoped_route(rel: str) -> bool:
    parts = {part.lower() for part in Path(rel).parts}
    return bool(parts.intersection({"domains", "policies", "workflows"}))


def is_nonruntime_record(target_rel: str, ledger_rel: str | None) -> bool:
    lower_parts = {part.casefold() for part in Path(target_rel).parts}
    lower_name = Path(target_rel).name.casefold()
    record_names = {
        "migration-ledger.md",
        "migration-report.md",
        "operator-runtime-config.md",
        "rule-ledger.md",
        "rule-migration-report.md",
    }
    return bool(
        (ledger_rel and target_rel == ledger_rel)
        or lower_parts.intersection({"legacy", "archive"})
        or lower_name in record_names
    )


def markdown_anchors(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    anchors: set[str] = set()
    counts: dict[str, int] = {}
    for section in document_sections(text):
        normalized = str(section["heading"]).strip()
        base = re.sub(r"\s+", "-", normalized)
        count = counts.get(base, 0)
        counts[base] = count + 1
        anchors.add(normalized)
        if count:
            anchors.add(normalize_heading(f"{base}-{count}"))
    return anchors


def validate_ledger_authorities(
    root: Path,
    entries: list[dict[str, str]],
    routed_rule_files: set[str],
    ledger_rel: str | None,
) -> list[dict[str, object]]:
    errors: list[dict[str, object]] = []
    for entry in entries:
        status = entry.get("status", "").strip().casefold()
        category = entry.get("category", "").strip().casefold()
        raw_target = entry.get("authority target", "").strip().strip("`")
        line_number = int(entry.get("_line", "0") or 0) or None
        markdown_link = re.fullmatch(r"\[[^\]]+\]\(([^)]+)\)", raw_target)
        if markdown_link:
            raw_target = markdown_link.group(1).strip()
        target_parts = raw_target.split("#", 1)
        target_without_anchor = target_parts[0].strip()
        raw_anchor = unquote(target_parts[1]).strip() if len(target_parts) == 2 else ""
        target_anchors = {
            normalize_heading(part)
            for part in re.split(r"[/|｜／]", raw_anchor)
            if normalize_heading(part)
        }
        if raw_anchor:
            target_anchors.add(normalize_heading(raw_anchor))
        if not target_without_anchor:
            errors.append(
                issue(
                    "ledger_authority_target_missing",
                    "Authority target must name a repository file.",
                    ledger_rel or "",
                    line_number,
                )
            )
            continue
        target_path = Path(target_without_anchor).expanduser()
        if not target_path.is_absolute():
            target_path = root / target_path
        target_path = target_path.resolve()
        try:
            target_rel = target_path.relative_to(root).as_posix()
        except ValueError:
            errors.append(
                issue(
                    "ledger_authority_target_not_runtime",
                    f"Authority target is outside the repository: {raw_target}",
                    ledger_rel or "",
                    line_number,
                )
            )
            continue
        if status == "externalized-runtime-config":
            if category != "operator-runtime-config":
                errors.append(issue(
                    "externalized_runtime_config_category_mismatch",
                    "externalized-runtime-config requires operator-runtime-config category.",
                    ledger_rel or "", line_number,
                ))
            if not is_nonruntime_record(target_rel, ledger_rel):
                errors.append(issue(
                    "externalized_runtime_config_target_is_runtime",
                    "Externalized runtime config must target a non-runtime migration or operator record.",
                    ledger_rel or "", line_number,
                ))
            elif not target_path.is_file():
                errors.append(issue(
                    "ledger_authority_target_missing",
                    f"Externalized record does not exist: {raw_target}", ledger_rel or "", line_number,
                ))
            continue
        if is_nonruntime_record(target_rel, ledger_rel):
            errors.append(
                issue(
                    "ledger_authority_target_not_runtime",
                    f"Archive or migration records cannot be authority targets: {raw_target}",
                    ledger_rel or "",
                    line_number,
                )
            )
            continue
        if not target_path.is_file():
            errors.append(
                issue(
                    "ledger_authority_target_missing",
                    f"Authority target does not exist: {raw_target}",
                    ledger_rel or "",
                    line_number,
                )
            )
            continue
        if target_anchors and target_path.suffix.casefold() == ".md":
            if target_anchors.isdisjoint(markdown_anchors(target_path)):
                errors.append(
                    issue(
                        "ledger_authority_anchor_missing",
                        f"Authority target anchor does not exist: {raw_target}",
                        ledger_rel or "",
                        line_number,
                    )
                )
        instruction_target = target_path.name in {"AGENTS.md", "AGENTS.override.md"}
        mechanical_target = target_rel.startswith((".codex/rules/", ".github/workflows/"))
        if (
            target_path.suffix.casefold() == ".md"
            and not instruction_target
            and not mechanical_target
            and target_rel not in routed_rule_files
        ):
            errors.append(
                issue(
                    "ledger_authority_target_unreachable",
                    f"Markdown authority target is not directly routed from root: {raw_target}",
                    ledger_rel or "",
                    line_number,
                )
            )
    return errors


def negates_workflow_enablement(line: str) -> bool:
    return bool(
        re.search(
            r"(?i)\b(?:is|are|does|do|will|must)?\s*not\s+automatically\b|"
            r"\bnever\b.*\bautomatically\b|\bautomatically\s+(?:disabled|off)\b|"
            r"\b(?:disabled|off)\b.*\bby\s+default\b|"
            r"\bdefault(?:s)?\s+(?:to\s+)?off\b|"
            r"\b(?:do|does|must|should|will)\s+not\b.*\b(?:start|enable|use|invoke|run)\b|"
            r"\bnever\b.*\b(?:start|enable|use|invoke|run)\b|"
            r"不(?:会|得)?自动|不会默认|默认关闭|仅在.*明确|只有.*明确",
            line,
        )
    )


def has_explicit_workflow_trigger(line: str) -> bool:
    return bool(
        re.search(
            r"(?i)\b(?:only\s+(?:when|if)|requires?\s+(?:an?\s+)?explicit|"
            r"explicit(?:ly)?\s+(?:requested|approved)|user\s+(?:explicitly\s+)?requests?)\b|"
            r"\b(?:may|can)\b.*\b(?:manually|optionally|start|enable|use|invoke|run)\b|"
            r"仅在|只有|用户.*明确|明确要求|明确请求|显式要求|显式请求",
            line,
        )
    )


def is_automatic_workflow_enablement(line: str) -> bool:
    if negates_workflow_enablement(line) or has_explicit_workflow_trigger(line):
        return False
    if any(pattern.search(line) for pattern in AUTOMATIC_WORKFLOW_PATTERNS):
        return True
    if not re.search(r"(?i)\b(?:agenthub|harness)\b", line):
        return False
    return bool(
        re.search(
            r"(?i)\b(?:start|enable|use|invoke|run)\b.*\b(?:agenthub|harness)\b|"
            r"\b(?:agenthub|harness)\b\s+(?:starts|runs|launches|"
            r"is\s+enabled|is\s+used)\b|"
            r"(?:启动|启用|使用|调用|运行).*(?:AgentHub|Harness)|"
            r"(?:AgentHub|Harness).*(?:启动|启用|默认|自动|标准工作流)",
            line,
        )
    )


def is_mandatory_link_context(line: str) -> bool:
    stripped = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", line.strip())
    if MANDATORY_LINK_RE.search(stripped):
        return True
    if OPTIONAL_LINK_RE.search(stripped):
        return False
    if re.match(r"(?i)^(?:read|load|follow)\b", stripped):
        return True
    return bool(
        re.match(r"^(?:读取|阅读|加载|遵循)", stripped)
        and re.search(r"(?:前|后|时|先)", stripped)
    )


def scan_forbidden_workflows(
    documents: list[tuple[str, str]], errors: list[dict[str, object]]
) -> None:
    seen: set[tuple[str, str, int]] = set()
    for rel, text in documents:
        in_fence = False
        for line_number, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith(("```", "~~~")):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            if PLAN_MODE_RE.search(line):
                key = ("plan_mode_rule", rel, line_number)
                if key not in seen:
                    errors.append(
                        issue(
                            "plan_mode_rule",
                            "Project rules must not manage Codex plan mode.",
                            rel,
                            line_number,
                        )
                    )
                    seen.add(key)
            if is_automatic_workflow_enablement(line):
                key = ("automatic_optional_workflow", rel, line_number)
                if key not in seen:
                    errors.append(
                        issue(
                            "automatic_optional_workflow",
                            "AgentHub, Harness, or all Superpowers must not be enabled automatically.",
                            rel,
                            line_number,
                        )
                    )
                    seen.add(key)


def scan_root_runtime_boundaries(
    text: str, errors: list[dict[str, object]], warnings: list[dict[str, object]]
) -> None:
    in_fence = False
    visible_text: list[str] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        visible_text.append(line)
        if any(pattern.search(line) for pattern in ROOT_RUNTIME_CONFIG_PATTERNS):
            errors.append(issue(
                "user_runtime_config_in_root",
                "Suspected user/runtime Codex configuration must be externalized from root rules.",
                "AGENTS.md", line_number,
            ))
            warnings.append(issue(
                "do_not_access_user_runtime_config",
                "Do not automatically read, back up, or modify user-level Codex configuration.",
                "AGENTS.md", line_number,
            ))
        if any(pattern.search(line) for pattern in ROOT_UNSTABLE_AGENTHUB_PATTERNS):
            errors.append(issue(
                "unstable_agenthub_detail_in_root",
                "Optional AgentHub matrices and unstable runtime metadata belong in an explicit workflow leaf, if anywhere.",
                "AGENTS.md", line_number,
            ))
        if re.search(r"(?i)\b(?:r3|direct[- ]start)\b.*\bdanger-full-access\b|(?:R3|直接开始).*(?:danger-full-access)", line):
            errors.append(issue(
                "danger_full_access_without_explicit_authorization",
                "Risk classification or direct-start does not authorize danger-full-access.",
                "AGENTS.md", line_number,
            ))
        elif "danger-full-access" in line.casefold() and not re.search(
            r"(?i)(?:separate|per-task|explicit user|单独|针对当前任务).{0,50}(?:authori[sz]|授权)|(?:authori[sz]|授权).{0,50}(?:separate|per-task|explicit user|单独|针对当前任务)",
            line,
        ):
            errors.append(issue(
                "danger_full_access_without_explicit_authorization",
                "danger-full-access requires separate explicit per-task user authorization.",
                "AGENTS.md", line_number,
            ))
        if re.search(r"(?i)\bnever\s+delete\s+any\s+files?\b|(?:永远|一律|禁止)删除(?:任何|所有)文件", line):
            errors.append(issue(
                "overbroad_file_deletion_ban",
                "Allow deletion of in-scope repository files when reasonably required; keep destructive boundaries scoped.",
                "AGENTS.md", line_number,
            ))
    joined = "\n".join(visible_text)
    if all(re.search(rf"\b{name}\b", joined, re.IGNORECASE) for name in ("Sol", "Terra", "Luna")) and not any(
        item.get("code") == "unstable_agenthub_detail_in_root" for item in errors
    ):
        errors.append(issue(
            "unstable_agenthub_detail_in_root",
            "A full model profile matrix does not belong in root rules, including multi-line matrices.",
            "AGENTS.md",
        ))


def validate_agenthub_leaf(
    rel: str, text: str, errors: list[dict[str, object]]
) -> None:
    if "agenthub" not in rel.casefold() and "agenthub" not in text.casefold():
        return
    has_models = bool(re.search(r"\b(?:Sol|Terra|Luna)\b", text, re.IGNORECASE))
    has_deep = bool(re.search(r"deep/critical|深度/关键|深度.*关键", text, re.IGNORECASE))
    has_balanced = bool(re.search(r"balanced implementation|均衡实现", text, re.IGNORECASE))
    has_fast = bool(re.search(r"fast deterministic|快速确定", text, re.IGNORECASE))
    has_tiers = has_deep and has_balanced and has_fast
    has_fallback = bool(re.search(r"fall\s*back|fallback|nearest available capability|最近可用能力|最接近.*能力", text, re.IGNORECASE))
    if has_models and not (has_tiers and has_fallback):
        errors.append(issue(
            "agenthub_fixed_mapping_without_policy",
            "Model names require semantic capability tiers and a nearest-capability fallback principle.", rel,
        ))
    if not has_tiers:
        errors.append(issue(
            "agenthub_capability_tiers_incomplete",
            "AgentHub rules require deep/critical, balanced implementation, and fast deterministic capability tiers.", rel,
        ))
    has_single_writer = bool(re.search(r"one writer|single writer|单写者", text, re.IGNORECASE))
    has_isolation = bool(re.search(r"isolated worktrees?|隔离.*worktree|non-overlapping writable roots|不重叠.*写", text, re.IGNORECASE))
    has_integrator = bool(re.search(r"sole final integrator|唯一.*Integrator|Integrator.*唯一", text, re.IGNORECASE))
    has_ownership = bool(re.search(r"ownership|所有权|owner", text, re.IGNORECASE))
    if not (has_single_writer and has_isolation and has_integrator and has_ownership):
        errors.append(issue(
            "agenthub_write_governance_missing",
            "AgentHub rules require shared-workspace single writer, isolated parallel writers, ownership, and one Integrator.", rel,
        ))
    has_read_only = all(
        re.search(pattern, text, re.IGNORECASE)
        for pattern in (r"Explorer|调查", r"Reviewer|审查", r"Advisor|顾问", r"资料核验|read verification")
    ) and bool(re.search(r"只读|read-only", text, re.IGNORECASE))
    has_workspace_write = bool(re.search(r"workspace-write", text, re.IGNORECASE))
    has_explicit_danger = bool(re.search(r"danger-full-access.{0,80}(?:separate explicit|明确.*单独|单独.*明确)|(?:separate explicit|明确.*单独|单独.*明确).{0,80}danger-full-access", text, re.IGNORECASE))
    has_platform_allowance = bool(re.search(r"platform (?:allows?|permits?)|平台允许", text, re.IGNORECASE))
    if not (has_read_only and has_workspace_write and has_explicit_danger and has_platform_allowance):
        errors.append(issue(
            "agenthub_permission_governance_missing",
            "AgentHub rules require read-only investigation roles, owned workspace-write, and separate explicit authorization for danger-full-access.", rel,
        ))
def validate_repository(
    start: Path | str = Path.cwd(),
    ledger_path: Path | str | None = None,
    baseline_inventory_path: Path | str | None = None,
    *,
    target_root_bytes: int = TARGET_ROOT_BYTES,
    hard_root_bytes: int = HARD_ROOT_BYTES,
) -> dict[str, object]:
    root, _ = resolve_root(Path(start))
    errors: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []
    effective_target_bytes = min(max(1, target_root_bytes), TARGET_ROOT_BYTES)
    effective_hard_bytes = min(max(1, hard_root_bytes), HARD_ROOT_BYTES)
    if target_root_bytes > TARGET_ROOT_BYTES:
        warnings.append(
            issue(
                "root_target_override_ignored",
                f"Optimization target cannot exceed {TARGET_ROOT_BYTES} bytes.",
            )
        )
    if hard_root_bytes > HARD_ROOT_BYTES:
        warnings.append(
            issue(
                "root_hard_limit_override_ignored",
                f"Hard limit cannot exceed {HARD_ROOT_BYTES} bytes.",
            )
        )
    root_path = root / "AGENTS.md"
    metrics: dict[str, object] = {"bytes": 0, "lines": 0, "route_depth": 0}
    documents: list[tuple[str, str]] = []
    root_text = ""
    root_sections: list[dict[str, object]] = []
    if not root_path.is_file():
        errors.append(issue("missing_root_agents", "Root AGENTS.md does not exist.", "AGENTS.md"))
    else:
        data = root_path.read_bytes()
        root_text = data.decode("utf-8", errors="replace")
        metrics["bytes"] = len(data)
        metrics["lines"] = len(data.splitlines())
        documents.append(("AGENTS.md", root_text))
        if len(data) > effective_hard_bytes:
            errors.append(
                issue(
                    "root_over_hard_limit",
                    f"Root AGENTS.md is {len(data)} bytes; hard limit is {effective_hard_bytes}.",
                    "AGENTS.md",
                )
            )
        elif len(data) > effective_target_bytes:
            warnings.append(
                issue(
                    "root_over_target",
                    f"Root AGENTS.md is {len(data)} bytes; optimization target is {effective_target_bytes}.",
                    "AGENTS.md",
                )
            )
        line_count = int(metrics["lines"])
        if line_count < SOFT_MIN_LINES or line_count > SOFT_MAX_LINES:
            warnings.append(
                issue(
                    "root_outside_line_target",
                    f"Root AGENTS.md has {line_count} lines; soft target is {SOFT_MIN_LINES}-{SOFT_MAX_LINES}.",
                    "AGENTS.md",
                )
            )
        root_sections = document_sections(root_text)
        scan_root_runtime_boundaries(root_text, errors, warnings)
        for section_key, aliases in REQUIRED_ROOT_SECTIONS:
            matches = matching_sections(root_sections, aliases)
            if not matches:
                errors.append(
                    issue(
                        "missing_required_section",
                        f"Missing root section: {section_key}.",
                        "AGENTS.md",
                    )
                )
            elif not any(
                section_has_meaningful_content(
                    section, reject_reference_shell=section_key == "project_context"
                )
                for section in matches
            ):
                errors.append(
                    issue(
                        "empty_or_placeholder_section",
                        f"Root section is empty or contains placeholders: {section_key}.",
                        "AGENTS.md",
                        int(matches[0]["line"]),
                    )
                )

    ledger = resolve_optional_path(root, ledger_path)
    default_ledger = root / "docs" / "agent" / "reference" / "rule-migration-report.md"
    if ledger is None and default_ledger.is_file():
        ledger = default_ledger.resolve()
    ledger_rel: str | None = None
    if ledger is not None:
        try:
            ledger_rel = ledger.relative_to(root).as_posix()
        except ValueError:
            ledger_rel = str(ledger)

    routed_paths: list[Path] = []
    if root_path.is_file():
        routing_aliases = next(
            aliases for key, aliases in REQUIRED_ROOT_SECTIONS if key == "rule_routing"
        )
        routing_sections = matching_sections(root_sections, routing_aliases)
        routing_ranges = [
            (int(section["start"]), int(section["end"])) for section in routing_sections
        ]
        for link in extract_markdown_links(root_text):
            resolved = resolve_markdown_target(root, root_path, str(link["raw_target"]))
            if resolved is None:
                continue
            target_rel, exists = resolved
            line_number = int(link["line"])
            if not exists:
                errors.append(
                    issue(
                        "dangling_markdown_link",
                        f"Missing Markdown target: {target_rel}",
                        "AGENTS.md",
                        line_number,
                    )
                )
                continue
            in_routing_section = any(
                start_line <= line_number <= end_line
                for start_line, end_line in routing_ranges
            )
            if in_routing_section:
                if is_nonruntime_record(target_rel, ledger_rel):
                    errors.append(
                        issue(
                            "non_runtime_route",
                            f"Root routing points to a non-runtime record: {target_rel}",
                            "AGENTS.md",
                            line_number,
                        )
                    )
                    continue
                target_path = (root / target_rel).resolve()
                if target_path not in routed_paths:
                    routed_paths.append(target_path)
    if routed_paths:
        metrics["route_depth"] = 1

    for route_path in sorted(routed_paths):
        route_rel = route_path.relative_to(root).as_posix()
        text = route_path.read_text(encoding="utf-8", errors="replace")
        documents.append((route_rel, text))
        validate_agenthub_leaf(route_rel, text, errors)
        if "agenthub" in route_rel.casefold() and not any(
            "agenthub" in line.casefold() and has_explicit_workflow_trigger(line)
            for line in root_text.splitlines()
        ):
            errors.append(issue(
                "agenthub_explicit_trigger_missing",
                "A routed AgentHub workflow requires an explicit user-request trigger in root rules.",
                "AGENTS.md",
            ))
        if not meaningful_rule_content(text):
            errors.append(
                issue("empty_rule_file", "Routed rule file has no meaningful content.", route_rel)
            )
        route_sections = document_sections(text)
        has_scope_heading = any(
            matching_sections(route_sections, aliases)
            for _, aliases in SCOPED_ROUTE_SECTIONS
        )
        if is_scoped_route(route_rel) or has_scope_heading:
            for section_key, aliases in SCOPED_ROUTE_SECTIONS:
                matches = matching_sections(route_sections, aliases)
                if not matches:
                    errors.append(
                        issue(
                            "route_missing_scope_section",
                            f"Routed rule file is missing section: {section_key}.",
                            route_rel,
                        )
                    )
                elif not any(section_has_meaningful_content(section) for section in matches):
                    errors.append(
                        issue(
                            "route_section_empty",
                            f"Routed rule section is empty or contains placeholders: {section_key}.",
                            route_rel,
                            int(matches[0]["line"]),
                        )
                    )
        for link in extract_markdown_links(text):
            resolved = resolve_markdown_target(root, route_path, str(link["raw_target"]))
            if resolved is None:
                continue
            target_rel, exists = resolved
            line_number = int(link["line"])
            context = str(link.get("context", ""))
            if not exists:
                errors.append(
                    issue(
                        "dangling_markdown_link",
                        f"Missing Markdown target: {target_rel}",
                        route_rel,
                        line_number,
                    )
                )
            if is_mandatory_link_context(context):
                metrics["route_depth"] = max(int(metrics["route_depth"]), 2)
                errors.append(
                    issue(
                        "mandatory_route_too_deep",
                        f"Mandatory routed link exceeds one hop: {target_rel}",
                        route_rel,
                        line_number,
                    )
                )

    scan_forbidden_workflows(documents, errors)

    baseline = resolve_optional_path(root, baseline_inventory_path)
    ledger_entries: list[dict[str, str]] = []
    if ledger is not None:
        if not ledger.is_file():
            errors.append(
                issue("missing_migration_ledger", "Migration ledger does not exist.", ledger_rel or str(ledger))
            )
        else:
            ledger_entries, ledger_errors = parse_ledger(ledger)
            errors.extend(ledger_errors)
            errors.extend(
                validate_ledger_authorities(
                    root,
                    ledger_entries,
                    {path.relative_to(root).as_posix() for path in routed_paths},
                    ledger_rel,
                )
            )
    elif baseline is not None:
        errors.append(
            issue(
                "missing_migration_ledger",
                "A baseline inventory was supplied but no migration ledger exists.",
            )
        )

    baseline_ids: set[str] = set()
    if baseline is not None:
        baseline_ids, baseline_errors = load_baseline(baseline)
        errors.extend(baseline_errors)
    ledger_ids = {
        entry.get("source id", "").strip()
        for entry in ledger_entries
        if entry.get("source id", "").strip()
    }
    missing_ids = sorted(baseline_ids - ledger_ids)
    if missing_ids:
        errors.append(
            issue(
                "ledger_missing_coverage",
                "Baseline rule candidates missing from ledger: " + ", ".join(missing_ids),
                ledger_rel or "",
            )
        )
    extra_ids = sorted(ledger_ids - baseline_ids) if baseline is not None else []
    if extra_ids:
        warnings.append(
            issue(
                "ledger_ids_not_in_baseline",
                "Ledger Source IDs not present in baseline inventory: " + ", ".join(extra_ids),
                ledger_rel or "",
            )
        )

    report = {
        "schema_version": SCHEMA_VERSION,
        "root": str(root),
        "root_file": "AGENTS.md",
        "valid": not errors,
        "metrics": metrics,
        "routed_rule_files": [path.relative_to(root).as_posix() for path in sorted(routed_paths)],
        "ledger": {
            "path": ledger_rel,
            "entries": len(ledger_entries),
            "total_candidates": len(baseline_ids),
            "covered_candidates": len(baseline_ids & ledger_ids),
            "missing_source_ids": missing_ids,
        },
        "errors": errors,
        "warnings": warnings,
    }
    return report


def render_text(report: dict[str, object]) -> str:
    metrics = report["metrics"]
    lines = [
        f"Root: {report['root']}",
        f"Result: {'PASS' if report['valid'] else 'FAIL'}",
        f"Root size: {metrics['bytes']} bytes, {metrics['lines']} lines",
        f"Route depth: {metrics['route_depth']}",
        f"Routed rule files: {len(report['routed_rule_files'])}",
        f"Errors: {len(report['errors'])}",
        f"Warnings: {len(report['warnings'])}",
    ]
    for item in report["errors"]:
        location = item.get("path", "")
        if item.get("line"):
            location = f"{location}:{item['line']}"
        lines.append(f"  ERROR {item['code']} {location}: {item['message']}")
    for item in report["warnings"]:
        location = item.get("path", "")
        lines.append(f"  WARN {item['code']} {location}: {item['message']}")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only validation of repository Agent rule routing and migration coverage."
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Repository or directory to validate")
    parser.add_argument("--ledger", type=Path, help="Migration ledger path, relative to the repository")
    parser.add_argument(
        "--baseline-inventory",
        type=Path,
        help="JSON emitted by inventory_agent_rules.py before migration",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument(
        "--target-root-bytes",
        type=int,
        default=TARGET_ROOT_BYTES,
        help=f"Optional stricter optimization target; cannot exceed {TARGET_ROOT_BYTES}",
    )
    parser.add_argument(
        "--hard-root-bytes",
        type=int,
        default=HARD_ROOT_BYTES,
        help=f"Optional stricter hard limit; cannot exceed {HARD_ROOT_BYTES}",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = validate_repository(
        args.repo,
        args.ledger,
        args.baseline_inventory,
        target_root_bytes=args.target_root_bytes,
        hard_root_bytes=args.hard_root_bytes,
    )
    if args.json:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        print(render_text(report))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
