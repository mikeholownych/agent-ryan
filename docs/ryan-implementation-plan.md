# Ryan Implementation Plan

## 1. Executive Summary

Ryan is an autonomous agent business operating system for a narrowly configured, auditable micro-business. The product must let an agent detect demand signals, select approved offers, create payment requests, receive settlement events, allocate revenue, propose expenses, and execute only policy-approved actions. The core constraint across the documents is that the agent is not the authority for money movement. All money-moving and permission-changing actions must be mediated by deterministic policy, wallet controls, ledger records, telemetry, and operator override.

The MVP must prove one bounded revenue loop end to end while preserving financial safety:

- A single configured business model.
- An approved offer catalog, initially with one active offer.
- Approved demand-signal sources.
- Checkout, invoice, or payment-request creation.
- Payment confirmation and settlement recording.
- Multi-wallet revenue allocation into at least revenue, operating, and reserve wallets.
- Expense proposal, deterministic policy evaluation, and approved expense execution.
- Append-only ledger and immutable action history.
- Daily P&L and operations reports.
- Operator exception review, wallet freeze, wallet unfreeze, and global kill switch.

The recommended build approach is a modular monolith first, with explicit internal service boundaries matching the System Design Document: Agent Brain, Policy Engine, Wallet Service, Payments Service, Ledger Service, Telemetry Service, and Human Console. This keeps MVP delivery buildable while preserving clear boundaries for later extraction. Because the repository currently contains only `/docs`, the first implementation task is scaffolding the application, persistence, tests, configuration, and local run path.

The docs leave several launch-critical items unresolved: initial niche, payment rail, autonomous spend ceiling, escalation triggers, reserve minimum, stack, hosting environment, identity model, and credential management approach. These must be resolved before production money movement. Until then, the plan requires sandbox payments, explicit default-deny policy, seeded local configuration, and fail-closed behavior.

## 2. Source Documents Reviewed

Reviewed source-of-truth files:

- `/docs/PRD.md`
- `/docs/BDD.md`
- `/docs/SDD.md`

Document reconciliation:

- `/docs/PRD.md` is the broadest source. It defines purpose, product thesis, goals, non-goals, functional requirements, non-functional requirements, behavior scenarios, architecture, data model, APIs, UX expectations, acceptance criteria, tests, phases, and open questions.
- `/docs/BDD.md` isolates the five behavioral scenarios: revenue capture, expense approval, expense rejection, kill switch, and budget exhaustion.
- `/docs/SDD.md` isolates the system design: logical components, data flow, trust boundaries, data model, policy specification, API surface, UX requirements, acceptance criteria, testing strategy, delivery plan, and open questions.
- The BDD scenarios in `/docs/BDD.md` match the scenarios embedded in `/docs/PRD.md`.
- The architecture, data model, API, UX, testing, delivery phases, and open questions in `/docs/SDD.md` match the corresponding sections embedded in `/docs/PRD.md`.
- The user clarified that multi-wallet is an MVP requirement. Therefore v1 must implement distinct revenue, operating, and reserve wallets rather than treating wallet allocation as a deferred or internal-only abstraction.
- Reconciliation rule: where the phase summary phrase "single wallet flow" conflicts with revenue allocation into revenue, operating, and reserve buckets and the user's explicit clarification, multi-wallet MVP overrides the ambiguous single-wallet wording. The implementer must not simplify v1 into one wallet plus labels.

No application source files exist yet. The implementation plan therefore names recommended modules, routes, and data artifacts to be created, while keeping product behavior limited to requirements found in the docs and the explicit multi-wallet clarification.

## 3. Product Scope

### Product Goals

Ryan must:

- Enable a bounded autonomous revenue loop.
- Enforce strict spending and revenue controls.
- Maintain complete auditability.
- Provide human override and kill-switch controls.
- Support a narrow but real self-sufficient business workflow.
- Keep human intervention optional for approved low-risk actions.
- Fail closed when policy or payment state is uncertain.

### Product Non-Goals

Ryan must not become:

- A general-purpose open-ended autonomy platform.
- A payroll, tax filing, lending, or treasury management system.
- An unrestricted vendor negotiation system.
- A system where the model directly handles payment credentials or cloud admin credentials.
- A system where human operators can silently rewrite financial history.

### MVP Scope

MVP must build:

- Configurable single business model.
- Approved offer catalog with one active offer in the initial release path.
- Approved demand signal source configuration and ingestion interface.
- Agent planning endpoint for opportunities and proposed actions.
- Agent execution endpoint that routes all external or money-related actions through policy.
- Policy engine with deterministic approve, reject, and escalate decisions.
- Multi-wallet wallet service with revenue, operating, and reserve wallets.
- Wallet freeze and unfreeze controls per wallet.
- Global kill switch that blocks external spend and send actions.
- Payment creation, confirmation, settlement recording, and refund route surface.
- Ledger append flow for all financial and policy events.
- Exception queue for rejected, escalated, uncertain, and anomalous actions.
- Daily P&L and operations report generation.
- Operator console for balances, recent actions, policy status, exception queue, daily P&L, freeze, unfreeze, and kill switch.
- Agent console for objective, approved offers, pending tasks, allowed spend, recent outcomes, and visible budget state.
- Tests for happy paths, reject paths, failure paths, idempotent retries, duplicate requests, invalid confirmations, frozen spends, and budget exhaustion.

### Deferred Scope

Defer to later phases:

- Multiple active offers beyond the single-offer MVP path.
- Multi-channel acquisition beyond approved-source ingestion.
- Adaptive pricing within bounds.
- Automated anomaly detection beyond deterministic duplicate or obvious inconsistency checks.
- Richer operator controls beyond exception review, wallet freeze, wallet unfreeze, and kill switch.
- Vendor negotiation automation.
- Payroll, tax filing, lending, treasury management, or raw financial credential access.

### Explicit MVP Constraint

Multi-wallet is not deferred. Ryan v1 must have separate first-class wallet records and balances for at least:

- `revenue`
- `operating`
- `reserve`

Revenue allocation after settlement must transfer or allocate funds across these wallets according to configured policy. Expense execution must draw from the operating wallet unless an operator-approved policy explicitly allows another source.

This is a launch-critical interpretation, not a preference. A build that records one balance and labels it with buckets does not satisfy MVP unless the wallet service exposes separate wallet records, freeze state, limits, and ledger-backed balance mutations for revenue, operating, and reserve wallets.

## 4. Architecture Overview

### Recommended Architecture

Build Ryan as a modular monolith with service boundaries that map directly to the docs. The application should expose HTTP APIs, persist state in a transactional database, run scheduled report jobs, and render an operator and agent console. Each internal service should own its own domain rules, with money movement and external execution always passing through the policy engine and ledger.

### Architecture Decision Record

Decision: build v1 as a modular monolith backed by a transactional database.

Status: accepted for MVP planning.

Rationale:

- The docs define tightly coupled financial safety behavior: policy decisions, wallet balances, payments, ledger entries, exceptions, and reports must be consistent.
- A modular monolith gives Ryan clear internal boundaries without introducing distributed transaction and deployment complexity before the first revenue loop works.
- A transactional database is required for idempotency, wallet balance updates, unique payment references, append-only ledger records, and settlement allocation.
- The internal modules should be designed for future extraction, but extraction is not an MVP task.

