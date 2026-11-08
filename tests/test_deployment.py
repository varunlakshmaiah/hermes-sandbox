import contextlib
import importlib.util
import io
import json
import os
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"docker/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gateway = load("gateway")
sandbox = load("sandbox")


def archive(files, links=()):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        for name, target in links:
            info = tarfile.TarInfo(name)
            info.type = tarfile.SYMTYPE
            info.linkname = target
            tar.addfile(info)
    buffer.seek(0)
    return buffer


class GatewayTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name) / "data"
        self.public = Path(self.temporary.name) / "public"
        self.home.mkdir()
        self.addCleanup(os.umask, os.umask(0o022))
        for replacement in (
            patch.object(gateway, "HOME", self.home),
            patch.object(gateway, "PUBLIC", self.public),
            patch.dict(sys.modules, {"hermes_yaml": yaml}),
            patch.dict(os.environ, {"OPENAI_API_KEY": "synthetic-test-only"}, clear=True),
        ):
            replacement.start()
            self.addCleanup(replacement.stop)


class BootstrapTests(GatewayTestCase):
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
        self.assertEqual(config["terminal"]["ssh_host"], "hermes-sandbox")
        self.assertEqual(config["terminal"]["ssh_port"], 2222)
        self.assertEqual(config["terminal"]["env_passthrough"], [])
        self.assertEqual(config["terminal"]["credential_files"], [])
        self.assertEqual(config["model"], {"provider": "openai", "default": "gpt-4.1-mini"})
        self.assertTrue(config["custom"]["keep"])
        self.assertEqual(dotenv_values(self.home / ".env")["DISCORD_BOT_TOKEN"], "")
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

    def test_custom_model(self):
        os.environ["HERMES_MODEL"] = "gpt-custom"
        gateway.configure()
        config = yaml.safe_load((self.home / "config.yaml").read_text())
        self.assertEqual(config["model"]["default"], "gpt-custom")

    def test_overrides_upstream_seeded_dotenv_and_rotates_credentials(self):
        dotenv = self.home / ".env"
        dotenv.write_text(
            "OPENAI_API_KEY=old-provider-key\nAPI_SERVER_KEY=upstream-generated-key\n"
            "DISCORD_BOT_TOKEN=your_discord_token_here_optional\nTERMINAL_ENV=local\n"
            "DISCORD_ALLOW_ALL_USERS=true\nUNRELATED_SETTING=preserved\n"
        )
        gateway.configure()
        values = dotenv_values(dotenv)
        self.assertEqual(values["OPENAI_API_KEY"], "synthetic-test-only")
        self.assertEqual(values["API_SERVER_KEY"], (self.home / ".deployment/api-key").read_text().strip())
        self.assertEqual(values["TERMINAL_ENV"], "ssh")
        self.assertEqual(values["DISCORD_BOT_TOKEN"], "")
        self.assertEqual(values["DISCORD_ALLOW_ALL_USERS"], "false")
        self.assertEqual(values["GATEWAY_ALLOW_ALL_USERS"], "false")
        self.assertEqual(values["UNRELATED_SETTING"], "preserved")
        self.assertEqual(stat.S_IMODE(dotenv.stat().st_mode), 0o600)
        os.environ["OPENAI_API_KEY"] = "synthetic-rotated-key"
        os.environ["API_SERVER_KEY"] = "synthetic-rotated-api-token-at-least-32-characters"
        gateway.configure()
        values = dotenv_values(dotenv)
        self.assertEqual(values["OPENAI_API_KEY"], os.environ["OPENAI_API_KEY"])
        self.assertEqual(values["API_SERVER_KEY"], os.environ["API_SERVER_KEY"])

    def test_preserves_real_discord_settings(self):
        os.environ["DISCORD_BOT_TOKEN"] = "synthetic-discord-token"
        os.environ["DISCORD_ALLOWED_USERS"] = "123,456"
        gateway.configure()
        values = dotenv_values(self.home / ".env")
        self.assertEqual(values["DISCORD_BOT_TOKEN"], "synthetic-discord-token")
        self.assertEqual(values["DISCORD_ALLOWED_USERS"], "123,456")

    def test_refuses_unrestricted_chat_access(self):
        for name in ("DISCORD_ALLOW_ALL_USERS", "GATEWAY_ALLOW_ALL_USERS"):
            with (
                self.subTest(name),
                patch.dict(os.environ, {name: "true"}),
                self.assertRaisesRegex(ValueError, name),
            ):
                gateway.configure()
        (self.home / "config.yaml").write_text("gateway:\n  allow_all_users: true\n")
        with self.assertRaisesRegex(ValueError, "allow_all_users"):
            gateway.configure()
        self.assertFalse((self.home / ".ssh").exists())

    def test_rejects_placeholder_and_invalid_config(self):
        for value in ("", "your_openai_api_key_here"):
            with (
                self.subTest(value),
                patch.dict(os.environ, {"OPENAI_API_KEY": value}),
                self.assertRaisesRegex(ValueError, "OPENAI_API_KEY"),
            ):
                gateway.configure()
        for text, message in (("- not\n- a mapping\n", "mapping"), ("terminal: [1]\n", "'terminal'")):
            with self.subTest(text):
                (self.home / "config.yaml").write_text(text)
                with self.assertRaisesRegex(ValueError, message):
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
            gateway.wait_for_sandbox(attempts=3)
        self.assertIn("hermes-sandbox", " ".join(run.call_args.args[0]))


