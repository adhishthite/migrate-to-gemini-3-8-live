---
name: migrate-to-gemini-3-8-live
description: Use this skill to migrate Gemini Live API applications from legacy preview models (gemini-3.1-flash-live-preview, gemini-2.5-flash-native-audio-preview) to Gemini 3.8 Live (gemini-3.8-live) or Gemini 3.8 Live Extended Thinking (gemini-3.8-live-extended-thinking). Runs a credential and model-availability preflight across Vertex/Agent Platform and AI Studio, analyzes codebase use cases, verifies against latest documentation, recommends a target model, generates a technical migration report, requests confirmation before refactoring, and runs only the verification its capability tier permits.
license: Apache-2.0
compatibility: Requires Python 3.10+, gcloud CLI, Application Default Credentials (ADC) or GEMINI_API_KEY, and network access.
metadata:
  version: "1.0.0"
  author: adhishthite
---

# Gemini 3.8 Live Migration Toolkit

This skill safely migrates production voice applications from `gemini-3.1-flash-live-preview` (and earlier preview models) to `gemini-3.8-live` or `gemini-3.8-live-extended-thinking`.

## Migration Doctrine

Follow these principles during every migration:
- **Signals before source**: Do not inspect or modify source files before running preflight and analysis scripts. Read [references/doctrine.md](references/doctrine.md).
- **Three lenses of validation**: Examine contract safety (Lens 1), control flow and event loops (Lens 2), and tool behavior and latency (Lens 3).
- **Deterministic gates**: Scripts determine blockers and recommendations. Models must not guess target models from simple pattern matches.
- **Respect regional availability**: If a model is published in zero project locations, halt the migration.
- **Progressive disclosure**:
  - Read [references/migration_matrix.md](references/migration_matrix.md) when comparing parameters, protocols, or breaking changes.
  - Read [references/event_loop_patterns.md](references/event_loop_patterns.md) when analyzing receive loops, `turnComplete`, or `interaction_status`.
  - Read [references/tool_classification.md](references/tool_classification.md) when classifying tool latency or selecting tool execution modes.
  - Read [assets/report_template.md](assets/report_template.md) before writing the technical migration report.
  - Read [assets/mock_fixtures.py](assets/mock_fixtures.py) when running offline event-loop verification tests.

## Gotchas

- **The `handleTurn` Truncation Trap**: In `gemini-3.8-live-extended-thinking`, `turnComplete: true` is emitted on conversational filler utterances while `interaction_status` is `IN_PROGRESS`. Client loops that treat `turnComplete` as idle will disconnect or reset state prematurely. The conversation truncates silently without an error.
- **Regional Model Availability**: `gemini-3.8-live-extended-thinking` may be published in zero locations for a given project. The preflight check sweeps all discovered locations. Never refactor code for an unreachable model.
- **Rejected Placeholder API Keys**: Shell environments often contain non-functional or expired `GEMINI_API_KEY` placeholders. The preflight validates the key against the API and falls back to Vertex Application Default Credentials (ADC).
- **Hard Configuration Errors**:
  - Setting `thinking_config` or `thinking_level` on `gemini-3.8-live` causes a 400 error.
  - Setting `thinking_level: "minimal"` on `gemini-3.8-live-extended-thinking` causes a 400 error.
  - Setting `behavior: "BLOCKING"` on `gemini-3.8-live-extended-thinking` causes a 400 error.
  - Setting `enable_affective_dialog` causes a 400 error on all 3.8 models.
  - Setting `proactive_audio: false` causes a 400 error on all 3.8 models.

## Prerequisites

- Python 3.10+
- Google Cloud SDK (`gcloud`) with Application Default Credentials, or a valid `GEMINI_API_KEY`.
- Target application repository or file path.

## Run Directory

Create a fresh run directory for each migration session:

```bash
RUN_DIR="$(mktemp -d -t gemini-migrate-XXXXXX)"
```

## Migration Pipeline

### 1. Collect Signals

Run signal collection from the repository root:

```bash
python3 scripts/preflight_check.py <codebase-root> --json > "$RUN_DIR/preflight.json" 2> "$RUN_DIR/preflight.stderr"
python3 scripts/analyze_workload.py <codebase-root> --json > "$RUN_DIR/workload.json" 2> "$RUN_DIR/workload.stderr"
python3 scripts/classify_tool_latency.py <codebase-root> --json > "$RUN_DIR/tools.json" 2> "$RUN_DIR/tools.stderr"
python3 scripts/analyze_event_loop.py <codebase-root> --json > "$RUN_DIR/event_loop.json" 2> "$RUN_DIR/event_loop.stderr"
```

