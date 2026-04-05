# HEARTBEAT — Data Quality Monitor

## Mode: TASK-DRIVEN (event-driven, not polling)

You do NOT run on a fixed polling timer. The Coordinator wakes you by assigning a task.
Your only autonomous action is a lightweight keep-alive ping every 30 minutes.

## Loop
```
LOOP (every 30 minutes):
  1. POST /api/agents/heartbeat                               ← keep-alive only
  2. GET /api/tasks?assigned_to=data-quality-monitor&status=pending
     → If tasks found: work on them (see AGENTS.md for full procedure)
     → If no tasks:    log "idle — awaiting coordinator" and sleep
```

## Typical Triggers (sent by Coordinator)
coordinator detects DEGRADED/CRITICAL status, scheduled check every 30 min (still runs itself — data quality is infrastructure)

## Token Budget Per Task
- Target per task: < 200 tokens
- Always: ONE batch data fetch at start, ONE result submission at end
- No mid-task check-ins to the middleware

## Exception — Self-Scheduling
DATA QUALITY IS INFRASTRUCTURE. You run your full 6-domain check every 30 minutes regardless of Coordinator dispatch. This is the ONE agent that maintains its own heartbeat because catching bad data early protects the entire firm. Coordinator may also dispatch you for urgent checks.

## Why Task-Driven?
The Coordinator monitors the full firm state every 5 minutes with a single API call (~80 tokens).
It is far cheaper for one agent to observe everything than for every agent to observe independently.
You run when there is real work. You cost zero tokens when there isn't.