Consequences:

- First pass implementation creates modules inside one deployable application.
- Services communicate through internal interfaces first, not network calls.
- External interfaces are the documented HTTP APIs and console routes.
- Future extraction must preserve the same policy, wallet, ledger, and telemetry contracts.
- The implementation agent may choose the concrete stack and database during scaffolding, but must document that choice and verify transactions, migrations, unique constraints, and test support.

Recommended top-level modules:

- `agent`: planning, approved-source demand signals, opportunity selection, action proposal.
- `policy`: deterministic rule evaluation, policy decision records, escalation rules.
- `wallets`: multi-wallet balances, freezes, transfers, allocation logic, limits.
- `payments`: checkout, invoice, payment request, confirmation, settlement, refund abstraction.
- `ledger`: append-only financial and action records.
- `telemetry`: action logs, metrics, alerts, reports.
- `console`: operator and agent views.
- `config`: business model, offer catalog, wallet limits, policy thresholds, approved sources, vendor allowlists.

### Logical Components

The implementation must preserve the components from `/docs/SDD.md`:

- Agent Brain: planning, drafting, and opportunity selection.
- Policy Engine: deterministic rule evaluation.
- Wallet Service: balances, buckets, freezes, and transfers.
- Payments Service: invoices, checkout, refunds, and settlements.
- Ledger Service: append-only financial records.
- Telemetry Service: metrics, logs, alerts, and reports.
- Human Console: review, override, and configuration.

### Data Flow

Required end-to-end flow:

1. Approved demand signals enter the Agent Brain.
2. The Agent Brain proposes a plan or action.
3. Any external send, expense, payment, transfer, refund, freeze, unfreeze, permission, or execution action is submitted to the Policy Engine.
4. The Policy Engine returns an approve, reject, or escalate decision with reason strings.
5. Approved payment and wallet actions execute through Payments Service or Wallet Service.
6. Every decision, action, payment event, wallet movement, exception, and report event is appended to the Ledger and telemetry/audit logs.
7. Daily reports feed back into planning and are visible to the operator.

### Trust Boundaries

Required trust boundaries:

- The model never directly handles credentials.
- The policy engine is authoritative for approvals.
- Wallet balances are source-of-truth controlled by the wallet service.
- The ledger is append-only and not directly editable by the model.
- Human operators can override policy but cannot silently rewrite history.
- External payment provider callbacks must be verified before state changes.
- Idempotency keys must protect retries, duplicate callbacks, and repeated agent actions.
- Kill switch and wallet freeze states must be checked before external execution, not after.

### Recommended Persistence Boundary

Use a transactional database as the source of truth for:

- Configuration.
- Offers.
- Leads.
- Customers.
- Checkout sessions.
- Invoices.
- Payments.
- Expense requests.
- Policy rules.
- Policy decisions.
- Wallets.
- Wallet transfers.
- Bucket allocations.
- Ledger entries.
- Exceptions.
- Reports.
- Kill switch state.
- Idempotency records.

The docs do not specify a database. The implementation agent should choose one during scaffolding and document the choice. For MVP correctness, use a database that supports transactions and unique constraints.

## 5. Implementation Phases

The first pass should optimize for a working, testable safety core before agent autonomy. Build order is: scaffold, configure, persist, ledger, idempotency, telemetry, policy, wallets, payments, expenses, reports, operator console, then agent execution. Phase 2 features can be designed with clean boundaries, but should not be implemented until the MVP scenarios pass.

### Phase 0: Prerequisites and Scaffolding

Goal: create the application skeleton, test harness, configuration loading, persistence, and local run path.

Must include:

- Application framework and route structure.
- Database schema migration setup.
- Test runner and CI-ready commands.
- Environment configuration validation.
- Local seed data for one business model, one active offer, three MVP wallets, policy thresholds, and allowlisted vendors.
- Placeholder payment provider adapter that can run in sandbox or simulated mode until the primary payment rail is chosen.

Dependency: no domain work should proceed until the app can boot, run tests, apply migrations, and load seed configuration.

### Phase 1: Core Financial Safety Foundation

Goal: implement the safety and accounting substrate before agent autonomy.

Must include:

- Append-only ledger.
- Policy engine.
- Multi-wallet service with revenue, operating, and reserve wallets.
- Wallet freezes.
- Global kill switch.
- Idempotency controls.
- Exception records.
- Telemetry event emission for every action and policy decision.

Dependency: payment, reporting, console, expense, and agent execution features must depend on this phase because money movement must be policy-gated and auditable.

### Phase 2: Payment and Revenue Loop

Goal: complete the customer purchase scenario.

Must include:

- Offer catalog read path.
- Checkout, invoice, or payment request creation.
- Payment confirmation and settlement event handling.
- Revenue allocation to revenue, operating, and reserve wallets.
- Confirmation event to operator.
- Ledger entries for checkout creation, payment confirmation, settlement, allocation, and operator notification.

Dependency: Phase 1 must be complete.

### Phase 3: Expense Proposal and Execution

Goal: complete approved expense, rejected expense, and budget exhaustion scenarios.

Must include:

- Expense request creation with vendor, category, amount, and rationale.
- Policy evaluation against vendor allowlist, per-transaction cap, category budget, time window, revenue floor, lock/freeze, and exception escalation rules.
- Approved expense execution through the payment or wallet service.
- Rejected expense exception logging.
- Budget exhaustion alert.
- Wallet balance update and ledger append.

Dependency: multi-wallet and policy engine must be complete.

### Phase 4: Reporting and Operator Console

Goal: provide operational review and release readiness visibility before autonomous execution.

Must include:

- Daily P&L and operations report generation.
- Report retrieval endpoint.
- Operator console displaying balance breakdown, recent actions, policy status, exception queue, and daily P&L.
- Freeze, unfreeze, and kill-switch controls.
- Approval and rejection reason display.
- Manual operator review and override flow for exceptions.

Dependency: ledger, wallet, policy, exception, payment, expense, and telemetry event data must exist.

### Phase 5: Agent Brain and Controlled Execution

Goal: allow the agent to plan and execute only through constrained APIs.

Must include:

- Demand signal ingestion from approved sources.
- Plan generation endpoint.
- Execute endpoint that accepts proposed actions and routes gated actions to policy.
- Read-only planning mode when kill switch is active.
- Agent status endpoint.
- Agent console data for objective, approved offers, pending tasks, allowed spend, recent outcomes, and budget state.

Dependency: policy, wallet, ledger, exception, report, and operator console services must be complete enough that every agent action is visible and reviewable.

### Phase 6: Hardening, Validation, and Launch

Goal: validate that Ryan can safely run one real or sandbox revenue loop end to end.

Must include:

- Full test suite.
- E2E happy path and negative path validation.
- Payment webhook replay tests.
- Kill switch verification.
- Wallet freeze verification.
- Report generation verification.
- Operational runbook.
- Production readiness checklist.
- Sandbox pilot before real payment credentials.

Dependency: all MVP components must be complete.

## 6. Component Breakdown

### Agent Brain

Responsibilities:

- Maintain current objective for the configured business model.
- Read approved offer catalog.
- Read approved demand signal sources.
- Detect or ingest demand signals only from approved sources.
- Generate plans and proposed actions.
- Select offers only from the approved catalog.
- Submit execution requests to the policy-gated execution path.
- Switch to read-only planning when kill switch is active.

