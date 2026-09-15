# Gemini Live API Migration Report

## 1. Executive Summary
- Current Model: `{CURRENT_MODEL}`
- Recommended Model: `{RECOMMENDED_MODEL}`
- Migration Risk Level: `{LOW | MEDIUM | HIGH}`
- Blocker Status: `{NONE | BLOCKED: reason}`

## 2. Preflight & Regional Availability
- Capability Tier: `{CAPABILITY_TIER}`
- Authentication Surface: `{VERTEX | AI_STUDIO | BOTH}`
- Target Model Availability:
  - `gemini-3.8-live`: `{AVAILABLE_REGIONS_COUNT}` locations (e.g., `{REGIONS_SAMPLE}`)
  - `gemini-3.8-live-extended-thinking`: `{AVAILABLE_REGIONS_COUNT}` locations
- Regional Constraints: `{NOTES_ON_REGIONAL_AVAILABILITY}`

## 3. Workload Analysis Findings

### Lens 1: Contract & Configuration
- Forbidden Fields Detected: `{LIST_OF_FIELDS_OR_NONE}`
- `thinking_config` Status: `{STATUS}`
- Proactive Audio Status: `{STATUS}`

### Lens 2: Control Flow & Event Loop
- Event Loop Receive Patterns Found: `{COUNT}`
- `handleTurn` Truncation Risk: `{PROVEN_DEFECT | SAFE | UNVERIFIED}`
- State-Destroying Paths Consulting `interaction_status`: `{SAFE_COUNT}/{TOTAL_PATHS}`
- Truncation Risks:
  - `{FILE_PATH}:{LINE_NUMBER}` - `{DESCRIPTION}`

### Lens 3: Tool Classification & Latency
| Tool Name | File & Line | Inferred Latency | Recommended Mode | Rationale |
| :--- | :--- | :--- | :--- | :--- |
| `{TOOL_NAME}` | `{LOCATION}` | `{TIER}` | `{BLOCKING | NON_BLOCKING}` | `{SIGNALS}` |

## 4. Migration Plan & Code Changes

### Change Set 1: Model Identification & Endpoints
- File: `{FILE_PATH}`
- Target Lines: `{LINES}`
- Action: `{ACTION}`

### Change Set 2: Configuration & Parameters
- File: `{FILE_PATH}`
- Target Lines: `{LINES}`
- Action: `{ACTION}`

### Change Set 3: Event Loop Hardening
- File: `{FILE_PATH}`
- Target Lines: `{LINES}`
- Action: `{ACTION}`

## 5. Rollback Plan
- Fast rollback procedure:
  1. Revert model parameter to `{CURRENT_MODEL}`.
  2. Restore original event loop code if modified.
  3. Verify reconnection via preflight script.

## 6. Verification Plan
- Unit tests with mock fixtures: `{STATUS}`
- Text-mode replay tests: `{STATUS}`
- Live audio latency check: `{OPTIONAL / STATUS}`
