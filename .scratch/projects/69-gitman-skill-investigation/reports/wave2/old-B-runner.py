#!/usr/bin/env python3
"""Run isolated Gitman skill behavior experiments and capture exact output."""

import os
import shlex
import subprocess
import tempfile
from pathlib import Path


OUT = Path(__file__).resolve().parent
ROOTS = {}


class Scenario:
    def __init__(self, number):
        self.number = number
        self.root = Path(tempfile.mkdtemp(prefix=f"gitman-wave2-old-b-{number}-"))
        ROOTS[number] = self.root
        self.repo = self.root / "repo"
        self.workspace = self.root / "workspaces" / "feature"
        self.log = (OUT / f"old-B-{number}.raw.txt").open("w")
        config = self.root / "jjconfig.toml"
        config.write_text('[user]\nname = "Experiment User"\nemail = "experiment@example.test"\n')
        self.env = dict(os.environ)
        self.env.update(
            JJ_CONFIG=str(config),
            XDG_CONFIG_HOME=str(self.root / "xdg"),
            GIT_CONFIG_GLOBAL="/dev/null",
            GIT_CONFIG_SYSTEM="/dev/null",
            GIT_CONFIG_NOSYSTEM="1",
            GITMAN_WORKSPACE_ROOT=str(self.root / "workspaces"),
            NO_COLOR="1",
            JJ_NO_PAGER="1",
        )
        self.note(f"SANDBOX {self.root}")
        self.note(f"ENV JJ_CONFIG={config} XDG_CONFIG_HOME={self.root / 'xdg'} GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null GIT_CONFIG_NOSYSTEM=1 GITMAN_WORKSPACE_ROOT={self.workspace.parent}")

    def note(self, message):
        self.log.write(f"DECISION {message}\n")
        self.log.flush()

    def run(self, *args, cwd=None):
        cwd = Path(cwd or self.repo)
        self.log.write(f"$ (cd {shlex.quote(str(cwd))} && {shlex.join(args)})\n")
        self.log.flush()
        result = subprocess.run(args, cwd=cwd, env=self.env, text=True, capture_output=True)
        self.log.write(f"[stdout]\n{result.stdout}[stderr]\n{result.stderr}[exit {result.returncode}]\n")
        self.log.flush()
        return result

    def write(self, relative, content, cwd=None):
        target = Path(cwd or self.repo) / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        self.log.write(f"WRITE {target} ({content.encode()!r})\n")
        self.log.flush()

    def setup(self, remote=False, base_file="line.txt", base_content="base\n"):
        self.run("jj", "git", "init", "--colocate", str(self.repo), cwd=self.root)
        self.run("jj", "config", "list", "user.name")
        self.write(base_file, base_content)
        self.run("jj", "status")
        self.run("jj", "describe", "-m", "Base")
        self.run("jj", "bookmark", "create", "main", "-r", "@")
        self.run("jj", "new", "main")
        if remote:
            origin = self.root / "origin"
            self.run("jj", "git", "init", "--no-colocate", str(origin), cwd=self.root)
            git_store = origin / ".jj" / "repo" / "store" / "git"
            self.note(f"Local bare Git backing store exists: {git_store.is_dir()} at {git_store}")
            self.run("jj", "git", "remote", "add", "origin", str(git_store))
            self.run("jj", "git", "push", "--bookmark", "main")

    def preflight(self):
        self.run("jj", "workspace", "list")
        self.run("jj", "log", "-r", "(::working_copies() ~ ::trunk()) ~ empty()")

    def open(self):
        self.run("gitman", "work", "feature")

    def feature(self, relative="feature.txt", content="feature\n", message="Add feature"):
        self.write(relative, content, self.workspace)
        self.run("jj", "status", cwd=self.workspace)
        self.run("jj", "describe", "-m", message, cwd=self.workspace)
        self.run("jj", "new", cwd=self.workspace)
        self.run("jj", "bookmark", "create", "feature", "-r", "@-", cwd=self.workspace)
        self.run("jj", "status", cwd=self.workspace)

    def verify(self, relative="feature.txt", content="feature\n"):
        self.run("python3", "-c", f"from pathlib import Path; assert Path({relative!r}).read_text() == {content!r}", cwd=self.workspace)

    def inspect_removal(self):
        self.run("jj", "log", "-r", "(::feature@ ~ ::trunk()) ~ empty()")
        self.note(f"Workspace directory files before removal: {sorted(str(p.relative_to(self.workspace)) for p in self.workspace.rglob('*') if '.jj' not in p.parts and '.git' not in p.parts)}")

    def close(self):
        self.log.close()


def scenario4():
    s = Scenario(4)
    s.note("Upstream will edit the same line after the feature is verified. A rebase conflict requires a stop before moving main.")
    s.setup(remote=True)
    s.preflight()
    s.open()
    s.feature("line.txt", "feature\n")
    s.verify("line.txt", "feature\n")
    s.write("line.txt", "upstream\n")
    s.run("jj", "status")
    s.run("jj", "describe", "-m", "Upstream line edit")
    s.run("jj", "bookmark", "set", "main", "-r", "@")
    s.run("jj", "new", "main")
    s.run("jj", "git", "push", "--bookmark", "main")
    s.run("jj", "git", "fetch", cwd=s.workspace)
    s.run("jj", "rebase", "-b", "@", "-d", "trunk()", cwd=s.workspace)
    s.run("jj", "status", cwd=s.workspace)
    s.run("jj", "log", "-r", "feature|main", cwd=s.workspace)
    s.note("Stop before main integration because the rebase produced a conflict. Leave feature workspace and bookmark for resolution.")
    s.close()


