# Tool Latency Classification

This document provides classification rules and signals for client tools used with the Gemini Live API.

## Latency Tiers

Classify client tools into four latency tiers:

| Tier | Duration | Typical Operations | Recommended Model Handling |
| :--- | :--- | :--- | :--- |
| **Instant** | < 50 ms | In-memory lookup, string formatting, arithmetic | `gemini-3.8-live` (`BLOCKING` or `NON_BLOCKING`) |
| **Fast** | 50–500 ms | Local cache read, local database read | `gemini-3.8-live` (`BLOCKING` or `NON_BLOCKING`) |
| **Slow** | 0.5–3.0 s | Single external HTTP request, remote database query | `gemini-3.8-live` (`NON_BLOCKING`) or Extended Thinking |
| **Very Slow** | > 3.0 s | Chained HTTP calls, retry loops, batch processing | `gemini-3.8-live-extended-thinking` (mandatory `NON_BLOCKING`) |

## Code Signals

Inspect tool implementation functions for these signals:

### Instant Signals
- No network libraries.
- No `await` statements or promises.
- Pure arithmetic, dictionary lookup, or regex operations.

### Fast Signals
- In-memory database or cache access (`redis`, `memcached`).
- Local filesystem reads (`open()`, `fs.readFile`).
- Low timeout configurations (`timeout <= 0.5`).

### Slow Signals
- Single external HTTP call (`requests.get`, `httpx.post`, `fetch`, `axios`).
- Cloud service API call (Google Cloud, AWS, Stripe).
- Relational database query over network (`psycopg2`, `prisma`, `sqlalchemy`).

### Very Slow Signals
- Sequential `await` statements in loops.
- Retry decorators (`@retry`, `tenacity`, `backoff`).
- Explicit high timeout values (`timeout >= 5.0`).
- Long-running subprocess execution (`subprocess.run`, `child_process.exec`).

## Migration Decision Rules

Use tool classification to guide target model selection:

1. **All tools Instant/Fast:**
   Recommend `gemini-3.8-live`. Low voice turn latency. Fillers are unnecessary.

2. **One or more tools Slow/Very Slow:**
   Recommend `gemini-3.8-live-extended-thinking` if published in the region.
   Extended Thinking emits conversational fillers while tools execute.
   If Extended Thinking is unavailable, recommend `gemini-3.8-live` with `behavior: "NON_BLOCKING"`.

3. **Bimodal Distribution (Many Instant + Few Very Slow):**
   Recommend `gemini-3.8-live` with hybrid tool declarations:
   - Mark Instant tools as `BLOCKING`.
   - Mark Very Slow tools as `NON_BLOCKING`.
