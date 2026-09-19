# Security Policy

## Supported versions

TrendCite is pre-1.0. Security fixes are made on the latest `main` only.

## Reporting a vulnerability

Please report suspected vulnerabilities privately. Once this repository is published on GitHub, use **GitHub private vulnerability reporting** ("Report a vulnerability" under the Security tab). Please do not open a public issue for security problems.

Include what you found, how to reproduce it, and the impact you expect. There is no bug bounty. This is a volunteer-maintained project, so response times are best-effort.

## Threat model and controls

TrendCite reads public web content and, optionally, sends evidence to an LLM provider. The main risks and how they are handled:

| Risk | Control |
|---|---|
| Prompt injection in retrieved content | Content is cleaned, bounded and treated as data; injection-like text is flagged, never followed. LLM input is JSON inside `<untrusted_evidence>` delimiters with `<`/`>` escaped. LLM output is validated, bounded, redacted, stripped of links absent from the evidence, and can only change the angle and draft outline. Delimiting reduces but does not eliminate injection risk. |
| Secret leakage | No source needs credentials. Keys are read from environment variables and passed only to official SDK clients. Nothing from the environment, filesystem or tool configuration is put in model input. Logs and all output pass through a redaction filter. |
| SSRF / unsafe URLs | Only http/https; private, loopback, link-local, reserved and `.local`/`.internal` hosts are refused, including on redirects; only URLs from the user's configuration are fetched. DNS is not resolved for this check (documented limitation). |
| Resource exhaustion | 10 s timeouts, 2 MB response cap, bounded retries, item limits per feed and query, bounded text lengths. |
| XML attacks | Feeds containing DTD or entity declarations are rejected before parsing. |
| Markdown/HTML injection in reports | Untrusted text is escaped before rendering; URLs are canonicalised and wrapped. |
| Code execution from content | TrendCite never executes, evaluates or shells out with retrieved content. |

## Scope notes

- TrendCite never posts, messages or authenticates to social platforms.
- Using an LLM provider sends the evidence fields described above to that provider under its own terms.
