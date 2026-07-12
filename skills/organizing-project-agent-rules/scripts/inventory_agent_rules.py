#!/usr/bin/env python3
"""Read-only inventory for repository Agent instructions and rule sources."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import deque
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urlsplit


SCHEMA_VERSION = 2
EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "target",
    "vendor",
}
INSTRUCTION_NAMES = {"AGENTS.md", "AGENTS.override.md"}
FALLBACK_KEYS = {
    "project_doc_fallback_filename",
    "project_doc_fallback_filenames",
}
INLINE_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
REFERENCE_LINK_RE = re.compile(r"\[([^\]]+)\]\[([^\]]*)\]")
LINK_DEFINITION_RE = re.compile(
    r"^\s{0,3}\[([^\]]+)\]:\s*(?:<([^>]+)>|(\S+))(?:\s+.*)?$"
)
LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*?)\s*$")
RULE_PATH_HINTS = {
    "agent",
    "agents",
    "guardrail",
    "guardrails",
    "guidance",
    "guidelines",
    "instruction",
    "instructions",
    "policies",
    "policy",
    "rule",
    "rules",
    "standard",
    "standards",
    "workflow",
    "workflows",
}
RUNTIME_CONFIG_PATTERNS = (
    ("context-window", re.compile(r"\bmodel_context_window\b", re.IGNORECASE)),
    ("auto-compact-limit", re.compile(r"\bmodel_auto_compact_token_limit\b", re.IGNORECASE)),
    ("user-config-path", re.compile(r"(?:~\/\.codex\/config\.toml|\$CODEX_HOME\/[\w.-]*\.config\.toml)", re.IGNORECASE)),
    ("fixed-context-threshold", re.compile(r"\b(?:272000|240000|258400)\b")),
    ("pricing-threshold", re.compile(r"(?:price|pricing|价格|倍率|multiplier).{0,30}\b\d+(?:\.\d+)?x\b", re.IGNORECASE)),
)
ASSISTANT_EVIDENCE_NAMES = {
    "claude.md",
    "gemini.md",
    "copilot-instructions.md",
    ".github/copilot-instructions.md",
}


def run_git(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(path), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def resolve_root(start: Path) -> tuple[Path, bool]:
    start = start.expanduser().resolve()
    if start.is_file():
        start = start.parent
    result = run_git(start, "rev-parse", "--show-toplevel")
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip()).resolve(), True
    return start, False


def iter_repo_files(root: Path) -> Iterable[Path]:
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if name not in EXCLUDED_DIRS)
        base = Path(current)
        for filename in sorted(filenames):
            path = base / filename
            if path.is_symlink():
                continue
            yield path


def relative_path(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root).as_posix()


def read_text(path: Path, warnings: list[str]) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        warnings.append(f"Could not read {path}: {exc}")
        return ""


def parse_fallback_names(root: Path, warnings: list[str]) -> set[str]:
    names: set[str] = set()
    config_paths = [root / ".codex" / "config.toml", root / "codex.toml"]
    assignment = re.compile(
        r"(?ms)^\s*(project_doc_fallback_filename(?:s)?)\s*=\s*"
        r"(\[[^\]]*\]|[^\n#]+)"
    )
    for config_path in config_paths:
        if not config_path.is_file():
            continue
        text = read_text(config_path, warnings)
        for match in assignment.finditer(text):
            key, raw_value = match.groups()
            if key not in FALLBACK_KEYS:
                continue
            raw_value = raw_value.strip()
            try:
                value = ast.literal_eval(raw_value)
            except (SyntaxError, ValueError):
                warnings.append(
                    f"Could not parse {relative_path(root, config_path)} setting {key}"
                )
                continue
            values = value if isinstance(value, (list, tuple)) else [value]
            for item in values:
                if isinstance(item, str) and item.strip():
                    names.add(item.strip())
    return names


def file_metadata(root: Path, path: Path, kind: str) -> dict[str, object]:
    data = path.read_bytes()
    return {
        "path": relative_path(root, path),
        "kind": kind,
        "bytes": len(data),
        "lines": len(data.splitlines()),
    }


def extract_markdown_links(text: str) -> list[dict[str, object]]:
    definitions: dict[str, str] = {}
    in_fence = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = LINK_DEFINITION_RE.match(line)
        if match:
            definitions[match.group(1).strip().casefold()] = match.group(2) or match.group(3)

    links: list[dict[str, object]] = []
    in_fence = False
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence or LINK_DEFINITION_RE.match(line):
            continue
        for match in INLINE_LINK_RE.finditer(line):
            links.append(
                {
                    "label": match.group(1).strip(),
                    "raw_target": match.group(2).strip(),
                    "line": line_number,
                    "context": stripped,
                }
            )
        for match in REFERENCE_LINK_RE.finditer(line):
            label = match.group(1).strip()
            reference_id = (match.group(2).strip() or label).casefold()
            raw_target = definitions.get(reference_id)
            if raw_target:
                links.append(
                    {
                        "label": label,
                        "raw_target": raw_target,
                        "line": line_number,
                        "context": stripped,
                    }
                )
    return links


def rule_routing_line_ranges(text: str) -> list[tuple[int, int]]:
    lines = text.splitlines()
    headings: list[tuple[int, int, str]] = []
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
            normalized = re.sub(
                r"[^a-z0-9\u4e00-\u9fff]+", " ", match.group(2).casefold()
            ).strip()
            headings.append((index, len(match.group(1)), normalized))
    ranges: list[tuple[int, int]] = []
    aliases = ("rule routing", "domain rule routing", "规则路由", "领域规则路由")
    for position, (index, level, heading) in enumerate(headings):
        if not any(alias == heading or alias in heading for alias in aliases):
            continue
        end = len(lines)
        for next_index, next_level, _ in headings[position + 1 :]:
            if next_level <= level:
                end = next_index
                break
        ranges.append((index + 2, end))
    return ranges


def resolve_markdown_target(
    root: Path, source: Path, raw_target: str
) -> tuple[str, bool] | None:
    raw_target = raw_target.strip()
    if raw_target.startswith("<") and ">" in raw_target:
        raw_target = raw_target[1 : raw_target.index(">")]
    else:
        raw_target = raw_target.split(maxsplit=1)[0]
    if not raw_target or raw_target.startswith("#"):
        return None
    parsed = urlsplit(raw_target)
    if parsed.scheme or parsed.netloc:
        return None
    decoded = unquote(parsed.path)
    if not decoded or not decoded.lower().endswith(".md"):
        return None
    candidate = (
        (root / decoded.lstrip("/"))
        if decoded.startswith("/")
        else (source.parent / decoded)
    ).resolve()
    try:
        rel = candidate.relative_to(root).as_posix()
    except ValueError:
        return None
    return rel, candidate.is_file()


def local_markdown_targets(root: Path, source: Path, text: str) -> list[tuple[str, bool]]:
    targets: list[tuple[str, bool]] = []
    for link in extract_markdown_links(text):
        resolved = resolve_markdown_target(root, source, str(link["raw_target"]))
        if resolved is not None and resolved not in targets:
            targets.append(resolved)
    return targets


def looks_like_rule_reference(rel: str, link: dict[str, object], target_text: str) -> bool:
    lower_parts = {part.casefold() for part in Path(rel).parts}
    name_tokens = set(re.split(r"[^a-z0-9]+", Path(rel).stem.casefold()))
    path_hint = bool(RULE_PATH_HINTS.intersection(lower_parts | name_tokens))
    context = f"{link.get('label', '')} {link.get('context', '')}".casefold()
    context_hint = bool(
        re.search(
            r"\b(instruction|policy|rule|workflow|guidance|guideline|guardrail|standard)s?\b|"
            r"规则|指令|政策|工作流|指南|护栏|标准",
            context,
        )
    )
    evidence_name = Path(rel).name.casefold()
    evidence_path = (
        evidence_name.startswith(("readme", "contributing"))
        or "adr" in lower_parts
        or "architecture-decision" in lower_parts
    )
    if path_hint or context_hint:
        return True
    target_headings = {
        re.sub(
            r"[^a-z\u4e00-\u9fff]+",
            " ",
            line.lstrip().lstrip("#").strip().casefold(),
        ).strip()
        for line in target_text.splitlines()
        if line.lstrip().startswith("#")
    }
    if any(
        heading.startswith(("applies to", "authoritative rules", "适用范围", "权威规则"))
        for heading in target_headings
    ):
        return True
    if evidence_path:
        return False
    normative = re.compile(
        r"(?i)^(?:must|never|do\s+not|don't|shall|should|required|use|keep|"
        r"preserve|run|validate|ensure|avoid)\b|^(?:必须|不得|禁止|不要|应当|应|只允许|保持|运行|验证)"
    )
    return any(normative.search(candidate) for _, candidate in markdown_candidate_blocks(target_text))


def discover_instruction_files(
    root: Path, files: list[Path], fallback_names: set[str], warnings: list[str]
) -> list[dict[str, object]]:
    discovered: list[dict[str, object]] = []
    fallback_paths = {Path(name).as_posix() for name in fallback_names}
    fallback_basenames = {Path(name).name for name in fallback_names}
    for path in files:
        rel = relative_path(root, path)
        kind = ""
        if path.name == "AGENTS.md":
            kind = "agents"
        elif path.name == "AGENTS.override.md":
            kind = "agents-override"
        elif rel in fallback_paths or path.name in fallback_basenames:
            kind = "configured-fallback"
        if kind:
            try:
                discovered.append(file_metadata(root, path, kind))
            except OSError as exc:
                warnings.append(f"Could not stat {rel}: {exc}")
    for name in sorted(fallback_names):
        candidate = (root / name).resolve()
        if not candidate.is_file() and not any(item["path"] == Path(name).name for item in discovered):
            warnings.append(f"Configured fallback instruction file is missing: {name}")
    return sorted(discovered, key=lambda item: str(item["path"]))


def discover_rule_graph(
    root: Path,
    instruction_files: list[dict[str, object]],
    warnings: list[str],
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[Path]]:
    graph: list[dict[str, object]] = []
    referenced: dict[str, dict[str, object]] = {}
    content_paths: list[Path] = []
    queue: deque[tuple[Path, bool]] = deque(
        (root / str(item["path"]), True) for item in instruction_files
    )
    seen: set[str] = set()
    while queue:
        source, is_rule_content = queue.popleft()
        source = source.resolve()
        try:
            source_rel = relative_path(root, source)
        except ValueError:
            continue
        if source_rel in seen or not source.is_file():
            continue
        seen.add(source_rel)
        if is_rule_content:
            content_paths.append(source)
        text = read_text(source, warnings)
        routing_ranges = rule_routing_line_ranges(text)
        for link in extract_markdown_links(text):
            resolved = resolve_markdown_target(root, source, str(link["raw_target"]))
            if resolved is None:
                continue
            target_rel, exists = resolved
            edge = {"source": source_rel, "target": target_rel, "exists": exists}
            if edge not in graph:
                graph.append(edge)
            if exists:
                target_path = root / target_rel
                target_text = read_text(target_path, warnings)
                link_line = int(link["line"])
                routed_from_section = any(
                    start_line <= link_line <= end_line
                    for start_line, end_line in routing_ranges
                )
                target_is_rule = routed_from_section or looks_like_rule_reference(
                    target_rel, link, target_text
                )
                if target_rel not in referenced:
                    metadata = file_metadata(
                        root,
                        target_path,
                        "referenced-rule" if target_is_rule else "referenced-document",
                    )
                    referenced[target_rel] = metadata
                elif target_is_rule:
                    referenced[target_rel]["kind"] = "referenced-rule"
                if target_is_rule and target_rel not in seen:
                    queue.append((target_path, True))
            else:
                warnings.append(f"Missing Markdown reference: {source_rel} -> {target_rel}")
    graph.sort(key=lambda item: (str(item["source"]), str(item["target"])))
    return graph, [referenced[path] for path in sorted(referenced)], content_paths


def split_candidate_sentences(text: str) -> list[str]:
    return [
        item.strip()
        for item in re.split(r"(?<=[.!?。！？])\s+(?=[A-Z0-9`*_\u4e00-\u9fff])", text)
        if item.strip()
    ]


def markdown_candidate_blocks(text: str) -> list[tuple[int, str]]:
    lines = text.splitlines()
    table_headers = {
        index
        for index in range(len(lines) - 1)
        if lines[index].strip().startswith("|")
        and lines[index + 1].strip().startswith("|")
        and all(
            re.fullmatch(r":?-{3,}:?", cell.strip())
            for cell in lines[index + 1].strip().strip("|").split("|")
        )
    }
    blocks: list[tuple[int, str]] = []
    paragraph: list[str] = []
    paragraph_line = 0
    list_parts: list[str] = []
    list_line = 0
    in_fence = False

    def flush_paragraph() -> None:
        nonlocal paragraph, paragraph_line
        if paragraph:
            combined = re.sub(r"\s+", " ", " ".join(paragraph)).strip()
            for sentence in split_candidate_sentences(combined):
                blocks.append((paragraph_line, sentence))
        paragraph = []
        paragraph_line = 0

    def flush_list() -> None:
        nonlocal list_parts, list_line
        if list_parts:
            combined = re.sub(r"\s+", " ", " ".join(list_parts)).strip()
            blocks.append((list_line, combined))
        list_parts = []
        list_line = 0

    for index, line in enumerate(lines):
        line_number = index + 1
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            flush_paragraph()
            flush_list()
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if list_parts and line[:1].isspace() and stripped and not LIST_ITEM_RE.match(line):
            list_parts.append(stripped)
            continue
        flush_list()
        if not stripped:
            flush_paragraph()
            continue
        if LINK_DEFINITION_RE.match(line) or stripped.startswith("<!--"):
            flush_paragraph()
            continue
        if re.match(r"^\s{0,3}#{1,6}\s+", line) or re.fullmatch(r"[-*_]{3,}", stripped):
            flush_paragraph()
            continue
        list_match = LIST_ITEM_RE.match(line)
        if list_match:
            flush_paragraph()
            list_line = line_number
            list_parts = [re.sub(r"^\[[ xX]\]\s*", "", list_match.group(1)).strip()]
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            flush_paragraph()
            if index in table_headers:
                continue
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if cells and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
                continue
            content = " | ".join(cell for cell in cells if cell)
            if content:
                blocks.append((line_number, content))
            continue
        cleaned = re.sub(r"^>\s?", "", stripped)
        if not paragraph:
            paragraph_line = line_number
        paragraph.append(cleaned)
    flush_list()
    flush_paragraph()
    return blocks


def extract_rule_candidates(
    root: Path, paths: Iterable[Path], warnings: list[str]
) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    for path in sorted(set(paths)):
        rel = relative_path(root, path)
        for line_number, text in markdown_candidate_blocks(read_text(path, warnings)):
            if not text:
                continue
            normalized = re.sub(r"\s+", " ", text)
            source = f"{rel}:{line_number}:{normalized}"
            candidate_id = "R-" + hashlib.sha256(source.encode("utf-8")).hexdigest()[:12]
            candidates.append(
                {"id": candidate_id, "source": rel, "line": line_number, "text": normalized}
            )
    return candidates


def detect_suspected_runtime_config(
    root: Path, paths: Iterable[Path], warnings: list[str]
) -> list[dict[str, object]]:
    """Inspect repository rule documents only; never consult user-level config."""
    findings: list[dict[str, object]] = []
    for path in sorted(set(paths)):
        rel = relative_path(root, path)
        for line_number, line in enumerate(read_text(path, warnings).splitlines(), start=1):
            for kind, pattern in RUNTIME_CONFIG_PATTERNS:
                if pattern.search(line):
                    findings.append(
                        {"source": rel, "line": line_number, "kind": kind, "text": line.strip()}
                    )
    return findings


def is_candidate_source(rel: str) -> bool:
    path = Path(rel)
    lower = rel.lower()
    name = path.name.lower()
    parts = {part.lower() for part in path.parts}
    if name in {
        ".node-version",
        ".nvmrc",
        ".python-version",
        ".ruby-version",
        ".tool-versions",
        "app.py",
        "build.gradle",
        "build.gradle.kts",
        "cargo.toml",
        "composer.json",
        "dockerfile",
        "gemfile",
        "go.mod",
        "index.ts",
        "index.tsx",
        "jenkinsfile",
        "justfile",
        "lib.rs",
        "main.go",
        "main.py",
        "main.rs",
        "main.ts",
        "makefile",
        "mise.toml",
        "package.json",
        "pnpm-workspace.yaml",
        "pom.xml",
        "program.cs",
        "pyproject.toml",
        "tsconfig.json",
        "turbo.json",
        "runtime.txt",
    }:
        return True
    if name.startswith(("readme", "contributing", "requirements")):
        return True
    if name.endswith((".lock", "lock.yaml", "lock.json")):
        return True
    if name.startswith((".eslint", ".prettier", "biome", "ruff", "mypy")):
        return True
    if name.startswith(("docker-compose", "vite.config", "webpack.config")):
        return True
    if "generated" in name or any(part.lower() == "generated" for part in path.parts):
        return True
    if ".codex" in parts or ".agents" in parts:
        return True
    if "adr" in parts or "architecture" in parts:
        return True
    if ".github" in parts and "workflows" in parts:
        return True
    if name == ".gitlab-ci.yml" or lower.startswith(".circleci/"):
        return True
    if "test" in parts or "tests" in parts:
        return True
    if parts.intersection({"contracts", "schemas", "database", "migrations", "prisma", "infra", "infrastructure"}):
        return True
    if name in {"schema.json", "schema.sql", "schema.prisma", "openapi.json", "openapi.yaml", "openapi.yml"}:
        return True
    return False


def discover_noncanonical_instruction_evidence(
    root: Path, files: Iterable[Path]
) -> tuple[list[str], list[str]]:
    anomalous: list[str] = []
    assistant_evidence: list[str] = []
    for path in files:
        rel = relative_path(root, path)
        name = path.name.casefold()
        if name in {"agents.md", "agents.override.md", "agent.md"} and path.name not in INSTRUCTION_NAMES:
            anomalous.append(rel)
        if name in ASSISTANT_EVIDENCE_NAMES or rel.casefold() in ASSISTANT_EVIDENCE_NAMES:
            assistant_evidence.append(rel)
    return sorted(set(anomalous)), sorted(set(assistant_evidence))


def detect_domain_signals(root: Path, files: Iterable[Path]) -> dict[str, bool]:
    signals = {name: False for name in (
        "frontend", "backend", "contracts", "database", "security", "infrastructure"
    )}
    for path in files:
        rel = relative_path(root, path).casefold()
        parts = set(Path(rel).parts)
        if rel.startswith("docs/agent/"):
            continue
        name = path.name.casefold()
        if parts.intersection({"frontend", "web", "ui"}) or "apps/web" in rel:
            signals["frontend"] = True
        if parts.intersection({"backend", "server", "api", "services"}) or name in {"main.py", "main.go", "program.cs"}:
            signals["backend"] = True
        if parts.intersection({"contracts", "schemas"}) or any(token in rel for token in ("openapi", "shared/types", "schema.json")):
            signals["contracts"] = True
        if parts.intersection({"database", "migrations", "prisma"}) or name in {"schema.sql", "schema.prisma"}:
            signals["database"] = True
        if parts.intersection({"auth", "security", "identity"}):
            signals["security"] = True
        if parts.intersection({"infra", "infrastructure", "terraform"}) or any(
            token in rel for token in (".github/workflows/", ".gitlab-ci", ".circleci/", "dockerfile", "docker-compose")
        ):
            signals["infrastructure"] = True
        if name == "package.json":
            try:
                package_text = path.read_text(encoding="utf-8", errors="replace").casefold()
            except OSError:
                package_text = ""
            if any(token in package_text for token in ('"react"', '"vue"', '"svelte"', '"next"')):
                signals["frontend"] = True
    return signals


def select_mode(
    root: Path,
    graph: list[dict[str, object]],
    *,
    has_rule_issues: bool = False,
    requested_mode: str | None = None,
) -> tuple[str, bool, list[str]]:
    root_path = root / "AGENTS.md"
    reasons: list[str] = []
    if not root_path.is_file():
        automatic = "bootstrap"
        reasons.append("root AGENTS.md is missing")
    else:
        text = root_path.read_text(encoding="utf-8", errors="replace")
        routing_present = bool(rule_routing_line_ranges(text))
        normalized_headings = {
            re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", line.lstrip("# ").casefold()).strip()
            for line in text.splitlines() if re.match(r"^\s{0,3}#{1,6}\s+", line)
        }
        required_heading_groups = (
            ("basic conventions", "基本约定"), ("project context", "项目背景"),
            ("risk and change scale", "风险与改动规模"), ("technology and documentation", "技术栈与文档"),
            ("rule routing", "规则路由"), ("documentation and checkpoints", "文档与检查点"),
            ("minimum verification", "最低验证"), ("prohibitions", "禁止事项"),
            ("architecture guardrails", "架构护栏"),
            ("optional workflows and rule precedence", "可选工作流入口与规则优先级"),
        )
        root_structure_complete = all(
            any(
                alias == heading or alias in heading
                for alias in aliases for heading in normalized_headings
            )
            for aliases in required_heading_groups
        )
        root_edges = [edge for edge in graph if edge.get("source") == "AGENTS.md"]
        broken_route = any(not bool(edge.get("exists")) for edge in root_edges)
        partial_rule_tree = (root / "docs" / "agent").exists()
        root_over_hard_limit = root_path.stat().st_size > 6144
        if routing_present and (
            broken_route or root_over_hard_limit or has_rule_issues
            or not root_structure_complete or (partial_rule_tree and not root_edges)
        ):
            automatic = "repair"
            reasons.append("existing routing structure is incomplete, duplicated, over budget, or has missing targets")
        elif not routing_present:
            automatic = "migrate"
            reasons.append("root AGENTS.md exists without a normalized routing section")
        else:
            automatic = "audit"
            reasons.append("root routing exists and its direct targets are present")
    if requested_mode is None:
        return automatic, True, reasons
    applicable = requested_mode == automatic
    if not applicable:
        reasons.append(f"requested mode {requested_mode} is not applicable; automatic mode is {automatic}")
    return requested_mode, applicable, reasons


def build_evidence_candidates(candidate_sources: Iterable[str]) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    for rel in sorted(set(candidate_sources)):
        lower = rel.casefold()
        name = Path(rel).name.casefold()
        if name.startswith(("readme", "contributing")) or "adr" in Path(lower).parts:
            source_type = "documentation"
            confidence = "medium"
        elif any(token in lower for token in (".github/workflows/", ".gitlab-ci", ".circleci/")):
            source_type = "machine-config"
            confidence = "high"
        elif name.endswith((".lock", "lock.yaml", "lock.json")) or name in {
            "package.json", "pyproject.toml", "cargo.toml", "go.mod", "pom.xml",
            "build.gradle", "build.gradle.kts", "tsconfig.json", "dockerfile",
            "schema.json", "schema.sql", "schema.prisma", "openapi.json", "openapi.yaml", "openapi.yml",
        }:
            source_type = "machine-config"
            confidence = "high"
        else:
            source_type = "repository-evidence"
            confidence = "low"
        digest = hashlib.sha256(f"{rel}:{source_type}".encode("utf-8")).hexdigest()[:12]
        candidates.append({
            "id": f"E-{digest}",
            "source": rel,
            "location": "file",
            "source_type": source_type,
            "confidence": confidence,
            "existing_explicit_rule": False,
            "inferred_from_repository": True,
            "user_confirmed": False,
            "summary": f"Candidate repository evidence from {rel}; inspect before deriving any rule.",
        })
    return candidates


def collect_inventory(
    start: Path | str = Path.cwd(), requested_mode: str | None = None
) -> dict[str, object]:
    root, is_git = resolve_root(Path(start))
    warnings: list[str] = []
    files = list(iter_repo_files(root))
    fallback_names = parse_fallback_names(root, warnings)
    instructions = discover_instruction_files(root, files, fallback_names, warnings)
    graph, referenced, content_paths = discover_rule_graph(root, instructions, warnings)
    anomalous_instructions, assistant_evidence = discover_noncanonical_instruction_evidence(
        root, files
    )
    domain_signals = detect_domain_signals(root, files)
    rule_candidates = extract_rule_candidates(root, content_paths, warnings)
    normalized_candidate_texts = [
        re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", str(item["text"]).casefold()).strip()
        for item in rule_candidates
    ]
    has_rule_issues = len(normalized_candidate_texts) != len(set(normalized_candidate_texts))
    mode, mode_applicable, mode_reasons = select_mode(
        root, graph, has_rule_issues=has_rule_issues, requested_mode=requested_mode
    )
    suspected_runtime_config = detect_suspected_runtime_config(
        root, content_paths, warnings
    )
    instruction_paths = {str(item["path"]) for item in instructions}
    referenced_rule_paths = {
        str(item["path"]) for item in referenced if item.get("kind") == "referenced-rule"
    }
    candidate_sources = sorted(
        relative_path(root, path)
        for path in files
        if relative_path(root, path) not in instruction_paths
        and relative_path(root, path) not in referenced_rule_paths
        and is_candidate_source(relative_path(root, path))
    )
    evidence_candidates = build_evidence_candidates(candidate_sources)
    git_status: list[str] = []
    if is_git:
        status = run_git(root, "status", "--short", "--untracked-files=all")
        if status.returncode == 0:
            git_status = [line for line in status.stdout.splitlines() if line]
        else:
            warnings.append("Could not read git status")
    return {
        "schema_version": SCHEMA_VERSION,
        "root": str(root),
        "root_agents_exists": (root / "AGENTS.md").is_file(),
        "mode": mode,
        "mode_applicable": mode_applicable,
        "mode_reasons": mode_reasons,
        "version_controlled": is_git,
        "git_status": git_status,
        "instruction_files": instructions,
        "anomalous_instruction_files": anomalous_instructions,
        "assistant_evidence_files": assistant_evidence,
        "domain_signals": domain_signals,
        "configured_fallback_names": sorted(fallback_names),
        "referenced_documents": referenced,
        "link_graph": graph,
        "rule_candidates": rule_candidates,
        "suspected_runtime_config": suspected_runtime_config,
        "candidate_sources": candidate_sources,
        "evidence_candidates": evidence_candidates,
        "warnings": sorted(set(warnings)),
    }


def render_text(report: dict[str, object]) -> str:
    instruction_files = report["instruction_files"]
    rule_candidates = report["rule_candidates"]
    candidate_sources = report["candidate_sources"]
    link_graph = report["link_graph"]
    warnings = report["warnings"]
    lines = [
        f"Root: {report['root']}",
        f"Mode: {report['mode']} ({'applicable' if report['mode_applicable'] else 'not applicable'})",
        f"Version controlled: {'yes' if report['version_controlled'] else 'no'}",
        f"Instruction files: {len(instruction_files)}",
        f"Referenced Markdown documents: {len(report['referenced_documents'])}",
        f"Rule candidates: {len(rule_candidates)}",
        f"Suspected runtime config rules: {len(report['suspected_runtime_config'])}",
        f"Candidate evidence sources: {len(candidate_sources)}",
        f"Evidence candidates: {len(report['evidence_candidates'])}",
        f"Link edges: {len(link_graph)}",
        f"Warnings: {len(warnings)}",
    ]
    for item in instruction_files:
        lines.append(
            f"  - {item['path']} ({item['kind']}, {item['bytes']} bytes, {item['lines']} lines)"
        )
    for warning in warnings:
        lines.append(f"  ! {warning}")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only inventory of repository Agent instruction files and rule sources."
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Repository or directory to scan")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument(
        "--mode", choices=("bootstrap", "migrate", "repair", "audit"),
        help="Optional user-requested mode; applicability is reported, not assumed",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = collect_inventory(args.repo, requested_mode=args.mode)
    if args.json:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        print(render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
