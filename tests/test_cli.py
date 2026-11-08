"""Tests for the ./hermes CLI using a fake `docker` binary (no Docker daemon needed)."""

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FAKE_DOCKER = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_DOCKER_LOG"
case "$*" in
  "compose version --short") echo "${FAKE_COMPOSE_VERSION:-2.29.1}" ;;
  *" ps --status running -q "*) printf 'gateway\\nsandbox\\n' ;;
  *" exec -T hermes-sandbox test ! -e "*) exit "${FAKE_EXISTS:-0}" ;;
  *" exec -T hermes-sandbox test -f "*) exit "${FAKE_MISSING:-0}" ;;
  *" exec -T --user hermes hermes-gateway cat "*) echo synthetic-hermes-api-key ;;
esac
cat > /dev/null 2>&1 || true
"""


class CliTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        for name in ("hermes", ".env.example"):
            shutil.copy2(ROOT / name, self.project / name)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        docker = bin_dir / "docker"
        docker.write_text(FAKE_DOCKER)
        docker.chmod(0o755)
        self.log = self.root / "docker.log"
        self.env = {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "FAKE_DOCKER_LOG": str(self.log),
            "HOME": str(self.root),
        }

    def run_cli(self, *args, **env):
        return subprocess.run(
            [str(self.project / "hermes"), *args],
            env={**self.env, **env},
            cwd=self.root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
        )

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_help_needs_no_docker(self):
        result = self.run_cli("help", PATH="/usr/bin:/bin")
        self.assertEqual(result.returncode, 0)
        self.assertIn("Usage: ./hermes", result.stdout)

    def test_rejects_old_compose(self):
        result = self.run_cli("status", FAKE_COMPOSE_VERSION="v2.20.0")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("2.24 or newer", result.stderr)

    def test_unknown_command(self):
        self.assertEqual(self.run_cli("bogus").returncode, 2)

    def test_setup_writes_private_env_and_deploys(self):
        result = self.run_cli("setup", OPENAI_API_KEY="sk-synthetic")
        self.assertEqual(result.returncode, 0, result.stderr)
        env_file = self.project / ".env"
        self.assertEqual(stat.S_IMODE(env_file.stat().st_mode), 0o600)
        lines = env_file.read_text().splitlines()
        self.assertIn("OPENAI_API_KEY='sk-synthetic'", lines)
        self.assertEqual(sum(line.startswith("OPENAI_API_KEY=") for line in lines), 1)
        self.assertIn("HERMES_API_PORT=8000", lines)
        self.assertIn("synthetic-hermes-api-key", result.stdout)
        self.assertIn("http://127.0.0.1:8000/v1", result.stdout)
        compose = f"compose --project-directory {self.project} -f {self.project}/docker-compose.yml"
        self.assertIn(f"{compose} up -d --wait --wait-timeout 600", self.calls())
        # A second run keeps the stored key and does not prompt.
        self.assertEqual(self.run_cli("setup").returncode, 0)
        self.assertIn("OPENAI_API_KEY='sk-synthetic'", env_file.read_text())

    def test_setup_accepts_openai_compatible_provider_from_environment(self):
        result = self.run_cli(
            "setup",
            LLM_BASE_URL="https://api.groq.com/openai/v1",
            LLM_API_KEY="gsk-synthetic",
            HERMES_MODEL="m-1",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = (self.project / ".env").read_text().splitlines()
        for line in (
            "LLM_BASE_URL='https://api.groq.com/openai/v1'",
            "LLM_API_KEY='gsk-synthetic'",
            "HERMES_MODEL='m-1'",
        ):
            self.assertIn(line, lines)
        self.assertIn("OPENAI_API_KEY=your_openai_api_key_here", lines)

    def test_setup_rejects_unsafe_values_before_writing(self):
        result = self.run_cli("setup", LLM_BASE_URL="https://x/v1", HERMES_MODEL="bad model")
        self.assertIn("HERMES_MODEL must not contain spaces", result.stderr)
        self.assertNotIn("LLM_BASE_URL='", (self.project / ".env").read_text())

    def test_setup_without_key_or_terminal_fails_clearly(self):
        result = self.run_cli("setup")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Set OPENAI_API_KEY, or LLM_BASE_URL", result.stderr)
        self.assertFalse(any(" up " in call for call in self.calls()))

    def test_import_validates_and_streams_into_sandbox(self):
        source = self.root / "my skills"
        source.mkdir()
        (source / "SKILL.md").write_text("x")
        self.assertIn("Invalid name", self.run_cli("import", str(source)).stderr)
        self.assertIn("Not a directory", self.run_cli("import", "missing", "name").stderr)
        result = self.run_cli("import", str(source), "my-skills")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(
            any("/workspace/repos/my-skills" in call and "tar -xf" in call for call in self.calls())
        )
        result = self.run_cli("import", str(source), "my-skills", FAKE_EXISTS="1")
        self.assertIn("already exists", result.stderr)

    def test_activate_validates_paths_and_uses_gateway_installer(self):
        for path in ("../etc", "/abs", "a/../b", "a//b", "a/./b", "bad name"):
            with self.subTest(path):
                result = self.run_cli("activate", path)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Invalid path", result.stderr)
        self.assertIn("SKILL.md not found", self.run_cli("activate", "repo/skill", FAKE_MISSING="1").stderr)
        result = self.run_cli("activate", "repo/skills/demo/", "--replace")
        self.assertEqual(result.returncode, 0, result.stderr)
        install = [call for call in self.calls() if "install-skill" in call]
        self.assertTrue(install[-1].endswith("/opt/deployment/gateway.py install-skill demo --replace"))
        self.run_cli("activate", "repo/skills/demo", "renamed")
        install = [call for call in self.calls() if "install-skill" in call]
        self.assertTrue(install[-1].endswith("install-skill renamed"))

    def test_export_picks_source_and_refuses_to_overwrite(self):
        self.assertEqual(self.run_cli("export", "demo").returncode, 0)
        self.assertTrue(
            self.calls()[-1].endswith("cp hermes-gateway:/opt/data/skills/demo ./skills-export/demo")
        )
        self.assertEqual(self.run_cli("export", "repo/skills/demo", "out").returncode, 0)
        self.assertTrue(
            self.calls()[-1].endswith("cp hermes-sandbox:/workspace/repos/repo/skills/demo out/demo")
        )
        (self.root / "out/demo").mkdir(parents=True)
        self.assertIn("already exists", self.run_cli("export", "demo", "out").stderr)

    def test_restore_requires_both_archives_and_confirmation(self):
        prefix = self.root / "backups/hermes-1"
        self.assertIn("Missing", self.run_cli("restore", str(prefix)).stderr)
        prefix.parent.mkdir()
        for part in ("gateway", "sandbox"):
            Path(f"{prefix}-{part}.tar.gz").write_bytes(b"")
        result = self.run_cli("restore", str(prefix))
        self.assertIn("--yes", result.stderr)
        self.assertFalse(any(" stop" in call for call in self.calls()))


if __name__ == "__main__":
    unittest.main()