class HealthTests(GatewayTestCase):
    def setUp(self):
        super().setUp()
        (self.home / ".deployment").mkdir()
        (self.home / ".deployment/api-key").write_text("k" * 40 + "\n")

    def respond(self, urlopen, payload):
        response = MagicMock()
        response.__enter__.return_value = io.BytesIO(json.dumps(payload).encode())
        urlopen.return_value = response

    @patch.object(gateway.subprocess, "run")
    @patch.object(gateway, "urlopen")
    def test_checks_authenticated_api_and_sandbox(self, urlopen, run):
        self.respond(urlopen, {"data": []})
        gateway.health()
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:8000/v1/models")
        self.assertEqual(request.get_header("Authorization"), "Bearer " + "k" * 40)
        self.assertTrue(run.call_args.kwargs["check"])

    @patch.object(gateway.subprocess, "run")
    @patch.object(gateway, "urlopen")
    def test_rejects_unexpected_payload(self, urlopen, run):
        self.respond(urlopen, {"error": "starting"})
        with self.assertRaisesRegex(RuntimeError, "not ready"):
            gateway.health()
        run.assert_not_called()


class InstallSkillTests(GatewayTestCase):
    def test_installs_and_replaces_atomically(self):
        target = gateway.install_skill("demo", archive({"./SKILL.md": b"v1", "./bin/run.py": b"x"}))
        self.assertEqual((target / "SKILL.md").read_text(), "v1")
        self.assertTrue((target / "bin/run.py").is_file())
        with self.assertRaises(FileExistsError):
            gateway.install_skill("demo", archive({"SKILL.md": b"v2"}))
        gateway.install_skill("demo", archive({"SKILL.md": b"v2"}), replace=True)
        self.assertEqual((target / "SKILL.md").read_text(), "v2")
        self.assertFalse((target / "bin").exists())
        self.assertEqual(sorted(p.name for p in (self.home / "skills").iterdir()), ["demo"])

    def test_rejects_unsafe_archives_without_side_effects(self):
        cases = {
            "link": archive({"SKILL.md": b"x"}, links=[("secret", "/opt/data/.env")]),
            "relative link": archive({"SKILL.md": b"x"}, links=[("other", "SKILL.md")]),
            "traversal": archive({"SKILL.md": b"x", "../escape": b"x"}),
            "no SKILL.md": archive({"README.md": b"x"}),
            "not a tar": io.BytesIO(b"definitely not a tar archive" * 40),
        }
        for label, stream in cases.items():
            with self.subTest(label):
                with self.assertRaises((ValueError, tarfile.TarError)):
                    gateway.install_skill("demo", stream)
                self.assertEqual(list((self.home / "skills").iterdir()), [])
        self.assertFalse((self.home.parent / "escape").exists())

    def test_absolute_member_names_stay_inside_the_skill(self):
        target = gateway.install_skill("demo", archive({"SKILL.md": b"x", "/inside": b"x"}))
        self.assertTrue((target / "inside").is_file())

    def test_rejects_bad_names_and_oversized_skills(self):
        for name in ("", "../x", ".hidden", "a/b", "x" * 65):
            with self.subTest(name), self.assertRaisesRegex(ValueError, "Invalid skill name"):
                gateway.install_skill(name, archive({"SKILL.md": b"x"}))
        with patch.object(gateway, "MAX_SKILL_BYTES", 10), self.assertRaisesRegex(ValueError, "too large"):
            gateway.install_skill("big", archive({"SKILL.md": b"x" * 11}))

    def test_cli_dispatch(self):
        stdin = MagicMock(buffer=archive({"SKILL.md": b"x"}))
        with patch.object(sys, "stdin", stdin), contextlib.redirect_stdout(io.StringIO()) as output:
            gateway.main(["install-skill", "cli-skill"])
            self.assertIn("Installed skill 'cli-skill'", output.getvalue())
            self.assertTrue((self.home / "skills/cli-skill/SKILL.md").is_file())
        with self.assertRaisesRegex(SystemExit, "Usage"):
            gateway.main(["unknown"])


class SandboxTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(os.umask, os.umask(0o022))

    def test_prepare_creates_host_key_and_removes_legacy_skills_link(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(sandbox, "HOME", Path(directory)):
            home = Path(directory)
            (home / ".hermes").mkdir()
            (home / "skills").mkdir()
            (home / ".hermes/skills").symlink_to(home / "skills")
            sandbox.prepare()
            key = home / ".ssh/ssh_host_ed25519_key"
            self.assertEqual(stat.S_IMODE(key.stat().st_mode), 0o600)
            self.assertFalse((home / ".hermes/skills").exists())
            self.assertTrue((home / "repos").is_dir())
            before = key.read_bytes()
            sandbox.prepare()
            self.assertEqual(key.read_bytes(), before)

    def test_health_requires_ssh_banner(self):
        for banner, healthy in ((b"SSH-2.0-OpenSSH_10.0\r\n", True), (b"HTTP/1.1 400\r\n", False)):
            with self.subTest(banner), socket.socket() as server:
                server.bind(("127.0.0.1", 0))
                server.listen(1)

                def reply(server=server, banner=banner):
                    connection, _ = server.accept()
                    with connection:
                        connection.sendall(banner)

                thread = threading.Thread(target=reply)
                thread.start()
                with patch.object(sandbox, "PORT", server.getsockname()[1]):
                    if healthy:
                        sandbox.health()
                    else:
                        with self.assertRaises(SystemExit):
                            sandbox.health()
                thread.join()


class ComposeTests(unittest.TestCase):
    def setUp(self):
        self.compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
        self.services = self.compose["services"]

    def test_two_services_and_sandbox_security(self):
        self.assertEqual(set(self.services), {"hermes-gateway", "hermes-sandbox"})
        sandbox = self.services["hermes-sandbox"]
        self.assertEqual(sandbox["user"], "10000:10000")
        self.assertEqual(sandbox["cap_drop"], ["ALL"])
        self.assertIn("no-new-privileges:true", sandbox["security_opt"])
        self.assertTrue(sandbox["read_only"])
        self.assertEqual(sandbox["mem_limit"], "2G")
        self.assertEqual(sandbox["cpus"], 2.0)
        self.assertEqual(sandbox["pids_limit"], 256)
        for key in ("env_file", "environment", "ports"):
            self.assertNotIn(key, sandbox)
        self.assertEqual(
            sandbox["volumes"], ["hermes_workspace:/workspace", "hermes_public_keys:/run/hermes-public:ro"]
        )

    def test_prebuilt_images_with_source_fallback(self):
        for name, service in self.services.items():
            self.assertTrue(service["image"].startswith("ghcr.io/varunlakshmaiah/hermes-sandbox/"), name)
            self.assertTrue((ROOT / service["build"]["dockerfile"]).is_file())
            self.assertNotIn("entrypoint", service)
            self.assertNotIn("healthcheck", service, "health checks live in the Dockerfiles")
            for mount in service["volumes"]:
                self.assertIn(mount.split(":")[0], self.compose["volumes"])
                self.assertNotIn("docker.sock", mount)

    def test_gateway_configuration_works_without_env_file(self):
        service = self.services["hermes-gateway"]
        self.assertEqual(service["env_file"], [{"path": ".env", "required": False}])
        self.assertEqual(service["ports"], ["127.0.0.1:${HERMES_API_PORT:-8000}:8000"])
        environment = service["environment"]
        self.assertEqual(environment["OPENAI_API_KEY"], "${OPENAI_API_KEY:-}")
        self.assertEqual(environment["HERMES_DASHBOARD"], "false")
        self.assertFalse(any(name.startswith("TERMINAL_") for name in environment))
        self.assertEqual(service["depends_on"]["hermes-sandbox"]["condition"], "service_healthy")

    def test_env_example_matches_compose(self):
        example = dotenv_values(ROOT / ".env.example")
        text = (ROOT / "docker-compose.yml").read_text()
        for name in example:
            self.assertIn("${" + name, text)

    def test_images_are_pinned_and_healthchecked(self):
        for name in ("gateway", "sandbox"):
            dockerfile = (ROOT / f"docker/{name}.Dockerfile").read_text()
            self.assertRegex(dockerfile, r"(?m)^FROM \S+:\S+@sha256:[0-9a-f]{64}$")
            self.assertIn("HEALTHCHECK", dockerfile)
        self.assertIn("--password '*'", (ROOT / "docker/sandbox.Dockerfile").read_text())

    def test_ssh_server_rejects_secret_forwarding_and_privilege_paths(self):
        lines = (ROOT / "docker/sshd_config").read_text().splitlines()
        settings = dict(line.split(maxsplit=1) for line in lines if line.strip())
        self.assertNotIn("AcceptEnv", settings)
        for name in ("PasswordAuthentication", "PermitRootLogin", "UsePAM", "PermitUserEnvironment"):
            self.assertEqual(settings[name], "no")
        self.assertEqual(settings["DisableForwarding"], "yes")
        self.assertEqual(settings["AuthenticationMethods"], "publickey")
        self.assertEqual(settings["Port"], str(gateway.SANDBOX_PORT))


if __name__ == "__main__":
    unittest.main()
