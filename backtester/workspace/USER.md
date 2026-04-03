# User Context

## CEO: Brian

- Email: leehongjie91@gmail.com
- Role: CEO and final decision maker
- Risk appetite: Conservative to moderate — capital preservation first

## Manager: Claude

- Orchestrates all agents, approves strategy promotions
- Communicates via the Laravel middleware API

## Middleware

- Base URL: configured via MIDDLEWARE_BASE_URL environment variable
- Historical data available via: `GET /api/market-data/{symbol}`
- Submit reports via: `POST /api/backtest-reports`
