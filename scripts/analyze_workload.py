#!/usr/bin/env python3
"""Static analyzer for Gemini Live API client codebases.

Scans Python and JavaScript/TypeScript files for Live API connection patterns,
model strings, thinking configurations, tool definitions, and event loop logic.
Outputs a structured analysis report for migration to Gemini 3.8 Live.
"""

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

LEGACY_MODELS = [
    "gemini-3.1-flash-live-preview",
    "gemini-2.5-flash-native-audio-preview-12-2025",
    "gemini-live-2.5-flash-preview",
    "gemini-2.5-flash-live",
    "gemini-2.0-flash-live-001",
]

PATTERNS = {
    "live_connect": re.compile(
        r"(client\.aio\.live\.connect|ai\.live\.connect|BidiGenerateContent)",
        re.MULTILINE,
    ),
    "legacy_model": re.compile(
        r"|".join(re.escape(m) for m in LEGACY_MODELS), re.MULTILINE
    ),
    "gemini_38_live": re.compile(r"gemini-3\.8-live(?!-extended-thinking)"),
    "gemini_38_extended": re.compile(r"gemini-3\.8-live-extended-thinking"),
    "thinking_config": re.compile(
        r"(thinking_level|thinkingLevel|thinking_config|thinkingConfig)",
        re.MULTILINE,
    ),
    "minimal_thinking": re.compile(r"""['"]?minimal['"]?""", re.IGNORECASE),
    "tool_declarations": re.compile(
        r"(function_declarations|functionDeclarations|types\.FunctionDeclaration)",
        re.MULTILINE,
    ),
    "non_blocking_tool": re.compile(
        r"""behavior['"]?\s*[:=]\s*['"]?NON_BLOCKING['"]?""", re.MULTILINE
    ),
    "blocking_tool": re.compile(
        r"""behavior['"]?\s*[:=]\s*['"]?BLOCKING['"]?""", re.MULTILINE
    ),
    "turn_complete": re.compile(r"(turn_complete|turnComplete)", re.MULTILINE),
    "interaction_status": re.compile(
        r"(interaction_status|interactionStatus)", re.MULTILINE
    ),
    "affective_dialog": re.compile(
        r"(enable_affective_dialog|enableAffectiveDialog)", re.MULTILINE
    ),
    "proactive_audio_false": re.compile(
        r"""proactive_audio['"]?\s*[:=]\s*False|proactiveAudio['"]?\s*[:=]\s*false""",
        re.MULTILINE,
    ),
}


def scan_file(file_path: Path) -> dict[str, Any]:
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, UnicodeDecodeError) as e:
        return {"error": str(e)}

    findings: dict[str, Any] = {
        "file": str(file_path),
        "has_live_api": bool(PATTERNS["live_connect"].search(content)),
        "models_found": list(set(PATTERNS["legacy_model"].findall(content))),
        "has_38_live": bool(PATTERNS["gemini_38_live"].search(content)),
        "has_38_extended": bool(PATTERNS["gemini_38_extended"].search(content)),
        "has_thinking_config": bool(PATTERNS["thinking_config"].search(content)),
        "has_minimal_thinking": bool(PATTERNS["minimal_thinking"].search(content)),
        "has_tools": bool(PATTERNS["tool_declarations"].search(content)),
        "has_non_blocking_tool": bool(PATTERNS["non_blocking_tool"].search(content)),
        "has_blocking_tool": bool(PATTERNS["blocking_tool"].search(content)),
        "tracks_turn_complete": bool(PATTERNS["turn_complete"].search(content)),
        "tracks_interaction_status": bool(
            PATTERNS["interaction_status"].search(content)
        ),
        "has_affective_dialog": bool(PATTERNS["affective_dialog"].search(content)),
        "has_proactive_audio_false": bool(
            PATTERNS["proactive_audio_false"].search(content)
        ),
    }
    return findings


def analyze_directory(root_path: Path) -> dict[str, Any]:
    valid_extensions = {".py", ".ts", ".js", ".tsx", ".jsx", ".json"}
    files_to_scan: list[Path] = []

    if root_path.is_file():
        files_to_scan.append(root_path)
    else:
        for root, dirs, files in os.walk(root_path):
            # Skip hidden and common non-source directories
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(".")
                and d not in {"node_modules", "venv", ".venv", "dist", "build"}
            ]
            for file in files:
                p = Path(root) / file
                if p.suffix.lower() in valid_extensions:
                    files_to_scan.append(p)

    results = []
    for p in files_to_scan:
        res = scan_file(p)
        if res.get("has_live_api") or res.get("models_found"):
            results.append(res)

    # Workload summary
    total_live_files = len(results)
    uses_legacy_models = any(r["models_found"] for r in results)
    uses_thinking = any(r["has_thinking_config"] for r in results)
    uses_tools = any(r["has_tools"] for r in results)
    tracks_interaction_status = any(r["tracks_interaction_status"] for r in results)

    recommended_model = "gemini-3.8-live"
    recommendation_reason = (
        "Default recommended path for low-latency voice dialogue and drop-in "
        "compatibility with existing turnComplete event loops."
    )

    if uses_tools and tracks_interaction_status:
        recommendation_reason += (
            " Existing codebase already tracks interaction_status, making "
            "gemini-3.8-live-extended-thinking a viable alternative."
        )

    return {
        "scanned_files_count": len(files_to_scan),
        "live_api_files_count": total_live_files,
        "files": results,
        "summary": {
            "uses_legacy_models": uses_legacy_models,
            "uses_thinking": uses_thinking,
            "uses_tools": uses_tools,
            "tracks_interaction_status": tracks_interaction_status,
            "recommended_model": recommended_model,
            "recommendation_reason": recommendation_reason,
        },
    }


def main():
    parser = argparse.ArgumentParser(
        description="Analyze Live API codebase for migration to Gemini 3.8 Live."
    )
    parser.add_argument(
        "path",
        type=Path,
        nargs="?",
        default=Path("."),
        help="Path to file or directory to scan",
    )
    parser.add_argument("--json", action="store_true", help="Output raw JSON results")
    args = parser.parse_args()

    report = analyze_directory(args.path)

    if args.json:
        print(json.dumps(report, indent=2))
        return

    print("==================================================")
    print("Gemini Live API Migration Audit Report")
    print("==================================================")
    print(f"Scanned Files: {report['scanned_files_count']}")
    print(f"Live API Files Detected: {report['live_api_files_count']}\n")

    summary = report["summary"]
    print(f"Uses Legacy Models: {summary['uses_legacy_models']}")
    print(f"Uses Thinking Config: {summary['uses_thinking']}")
    print(f"Uses Tools: {summary['uses_tools']}")
    print(f"Tracks interaction_status: {summary['tracks_interaction_status']}\n")

    print(f"Recommended Model: {summary['recommended_model']}")
    print(f"Reason: {summary['recommendation_reason']}\n")

    if report["files"]:
        print("Affected Files:")
        for f in report["files"]:
            print(f"  - {f['file']}")
            if f["models_found"]:
                print(f"    Legacy Models: {', '.join(f['models_found'])}")
            if f["has_thinking_config"]:
                print("    Contains thinking configuration")
            if f["has_tools"]:
                print(
                    f"    Tools declared (Non-blocking: {f['has_non_blocking_tool']}, Blocking: {f['has_blocking_tool']})"
                )
            if f["has_affective_dialog"]:
                print("    WARNING: Contains removed enable_affective_dialog")
            if f["has_proactive_audio_false"]:
                print("    WARNING: Contains proactive_audio: false (invalid)")
    else:
        print("No Live API usage found in specified path.")


if __name__ == "__main__":
    main()
