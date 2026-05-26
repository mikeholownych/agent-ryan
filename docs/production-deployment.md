# Ryan Production Deployment

## Production Decisions

Ryan production deployment uses the following explicit defaults:

- Payment rail: Stripe Checkout.
- Secret backend: AWS Secrets Manager.
- Hosting mode: container runtime, with AWS ECS acceptable as the managed target.
- Database: external transactional database, not SQLite.
- Production access control: `X-Ryan-Role` plus `X-Ryan-Api-Key` RBAC.

## Required Environment

Set all values through the selected secret backend or the deployment platform's secret injection. Do not commit real values.

```bash
RYAN_ENVIRONMENT=production
RYAN_DATABASE_URL=postgresql+psycopg://...
RYAN_OPERATOR_API_KEY=...
RYAN_AGENT_API_KEY=...
RYAN_PAYMENT_RAIL=stripe
RYAN_STRIPE_API_KEY=...
RYAN_STRIPE_WEBHOOK_SECRET=...
RYAN_STRIPE_SUCCESS_URL=https://your-domain.example/success
RYAN_STRIPE_CANCEL_URL=https://your-domain.example/cancel
RYAN_SECRET_BACKEND=aws_secrets_manager
RYAN_HOSTING_ENVIRONMENT=container
```

All production policy fields must also be explicit:

- `RYAN_BUSINESS_MODEL`
- `RYAN_OFFER_CATALOG`
- `RYAN_APPROVED_DEMAND_SOURCES`
- `RYAN_VENDOR_ALLOWLIST`
- `RYAN_SPEND_THRESHOLD`
- `RYAN_CATEGORY_BUDGETS`
- `RYAN_SPEND_TIME_WINDOWS`
- `RYAN_REVENUE_FLOOR`
- `RYAN_RESERVE_MINIMUM`
- `RYAN_REVENUE_ALLOCATION`

Use nested Pydantic environment variables or platform-provided settings serialization according to the deployment system.

## Build

```bash
docker build -t ryan:production .
```

## Migrate

Run migrations before starting production traffic:

```bash
uv run alembic upgrade head
```

## Start

```bash
docker run --rm -p 8000:8000 --env-file .env.production ryan:production
```

In managed hosting, run the same container command with secrets injected by the platform.

## Readiness Check

Call readiness with operator credentials:

```bash
curl \
  -H "X-Ryan-Role: operator" \
  -H "X-Ryan-Api-Key: $RYAN_OPERATOR_API_KEY" \
  https://your-domain.example/api/production/readiness
```

Production readiness requires:

- production environment,
- non-SQLite database URL,
- Stripe payment rail with API key, webhook secret, success URL, and cancel URL,
- AWS Secrets Manager selected as secret backend,
- container or AWS ECS hosting mode,
- operator and agent API keys,
- production-ready business model.

## Stripe Notes

The Stripe provider creates Checkout Sessions with:

- `mode=payment`,
- hosted Checkout success and cancel URLs,
- one line item with price data,
- metadata containing `offer_id` and channel,
- Stripe idempotency key matching Ryan's payment-create idempotency key.

Webhook verification must use the configured Stripe webhook secret before confirmation events are trusted.

## Access Control

Production mode blocks unauthenticated requests except `/health`.

- `operator` role can access all routes.
- `agent` role can access `/api/plan`, `/api/execute`, `/api/status`, `/api/agent/console`, and `/api/payments/create`.

Rotate API keys through AWS Secrets Manager and restart or redeploy the service after rotation.
