#!/usr/bin/env bash
# MP2 extended dogfood: init → start → save → version bump → publish → release → reconcile,
# each with an undo where applicable. Drives the real `gitman` console script. The repo + the
# stray are bootstrapped via pyjutsu (the `jj` CLI is not on PATH; the embedded lib is).
set -euo pipefail

GM="$DEVENV_STATE/venv/bin/gitman"
PY="$DEVENV_STATE/venv/bin/python"
ROOT="$(mktemp -d /tmp/gitman-dogfood-XXXX)"
REPO="$ROOT/repo"
REMOTE="$ROOT/remote.git"
mkdir -p "$REPO"
git init --bare -q "$REMOTE"

"$PY" - "$REPO" <<'PY'
import sys
from pathlib import Path
from pyjutsu import Workspace
repo = Path(sys.argv[1])
ws = Workspace.init(repo, colocate=True)
(repo / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "1.2.3"\n')
(repo / "app.py").write_text("print(1)\n")
with ws.transaction("initial") as tx:
    tx.describe("@", "initial")  # no bookmark — init freezes trunk
PY

cd "$REPO"
git remote add origin "$REMOTE"

run() { echo; echo ">>> gitman $*"; "$GM" "$@"; }

run init
run status
run start feat
printf 'print(2)\n' >> app.py
run save -m "feat work"
run version
run version bump minor
echo "  version file now: $(grep '^version\|version =' pyproject.toml)"
run undo
echo "  version file after undo: $(grep '^version\|version =' pyproject.toml)"
run version bump minor
run publish
echo "  remote branches: $(git ls-remote "$REMOTE" 'refs/heads/*' | awk '{print $2}' | tr '\n' ' ')"
run land feat
run status
run release
echo "  tags: $(git tag -l | tr '\n' ' ')"

# reconcile: bootstrap a stray off trunk via pyjutsu, then recover through gitman.
"$PY" - "$REPO" <<'PY'
import sys
from pathlib import Path
from pyjutsu import Workspace
repo = Path(sys.argv[1])
ws = Workspace.load(repo)
with ws.transaction("stray") as tx:
    tx.new("main"); tx.describe("@", "stray work")
(repo / "stray.txt").write_text("stray\n")
ws.snapshot()
with ws.transaction("move @") as tx:
    tx.new("main")
PY

set +e
run status
set -e
run reconcile
run status
run undo
set +e
run status
set -e

echo; echo "=== DOGFOOD OK ($ROOT) ==="
