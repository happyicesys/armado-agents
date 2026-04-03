# User Context

## CEO: Brian

- Email: leehongjie91@gmail.com
- Receives: Weekly portfolio report every Monday
- Authority: Override any allocation decision, retire strategies with positive P&L

## Manager: Claude

- Reviews weekly report and recommended actions
- Approves tier promotions above Tier 2
- Monitors strategy lifecycle

## Middleware Endpoints

- Portfolio state: `GET /api/portfolio/state`
- Update allocation: `POST /api/portfolio/allocations`
- Strategy performance: `PATCH /api/portfolio/strategies/{id}`
- Weekly report: `POST /api/reports/portfolio-summary`
- Circuit breaker: `POST /api/portfolio/circuit-breaker`
