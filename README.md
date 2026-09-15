# Gemini 3.8 Live Migration Toolkit

[![skills.sh](https://img.shields.io/badge/skills.sh-gemini--3.8--live-black?logo=vercel)](https://skills.sh)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Agent Skills](https://img.shields.io/badge/Agent_Skills-v1.0-orange)](https://agentskills.io)

Safely migrate your real-time voice agents from `gemini-3.1-flash-live-preview` to `gemini-3.8-live` or `gemini-3.8-live-extended-thinking` without breaking production.

## Why Use This Skill?

Updating a voice agent to Gemini 3.8 is not a simple find-and-replace. Upgrading without analysis can cause silent production failures:

- **Prevents Silent Conversation Truncation**: Extended Thinking emits `turnComplete: true` during conversational fillers ("Let me check that..."). Standard client event loops exit early, cutting off the conversation before the answer arrives.
- **Validates Regional Availability First**: New models roll out across regions gradually. The preflight check sweeps all 48+ Vertex locations to ensure the target model is reachable before touching code.
- **Profiles Tool Latency**: Automatically identifies whether your tools need synchronous (`BLOCKING`) or asynchronous (`NON_BLOCKING`) execution to keep voice turns responsive.
- **Eliminates Hard 400 Errors**: Detects and cleans up removed parameters (`enable_affective_dialog`, `proactive_audio: false`, invalid `thinking_level`) that fail connection handshakes.
- **Zero-Risk Refactoring**: Generates a technical migration report and diff preview for developer review before modifying any files.

---

## Migration Workflow

```mermaid
flowchart TD
    A["Voice Agent Codebase"] --> B["1. Preflight Sweep\n(Auth & 48+ Regions)"]
    B --> C["2. Workload Analysis\n(Tool Latency & Event Loops)"]
    C --> D{"Deterministic Gate"}
    D -->|"Model Reachable\n& Event Loop Safe"| E["Recommend Optimal Path"]
    D -->|"Model Not in Region\nor Truncation Risk"| F["Surface Actionable Blocker\n& Remediation"]
    E --> G["3. Technical Report\n& Diff Preview"]
    G --> H["Developer Approval"]
    H -->|"Approved"| I["4. Safe Code Refactor\n& Offline Verification"]
    H -->|"Report Only"| J["Migration Plan Delivered"]
```

---

## The `handleTurn` Silent Truncation Trap

The most common defect when migrating to Extended Thinking is premature turn termination. Here is why standard loops fail and how this skill protects your app:

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Client as Client Event Loop
    participant Model as Gemini 3.8 Extended Thinking

    User->>Model: "Book a flight to San Francisco"
    Note over Model: Begins deep reasoning & tool planning
    Model-->>Client: Conversational Filler: "Checking flights now..." (turnComplete=true, interaction_status=IN_PROGRESS)

    rect rgb(255, 230, 230)
        Note over Client: DEFECTIVE CLIENT:<br/>Treats turnComplete as idle.<br/>Closes turn & resets UI!
        Client--xModel: User is cut off. Final answer never received!
    end

    rect rgb(230, 255, 230)
        Note over Client: HARDENED CLIENT (This Skill):<br/>Checks interaction_status == IN_PROGRESS.<br/>Keeps listening & plays filler audio.
        Model->>Client: Tool Call: search_flights(SFO)
        Client->>Model: Tool Response: [Flights Found]
        Model-->>Client: Final Answer: "I found three flights..." (turnComplete=true, interaction_status=IDLE)
        Note over Client: Safely transitions UI to listening.
    end
```

---

## Model Decision Matrix

| Dimension | `gemini-3.8-live` | `gemini-3.8-live-extended-thinking` |
| :--- | :--- | :--- |
| **Primary Use Case** | Low-latency voice assistants, customer triage | Complex reasoning, diagnostics, multi-step problem solving |
| **Voice Turn Latency** | Ultra-fast (<800 ms) | Thoughtful with conversational fillers |
| **Tool Execution** | `BLOCKING` or `NON_BLOCKING` | **`NON_BLOCKING` mandatory** |
| **Event Loop Requirement**| Standard `turnComplete` handling | **Must inspect `interaction_status`** |
| **Migration Risk** | Minimal (drop-in replacement) | Moderate (requires event-loop hardening) |

---

## Installation

### For AI Coding Agents (Claude Code, Cursor, Jetski)

Install directly into your agent environment using `skills.sh`:

```bash
npx skills add adhishthite/migrate-to-gemini-3-8-live
```

Then ask your agent:
> *"Migrate my Live API application to Gemini 3.8."*

---

## Direct CLI Tools

You can also run the bundled analysis and verification tools directly from your terminal:

```bash
# 1. Sweep authentication and regional model reachability
python3 scripts/preflight_check.py .

# 2. Check for silent event loop truncation risks
python3 scripts/analyze_event_loop.py .

# 3. Classify function and tool latency tiers
python3 scripts/classify_tool_latency.py .

# 4. Verify turn handling against multi-stage mock fixtures
python3 scripts/verify_turn.py
```

---

## License

Apache License 2.0. See [LICENSE](LICENSE) for details.
