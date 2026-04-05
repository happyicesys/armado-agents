#!/usr/bin/env python3
"""
Armado Quant — Agent Runner
Each Docker container runs this script.
Reads workspace files → calls LLM with tool use → executes middleware API calls.

Provider routing (set via CLAUDE_MODEL env var):
  claude-*     → Anthropic API  (brain agents: researcher, risk, signal, execution, backtest, algo)
  gemini-*     → Google Gemini via OpenAI-compatible endpoint  (plumbing agents)
  gpt-*        → OpenAI API  (fallback plumbing option)
"""

import json
import logging
import os
import re
import time
from pathlib import Path

import requests

# ─── Config ──────────────────────────────────────────────────────────────────

WORKSPACE      = Path('/home/agent/workspace')
MIDDLEWARE_URL = os.environ['MIDDLEWARE_BASE_URL'].rstrip('/')
MIDDLEWARE_KEY = os.environ['MIDDLEWARE_API_KEY']
AGENT_ID       = os.environ['OPENCLAW_AGENT_ID']
AGENT_NAME     = os.environ.get('OPENCLAW_AGENT_NAME', AGENT_ID)
MODEL          = os.environ.get('CLAUDE_MODEL', 'claude-sonnet-4-6')

# Auto-detect provider from model name
if MODEL.startswith('gemini'):
    PROVIDER = 'gemini'
elif MODEL.startswith('gpt') or MODEL.startswith('o1') or MODEL.startswith('o3'):
    PROVIDER = 'openai'
else:
    PROVIDER = 'anthropic'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s — %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%SZ',
)
log = logging.getLogger(AGENT_ID)

# ─── LLM Client Init ─────────────────────────────────────────────────────────

if PROVIDER == 'anthropic':
    import anthropic
    CLAUDE_API_KEY = os.environ['CLAUDE_API_KEY']
    llm = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
    MAX_TOKENS = int(os.environ.get('MAX_TOKENS', '4096'))  # brain agents need room to think
    log.info(f"Provider: Anthropic | Model: {MODEL}")

elif PROVIDER == 'gemini':
    from openai import OpenAI as _OAI
    GEMINI_API_KEY = os.environ['GEMINI_API_KEY']
    llm = _OAI(
        api_key=GEMINI_API_KEY,
        base_url='https://generativelanguage.googleapis.com/v1beta/openai/',
    )
    MAX_TOKENS = int(os.environ.get('MAX_TOKENS', '1024'))  # plumbing agents are simple
    log.info(f"Provider: Gemini (OpenAI-compat) | Model: {MODEL}")

elif PROVIDER == 'openai':
    from openai import OpenAI as _OAI
    OPENAI_API_KEY = os.environ['OPENAI_API_KEY']
    llm = _OAI(api_key=OPENAI_API_KEY)
    MAX_TOKENS = int(os.environ.get('MAX_TOKENS', '1024'))
    log.info(f"Provider: OpenAI | Model: {MODEL}")

# ─── Workspace ───────────────────────────────────────────────────────────────

def read_workspace() -> tuple[str, str, str]:
    soul      = (WORKSPACE / 'SOUL.md').read_text(errors='replace')
    agents_md = (WORKSPACE / 'AGENTS.md').read_text(errors='replace')
    heartbeat = (WORKSPACE / 'HEARTBEAT.md').read_text(errors='replace')
    return soul, agents_md, heartbeat

def parse_interval(heartbeat_md: str) -> int:
    """Extract sleep seconds from HEARTBEAT.md. Defaults to 30 min."""
    m = re.search(r'every\s+(\d+)\s*min', heartbeat_md, re.IGNORECASE)
    return int(m.group(1)) * 60 if m else 1800

# ─── Middleware HTTP ──────────────────────────────────────────────────────────

def mw(method: str, path: str, **kwargs) -> dict:
    url = f"{MIDDLEWARE_URL}/api/{path.lstrip('/')}"
    headers = {
        'Authorization': f'Bearer {MIDDLEWARE_KEY}',
        'Content-Type':  'application/json',
        'Accept':        'application/json',
    }
    try:
        r = requests.request(method, url, headers=headers, timeout=30, **kwargs)
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as e:
        log.warning(f"{method} {path} → {e.response.status_code}: {e.response.text[:300]}")
        return {'error': str(e), 'status_code': e.response.status_code}
    except Exception as e:
        log.error(f"{method} {path} failed: {e}")
        return {'error': str(e)}

# ─── Tool definitions (shared across all providers) ──────────────────────────