Must build now:

- Demand signal ingestion interface.
- Plan endpoint: `POST /api/plan`.
- Execute endpoint: `POST /api/execute`.
- Status endpoint: `GET /api/status`.
- Agent action model that distinguishes read-only planning actions from external send, payment, wallet, refund, and expense actions.

Can be deferred:

- Adaptive pricing.
- Multi-channel autonomous acquisition.
- Advanced opportunity ranking.

Implementation notes:

- The agent must never call payment providers, wallet mutation functions, credential stores, or cloud administration APIs directly.
- The agent must persist proposed actions and their outcomes for traceability.
- Any proposed external action must include actor, action type, amount if applicable, vendor if applicable, category if applicable, rationale, idempotency key, and references to related offer, lead, customer, or expense.

### Policy Engine

Responsibilities:

- Evaluate every money-moving and permission-changing action.
- Return deterministic decisions: approve, reject, or escalate.
- Attach a clear reason string to every decision.
- Enforce fail-closed behavior on missing inputs, uncertain payment state, invalid wallet state, duplicate events, or unavailable rules.
- Write policy decision records.

Must build now:

- `POST /api/policy/evaluate`.
- `GET /api/policy/rules`.
- `POST /api/policy/rules`, with operator-only access once identity is defined.
- Rule evaluator for vendor allowlist.
- Rule evaluator for per-transaction spend threshold.
- Rule evaluator for category budget.
- Rule evaluator for time window.
- Rule evaluator for revenue floor.
- Rule evaluator for lock and freeze.
- Rule evaluator for exception escalation.
- Kill-switch rule that blocks external spend and send actions and forces read-only planning.

Decision behavior:

- Approve when all required allow conditions pass.
- Reject when a hard block condition is present, such as unallowlisted vendor or frozen wallet.
- Escalate when the docs require human review, when action is irreversible, when amount exceeds threshold, or when configuration is incomplete.
- Fail closed as reject or escalate, never approve, when policy cannot evaluate fully.

### Wallet Service

Responsibilities:

- Own wallet balances and wallet locks.
- Maintain at least revenue, operating, and reserve wallets for MVP.
- Execute internal transfers.
- Apply settlement allocations.
- Enforce per-wallet freeze and unfreeze.
- Expose balances and limits.
- Prevent spends when the operating wallet is below the reserve or minimum threshold configured for spending.

Must build now:

- `GET /api/wallets`.
- `POST /api/wallets/transfer`.
- `POST /api/wallets/freeze`.
- `POST /api/wallets/unfreeze`.
- Wallet records with type, balance, locked state, and limits.
- Wallet transfer records.
- Revenue allocation operation after settlement.
- Operating wallet spend operation.
- Reserve protection check.

Required MVP wallets:

- Revenue wallet: receives gross or net settled revenue before allocation, depending on payment provider settlement semantics.
- Operating wallet: source for approved expenses.
- Reserve wallet: protected funds that must not be spent by the agent unless operator policy explicitly allows it.

Implementation notes:

- Use database transactions for all balance changes.
- Use idempotency records for transfer requests and settlement allocation.
- Append ledger entries for each wallet balance mutation.
- Reject or escalate transfer attempts involving locked wallets.
- Per-wallet freeze must not require global kill switch.

### Payments Service

Responsibilities:

- Create checkout links, invoices, or payment requests.
- Confirm payments.
- Record settlement events.
- Process refunds through policy.
- Abstract the payment rail.

Must build now:

- `POST /api/payments/create`.
- `POST /api/payments/confirm`.
- `POST /api/payments/refund`.
- `GET /api/payments/:id`.
- Payment provider adapter interface.
- Sandbox or simulated payment adapter if the primary payment rail is not resolved.
- Payment state machine.
- Confirmation and settlement processing.
- Duplicate confirmation and replay protection.

Required payment states:

- Created.
- Pending.
- Confirmed.
- Settled.
- Failed.
- Refunded.
- Rejected or invalid, for failed verification.

Implementation notes:

- Payment confirmation must not allocate revenue until the payment event is verified.
- Settlement must trigger allocation into revenue, operating, and reserve wallets.
- Refunds are money-moving actions and must be policy-gated.
- Invalid payment confirmation must be logged and must not mutate wallets.

### Ledger Service

Responsibilities:

- Provide append-only financial and action records.
- Record every financial event, policy decision, wallet mutation, operator override, exception, kill switch action, freeze, unfreeze, and report generation event.
- Support ledger queries for console and reports.

Must build now:

- `GET /api/ledger`.
- `POST /api/ledger/append`, restricted to internal service or operator-authorized use.
- Append-only ledger table.
- Ledger entry reference model.
- Integrity checks for financial event sequences.

Implementation notes:

- Ledger entries must never be updated in place for business corrections.
- Corrections must be compensating entries.
- The model must not directly edit ledger entries.
- Human overrides must append new entries rather than altering prior decisions.

### Telemetry Service

Responsibilities:

- Emit metrics, logs, alerts, and reports.
- Record operator confirmation events.
- Record exception events.
- Generate daily P&L and operations reports.
- Provide daily monitoring and alerting.

Must build now:

- Structured action logs.
- Alert events for budget exhaustion, duplicate charges or duplicate events, policy uncertainty, invalid payment confirmation, and frozen spend attempts.
- Daily report generation.
- `GET /api/reports/daily`.
- Report persistence.

Implementation notes:

- The ledger is the financial source of truth. Telemetry can summarize but cannot replace ledger records.
- Reports must include revenue, expenses, wallet balances, exceptions, policy decisions, and notable operational events.

### Human Console

Responsibilities:

- Let operators review the business and safety state.
- Provide exception review.
- Provide override controls.
- Provide freeze, unfreeze, and kill-switch controls.
- Show policy decisions and reason strings.

Must build now:

- Balance breakdown across revenue, operating, and reserve wallets.
- Recent action feed.
- Policy status and latest policy decisions.
- Exception queue.
- Daily P&L view.
- Wallet freeze and unfreeze controls.
- Global kill switch control.
- Manual review and override workflow for escalated exceptions.

Implementation notes:

- Operator actions are permission-changing or money-adjacent and must be logged.
- Human override cannot silently rewrite history.
- Until identity/auth is specified, production launch is blocked. Local MVP can use a clearly marked development operator identity.

### Agent Console

Responsibilities:

- Show the agent's current operational context.
- Make budget state visible at all times.
- Display current objective, approved offer set, pending tasks, allowed spend, and recent outcomes.

Must build now:

- Current objective panel.
- Approved offer set panel.
- Pending task list.
- Allowed spend and operating wallet state.
- Recent outcomes list.
- Kill switch or read-only state indicator.

## 7. Data Model

The data model must cover all core entities named in `/docs/SDD.md` and `/docs/PRD.md`.

### Core Entities

Agent:

- `id`
- `name`
- `status`
- `current_objective`
- `mode`, such as active or read-only planning
- `created_at`
- `updated_at`

Offer:

- `id`
- `name`
- `price`
- `currency`
- `status`
- `allowed_channels`
- `created_at`
- `updated_at`

Lead:

- `id`
- `source`
- `source_reference`
- `status`
- `detected_at`
- `metadata`

