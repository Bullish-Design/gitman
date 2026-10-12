# Gitman v2 pilot notes

Date: 2026-10-08. Toolchain: jj 0.46.0 (nix/jj.nix), Git 2.54.0.

## Findings during the build

- nixpkgs ships jj 0.43.0. It lacks `jj workspace remove` and `jj workspace add --colocate`.
  jj 0.46.0 (released 2026-10-07) added both. `nix/jj.nix` pins the release binary.
- `jj workspace add` does not create parent directories. Gitman creates them.
- jj accepts an existing empty destination. Gitman uses an atomic `mkdir` to claim the path.
- Four concurrent `work` calls with one name and four paths all succeeded in jj. Gitman now
  takes an advisory `flock` in the Git directory (`gitman-work.lock`). It does not cover native jj.
- In the colocated worktree, `git ls-files --others --ignored --exclude-standard -z` lists
  ignored paths and excludes tracked ones. It also lists jj's `.jj/` files; Gitman filters them.
- The central Devman `gitman` skill (`~/.config/devman/skills/gitman`) is linked by about 60
  projects that still run v1. It was not edited.

## Pilot (disposable clone of this repo, local bare origin, `GITMAN_WORKSPACE_ROOT=/tmp/pilot-ws`)

- `work api`, `work ui` from main; `work stacked --from @-` from inside `api`. All used the
  same root. `jj workspace list` showed all three.
- `close ui` with `.devenv/` output printed `deletes 2 ignored file(s)` before removal.
- `jj workspace forget stacked` kept the directory. `close api` from main worked.

## Friction

- `jj workspace list` prints paths relative to the current workspace. Use `jj workspace root --name`.
- A new secondary workspace has no devenv state; the first `devenv shell` there runs `uv sync`
  and its first-task run can report a spurious failure. A second entry succeeds.
