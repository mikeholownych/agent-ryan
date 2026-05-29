# Ryan AWS Production Deployment Status

## Deployment Account

- AWS account: `352818908635`
- AWS profile used for deployment: `SyndicateAdmin-352818908635`
- AWS region: `ca-central-1`
- Deployment date: `2026-05-26`
- Live service date: `2026-05-27`

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
- NAT gateway: `ryan-prod-nat-a`, `nat-0f4348356905bd5fd`
- Private route table: `rtb-0d9c6380945566a9f`
  - default route `0.0.0.0/0` targets `nat-0f4348356905bd5fd`
  - required so private ECS tasks can pull ECR images, read Secrets Manager,
    write CloudWatch logs, and call Stripe while remaining off public subnets

### Security Groups

- ALB security group: `ryan-prod-alb-sg`, `sg-08585703d14db10a8`
  - inbound HTTP `80` from `0.0.0.0/0`
  - inbound HTTPS `443` from `0.0.0.0/0`
- ECS task security group: `ryan-prod-ecs-sg`, `sg-09b1eea45716fa5be`
- RDS security group: `ryan-prod-rds-sg`, `sg-0a0db80c24d2db515`

### Container Registry

- ECR repository: `352818908635.dkr.ecr.ca-central-1.amazonaws.com/ryan-prod`
- Image pushed: `352818908635.dkr.ecr.ca-central-1.amazonaws.com/ryan-prod:530f3ff`
- Webhook-capable image pushed: `352818908635.dkr.ecr.ca-central-1.amazonaws.com/ryan-prod:b43046d`

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
- `ryan/prod/stripe-api-key`
- `ryan/prod/stripe-webhook-secret`
- `ryan/prod/stripe-success-url`
- `ryan/prod/stripe-cancel-url`
- `ryan/prod/business-model`
- `ryan/prod/offer-catalog`
- `ryan/prod/approved-demand-sources`
- `ryan/prod/vendor-allowlist`
- `ryan/prod/spend-threshold`
- `ryan/prod/category-budgets`
- `ryan/prod/spend-time-windows`
- `ryan/prod/revenue-floor`
- `ryan/prod/reserve-minimum`
- `ryan/prod/revenue-allocation`

The following production readiness secrets are now required by the code but
have not yet been provisioned in the documented AWS runtime:

- `ryan/prod/outbound-payment-rail`
- `ryan/prod/outbound-payment-provider`
- `ryan/prod/treasury-account-reference`
- `ryan/prod/outbound-live-validation-approved`

Even after those secrets are provisioned, readiness must remain blocked until
the selected outbound provider has an implemented production adapter in the
deployed Ryan code. A provider name alone is not a safe outbound payment rail.

### IAM

- ECS execution role: `arn:aws:iam::352818908635:role/ryan-prod-ecs-execution-role`
- ECS task role: `arn:aws:iam::352818908635:role/ryan-prod-ecs-task-role`

The execution role can read Ryan production secrets under `ryan/prod/*`.

### ECS

- ECS cluster: `arn:aws:ecs:ca-central-1:352818908635:cluster/ryan-prod`
- Migration task definition: `arn:aws:ecs:ca-central-1:352818908635:task-definition/ryan-prod-migrate:1`
- Web task definition: `arn:aws:ecs:ca-central-1:352818908635:task-definition/ryan-prod-web:1`
- ECS service: `arn:aws:ecs:ca-central-1:352818908635:service/ryan-prod/ryan-prod-web`
- Desired tasks: `1`
- Running tasks: `1`
- Service state: `ACTIVE`
- Web image: `352818908635.dkr.ecr.ca-central-1.amazonaws.com/ryan-prod:b43046d`
- Production seed task completed successfully with exit code `0`.

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
- Blog hostname: `agentryan.blog`
- Blog DNS record: Route 53 `A` record to Lightsail static IP `16.52.15.161`
- Blog alias hostname: `www.agentryan.blog`
- Blog alias DNS record: Route 53 `A` record to Lightsail static IP
  `16.52.15.161`
- ACM certificate: `arn:aws:acm:ca-central-1:352818908635:certificate/f36c7668-df33-4044-b05d-d534e55d4a96`
- Certificate status: `ISSUED`
- ALB HTTPS listener: `443`
- ALB HTTP listener: `80`, redirects to HTTPS

### Logs

- CloudWatch log group: `/ecs/ryan-prod`
- Retention: `30` days

### WordPress Blog

The operator approved setting up the blog before the full closed-loop
production gate is complete. Outbound payments remain operator-handled until a
viable provider is selected and validated.

- Lightsail instance: `ryan-blog-wordpress`
- Region: `ca-central-1`
- Blueprint: `wordpress_ls_1_0`
- Bundle: `nano_3_0`
- Static IP: `ryan-blog-ip`, `16.52.15.161`
- Active theme: `Ryan Operating Log` (`ryan-operating-log`)
- Public URL: `https://agentryan.blog/`
- Alias URL: `https://www.agentryan.blog/`, redirects to the apex site
- WordPress admin secret: `ryan/blog/wordpress-admin`
- WordPress operator review account: `mike`
  (`mike.holownych@aisyndicate.io`), role `editor`