Customer:

- `id`
- `external_reference`
- `email_or_contact_reference`, if allowed by privacy and product choices
- `created_at`
- `updated_at`

Checkout Session:

- `id`
- `offer_id`
- `customer_id`
- `status`
- `payment_provider`
- `provider_reference`
- `checkout_url`
- `amount`
- `currency`
- `idempotency_key`
- `created_at`
- `updated_at`

Invoice:

- `id`
- `offer_id`
- `customer_id`
- `status`
- `payment_provider`
- `provider_reference`
- `amount`
- `currency`
- `due_at`
- `created_at`
- `updated_at`

Payment:

- `id`
- `checkout_session_id`
- `invoice_id`
- `amount`
- `currency`
- `status`
- `source`
- `provider_reference`
- `settlement_time`
- `idempotency_key`
- `created_at`
- `updated_at`

Expense Request:

- `id`
- `vendor`
- `category`
- `amount`
- `currency`
- `rationale`
- `policy_status`
- `policy_decision_id`
- `source_wallet_id`
- `execution_status`
- `idempotency_key`
- `created_by_actor`
- `created_at`
- `updated_at`

Policy Rule:

- `id`
- `type`
- `status`
- `configuration`
- `priority`
- `created_by_actor`
- `created_at`
- `updated_at`

Policy Decision:

- `id`
- `action_type`
- `decision`, approve, reject, or escalate
- `reason`
- `rule_results`
- `request_reference_type`
- `request_reference_id`
- `actor`
- `created_at`

Wallet:

- `id`
- `type`, revenue, operating, or reserve
- `balance`
- `currency`
- `locked`
- `limits`
- `created_at`
- `updated_at`

Bucket Allocation:

- `id`
- `payment_id`
- `source_wallet_id`
- `destination_wallet_id`
- `amount`
- `currency`
- `allocation_rule_reference`
- `idempotency_key`
- `created_at`

Wallet Transfer:

- `id`
- `source_wallet_id`
- `destination_wallet_id`
- `amount`
- `currency`
- `status`
- `reason`
- `policy_decision_id`
- `idempotency_key`
- `created_at`
- `updated_at`

Ledger Entry:

- `id`
- `type`
- `amount`
- `currency`
- `reference_type`
- `reference_id`
- `timestamp`
- `actor`
- `metadata`

Exception:

- `id`
- `type`
- `severity`
- `status`
- `reason`
- `reference_type`
- `reference_id`
- `policy_decision_id`
- `assigned_to`
- `created_at`
- `resolved_at`

Report:

- `id`
- `type`
- `period_start`
- `period_end`
- `status`
- `summary`
- `generated_at`

Kill Switch State:

- `id`
- `active`
- `reason`
- `activated_by_actor`
- `activated_at`
- `deactivated_by_actor`
- `deactivated_at`

Idempotency Record:

- `id`
- `idempotency_key`
- `scope`
- `request_hash`
- `response_reference_type`
- `response_reference_id`
- `status`
- `created_at`
- `expires_at`

### Data Model Constraints

- Payment provider references must be unique per provider.
- Idempotency keys must be unique within a defined scope.
- Wallet balances must not be changed outside wallet service transactions.
- Ledger entries are append-only.
- Policy decisions are immutable after creation.
- Exceptions can change status, but resolution must append ledger or audit events.
- Wallet transfers must preserve currency unless explicit currency conversion support is later specified.
- Expense requests must include vendor, category, amount, and rationale.
- Offers must include id, name, price, status, and allowed channels as required by the docs.

## 8. API Surface

The implementation must expose the API surface named in `/docs/SDD.md` and `/docs/PRD.md`. Payload details below are recommended to make the API implementable without adding unsupported product features.

### Agent API

`POST /api/plan`

- Purpose: produce or persist an agent plan based on current objective, approved offers, approved demand signals, wallet state, and policy state.
- Must not execute external actions.
- Must return plan id, proposed actions, policy-relevant metadata, and read-only state if kill switch is active.

`POST /api/execute`

- Purpose: submit a proposed agent action for controlled execution.
- Must route money-moving and external send actions through policy.
- Must reject or freeze execution when kill switch is active.
- Must write action, policy, ledger, and telemetry records.

`GET /api/status`

- Purpose: return agent mode, current objective, active offer set, wallet budget state, pending tasks, recent outcomes, kill switch state, and exception count.

`GET /api/reports/daily`

- Purpose: return latest daily P&L and operations reports.

### Policy API

`POST /api/policy/evaluate`

- Purpose: evaluate a proposed action or expense request.
- Must return decision, reason, rule results, and escalation or exception reference when applicable.

`GET /api/policy/rules`

- Purpose: list active policy rules.

`POST /api/policy/rules`

- Purpose: create or update policy rules.
- Must be operator-controlled.
- Must log changes.
- Must not allow the agent model to silently relax policy.

### Wallet API

`GET /api/wallets`

- Purpose: list revenue, operating, reserve, and future wallets with balances, locked state, and limits.

`POST /api/wallets/transfer`

- Purpose: move funds between wallets.
- Must be policy-gated.
- Must be idempotent.
- Must append ledger entries.

`POST /api/wallets/freeze`

- Purpose: freeze one wallet.
- Must log actor and reason.
- Must prevent outbound mutation from the frozen wallet.

`POST /api/wallets/unfreeze`

- Purpose: unfreeze one wallet.
- Must log actor and reason.
- Must be operator-controlled.

### Payments API

`POST /api/payments/create`

- Purpose: create checkout link, invoice, or payment request for an approved offer.
- Must validate offer status and allowed channel.
- Must be idempotent.

`POST /api/payments/confirm`

- Purpose: confirm payment events.
- Must verify provider event, reject invalid confirmation, prevent replay, update payment status, and append ledger events.

`POST /api/payments/refund`

- Purpose: request refund.
- Must be policy-gated as money movement.
- Must append ledger and telemetry entries.

`GET /api/payments/:id`

- Purpose: return payment details, status, settlement time, references, and related ledger entries.

### Ledger API

`GET /api/ledger`

- Purpose: list ledger entries with filters for date, type, actor, and reference.

`POST /api/ledger/append`

- Purpose: append ledger entries through controlled internal use.
- Must not be exposed to the model as a raw mutation capability.
- Must preserve append-only behavior.

### Console API Needs

The docs define UX surfaces but not exact console APIs. The implementation can satisfy this with either server-rendered pages or JSON endpoints. The console must be able to retrieve:

- Balance breakdown.
- Recent actions.
- Policy status.
- Exception queue.
- Daily P&L.
- Approval and rejection reason strings.
- Current objective.
- Approved offer set.
- Pending tasks.
- Allowed spend.
- Recent outcomes.
- Kill switch state.

## 9. Policy and Safety

### Safety Invariants

Ryan must enforce these invariants:

- All money-moving actions are policy-gated.
- All permission-changing actions are policy-gated or operator-controlled.
- All actions are traceable through immutable event logs.
- Idempotent retries must not duplicate payments, transfers, or ledger entries.
- The system fails closed on policy uncertainty.
- The system fails closed on payment uncertainty.
- Wallet controls and credentials stay outside model access.
- The policy engine is authoritative for approvals.
- Wallet balances are controlled only by the wallet service.
- The ledger is append-only.
- Human overrides append history rather than rewriting it.

