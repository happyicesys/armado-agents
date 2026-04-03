FROM python:3.11-slim

WORKDIR /home/agent

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the agent runner
COPY runner.py .

# Workspace files are mounted per-agent via docker-compose volumes
# /home/agent/workspace/ ← SOUL.md, AGENTS.md, HEARTBEAT.md, USER.md

CMD ["python", "-u", "runner.py"]
