# Security Policy

## Reporting Vulnerabilities

Please do not open public issues for suspected vulnerabilities. Before making this
repository public, the owner should configure either GitHub private vulnerability
reporting or a monitored security contact address, then replace this paragraph with
the exact reporting channel and expected response window.

When reporting a vulnerability, include:

- Affected commit, version, or deployment configuration.
- Steps to reproduce.
- Impact, including whether data exposure, prompt injection, unauthorized tool use,
  or denial of service is possible.
- Any logs, request IDs, or proof-of-concept payloads that help reproduce the issue.

## Supported Version

The current project version is `0.1.0`. It is a local demonstrator and reference
implementation. Production deployments should pin a release tag and maintain a
separate support policy.

## Security Scope

Relevant security areas include:

- Prompt injection and indirect prompt injection.
- Sensitive-information disclosure in answers, logs, or traces.
- Improper output handling in the workbench.
- Upload validation and parser robustness.
- API key handling, trusted-host checks, and rate limiting.
- Excessive agency in task actions or external tool calls.
- Knowledge poisoning through unreviewed FAQ, document, or KG ingestion.
- Dependency, container, and CI supply-chain exposure.

## Local Hardening Baseline

The service already includes API key support, trusted-host validation, basic
rate limiting, upload-size limits, unsupported-file rejection, safe DOM rendering,
and evidence/citation quality gates. These are baseline controls, not a complete
enterprise security program.

Before production use, add gateway authentication, tenant isolation, RBAC, secret
management, audit retention, dependency scanning, container scanning, and security
review for any real business action adapter.
