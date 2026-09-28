# 53 — gitman has no safe cross-repo invocation, and its foreign-path warning misreads the result

> **Found:** 2026-09-28, running `gitman status` against **nix-meta** from gitman's own
> devenv shell.
> **Severity:** high. The failure mode is silent lock corruption, and it already slipped
> through gitman's own warning once, undetected, for six days.
> **Scope:** gitman's CLI invocation contract (no cross-repo entry point) and the
> foreign-path detector in the `status` warning path.

---

## 1. What happened

gitman manages version control for other repositories. It runs from its own pinned
devenv environment, not from inside the repo it manages. nix-meta's `CLAUDE.md`
documents the invocation:

```
devenv --dir ~/Documents/Projects/gitman shell -- gitman status
```

devenv 2.2.2+b8030c5 removed `--dir`. The command now fails immediately:

```
error: unexpected argument '--dir' found
```

The apparent replacement, `--from path:...`, has different semantics. It loads the
devenv **configuration** from the given path, but evaluates and runs the shell against
the **current working directory**. Run from inside nix-meta:

```
devenv --from path:/home/andrew/Documents/Projects/gitman shell -- gitman status
```

This:

1. Failed with `No pyproject.toml found in /home/andrew/Documents/Projects/nix-meta`
   — gitman's devenv expects a Python project, and nix-meta is not one.
2. Then failed with `exec: gitman: not found`.
3. Before failing, **silently wrote `/home/andrew/Documents/Projects/nix-meta/devenv.lock`.**

Two separate bugs follow from this. §2 covers the corruption itself. §3 covers gitman
misreporting it when asked to look.

## 2. The corruption

The overwritten lock carries gitman's own input closure:

```
devenv, flake-compat, mk-shell-bin, nix2container, nixpkgs, nixpkgs-python,
nixpkgs-src, nixpkgs_2, nixpkgs_3
```

nix-meta's correct lock, on trunk `8da9ac5`, carries:

```
devenv, nixpkgs, nixpkgs-src, repoman, shellij
```

`repoman` and `shellij` — nix-meta's real inputs — are gone. `flake-compat`,
`mk-shell-bin`, `nix2container`, `nixpkgs-python`, `nixpkgs_2`, `nixpkgs_3` — gitman's
inputs, and nothing nix-meta ever declared — are in their place.

nix-meta has no `devenv.yaml` and no `devenv.nix`. It tracks only `devenv.lock`, plus a
`devenv.local.nix` symlink to `~/.config/devman/projects/nix-meta/devenv.local.nix`.
nix-meta cannot legitimately produce a lock naming `nix2container` or `nixpkgs-python`
under any configuration it owns. On inspection the contamination is unambiguous: the
lock's shape belongs to gitman, not to the repo holding it.

## 3. `gitman status` noticed a change, and misattributed it

`gitman status`, run in nix-meta after the corrupted write, reported:

```
!! 1 path(s) in @ were not written by this session (default):
     devenv.lock
   Another session may be working here. `gitman describe` describes ALL of it —
   carve theirs out first: `gitman split --paths <theirs> --into parked/other`.
```

This is the foreign-path warning from [38 — working-copy
co-tenancy](../38-working-copy-co-tenancy/ISSUE.md). It fired correctly — the file
really was written by a process outside the session's own writes — and named the wrong
cause. There was no second session. There was one process, writing into the wrong
repo's devenv state through a misconfigured `--from` invocation.

The suggested remedy makes it worse. `gitman split --paths devenv.lock --into
parked/other` treats the foreign lock as legitimate work belonging to some other actor,
and parks it for later reconciliation. That preserves the corruption instead of flagging
it. A parked lane with a foreign-shaped lock looks, from the outside, exactly like normal
concurrent work waiting to be split out — nothing marks it as damage.

## 4. This already happened once, and was not caught

On 2026-09-22, a lane named `preserve-devenv-lock` was created in nix-meta: commit
`24386e51ef82efc6e957b651c455327f5ba2be89`, message "chore: preserve existing devenv
lock update". Its `devenv.lock` carries the same gitman-shaped input closure described
in §2, differing only in a `nix2container` revision.

Someone followed exactly the guidance `status` gave: saw a foreign-looking `devenv.lock`,
treated it as another session's in-progress update, and parked it in a lane rather than
discard it. The lane sat for six days undetected. Landing it would have dropped
`repoman` and `shellij` from nix-meta's devenv inputs — the same silent breakage the
2026-09-28 incident produced directly.

The cleanup for this lane — abandoning it and restoring the correct lock in nix-meta —
is being handled separately, in nix-meta. It is out of scope for this issue.

## 5. Root cause

gitman is designed as a cross-repo tool: it version-controls repositories other than
its own. It ships no supported way to invoke it against a target repo. Every command in
its own docs and skill assumes the caller is already inside the repo gitman is managing.

`devenv --dir` was the accidental workaround: it changed devenv's working directory
without changing the shell's. Its removal in devenv 2.2.2+b8030c5 closed that gap and
left nothing in its place. `--from path:...` is not a substitute — it loads
configuration from one path and evaluates against another, which is precisely the
combination that let gitman's Python project bleed into nix-meta's Nix-only tree.

