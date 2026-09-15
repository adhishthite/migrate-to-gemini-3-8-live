"""Mock WebSocket event fixtures for Gemini 3.8 Live and Extended Thinking.

Use these fixtures in unit tests to verify client event loop handling,
interaction_status tracking, and conversational filler audio processing.
"""

from typing import Any

# Standard 3.8 Live Turn (Immediate response, turnComplete signals idle)
MOCK_38_LIVE_STANDARD_TURN: list[dict[str, Any]] = [
    {
        "serverContent": {
            "modelTurn": {
                "parts": [
                    {
                        "inlineData": {
                            "mimeType": "audio/pcm;rate=24000",
                            "data": "UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=",
                        }
                    }
                ]
            },
            "turnComplete": True,
        }
    }
]

# Extended Thinking Multi-Stage Turn (Fillers, Tool Call, Final Answer, IDLE)
MOCK_38_EXTENDED_THINKING_TURN: list[dict[str, Any]] = [
    # Stage 1: Conversational filler audio emitted while reasoning begins
    {
        "serverContent": {
            "interactionStatus": "IN_PROGRESS",
            "modelTurn": {
                "parts": [
                    {
                        "inlineData": {
                            "mimeType": "audio/pcm;rate=24000",
                            "data": "UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=",
                        }
                    }
                ]
            },
            "outputTranscription": {"text": "Checking flight options now..."},
            "turnComplete": True,  # Utterance finished, but session is IN_PROGRESS!
        }
    },
    # Stage 2: Asynchronous tool call emitted
    {
        "toolCall": {
            "functionCalls": [
                {
                    "id": "call_12345",
                    "name": "search_flights",
                    "args": {"destination": "SFO"},
                }
            ]
        }
    },
    # Stage 3: Final answer after tool response received
    {
        "serverContent": {
            "interactionStatus": "IDLE",  # Session is now truly complete
            "modelTurn": {
                "parts": [
                    {
                        "inlineData": {
                            "mimeType": "audio/pcm;rate=24000",
                            "data": "UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=",
                        }
                    }
                ]
            },
            "outputTranscription": {"text": "I found three flights to San Francisco."},
            "turnComplete": True,
        }
    },
]

# Error Payloads
MOCK_38_LIVE_THINKING_ERROR: dict[str, Any] = {
    "error": {
        "code": 400,
        "message": "thinking_level is not supported for model gemini-3.8-live.",
        "status": "INVALID_ARGUMENT",
    }
}

MOCK_38_EXTENDED_BLOCKING_TOOL_ERROR: dict[str, Any] = {
    "error": {
        "code": 400,
        "message": (
            "Synchronous function calling is not supported for "
            "gemini-3.8-live-extended-thinking. Set behavior: NON_BLOCKING."
        ),
        "status": "INVALID_ARGUMENT",
    }
}
