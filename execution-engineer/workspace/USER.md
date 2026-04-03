# User Context

## CEO: Brian

- Email: leehongjie91@gmail.com
- Binance account owner — API keys stored securely in the middleware vault

## Manager: Claude

- Monitors execution quality and slippage reports
- Can halt execution if anomalies detected

## Middleware

- Base URL: configured via MIDDLEWARE_BASE_URL environment variable
- Get approved signals: `GET /api/signals?status=APPROVED`
- Submit execution reports: `POST /api/execution-reports`
- Get API keys from vault: `GET /api/vault/binance` (requires agent auth)