## 6. Proposed fix

### Option (a) — add a `--repo <path>` / `-C <path>` global option to the gitman CLI

The gitman process starts in its own directory (so its devenv shell resolves normally),
and `--repo` tells it which working tree to act on. This is the direct fix: gitman
already needs to know the target repo's path internally for every operation, so this
makes the existing cross-repo assumption an explicit, checked argument instead of an
implicit "current directory" the caller must get right by other means.

### Option (b) — ship gitman as a binary on PATH through the developer profile

nix-meta's `CLAUDE.md` already records that `repoman` is supplied this way: "repoman is
supplied by the developer profile." gitman deserves the same treatment. A `gitman`
binary on `PATH`, built once and exported by the developer profile, removes the devenv
dance entirely — no `--dir`, no `--from`, no risk of evaluating one repo's devenv
inside another's working tree. This is the more robust fix: it does not depend on every
caller getting a new flag right, because there is no flag to get wrong.

### Option (c) — document the one invocation that is safe today

Until (a) or (b) ships, the only safe form keeps devenv's evaluation directory and the
gitman process's target directory separate by construction:

```bash
cd /home/andrew/Documents/Projects/gitman && \
  devenv shell -- bash -c 'cd <target-repo> && gitman <args>'
```

This is safe because devenv evaluates in gitman's own directory — where its
`pyproject.toml` and Python project actually live — and the inner `cd` only moves the
`gitman` process itself, after the shell is already built. Nothing about the target
repo's working directory reaches devenv's evaluation.

### Recommendation

Ship **(b)**. It matches the precedent already set for `repoman`, it removes an entire
class of invocation mistakes rather than documenting around them, and it stops every
consumer repo from needing to know gitman's own directory at all. Treat **(a)** as a
complementary long-term improvement for callers who want to pin a specific gitman
build against a specific repo without relying on `PATH`. Use **(c)** only as an interim
workaround until one of the other two ships, and update nix-meta's `CLAUDE.md` to (c)'s
form immediately, since the currently documented invocation is broken outright.

## 7. Proposed fix — foreign-lock detection (secondary problem)

`status`'s foreign-path warning (from [38](../38-working-copy-co-tenancy/ISSUE.md))
should distinguish a foreign **devenv lock** from a foreign **edit by another session**.
When a working-copy `devenv.lock` holds an input closure that does not match the repo's
own `devenv.yaml` or `devenv.nix` — or when the repo has no `devenv.yaml` at all —
gitman should report that the lock looks foreign to this project, not that another
session wrote it:

```
!! devenv.lock does not match this project's devenv configuration:
     inputs present: nix2container, nixpkgs-python, mk-shell-bin, flake-compat
     none of these are declared by this repo's devenv.yaml (or: this repo has no devenv.yaml)
   This looks like a lock written by a different repo's devenv shell, not a
   concurrent session. Do not park it — restore the previous lock or investigate
   how the write happened before saving.
```

This check needs no cross-repo knowledge, only the target repo's own `devenv.yaml` (or
its absence) compared against the lock's own input names. It should not suggest
`gitman split --paths ... --into parked/other` for this case — parking is the correct
remedy for genuine concurrent work, and the wrong remedy for a corrupted lock, as §4
demonstrates.

## 8. Reproduction

1. Have gitman's devenv shell pinned at `~/Documents/Projects/gitman`, expecting a
   Python project (`pyproject.toml` present).
2. Have a consumer repo, e.g. nix-meta, that tracks only `devenv.lock` — no
   `devenv.yaml`, no `devenv.nix` — with inputs `devenv, nixpkgs, nixpkgs-src, repoman,
   shellij`.
3. From inside the consumer repo, run:
   ```
   devenv --from path:/home/andrew/Documents/Projects/gitman shell -- gitman status
   ```
4. Observe the two failures in order (`No pyproject.toml found in <consumer repo>`,
   then `exec: gitman: not found`), and observe that `devenv.lock` in the consumer repo
   has been overwritten before either failure is reported.
5. Run `gitman status` again, correctly invoked, in the now-corrupted consumer repo.
   Observe the "not written by this session" warning, and that it recommends
   `gitman split --paths devenv.lock --into parked/other`.

## 9. Impact

- Silent, unattended data loss of a repo's real devenv input closure, with no error
  surfaced until something downstream fails to evaluate.
- gitman's own remedy for the symptom it does detect actively preserves the damage
  instead of flagging it.
- The failure already reached a landed lane once (§4) and went unnoticed for six days.
  It is reproducible by any consumer repo following gitman's own documented invocation.
- Any other consumer repo using the same `devenv --dir` invocation pattern in its own
  `CLAUDE.md` or equivalent docs is exposed the same way today, since devenv 2.2.2+
  removed `--dir` outright.

## 10. Out of scope

The immediate cleanup in nix-meta — abandoning the `preserve-devenv-lock` lane and
restoring the correct `devenv.lock` on trunk — is being handled separately in nix-meta.
It is not part of this issue.
