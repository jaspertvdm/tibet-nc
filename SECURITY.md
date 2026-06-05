# Security Policy

## Supported Status

`tibet-nc` is maintained alpha software. It is suitable for controlled lab and
operator environments where the Matrix room, access token, service account, and
host are all under direct administrative control.

It is not yet a drop-in replacement for production SSH fleets.

## Reporting Vulnerabilities

Report security issues privately:

- security@humotica.com

Please include:

- affected version or commit
- deployment mode
- Matrix homeserver and client family, if relevant
- reproduction steps
- expected impact

## Security Model

The intended defense boundary is:

- no inbound TCP listener on the managed host
- Matrix E2EE transport
- explicit sender allowlist
- freshness/timebox validation
- blocked command patterns
- restricted shell execution
- per-command hash-chain continuity
- TIBET audit/provenance emission

This is a bounded operator shell, not an unrestricted privileged automation
channel.

## High-Impact Actions

Shutdown, reboot, network cut-off, destructive disk operations, user management,
and similar privileged operations should be handled through a signed
cmail/capsule approval flow with explicit scope and audit trail.

They should not be enabled as ordinary `$` Matrix commands.
