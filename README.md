# tibet-nc

Secure remote shell over Matrix E2EE with a TIBET L4 Airlock.

`tibet-nc` is a no-listener remote command channel: there is no SSH port, no TCP
service to scan, and no inbound network path to the host. Commands arrive through
a Matrix room, pass a local airlock, execute in a restricted PTY, and return with
TIBET provenance.

> Status: maintained alpha. Powerful enough for controlled operator use, not a
> general-purpose production SSH replacement yet.

## Why It Exists

Sometimes the right operator path is not an agent workflow. If an agent, cortex,
SNAFT, or policy layer decides an action is above its authority, a human still
needs a narrow, auditable override lane.

`tibet-nc` is that human cockpit:

- no exposed SSH daemon
- Matrix E2EE transport
- allowlisted Matrix senders
- restricted shell
- blocked dangerous command patterns
- per-command L4 hash chain
- TIBET token/audit emission for command execution

The normal agent route remains capsule/cmail approval. `tibet-nc` is for direct
human-in-the-loop diagnostics and bounded intervention.

## Architecture

```text
Matrix client
  -> E2EE room message
  -> tibet-nc daemon
  -> L4 Airlock
       1. sender allowlist
       2. freshness/timebox
       3. command safety filter
       4. hash-chain advance
  -> restricted PTY
  -> Matrix response + TIBET token
```

## Example Use

In the configured Matrix control room:

```text
$ status
$ df -h
$ uptime
$ journalctl --user -n 50
```

Outside the dedicated room, messages must use the `$ ` prefix. Inside the
dedicated room, the deployed daemon accepts both prefixed and direct commands.

## Safety Boundary

`tibet-nc` is intentionally not a raw root shell.

Blocked command families include:

- shutdown/reboot/poweroff/halt
- destructive disk commands such as `mkfs`, `fdisk`, `dd if=/dev`
- known shell bombs
- recursive root deletion patterns
- pipe-to-shell download patterns

High-impact actions should go through a signed capsule/cmail approval flow, not
an ordinary Matrix command. That keeps the split clear:

- `tibet-nc`: human diagnostics and bounded shell
- `cmail/capsule`: explicit signed approval for privileged execution

## Configuration

Create an environment file for the daemon:

```env
MATRIX_HOMESERVER=https://matrix.example.org
TIBET_NC_USER_ID=@tibetnc:matrix.example.org
TIBET_NC_ACCESS_TOKEN=...
TIBET_NC_ROOM=!roomid:matrix.example.org
TIBET_NC_ALLOWED_USERS=@operator:matrix.example.org
TIBET_NC_HOSTNAME=host-a
BRAIN_API_BASE=http://localhost:8000
```

The live Humotica deployment currently uses Matrix on
`chat.jaspervandemeent.nl`; migration to an AInternet Matrix domain is a hosting
decision, not a protocol requirement.

## Install

From a checkout:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[e2ee]"
```

Run:

```bash
python -m tibet_nc.daemon
```

The package metadata exposes a `tibet-nc` console command, but the CLI wrapper
must be verified before the next PyPI upload. See
[`GITHUB_UPLOAD_CHECKLIST.md`](GITHUB_UPLOAD_CHECKLIST.md).

## Systemd

Use a locked-down service account and an environment file outside the repository.

```ini
[Unit]
Description=tibet-nc Matrix remote shell
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/tibet-nc
EnvironmentFile=/etc/tibet-nc.env
ExecStart=/opt/tibet-nc/.venv/bin/python -m tibet_nc.daemon
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

## Current Package Notes

The deployed daemon has had maintenance beyond the older package snapshot:

- `/usr/local/tibet-nc-bin` is included in the restricted PATH
- longer output windows exist for slow package/build commands
- progress output is collapsed before returning to Matrix

Before publishing a fresh PyPI build, sync those deployed changes back into
`src/tibet_nc/daemon.py` through the normal Root AI code-review path.

## Project Status

- Matrix transport: implemented
- L4 Airlock: implemented
- restricted PTY: implemented
- Matrix response with TIBET provenance: implemented
- systemd deployment: proven locally
- file transfer: planned
- interactive full-screen programs: planned
- signed privileged override lane: use cmail/capsule, not raw `$` commands

## License

MIT. See [`LICENSE`](LICENSE).

## Credits

Designed by Jasper van de Meent and Root AI as part of the HumoticaOS / TIBET
ecosystem.