The preflight check outputs a capability tier:
- `LIVE_VERIFIED`: Live session handshake verified.
- `MODEL_VISIBLE`: Model listed in project locations.
- `AUTH_ONLY`: Valid credentials, but target model is not published.
- `NO_AUTH`: No valid credentials found.

### 2. Evaluate Deterministic Gates

Evaluate signals through deterministic gates:

```bash
python3 scripts/gate_migration.py \
  --preflight "$RUN_DIR/preflight.json" \
  --workload "$RUN_DIR/workload.json" \
  --tools "$RUN_DIR/tools.json" \
  --event-loop "$RUN_DIR/event_loop.json" \
  --json > "$RUN_DIR/gate_verdict.json"
```

#### Blocker: Unreachable Model Gate
If `gate_verdict.json` contains `UNREACHABLE_MODEL_BLOCKER`, stop and present this prompt:

```text
Model '<MODEL>' is not published in any supported locations for this project.
The recommended alternative is 'gemini-3.8-live' with asynchronous tool execution.
Do you want to migrate to 'gemini-3.8-live' instead?
```

#### Blocker: Event Loop Truncation Gate
If `gate_verdict.json` contains `EVENT_LOOP_TRUNCATION_BLOCKER` and Extended Thinking is requested, do not modify the model string until the receive loop is refactored to check `interaction_status`.

### 3. Recommend Target Model via `ask_question`

Present the recommended model path using `ask_question`:

- **Question**: `"We completed the migration analysis. Which target model path do you want to select?"`
- **Options**:
  - `"(Recommended) Gemini 3.8 Live: Low-latency voice dialogue, drop-in replacement, minimal code changes."`
  - `"Gemini 3.8 Live Extended Thinking: Deep reasoning, asynchronous tools, and conversational fillers."`

### 4. Generate Technical Migration Report

Do not edit code before presenting the report. Draft the report using the structure in [assets/report_template.md](assets/report_template.md):

1. Executive Summary and Blocker Status.
2. Preflight and Regional Availability.
3. Three-Lens Analysis Findings (Contract, Control Flow, Tool Latency).
4. Recommended Target Model and Rationale.
5. Required Changes Inventory (File paths, lines, diffs).
6. Rollback Plan.
7. Verification Checklist.

Call `ask_question` for developer approval:
- **Question**: `"The migration report is ready. How do you want to proceed?"`
- **Options**:
  - `"(Recommended) Apply the code changes and run verification tests."`
  - `"Report only — do not modify code."`
  - `"Create a condensed decision summary."`

### 5. Refactor Code

Execute refactoring according to the selected model path:

#### Path A: `gemini-3.8-live`
1. Update model identifier to `gemini-3.8-live`.
2. Remove `thinking_config` and `thinking_level`.
3. Remove `enable_affective_dialog` and `proactive_audio: false`.
4. If tools are slow (>500ms), set `behavior: "NON_BLOCKING"`.
5. Preserve existing `turnComplete` receive loop logic.

#### Path B: `gemini-3.8-live-extended-thinking`
1. Update model identifier to `gemini-3.8-live-extended-thinking`.
2. Set `thinking_level` to `"low"`, `"medium"`, or `"high"`. Remove `"minimal"`.
3. Set `behavior: "NON_BLOCKING"` on all tool declarations.
4. Refactor receive loops to inspect `interaction_status`:
   - Keep loop active when `turnComplete: true` and `status == "IN_PROGRESS"`.
   - Transition to idle only when `status == "IDLE"`.
   - Route conversational filler audio to the playback queue.

### 6. Verification

Execute verification bounded by the capability tier:

1. **Offline Turn Verification**:
   ```bash
   python3 scripts/verify_turn.py
   ```
2. **Repository Test Suite**: Run `pytest`, `bun test`, `make test`, or `make check`.
3. **Linter and Type Checks**: Run `ruff check .` or `biome check .`.
4. **Live Verification (Only if `LIVE_VERIFIED`)**:
   Ask user permission before initiating any live audio probe.
