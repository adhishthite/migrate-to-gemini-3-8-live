#!/usr/bin/env python3
"""Offline Turn Verification Harness for Gemini Live API Migration.

Replays mock multi-stage turns against event-loop fixtures to verify:
1. Standard turn completion.
2. Extended Thinking conversational filler handling (no premature exit).
3. Tool call dispatch and final answer completion.

Uses assets/mock_fixtures.py. Requires zero network and zero audio processing.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Locate mock fixtures in assets/
ASSETS_DIR = Path(__file__).parent.parent / "assets"
sys.path.insert(0, str(ASSETS_DIR))

try:
    from mock_fixtures import (
        MOCK_38_EXTENDED_THINKING_TURN,
        MOCK_38_LIVE_STANDARD_TURN,
    )
except ImportError:
    MOCK_38_LIVE_STANDARD_TURN = []
    MOCK_38_EXTENDED_THINKING_TURN = []


def simulate_receive_loop(
    messages: list[dict[str, Any]], check_interaction_status: bool = True
) -> dict[str, Any]:
    """Simulates a client receive loop processing the given message stream."""
    received_fillers = 0
    received_tool_calls = 0
    received_final_answer = False
    truncated_early = False
    session_ended = False

    for msg in messages:
        if session_ended:
            break

        server_content = msg.get("serverContent")
        tool_call = msg.get("toolCall")

        if tool_call:
            received_tool_calls += len(tool_call.get("functionCalls", []))

        if server_content:
            status = server_content.get("interactionStatus")
            is_turn_complete = server_content.get("turnComplete", False)

            # Check if this is a filler
            if status == "IN_PROGRESS" and is_turn_complete:
                received_fillers += 1
                # If client does NOT check interaction_status and exits on turnComplete:
                if not check_interaction_status:
                    truncated_early = True
                    session_ended = True
                    break

            if status == "IDLE" or (is_turn_complete and not status):
                received_final_answer = True
                session_ended = True

    return {
        "success": received_final_answer and not truncated_early,
        "truncated_early": truncated_early,
        "received_fillers": received_fillers,
        "received_tool_calls": received_tool_calls,
        "received_final_answer": received_final_answer,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify event loop turn handling against mock fixtures."
    )
    parser.add_argument(
        "--test-defective",
        action="store_true",
        help="Simulate a defective client ignoring interaction_status.",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON results.")
    args = parser.parse_args()

    # Test 1: Standard Turn
    res_std = simulate_receive_loop(
        MOCK_38_LIVE_STANDARD_TURN, check_interaction_status=not args.test_defective
    )

    # Test 2: Extended Thinking Multi-Stage Turn
    res_ext = simulate_receive_loop(
        MOCK_38_EXTENDED_THINKING_TURN, check_interaction_status=not args.test_defective
    )

    results = {
        "standard_turn": res_std,
        "extended_thinking_turn": res_ext,
        "overall_passed": res_std["success"] and res_ext["success"],
    }

    if args.json:
        print(json.dumps(results, indent=2))
        return 0 if results["overall_passed"] else 1

    print("\n=== OFFLINE TURN VERIFICATION ===")
    print("1. Standard 3.8 Live Turn:")
    print(f"   Status: {'PASSED' if res_std['success'] else 'FAILED'}")

    print("2. Extended Thinking Multi-Stage Turn:")
    print(f"   Status:                 {'PASSED' if res_ext['success'] else 'FAILED'}")
    print(f"   Fillers Processed:      {res_ext['received_fillers']}")
    print(f"   Tool Calls Handled:     {res_ext['received_tool_calls']}")
    print(f"   Final Answer Reached:   {res_ext['received_final_answer']}")
    if res_ext["truncated_early"]:
        print("   [CRITICAL] Truncated prematurely during filler utterance!")

    print(f"\nOverall Result: {'PASSED' if results['overall_passed'] else 'FAILED'}\n")
    return 0 if results["overall_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
