"""prepare-release.sh readies a deployed machine without stopping anything (ADR 0081)."""

from __future__ import annotations

import unittest

from harness import Sandbox, run_git


class PrepareRelease(Sandbox):
    def test_it_checks_out_the_release_then_pulls_and_checks_it(self) -> None:
        release = self.write_release("v1.1.0")

        result = self.run_script("prepare-release.sh", str(release))

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.head_version(), "1.1.0")
        self.assertEqual(
            self.calls("make"),
            [
                "make --no-print-directory pull-app RELEASE=release.env",
                "make --no-print-directory check-env",
                "make --no-print-directory check-schema",
            ],
        )
        self.assertIn("RELEASE_VERSION=v1.1.0", (self.checkout / "release.env").read_text())

    def test_preparing_the_release_already_checked_out_changes_nothing_else(self) -> None:
        release = self.write_release("v1.0.0", name="release.env")

        result = self.run_script("prepare-release.sh", "release.env")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.head_version(), "1.0.0")
        self.assertEqual(release.read_text().splitlines()[0], "RELEASE_VERSION=v1.0.0")

    def test_a_checkout_with_local_changes_is_refused_before_anything_runs(self) -> None:
        (self.checkout / "VERSION").write_text("edited on the machine\n")
        release = self.write_release("v1.1.0")

        result = self.run_script("prepare-release.sh", str(release))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("local changes", result.stdout)
        self.assertEqual(self.calls("make"), [])
        self.assertEqual(run_git(self.checkout, "describe", "--tags"), "v1.0.0")

    def test_a_version_origin_never_tagged_is_refused(self) -> None:
        release = self.write_release("v9.9.9")

        result = self.run_script("prepare-release.sh", str(release))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no tag v9.9.9", result.stdout)
        self.assertEqual(self.calls("make"), [])

    def test_a_file_without_a_version_is_refused(self) -> None:
        release = self.checkout / "incoming.env"
        release.write_text("CAREERPOLARIS_BACKEND_IMAGE=registry.invalid/x@sha256:aa\n")

        result = self.run_script("prepare-release.sh", str(release))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("RELEASE_VERSION", result.stdout)

    def test_a_missing_setting_stops_it_before_the_schema_is_checked(self) -> None:
        self.set_failure("make", "check-env")
        release = self.write_release("v1.1.0")

        result = self.run_script("prepare-release.sh", str(release))

        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("make --no-print-directory check-schema", self.calls("make"))


class PrepareReleaseOnADevelopmentMachine(Sandbox):
    machine = "local"

    def test_local_is_refused_because_it_builds_its_own_images(self) -> None:
        release = self.write_release("v1.1.0")

        result = self.run_script("prepare-release.sh", str(release))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("only a deployed machine", result.stdout)
        self.assertEqual(self.head_version(), "1.0.0")


if __name__ == "__main__":
    unittest.main()
