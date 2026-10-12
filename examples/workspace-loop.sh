#!/usr/bin/env bash
# Demo: open two workspaces, then close them with `gitman done` and native jj.
set -euo pipefail

demo="$(mktemp -d)"
trap 'rm -rf "$demo"' EXIT
export JJ_CONFIG="$demo/jj.toml"
printf '[user]\nname = "Demo"\nemail = "demo@example.com"\n' > "$JJ_CONFIG"

mkdir "$demo/repo" && cd "$demo/repo"
jj git init --colocate
printf '.devenv/\n' > .gitignore
jj describe -m "base"
jj new

gitman work api --from '@-'
gitman work ui --from 'root()'
mkdir -p .gitman/workspaces/api/.devenv
echo output > .gitman/workspaces/api/.devenv/cache
echo change > .gitman/workspaces/api/feature.txt

jj workspace list
# This repository has no remote, so trunk() is root(). The api work is not on it.
if gitman done api; then echo "done should refuse unlanded work" >&2; exit 1; fi
test -d .gitman/workspaces/api
# The ui workspace holds no work, so done removes it.
gitman done ui
test ! -e .gitman/workspaces/ui
# Native jj is the override. It deletes the directory, including ignored output.
jj workspace remove api
test ! -e .gitman/workspaces/api
jj workspace list
