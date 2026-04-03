# User Context

## CEO: Brian

- Email: leehongjie91@gmail.com
- Wants daily market summary and immediate alerts for CRITICAL events

## Manager: Claude

- Uses market intelligence to inform strategy decisions
- Routes anomaly alerts to relevant team members

## Middleware

- Base URL: configured via MIDDLEWARE_BASE_URL environment variable
- Submit market updates: `POST /api/market-updates`
- Submit alerts: `POST /api/alerts`
- Get Binance market data: `GET /api/market-data/{symbol}`
