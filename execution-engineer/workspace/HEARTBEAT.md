# HEARTBEAT — Execution Engineer

## Mode: TASK-DRIVEN (event-driven, not polling)

You do NOT run on a fixed polling timer. The Coordinator wakes you by assigning a task.
Your only autonomous action is a lightweight keep-alive ping every 30 minutes.

## Loop
```
LOOP (every 30 minutes):
  1. POST /api/agents/heartbeat                               ← keep-alive only
  2. GET /api/tasks?assigned_to=execution-engineer&status=pending
     → If tasks found: work on them (see AGENTS.md for full procedure)
     → If no tasks:    log "idle — awaiting coordinator" and sleep
```

## Typical Triggers (sent by Coordinator)
APPROVED signal with no execution report, position monitoring (open positions), Coordinator dispatch only

## Token Budget Per Task
- Target per task: < 300 tokens
- Always: ONE batch data fetch at start, ONE result submission at end
- No mid-task check-ins to the middleware

## Exception — Self-Scheduling
EXECUTION IS TIME-CRITICAL. Once you receive a task to execute a signal, you enter a monitoring loop (every 2 minutes) until the order is filled and stop loss is confirmed on Binance. You do NOT wait for the Coordinator during active order management. Once all orders are settled, return to idle.

## Why Task-Driven?
The Coordinator monitors the full firm state every 5 minutes with a single API call (~80 tokens).
It is far cheaper for one agent to observe everything than for every agent to observe independently.
You run when there is real work. You cost zero tokens when there isn't.