TOOLS = [
    {
        "name": "post_heartbeat",
        "description": "Send a keep-alive heartbeat. Always call this first each cycle.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_tasks",
        "description": "Get tasks assigned to this agent.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "failed"], "description": "Filter by status. Omit for all."},
            },
        },
    },
    {
        "name": "update_task",
        "description": "Update a task status and optional result payload.",
        "input_schema": {
            "type": "object",
            "properties": {
                "uuid":   {"type": "string"},
                "status": {"type": "string", "enum": ["in_progress", "completed", "failed"]},
                "result": {"type": "object", "description": "Optional structured result data."},
            },
            "required": ["uuid", "status"],
        },
    },
    {
        "name": "create_task",
        "description": "Create and assign a task to another agent.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title":       {"type": "string"},
                "description": {"type": "string"},
                "assigned_to": {"type": "string", "description": "agent_id of the recipient"},
                "priority":    {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                "payload":     {"type": "object"},
            },
            "required": ["title", "assigned_to"],
        },
    },
    {
        "name": "get_firm_overview",
        "description": "Get complete firm state: agents, signals, portfolio, data quality.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_signals",
        "description": "Get trade signals, optionally filtered by status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "e.g. PENDING, APPROVED, REJECTED, EXECUTED"},
            },
        },
    },
    {
        "name": "post_signal",
        "description": "Submit a new trade signal for risk review.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol":      {"type": "string"},
                "direction":   {"type": "string", "enum": ["LONG", "SHORT"]},
                "entry_price": {"type": "number"},
                "stop_loss":   {"type": "number"},
                "take_profit": {"type": "number"},
                "confidence":  {"type": "number", "description": "0.0–1.0"},
                "strategy_id": {"type": "string"},
                "rationale":   {"type": "string"},
            },
            "required": ["symbol", "direction", "entry_price", "stop_loss"],
        },
    },
    {
        "name": "post_alert",
        "description": "Raise an alert visible to all agents and the dashboard.",
        "input_schema": {
            "type": "object",
            "properties": {
                "type":               {"type": "string", "description": "Short alert type, e.g. TASK_FAILURE, DATA_QUALITY, CIRCUIT_BREAKER"},
                "severity":           {"type": "string", "enum": ["INFO", "WARNING", "CRITICAL"]},
                "description":        {"type": "string", "description": "Full description of the alert condition"},
                "symbol":             {"type": "string", "description": "Optional trading symbol if relevant"},
                "recommended_action": {"type": "string", "description": "Optional suggested remediation"},
            },
            "required": ["type", "severity", "description"],
        },
    },
    {
        "name": "post_research_finding",
        "description": "Submit a quantitative research finding for the backtester to validate.",
        "input_schema": {
            "type": "object",
            "properties": {
                "signal_name":          {"type": "string", "description": "Short name for the signal, e.g. 'BTC_1H_FLASH_FLUSH_MEAN_REVERSION'"},
                "hypothesis":           {"type": "string", "description": "The trading hypothesis being tested"},
                "universe":             {"type": "string", "description": "Assets in scope, e.g. 'BTCUSDT' or 'BTC,ETH,SOL perpetuals'"},
                "timeframe":            {"type": "string", "description": "Chart timeframe, e.g. '1h', '4h', '1d'"},
                "lookback":             {"type": "string", "description": "Historical period used, e.g. '6 months', '2 years'"},
                "edge_metric":          {"type": "string", "description": "Primary metric name, e.g. 'Sharpe Ratio', 'Win Rate', 'Profit Factor'"},
                "edge_value":           {"type": "number", "description": "Numeric value of the edge metric"},
                "statistical_test":     {"type": "string", "description": "Test used for significance, e.g. 't-test', 'Mann-Whitney U'"},
                "p_value":              {"type": "number", "description": "p-value between 0 and 1"},
                "out_of_sample":        {"type": "boolean", "description": "Was out-of-sample testing performed?"},
                "out_of_sample_value":  {"type": "number", "description": "OOS metric value if available"},
                "notes":                {"type": "string", "description": "Any additional observations or caveats"},
            },
            "required": ["signal_name", "hypothesis", "universe", "timeframe", "lookback", "edge_metric", "edge_value", "statistical_test", "p_value", "out_of_sample"],
        },
    },
    {
        "name": "post_market_update",
        "description": "Post a market observation or analysis update.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol":      {"type": "string"},
                "update_type": {"type": "string"},
                "content":     {"type": "string"},
                "data":        {"type": "object"},
            },
            "required": ["symbol", "update_type", "content"],
        },
    },
    {
        "name": "post_execution_report",
        "description": "Report a completed or failed trade execution.",
        "input_schema": {
            "type": "object",
            "properties": {
                "signal_uuid":        {"type": "string"},
                "symbol":             {"type": "string"},
                "direction":          {"type": "string", "enum": ["LONG", "SHORT"]},
                "status":             {"type": "string", "enum": ["FILLED", "PARTIAL", "FAILED", "CANCELLED"]},
                "fill_price":         {"type": "number"},
                "fill_quantity":      {"type": "number"},
                "stop_loss_order_id": {"type": "string"},
                "entry_order_id":     {"type": "string"},
                "slippage_bps":       {"type": "number"},
                "fees_paid":          {"type": "number"},
                "error":              {"type": "string"},
            },
            "required": ["signal_uuid", "symbol", "direction", "status"],
        },
    },
    {
        "name": "post_data_quality",
        "description": "Submit a data quality check result.",
        "input_schema": {
            "type": "object",
            "properties": {
                "check_name": {"type": "string"},
                "status":     {"type": "string", "enum": ["pass", "warn", "fail"]},
                "details":    {"type": "object"},
            },
            "required": ["check_name", "status"],
        },
    },
    {
        "name": "get_market_price",
        "description": "Get current Binance price for a symbol.",
        "input_schema": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
    },
    {
        "name": "get_market_klines",
        "description": "Get OHLCV candlestick data from Binance.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol":   {"type": "string"},
                "interval": {"type": "string", "description": "e.g. 1m, 5m, 1h, 4h, 1d"},
                "limit":    {"type": "integer"},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_logs_summary",
        "description": "Get a count summary of system log entries by channel and level.",
        "input_schema": {
            "type": "object",
            "properties": {
                "minutes": {"type": "integer", "description": "Look-back window in minutes (default 60)"},
            },
        },
    },
]

