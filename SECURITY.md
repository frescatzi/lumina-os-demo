# Security policy

## Reporting a vulnerability

Please report security issues privately through GitHub: Security tab, then "Report a vulnerability".
Do not open a public issue for a vulnerability.

Include what you found, how to reproduce it and the impact you expect. I aim to reply within 7 days.

## Never post secrets

Do not paste API keys, tokens, passwords or private URLs in issues, pull requests or discussions, even redacted ones you believe are expired. If you posted one by mistake, rotate it first, then tell me so I can remove the content.

## Scope

This repository is a demo that runs locally with synthetic data. The ingest API binds to `127.0.0.1` by default and has no authentication: do not expose it to a network you do not control. It only accepts `Content-Type: application/json`, which blocks blind cross-site posts from a browser.

Treat the knowledge base as untrusted input for agents. Anything ingested from a feed can contain text written to manipulate an LLM, so agents reading it through MCP should not act on instructions found in documents.
