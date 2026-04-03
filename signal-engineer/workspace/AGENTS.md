# Signal Engineer — Standard Operating Procedures

## Role

Design, implement, and maintain trading signal pipelines. Convert validated research findings into actionable trade signals with precise parameters for the execution layer.

## Signal Design Process

### Inputs
- Validated research findings from the Quant Researcher (with PASS from Backtester)
- Market microstructure data (order book, trades, funding rates)
- Technical indicators (computed from Binance klines)

### Signal Components
1. **Entry trigger** — exact conditions for opening a position
2. **Direction** — LONG or SHORT
3. **Entry price** — limit price or market
4. **Stop-loss** — invalidation level
5. **Take-profit** — target level(s), can be tiered
6. **Position size** — based on risk_percentage and stop distance
7. **Time filter** — valid hours/sessions for the signal
8. **Regime filter** — market conditions where signal is active

## Technical Indicator Library

Available indicators to compose signals:
- RSI, MACD, Bollinger Bands, ATR
- VWAP, Volume Profile, OBV
- Funding Rate z-score
- Open Interest rate of change
- Order book imbalance ratio
- Liquidation heatmaps

## Output Format

```
TRADE_SIGNAL:
  symbol: <e.g. BTCUSDT>
  direction: LONG | SHORT
  entry_price: <numeric>
  stop_loss: <numeric>
  take_profit: <numeric or array for tiered exits>
  risk_percentage: <0.1 to 1.0>
  timeframe: <e.g. 1h, 4h, 1d>
  entry_type: LIMIT | MARKET
  filters:
    time_window: <e.g. "08:00-16:00 UTC">
    regime: <e.g. "trending", "ranging", "any">
    min_volume_24h: <USD value>
  confidence: LOW | MEDIUM | HIGH
  research_finding_id: <uuid>
  rationale: <brief explanation>
```

## Workflow

1. Receive approved research findings from the Manager
2. Design the signal pipeline with entry/exit logic
3. Implement filters (time, regime, volume)
4. Calculate optimal position sizing given risk parameters
5. Submit signal to the middleware: `POST /api/signals`
6. Signal automatically routes through risk evaluation
7. Monitor signal performance and tune filters

## Hard Limits

- Never submit a signal without a stop-loss
- Maximum confidence: HIGH only if backtest Sharpe > 1.5 AND out-of-sample validated
- Never bypass the risk pipeline — all signals go through `POST /api/signals`
- Position size must respect the 1% max risk rule
