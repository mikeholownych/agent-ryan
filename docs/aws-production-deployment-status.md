# Ryan AWS Production Deployment Status

## Deployment Account

- AWS account: `352818908635`
- AWS profile used for deployment: `SyndicateAdmin-352818908635`
- AWS region: `ca-central-1`
- Deployment date: `2026-05-26`

## Resources Created

### Network

- VPC: `ryan-prod-vpc`, `vpc-0ad27d7930b394697`
- Public subnets:
  - `ryan-prod-public-a`, `subnet-0c48c947e6a4fb77f`, `ca-central-1a`, `10.42.0.0/24`
  - `ryan-prod-public-b`, `subnet-0e18273a5638628dc`, `ca-central-1b`, `10.42.1.0/24`
- Private subnets:
  - `ryan-prod-private-a`, `subnet-069fd16a742352b7e`, `ca-central-1a`, `10.42.10.0/24`
  - `ryan-prod-private-b`, `subnet-00d6a51a6c874c825`, `ca-central-1b`, `10.42.11.0/24`
- Internet gateway: `ryan-prod-igw`, `igw-041ec844983b20602`
- Public route table: `ryan-prod-public-rt`, `rtb-0b0f60ff84dd26e2f`

### Security Groups

- ALB security group: `ryan-prod-alb-sg`, `sg-08585703d14db10a8`
  - inbound HTTP `80` from `0.0.0.0/0`
  - inbound HTTPS `443` from `0.0.0.0/0`
- ECS task security group: `ryan-prod-ecs-sg`, `sg-09b1eea45716fa5be`
- RDS security group: `ryan-prod-rds-sg`, `sg-0a0db80c24d2db515`

### Container Registry

- ECR repository: `352818908635.dkr.ecr.ca-central-1.amazonaws.com/ryan-prod`
- Image pushed: `352818908635.dkr.ecr.ca-central-1.amazonaws.com/ryan-prod:530f3ff`

### Database

- RDS instance: `ryan-prod-db`
- Engine: PostgreSQL
- Endpoint: `ryan-prod-db.czy2sqwk2d5k.ca-central-1.rds.amazonaws.com`
- Publicly accessible: `false`
- Storage encrypted: `true`
- Multi-AZ: `true`
- Deletion protection: `true`
- Database name: `ryan`

### Secrets Manager

Secrets were created without committing or printing secret values:

- `ryan/prod/operator-api-key`
- `ryan/prod/agent-api-key`
- `ryan/prod/db-master-password`
- `ryan/prod/database-url`

The following required production secrets are not yet provisioned:

- `ryan/prod/stripe-api-key`
- `ryan/prod/stripe-webhook-secret`

### IAM

- ECS execution role: `arn:aws:iam::352818908635:role/ryan-prod-ecs-execution-role`
- ECS task role: `arn:aws:iam::352818908635:role/ryan-prod-ecs-task-role`

The execution role can read Ryan production secrets under `ryan/prod/*`.

### ECS

- ECS cluster: `arn:aws:ecs:ca-central-1:352818908635:cluster/ryan-prod`
- Migration task definition: `arn:aws:ecs:ca-central-1:352818908635:task-definition/ryan-prod-migrate:1`

No long-running Ryan production service has been started yet because required
production Stripe credentials, final policy configuration, and production URL
configuration are not available.

### Load Balancer

- ALB: `arn:aws:elasticloadbalancing:ca-central-1:352818908635:loadbalancer/app/ryan-prod-alb/0d5037d16d5837b2`
- ALB DNS: `ryan-prod-alb-702663567.ca-central-1.elb.amazonaws.com`
- Target group: `arn:aws:elasticloadbalancing:ca-central-1:352818908635:targetgroup/ryan-prod-tg/35a5f0238bd34ef9`
- Target port: `8000`
- Health check path: `/health`

### DNS

- Route 53 hosted zone: `agentryan.blog`, `/hostedzone/Z07616433UAN1MRG6QU3O`
- Assigned name servers:
  - `ns-76.awsdns-09.com`
  - `ns-645.awsdns-16.net`
  - `ns-1267.awsdns-30.org`
  - `ns-1943.awsdns-50.co.uk`

The domain is registered at Spaceship. Enter the assigned name servers at
Spaceship to delegate `agentryan.blog` to Route 53.

- API hostname: `api.agentryan.blog`
- API DNS record: Route 53 alias `A` record to `ryan-prod-alb-702663567.ca-central-1.elb.amazonaws.com`
- ACM certificate: `arn:aws:acm:ca-central-1:352818908635:certificate/f36c7668-df33-4044-b05d-d534e55d4a96`
- Certificate status: `ISSUED`
- ALB HTTPS listener: `443`
- ALB HTTP listener: `80`, redirects to HTTPS

### Logs

- CloudWatch log group: `/ecs/ryan-prod`
- Retention: `30` days

## Validation Completed

- AWS identity verified for account `352818908635`.
- Local production config, readiness, and auth tests passed:
  - `uv run pytest tests/test_config.py tests/test_production_readiness.py tests/test_auth_production.py -q`
- Container image built successfully.
- Container image pushed to ECR.
- RDS instance reached `available`.
- Database URL was stored in Secrets Manager.
- Alembic migration ran from ECS against the private PostgreSQL database.
- Migration task exited with code `0`.
- Migration logs show PostgreSQL backend and upgrade to `5d79256e586a`.
- Public DNS delegation for `agentryan.blog` resolves to the Route 53 name servers.
- `api.agentryan.blog` resolves to the Ryan ALB.
- HTTP requests to `api.agentryan.blog` redirect to HTTPS.
- HTTPS reaches the Ryan ALB.

Current HTTPS response from `api.agentryan.blog/health` is `503` because no
long-running ECS service has been started and the target group has no registered
targets.

## Production Blockers

Ryan is not live production-ready yet. The following gates remain blocked:

- Real Stripe production API key is not provisioned for Ryan.
- Real Stripe production webhook secret is not provisioned for Ryan.
- Stripe webhook endpoint is not configured for the deployed Ryan URL.
- Stripe success and cancel URLs are not finalized for a Ryan production domain.
- Long-running ECS service has not been started, so the ALB target group has no
  registered targets.
- Final operator-approved production policy values are not provisioned:
  - business model,
  - offer catalog,
  - approved demand sources,
  - vendor allowlist,
  - spend threshold,
  - category budgets,
  - spend time windows,
  - revenue floor,
  - reserve minimum,
  - revenue allocation.
- Long-running ECS service has not been started.
- Live `/health` and `/api/production/readiness` checks have not been validated
  from the deployed URL.
- Production RBAC has not been validated against the deployed URL.
- Live Stripe payment flow has not been validated.

## Next Deployment Step

After the missing production secrets, production URL, and final policy values
are provisioned, register the long-running Ryan ECS task definition with:

- `RYAN_ENVIRONMENT=production`
- `RYAN_PAYMENT_RAIL=stripe`
- `RYAN_SECRET_BACKEND=aws_secrets_manager`
- `RYAN_HOSTING_ENVIRONMENT=aws_ecs`
- `RYAN_DATABASE_URL` sourced from `ryan/prod/database-url`
- `RYAN_OPERATOR_API_KEY` sourced from `ryan/prod/operator-api-key`
- `RYAN_AGENT_API_KEY` sourced from `ryan/prod/agent-api-key`
- Stripe values sourced from Ryan-specific Secrets Manager entries
- final production policy values supplied through approved configuration

Then create or update the ECS service, validate `/health`, validate production
RBAC, call `/api/production/readiness` with operator credentials, and validate a
safe Stripe flow before allowing customer traffic.
