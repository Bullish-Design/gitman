# Hand-off: Vendomat moves to Gitman 0.12.0

Kickoff for a Vendomat session. Do not edit Gitman from this session.

## Task

1. In `flake.nix`, change the `gitman` input from `?ref=refs/tags/v0.9.1` to
   `?ref=refs/tags/v0.12.0`. The input is at line 55. The kickoff said lines 4 and 54.
   Line 4 holds no Gitman pin. Check the line numbers again before you edit.
2. Refresh the lock: `nix flake lock --update-input gitman`.
3. Rebuild the toolchain closure. Check that `gitman-uv2nix-cli` (`flake.nix:210`) builds.
   The 0.12.0 package has no Python dependency, so uv2nix resolves an empty set.
4. Check that the closure supplies **jj 0.46.0 or later**. `gitman work` needs
   `jj workspace add --colocate`. Report the exact jj version the closure ships.
5. Run `gitman --help` from the new closure. It must list only `work`.

## Notes

- The pyjutsu wheel wiring (`pyjutsu-wheel`, `pyjutsu-package`, near `flake.nix:116-165`)
  is dead for Gitman. Gitman 0.12.0 does not import pyjutsu. Other consumers may
  still use it. Leave it unless you find no consumer.
- Do not move the pin until the tag `v0.12.0` exists on the Gitman remote.
  Check with `git ls-remote --tags https://github.com/Bullish-Design/gitman v0.12.0`.
- The Devman skill pool swap waits for this work. The pool owner confirms the closure
  ships 0.12.0 before the pool commit.