# ─── Tool execution (shared across all providers) ────────────────────────────

def execute_tool(name: str, inp: dict) -> str:
    log.info(f"→ {name}({json.dumps(inp)[:120]})")

    if name == "post_heartbeat":
        result = mw('POST', 'agents/heartbeat')

    elif name == "get_tasks":
        params = {'assigned_to': AGENT_ID}
        if 'status' in inp:
            params['status'] = inp['status']
        result = mw('GET', 'tasks', params=params)

    elif name == "update_task":
        uuid = inp.pop('uuid')
        result = mw('PATCH', f'tasks/{uuid}', json=inp)

    elif name == "create_task":
        inp.setdefault('created_by', AGENT_ID)
        result = mw('POST', 'tasks', json=inp)

    elif name == "get_firm_overview":
        result = mw('GET', 'firm/overview')

    elif name == "get_signals":
        result = mw('GET', 'signals', params=inp)

    elif name == "post_signal":
        inp.setdefault('agent_id', AGENT_ID)
        result = mw('POST', 'signals', json=inp)

    elif name == "post_alert":
        inp.setdefault('agent_id', AGENT_ID)
        result = mw('POST', 'alerts', json=inp)

    elif name == "post_research_finding":
        inp.setdefault('agent_id', AGENT_ID)
        result = mw('POST', 'research-findings', json=inp)

    elif name == "post_market_update":
        result = mw('POST', 'market-updates', json=inp)

    elif name == "post_execution_report":
        inp.setdefault('agent_id', AGENT_ID)
        result = mw('POST', 'execution-reports', json=inp)

    elif name == "post_data_quality":
        inp.setdefault('agent_id', AGENT_ID)
        result = mw('POST', 'data-quality', json=inp)

    elif name == "get_market_price":
        result = mw('GET', 'market/price', params=inp)

    elif name == "get_market_klines":
        result = mw('GET', 'market/klines', params=inp)

    elif name == "get_logs_summary":
        result = mw('GET', 'logs/summary', params=inp)

    else:
        result = {'error': f'Unknown tool: {name}'}

    log.info(f"← {name}: {json.dumps(result)[:120]}")
    return json.dumps(result)

# ─── Agent cycle — Anthropic ─────────────────────────────────────────────────