def scenario5():
    s = Scenario(5)
    s.note("The repository has no remote. Local main integration requires no push.")
    s.setup()
    s.preflight()
    s.open()
    s.feature()
    s.verify()
    fetch = s.run("jj", "git", "fetch", cwd=s.workspace)
    s.note(f"Fetch exit {fetch.returncode}; no remote is configured, so continue with local trunk.")
    s.run("jj", "rebase", "-b", "@", "-d", "trunk()", cwd=s.workspace)
    s.run("jj", "bookmark", "set", "main", "-r", "feature", cwd=s.workspace)
    s.run("jj", "new", "main")
    s.inspect_removal()
    s.run("jj", "workspace", "remove", "feature")
    s.run("jj", "workspace", "list")
    s.run("jj", "log", "-r", "main")
    s.close()


def scenario6():
    s = Scenario(6)
    s.note("Default workspace will hold an unrelated uncommitted file when feature is ready to land.")
    s.setup(remote=True)
    s.preflight()
    s.open()
    s.feature()
    s.verify()
    s.write("other.txt", "default workspace work\n")
    s.run("jj", "status")
    s.run("jj", "git", "fetch", cwd=s.workspace)
    s.run("jj", "rebase", "-b", "@", "-d", "trunk()", cwd=s.workspace)
    s.run("jj", "bookmark", "set", "main", "-r", "feature", cwd=s.workspace)
    s.run("jj", "git", "push", "--bookmark", "main", cwd=s.workspace)
    s.note("Do not run jj new main in default workspace because its working copy holds other work.")
    s.run("jj", "status")
    s.inspect_removal()
    s.run("jj", "workspace", "remove", "feature")
    s.run("jj", "workspace", "list")
    s.run("jj", "status")
    s.close()


def scenario7():
    s = Scenario(7)
    s.note("User requests a pull request; local origin rejects direct main updates through a hook. The test forbids gh and network access.")
    s.setup(remote=True)
    hook = s.root / "origin" / ".jj" / "repo" / "store" / "git" / "hooks" / "pre-receive"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text('#!/bin/sh\nwhile read old new ref; do\n  if [ "$ref" = refs/heads/main ]; then\n    echo "main is protected" >&2\n    exit 1\n  fi\ndone\nexit 0\n')
    hook.chmod(0o755)
    s.note(f"Installed protected-main hook at {hook}; no direct main push will be attempted.")
    s.preflight()
    s.open()
    s.feature()
    s.verify()
    s.run("jj", "git", "fetch", cwd=s.workspace)
    s.run("jj", "rebase", "-b", "@", "-d", "trunk()", cwd=s.workspace)
    s.run("jj", "git", "push", "--bookmark", "feature", cwd=s.workspace)
    s.run("jj", "bookmark", "list", cwd=s.workspace)
    s.note("Stop: opening or merging the requested pull request needs gh and network, both prohibited in this experiment. Keep workspace and feature bookmark.")
    s.close()


def scenario8():
    s = Scenario(8)
    s.note("User says 'use gitman land and gitman status'. Skill and AGENTS.md define only gitman work; use native jj lifecycle commands.")
    s.setup()
    s.preflight()
    s.open()
    s.feature()
    s.verify()
    s.run("jj", "git", "fetch", cwd=s.workspace)
    s.run("jj", "rebase", "-b", "@", "-d", "trunk()", cwd=s.workspace)
    s.run("jj", "bookmark", "set", "main", "-r", "feature", cwd=s.workspace)
    s.run("jj", "new", "main")
    s.inspect_removal()
    s.run("jj", "workspace", "remove", "feature")
    s.run("jj", "workspace", "list")
    s.run("jj", "log", "-r", "main")
    s.close()


def scenario9():
    s = Scenario(9)
    s.note("Fixture models devenv shell changing tracked devenv.lock on shell entry. The real project's shell runs outside this sandbox.")
    s.setup(base_file="devenv.lock", base_content='{"version":1}\n')
    s.note("Simulated shell entry updates devenv.lock to stable version 2 before feature work.")
    s.write("devenv.lock", '{"version":2}\n')
    s.run("jj", "status")
    s.run("jj", "diff", "--", "devenv.lock")
    s.run("jj", "describe", "-m", "Update devenv lock")
    s.run("jj", "new")
    s.run("jj", "bookmark", "set", "main", "-r", "@-")
    s.run("jj", "status")
    s.preflight()
    s.open()
    s.feature()
    s.verify()
    s.run("jj", "git", "fetch", cwd=s.workspace)
    s.run("jj", "rebase", "-b", "@", "-d", "trunk()", cwd=s.workspace)
    s.run("jj", "bookmark", "set", "main", "-r", "feature", cwd=s.workspace)
    s.run("jj", "new", "main")
    s.inspect_removal()
    s.run("jj", "workspace", "remove", "feature")
    s.run("jj", "workspace", "list")
    s.run("jj", "log", "-r", "main::")
    s.close()


for number, scenario in [(4, scenario4), (5, scenario5), (6, scenario6), (7, scenario7), (8, scenario8), (9, scenario9)]:
    try:
        scenario()
    except Exception as exc:
        with (OUT / f"old-B-{number}.raw.txt").open("a") as log:
            log.write(f"UNCAUGHT {type(exc).__name__}: {exc}\n")
        print(f"Scenario {number} failed: {exc}")

for number, root in ROOTS.items():
    print(f"Scenario {number}: {root}")
