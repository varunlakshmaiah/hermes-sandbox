import importlib.util
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml
from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gateway", ROOT / "docker/gateway.py")
gateway = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"hermes_yaml": yaml}):
    spec.loader.exec_module(gateway)


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name) / "data"
        self.public = Path(self.temporary.name) / "public"
        self.home.mkdir()
        for name, value in (("HOME", self.home), ("PUBLIC", self.public)):
            replacement = patch.object(gateway, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)
        replacement = patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "synthetic-test-only", "API_SERVER_KEY": ""},
            clear=True,
        )
        replacement.start()
        self.addCleanup(replacement.stop)

    def test_api_key_is_private_persistent_and_replaceable(self):
        first = gateway.api_key()
        self.assertGreaterEqual(len(first), 32)
        self.assertEqual(gateway.api_key(), first)
        path = self.home / ".deployment/api-key"
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
        os.environ["API_SERVER_KEY"] = "replacement-token-with-at-least-32-characters"
        self.assertEqual(gateway.api_key(), os.environ["API_SERVER_KEY"])
        self.assertEqual(path.read_text().strip(), os.environ["API_SERVER_KEY"])

    def test_rejects_weak_supplied_or_stored_api_key(self):
        os.environ["API_SERVER_KEY"] = "weak"
        with self.assertRaisesRegex(ValueError, "at least 32"):
            gateway.api_key()
        os.environ["API_SERVER_KEY"] = ""
        (self.home / ".deployment/api-key").write_text("weak")
        with self.assertRaisesRegex(ValueError, "Stored API key"):
            gateway.api_key()

    def test_bootstrap_keys_config_and_optional_discord(self):
        (self.home / "config.yaml").write_text(
            "model: old-model\nterminal:\n  backend: local\ncustom:\n  keep: true\n"
        )
        os.environ["DISCORD_BOT_TOKEN"] = "your_discord_token_here_optional"
        gateway.configure()
        config = yaml.safe_load((self.home / "config.yaml").read_text())
        self.assertEqual(config["terminal"]["backend"], "ssh")
        self.assertEqual(config["terminal"]["cwd"], "/workspace")
        self.assertEqual(config["terminal"]["ssh_port"], 2222)
        self.assertEqual(config["terminal"]["env_passthrough"], [])
        self.assertEqual(config["terminal"]["credential_files"], [])
        self.assertEqual(config["model"]["provider"], "openai")
        self.assertEqual(config["model"]["default"], "gpt-4.1-mini")
        self.assertTrue(config["custom"]["keep"])
        self.assertNotIn("DISCORD_BOT_TOKEN", os.environ)
        self.assertEqual(os.environ["TERMINAL_ENV"], "ssh")
        private = (self.home / ".ssh/id_ed25519").read_bytes()
        public = (self.public / "authorized_keys").read_text()
        self.assertTrue(public.startswith("restrict ssh-ed25519 "))
        self.assertNotIn("PRIVATE", public)
        self.assertEqual(stat.S_IMODE((self.public / "authorized_keys").stat().st_mode), 0o644)
        (self.public / "authorized_keys").unlink()
        gateway.configure()
        self.assertEqual((self.home / ".ssh/id_ed25519").read_bytes(), private)
        self.assertEqual((self.public / "authorized_keys").read_text(), public)
        self.assertNotIn("synthetic-test-only", (self.home / "config.yaml").read_text())

    def test_overrides_upstream_seeded_dotenv_and_rotates_credentials(self):
        dotenv = self.home / ".env"
        dotenv.write_text(
            "OPENAI_API_KEY=old-provider-key\nAPI_SERVER_KEY=upstream-generated-key\n"
            "DISCORD_BOT_TOKEN=your_discord_token_here_optional\nTERMINAL_ENV=local\n"
            "UNRELATED_SETTING=preserved\n"
        )
        gateway.configure()
        values = dotenv_values(dotenv)
        self.assertEqual(values["OPENAI_API_KEY"], "synthetic-test-only")
        self.assertEqual(values["API_SERVER_KEY"], os.environ["API_SERVER_KEY"])
        self.assertEqual(values["TERMINAL_ENV"], "ssh")
        self.assertEqual(values["DISCORD_BOT_TOKEN"], "")
        self.assertEqual(values["UNRELATED_SETTING"], "preserved")
        self.assertEqual(stat.S_IMODE(dotenv.stat().st_mode), 0o600)
        os.environ["OPENAI_API_KEY"] = "synthetic-rotated-key"
        os.environ["API_SERVER_KEY"] = "synthetic-rotated-api-token-at-least-32-characters"
        gateway.configure()
        values = dotenv_values(dotenv)
        self.assertEqual(values["OPENAI_API_KEY"], os.environ["OPENAI_API_KEY"])
        self.assertEqual(values["API_SERVER_KEY"], os.environ["API_SERVER_KEY"])

    def test_preserves_real_discord_token(self):
        os.environ["DISCORD_BOT_TOKEN"] = "synthetic-discord-token"
        gateway.configure()
        self.assertEqual(os.environ["DISCORD_BOT_TOKEN"], "synthetic-discord-token")

    def test_rejects_provider_placeholder_and_invalid_config(self):
        os.environ["OPENAI_API_KEY"] = "your_openai_api_key_here"
        with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY"):
            gateway.configure()
        os.environ["OPENAI_API_KEY"] = "synthetic-test-only"
        (self.home / "config.yaml").write_text("- not\n- a mapping\n")
        with self.assertRaisesRegex(ValueError, "mapping"):
            gateway.configure()

    def test_atomic_write_does_not_leave_temporary_files(self):
        path = self.home / "sample"
        gateway.atomic_write(path, "one")
        gateway.atomic_write(path, "two")
        self.assertEqual(path.read_text(), "two")
        self.assertEqual(list(self.home.iterdir()), [path])
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    @patch.object(gateway.time, "sleep")
    @patch.object(gateway.subprocess, "run")
    def test_readiness_retries_timeouts_and_auth_failures(self, run, sleep):
        run.side_effect = [
            subprocess.TimeoutExpired("ssh", 10),
            subprocess.CompletedProcess([], 255, stderr="Permission denied"),
            subprocess.CompletedProcess([], 0),
        ]
        gateway.wait_for_sandbox()
        self.assertEqual(run.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        run.side_effect = None
        run.return_value = subprocess.CompletedProcess([], 255, stderr="Permission denied")
        with self.assertRaisesRegex(RuntimeError, "Permission denied"):
            gateway.wait_for_sandbox()


class ComposeTests(unittest.TestCase):
    def setUp(self):
        self.compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())

    def test_two_services_and_sandbox_security(self):
        self.assertEqual(set(self.compose["services"]), {"hermes-gateway", "hermes-sandbox"})
        sandbox = self.compose["services"]["hermes-sandbox"]
        self.assertEqual(sandbox["user"], "10000:10000")
        self.assertEqual(sandbox["cap_drop"], ["ALL"])
        self.assertIn("no-new-privileges:true", sandbox["security_opt"])
        self.assertTrue(sandbox["read_only"])
        self.assertEqual(sandbox["mem_limit"], "2G")
        self.assertEqual(sandbox["cpus"], 2.0)
        self.assertEqual(sandbox["pids_limit"], 256)
        self.assertNotIn("env_file", sandbox)
        self.assertNotIn("environment", sandbox)
        self.assertNotIn("ports", sandbox)
        self.assertIn("hermes_public_keys:/run/hermes-public:ro", sandbox["volumes"])
        self.assertFalse(any(volume.startswith("hermes_data:") for volume in sandbox["volumes"]))

    def test_named_volumes_auth_and_entrypoint(self):
        for service in self.compose["services"].values():
            self.assertNotIn("entrypoint", service)
            for mount in service["volumes"]:
                self.assertIn(mount.split(":")[0], self.compose["volumes"])
                self.assertNotIn("docker.sock", mount)
        service = self.compose["services"]["hermes-gateway"]
        self.assertEqual(service["env_file"], ".env")
        self.assertEqual(service["ports"], ["127.0.0.1:8000:8000"])
        self.assertEqual(service["environment"]["API_SERVER_ENABLED"], "true")
        self.assertEqual(service["environment"]["HERMES_DASHBOARD"], "false")
        self.assertEqual(service["environment"]["TERMINAL_ENV"], "ssh")
        self.assertEqual(service["depends_on"]["hermes-sandbox"]["condition"], "service_healthy")

    def test_ssh_server_rejects_secret_forwarding_and_privilege_paths(self):
        lines = (ROOT / "docker/sshd_config").read_text().splitlines()
        settings = dict(line.split(maxsplit=1) for line in lines if line.strip())
        self.assertNotIn("AcceptEnv", settings)
        for name in ("PasswordAuthentication", "PermitRootLogin", "UsePAM", "PermitUserEnvironment"):
            self.assertEqual(settings[name], "no")
        self.assertEqual(settings["DisableForwarding"], "yes")
        self.assertEqual(settings["AuthenticationMethods"], "publickey")
        self.assertEqual(settings["Port"], "2222")


if __name__ == "__main__":
    unittest.main()
