# Quarantine Notice: Ryan Repository Excluded

> [!WARNING]
> The `ryan/` repository is explicitly **QUARANTINED** and excluded from the AI Syndicate governed production-readiness envelope. 
> It must not be included in any production build, deployment pipeline, CI validation, or governed runtime environment.

## Reason for Quarantine

During the production-readiness audit, `ryan/` was identified as an ungoverned authority plane with several critical security and compliance gaps:
1. **GitHub Remote**: Configured to an external repository (`git@github.com:mikeholownych/agent-ryan.git`) outside the organization GitLab.
2. **Missing CI/CD & Governance**: No GitLab CI configuration, no release tags, and dirty working tree status.
3. **Secret/Data Exposure**: Root-level active credential files (`.ryan_stripe` and `.ryan_mail_api`) exist in the workspace, and local untracked databases (`ryan.sqlite3`) are adjacent.
4. **No ControlPlane Integration**: Lacks ControlPlane admission gates, ledger verification, and AI Syndicate audit/evidence guarantees.

---

## Required Manual Secret Rotation Actions

The following credentials were found to be exposed or configured locally. Since provider access is not available to the automation stack, these actions are marked **REQUIRED, NOT PERFORMED**.

| Secret / Asset | Type / Value Identifier | Exposure Status | Required Remediation / Rotation Action |
|---|---|---|---|
| **Stripe API Key** | `sk_live_51TbVJQ...` (in `.ryan_stripe`) | Workspace root (untracked local file) | **REQUIRED, NOT PERFORMED**: Revoke the key immediately in the Stripe Dashboard and generate a new one if needed, injecting it only via secure secrets manager (e.g. AWS Secrets Manager). |
| **Mail API Key** | `am_us_b5e1c0...` (in `.ryan_mail_api`) | Workspace root (untracked local file) | **REQUIRED, NOT PERFORMED**: Revoke the Mail API token in the provider console. |
| **Local SQLite DB** | `ryan/ryan.sqlite3` | Local untracked database | **Exclusion Checked**: Ignore rules have been set in `.gitignore` to prevent any DB tracking. Evaluate if history has any test data/traces; retire repo or perform a history purge if any live data is found. |
| **WordPress Credentials** | WordPress admin/editor accounts | Local operational setup | **REQUIRED, NOT PERFORMED**: Revoke/rotate any WordPress app passwords or editor account credentials sent or configured. |

---

## Desired State Enforcement

- **Exclusion**: The monorepo workspace does not include `ryan/` in its `pnpm-workspace.yaml` or build orchestrators.
- **Validation**: Any run of the workspace production-scope validation checks will verify the presence of this quarantine manifest and fail if `ryan/` is treated as a governed stack repository.
