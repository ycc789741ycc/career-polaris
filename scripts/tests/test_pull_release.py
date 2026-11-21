"""pull-release.sh pulls each image by digest anonymously, with no credential
helper, so an unattended pull never waits on the Keychain (ADR 0082)."""

from __future__ import annotations

import unittest

from harness import Sandbox

# Records, per call, the arguments and the config and endpoint it ran with.
DOCKER = """\
case "$1" in
  context) echo "unix:///desktop.sock"; exit 0 ;;
  pull) echo "pull config=$(cat "$DOCKER_CONFIG/config.json" 2>/dev/null || echo none) host=${DOCKER_HOST:-none}" >> "$FAKE_LOG" ;;
esac
"""

RELEASE = (
    "RELEASE_VERSION=v1.1.0\n"
    "CAREERPOLARIS_BACKEND_IMAGE=registry.invalid/careerpolaris-backend@sha256:aa\n"
    "CAREERPOLARIS_WEB_IMAGE=registry.invalid/careerpolaris-web@sha256:bb\n"
    "CAREERPOLARIS_PROXY_IMAGE=registry.invalid/careerpolaris-proxy@sha256:cc\n"
)


class PullRelease(Sandbox):
    def setUp(self) -> None:
        super().setUp()
        self.install_fake("docker", DOCKER)
        self.release = self.checkout / "release.env"
        self.release.write_text(RELEASE)

    def pulls(self) -> list[str]:
        return [line for line in self.calls() if line.startswith("pull ")]

    def test_each_image_is_pulled_with_an_empty_config_on_the_current_endpoint(self) -> None:
        result = self.run_script("pull-release.sh", str(self.release))

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.pulls(), ["pull config={} host=unix:///desktop.sock"] * 3)
        self.assertIn("docker tag registry.invalid/careerpolaris-web@sha256:bb careerpolaris-web:prod", self.calls())

    def test_a_docker_host_already_set_is_kept(self) -> None:
        result = self.run_script(
            "pull-release.sh", str(self.release), env={"DOCKER_HOST": "tcp://engine.invalid:2375"}
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.pulls(), ["pull config={} host=tcp://engine.invalid:2375"] * 3)

    def test_an_image_without_a_digest_is_refused_before_any_pull(self) -> None:
        self.release.write_text(RELEASE.replace("careerpolaris-backend@sha256:aa", "careerpolaris-backend:v1.1.0"))

        result = self.run_script("pull-release.sh", str(self.release))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("names no digest for careerpolaris-backend", result.stdout)
        self.assertEqual(self.pulls(), [])


if __name__ == "__main__":
    unittest.main()