### Policy Rule Types

Must implement:

- Allowlist vendor rules.
- Spend threshold rules.
- Category budget rules.
- Time window rules.
- Revenue floor rules.
- Lock and freeze rules.
- Exception escalation rules.

### Default Decision Rules

Must implement behavior equivalent to the examples in the docs:

- Approve if amount is less than or equal to the configured threshold and vendor is allowlisted.
- Escalate if amount exceeds threshold or action is irreversible.
- Block if operating wallet balance is below minimum reserve or spending threshold.
- Freeze or block outbound actions if duplicate charges or anomalies are detected.

### Kill Switch Behavior

When the operator activates the kill switch:

- All external spend actions stop.
- All external send actions stop.
- Pending actions are frozen.
- The agent is restricted to read-only planning.
- Payment webhooks may still be ingested if they only record incoming events and do not initiate outbound actions, but any resulting money movement must respect the kill-switch policy unless the operator defines a narrow allowed settlement-allocation exception.
- A ledger entry and telemetry event must be appended.

Open point: the docs do not specify whether inbound settlement allocation should continue while kill switch is active. The safest MVP behavior is to record inbound payment events, create an exception for allocation review, and avoid outbound movement until operator confirmation if the kill switch is active.

### Wallet Freeze Behavior

When a wallet is frozen:

- Outbound transfers and spends from that wallet must be rejected or escalated.
- Inbound recording may continue if it does not create external spend.
- The freeze and unfreeze actions must include actor, reason, timestamp, wallet id, and ledger/audit records.

### Exception Handling

Exceptions must be created for:

- Rejected unallowlisted vendor expense.
- Expense above configured threshold.
- Irreversible action requiring human review.
- Budget exhaustion.
- Invalid payment confirmation.
- Duplicate or replayed event.
- Policy evaluation failure.
- Payment provider uncertainty.
- Attempted spend while frozen.
- Attempted external action while kill switch is active.

### Credential Boundary

The implementation must:

- Keep payment provider credentials in server-side environment or secret storage.
- Never expose credentials to the model.
- Never persist raw credentials in ledger, telemetry, or reports.
- Use provider references rather than secrets in persisted payment records.

## 10. Money Flow and Wallets

### MVP Wallet Model

Ryan v1 must implement a multi-wallet model with at least:

- Revenue wallet.
- Operating wallet.
- Reserve wallet.

Each wallet must have:

- Balance.
- Currency.
- Type.
- Locked/frozen state.
- Limits.
- Ledger-backed mutation history.

### Revenue Capture Flow

Required flow:

1. Agent selects an approved offer from the catalog.
2. System creates checkout link, invoice, or payment request.
3. Customer completes payment.
4. Payment confirmation is verified.
5. Settlement event is recorded.
6. Funds are allocated according to policy across revenue, operating, and reserve wallets.
7. Ledger records payment and allocations.
8. Operator receives confirmation event.

### Allocation Flow

The docs require allocation into revenue, operating, and reserve buckets. With multi-wallet MVP, allocation should be represented as wallet movements or wallet balance postings:

- Payment settlement creates a revenue receipt record.
- Allocation policy determines amounts for revenue, operating, and reserve wallets.
- Wallet service applies allocation atomically.
- Bucket allocation records link the payment to the destination wallets.
- Ledger entries record each allocation leg.

Open point: allocation percentages or formulas are not specified. Implementation must require configured allocation policy before production launch. For local MVP, seed explicit non-production allocation values and mark them as configurable.

### Expense Flow

Required flow:

1. Agent creates an expense request with amount, category, vendor, and rationale.
2. Policy engine evaluates vendor allowlist, amount cap, category budget, time window, revenue floor, wallet freeze, operating balance, and escalation rules.
3. If approved, payment or wallet service executes the expense from the operating wallet.
4. If rejected, no payment executes and exception is logged.
5. If escalated, no payment executes until operator review.
6. Ledger and telemetry record the request, decision, execution, or exception.

### Budget Exhaustion Flow

Required behavior:

- If operating wallet balance is below minimum threshold, a new spend attempt must be blocked.
- The system must emit a budget exhaustion alert.
- The blocked action must be recorded in policy decisions, exceptions, telemetry, and ledger/audit logs as appropriate.

### Refund Flow

The docs include `POST /api/payments/refund`, so MVP must expose the route. Refunds are money-moving and must be policy-gated. Because detailed refund policy is not specified, MVP should require operator review for refunds unless an explicit rule is configured.

## 11. Logging and Observability

### Required Logs

Log every:

- Agent plan.
- Agent execution attempt.
- Policy evaluation request.
- Policy decision.
- Checkout, invoice, or payment request creation.
- Payment confirmation.
- Payment settlement.
- Payment failure.
- Refund request.
- Refund result.
- Wallet transfer.
- Wallet freeze.
- Wallet unfreeze.
- Kill switch activation.
- Kill switch deactivation.
- Expense request.
- Expense execution.
- Expense rejection.
- Exception creation.
- Exception resolution.
- Operator override.
- Report generation.

### Required Ledger Coverage

Financial ledger entries must cover:

- Payment created.
- Payment confirmed.
- Payment settled.
- Revenue allocation.
- Wallet transfer.
- Expense approved and executed.
- Refund executed.
- Compensating entries if corrections are needed.

Policy and operational audit entries must cover:

- Policy decisions.
- Rejections.
- Escalations.
- Freeze and unfreeze.
- Kill switch changes.
- Operator overrides.

### Metrics and Alerts

Must include metrics or queryable counters for:

- Payment created count.
- Payment confirmed count.
- Payment settled count.
- Failed or invalid payment events.
- Total revenue.
- Operating wallet balance.
- Reserve wallet balance.
- Expense requests by status.
- Policy approvals, rejections, and escalations.
- Exception count by status and severity.
- Duplicate request count.
- Frozen spend attempts.
- Kill switch active state.

Must alert on:

- Budget exhaustion.
- Invalid payment confirmation.
- Duplicate payment event or duplicate charge anomaly.
- Attempted spend while frozen.
- Attempted external action while kill switch is active.
- Policy engine failure.
- Payment provider uncertainty.

### Daily Reports

Daily P&L and operations report must include:

- Period start and end.
- Revenue received.
- Payments confirmed and settled.
- Expenses approved and executed.
- Wallet balances by wallet.
- Allocation summary.
- Exceptions opened and resolved.
- Policy decisions summary.
- Kill switch or freeze events.
- Operational notes generated from structured data.

Reports must generate automatically and be retrievable through `GET /api/reports/daily`.

## 12. Testing Strategy

### Test Principles

Tests must prove safety before autonomy:

- Policy tests must be deterministic.
- Wallet tests must prove transactional balance correctness.
- Payment tests must prove idempotency and invalid event handling.
- Ledger tests must prove append-only behavior.
- E2E tests must cover full happy path and negative paths.
- Kill switch and wallet freeze tests must prove external actions stop.

### Required Unit Tests

Policy unit tests:

- Approves allowlisted vendor under threshold.
- Rejects unallowlisted vendor.
- Escalates amount above threshold.
- Blocks spend below operating wallet minimum threshold.
- Blocks spend from frozen wallet.
- Blocks external send or spend when kill switch is active.
- Fails closed when required policy config is missing.

