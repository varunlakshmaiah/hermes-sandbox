"""Sandbox entrypoint and health check. Usage: sandbox.py [health]"""

import os
import socket
import subprocess
import sys
from pathlib import Path

HOME = Path("/workspace")
PORT = 2222


def prepare():
    os.umask(0o077)
    keys = HOME / ".ssh"
    keys.mkdir(mode=0o700, exist_ok=True)
    keys.chmod(0o700)
    key = keys / "ssh_host_ed25519_key"
    if not key.exists():
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
    os.umask(0o022)
    (HOME / "repos").mkdir(exist_ok=True)
    (HOME / ".hermes").mkdir(exist_ok=True)
    # Older releases linked skills to a volume shared with the gateway; Hermes now syncs them.
    legacy = HOME / ".hermes/skills"
    if legacy.is_symlink():
        legacy.unlink()


def health():
    with socket.create_connection(("127.0.0.1", PORT), timeout=3) as connection:
        if not connection.recv(64).startswith(b"SSH-2.0-"):
            raise SystemExit("sshd is not answering")


def main(argv):
    if argv == ["health"]:
        health()
        return
    prepare()
    os.execv("/usr/sbin/sshd", ["/usr/sbin/sshd", "-D", "-e", "-f", "/etc/ssh/sshd_config"])


if __name__ == "__main__":
    main(sys.argv[1:])
