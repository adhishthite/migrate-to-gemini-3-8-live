# Live API Model Comparison & Migration Matrix

Reference comparison between `gemini-3.1-flash-live-preview`, `gemini-3.8-live`, and `gemini-3.8-live-extended-thinking`.

---

## 1. Feature & Protocol Matrix

| Dimension | `gemini-3.1-flash-live-preview` | `gemini-3.8-live` | `gemini-3.8-live-extended-thinking` |
| :--- | :--- | :--- | :--- |
| **Status** | Legacy Preview | Stable (September 15, 2026) | Stable (September 15, 2026) |
| **Model Code** | `gemini-3.1-flash-live-preview` | `gemini-3.8-live` | `gemini-3.8-live-extended-thinking` |
| **Primary Use Case** | Voice dialogue preview | Low-latency voice dialogue | Complex reasoning, multi-step tasks |
| **Thinking Support** | Supported (`thinkingLevel`) | Supported (interleaved, fixed latency) | Supported (background reasoning) |
| **`thinking_level` Config** | `minimal`, `low`, `medium`, `high` | **Not supported** (must omit) | `low`, `medium`, `high` (**`minimal` not supported**) |
| **Turn Completion Signal** | `turnComplete: true` = session idle | `turnComplete: true` = session idle | `turnComplete: true` = utterance finished; session managed by `interaction_status` |
| **Session Lifecycle Field** | Not emitted | Not emitted | `interaction_status`: `IN_PROGRESS` or `IDLE` |
| **Conversational Fillers** | No (silent during tool execution) | No (silent during tool execution) | Yes (speaks updates while reasoning/calling tools) |
| **Tool Execution Modes** | Synchronous only (`BLOCKING`) | Synchronous (`BLOCKING`) & Asynchronous (`NON_BLOCKING`) | **Asynchronous only** (`NON_BLOCKING`) |
| **Function Scheduling** | Not supported | `SILENT`, `WHEN_IDLE`, `INTERRUPTED` | Not supported |
| **Client Content Updates** | Initial history seeding only | Full session (`user` & `model` roles) | Full session (`user` & `model` roles) |
| **Proactive Audio** | Not supported | Permanently enabled | Permanently enabled |
| **Affective Dialogue** | Deprecated / optional | **Removed** (setting causes error) | **Removed** (setting causes error) |
| **Default Turn Coverage** | Audio activity & video | `TURN_INCLUDES_AUDIO_ACTIVITY_AND_ALL_VIDEO` | `TURN_INCLUDES_AUDIO_ACTIVITY_AND_ALL_VIDEO` |

---

## 2. Hard Error Triggers

Avoid these configurations to prevent runtime errors:

1. **`thinking_config` on `gemini-3.8-live`**:
   * Error: `400 Invalid Argument: thinking_level is not supported for model gemini-3.8-live.`
   * Fix: Omit `thinking_config` and `thinking_level` from `LiveConnectConfig`.

2. **`thinking_level: "minimal"` on `gemini-3.8-live-extended-thinking`**:
   * Error: `400 Invalid Argument: thinking_level minimal is not supported for gemini-3.8-live-extended-thinking. Use low, medium, or high.`
   * Fix: Set `thinking_level` to `"low"`, `"medium"`, or `"high"`.

3. **`behavior: "BLOCKING"` on `gemini-3.8-live-extended-thinking`**:
   * Error: `400 Invalid Argument: Synchronous function calling is not supported for gemini-3.8-live-extended-thinking. Use behavior: NON_BLOCKING.`
   * Fix: Set `behavior: "NON_BLOCKING"` on all function declarations.

4. **`proactive_audio: false`**:
   * Error: `400 Invalid Argument: Proactive audio cannot be disabled on Gemini 3.8 Live models.`
   * Fix: Remove `proactive_audio` from configuration.

5. **`enable_affective_dialog`**:
   * Error: `400 Invalid Argument: Unknown field enable_affective_dialog.`
   * Fix: Delete the field from setup payloads.

---

## 3. Event Handling Patterns

### Standard Event Loop (`gemini-3.8-live`)
```python
async for response in session.receive():
    server_content = response.server_content
    if server_content:
        if server_content.model_turn:
            for part in server_content.model_turn.parts:
                if part.inline_data:
                    play_audio(part.inline_data.data)
        if server_content.turn_complete:
            # Turn complete signals idle
            set_ui_state("listening")
```

### Extended Thinking Event Loop (`gemini-3.8-live-extended-thinking`)
```python
async for response in session.receive():
    server_content = response.server_content
    if server_content:
        # 1. Inspect interaction_status FIRST
        status = getattr(server_content, "interaction_status", None)
        if status == "IDLE":
            set_ui_state("listening")
        elif status == "IN_PROGRESS":
            set_ui_state("thinking")

        # 2. Process audio parts (including conversational fillers)
        if server_content.model_turn:
            for part in server_content.model_turn.parts:
                if part.inline_data:
                    play_audio(part.inline_data.data)

        # 3. Handle turnComplete without resetting session state prematurely
        if server_content.turn_complete and status != "IN_PROGRESS":
            set_ui_state("listening")

    # 4. Handle asynchronous tool calls
    elif response.tool_call:
        asyncio.create_task(execute_and_respond_tool(response.tool_call))
```