Wallet tests:

- Creates revenue, operating, and reserve wallets.
- Transfers between wallets atomically.
- Rejects transfer from frozen wallet.
- Rejects spend that would violate minimum operating threshold.
- Applies settlement allocation exactly once with idempotency key.

Payment tests:

- Creates payment request for approved offer.
- Rejects payment creation for inactive or unapproved offer.
- Confirms valid payment event.
- Rejects invalid payment confirmation.
- Handles duplicate confirmation idempotently.
- Does not allocate revenue before settlement.
- Triggers allocation after settlement.

Ledger tests:

- Appends ledger entries.
- Prevents update or deletion of existing ledger entries.
- Links ledger entries to payment, wallet, policy, and expense references.
- Records compensating entries rather than modifying history.

Telemetry and report tests:

- Emits budget exhaustion alert.
- Emits invalid payment alert.
- Emits frozen spend attempt alert.
- Generates daily P&L report.
- Includes wallet balances and policy decision summaries in report.

### Required Integration Tests

Revenue capture:

- Given a valid checkout link exists, when customer completes payment, then payment is recorded, revenue is allocated to revenue, operating, and reserve wallets, and operator receives confirmation event.

Expense approval:

- Given vendor is allowlisted and amount is within per-transaction cap, when agent submits expense request, then policy approves, payment executes, operating wallet updates, and ledger updates.

Expense rejection:

- Given vendor is not allowlisted, when agent submits expense request, then policy rejects, no payment executes, and exception event logs.

Kill switch:

- Given system is active, when operator activates kill switch, then external spend and send actions stop, pending actions freeze, and agent is restricted to read-only planning.

Budget exhaustion:

- Given operating wallet balance is below minimum threshold, when agent attempts new spend, then policy blocks action and system emits budget exhaustion alert.

Duplicate request:

- Given an idempotency key has already been processed, when the same request is retried, then the previous result is returned and no duplicate wallet, payment, or ledger mutation occurs.

### Manual Validation

Before launch, an operator must manually validate:

- Console shows all three MVP wallets.
- Console freeze prevents spend from a selected wallet.
- Console unfreeze restores eligible spend after policy evaluation.
- Kill switch blocks external spend and send.
- Exception queue shows rejected and escalated requests.
- Policy decisions show reason strings.
- Daily report matches ledger-derived totals.
- Agent console shows allowed spend and budget state.

## 13. Launch Plan

### Launch Gates

Ryan is release-ready only when:

- The agent can complete one revenue loop end to end.
- Unauthorized spend is rejected deterministically.
- All financial events appear in the ledger.
- Daily reports generate automatically.
- Operator freeze works reliably.
- Operator unfreeze works reliably.
- Global kill switch works reliably.
- Exceptions are routed and visible.
- Tests cover happy path, reject path, and failure path.
- Multi-wallet revenue, operating, and reserve balances are visible and ledger-backed.

### Rollout Sequence

1. Local simulation launch:
   - Use seeded business model, one offer, simulated payment provider, and three wallets.
   - Run all unit and integration tests.
   - Execute revenue capture, approved expense, rejected expense, kill switch, and budget exhaustion scenarios.

2. Sandbox payment launch:
   - Configure selected payment rail in sandbox mode.
   - Verify checkout creation, payment confirmation, settlement, duplicate callbacks, and invalid callbacks.
   - Confirm wallet allocation and ledger entries.

3. Operator dry run:
   - Use console to freeze and unfreeze wallets.
   - Activate and deactivate kill switch.
   - Review exceptions.
   - Generate daily report.

4. Limited production pilot:
   - Enable one business model.
   - Enable one approved offer.
   - Keep low autonomous spend threshold.
   - Require escalation for refunds and irreversible actions.
   - Monitor daily reports and alerts.

5. Phase 2 readiness review:
   - Consider multiple offers only after MVP ledger, policy, wallet, and reporting prove stable.
   - Consider anomaly detection only after enough telemetry exists.
   - Consider tighter policy tuning after real exception patterns are understood.

### Operational Runbook Requirements

Before production, write runbook entries for:

- Activating kill switch.
- Freezing one wallet.
- Unfreezing one wallet.
- Reviewing and resolving exceptions.
- Handling invalid payment confirmation.
- Handling duplicate payment callback.
- Handling budget exhaustion.
- Reconciling daily report with ledger.
- Rotating payment credentials.
- Disabling agent execution while keeping read-only planning.

## 14. Risks and Open Questions

### Risks

- Payment rail unspecified: checkout, confirmation, settlement, and refund details depend on provider semantics.
- Initial niche unspecified: demand signals, offer copy, approved channels, and business objective cannot be finalized.
- Policy thresholds unspecified: autonomous spend ceiling, category budgets, time windows, revenue floor, and reserve minimum are required for production.
- Allocation policy unspecified: revenue, operating, and reserve wallet allocation percentages or formulas are required.
- Identity and authorization unspecified: operator-only controls need auth before production.
- Hosting and secret management unspecified: credential boundary cannot be fully validated without deployment target.
- Tax, compliance, and bookkeeping boundaries are non-goals, but real money movement can still create operational obligations outside this system.
- Anomaly detection is mentioned for later phases, but MVP still needs deterministic duplicate/replay protection.
- The PRD phase summary phrase "single wallet flow" conflicts with explicit revenue/operating/reserve allocation and the user's clarification that multi-wallet is MVP. This plan resolves the conflict by treating multi-wallet as non-negotiable for v1. The ambiguous single-wallet wording must not be used to remove first-class revenue, operating, and reserve wallets from MVP.

### Production Blockers

Must resolve before production money movement:

- Select initial niche.
- Select primary payment rail.
- Define autonomous spend threshold.
- Define human-review triggers.
- Define reserve minimum.
- Define revenue allocation percentages or formulas across revenue, operating, and reserve wallets.
- Define approved demand-signal sources.
- Define active MVP offer.
- Define allowlisted vendors.
- Define category budgets and time-window rules.
- Define authentication and authorization for operator-only controls.
- Define deployment environment and secret storage.
- Define operator notification channel for confirmations and alerts.
- Decide whether inbound settlement allocation continues while kill switch is active or always creates an operator-review exception.
- Decide MVP refund policy, with the safest default being operator review for all refunds.

Can operate in sandbox before those blockers are resolved:

- Local modular monolith scaffold.
- Transactional schema and migrations.
- Simulated or sandbox payment adapter.
- Seeded non-production business model, offer, policy thresholds, and allocation policy.
- Revenue, operating, and reserve wallets.
- Ledger, idempotency, policy, wallet, telemetry, exception, report, and console flows.
- BDD scenarios using simulated demand signals and sandbox payments.

Can defer to Phase 2:

- Multiple active offers.
- Multi-channel acquisition.
- Adaptive pricing within configured bounds.
- Automated anomaly detection beyond deterministic duplicate and replay protection.
- Richer operator controls beyond exception review, wallet freeze, wallet unfreeze, and kill switch.
- Advanced opportunity ranking.

### Open Questions

