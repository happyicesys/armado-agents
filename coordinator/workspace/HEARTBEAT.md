# HEARTBEAT — Coordinator

## Idle Loop Interval
Every **10 minutes**.

## Why 10 Minutes
Crypto signals on 1h+ timeframes tolerate a 10-minute dispatch lag. Signals approved for execution are still valid — the Execution Engineer will act within one cycle. At 10 minutes you make ~144 cycles/day vs 288 at 5 min, cutting coordinator token cost by ~50% with no meaningful impact on execution quality.

## The Loop
```
LOOP (every 5 minutes):
  1. POST /api/agents/heartbeat
  2. GET /api/dashboard/overview          ← ONE call, everything
  3. Compare against LAST_STATE
  4. Run dispatch logic (Priority 1 → 6)
  5. POST /api/tasks for each agent that needs work  ← only if needed
  6. Update LAST_STATE
  7. Log one-line dispatch summary
  8. Sleep 5 minutes
```

## Token Expectations

| Scenario | Tokens Used |
|----------|-------------|
| All clear, nothing changed | ~80 tokens |
| 1-2 tasks dispatched | ~150-200 tokens |
| Active signal pipeline (4+ tasks) | ~300-400 tokens |
| CRITICAL halt condition | ~400-500 tokens (worth it) |

**Daily estimate:**
- 144 cycles × avg 120 tokens = ~17,280 tokens/day coordinator cost
- vs. 5-min cycle: 288 cycles × avg 120 tokens = ~34,560 tokens/day
- **~50% coordinator token reduction vs 5-min cycle**

## Rules
- ONE `GET /api/dashboard/overview` per cycle — no other read calls
- NEVER create duplicate tasks (check `GET /api/tasks?assigned_to=X&status=pending` is already handled by the overview endpoint)
- If an agent already has a pending task of the same type, do not create another one
- If you are unsure whether to create a task: don't. The agent will catch it next cycle.
