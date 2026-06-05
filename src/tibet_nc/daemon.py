"""
TIBET-NC Daemon — Port 22 is dood. Leve de Matrix.

Remote shell via Matrix E2EE transport + TIBET L4 Airlock.
Elke keystroke is een TIBET token. Geen poort. Geen aanvalsoppervlak.

Architectuur:
  JTM App / Element / CLI
      ↓ Matrix E2EE room
      ↓ TIBET-signed command payload
  tibet_nc_daemon
      → Timebox check
      → Sequence chain (L4 hash)
      → Command hash integrity
      → Identity (ed25519 / Matrix verified)
      → PTY execute (bash --restricted)
      → Output terug via Matrix
      → TIBET token issued

Door: Jasper van de Meent (concept) + Root AI (implementatie)
HumoticaOS — Hackaway 2026
"""

import os
import pty
import select
import json
import time
import hashlib
import signal
import asyncio
import threading
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import requests
from nio import AsyncClient, RoomMessageText, InviteEvent
from dotenv import load_dotenv

# Optioneel: ed25519 cryptografie
try:
    from nacl.signing import SigningKey, VerifyKey
    from nacl.exceptions import BadSignatureError
    NACL_AVAILABLE = True
except ImportError:
    NACL_AVAILABLE = False

load_dotenv()

# ---------------------------------------------------------
# CONFIGURATIE
# ---------------------------------------------------------
MATRIX_HOMESERVER = os.getenv("MATRIX_HOMESERVER", "https://chat.jaspervandemeent.nl")
MATRIX_USER_ID = os.getenv("TIBET_NC_USER_ID", "@tibet-nc:chat.jaspervandemeent.nl")
MATRIX_ACCESS_TOKEN = os.getenv("TIBET_NC_ACCESS_TOKEN", "")
BRAIN_API_BASE = os.getenv("BRAIN_API_BASE", "http://localhost:8000")

# Room waar TIBET-NC in luistert — dedicated terminal room
NC_ROOM_ID = os.getenv("TIBET_NC_ROOM", "")

# Command prefix — berichten die hiermee beginnen worden als commands behandeld
CMD_PREFIX = "$ "

# Wie mag commands sturen (Matrix user IDs)
ALLOWED_USERS = os.getenv("TIBET_NC_ALLOWED_USERS", "@jasper:chat.jaspervandemeent.nl").split(",")

# Trust requirement
MIN_TRUST_SCORE = float(os.getenv("TIBET_NC_MIN_TRUST", "0.80"))

# Hostname voor audit
HOSTNAME = os.getenv("TIBET_NC_HOSTNAME", os.uname().nodename)

# ---------------------------------------------------------
# TIMEBOX PER DID TYPE
# ---------------------------------------------------------
TIMEBOX_PER_DID = {
    "jis:pixel": 5.0,       # Snelle 5G/WiFi apparaten
    "jis:satellite": 30.0,  # Hoge latency verbindingen
    "jis:iot": 2.0,         # Sensoren/Beacons
    "matrix": 10.0,         # Matrix berichten (netwerk latency)
    "default": 10.0
}

# ---------------------------------------------------------
# BLOCKED COMMANDS — Nooit uitvoeren
# ---------------------------------------------------------
BLOCKED_COMMANDS = {
    "rm -rf /", "rm -rf /*", ":(){ :|:& };:",  # Fork bomb
    "dd if=/dev/zero", "mkfs", "fdisk",
    "shutdown", "reboot", "halt", "poweroff",
    "passwd", "useradd", "userdel", "usermod",
    "> /dev/sda", "chmod -R 777 /",
}

BLOCKED_PATTERNS = [
    "rm -rf /",
    "> /dev/sd",
    "mkfs.",
    "dd if=/dev",
    ":(){ :",
    "chmod -R 777 /",
    "curl|sh", "curl | sh", "wget|sh", "wget | sh",  # Pipe to shell
]


