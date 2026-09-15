# Migration Doctrine

Follow these principles when migrating workloads to Gemini 3.8 Live models.

## 1. Collect Signals Before Code Inspection

Do not inspect or edit source files before collecting environment and workload signals.
Run the preflight check script first.
Run the tool latency classifier script second.
Recommendations must start from verified signals, not manual guesses.

## 2. Apply the Three Lenses

Examine every migration candidate through three lenses:

- **Lens 1: Contract (Connection safety)**
  Does the configuration connect without 400 errors?
  Remove removed fields (`enable_affective_dialog`).
  Verify supported `thinking_level` values.

- **Lens 2: Control Flow (Event loop safety)**
  Does the client handle `turnComplete` safely?
  Examine the receive loop.
  Verify that the code reads `interaction_status` before it resets state or closes connections.
  Prevent silent conversation truncation.

- **Lens 3: Behavior (Task execution)**
  Does the model call the correct tools with correct arguments?
  Use text-mode replays to verify tool-calling logic at low cost.
  Reserve audio verification for latency and voice quality tests.

## 3. Use Deterministic Gates

Scripts must gate investigations and recommendations.
Do not ask models to select target models from simple pattern matches.
If a deterministic gate fails, stop the workflow and alert the user.

## 4. Respect Regional Availability

Model availability depends on the cloud project and location.
If the target model is available in zero project locations, halt the migration immediately.
Do not recommend or refactor code for an unavailable model.

## 5. Verify Progressively

Test contract changes first.
Test control flow with mock fixtures second.
Test behavioral correctness with text replays third.
Do not perform live audio tests until earlier stages pass.
