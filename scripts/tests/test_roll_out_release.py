"""roll-out-release.sh deploys the Latest release in an order that keeps writers
off a changing schema, and carries on after a failure (ADR 0081).

The compute machine is the sandbox's checkout; the droplet is a second checkout
the fake ssh runs remote commands in, so remote steps really run as detached
jobs through rollout-remote.sh. make is a fake that records which checkout
called it.
"""

from __future__ import annotations

import os
import textwrap
import unittest
from pathlib import Path

from harness import Sandbox

ROLLOUT = textwrap.dedent(
    """\
    # test rollout
    droplet-1vcpu-2gb    ssh    migrates
    compute-m5pro-48gb   local  writer
    """
)

# The remote command is ssh's last argument; run it here, stdin and all.
SSH = 'cd "$FAKE_DIR" >/dev/null; bash -c "${@: -1}"\n'

# Saves the release CI marked Latest, from a file the test writes, where -o says.
CURL = textwrap.dedent(
    """\
    out=""
    while [ $# -gt 0 ]; do
      case "$1" in -o) out="$2"; shift ;; esac
      shift
    done
    [ -f "$FAKE_DIR/latest.env" ] || exit 22
    if [ -n "$out" ]; then cp "$FAKE_DIR/latest.env" "$out"; fi
    """
)


