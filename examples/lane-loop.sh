#!/usr/bin/env bash
# Runnable demo of the Gitman lane loop in a throwaway colocated repo.
#
#   devenv shell -- bash examples/lane-loop.sh
#
# It builds a temp repo, then exercises: init --colocate → seed → start → describe → status →
# land → undo → a conflict rollback → repair. Nothing here touches your real repo.
#
# Gitman's own golden rule is "route all version control through gitman" — but this demo
# needs one off-canonical repo to show `repair` recovering from it, and there is no `jj` CLI
# in this devenv to make that stray by hand. The "simulate an out-of-band edit" step below
# talks to pyjutsu directly for that one purpose; every other step is a plain `gitman` intent.
set -u

DEMO="$(mktemp -d "${TMPDIR:-/tmp}/gitman-demo.XXXX")"
cd "$DEMO" || exit 1
echo "demo repo: $DEMO"
echo

run() { echo "\$ gitman $*"; gitman "$@"; echo; }

# --- colocate + freeze trunk, then make the first commit ---
run init --colocate
printf '[project]\nname = "demo"\nversion = "0.1.0"\n' > pyproject.toml
printf 'value = 1\n' > config.py
run seed -m "initial"
run status

# --- a normal lane ---
run start add-feature
printf 'feature = True\n' >> config.py
run describe -m "add feature flag"
run status
run land add-feature
run status

# --- versioning ---
run start bump
run version bump minor          # 0.1.0 -> 0.2.0, on the lane
run land bump
run version

# --- the safety net: undo the last intent ---
run start oops
run undo                        # the lane 'oops' never happened
run status

# --- conflicts are first-class: land two lanes that touch the same line ---
run start lane-a; printf 'value = 2\n' > config.py; gitman describe -m "a" >/dev/null
run start lane-b; printf 'value = 3\n' > config.py; gitman describe -m "b" >/dev/null
echo "\$ gitman land lane-a lane-b   # second conflicts -> rolled back, not stuck"
gitman land lane-a lane-b; echo "(exit $?)"; echo
run status                      # lane-b survives; repo still canonical

# --- recover from an out-of-band edit (off-canonical) ---
python3 - <<'PY'
from pathlib import Path

from pyjutsu import Workspace

ws = Workspace.load(".")
with ws.transaction("demo:raw-stray") as tx:
    tx.new(["main"])
    tx.describe("@", "raw stray")
Path("stray.txt").write_text("oops\n")
ws.snapshot()
with ws.transaction("demo:repark") as tx:
    tx.new(["lane-b"])  # park @ back on a named lane; "raw stray" is now orphaned
PY
run status                      # OFF-CANONICAL
run repair                      # adopt the stray into a lane
run status                      # CANONICAL again

echo "done. remove the demo repo with:  rm -rf $DEMO"
