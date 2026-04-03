# User Context

## CEO: Brian

- Email: leehongjie91@gmail.com
- Risk appetite: Conservative to moderate

## Manager: Claude

- Approves signal designs before deployment
- Reviews signal performance weekly

## Middleware

- Base URL: configured via MIDDLEWARE_BASE_URL environment variable
- Submit signals: `POST /api/signals`
- Get market data: `GET /api/market-data/{symbol}`
- Get research findings: `GET /api/research-findings`
