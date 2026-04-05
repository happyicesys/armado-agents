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
        "description": "Get tasks. By default returns tasks assigned to this agent. Pass assigned_to to check another agent's queue (coordinator uses this to avoid duplicates).",
        "input_schema": {
            "type": "object",
            "properties": {
                "status":      {"type": "string", "enum": ["pending", "in_progress", "completed", "failed"], "description": "Filter by status. Omit for all."},
                "assigned_to": {"type": "string", "description": "Agent ID to check. Defaults to this agent. Coordinator uses this to check other agents before creating tasks."},
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
        "name": "get_alerts",
        "description": "Get active (unacknowledged) alerts. Use to check current system alerts and act on critical ones.",
        "input_schema": {
            "type": "object",
            "properties": {
                "severity": {"type": "string", "enum": ["INFO", "WARNING", "CRITICAL"], "description": "Filter by severity. Omit for all."},
            },
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
        "description": "Post a market status update. Must include BTC price and market regime. Called by market-analyst each cycle.",
        "input_schema": {
            "type": "object",
            "properties": {
                "btc_price":              {"type": "number",  "description": "Current BTC price in USD"},
                "btc_24h_change_pct":     {"type": "number",  "description": "BTC 24h price change percent (e.g. -2.3)"},
                "market_regime":          {"type": "string",  "description": "One of: BULL, BEAR, SIDEWAYS, VOLATILE"},
                "risk_level":             {"type": "string",  "enum": ["LOW", "MEDIUM", "HIGH", "EXTREME"], "description": "Current market risk level"},
                "funding_rate_btc":       {"type": "number",  "description": "BTC perpetual funding rate as raw Binance decimal (e.g. 0.0001 means 0.01% per 8h). Do NOT multiply by 100 — store the raw value exactly as Binance returns it."},
                "total_oi_change_1h_pct": {"type": "number",  "description": "Open interest 1h change pct (optional)"},
                "notable_events":         {"type": "array",   "description": "List of notable market events (optional)"},
            },
            "required": ["btc_price", "btc_24h_change_pct", "market_regime", "risk_level"],
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
        "description": "Submit a data quality check result. Use UPPERCASE for status and overall_status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "check_domain":       {"type": "string", "description": "Domain of the check, e.g. MARKET_DATA, PRICE_FEED, ON_CHAIN"},
                "status":             {"type": "string", "enum": ["PASS", "WARN", "FAIL"], "description": "Result of this specific check (UPPERCASE)"},
                "overall_status":     {"type": "string", "enum": ["HEALTHY", "DEGRADED", "CRITICAL"], "description": "Overall system data quality status (UPPERCASE)"},
                "symbols_checked":    {"type": "integer", "description": "Number of symbols checked"},
                "issues_found":       {"type": "integer", "description": "Number of issues found"},
                "details":            {"type": "object",  "description": "Optional structured detail data"},
                "api_latency_avg_ms": {"type": "number",  "description": "Average API latency in ms"},
                "api_latency_max_ms": {"type": "number",  "description": "Max API latency in ms"},
                "data_gap_count":     {"type": "integer", "description": "Number of data gaps detected"},
            },
            "required": ["check_domain", "status", "overall_status"],
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
    # ── Research & Backtest pipeline ─────────────────────────────────────────
    {
        "name": "get_research_findings",
        "description": "List research findings. Backtester uses this to find findings awaiting backtest.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["submitted", "approved_for_backtest", "in_backtest", "promoted", "rejected"], "description": "Filter by status. Omit for all."},
                "per_page": {"type": "integer", "description": "Results per page (default 20)"},
            },
        },
    },
    {
        "name": "post_backtest_report",
        "description": "Submit a backtest result for a research finding. Fetch research findings first with get_research_findings to get the UUID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "research_finding_id":  {"type": "string", "description": "UUID of the research finding (from get_research_findings)"},
                "strategy_name":        {"type": "string", "description": "Human-readable strategy name, e.g. BTC_1H_FLASH_FLUSH_V1"},
                "period_start":         {"type": "string", "description": "Backtest start date YYYY-MM-DD"},
                "period_end":           {"type": "string", "description": "Backtest end date YYYY-MM-DD"},
                "in_sample_sharpe":     {"type": "number", "description": "In-sample Sharpe ratio"},
                "out_of_sample_sharpe": {"type": "number", "description": "Out-of-sample Sharpe ratio"},
                "total_return_pct":     {"type": "number", "description": "Total return in percent"},
                "max_drawdown_pct":     {"type": "number", "description": "Max drawdown in percent (positive, e.g. 12.5)"},
                "win_rate":             {"type": "number", "description": "Win rate 0–100 (e.g. 55.3)"},
                "profit_factor":        {"type": "number", "description": "Gross profit / Gross loss"},
                "total_trades":         {"type": "integer", "description": "Total number of trades in backtest"},
                "verdict":              {"type": "string", "enum": ["PASS", "FAIL", "NEEDS_MORE_DATA"]},
                "notes":                {"type": "string"},
            },
            "required": ["research_finding_id", "strategy_name", "period_start", "period_end",
                         "in_sample_sharpe", "out_of_sample_sharpe", "total_return_pct",
                         "max_drawdown_pct", "win_rate", "profit_factor", "total_trades", "verdict"],
        },
    },
    # ── Model Registry ───────────────────────────────────────────────────────
    {
        "name": "get_model_registry",
        "description": "List models in the model registry. Signal Engineer uses this to find promoted models to build signals from.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["candidate", "approved", "deprecated"], "description": "Filter by status. Omit for all."},
            },
        },
    },
    {
        "name": "post_model_registry",
        "description": "Register a trained model/strategy in the registry after a backtest PASS. Algorithm Designer calls this.",
        "input_schema": {
            "type": "object",
            "properties": {
                "strategy_name":        {"type": "string", "description": "Unique strategy name, e.g. BTC_1H_MEAN_REVERSION_V1"},
                "model_type":           {"type": "string", "description": "e.g. RULE_BASED, ML_CLASSIFIER, ENSEMBLE"},
                "feature_set":          {"type": "string", "description": "Feature set description, e.g. PRICE_VOLUME_OI"},
                "feature_list":         {"type": "array",  "items": {"type": "string"}, "description": "List of feature names used"},
                "hyperparameters":      {"type": "object", "description": "Key hyperparameters as object"},
                "in_sample_sharpe":     {"type": "number"},
                "out_of_sample_sharpe": {"type": "number"},
                "notes":                {"type": "string"},
            },
            "required": ["strategy_name", "model_type", "feature_set", "feature_list", "hyperparameters", "in_sample_sharpe", "out_of_sample_sharpe"],
        },
    },
    # ── Portfolio ────────────────────────────────────────────────────────────
    {
        "name": "get_portfolio_state",
        "description": "Get current portfolio state: equity, open positions, deployed capital, circuit breaker status.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "update_signal_status",
        "description": "Risk Officer uses this to approve or reject a pending trade signal.",
        "input_schema": {
            "type": "object",
            "properties": {
                "uuid":   {"type": "string", "description": "Signal UUID"},
                "status": {"type": "string", "enum": ["APPROVED", "REJECTED_BY_RISK"], "description": "New status"},
                "reason": {"type": "string", "description": "Reason for approval or rejection"},
            },
            "required": ["uuid", "status"],
        },
    },
    # ── On-Chain & Sentiment ─────────────────────────────────────────────────
    {
        "name": "get_fear_greed",
        "description": "Fetch the Alternative.me Fear & Greed Index (0=Extreme Fear, 100=Extreme Greed). Cached 10 min. Use as baseline sentiment for on-chain analysis.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_onchain_metrics",
        "description": "Fetch stored on-chain metrics from the middleware. Returns exchange flows, whale activity, network metrics stored by the on-chain analyst.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "e.g. BTCUSDT (default)"},
                "hours":  {"type": "integer", "description": "Look-back window in hours (default 24)"},
                "type":   {"type": "string", "description": "Optional metric_type filter, e.g. EXCHANGE_FLOW, WHALE_TRANSFER"},
            },
        },
    },
    {
        "name": "post_onchain_metrics",
        "description": "Store on-chain metric readings. Accepts a batch of metrics. On-Chain Analyst calls this to persist derived metrics each cycle.",
        "input_schema": {
            "type": "object",
            "properties": {
                "metrics": {
                    "type": "array",
                    "description": "Array of metric objects",
                    "items": {
                        "type": "object",
                        "properties": {
                            "symbol":      {"type": "string", "description": "e.g. BTCUSDT"},
                            "metric_type": {"type": "string", "description": "e.g. EXCHANGE_FLOW, WHALE_TRANSFER, FUNDING_SIGNAL, SENTIMENT_PROXY"},
                            "value":       {"type": "number", "description": "Numeric metric value"},
                            "metadata":    {"type": "object", "description": "Optional extra fields"},
                            "measured_at": {"type": "string", "description": "ISO-8601 timestamp, e.g. 2025-01-01T00:00:00Z"},
                        },
                        "required": ["symbol", "metric_type", "value", "measured_at"],
                    },
                },
            },
            "required": ["metrics"],
        },
    },
    {
        "name": "get_sentiment_score",
        "description": "Fetch latest sentiment scores from the middleware. Returns the most recent overall sentiment reading.",
        "input_schema": {
            "type": "object",
            "properties": {
                "hours": {"type": "integer", "description": "History window in hours (default 24)"},
            },
        },
    },
    {
        "name": "post_sentiment_score",
        "description": "Store a sentiment score reading. On-Chain Analyst calls this each cycle to record overall market sentiment.",
        "input_schema": {
            "type": "object",
            "properties": {
                "score":              {"type": "number",  "description": "Normalized sentiment: -1.0 (extreme fear) to +1.0 (extreme greed)"},
                "velocity":           {"type": "number",  "description": "Change per hour (optional)"},
                "fear_greed_index":   {"type": "integer", "description": "Raw 0-100 fear & greed index value"},
                "dominant_narrative": {"type": "string",  "description": "Brief description of dominant market narrative"},
                "overall_bias":       {"type": "string",  "enum": ["BULLISH", "BEARISH", "NEUTRAL"]},
                "confidence":         {"type": "number",  "description": "0.0-1.0 confidence in the reading"},
                "sources":            {"type": "array",   "description": "List of data sources used"},
                "measured_at":        {"type": "string",  "description": "ISO-8601 timestamp"},
            },
            "required": ["score", "overall_bias", "confidence", "measured_at"],
        },
    },
    {
        "name": "get_market_funding_rate",
        "description": "Get BTC or ETH perpetual funding rate from Binance (cached 5 min). Returns raw decimal e.g. 0.0001 = 0.01% per 8h. High positive (>0.0005) = overleveraged longs. Negative = overleveraged shorts. When storing to post_market_update, pass this raw value directly without multiplying by 100.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "e.g. BTCUSDT or ETHUSDT"},
            },
            "required": ["symbol"],
        },
    },
]

