# Ryan Sandbox Launch Rehearsal

## Result

Status: passed for the sandbox MVP path.

Command run:

```bash
uv run pytest tests/test_bdd_e2e.py -q
```

Result:

```text
5 passed
```

## Covered Scenarios

1. Customer purchases approved offer through simulated checkout and settlement confirmation.
2. Settlement allocates revenue across revenue, operating, and reserve wallets.
3. Agent executes an allowlisted, under-threshold expense through policy.
4. Agent proposes an unapproved expense and receives a blocked outcome with an exception.
5. Operator activates kill switch and agent execution is blocked while read-only console state remains visible.
6. Operating budget depletion blocks spend, emits alert telemetry, and creates an exception.

## Verified Surfaces

- Payment creation and confirmation APIs.
- Multi-wallet settlement allocation.
- Agent execution API.
- Policy decision persistence.
- Expense execution and rejection behavior.
- Exception queue creation.
- Kill switch behavior.
- Ledger and telemetry records.
- Daily report API.
- Operator console visibility.
- Agent console visibility.

## Production Launch Blockers

The sandbox rehearsal does not clear production launch. The implementation plan still lists unresolved production decisions that must be resolved before production money movement:

- Initial niche and exact business objective.
- Production payment rail.
- Production credential and secret-management system.
- Production identity and operator authorization model.
- Final autonomous spend ceiling.
- Final escalation triggers.
- Final reserve minimum and allocation percentages.
- Production hosting and deployment environment.