class RollOut(Sandbox):
    machine = "compute-m5pro-48gb"
    files = {"deploy/compute-m5pro-48gb/rollout": ROLLOUT}

    def setUp(self) -> None:
        super().setUp()
        self.droplet = self.clone("droplet", "droplet-1vcpu-2gb")
        self.install_fake("ssh", SSH)
        self.install_fake("curl", CURL)
        (self.checkout / ".env").write_text(
            "ROLLOUT_REMOTE_HOST=droplet.invalid\n"
            "ROLLOUT_REMOTE_USER=deploy\n"
            f"ROLLOUT_REMOTE_DIR={self.droplet}\n"
            "ROLLOUT_SSH_KEY=/dev/null\n"
            "ROLLOUT_RELEASE_URL=https://releases.invalid/release.env\n"
            "ROLLOUT_POLL_SECONDS=0.1\n"
            "ROLLOUT_STEP_TIMEOUT_SECONDS=20\n"
            "ROLLOUT_RETRY_SECONDS=1800\n"
        )
        self.publish("v1.1.0")

    def publish(self, version: str) -> None:
        (self.fake_dir / "latest.env").write_text(
            f"RELEASE_VERSION={version}\n"
            "CAREERPOLARIS_BACKEND_IMAGE=registry.invalid/careerpolaris-backend@sha256:aa\n"
        )

    def deployed(self, checkout: Path) -> str:
        path = checkout / ".rollout" / "deployed"
        return path.read_text().strip() if path.exists() else "none"

    def set_deployed(self, checkout: Path, version: str) -> None:
        (checkout / ".rollout").mkdir(exist_ok=True)
        (checkout / ".rollout" / "deployed").write_text(f"{version}\n")

    def make_calls(self) -> list[str]:
        return [line for line in self.calls_where() if ": make " in line]

    def roll_out(self) -> int:
        result = self.run_script("roll-out-release.sh", "run")
        self.output = result.stdout + result.stderr
        return result.returncode

    def test_a_new_release_drains_the_writer_before_the_droplet_migrates(self) -> None:
        self.assertEqual(self.roll_out(), 0, self.output)

        self.assertEqual(
            self.make_calls(),
            [
                "droplet: make --no-print-directory prepare-release RELEASE=.rollout/release-v1.1.0.env",
                "checkout: make --no-print-directory prepare-release RELEASE=.rollout/releases/v1.1.0.env",
                "checkout: make --no-print-directory stop-app",
                "droplet: make --no-print-directory stop-app",
                "droplet: make --no-print-directory start-app",
                "droplet: make --no-print-directory check-app",
                "checkout: make --no-print-directory start-app",
                "checkout: make --no-print-directory check-app",
            ],
        )
        self.assertEqual(self.deployed(self.droplet), "v1.1.0")
        self.assertEqual(self.deployed(self.checkout), "v1.1.0")
        self.assertIn('"event":"rollout.finished"', self.output)

    def test_machines_already_on_the_latest_release_are_left_alone(self) -> None:
        self.set_deployed(self.droplet, "v1.1.0")
        self.set_deployed(self.checkout, "v1.1.0")

        self.assertEqual(self.roll_out(), 0, self.output)

        self.assertEqual(self.make_calls(), [])

    def test_a_release_that_fails_to_prepare_stops_nothing(self) -> None:
        self.set_failure("make", "prepare-release")

        self.assertNotEqual(self.roll_out(), 0)

        self.assertFalse([call for call in self.make_calls() if "stop-app" in call])
        self.assertIn("prepare-droplet-1vcpu-2gb", (self.checkout / ".rollout/failed").read_text())

    def test_a_failed_migration_keeps_the_writer_stopped(self) -> None:
        self.set_failure("make", "start-app")

        self.assertNotEqual(self.roll_out(), 0)

        calls = self.make_calls()
        self.assertIn("checkout: make --no-print-directory stop-app", calls)
        self.assertNotIn("checkout: make --no-print-directory start-app", calls)
        self.assertEqual(self.deployed(self.checkout), "none")
        self.assertIn("deploy-droplet-1vcpu-2gb", (self.checkout / ".rollout/failed").read_text())

    def test_a_failed_release_is_not_tried_again_until_the_retry_period_ends(self) -> None:
        self.set_failure("make", "prepare-release")
        self.roll_out()
        calls_before = len(self.make_calls())

        self.assertEqual(self.roll_out(), 0, self.output)

        self.assertEqual(len(self.make_calls()), calls_before)
        self.assertIn('"event":"rollout.waiting"', self.output)

    def test_a_pass_after_the_migration_only_starts_the_writer(self) -> None:
        self.set_deployed(self.droplet, "v1.1.0")

        self.assertEqual(self.roll_out(), 0, self.output)

        self.assertEqual(
            self.make_calls(),
            [
                "checkout: make --no-print-directory prepare-release RELEASE=.rollout/releases/v1.1.0.env",
                "checkout: make --no-print-directory start-app",
                "checkout: make --no-print-directory check-app",
            ],
        )
        self.assertEqual(self.deployed(self.checkout), "v1.1.0")

    def test_a_paused_controller_does_nothing(self) -> None:
        (self.checkout / ".rollout").mkdir()
        (self.checkout / ".rollout" / "paused").touch()

        self.assertEqual(self.roll_out(), 0, self.output)

        self.assertEqual(self.calls_where(), [])

    def test_a_pass_already_running_is_not_joined(self) -> None:
        lock = self.checkout / ".rollout" / "lock"
        lock.mkdir(parents=True)
        (lock / "pid").write_text(str(os.getpid()))

        self.assertEqual(self.roll_out(), 0, self.output)

        self.assertEqual(self.make_calls(), [])
        self.assertIn('"event":"rollout.busy"', self.output)

    def test_a_release_without_a_version_is_refused(self) -> None:
        (self.fake_dir / "latest.env").write_text("CAREERPOLARIS_BACKEND_IMAGE=x@sha256:aa\n")

        self.assertNotEqual(self.roll_out(), 0)

        self.assertEqual(self.make_calls(), [])


class RollOutElsewhere(Sandbox):
    machine = "droplet-1vcpu-2gb"
    files = {"deploy/compute-m5pro-48gb/rollout": ROLLOUT}

    def test_a_machine_without_a_rollout_file_refuses(self) -> None:
        result = self.run_script("roll-out-release.sh", "run")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("runs no rollout", result.stdout)


if __name__ == "__main__":
    unittest.main()
