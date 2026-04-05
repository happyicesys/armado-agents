# HEARTBEAT — Market Analyst

## Mode: TASK-DRIVEN (event-driven, not polling)

You do NOT run on a fixed polling timer. The Coordinator wakes you by assigning a task.
Your only autonomous action is a lightweight keep-alive ping every 60 minutes.

## Loop
```
LOOP (every 60 minutes):
  1. POST /api/agents/heartbeat                               ← keep-alive only
  2. GET /api/tasks?assigned_to=market-analyst&status=pending
     → If tasks found: work on them (see AGENTS.md for full procedure)
     → If no tasks:    log "idle — awaiting coordinator" and sleep
```

## Typical Triggers (sent by Coordinator)
market update overdue (>20 min), regime change detected by coordinator, extreme price move alert

## Token Budget Per Task
- Target per task: < 500 tokens
- Always: ONE batch data fetch at start, ONE result submission at end
- No mid-task check-ins to the middleware

## Exception — Self-Scheduling
None. Fully coordinator-driven. The Coordinator ensures you run at minimum every 20 minutes by detecting stale market updates.

## Why Task-Driven?
The Coordinator monitors the full firm state every 5 minutes with a single API call (~80 tokens).
It is far cheaper for one agent to observe everything than for every agent to observe independently.
You run when there is real work. You cost zero tokens when there isn't.
