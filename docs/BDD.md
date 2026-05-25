===== BDD.md =====
# Behavior-Driven Design

## 3. Behavioral Design

### 3.1 BDD: Revenue Capture
Scenario: Customer purchases approved offer.
Given a valid checkout link exists
When the customer completes payment
Then the payment is recorded
And revenue is allocated according to policy
And the operator receives a confirmation event.

### 3.2 BDD: Expense Approval
Scenario: Agent proposes a vendor expense under threshold.
Given the vendor is allowlisted
And the amount is within per-transaction cap
When the agent submits the expense request
Then the policy engine approves it
And the payment is executed
And the ledger is updated.

### 3.3 BDD: Expense Rejection
Scenario: Agent proposes an unapproved expense.
Given the vendor is not allowlisted
When the agent submits the expense request
Then the policy engine rejects it
And no payment is executed
And an exception event is logged.

### 3.4 BDD: Kill Switch
Scenario: Operator pauses the system.
Given the system is active
When the operator activates the kill switch
Then all external spend and send actions stop
And pending actions are frozen
And the agent is restricted to read-only planning.

### 3.5 BDD: Budget Exhaustion
Scenario: Operating budget is depleted.
Given the operating wallet balance is below minimum threshold
When the agent attempts a new spend
Then the policy engine blocks the action
And the system emits a budget exhaustion alert.

## 4. System Architecture
