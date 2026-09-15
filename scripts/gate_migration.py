#!/usr/bin/env python3
"""Deterministic Migration Gate for Gemini Live API.

Evaluates preflight, workload, tool latency, and event-loop signals
to make deterministic blocker checks and migration decisions.

Outputs structured JSON verdict and actionable blockers.
"""

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class GateVerdict:
    passed: bool
    recommended_model: str
    blockers: list[str]
    warnings: list[str]
    blocker_prompt: str | None
    notes: list[str]


def evaluate_gates(
    preflight_data: dict[str, Any] | None,
    workload_data: dict[str, Any] | None,
    tools_data: list[dict[str, Any]] | None,
    event_loop_data: list[dict[str, Any]] | None,
    requested_model: str | None = None,
) -> GateVerdict:
    blockers: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []
    blocker_prompt: str | None = None

    # Determine default model recommendation
    target_model = requested_model or "gemini-3.8-live"

    # --- GATE 1: Authentication Gate ---
    if preflight_data:
        tier = preflight_data.get("tier", "NO_AUTH")
        if tier == "NO_AUTH":
            blockers.append(
                "AUTH_BLOCKER: No valid credentials found for Vertex or AI Studio."
            )
            blocker_prompt = (
                "No valid authentication credentials were found. Please configure Application "
                "Default Credentials (gcloud auth application-default login) or set GEMINI_API_KEY."
            )
            return GateVerdict(
                passed=False,
                recommended_model="none",
                blockers=blockers,
                warnings=warnings,
                blocker_prompt=blocker_prompt,
                notes=notes,
            )

        # --- GATE 2: Regional Model Reachability Gate ---
        # Check target model availability in discovered locations
        model_probes = preflight_data.get(
            "target_model_probes"
        ) or preflight_data.get("model_probes", [])
        avail_map = {}
        surface_map: dict[str, list[str]] = {}
        for mp in model_probes:
            m_id = mp.get("model_id") or mp.get("model", "")
            surf = mp.get("surface", "unknown")
            is_vis = mp.get("visible", False)
            avail_in = mp.get("available_in", [])
            if is_vis:
                surface_map.setdefault(m_id, []).append(surf)
            count = len(avail_in) if avail_in else (1 if is_vis else 0)
            avail_map[m_id] = avail_map.get(m_id, 0) + count

        count_38_live = avail_map.get("gemini-3.8-live", 0)
        count_38_ext = avail_map.get("gemini-3.8-live-extended-thinking", 0)
        surfaces_38_live = surface_map.get("gemini-3.8-live", [])

        notes.append(
            f"Model availability: gemini-3.8-live in {count_38_live} locations (surfaces: {surfaces_38_live or 'none'}); "
            f"extended-thinking in {count_38_ext} locations."
        )

        # If user/workload requests extended thinking but it is in 0 locations:
        if target_model == "gemini-3.8-live-extended-thinking" and count_38_ext == 0:
            blockers.append(
                f"UNREACHABLE_MODEL_BLOCKER: 'gemini-3.8-live-extended-thinking' is available in 0 of {preflight_data.get('notes', '')} locations."
            )
            blocker_prompt = (
                "Model 'gemini-3.8-live-extended-thinking' is not yet published in any supported "
                "locations for this project. The recommended alternative is 'gemini-3.8-live' "
                "with asynchronous tool execution. Do you want to migrate to 'gemini-3.8-live' instead?"
            )
            target_model = "gemini-3.8-live"

        # Transient Edge Case: gemini-3.8-live is available on AI Studio via GEMINI_API_KEY
        # but pending publication under Vertex AI publishers/google/models/.
        if target_model == "gemini-3.8-live":
            if count_38_live == 0:
                blockers.append(
                    "UNREACHABLE_MODEL_BLOCKER: 'gemini-3.8-live' is not available on any credentialed surface. "
                    "Supply a valid GEMINI_API_KEY for Google AI Studio, or wait for Vertex AI publication."
                )
                blocker_prompt = (
                    "Model 'gemini-3.8-live' is not available on any credentialed surface. "
                    "Please supply a valid GEMINI_API_KEY for Google AI Studio (temporary until published on Vertex), "
                    "or verify Vertex AI project enablement."
                )
            elif "aistudio" in surfaces_38_live and "vertex" not in surfaces_38_live:
                warnings.append(
                    "TRANSIENT_VERTEX_AVAILABILITY_WARNING: 'gemini-3.8-live' is available on Google AI Studio "
                    "via GEMINI_API_KEY, but is pending publication on Vertex AI. The migration will configure a "
                    "dual-surface bridge: routing to gemini-3.8-live on AI Studio when GEMINI_API_KEY is present, "
                    "with fallback to gemini-live-2.5-flash-native-audio on Vertex AI until 3.8 arrives on Vertex."
                )

    # --- GATE 3: Event-Loop Truncation Gate ---
    if event_loop_data:
        risks = [f for f in event_loop_data if f.get("is_truncation_risk")]
        if risks:
            msg = f"Found {len(risks)} event loop paths with proven conversation truncation defects."
            if target_model == "gemini-3.8-live-extended-thinking":
                blockers.append(f"EVENT_LOOP_TRUNCATION_BLOCKER: {msg}")
                blocker_prompt = (
                    f"{msg} In Extended Thinking, filler utterances emit turnComplete: true while "
                    "interaction_status is IN_PROGRESS. You must refactor the event loop to consult "
                    "interaction_status before migrating to Extended Thinking."
                )
            else:
                warnings.append(
                    f"EVENT_LOOP_WARNING: {msg} While gemini-3.8-live is not affected, fixing this is "
                    "recommended for future Extended Thinking compatibility."
                )

    # --- GATE 4: Tool Latency Gate ---
    if tools_data:
        slow_tools = [t for t in tools_data if t.get("tier") in ("Slow", "Very Slow")]
        if slow_tools:
            notes.append(
                f"Detected {len(slow_tools)} Slow/Very Slow tools. Mandatory requirement: configure "
                "these tools as 'NON_BLOCKING' to avoid blocking dialogue."
            )
            if (
                not blockers
                and count_38_ext > 0
                and not any("TRUNCATION" in b for b in blockers)
            ):
                target_model = "gemini-3.8-live-extended-thinking"
                notes.append(
                    "Selected gemini-3.8-live-extended-thinking to provide conversational fillers during slow tool execution."
                )

    # --- GATE 5: Workload Contract Checks ---
    if workload_data:
        for f in workload_data.get("files", []):
            if f.get("has_affective_dialog"):
                warnings.append(
                    f"Contract: remove enable_affective_dialog in {f.get('file')}."
                )
            if f.get("has_proactive_audio_false"):
                warnings.append(
                    f"Contract: remove proactive_audio: false in {f.get('file')}."
                )
            if target_model == "gemini-3.8-live" and f.get("has_thinking_config"):
                warnings.append(
                    f"Contract: remove thinking_config when migrating to gemini-3.8-live in {f.get('file')}."
                )

    passed = len(blockers) == 0
    return GateVerdict(
        passed=passed,
        recommended_model=target_model,
        blockers=blockers,
        warnings=warnings,
        blocker_prompt=blocker_prompt,
        notes=notes,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate deterministic migration gates."
    )
    parser.add_argument("--preflight", help="Path to preflight JSON output.")
    parser.add_argument("--workload", help="Path to workload JSON output.")
    parser.add_argument("--tools", help="Path to tools JSON output.")
    parser.add_argument("--event-loop", help="Path to event-loop JSON output.")
    parser.add_argument("--target-model", help="Explicit target model to evaluate.")
    parser.add_argument("--json", action="store_true", help="Output JSON verdict.")
    args = parser.parse_args()

    preflight = None
    if args.preflight and Path(args.preflight).exists():
        preflight = json.loads(Path(args.preflight).read_text())

    workload = None
    if args.workload and Path(args.workload).exists():
        workload = json.loads(Path(args.workload).read_text())

    tools = None
    if args.tools and Path(args.tools).exists():
        tools = json.loads(Path(args.tools).read_text())

    event_loop = None
    if args.event_loop and Path(args.event_loop).exists():
        event_loop = json.loads(Path(args.event_loop).read_text())

    verdict = evaluate_gates(
        preflight_data=preflight,
        workload_data=workload,
        tools_data=tools,
        event_loop_data=event_loop,
        requested_model=args.target_model,
    )

    if args.json:
        print(json.dumps(asdict(verdict), indent=2))
        return 0 if verdict.passed else 1

    print("\n=== MIGRATION GATE EVALUATION ===")
    print(f"Status:            {'PASSED' if verdict.passed else 'BLOCKED'}")
    print(f"Recommended Model: {verdict.recommended_model}\n")

    if verdict.blockers:
        print("BLOCKERS:")
        for b in verdict.blockers:
            print(f"  [X] {b}")
        if verdict.blocker_prompt:
            print(f'\nUser Blocker Prompt:\n"{verdict.blocker_prompt}"\n')

    if verdict.warnings:
        print("WARNINGS:")
        for w in verdict.warnings:
            print(f"  [!] {w}")

    if verdict.notes:
        print("\nNOTES:")
        for n in verdict.notes:
            print(f"  - {n}")
    print()

    return 0 if verdict.passed else 1


if __name__ == "__main__":
    sys.exit(main())
