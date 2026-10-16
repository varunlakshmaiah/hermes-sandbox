import os
from pathlib import Path
import subprocess


def main():
    os.umask(0o077)
    key_dir = Path("/workspace/.ssh")
    key_dir.mkdir(mode=0o700, exist_ok=True)
    key_dir.chmod(0o700)
    key = key_dir / "ssh_host_ed25519_key"
    if not key.exists():
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
            check=True,
        )
    os.execv(
        "/usr/sbin/sshd",
        ["/usr/sbin/sshd", "-D", "-e", "-f", "/etc/ssh/sshd_config"],
    )


if __name__ == "__main__":
    main()
