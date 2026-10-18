"""check-app.sh says the app came up and stayed up, or names what did not (ADR 0081)."""

from __future__ import annotations

import textwrap
import unittest

from harness import Sandbox

# A fake docker: compose lists api and worker; each container's state comes
# from a file named for it, so a test sets what `docker inspect` reports.
DOCKER = textwrap.dedent(
    """\
    case " $* " in
      *" config --services "*) printf 'api\\nworker\\n' ;;
      *" ps -q api"*) echo id-api ;;
      *" ps -q worker"*) echo id-worker ;;
      *" inspect "*)
        id="${@: -1}"
        format="${@: -2:1}"
        service="${format%% *}"
        echo "$service $id $(cat "$FAKE_DIR/state.$id") 0" ;;
    esac
    """
)

SETTINGS = {
    "APP_COMPOSE_FILE": "deploy/x/compose.app.yaml",
    "CHECK_APP_SETTLE_SECONDS": "0",
    "CHECK_APP_TIMEOUT_SECONDS": "3",
}


class CheckApp(Sandbox):
    fakes = ()

    def setUp(self) -> None:
        super().setUp()
        self.install_fake("docker", DOCKER)

    def set_state(self, container: str, state: str) -> None:
        (self.fake_dir / f"state.{container}").write_text(state)

    def test_running_and_healthy_services_pass(self) -> None:
        self.set_state("id-api", "healthy")
        self.set_state("id-worker", "running")

        result = self.run_script("check-app.sh", env=SETTINGS)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("2 services up: api, worker", result.stdout)

    def test_a_service_that_keeps_restarting_fails_by_name(self) -> None:
        self.set_state("id-api", "healthy")
        self.set_state("id-worker", "restarting")

        result = self.run_script("check-app.sh", env=SETTINGS)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("worker: restarting", result.stdout)

    def test_an_unhealthy_service_fails_by_name(self) -> None:
        self.set_state("id-api", "unhealthy")
        self.set_state("id-worker", "running")

        result = self.run_script("check-app.sh", env=SETTINGS)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("api: unhealthy", result.stdout)


if __name__ == "__main__":
    unittest.main()
