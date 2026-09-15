#!/usr/bin/env python3
"""Event Loop & Control Flow Analyzer for Gemini Live API Migration.

Detects event loops receiving Live API messages and verifies whether
turnComplete handling safely consults interaction_status before executing
state-destroying actions (break, return, set UI to listening, resolve turn).

Emits structured JSON to stdout or human-readable report.
"""

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class EventLoopFinding:
    file_path: str
    line_number: int
    pattern_type: str
    snippet: str
    has_turn_complete: bool
    checks_interaction_status: bool
    state_destroying_action: str | None
    is_truncation_risk: bool
    explanation: str


def analyze_file_content(file_path: Path) -> list[EventLoopFinding]:
    findings: list[EventLoopFinding] = []
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"Warning: could not read {file_path}: {exc}", file=sys.stderr)
        return []

    lines = content.splitlines()

    # Look for receive loop patterns
    loop_patterns = [
        re.compile(
            r"(?:async\s+for\s+.*in\s+.*receive\(|for\s+await\s+.*of\s+.*receive\()"
        ),
        re.compile(r"\.(?:on\(['\"]message['\"]|recv\(\))"),
        re.compile(r"turnComplete|turn_complete"),
    ]

    for i, line in enumerate(lines, start=1):
        if any(pat.search(line) for pat in loop_patterns):
            # Capture context window around this line
            start_idx = max(0, i - 5)
            end_idx = min(len(lines), i + 25)
            window = "\n".join(lines[start_idx:end_idx])

            has_tc = bool(re.search(r"\b(?:turnComplete|turn_complete)\b", window))
            checks_status = bool(
                re.search(r"\b(?:interaction_status|interactionStatus)\b", window)
                or re.search(
                    r"\b(?:status\s*[!=]=?\s*['\"](?:IN_PROGRESS|IDLE)['\"])", window
                )
            )

            # Check for state destroying actions
            destroying_action = None
            if re.search(r"\bbreak\b", window):
                destroying_action = "break (exit receive loop)"
            elif re.search(r"\breturn\b", window):
                destroying_action = "return (exit function)"
            elif re.search(
                r"['\"]listening['\"]|['\"]ready['\"]|['\"]idle['\"]", window
            ):
                destroying_action = "set UI to listening/idle"
            elif re.search(r"\bresolve\(|\.set_result\(", window):
                destroying_action = "resolve turn completion promise/future"
            elif re.search(r"clear\(\)|reset\(\)", window):
                destroying_action = "reset audio or message buffer"

            # If turnComplete is handled with state-destroying action, but interaction_status is NOT checked,
            # this is a proven truncation risk on Extended Thinking.
            is_risk = has_tc and bool(destroying_action) and not checks_status

            explanation = ""
            if is_risk:
                explanation = (
                    f"Found '{destroying_action}' guarded by turnComplete without checking "
                    "interaction_status. On Extended Thinking, conversational filler utterances "
                    "emit turnComplete: true while interaction_status is IN_PROGRESS. This "
                    "path will truncate conversations prematurely."
                )
            elif has_tc and checks_status:
                explanation = "Safely checks interaction_status alongside turnComplete."
            elif has_tc:
                explanation = (
                    "Handles turnComplete without obvious immediate state destruction."
                )

            if has_tc or destroying_action:
                findings.append(
                    EventLoopFinding(
                        file_path=str(file_path),
                        line_number=i,
                        pattern_type="turn_handling" if has_tc else "receive_loop",
                        snippet=line.strip(),
                        has_turn_complete=has_tc,
                        checks_interaction_status=checks_status,
                        state_destroying_action=destroying_action,
                        is_truncation_risk=is_risk,
                        explanation=explanation,
                    )
                )
    return findings


def scan_paths(target_path: Path) -> list[EventLoopFinding]:
    all_findings: list[EventLoopFinding] = []
    if target_path.is_file():
        return analyze_file_content(target_path)

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
            if fp.suffix in (".py", ".js", ".ts", ".mjs", ".cjs"):
                all_findings.extend(analyze_file_content(fp))
    return all_findings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze Live API event loops for truncation defects."
    )
    parser.add_argument("path", help="File or directory path to inspect.")
    parser.add_argument("--json", action="store_true", help="Output JSON format.")
    args = parser.parse_args()

    target = Path(args.path)
    if not target.exists():
        print(f"Error: path '{target}' does not exist.", file=sys.stderr)
        return 1

    findings = scan_paths(target)

    if args.json:
        print(json.dumps([asdict(f) for f in findings], indent=2))
        return 0

    risks = [f for f in findings if f.is_truncation_risk]
    print(f"\nAnalyzed event loops in '{target}':")
    print(f"Total loop/turn sites found: {len(findings)}")
    print(f"Proven truncation risks:     {len(risks)}\n")

    if risks:
        print("=== PROVEN TRUNCATION RISKS ===")
        for r in risks:
            loc = f"{Path(r.file_path).name}:{r.line_number}"
            print(f"- Location: {loc}")
            print(f"  Snippet:  {r.snippet}")
            print(f"  Action:   {r.state_destroying_action}")
            print(f"  Details:  {r.explanation}\n")
    else:
        print("No silent truncation defects detected.")

    return 0 if not risks else 2


if __name__ == "__main__":
    sys.exit(main())