# ─── Tool execution (shared across all providers) ────────────────────────────

def execute_tool(name: str, inp: dict) -> str:
    log.info(f"→ {name}({json.dumps(inp)[:120]})")

    if name == "post_heartbeat":
        result = mw('POST', 'agents/heartbeat')

    elif name == "get_tasks":
        params = {'assigned_to': inp.get('assigned_to', AGENT_ID)}
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

    elif name == "get_alerts":
        result = mw('GET', 'alerts', params=inp)

    elif name == "post_research_finding":
        inp.setdefault('agent_id', AGENT_ID)
        result = mw('POST', 'research-findings', json=inp)

    elif name == "post_market_update":
        inp.setdefault('agent_id', AGENT_ID)
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

    elif name == "get_research_findings":
        result = mw('GET', 'research-findings', params=inp)

    elif name == "post_backtest_report":
        inp.setdefault('agent_id', AGENT_ID)
        result = mw('POST', 'backtest-reports', json=inp)

    elif name == "get_model_registry":
        result = mw('GET', 'model-registry', params=inp)

    elif name == "post_model_registry":
        inp.setdefault('agent_id', AGENT_ID)
        result = mw('POST', 'model-registry', json=inp)

    elif name == "get_portfolio_state":
        result = mw('GET', 'portfolio/state')

    elif name == "update_signal_status":
        uuid = inp.pop('uuid')
        result = mw('PATCH', f'signals/{uuid}', json=inp)

    elif name == "get_fear_greed":
        result = mw('GET', 'market/fear-greed')

    elif name == "get_onchain_metrics":
        result = mw('GET', 'market/onchain', params=inp)

    elif name == "post_onchain_metrics":
        result = mw('POST', 'market/onchain', json=inp)

    elif name == "get_sentiment_score":
        result = mw('GET', 'market/sentiment', params=inp)

    elif name == "post_sentiment_score":
        result = mw('POST', 'market/sentiment', json=inp)

    elif name == "get_market_funding_rate":
        result = mw('GET', 'market/funding-rate', params=inp)

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
