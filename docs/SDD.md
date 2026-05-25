# System Design Document

## 4. System Architecture

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

## 5. Data Model

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

## 6. Policy Specification

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

## 7. API Surface

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

## 8. UX Requirements

### 8.1 Operator Console
The console shall display balance breakdown, recent actions, policy status, exception queue, and daily P&L. It shall provide freeze, unfreeze, and kill-switch controls. It shall show every approval and rejection with a reason string.

### 8.2 Agent Console
The agent view shall show current objective, approved offer set, pending tasks, allowed spend, and recent outcomes. The interface shall make budget state visible at all times.

## 9. Acceptance Criteria

### 9.1 Release Ready When
- The agent can complete one revenue loop end to end.
- The system can reject unauthorized spend deterministically.
- All financial events appear in the ledger.
- Daily reports generate automatically.
- Operator freeze and kill-switch actions work reliably.
- Exceptions are routed and visible.
- Tests cover happy path, reject path, and failure path.

## 10. Testing Strategy

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

## 11. Delivery Plan
### Phase 1
Single offer, single wallet flow, manual operator override, daily report.

### Phase 2
Multiple offers, better telemetry, automated anomaly detection, tighter policy tuning.

### Phase 3
Multi-channel acquisition, adaptive pricing within bounds, richer operator controls.

## 12. Open Questions
- Which initial niche should the agent serve?
- Which payment rail should be primary?
- How much spend should be fully autonomous?
- What should trigger human review?
- What reserve minimum is required before the agent pauses?
