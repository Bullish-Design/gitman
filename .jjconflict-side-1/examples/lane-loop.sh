#!/usr/bin/env bash
# Runnable demo of the Gitman lane loop in a throwaway colocated repo.
#
#   devenv shell -- bash examples/lane-loop.sh
#
# It builds a temp repo, then exercises: init → start → save → status → land → undo →
# a conflict rollback → reconcile. Nothing here touches your real repo.
set -u

DEMO="$(mktemp -d "${TMPDIR:-/tmp}/gitman-demo.XXXX")"
cd "$DEMO" || exit 1
export JJ_CONFIG=/dev/null
echo "demo repo: $DEMO"
echo

# --- seed a colocated repo with a version source ---
jj git init --colocate >/dev/null 2>&1
jj config set --repo user.name  "Demo"          >/dev/null 2>&1
jj config set --repo user.email "demo@example"  >/dev/null 2>&1
printf '[project]\nname = "demo"\nversion = "0.1.0"\n' > pyproject.toml
printf 'value = 1\n' > config.py
jj describe -m "initial" >/dev/null 2>&1

run() { echo "\$ gitman $*"; gitman "$@"; echo; }

run init
run status

# --- a normal lane ---
run start add-feature
printf 'feature = True\n' >> config.py
run save -m "add feature flag"
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
run start lane-a; printf 'value = 2\n' > config.py; gitman save -m "a" >/dev/null
run start lane-b; printf 'value = 3\n' > config.py; gitman save -m "b" >/dev/null
echo "\$ gitman land lane-a lane-b   # second conflicts -> rolled back, not stuck"
gitman land lane-a lane-b; echo "(exit $?)"; echo
run status                      # lane-b survives; repo still canonical

# --- recover from an out-of-band edit (off-canonical) ---
jj new main -m "raw stray" >/dev/null 2>&1; printf 'oops\n' > stray.txt; jj new lane-b >/dev/null 2>&1
run status                      # OFF-CANONICAL
run reconcile                   # adopt the stray into a lane
run status                      # CANONICAL again

echo "done. remove the demo repo with:  rm -rf $DEMO"
