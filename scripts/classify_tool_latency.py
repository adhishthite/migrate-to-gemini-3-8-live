#!/usr/bin/env python3
"""Tool Latency Classifier for Gemini Live API Migration.

Analyzes function definitions and tool implementations in Python, TypeScript,
and JavaScript files to classify them into latency tiers:
- Instant (<50ms)
- Fast (50-500ms)
- Slow (0.5-3s)
- Very Slow (>3s)

Emits structured JSON to stdout and logs/tables to stderr.
"""

import argparse
import ast
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class ToolSignal:
    name: str
    file_path: str
    line_number: int
    tier: str  # Instant, Fast, Slow, Very Slow
    signals: list[str]
    recommended_mode: str  # BLOCKING, NON_BLOCKING


class PythonToolVisitor(ast.NodeVisitor):
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.tools: list[ToolSignal] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._analyze_function(node, is_async=False)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._analyze_function(node, is_async=True)
        self.generic_visit(node)

    def _analyze_function(self, node: ast.AST, is_async: bool) -> None:
        name = getattr(node, "name", "unknown")
        line = getattr(node, "lineno", 0)

        # Check for tool indicators or analyze all public functions
        signals: list[str] = []
        if is_async:
            signals.append("async_def")

        # Inspect decorators
        decorators = getattr(node, "decorator_list", [])
        for dec in decorators:
            dec_name = ""
            if isinstance(dec, ast.Name):
                dec_name = dec.id
            elif isinstance(dec, ast.Attribute):
                dec_name = dec.attr
            elif isinstance(dec, ast.Call):
                if isinstance(dec.func, ast.Name):
                    dec_name = dec.func.id
                elif isinstance(dec.func, ast.Attribute):
                    dec_name = dec.func.attr

            if any(k in dec_name.lower() for k in ("retry", "backoff", "tenacity")):
                signals.append(f"decorator:{dec_name} (retry/backoff)")

        # Inspect body for calls, awaits, loops
        has_network = False
        has_sleep = False
        has_db = False
        high_timeout = False
        loop_with_await = False
        await_count = 0

        for child in ast.walk(node):
            if isinstance(child, ast.Await):
                await_count += 1

            if isinstance(child, (ast.For, ast.While)):
                for sub in ast.walk(child):
                    if isinstance(sub, ast.Await):
                        loop_with_await = True

            if isinstance(child, ast.Call):
                call_str = ""
                if isinstance(child.func, ast.Name):
                    call_str = child.func.id
                elif isinstance(child.func, ast.Attribute):
                    call_str = (
                        f"{getattr(child.func.value, 'id', '')}.{child.func.attr}"
                    )

                call_lower = call_str.lower()
                if any(
                    k in call_lower
                    for k in (
                        "requests.",
                        "httpx.",
                        "aiohttp.",
                        "urllib.",
                        "http.client",
                    )
                ):
                    has_network = True
                    signals.append(f"call:{call_str} (network)")
                elif any(
                    k in call_lower
                    for k in ("query", "execute", "select", "prisma", "session.get")
                ):
                    has_db = True
                    signals.append(f"call:{call_str} (database)")
                elif "sleep" in call_lower:
                    has_sleep = True
                    signals.append(f"call:{call_str} (sleep)")

                # Check keyword arguments for timeout
                for kw in child.keywords:
                    if kw.arg == "timeout" and isinstance(kw.value, ast.Constant):
                        val = kw.value.value
                        if isinstance(val, (int, float)) and val >= 3.0:
                            high_timeout = True
                            signals.append(f"timeout:{val}s")

        if loop_with_await:
            signals.append("loop_with_await")
        if await_count > 3:
            signals.append(f"chained_awaits:{await_count}")

        # Classify tier
        if loop_with_await or high_timeout or any("retry" in s for s in signals):
            tier = "Very Slow"
            mode = "NON_BLOCKING"
        elif has_network or has_db or await_count > 1:
            tier = "Slow"
            mode = "NON_BLOCKING"
        elif has_sleep or is_async:
            tier = "Fast"
            mode = "BLOCKING"
        else:
            tier = "Instant"
            mode = "BLOCKING"

        self.tools.append(
            ToolSignal(
                name=name,
                file_path=self.file_path,
                line_number=line,
                tier=tier,
                signals=signals,
                recommended_mode=mode,
            )
        )


