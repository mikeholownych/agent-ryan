# Ryan Offer Development

## Scope

This document tracks Ryan's initial offer research and public-build content
pipeline. It is not a production offer launch approval. The operator retains
approval over policy values, payments, publication, outreach, and any live
customer-facing claims.

Outbound payments remain operator-handled until a viable provider is selected
and implemented in Ryan. AgentMail may be used as an approved communication and
demand-source layer only through the draft, review, sanitize, approve, and send
workflow documented in `docs/operational-runbook.md`.

## Current Offer Hypothesis

Working title: `AI Operations Control Audit`.

Target buyer hypothesis: small business operators and founders who are adopting
AI tools but do not yet have deterministic controls for outbound communication,
spend, secrets, approval gates, and audit trails.

Initial proof-of-loop package hypothesis:

- one fixed-scope workflow review,
- current AI/tool usage inventory,
- control gap map,
- recommended safe operating policy,
- draft workflow for approval gates and auditability,
- written implementation notes suitable for a non-sensitive public build log.

Initial pricing hypothesis: `$100` proof-of-loop package.

Excluded from the offer:

- autonomous money movement,
- access to customer secrets,
- access to customer production credentials,
- uncontrolled outbound email or messaging,
- publishing customer-sensitive details,
- claims that a customer can run autonomous operations without policy gates.

## Market Research Notes

Research reviewed on `2026-05-29` supports demand for AI governance and
operational control:

- Pax8 reported on `2026-03-24` that `62%` of surveyed SMB leaders were already
  using AI, while adoption was outpacing strategy and governance.
- Business.com reported on `2026-01-20` that `57%` of U.S. small businesses
  were investing in AI technology and that worker trust concerns were rising.
- Tom's Hardware summarized Gallup data published in April 2026 showing that
  AI use at work had reached half of U.S. employees surveyed, with daily or
  weekly use at `28%`.
- TechRadar published a May 2026 agent-security opinion piece emphasizing that
  agentic automation requires auditability, policy boundaries, and forensic
  visibility.

References:

- https://www.globenewswire.com/news-release/2026/03/24/3261322/0/en/New-Pax8-Research-Reveals-Small-Businesses-Are-Adopting-AI-Faster-Than-They-re-Building-Strategies-to-Manage-It.html
- https://www.business.com/articles/ai-usage-smb-workplace-study/
- https://www.tomshardware.com/tech-industry/artificial-intelligence/half-of-all-us-employees-now-use-artificial-intelligence-at-work-crossing-landmark-threshold-for-first-time-gallup-data-shows-daily-and-weekly-usage-hitting-all-time-high-of-28-percent-in-q1-2026-with-65-percent-feeling-positive-about-its-impact-on-productivity
- https://www.techradar.com/pro/why-self-running-agents-are-creating-the-biggest-security-crisis-of-2026

## WordPress Draft Queue

Drafts created on `2026-05-29`:

- `Ryan Build Log: Blog Established`
- `Build Log: Ryan Starts Offer Development`
- `Research Note: SMB AI Automation Needs Controls`
- `Offer Hypothesis: AI Operations Control Audit`

All posts are drafts only. No public publication occurred.

## Publication Gate

Before any draft is published:

1. Review the factual claims and source links.
2. Sanitize all content for secrets, credentials, tokens, customer data, raw
   logs, private infrastructure details, wallet data, and operational-control
   details.
3. Verify that no draft implies autonomous outbound payments, unrestricted
   customer access, or uncontrolled outbound email.
4. Confirm the operator explicitly approves publication.
5. Publish only the approved, sanitized version.

## Next Validation Steps

- Convert the offer hypothesis into a short public-safe landing/post draft.
- Identify 3-5 beachhead customer segments for validation.
- Draft a customer discovery interview guide before any outbound outreach.
- Keep all outreach policy-gated and operator-approved.
- Do not enable WordPress indexing until the first public post is approved.
