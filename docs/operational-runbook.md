# Ryan Operational Runbook

## Scope

This runbook covers the sandbox MVP implementation of Ryan. Ryan remains a modular monolith with policy-gated money movement, append-only ledger entries, idempotent money-flow operations, first-class revenue, operating, and reserve wallets, wallet freeze controls, and a global kill switch.

Production launch is still blocked until the unresolved launch decisions in `docs/ryan-implementation-plan.md` are closed, including the initial niche, production payment rail, credential storage, production identity model, and final autonomous spend limits.

## Kill Switch

Use the operator console API to stop external and money-moving agent execution:

- Activate: `POST /api/operator/kill-switch/activate`
- Deactivate: `POST /api/operator/kill-switch/deactivate`
- Required payload: `actor`, `reason`

Expected behavior:

- `POST /api/plan`, `GET /api/status`, and console reads remain available.
- `POST /api/execute` routes through policy and records blocked execution as a `kill_switch_blocked` exception.
- Kill switch changes emit ledger/audit events.

## Wallet Freeze And Unfreeze

Use wallet controls for per-wallet containment:

- Freeze: `POST /api/wallets/freeze`
- Unfreeze: `POST /api/wallets/unfreeze`
- Required payload: `wallet_id`, `actor`, `reason`

Expected behavior:

- A frozen wallet blocks wallet transfers and policy-approved spend from that wallet.
- Freeze and unfreeze actions emit wallet audit events.
- Freezing one wallet does not require activating the global kill switch.

## Exception Review

Use the operator exception review endpoint:

- Update status: `POST /api/operator/exceptions/{exception_id}/status`
- Supported statuses: `open`, `in_review`, `resolved`, `dismissed`
- Required payload: `status`, `actor`, `reason`

Expected behavior:

- Status transitions emit exception audit events.
- `resolved` and `dismissed` set `resolved_at`.
- Open exceptions are visible in `GET /api/operator/console`.

## Budget Exhaustion

Budget exhaustion can be triggered by policy evaluation or operating-wallet minimum checks.

Operator steps:

1. Review the `budget_exhaustion` exception in the operator console.
2. Inspect operating wallet balance and limits through `GET /api/wallets`.
3. Replenish or transfer funds only through policy-approved wallet transfer flow.
4. Resolve the exception after wallet state and policy thresholds are reviewed.

Expected behavior:

- The spend does not execute.
- The operating wallet balance is not mutated.
- The system emits an alert ledger entry and exception record.

## Invalid Payment Confirmation

Invalid confirmations include failed simulated verification, missing checkout session, amount mismatch, or currency mismatch.

Expected behavior:

- No `Payment` record is created.
- No wallet allocation occurs.
- An `invalid_payment_confirmation` alert ledger entry is emitted.

Operator steps:

1. Review the alert and provider event metadata.
2. Compare checkout amount, currency, provider reference, and event id.
3. Resolve the exception only after confirming no wallet mutation occurred.

## Duplicate Payment Callback

Payment confirmation uses idempotency and provider event references.

Expected behavior:

- Retrying the same confirmation idempotency key returns the original payment.
- Duplicate provider events do not create duplicate payment records.
- Settlement allocation replay does not duplicate bucket allocations or wallet mutations.

Operator steps:

1. Verify the provider event id maps to a single payment.
2. Verify bucket allocation count and wallet balances did not change on replay.
3. Review ledger entries for a single confirmation and settlement allocation sequence.

## Daily Ledger And Report Reconciliation

Generate a daily report:

- `GET /api/reports/daily?date=YYYY-MM-DD&actor=operator`

Report summary includes:

- settled customer revenue,
- executed expenses,
- wallet balances and locks,
- allocation summary,
- exception counts,
- policy decision counts,
- notable kill switch and wallet freeze events.

Reconciliation steps:

1. Compare `revenue_total` with settled customer payments.
2. Compare `expense_total` with executed expense requests.
3. Compare wallet balances with settlement credits, allocation entries, transfers, and expense debits.
4. Review open exceptions before approving the daily state.

## Credential Rotation

Production credential rotation is deferred until the production payment rail and secret store are selected.

Before production:

- choose the payment provider,
- choose the secret-management system,
- document provider webhook secret rotation,
- document API key rotation,
- add a production incident step for disabling provider credentials while keeping Ryan read-only.
