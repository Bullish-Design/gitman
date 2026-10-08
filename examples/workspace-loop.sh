#!/usr/bin/env bash
# Demo: open two workspaces, then close one that holds ignored output.
set -euo pipefail

demo="$(mktemp -d)"
trap 'rm -rf "$demo"' EXIT
export JJ_CONFIG="$demo/jj.toml" GITMAN_WORKSPACE_ROOT="$demo/workspaces"
printf '[user]\nname = "Demo"\nemail = "demo@example.com"\n' > "$JJ_CONFIG"

mkdir "$demo/repo" && cd "$demo/repo"
jj git init --colocate
printf '.devenv/\n' > .gitignore
jj describe -m "base"
jj new

gitman work api --from '@-'
gitman work ui --from 'root()'
mkdir -p "$GITMAN_WORKSPACE_ROOT/api/.devenv"
echo output > "$GITMAN_WORKSPACE_ROOT/api/.devenv/cache"

jj workspace list
gitman close api      # warns about the ignored file, then removes the directory
jj workspace forget ui  # keeps the files
jj workspace list
ls "$GITMAN_WORKSPACE_ROOT"
