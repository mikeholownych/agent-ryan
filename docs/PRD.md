===== PRD.md =====
# Autonomous Agent Business OS — SDD/BDD + Technical PRD

## 1. Overview

### 1.1 Purpose
This document defines the requirements, behavior, architecture, and delivery expectations for an autonomous agent system that can generate revenue, manage constrained expenses, and operate within deterministic financial policy. The system is intended to function as a self-managing micro-business while remaining auditable, bounded, and operator-controllable.

### 1.2 Product Thesis
The product is a financial control plane for an autonomous agent. The agent may propose and execute business actions, but all money-moving and permission-changing actions are mediated by policy, wallets, and observability services.

### 1.3 Goals
- Enable a bounded autonomous revenue loop.
- Enforce strict spending and revenue controls.
- Maintain complete auditability.
- Provide human override and kill-switch controls.
- Support a narrow but real self-sufficient business workflow.

### 1.4 Non-Goals
- General-purpose open-ended autonomy.
- Payroll, tax filing, lending, or treasury management.
- Unrestricted vendor negotiation.
- Direct raw access to payment credentials or cloud admin accounts.

## 2. Product Requirements

### 2.1 Functional Requirements
FR-1 The system shall support a single configured business model with an approved offer catalog.
FR-2 The agent shall detect demand signals from approved sources.
FR-3 The agent shall generate and select offers from the approved catalog.
FR-4 The system shall create checkout links, invoices, or payment requests.
FR-5 The system shall accept payments and record settlement events.
FR-6 The system shall allocate revenue into revenue, operating, and reserve buckets.
FR-7 The agent shall propose expenses with amount, category, vendor, and rationale.
FR-8 The policy engine shall approve, reject, or escalate expenses.
FR-9 The system shall generate daily P&L and operations reports.
FR-10 The system shall expose a kill switch and per-wallet freeze.
FR-11 The system shall log every action and policy decision.
FR-12 The system shall support operator review of exceptions.

### 2.2 Non-Functional Requirements
NFR-1 All money-moving actions shall be policy-gated.
NFR-2 All actions shall be traceable via immutable event logs.
NFR-3 The system shall support idempotent retries.
NFR-4 The system shall fail closed on policy or payment uncertainty.
NFR-5 The system shall support daily monitoring and alerting.
NFR-6 The system shall keep human intervention optional for approved low-risk actions.
NFR-7 The system shall maintain security boundaries around credentials and wallet controls.

Scenario: Customer purchases approved offer.
Given a valid checkout link exists
When the customer completes payment
Then the payment is recorded
And revenue is allocated according to policy
And the operator receives a confirmation event.

Scenario: Agent proposes a vendor expense under threshold.
Given the vendor is allowlisted
And the amount is within per-transaction cap
When the agent submits the expense request
Then the policy engine approves it
And the payment is executed
And the ledger is updated.

Scenario: Agent proposes an unapproved expense.
Given the vendor is not allowlisted
When the agent submits the expense request
Then the policy engine rejects it
And no payment is executed
And an exception event is logged.

Scenario: Operator pauses the system.
Given the system is active
When the operator activates the kill switch
Then all external spend and send actions stop
And pending actions are frozen
And the agent is restricted to read-only planning.

Scenario: Operating budget is depleted.
Given the operating wallet balance is below minimum threshold
When the agent attempts a new spend
Then the policy engine blocks the action
And the system emits a budget exhaustion alert.

### 4.1 Logical Components
- Agent Brain: planning, drafting, and opportunity selection.
- Policy Engine: deterministic rule evaluation.
- Wallet Service: balances, buckets, freezes, and transfers.
- Payments Service: invoices, checkout, refunds, and settlements.
- Ledger Service: append-only financial records.
- Telemetry Service: metrics, logs, alerts, and reports.
- Human Console: review, override, and configuration.

### 4.2 Data Flow
Demand signals enter the agent brain. The agent proposes actions. The policy engine validates them. Approved actions are executed via the payments or wallet services. All results are written to the ledger and telemetry. Daily reports feed back into planning.

### 4.3 Trust Boundaries
- The model never directly handles credentials.
- The policy engine is authoritative for approvals.
- Wallet balances are source-of-truth controlled by the wallet service.
- The ledger is append-only and not directly editable by the model.
- Human operators can override policy but cannot silently rewrite history.

### 5.1 Core Entities
- Agent
- Offer
- Lead
- Customer
- Checkout Session
- Invoice
- Payment
- Expense Request
- Policy Rule
- Policy Decision
- Wallet
- Bucket Allocation
- Ledger Entry
- Exception
- Report

### 5.2 Key Fields
Offer: id, name, price, status, allowed_channels.
Payment: id, amount, currency, status, source, settlement_time.
Expense Request: id, vendor, category, amount, rationale, policy_status.
Wallet: id, type, balance, locked, limits.
Ledger Entry: id, type, amount, reference_id, timestamp, actor.

### 6.1 Rule Types
- Allowlist vendor rules.
- Spend threshold rules.
- Category budget rules.
- Time window rules.
- Revenue floor rules.
- Lock and freeze rules.
- Exception escalation rules.

### 6.2 Default Policy Examples
- Approve if amount <= configured threshold and vendor allowlisted.
- Escalate if amount exceeds threshold or action is irreversible.
- Block if operating wallet balance is below minimum reserve.
- Freeze all outbound actions if duplicate charges or anomalies are detected.

### 7.1 Agent API
- POST /api/plan
- POST /api/execute
- GET /api/status
- GET /api/reports/daily

### 7.2 Policy API
- POST /api/policy/evaluate
- GET /api/policy/rules
- POST /api/policy/rules

### 7.3 Wallet API
- GET /api/wallets
- POST /api/wallets/transfer
- POST /api/wallets/freeze
- POST /api/wallets/unfreeze

### 7.4 Payments API
- POST /api/payments/create
- POST /api/payments/confirm
- POST /api/payments/refund
- GET /api/payments/:id

### 7.5 Ledger API
- GET /api/ledger
- POST /api/ledger/append

### 8.1 Operator Console
The console shall display balance breakdown, recent actions, policy status, exception queue, and daily P&L. It shall provide freeze, unfreeze, and kill-switch controls. It shall show every approval and rejection with a reason string.

### 8.2 Agent Console
The agent view shall show current objective, approved offer set, pending tasks, allowed spend, and recent outcomes. The interface shall make budget state visible at all times.

### 9.1 Release Ready When
- The agent can complete one revenue loop end to end.
- The system can reject unauthorized spend deterministically.
- All financial events appear in the ledger.
- Daily reports generate automatically.
- Operator freeze and kill-switch actions work reliably.
- Exceptions are routed and visible.
- Tests cover happy path, reject path, and failure path.

### 10.1 Required Tests
- Policy unit tests.
- Wallet transfer tests.
- Payment create/confirm tests.
- Ledger consistency tests.
- Kill switch tests.
- Duplicate request tests.
- Report generation tests.
- End-to-end workflow tests.

### 10.2 Negative Tests
- Unallowlisted vendor spend.
- Budget exhausted spend.
- Invalid payment confirmation.
- Replay of duplicate event.
- Attempted spend while frozen.

### Phase 1
Single offer, single wallet flow, manual operator override, daily report.

### Phase 2
Multiple offers, better telemetry, automated anomaly detection, tighter policy tuning.

### Phase 3
Multi-channel acquisition, adaptive pricing within bounds, richer operator controls.

- Which initial niche should the agent serve?
- Which payment rail should be primary?
- How much spend should be fully autonomous?
- What should trigger human review?
- What reserve minimum is required before the agent pauses?
