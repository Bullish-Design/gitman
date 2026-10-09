# Hand-off: where "verify before you integrate" lives

## Problem

Gitman 0.11.0 ran a verify gate when you landed or pushed. Two things carried it:
the `[publish].verify` key in `gitman.toml` and the pyjutsu pre-push hook. Gitman
0.12.0 has neither. A consumer that runs native `jj git push` fires no gate.

In this repository, `gitman.toml` no longer exists. The `gitman:publish` task in
`nix/gitman.nix` only builds and uploads. It does not run lint or tests. The gate is
`devenv test`, which runs `gitman:lint` and `gitman:test`. Nothing forces a person
to run it before a push.

## Options

1. Skill law only. The `gitman` skill says "verify before you integrate; never
   integrate on red". Cheap. An agent can skip it.
2. A jj alias. Define `jj verify-push` that runs `devenv test` and then
   `jj git push`. Agents must call the alias.
3. A CI check. GitHub Actions runs the gate on each pull request. `gh pr merge`
   waits for green. This catches every path, including native `jj git push`.

## Recommendation

Option 3 for the hard stop, with option 1 as the agent guidance that exists now.
The decision belongs to the repository owner.
