# User Context

## CEO: Brian

- Risk appetite: Conservative to moderate
- Preference: Explainable models over black boxes

## Manager: Claude

- Assigns tasks with COMPLETE context in the payload — no need to ask for parameters
- Reviews model registry entries before promoting to signal engineering
- Communicates via the middleware task system

## Key Middleware Endpoints

- Batch features: `GET /api/features/batch`
- Register model: `POST /api/model-registry`
- Complete task: `PATCH /api/tasks/{uuid}`
- Read research finding: `GET /api/research-findings/{uuid}`

## Operational Mode

Tasks arrive with all context. Run the full pipeline. Report once. Do not check in mid-task.