- Which initial niche should the agent serve?
- Which payment rail should be primary?
- How much spend should be fully autonomous?
- What should trigger human review?
- What reserve minimum is required before the agent pauses?
- What revenue allocation policy should split funds across revenue, operating, and reserve wallets?
- What application stack should Ryan use?
- What database should be used?
- What authentication and authorization model should protect operator controls?
- What deployment environment and secret store should be used?
- What are the approved demand-signal sources for MVP?
- What exact offer should be active for the initial business model?
- What vendors should be allowlisted for MVP?
- Which categories and category budgets should be configured?
- What time windows should allow or block spend?
- Should inbound settlement allocation continue while global kill switch is active, or should it create an operator-review exception?
- Should refunds always require operator review in MVP?
- What notification channel should deliver operator confirmation events and alerts?

## 15. Definition of Done

Ryan MVP is done when:

- Application scaffolding exists and can be run locally.
- Database migrations create all MVP entities and constraints.
- Seed configuration creates one business model, one active offer, approved sources, policy rules, vendor allowlist, and revenue, operating, and reserve wallets.
- All API routes listed in the docs exist.
- Agent can produce plans without executing external actions directly.
- Agent execution routes all external and money-moving actions through policy.
- Policy engine returns approve, reject, or escalate with reason strings.
- Wallet service owns balances for revenue, operating, and reserve wallets.
- Revenue settlement allocates funds across the three MVP wallets according to configured policy.
- Operating wallet budget exhaustion blocks new spend and emits an alert.
- Expense approval path executes only after policy approval.
- Expense rejection path executes no payment and creates an exception.
- Kill switch blocks external spend and send and restricts agent to read-only planning.
- Per-wallet freeze blocks outbound wallet actions.
- Ledger records all financial events, policy decisions, wallet mutations, exceptions, operator overrides, freeze/unfreeze actions, and kill-switch actions.
- Daily P&L and operations report generates automatically and can be retrieved.
- Operator console shows balances, recent actions, policy status, exception queue, daily P&L, reason strings, freeze, unfreeze, and kill switch controls.
- Agent console shows objective, approved offer set, pending tasks, allowed spend, recent outcomes, and budget state.
- Required unit, integration, negative, idempotency, and E2E tests pass.
- Sandbox payment flow has been validated before production payment credentials are used.
- Risks and open questions are either resolved or explicitly accepted by the operator for a limited pilot.

Ryan production deployment is done only when:

- Production readiness is implemented in code and verified by automated checks.
- Real Stripe credentials, webhook secret, success URL, and cancel URL are provisioned outside the repository.
- Production operator and agent API keys are provisioned through the selected secret system.
- AWS Secrets Manager entries exist and are readable by the deployed runtime identity.
- External transactional database infrastructure is provisioned, migrated, reachable, and not SQLite.
- Hosting is provisioned as a container runtime or AWS ECS environment with required secret injection.
- Final production spend limits, category budgets, reserve minimum, and revenue allocation policy are explicitly configured.
- `/api/production/readiness` returns `ready=true` from the live production URL using operator credentials.
- Production authentication and authorization are verified end to end for operator, agent, unauthenticated, and public health-check paths.
- The selected Stripe production mode has been validated end to end before Ryan handles real customer traffic.
- Live production deployment is operational, secured, and verified end to end.

Ryan's first post-deployment operating task is done only when:

- Ryan owns the post-deployment blog workflow after launch.
- The WordPress blog at `agentryan.blog` is established, configured, and operating as a public documentation surface.
- WordPress is hardened before publication, including updates, least-privilege access, and strong authentication controls.
- A draft, review, sanitize, verify, publish workflow exists for every post.
- Reviewer approval is required before publication.
- Publication is blocked when a draft contains secrets, credentials, tokens, API keys, internal URLs, private IPs, customer data, wallet data, logs, deployment artifacts, or operational details that could expose Ryan or its users.
- The blog is explicitly excluded from Ryan's money movement, credential storage, customer-data storage, and operational-control boundaries.

## 16. Task Checklist

1. Establish project scaffold.
   - Dependencies: none.
   - Create application framework structure.
   - Create test framework structure.
   - Create database migration mechanism.
   - Create local environment configuration.
   - Create local run command.
   - Create CI-ready test command.
   - Validate that the app boots with no domain features enabled.

2. Define configuration model.
   - Dependencies: Task 1.
   - Add business model configuration.
   - Add approved offer catalog configuration.
   - Add approved demand-source configuration.
   - Add vendor allowlist configuration.
   - Add spend threshold configuration.
   - Add category budget configuration.
   - Add time-window policy configuration.
   - Add revenue floor configuration.
   - Add reserve minimum configuration.
   - Add revenue allocation policy configuration for revenue, operating, and reserve wallets.
   - Add configuration validation that fails closed when required policy values are missing.

3. Create persistence schema.
   - Dependencies: Task 1 and Task 2.
   - Add tables or collections for Agent, Offer, Lead, Customer, Checkout Session, Invoice, Payment, Expense Request, Policy Rule, Policy Decision, Wallet, Bucket Allocation, Wallet Transfer, Ledger Entry, Exception, Report, Kill Switch State, and Idempotency Record.
   - Add unique constraints for idempotency keys and payment provider references.
   - Add constraints for wallet type values: revenue, operating, reserve.
   - Add append-only protections for ledger entries.
   - Run migrations locally.

4. Seed MVP data.
   - Dependencies: Task 3.
   - Seed one configured business model.
   - Seed one active approved offer.
   - Seed approved demand source placeholders.
   - Seed vendor allowlist.
   - Seed policy rules.
   - Seed revenue, operating, and reserve wallets.
   - Seed kill switch inactive state.
   - Validate that all required MVP configuration is present.

5. Implement idempotency foundation.
   - Dependencies: Task 3.
   - Create idempotency record storage.
   - Add request hash comparison.
   - Add completed response reference storage.
   - Add duplicate request handling.
   - Add tests proving repeated requests do not duplicate payment, wallet, or ledger mutations.

6. Implement ledger service.
   - Dependencies: Task 3 and Task 5.
   - Add ledger append operation.
   - Add ledger query operation.
   - Add reference linking to payments, wallets, policy decisions, expenses, exceptions, reports, and operator actions.
   - Add compensating-entry pattern for corrections.
   - Add tests proving ledger entries cannot be updated or deleted.

7. Implement telemetry and audit event foundation.
   - Dependencies: Task 6.
   - Add structured action logging.
   - Add alert event model.
   - Add event emitters for policy, payment, wallet, expense, exception, kill switch, freeze, unfreeze, and report events.
   - Add tests for budget exhaustion, invalid payment, duplicate event, frozen spend, and kill switch alerts.

8. Implement kill switch.
   - Dependencies: Task 6 and Task 7.
   - Add global kill switch state read path.
   - Add activation operation with actor and reason.
   - Add deactivation operation with actor and reason.
   - Add policy-visible kill switch guard.
   - Add ledger and telemetry records for activation and deactivation.
   - Add tests proving external spend and send actions are blocked while active.

9. Implement policy engine.
   - Dependencies: Task 2, Task 3, Task 6, Task 7, and Task 8.
   - Add `POST /api/policy/evaluate`.
   - Add `GET /api/policy/rules`.
   - Add `POST /api/policy/rules`.
   - Implement allowlist vendor rule.
   - Implement spend threshold rule.
   - Implement category budget rule.
   - Implement time-window rule.
   - Implement revenue floor rule.
   - Implement lock and freeze rule.
   - Implement exception escalation rule.
   - Implement fail-closed behavior for missing or uncertain inputs.
   - Add policy decision persistence.
   - Add reason strings for every approval, rejection, and escalation.
   - Add policy unit tests for approve, reject, escalate, frozen wallet, budget exhaustion, kill switch, and missing config.

