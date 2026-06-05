"""
Tests for tibet-nc L4 Airlock verification.

PRE-ALPHA — These tests validate the core security model.
"""

import pytest


class TestBlockedCommands:
    """Test that dangerous commands are blocked by the airlock."""

    BLOCKED = [
        "rm -rf /",
        "rm -rf /*",
        "dd if=/dev/zero of=/dev/sda",
        "mkfs.ext4 /dev/sda",
        ":(){ :|:& };:",
        "> /dev/sda",
        "chmod -R 777 /",
        "shutdown -h now",
        "reboot",
        "init 0",
    ]

    ALLOWED = [
        "ls -la",
        "whoami",
        "hostname",
        "date",
        "echo hello",
        "cat /etc/hostname",
        "uname -a",
        "df -h",
        "ps aux",
    ]

    def test_blocked_patterns_exist(self):
        """Verify that the daemon defines blocked patterns."""
        from tibet_nc.daemon import BLOCKED_COMMANDS, BLOCKED_PATTERNS
        assert len(BLOCKED_COMMANDS) > 0
        assert len(BLOCKED_PATTERNS) > 0

    @pytest.mark.parametrize("cmd", BLOCKED)
    def test_dangerous_commands_blocked(self, cmd):
        """Dangerous commands must be caught by airlock."""
        from tibet_nc.daemon import BLOCKED_COMMANDS, BLOCKED_PATTERNS
        import re

        is_blocked = False
        cmd_base = cmd.split()[0] if cmd.split() else cmd

        if cmd_base in BLOCKED_COMMANDS:
            is_blocked = True
        else:
            for pattern in BLOCKED_PATTERNS:
                if re.search(pattern, cmd):
                    is_blocked = True
                    break

        assert is_blocked, f"Command should be blocked: {cmd}"
