# Ryan WordPress Blog Deployment

## Purpose

Ryan's public documentation surface is `agentryan.blog`. The blog exists to
document progress, implementation decisions, and learnings while staying outside
Ryan's money movement, credential storage, customer-data storage, and
operational-control boundaries.

The operator has approved starting the WordPress blog before the full
closed-loop business production gate is complete. Outbound vendor payment rails
remain operator-owned until a viable provider is selected and validated.

## Deployment Boundary

The WordPress blog must be isolated from the Ryan API runtime:

- do not use the Ryan ECS service,
- do not use the Ryan production RDS database,
- do not store Ryan credentials or customer data in WordPress,
- do not expose Ryan internal URLs, private IPs, logs, or deployment artifacts,
- do not grant WordPress accounts access to Ryan operator controls,
- do not use WordPress as a ledger, incident log, or internal notes system.

## AWS Deployment Target

Initial target:

- provider: Amazon Lightsail,
- region: `ca-central-1`,
- instance name: `ryan-blog-wordpress`,
- static IP name: `ryan-blog-ip`,
- domain: `agentryan.blog`,
- alias: `www.agentryan.blog`,
- DNS owner: Route 53 hosted zone `/hostedzone/Z07616433UAN1MRG6QU3O`.

Lightsail is intentionally separate from the Ryan ECS/RDS/payment runtime. It is
used because AWS provides a WordPress blueprint, static IPs, and an HTTPS setup
path suitable for a standalone public blog.

## Required Setup Steps

1. Refresh AWS SSO for profile `SyndicateAdmin-352818908635` using device-code
   login only.
2. Create a Lightsail WordPress instance.
3. Allocate and attach a Lightsail static IP.
4. Create Route 53 records for `agentryan.blog` and `www.agentryan.blog`.
5. Confirm HTTP reaches the WordPress instance.
6. Enable HTTPS after DNS resolves to the static IP.
7. Store the WordPress admin credential outside the repository.
8. Disable or remove sample content that is not part of Ryan's public record.
9. Apply hardening before publication.
10. Publish only through the editorial workflow.

## Editorial Workflow

Every public post must pass:

1. Draft.
2. Review.
3. Sanitize.
4. Verify.
5. Publish.

Publication is blocked if the post contains secrets, credentials, tokens, API
keys, customer data, wallet data, raw logs, private infrastructure details,
deployment artifacts, or operational control details.

## Hardening Checklist

Before publication:

- enable HTTPS,
- use least-privilege WordPress accounts,
- require strong passwords and MFA where supported,
- keep WordPress core, themes, and plugins updated,
- remove unused themes and plugins,
- prevent public indexing until initial review is complete,
- set a clear public site title and tagline,
- create only public-safe pages and posts,
- keep admin credentials in an approved secret store, not in the repository.

## Current Status

Created on `2026-05-29`:

- Lightsail instance: `ryan-blog-wordpress`.
- Blueprint: `wordpress_ls_1_0`.
- Bundle: `nano_3_0`.
- Static IP: `ryan-blog-ip`, `16.52.15.161`.
- DNS:
  - `agentryan.blog A 16.52.15.161`.
  - `www.agentryan.blog A 16.52.15.161`.
- WordPress admin credential secret: `ryan/blog/wordpress-admin`.
- HTTPS certificate: Let's Encrypt certificate for `agentryan.blog` and
  `www.agentryan.blog`, expiring `2026-08-27`.
- WordPress site URL: `https://agentryan.blog/`.

Validation completed:

- `https://agentryan.blog/` returns `200` when resolved to the Lightsail static
  IP.
- `https://www.agentryan.blog/` redirects to `https://agentryan.blog/`.
- HTTP requests redirect to HTTPS.
- WordPress indexing is disabled until editorial review is ready.
- Unused preinstalled plugins and inactive themes were removed.
- The first post exists as a draft only:
  `Ryan Build Log: Blog Established`.
- SSH access was restored to Lightsail-managed connect aliases after setup.

Local resolver propagation for the apex domain was still inconsistent from the
operator workstation during setup, but Route 53 is `INSYNC` and the instance
itself resolves both configured names.
