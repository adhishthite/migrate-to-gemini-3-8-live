# Event Loop Patterns and Analysis

This document describes event loop requirements for Gemini Live API models.

## The `handleTurn` Truncation Defect

Many client implementations use this pattern from older documentation:

```javascript
// DEFECTIVE PATTERN
if (message.serverContent && message.serverContent.turnComplete) {
  done = true;
  setUiState("listening");
}
```

### Cause of Failure

- In `gemini-3.1-flash-live-preview` and `gemini-3.8-live`, `turnComplete: true` indicates that the model is idle.
- In `gemini-3.8-live-extended-thinking`, `turnComplete: true` indicates only that the current utterance ended.
- Extended Thinking emits conversational fillers (such as "Checking your account now...").
- When a filler utterance completes, the server sends `turnComplete: true` with `interaction_status: "IN_PROGRESS"`.
- If the client exits on `turnComplete: true`, it disconnects or resets before the model emits tool calls or the final answer.
- The failure produces no error code. The conversation truncates silently.

## State-Destroying Actions

A state-destroying action terminates or resets client turn state. Common state-destroying actions include:

1. Breaking or returning from the receive loop (`break`, `return`).
2. Resolving a turn completion Promise or Future.
3. Setting user interface status to "listening" or "ready".
4. Clearing or resetting audio playback queues.
5. Closing or reconnecting the WebSocket session.

## Control Flow Verification Rule

Every code path reaching a state-destroying action must verify that `interaction_status` equals `IDLE`.

If `interaction_status` equals `IN_PROGRESS`, the client must:
- Keep the receive loop open.
- Keep the user interface in "thinking" or "working" state.
- Retain audio playback queues.
- Wait for subsequent tool calls or final responses.

## Correct Implementations

### Python Implementation

```python
async for response in session.receive():
    server_content = response.server_content
    if not server_content:
        if response.tool_call:
            asyncio.create_task(handle_tool_call(response.tool_call))
        continue

    # 1. Read interaction_status
    status = getattr(server_content, "interaction_status", None)

    # 2. Process audio parts
    if server_content.model_turn:
        for part in server_content.model_turn.parts:
            if part.inline_data:
                await audio_player.play(part.inline_data.data)

    # 3. Handle state transitions safely
    if status == "IN_PROGRESS":
        ui.set_state("thinking")
    elif status == "IDLE" or (server_content.turn_complete and status is None):
        ui.set_state("listening")
        break
```

### TypeScript Implementation

```typescript
for await (const message of session.receive()) {
  const serverContent = message.serverContent;
  if (!serverContent) {
    if (message.toolCall) {
      void handleToolCall(message.toolCall);
    }
    continue;
  }

  const status = serverContent.interactionStatus;

  // Process audio
  if (serverContent.modelTurn?.parts) {
    for (const part of serverContent.modelTurn.parts) {
      if (part.inlineData?.data) {
        audioPlayer.enqueue(part.inlineData.data);
      }
    }
  }

  // State transitions
  if (status === "IN_PROGRESS") {
    ui.setState("thinking");
  } else if (status === "IDLE" || (serverContent.turnComplete && !status)) {
    ui.setState("listening");
    break;
  }
}
```
