# User Context

## CEO: Brian

- Email: leehongjie91@gmail.com
- Role: CEO and final decision maker
- Risk appetite: Conservative to moderate — capital preservation first
- Preferred markets: Crypto (Binance), focus on BTC, ETH, and top altcoins
- Communication: Direct, data-driven, appreciates clear summaries

## Manager: Claude

- Role: Orchestrates all agents, reviews research, approves strategy pipelines
- Communicates via the Laravel middleware API
- Has authority to approve/reject research for backtesting
- Reports to CEO on overall firm performance

## Middleware

- Base URL: configured via MIDDLEWARE_BASE_URL environment variable
- All inter-agent communication routes through the middleware
- API key required for authentication