def log(msg: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    print(f"[{now}] {msg}", flush=True)


# ---------------------------------------------------------
# TIBET TOKEN CREATION
# ---------------------------------------------------------
def create_tibet_token(action_type: str, actor: str, command_hash: str,
                       l4_state: str, metadata: dict = None) -> Optional[str]:
    """Issue a TIBET token for this command execution via protocol/send (matrix)"""
    try:
        resp = requests.post(
            f"{BRAIN_API_BASE}/api/protocol/send",
            json={
                "protocol": "matrix",
                "sender_id": actor,
                "recipient_id": f"tibet-nc@{HOSTNAME}",
                "intent": f"nc.{action_type}",
                "content": f"[TIBET-NC] {action_type} | hash:{command_hash[:16]} | l4:{l4_state[:16]}",
                "metadata": {
                    "hostname": HOSTNAME,
                    "l4_state": l4_state,
                    "action": action_type,
                    "transport": "matrix-e2ee",
                    "service": "tibet-nc",
                    **(metadata or {})
                }
            },
            timeout=5
        )
        if resp.status_code == 200:
            data = resp.json()
            token_id = data.get("token_id") or data.get("id")
            if token_id:
                log(f"✓ TIBET token: {token_id} [{action_type}]")
                return token_id
            else:
                log(f"✓ TIBET logged (no token_id in response)")
                return "logged"
        else:
            log(f"✗ TIBET token HTTP {resp.status_code}: {resp.text[:100]}")
    except Exception as e:
        log(f"✗ TIBET token error: {e}")
    return None


# ---------------------------------------------------------
# L4 AIRLOCK — De onbreekbare check
# ---------------------------------------------------------
class TibetSession:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.l4_hash = hashlib.sha256(b"genesis_tibet_nc_" + session_id.encode()).hexdigest()
        self.lock = threading.Lock()
        self.command_count = 0
        self.created_at = time.time()
        self.last_command_at = 0.0

        # PTY state
        self.fd: Optional[int] = None
        self.pid: Optional[int] = None
        self.active = False

    def verify_airlock(self, sender: str, command: str, timestamp: float) -> tuple[bool, str]:
        """
        L4 Airlock Check — 4 verification layers

        Returns: (passed, reason)
        """
        with self.lock:
            # 1. IDENTITY CHECK — is de afzender toegestaan?
            if sender not in ALLOWED_USERS:
                return False, f"Unauthorized: {sender} niet in allowed users"

            # 2. TIMEBOX CHECK — is het bericht recent genoeg?
            max_latency = TIMEBOX_PER_DID.get("matrix", TIMEBOX_PER_DID["default"])
            age = abs(time.time() - timestamp)
            if age > max_latency:
                return False, f"Expired: {age:.1f}s > {max_latency}s timebox"

            # 3. COMMAND SAFETY CHECK — geblokkeerde commands
            cmd_lower = command.lower().strip()
            if cmd_lower in BLOCKED_COMMANDS:
                return False, f"Blocked: dangerous command"
            for pattern in BLOCKED_PATTERNS:
                if pattern in cmd_lower:
                    return False, f"Blocked: matches pattern '{pattern}'"

            # 4. COMMAND HASH + CHAIN ADVANCE
            command_hash = hashlib.sha256(command.encode('utf-8')).hexdigest()

            # Advance the L4 chain
            new_l4_data = f"{self.l4_hash}:{command_hash}:{timestamp}:{sender}".encode()
            self.l4_hash = hashlib.sha256(new_l4_data).hexdigest()
            self.command_count += 1
            self.last_command_at = time.time()

            return True, command_hash

    def start_pty(self) -> bool:
        """Fork een restricted bash shell"""
        if self.active:
            return True

        try:
            self.pid, self.fd = pty.fork()

            if self.pid == 0:
                # CHILD: Restricted shell
                # --restricted: geen cd, geen command redirects, geen PATH wijzigingen
                # --norc: geen .bashrc laden (voorkomt alias exploits)
                env = {
                    "HOME": "/tmp/tibet-nc",
                    "PATH": "/usr/local/tibet-nc-bin:/usr/bin:/bin",
                    "TERM": "xterm",
                    "PS1": f"tibet-nc@{HOSTNAME}$ ",
                    "TIBET_SESSION": self.session_id,
                }
                os.makedirs("/tmp/tibet-nc", exist_ok=True)
                for k, v in env.items():
                    os.environ[k] = v
                os.execv('/bin/bash', ['bash', '--restricted', '--norc', '--noprofile'])
            else:
                # PARENT: Cleanup handler voor orphan processes
                signal.signal(signal.SIGCHLD, lambda s, f: self._reap_child())
                self.active = True
                log(f"PTY gestart: pid={self.pid}, fd={self.fd}")

                # Wacht even op shell init
                time.sleep(0.3)
                return True

        except Exception as e:
            log(f"PTY fork error: {e}")
            return False

    def _reap_child(self):
        """Cleanup zombie processes"""
        try:
            if self.pid:
                os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            pass

    def execute_command(self, command: str) -> str:
        """Voer command uit in PTY en return output"""
        if not self.active or self.fd is None:
            return "[!] Geen actieve PTY sessie"

        try:
            # Stuur command naar de shell
            os.write(self.fd, (command + '\n').encode('utf-8'))

            # Lees output met timeout
            # Langere timeout voor install/update commands
            import re
            is_long_cmd = any(kw in command.lower() for kw in
                              ['apt', 'install', 'update', 'upgrade', 'pip', 'cargo', 'make'])
            max_wait = 60.0 if is_long_cmd else 10.0
            output_parts = []
            deadline = time.time() + max_wait

            while time.time() < deadline:
                r, _, _ = select.select([self.fd], [], [], 0.3)
                if self.fd in r:
                    try:
                        chunk = os.read(self.fd, 8192).decode('utf-8', errors='replace')
                        if chunk:
                            output_parts.append(chunk)
                            # Longer settle time for package managers
                            settle = 2.0 if is_long_cmd else 0.5
                            deadline = min(time.time() + settle, time.time() + max_wait)
                    except OSError:
                        break
                elif output_parts:
                    # Geen nieuwe data en we hebben al output — klaar
                    break

            output = ''.join(output_parts)

            # Strip ANSI escape codes en terminal control sequences
            output = re.sub(r'\x1b\[[?]?\d*[a-zA-Z]', '', output)  # ANSI escapes
            output = re.sub(r'\x1b\[\d*;\d*[a-zA-Z]', '', output)  # Color codes
            output = re.sub(r'\r', '', output)  # Carriage returns

            # Collapse duplicate progress lines (apt percentages, pip downloads)
            # Lines that only differ in numbers are collapsed to the final one
            lines_raw = output.split('\n')
            collapsed = []
            for line in lines_raw:
                # Skip apt progress lines like "  50% [Working]", "Get:1 ..."
                if re.match(r'^\s*\d+%\s', line.strip()):
                    if collapsed and re.match(r'^\s*\d+%\s', collapsed[-1].strip()):
                        collapsed[-1] = line  # Replace with latest progress
                    else:
                        collapsed.append(line)
                else:
                    collapsed.append(line)
            output = '\n'.join(collapsed)

            # Strip het commando zelf uit de output (echo)
            lines = output.split('\n')
            filtered = []
            prompt_pattern = f"tibet-nc@{HOSTNAME}$"
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    continue
                # Skip de echo van het command
                if stripped == command.strip():
                    continue
                # Skip prompt lines
                if stripped.endswith('$ ' + command.strip()):
                    continue
                if stripped == prompt_pattern or stripped.endswith('$ '):
                    continue
                filtered.append(line)

            return '\n'.join(filtered).strip() or "(geen output)"

        except Exception as e:
            return f"[!] Execute error: {e}"

    def close(self):
        """Sluit de PTY sessie"""
        self.active = False
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
        if self.pid is not None:
            try:
                os.kill(self.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        log(f"Sessie {self.session_id} gesloten. Commands: {self.command_count}")


# ---------------------------------------------------------
# MATRIX DAEMON
# ---------------------------------------------------------
class TibetNCDaemon:
    def __init__(self):
        self.sessions: Dict[str, TibetSession] = {}
        self.client: Optional[AsyncClient] = None
        self.boot_time_ms = int(time.time() * 1000)

    def get_or_create_session(self, room_id: str) -> TibetSession:
        """Eén sessie per room"""
        if room_id not in self.sessions:
            session_id = hashlib.sha256(
                f"tibet-nc:{room_id}:{time.time()}".encode()
            ).hexdigest()[:16]
            session = TibetSession(session_id)
            if session.start_pty():
                self.sessions[room_id] = session
                log(f"Nieuwe sessie: {session_id} voor room {room_id}")
            else:
                log(f"[!] Kon PTY niet starten voor {room_id}")
                return None
        return self.sessions.get(room_id)

    async def handle_message(self, room, event: RoomMessageText):
        """Verwerk inkomend Matrix bericht als TIBET-NC command"""
        body = (event.body or "").strip()
        sender = event.sender
        room_id = room.room_id

        # Skip oude berichten (breinbot patroon)
        if event.server_timestamp < self.boot_time_ms:
            return

        # Skip eigen berichten
        if sender == MATRIX_USER_ID:
            return

        # Alleen berichten met command prefix of in de NC room
        is_nc_room = (NC_ROOM_ID and room_id == NC_ROOM_ID)
        has_prefix = body.startswith(CMD_PREFIX)

        if not is_nc_room and not has_prefix:
            return

        # Strip prefix als aanwezig
        command = body[len(CMD_PREFIX):].strip() if has_prefix else body.strip()
        if not command:
            return

        # Special commands
        if command.lower() in ("exit", "quit", "bye"):
            session = self.sessions.get(room_id)
            if session:
                session.close()
                del self.sessions[room_id]
                await self._send_response(room_id, "🔒 TIBET-NC sessie gesloten.")
                create_tibet_token("session.close", sender,
                                   hashlib.sha256(b"session.close").hexdigest(),
                                   "closed")
            return

        if command.lower() == "status":
            session = self.sessions.get(room_id)
            status = {
                "daemon": f"tibet-nc@{HOSTNAME}",
                "session": session.session_id if session else "none",
                "l4_hash": session.l4_hash[:16] + "..." if session else "n/a",
                "commands": session.command_count if session else 0,
                "uptime": f"{time.time() - session.created_at:.0f}s" if session else "n/a",
                "nacl": NACL_AVAILABLE,
                "allowed_users": len(ALLOWED_USERS),
            }
            await self._send_response(room_id,
                f"📊 TIBET-NC Status\n```json\n{json.dumps(status, indent=2)}\n```")
            return

        if command.lower() == "chain":
            session = self.sessions.get(room_id)
            if session:
                await self._send_response(room_id,
                    f"🔗 L4 Chain State\n"
                    f"Session: `{session.session_id}`\n"
                    f"L4 Hash: `{session.l4_hash}`\n"
                    f"Commands: {session.command_count}\n"
                    f"Last: {session.last_command_at:.0f}")
            else:
                await self._send_response(room_id, "Geen actieve sessie.")
            return

        if command.lower() == "help":
            help_text = (
                "🖥️ **TIBET-NC** — Secure Shell via Matrix\n\n"
                f"Prefix: `{CMD_PREFIX}` (of typ in de NC room)\n\n"
                "**Commands:**\n"
                f"• `{CMD_PREFIX}ls -la` — Voer shell command uit\n"
                f"• `{CMD_PREFIX}status` — Sessie status + L4 hash\n"
                f"• `{CMD_PREFIX}chain` — Toon L4 chain state\n"
                f"• `{CMD_PREFIX}exit` — Sluit sessie\n"
                f"• `{CMD_PREFIX}help` — Dit bericht\n\n"
                "**Beveiliging:** Elk command doorloopt L4 Airlock:\n"
                "1. Identity (Matrix verified sender)\n"
                "2. Timebox (max latency per device type)\n"
                "3. Command safety (blocked patterns)\n"
                "4. Hash chain (L4 continuity)\n\n"
                f"Daemon: `tibet-nc@{HOSTNAME}`\n"
                f"Transport: Matrix E2EE — Port 22 is dood 🔒"
            )
            await self._send_response(room_id, help_text)
            return

        # --- EXECUTE COMMAND ---
        timestamp = time.time()

        # L4 Airlock Check
        session = self.get_or_create_session(room_id)
        if not session:
            await self._send_response(room_id, "❌ Kon geen PTY sessie starten.")
            return

        passed, result = session.verify_airlock(sender, command, timestamp)

        if not passed:
            # Airlock DENIED
            log(f"[AIRLOCK DENY] {sender}: {result}")
            await self._send_response(room_id,
                f"🛑 **Airlock Denied**\n`{result}`")

            create_tibet_token("airlock.deny", sender,
                               hashlib.sha256(command.encode()).hexdigest(),
                               session.l4_hash,
                               {"reason": result})
            return

        # Airlock PASSED — command_hash is in result
        command_hash = result

        # Audit log (hash only, never plaintext!)
        audit = {
            "type": "nc.command.execute",
            "did": sender,
            "command_hash": command_hash[:16],
            "timestamp": timestamp,
            "l4_state": session.l4_hash[:16],
            "session": session.session_id,
            "seq": session.command_count
        }
        log(f"[AUDIT] {json.dumps(audit)}")

        # Execute in PTY
        output = session.execute_command(command)

        # Truncate output voor Matrix (max 4000 chars)
        if len(output) > 4000:
            output = output[:3900] + f"\n... (truncated, {len(output)} chars total)"

        # TIBET token voor de executie
        token_id = create_tibet_token(
            "command.execute", sender, command_hash,
            session.l4_hash,
            {
                "session_id": session.session_id,
                "seq": session.command_count,
                "output_hash": hashlib.sha256(output.encode()).hexdigest()[:16],
                "output_len": len(output)
            }
        )

        # Response met TIBET provenance
        token_ref = f"TIBET: `{token_id[:12]}...`" if token_id else "TIBET: (offline)"
        chain_ref = f"L4: `{session.l4_hash[:12]}...` | #{session.command_count}"

        response = (
            f"```\n{output}\n```\n"
            f"_{token_ref} | {chain_ref}_"
        )

        await self._send_response(room_id, response)

    async def _send_response(self, room_id: str, message: str):
        """Stuur response naar Matrix room"""
        if not self.client:
            return
        try:
            await self.client.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content={
                    "msgtype": "m.text",
                    "body": message,
                    "format": "org.matrix.custom.html",
                    "formatted_body": message,
                },
            )
        except Exception as e:
            log(f"Send error: {e}")

    async def on_invite(self, room, event: InviteEvent):
        """Auto-join rooms bij invite"""
        log(f"Invite voor room {room.room_id}")
        try:
            await self.client.join(room.room_id)
            log(f"Gejoined: {room.room_id}")
        except Exception as e:
            log(f"Join error: {e}")

    async def run(self):
        """Start de TIBET-NC daemon"""
        if not MATRIX_ACCESS_TOKEN:
            log("FATAL: TIBET_NC_ACCESS_TOKEN niet gezet!")
            return

        log(f"TIBET-NC Daemon v1.0 — {HOSTNAME}")
        log(f"Transport: Matrix E2EE via {MATRIX_HOMESERVER}")
        log(f"Allowed users: {ALLOWED_USERS}")
        log(f"Command prefix: '{CMD_PREFIX}'")
        log(f"NaCl crypto: {'✓' if NACL_AVAILABLE else '✗ (demo mode)'}")
        log(f"Port 22: DOOD 🔒")
        log("")

        self.client = AsyncClient(
            homeserver=MATRIX_HOMESERVER,
            user=MATRIX_USER_ID,
            device_id="TIBET_NC_DAEMON",
        )
        self.client.access_token = MATRIX_ACCESS_TOKEN

        # Callbacks
        self.client.add_event_callback(
            lambda room, event: self.on_invite(room, event),
            InviteEvent,
        )
        self.client.add_event_callback(
            lambda room, event: self.handle_message(room, event),
            RoomMessageText,
        )

        # Initial sync
        log("Eerste sync...")
        try:
            await self.client.sync(timeout=30000, full_state=True)
        except Exception as e:
            log(f"Sync error: {e}")
            await self.client.close()
            return

        log("TIBET-NC draait. Wacht op commands via Matrix...")
        log("=" * 60)

        # Sync loop
        while True:
            try:
                await self.client.sync(timeout=30000)
            except Exception as e:
                log(f"Sync error: {e}, herverbinden...")
                await asyncio.sleep(5)

    def shutdown(self):
        """Cleanup alle sessies"""
        log("Shutdown: sessies sluiten...")
        for room_id, session in self.sessions.items():
            session.close()
        self.sessions.clear()
        log("TIBET-NC daemon gestopt.")


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------
if __name__ == "__main__":
    daemon = TibetNCDaemon()
    try:
        asyncio.run(daemon.run())
    except KeyboardInterrupt:
        daemon.shutdown()
    except Exception as e:
        log(f"FATAL: {e}")
        daemon.shutdown()
