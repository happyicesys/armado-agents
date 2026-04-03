# User Context

## CEO: Brian

- Email: leehongjie91@gmail.com
- Role: CEO and the ONLY person who can override hard risk limits
- Risk appetite: Conservative to moderate — capital preservation first
- Standing orders: Never risk more than 1% per trade, halt at 10% monthly drawdown

## Manager: Claude

- Can approve trades within established limits
- Cannot override hard risk limits — must escalate to CEO
- Communicates via the Laravel middleware API

## Middleware

- Base URL: configured via MIDDLEWARE_BASE_URL environment variable
- Signal evaluation via: `POST /api/signals` (auto-triggers risk check)
- Portfolio state via: `GET /api/portfolio/exposure`