def run_cycle_anthropic(system_prompt: str):
    """All agents: Claude Haiku/Sonnet with prompt caching on system prompt."""
    now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    user_message = (
        f"Agent: {AGENT_NAME} | ID: {AGENT_ID} | Time: {now}\n\n"
        "Begin your cycle per your AGENTS.md instructions:\n"
        "1. Call post_heartbeat first\n"
        "2. Check for pending tasks assigned to you\n"
        "3. Execute your scheduled duties or work on tasks\n"
        "4. Update task statuses when done\n"
        "Use tools to interact with the middleware. Be concise and efficient."
    )

    anthropic_tools = [
        {"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]}
        for t in TOOLS
    ]

    # Cache the system prompt — cached tokens don't count toward ITPM rate limits
    # and are billed at 10% of normal price. Cache TTL is 5 minutes.
    cached_system = [
        {
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }
    ]

    messages = [{"role": "user", "content": user_message}]
    max_rounds = 15

    for _ in range(max_rounds):
        response = llm.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=cached_system,
            tools=anthropic_tools,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == 'end_turn':
            for block in response.content:
                if hasattr(block, 'text') and block.text:
                    log.info(f"Done: {block.text[:300]}")
            break

        if response.stop_reason == 'tool_use':
            tool_results = []
            for block in response.content:
                if block.type == 'tool_use':
                    result = execute_tool(block.name, dict(block.input))
                    tool_results.append({
                        "type":        "tool_result",
                        "tool_use_id": block.id,
                        "content":     result,
                    })
            messages.append({"role": "user", "content": tool_results})
        else:
            log.warning(f"Unexpected stop_reason: {response.stop_reason}")
            break

# ─── Agent cycle — OpenAI-compatible (Gemini / GPT) ──────────────────────────

def run_cycle_openai_compat(system_prompt: str):
    """Plumbing agents: Gemini Flash / GPT-4o-mini — fast, cheap, reliable routing."""
    now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())

    openai_tools = [
        {
            "type": "function",
            "function": {
                "name":        t["name"],
                "description": t["description"],
                "parameters":  t["input_schema"],
            },
        }
        for t in TOOLS
    ]

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"Agent: {AGENT_NAME} | ID: {AGENT_ID} | Time: {now}\n\n"
                "Begin your cycle per your AGENTS.md instructions:\n"
                "1. Call post_heartbeat first\n"
                "2. Check for pending tasks assigned to you\n"
                "3. Execute your scheduled duties or work on tasks\n"
                "4. Update task statuses when done\n"
                "Use tools to interact with the middleware. Be concise and efficient."
            ),
        },
    ]
    max_rounds = 15

    for _ in range(max_rounds):
        response = llm.chat.completions.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            tools=openai_tools,
            tool_choice="auto",
            messages=messages,
        )

        choice = response.choices[0]
        messages.append({"role": "assistant", "content": choice.message.content, "tool_calls": choice.message.tool_calls})

        if choice.finish_reason == 'stop':
            if choice.message.content:
                log.info(f"Done: {choice.message.content[:300]}")
            break

        if choice.finish_reason == 'tool_calls' and choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                result = execute_tool(tc.function.name, args)
                messages.append({
                    "role":         "tool",
                    "tool_call_id": tc.id,
                    "content":      result,
                })
        else:
            log.warning(f"Unexpected finish_reason: {choice.finish_reason}")
            break

# ─── Unified cycle dispatcher ─────────────────────────────────────────────────

def run_cycle(system_prompt: str):
    if PROVIDER == 'anthropic':
        run_cycle_anthropic(system_prompt)
    else:
        run_cycle_openai_compat(system_prompt)

# ─── Main loop ───────────────────────────────────────────────────────────────

def main():
    log.info(f"Starting — {AGENT_NAME} ({AGENT_ID}) | Provider: {PROVIDER} | Model: {MODEL}")

    startup_delay = int(os.environ.get('STARTUP_DELAY', 0))
    if startup_delay:
        log.info(f"Startup delay: {startup_delay}s")
        time.sleep(startup_delay)

    soul, agents_md, heartbeat_md = read_workspace()
    interval      = parse_interval(heartbeat_md)
    system_prompt = f"{soul}\n\n---\n\n{agents_md}"

    log.info(f"Interval: {interval}s ({interval // 60} min)")

    # Initial heartbeat before first cycle
    mw('POST', 'agents/heartbeat')

    while True:
        try:
            log.info("─── Cycle start ───")
            run_cycle(system_prompt)
            log.info("─── Cycle end ───")
        except Exception as e:
            # Rate limits
            if 'rate' in str(e).lower() or '429' in str(e):
                log.warning(f"Rate limited — sleeping 60s: {e}")
                time.sleep(60)
                continue
            log.error(f"Cycle error: {e}", exc_info=True)

        log.info(f"Sleeping {interval}s")
        time.sleep(interval)


if __name__ == '__main__':
    main()
