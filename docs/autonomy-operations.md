# Ryan Autonomy Operations

## Purpose

Ryan's autonomous loop is the production worker responsible for advancing the
business without waiting for a human to call each API endpoint.

The current mandate is:

- determine one fastest-to-revenue offer,
- build, launch, and sell only that offer,
- prefer recurring subscription checkout when available,
- use `agentryan.blog` to build in public and document progress, learnings, and
  wins,
- draft operator approval and action requests from `agentryan@agentmail.to` to
  `mike.holownych@aisyndicate.io`,
- block all second-offer work until measured MRR reaches `$20,000`.

## Runtime

Run one cycle:

```bash
ryan-autonomy --once --seed
```

Run continuously:

```bash
RYAN_AUTONOMY_ENABLED=true ryan-autonomy --seed
```

The interval is controlled by:

```bash
RYAN_AUTONOMY_CYCLE_SECONDS=900
```

The second-offer gate is controlled by:

```bash
RYAN_AUTONOMY_MRR_SECOND_OFFER_GATE=20000.00
```

## Production Deployment Shape

The API service and the autonomy worker should run as separate ECS services or
separate task definitions using the same image:

- `ryan-prod-web`: serves FastAPI traffic.
- `ryan-prod-autonomy`: runs `ryan-autonomy --seed`.

The autonomy worker must use the same production database and Secrets Manager
configuration as the web service so ledger entries, checkout sessions, payments,
blog drafts, email drafts, exceptions, and MRR calculations share one source of
truth.

The worker can run before outbound vendor-payment rails are approved. In that
state Ryan can select and launch the first revenue offer, create checkout links,
document progress, and draft approval emails. Production readiness and outbound
expense execution remain blocked until a real outbound provider, treasury
account reference, and operator-approved live validation are configured.

## Current Safety Boundary

The loop is autonomous for offer selection, single-offer focus, subscription or
checkout-link creation, ledger-backed launch planning, WordPress draft creation
for build-in-public posts, and AgentMail approval-request drafting.

Actual WordPress publication and external email sending remain blocked behind
review, sanitization, verification, approval, and an explicitly wired provider
path. This keeps public communication useful without letting Ryan leak secrets,
customer data, wallet details, private infrastructure details, or raw logs.

## Audit Trail

Each cycle writes ledger entries:

- `audit.autonomy.offer_selected`
- `audit.autonomy.offer_paused`
- `audit.payment.checkout_created`
- `audit.autonomy.launch_plan`
- `audit.autonomy.blog_draft`
- `audit.autonomy.agentmail_draft`
- `audit.autonomy.cycle`

If Ryan cannot select an offer or create checkout, it opens an exception record
for operator review.
