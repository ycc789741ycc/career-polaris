"""A throwaway deployed checkout, and fake commands that record their calls.

A script under test runs from a checkout made here: a clone of a bare
``origin`` holding the scripts at two tagged releases. Commands it should not
really run (make, docker, ssh, curl) are fakes earlier on PATH. Each fake
appends one line to ``calls.log`` and exits as the test says.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent

# A fake: logs "<name> <args>", and "<checkout>: <name> <args>" to a second
# log, then exits with the code a file names for the first argument that has one.
FAKE = textwrap.dedent(
    """\
    #!/usr/bin/env bash
    name="$(basename "$0")"
    echo "$name $*" >> "$FAKE_LOG"
    echo "$(basename "$PWD"): $name $*" >> "$FAKE_LOG.where"
    for arg in "$@"; do
      if [ -f "$FAKE_DIR/$name.$arg.exit" ]; then
        cat "$FAKE_DIR/$name.$arg.out" 2>/dev/null || true
        exit "$(cat "$FAKE_DIR/$name.$arg.exit")"
      fi
    done
    cat "$FAKE_DIR/$name.out" 2>/dev/null || true
    exit 0
    """
)


def run_git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


class Sandbox(unittest.TestCase):
    """A checkout of a fake origin with releases v1.0.0 and v1.1.0."""

    machine = "droplet-1vcpu-2gb"
    fakes: tuple[str, ...] = ("make",)
    # Committed at both releases, beside the scripts: path -> content.
    files: dict[str, str] = {}

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="scripts-test-"))
        self.addCleanup(shutil.rmtree, self.root)
        self.fake_dir = self.root / "fakes"
        self.fake_dir.mkdir()
        self.log = self.root / "calls.log"
        self.log.touch()
        for name in self.fakes:
            path = self.fake_dir / name
            path.write_text(FAKE)
            path.chmod(0o755)

        origin = self.root / "origin.git"
        work = self.root / "authoring"
        run_git(self.root, "init", "--quiet", "--bare", "--initial-branch=master", str(origin))
        run_git(self.root, "clone", "--quiet", str(origin), str(work))
        shutil.copytree(SCRIPTS, work / "scripts", ignore=shutil.ignore_patterns("tests"))
        (work / ".gitignore").write_text("release.env\n.machine\n.rollout/\n.env\n")
        (work / "VERSION").write_text("1.0.0\n")
        for relative, content in self.files.items():
            (work / relative).parent.mkdir(parents=True, exist_ok=True)
            (work / relative).write_text(content)
        run_git(work, "add", "-A")
        run_git(work, "commit", "--quiet", "-m", "v1.0.0")
        run_git(work, "tag", "v1.0.0")
        (work / "VERSION").write_text("1.1.0\n")
        run_git(work, "commit", "--quiet", "-am", "v1.1.0")
        run_git(work, "tag", "v1.1.0")
        run_git(work, "push", "--quiet", "origin", "master", "--tags")

        self.origin = origin
        self.checkout = self.clone("checkout", self.machine)

    def clone(self, name: str, machine: str) -> Path:
        """Another deployed checkout of origin, at v1.0.0."""
        path = self.root / name
        run_git(self.root, "clone", "--quiet", str(self.origin), str(path))
        run_git(path, "checkout", "--quiet", "--detach", "v1.0.0")
        (path / ".machine").write_text(f"{machine}\n")
        (path / ".env").write_text("")
        return path

    def write_release(self, version: str, name: str = "incoming.env") -> Path:
        path = self.checkout / name
        path.write_text(
            f"RELEASE_VERSION={version}\n"
            "CAREERPOLARIS_BACKEND_IMAGE=registry.invalid/careerpolaris-backend@sha256:aa\n"
        )
        return path

    def set_failure(self, command: str, argument: str, code: int = 1, output: str = "") -> None:
        """Make the fake ``command`` exit with ``code`` when given ``argument``."""
        (self.fake_dir / f"{command}.{argument}.exit").write_text(str(code))
        (self.fake_dir / f"{command}.{argument}.out").write_text(output)

    def install_fake(self, name: str, body: str) -> None:
        """Replace a fake with a script of the test's own."""
        path = self.fake_dir / name
        path.write_text('#!/usr/bin/env bash\necho "$(basename "$0") $*" >> "$FAKE_LOG"\n' + body)
        path.chmod(0o755)

    def answer(self, command: str, output: str) -> None:
        """Make the fake ``command`` print ``output`` whenever it succeeds."""
        (self.fake_dir / f"{command}.out").write_text(output)

    def run_script(
        self, script: str, *args: str, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        environment = {
            **os.environ,
            "PATH": f"{self.fake_dir}:{os.environ['PATH']}",
            "FAKE_LOG": str(self.log),
            "FAKE_DIR": str(self.fake_dir),
            **(env or {}),
        }
        return subprocess.run(
            ["bash", str(self.checkout / "scripts" / script), *args],
            cwd=self.checkout,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def calls_where(self) -> list[str]:
        """Every fake call, as "<checkout>: <command> <args>"."""
        where = Path(f"{self.log}.where")
        return where.read_text().splitlines() if where.exists() else []

    def calls(self, command: str | None = None) -> list[str]:
        lines = self.log.read_text().splitlines()
        if command is None:
            return lines
        return [line for line in lines if line.split(" ", 1)[0] == command]

    def head_version(self) -> str:
        return (self.checkout / "VERSION").read_text().strip()
