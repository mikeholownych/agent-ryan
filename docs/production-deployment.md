# Ryan Production Deployment

## Production Decisions

Ryan production deployment uses the following explicit defaults:

- AWS account: `352818908635`.
- AWS region: `ca-central-1`.
- Payment rail: Stripe Checkout.
- Outbound payment rail: a configured production bank, treasury, or bill-pay
  provider. Simulated outbound execution is not production-ready.
- Treasury account: a real business banking or treasury account reference
  configured through the secret backend.
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
RYAN_OUTBOUND_PAYMENT_RAIL=bank
RYAN_OUTBOUND_PAYMENT_PROVIDER=...
RYAN_TREASURY_ACCOUNT_REFERENCE=...
RYAN_OUTBOUND_LIVE_VALIDATION_APPROVED=true
RYAN_SECRET_BACKEND=aws_secrets_manager
RYAN_HOSTING_ENVIRONMENT=container
```

Set `RYAN_OUTBOUND_LIVE_VALIDATION_APPROVED=true` only after the operator has
approved the selected outbound provider and completed live validation. Until
then, production readiness must fail closed.

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

## Seed Production Data

After migrations and before routing traffic, run the explicit MVP seed path with
the same production settings used by the web service. The app does not seed
offers, policy rules, wallets, or the inactive kill-switch state automatically
on startup.

The seed step must use production Secrets Manager injection and must complete
with exit code `0` before the ECS service is started.

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
- outbound payment rail set to `bank`, `treasury`, or `bill_pay`,
- outbound payment provider configured,
- treasury account reference configured,
- operator-approved outbound live validation,
- AWS Secrets Manager selected as secret backend,
- container or AWS ECS hosting mode,
- operator and agent API keys,
- production-ready business model.

## Live Production Gate

Ryan must not be declared operational in production only because the codebase
passes readiness checks in a local or sandbox environment. Production completion
requires operator-side provisioning and live validation of every external
dependency:

- real Stripe credentials and webhook endpoint configured for the production
  account,
- real outbound payment provider configured for approved vendor payments,
- real business banking or treasury account reference configured for custody
  and outbound movement,
- outbound vendor payment validation completed and approved by the operator,
- production operator and agent API keys stored outside the repository,
- AWS Secrets Manager entries created and readable by the runtime identity,
- external transactional database provisioned, migrated, and reachable,
- container hosting or AWS ECS environment provisioned with the required
  environment and secret injection,
- production spend limits, category budgets, reserve minimum, and revenue
  allocation policy explicitly configured,
- `/api/production/readiness` returns `ready=true` from the deployed production
  URL using operator credentials,
- authenticated operator and agent access paths are verified against the
  deployed service,
- unauthenticated production requests are rejected except `/health`,
- a live payment flow is validated through the selected Stripe mode before Ryan
  handles real customer traffic.

If any external dependency is missing, invalid, or unreachable, Ryan remains
production-ready in code only and must not be treated as live production.

## Current AWS Production Runtime

The live AWS deployment uses:

- ECS service: `ryan-prod-web`.
- ECS task definition: `ryan-prod-web:1`.
- Image: `352818908635.dkr.ecr.ca-central-1.amazonaws.com/ryan-prod:b43046d`.
- Public API URL: `https://api.agentryan.blog`.
- Health endpoint: `https://api.agentryan.blog/health`.
- Readiness endpoint: `https://api.agentryan.blog/api/production/readiness`.
- Stripe webhook URL:
  `https://api.agentryan.blog/api/payments/stripe/webhook`.
- Stripe success URL for the seed deployment:
  `https://api.agentryan.blog/health?checkout=success`.
- Stripe cancel URL for the seed deployment:
  `https://api.agentryan.blog/health?checkout=cancel`.

Private ECS tasks require outbound egress for ECR, Secrets Manager, CloudWatch
Logs, and Stripe. In the current AWS footprint, private subnet egress is routed
through NAT gateway `nat-0f4348356905bd5fd`.

The current seed policy is the operator-approved `$100` launch policy:

- one active offer,
- one approved demand source,
- vendor allowlist limited to Stripe, required infrastructure, and domain
  vendors,
- autonomous spend threshold `$15`,
- category spend cap `$25` per category per day,
- operator business-hours spend window,
- reserve minimum `$40`,
- revenue floor `$20`,
- allocation policy `40%` operating, `40%` revenue, `20%` reserve.

The live Stripe Checkout Session creation path has been validated without
completing a paid Checkout. A paid live Checkout completion and resulting Stripe
webhook settlement remain operator-gated because they create live financial
activity.

The current AWS runtime predates the production outbound rail readiness gate.
Until a real outbound provider, treasury account reference, and operator-
approved outbound live validation are provisioned and injected into the running
service, Ryan must not be treated as fully production-ready for closed-loop
business operation.

## First Post-Deployment Task

After the live production gate is satisfied, Ryan's first operating task is to
establish, configure, and run the WordPress blog at `agentryan.blog` as a
public documentation surface for process, implementation details, and lessons
learned. Ryan owns the post-deployment blog workflow after launch.

The blog must not store or publish secrets, credentials, tokens, API keys,
internal URLs, private IPs, customer data, wallet data, raw logs, deployment
artifacts, or operational details that could expose Ryan or its users.

Every post must follow the runbook workflow:

1. Draft.
2. Review.
3. Sanitize.
4. Verify.
5. Publish.

Publication must be blocked if sensitive data or unsafe operational detail
remains.

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
