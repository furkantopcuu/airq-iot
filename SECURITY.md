# Security policy

## Scope and known limits

This is a research / teaching project (trace-driven emulation of an IoT air-quality network), not a
production service. In particular:

- The **command channel** (`airq/cmd/*`, `/control/*` API endpoints) has **no authentication** and is
  meant for `localhost` only. A real deployment needs MQTT ACLs and TLS; the broker and the API must
  not be exposed to an untrusted network.
- The MQTT broker is configured anonymously and without TLS (`configs/mosquitto.conf`).
- The project needs **no API key, token or `.env` file** at all. Its only outbound traffic is the
  dataset download and the checksum-verified release download. Secret files (`.env*`, `*.pem`,
  `*.key`, `credentials*`) are git-ignored, and a scan of the full history found none.

## Protections that are in place (and tested in `tests/unit/test_security.py`)

- **Loopback only:** the broker, the API and the Streamlit dashboard listen on `127.0.0.1`; the
  demo starts them that way.
- **DNS rebinding / CSRF:** the API accepts only loopback `Host` headers (HTTP 400 otherwise) and
  refuses state-changing requests that carry a non-loopback `Origin` (HTTP 403), so a web page open
  in the same browser cannot drive the control endpoints. Streamlit runs with XSRF protection on.
- **HTML injection:** station names, quality flags and labels arrive through MQTT, so the dashboard
  HTML-escapes them before rendering.
- **Path traversal:** `/tables/*` and `/figures/*` serve plain names from fixed folders only.
- **Downloads:** release assets are verified against pinned SHA-256 sums; zip extraction rejects
  paths that leave the target folder.
- **Static checks in CI:** `bandit` (medium severity and up), `pip-audit`, `detect-secrets`
  (pre-commit), a repository scan for secret patterns, personal paths and unsafe constructs
  (`shell=True`, `eval`, `pickle`, `verify=False`), and Dependabot.

## Reporting a vulnerability

Please use GitHub's **private vulnerability reporting** (the *Security* tab of the repository ->
*Report a vulnerability*) instead of a public issue. You will get a first answer within a few days.

## Supported versions

Only the latest release receives fixes.
