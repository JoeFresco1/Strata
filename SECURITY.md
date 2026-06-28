# Security Policy

Strata is designed for single-user or trusted-network self-hosting. It does not
provide user accounts or tenant isolation and should not be exposed directly to
the public internet.

The public license is GNU AGPL v3.0. Security reporting does not change the
license terms.

## Reporting a vulnerability

Please report security issues privately through GitHub Security Advisories.
Do not include model API keys, prompts, project exports, telemetry bundles, or
other private project data in a public issue.

## Operator responsibilities

- Bind Strata to localhost unless access is protected by a trusted reverse proxy.
- Keep PostgreSQL and model endpoints off the public internet.
- Store model API credentials in environment variables, not project prompts.
- Review diagnostics bundles before sharing them.
- Keep the host operating system, Python dependencies, Node dependencies, model
  runtime, and PostgreSQL installation updated.