def analyze_python_file(file_path: Path) -> list[ToolSignal]:
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(content, filename=str(file_path))
        visitor = PythonToolVisitor(str(file_path))
        visitor.visit(tree)
        return visitor.tools
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        print(f"Warning: failed to parse {file_path}: {exc}", file=sys.stderr)
        return []


def analyze_js_ts_file(file_path: Path) -> list[ToolSignal]:
    results: list[ToolSignal] = []
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        lines = content.splitlines()

        # Regex patterns for function definitions
        func_pat = re.compile(
            r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z0-9_]+)\s*\("
        )
        const_func_pat = re.compile(
            r"^\s*(?:export\s+)?const\s+([A-Za-z0-9_]+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>"
        )

        for i, line in enumerate(lines, start=1):
            m = func_pat.search(line) or const_func_pat.search(line)
            if m:
                name = m.group(1)
                # Scan next 40 lines for body signals
                body = "\n".join(lines[i - 1 : min(i + 40, len(lines))])
                signals: list[str] = []

                if "async" in line:
                    signals.append("async_def")
                if re.search(r"\b(?:fetch|axios|http\.request)\b", body):
                    signals.append("network_call")
                if re.search(r"\b(?:prisma|db\.|query|select)\b", body):
                    signals.append("database_call")
                if re.search(r"\btimeout\s*:\s*(?:[3-9]\d{3}|\d{5,})\b", body):
                    signals.append("high_timeout")
                if re.search(r"\bfor\s*\(.*await", body) or re.search(
                    r"\bwhile\s*\(.*await", body
                ):
                    signals.append("loop_with_await")

                if any(s in ("high_timeout", "loop_with_await") for s in signals):
                    tier = "Very Slow"
                    mode = "NON_BLOCKING"
                elif any(s in ("network_call", "database_call") for s in signals):
                    tier = "Slow"
                    mode = "NON_BLOCKING"
                elif "async_def" in signals:
                    tier = "Fast"
                    mode = "BLOCKING"
                else:
                    tier = "Instant"
                    mode = "BLOCKING"

                results.append(
                    ToolSignal(
                        name=name,
                        file_path=str(file_path),
                        line_number=i,
                        tier=tier,
                        signals=signals,
                        recommended_mode=mode,
                    )
                )
    except (OSError, UnicodeDecodeError) as exc:
        print(f"Warning: failed to parse {file_path}: {exc}", file=sys.stderr)
    return results


def scan_directory(target_path: Path) -> list[ToolSignal]:
    all_tools: list[ToolSignal] = []
    if target_path.is_file():
        if target_path.suffix == ".py":
            return analyze_python_file(target_path)
        elif target_path.suffix in (".js", ".ts", ".mjs", ".cjs"):
            return analyze_js_ts_file(target_path)
        return []

    for root, _, files in os.walk(target_path):
        if any(
            ignored in root
            for ignored in (
                "node_modules",
                ".git",
                "venv",
                ".venv",
                "__pycache__",
                "dist",
                "build",
            )
        ):
            continue
        for file in files:
            fp = Path(root) / file
            if fp.suffix == ".py":
                all_tools.extend(analyze_python_file(fp))
            elif fp.suffix in (".js", ".ts", ".mjs", ".cjs"):
                all_tools.extend(analyze_js_ts_file(fp))
    return all_tools


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Classify client tool latency for Live API."
    )
    parser.add_argument("path", help="File or directory path to scan.")
    parser.add_argument("--json", action="store_true", help="Output JSON format.")
    args = parser.parse_args()

    target = Path(args.path)
    if not target.exists():
        print(f"Error: path '{target}' does not exist.", file=sys.stderr)
        return 1

    tools = scan_directory(target)

    if args.json:
        print(json.dumps([asdict(t) for t in tools], indent=2))
        return 0

    # Human-readable table
    print(f"\nDiscovered {len(tools)} function/tool implementations:\n")
    print(
        f"{'Tool Name':<25} {'Location':<35} {'Latency Tier':<12} {'Rec Mode':<14} {'Signals'}"
    )
    print("-" * 110)
    for t in tools:
        loc = f"{Path(t.file_path).name}:{t.line_number}"
        sig = ", ".join(t.signals) if t.signals else "none"
        print(f"{t.name:<25} {loc:<35} {t.tier:<12} {t.recommended_mode:<14} {sig}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