- HTTPS: Let's Encrypt certificate for `agentryan.blog` and
  `www.agentryan.blog`, expiring `2026-08-27`
- SSH: port `22` restricted to Lightsail-managed connect aliases after setup
- Editorial state: initial public posts published; future posts remain gated by
  review, sanitization, verification, and operator approval
- Offer-development record: `docs/offer-development.md`

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
- `agentryan.blog` and `www.agentryan.blog` Route 53 records point to the
  Lightsail blog static IP.
- HTTP requests to `api.agentryan.blog` redirect to HTTPS.
- HTTPS reaches the Ryan ALB.
- Ryan code now includes a Stripe-signed webhook endpoint at
  `/api/payments/stripe/webhook`.
- Stripe live API credential from the authenticated `agentryan` Stripe CLI
  profile was stored in `ryan/prod/stripe-api-key` without printing or
  committing the value.
- Webhook-capable image `b43046d` was built and pushed to ECR.
- Live Stripe webhook endpoint was created:
  - endpoint id: `we_1TbVwPEATTvuyEDgZjOnJ6kg`
  - URL: `https://api.agentryan.blog/api/payments/stripe/webhook`
  - enabled event: `checkout.session.completed`
  - livemode: `true`
- Stripe webhook signing secret was stored in
  `ryan/prod/stripe-webhook-secret` without printing or committing the value.
- Final operator-approved production policy values were provisioned in Secrets
  Manager and injected into `ryan-prod-web:1`:
  - one active `$100` offer,
  - one approved demand source,
  - vendor allowlist for Stripe, AWS, and Spaceship,
  - autonomous spend threshold `$15`,
  - category cap `$25` per category per day,
  - operator business hours Monday-Friday,
  - reserve minimum `$40`,
  - revenue floor `$20`,
  - wallet allocation `40%` operating, `40%` revenue, `20%` reserve.
- Stripe seed success URL is
  `https://api.agentryan.blog/health?checkout=success`.
- Stripe seed cancel URL is
  `https://api.agentryan.blog/health?checkout=cancel`.
- Live ECS target group reached `healthy`.
- `https://api.agentryan.blog/health` returned `200`.
- Unauthenticated `/api/production/readiness` returned `401`.
- Wrong-key `/api/production/readiness` returned `401`.
- Operator-authenticated `/api/production/readiness` returned `200` with
  `ready=true` and no blockers before the outbound rail and treasury readiness
  gates were added.
- Agent-authenticated `/api/status` returned `200`.
- Agent access to `/api/operator/console` returned `403`.
- Operator access to `/api/operator/console` returned `200`.
- A live Stripe Checkout Session creation against `seed-100` returned `201`.
- Replaying the same payment-create idempotency key returned the same checkout
  session and provider reference.
- Stripe webhook endpoint remains enabled for `checkout.session.completed`.
- Production safety checks passed:
  - kill switch activation caused policy evaluation to reject spend,
  - kill switch was deactivated after validation,
  - operating wallet freeze caused policy evaluation to reject spend,
  - operating wallet was unfrozen after validation,
  - missing policy input rejected fail-closed.
- CloudWatch logs were scanned for obvious secret markers; no secret material
  was detected.
- The WordPress blog was created on Lightsail and configured as a public
  documentation surface.
- WordPress admin credentials were rotated and stored in Secrets Manager under
  `ryan/blog/wordpress-admin`.
- WordPress site URL was set to `https://agentryan.blog/`.
- Let's Encrypt HTTPS was installed for `agentryan.blog` and
  `www.agentryan.blog`.
- `https://agentryan.blog/` returned `200` when resolved to the Lightsail
  static IP.
- `https://www.agentryan.blog/` redirected to `https://agentryan.blog/`.
- HTTP requests to the blog redirect to HTTPS.
- WordPress indexing was disabled pending editorial review.
- Unused preinstalled plugins and inactive themes were removed.
- The custom `Ryan Operating Log` theme was deployed and activated.
- Playwright desktop and mobile verification confirmed the custom stylesheet,
  Ryan mark, operating-posture rail, responsive layout, and ledger-paper post
  band are rendered on the public site.
- Published posts were verified through the public WordPress API for the blog
  setup, initial offer development, market research note, and offer hypothesis.
- A one-time password setup link for the `mike` editor account was sent through
  AgentMail to `mike.holownych@aisyndicate.io`.
- Blog SSH access was restored to Lightsail-managed connect aliases after
  setup.

## Remaining Operator-Gated Validation

The live service is operational and protected, but it is not complete as a
closed-loop production business OS until these operator-gated validations are
finished:

- provision a real outbound payment rail for approved vendor payments,
- provision a real business banking or treasury account reference for custody
  and outbound movement,
- complete operator-approved outbound live validation,
- complete a real paid Checkout and resulting live Stripe webhook settlement.

Until that approval is supplied and the payment is completed, customer-facing
payment capture should remain operator-gated. The Stripe production credential,
Checkout Session creation path, idempotent replay behavior, and webhook endpoint
configuration have been validated without printing or committing secrets.
