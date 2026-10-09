#!/usr/bin/env bash
# Demo: open two workspaces, then use native jj to remove or forget them.
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
echo "Inspect $GITMAN_WORKSPACE_ROOT/api before removal. Native jj deletes its directory."
jj workspace remove api  # deletes the workspace and its directory, including ignored output
test ! -e "$GITMAN_WORKSPACE_ROOT/api"
jj workspace forget ui  # drops the registration and keeps the files
test -d "$GITMAN_WORKSPACE_ROOT/ui"
jj workspace list
ls "$GITMAN_WORKSPACE_ROOT"