10. Implement wallet service with multi-wallet MVP.
   - Dependencies: Task 5, Task 6, Task 7, and Task 9.
   - Add `GET /api/wallets`.
   - Add `POST /api/wallets/transfer`.
   - Add `POST /api/wallets/freeze`.
   - Add `POST /api/wallets/unfreeze`.
   - Implement revenue wallet.
   - Implement operating wallet.
   - Implement reserve wallet.
   - Implement atomic internal transfer.
   - Implement wallet freeze and unfreeze.
   - Implement operating minimum threshold check.
   - Implement allocation operation for settled revenue.
   - Add wallet transfer ledger entries.
   - Add tests for transfer, freeze, unfreeze, budget exhaustion, and idempotent allocation.

11. Implement offer and demand-source read models.
   - Dependencies: Task 4.
   - Add approved offer listing.
   - Add active offer lookup.
   - Add allowed-channel validation.
   - Add approved demand source listing.
   - Add tests that inactive or unapproved offers cannot be used for payment creation.

12. Implement payment provider abstraction.
   - Dependencies: Task 5, Task 6, Task 7, Task 9, Task 10, and Task 11.
   - Add provider adapter interface for checkout, invoice or payment request creation, confirmation verification, settlement handling, and refund.
   - Add simulated or sandbox adapter.
   - Add payment state machine.
   - Add provider reference persistence.
   - Add duplicate provider event handling.
   - Add invalid confirmation handling.

13. Implement payments API.
   - Dependencies: Task 12.
   - Add `POST /api/payments/create`.
   - Add `POST /api/payments/confirm`.
   - Add `POST /api/payments/refund`.
   - Add `GET /api/payments/:id`.
   - Validate offer status and allowed channel.
   - Verify payment confirmation before state mutation.
   - Record settlement events.
   - Trigger multi-wallet revenue allocation after settlement.
   - Gate refunds through policy.
   - Add tests for create, confirm, settle, invalid confirm, duplicate confirm, refund escalation, and allocation.

14. Implement exception service.
   - Dependencies: Task 6, Task 7, Task 9, Task 10, and Task 13.
   - Create exceptions for policy rejection, escalation, budget exhaustion, invalid payment confirmation, duplicate event, policy uncertainty, payment uncertainty, frozen spend, and kill-switch blocked action.
   - Add exception status transitions for open, in review, resolved, and dismissed if supported by operator workflow.
   - Log resolution with actor and reason.
   - Add tests for exception creation and visibility.

15. Implement expense request flow.
   - Dependencies: Task 9, Task 10, Task 13, and Task 14.
   - Add expense request creation with vendor, category, amount, currency, and rationale.
   - Evaluate request through policy.
   - Execute approved expense from operating wallet.
   - Reject unallowlisted vendor without payment execution.
   - Escalate over-threshold or irreversible expenses without payment execution.
   - Emit budget exhaustion alert when operating wallet is below minimum threshold.
   - Add ledger entries for request, decision, execution, and exception.
   - Add BDD integration tests for approved expense, rejected expense, and budget exhaustion.

16. Implement daily reports.
   - Dependencies: Task 6, Task 7, Task 10, Task 13, Task 14, and Task 15.
   - Add report generation job.
   - Add `GET /api/reports/daily`.
   - Include revenue, expenses, wallet balances, allocation summary, exceptions, policy decisions, kill switch events, and freeze events.
   - Persist report records.
   - Add report generation tests.

17. Implement operator console.
   - Dependencies: Task 8, Task 9, Task 10, Task 14, and Task 16.
   - Display balance breakdown for revenue, operating, and reserve wallets.
   - Display recent actions.
   - Display policy status and reason strings.
   - Display exception queue.
   - Display daily P&L.
   - Add freeze control.
   - Add unfreeze control.
   - Add kill switch control.
   - Add exception review and override workflow.
   - Add UI or route tests for required console states.

18. Implement Agent Brain APIs.
   - Dependencies: Task 8, Task 9, Task 10, Task 11, Task 13, Task 15, Task 16, and Task 17.
   - Add `POST /api/plan`.
   - Add `POST /api/execute`.
   - Add `GET /api/status`.
   - Ensure `POST /api/plan` does not execute external actions.
   - Ensure `POST /api/execute` routes external and money-moving actions through policy.
   - Ensure kill switch restricts agent to read-only planning.
   - Persist proposed actions and outcomes.
   - Add tests for plan-only behavior, policy-gated execution, and read-only kill switch mode.

19. Implement agent console.
   - Dependencies: Task 11, Task 16, Task 17, and Task 18.
   - Display current objective.
   - Display approved offer set.
   - Display pending tasks.
   - Display allowed spend.
   - Display recent outcomes.
   - Display budget state at all times.
   - Display kill switch or read-only mode state.
   - Add UI or route tests for required console states.

20. Build BDD end-to-end tests.
   - Dependencies: Task 13, Task 15, Task 17, Task 18, and Task 19.
   - Test customer purchases approved offer.
   - Test agent proposes allowlisted vendor expense under threshold.
   - Test agent proposes unapproved expense.
   - Test operator activates kill switch.
   - Test operating budget is depleted.
   - Verify ledger, telemetry, wallet, exception, report, and console-visible state in each scenario.

21. Run full validation suite.
   - Dependencies: Task 20.
   - Run unit tests.
   - Run integration tests.
   - Run E2E tests.
   - Run migration checks.
   - Run linting or static checks if configured.
   - Confirm all required tests in the docs pass.

22. Create operational runbook.
   - Dependencies: Task 18 and Task 21.
   - Document kill switch activation and deactivation.
   - Document wallet freeze and unfreeze.
   - Document exception review.
   - Document budget exhaustion handling.
   - Document invalid payment confirmation handling.
   - Document duplicate payment callback handling.
   - Document daily ledger and report reconciliation.
   - Document credential rotation once payment rail and secret store are selected.

23. Conduct sandbox launch rehearsal.
   - Dependencies: Task 21 and Task 22.
   - Configure sandbox or simulated payment rail.
   - Execute full revenue capture.
   - Execute approved expense.
   - Execute rejected expense.
   - Activate kill switch and verify blocking.
   - Freeze operating wallet and verify blocking.
   - Generate daily report.
   - Review ledger and exceptions.

24. Resolve production launch blockers.
   - Dependencies: Task 23.
   - Select initial niche.
   - Select payment rail.
   - Define autonomous spend threshold.
   - Define escalation triggers.
   - Define reserve minimum.
   - Define revenue allocation percentages or formulas.
   - Define approved demand sources.
   - Define allowlisted vendors.
   - Define auth and authorization model.
   - Define hosting and secret management.
   - Define operator notification channel.

25. Execute limited production pilot.
   - Dependencies: Task 24.
   - Enable one business model.
   - Enable one approved offer.
   - Enable low autonomous spend threshold.
   - Keep refunds and irreversible actions escalated.
   - Monitor alerts and daily reports.
   - Review exceptions daily.
   - Confirm ledger completeness after each payment and expense.
