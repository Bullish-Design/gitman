# Issue 25 — `AttributeError: 'Workspace' object has no attribute 'sync_colocated'` on every mutating intent (pyjutsu version skew + a too-narrow best-effort guard)

**Date:** 2026-07-11
**Reporter env:** flora devenv (a downstream consumer that installs gitman editable).
**Severity:** noisy + misleading. Every mutating intent exits non-zero with a full
traceback, and the colocated-git re-sync it was trying to do is silently skipped —
so raw `git` tooling sharing the `.git` lags jj (the "verify by hash, not `git
status`" failure class). The intent itself still records.

---

## TL;DR

1. gitman `main` calls `self.ws.sync_colocated()` (`session.py:113`) in its
   post-commit "export colocated git" tail after **every** mutating intent
   (`invariants.py:310 → :268`). This method landed in **pyjutsu 0.10.0**; gitman
   `main` correctly declares `pyjutsu>=0.10` (`pyproject.toml:18`).
2. In flora's venv the installed pyjutsu is **0.8.0**, whose `Workspace` has no
   `sync_colocated`. Calling it raises `AttributeError`.
3. The tail is *documented as best-effort* and wraps the call in
   `try / except PyjutsuError` (`invariants.py:267–270`). **`AttributeError` is not
   in the `PyjutsuError` hierarchy**, so it is *not* caught. It escapes the
   context-manager `__exit__`, is not mapped by the CLI boundary (which only maps
   `PyjutsuError`/`GitmanError`), and Typer prints a full traceback → **exit code 1**.
4. The mutation is nevertheless committed and recorded (the jj tx + undo checkpoint
   run *before* the failing tail), so `gitman status` reports CANONICAL. But the
   colocated-git HEAD/index re-sync never happened → **git HEAD lags jj `@`**.

There are two separable defects:

- **Env (downstream, flora):** a stale venv — editable gitman advanced to the
  `>=0.10` / `sync_colocated` code without any dependency re-resolution, so pyjutsu
  stayed pinned at 0.8.0. Fix = re-sync (the wheelhouse already ships 0.10.1).
- **gitman (this repo):** the "best-effort" tail is not actually best-effort. It
  catches only `PyjutsuError`, so a missing/renamed method — or any non-pyjutsu
  failure — turns a tail that "must never undo the already-recorded intent" into a
  hard exit-1 traceback. **This is the gitman-side bug worth fixing regardless of
  the env cause.**

---

## Environment (all verified on disk / live 2026-07-11)

- **OS:** Linux (kernel 6.18.15). **Python:** 3.13.13.
- **gitman:** editable install of the sibling checkout
  `file:///home/andrew/Documents/Projects/gitman`
  (`…/site-packages/gitman-0.2.2.dist-info/direct_url.json` →
  `{"editable":true}`). `pyproject.toml` `version = "0.3.0"`, requires
  `pyjutsu>=0.10` (line 18). The `0.2.2` dist-info metadata is stale (never
  re-bumped); `gitman --version` prints `gitman 0.2.2` but the running code is
  `main`. The `sync_colocated` call was introduced in gitman commit `1ff193b`
  ("feat(trunk-model): Tier 1 single local-authored model …").
- **pyjutsu:** **0.8.0**, wheel install (no `direct_url.json`), from a vendomat
  prebuilt wheelhouse (`UV_NO_BUILD_PACKAGE=pyjutsu`, `UV_FIND_LINKS`). Live check:
  `python -c "import pyjutsu; print(pyjutsu.__version__, hasattr(pyjutsu.Workspace,'sync_colocated'))"`
  → `0.8.0 False`. Grepping the installed `pyjutsu/` package for `sync_colocated`
  returns nothing; the `_pyjutsu.pyi` `PyWorkspace` surface lists
  `snapshot / is_stale / update_stale / git_import / git_export` but **no
  `sync_colocated`**.
- **pyjutsu source** (sibling `~/Documents/Projects/Pyjutsu`) is at `0.10.1`.
  `sync_colocated` was added in commit `416f9d5`
  ("feat(0.10.0): untrack_paths + sync_colocated + force-with-lease contract",
  2026-07-09), defined at `python/pyjutsu/workspace.py:146`.
- **The wheelhouse already has the fix.** flora's live
  `UV_FIND_LINKS=/nix/store/…-vendomat-wheelhouse` contains
  **`pyjutsu-0.10.1-cp313-abi3-linux_x86_64.whl`** — only the venv is stale.

---

## Exact reproduction (run inside flora's devenv; throwaway repo)

```sh
mkdir gm-repro && cd gm-repro
git init -q -b main
printf 'hello\n' > README.md
git add -A && git -c user.email=t@t -c user.name=t commit -qm initial

gitman init --colocate --trunk main     # OK — "Gitman init — INITIALIZED"
printf 'edit\n' >> README.md
gitman start repro-lane                  # ← AttributeError traceback, exit 1
gitman save -m 'repro edit'              # ← AttributeError traceback, exit 1
```

Both `start` and `save` (and any other `canonical_tx` intent) print the traceback
below and exit 1.

### Full traceback (from `gitman start`)

```
File ".../gitman/cli.py:126 in start
  → _finish_intent(do_start(_session(), name, workspace, onto))
File ".../gitman/core.py:288 in do_start
  → with canonical_tx(session, "start") as tx:
File ".../python3.13/contextlib.py:148 in __exit__
  → next(self.gen)
File ".../gitman/invariants.py:310 in canonical_tx
  → _export_colocated_git(session)
File ".../gitman/invariants.py:268 in _export_colocated_git
  → session.sync_colocated()
File ".../gitman/session.py:113 in sync_colocated
  → self.ws.sync_colocated()
AttributeError: 'Workspace' object has no attribute 'sync_colocated'
```

### Observed effects

- **Intent still records.** `gitman status` → `CANONICAL · 1 lane`, `repro-lane`
  present as a draft with the change. The jj transaction commits and
  `write_undo_checkpoint` runs (`invariants.py:307`) *before* the failing
  `_export_colocated_git` at line 310.
- **But the exit is non-zero (1) with a full traceback** — the failure is *not*
  gracefully swallowed (see root cause). A caller that checks exit codes sees the
  intent "fail".
- **Colocated git HEAD lags jj `@`.** After the two ops, raw
  `git log --oneline` is still at `initial`, and `git status` shows the lane's
  files as uncommitted (`M README.md`, `A gitman.toml`,
  `A .claude/skills/gitman/SKILL.md`). The HEAD/index reset that `sync_colocated`
  performs never ran, so raw-git tooling sharing the `.git` is out of step with jj.

---

## Root cause

### (Refuted) A — stale/renamed internal call
Not the cause. gitman `main` *defines and intends* the method:
`Session.sync_colocated` at `session.py:105` (body `self.ws.sync_colocated()` at
`:113`), reached from `invariants.py:268` (guard tail) and `reconcile.py:81`
(stale-recovery). The call is current, not dangling.

### (Confirmed) B — pyjutsu version skew, via an editable-install blind spot
gitman `main` calls `Workspace.sync_colocated()` and declares `pyjutsu>=0.10`, but
the installed pyjutsu is `0.8.0`, whose `Workspace` lacks the method. The `>=0.10`
pin was never enforced because:

- gitman is installed **editable** (a sibling path checkout). Editing/advancing the
  gitman source updates the running code **immediately**, but does **not**
  re-resolve or re-install gitman's dependencies. So when gitman `main` bumped
  `pyjutsu>=0.8` → `>=0.10` and started calling `sync_colocated`, nothing forced
  the venv's pyjutsu to move off 0.8.0.
- The downstream `repoman.lock` that drives the venv install still carries the
  stale note "gitman declares `pyjutsu>=0.8`" and was last synced **26 Jun 2026**,
  before pyjutsu 0.10.0 (2026-07-09) existed. So the venv was populated with
  pyjutsu 0.8.0 and never refreshed.

Net: **new gitman code × old pyjutsu = AttributeError.** The wheelhouse already
offers `pyjutsu-0.10.1`; only the stale venv needs re-syncing.

### (Confirmed) C — the "best-effort" tail is not best-effort against this error
`_export_colocated_git` (`invariants.py:265–271`) is explicitly last and
best-effort ("a non-colocated repo (or a rare sync failure) must never undo the
already-committed, already-recorded intent"), and `session.py:111` documents the
intended degrade path as pyjutsu raising `GitError` on a non-colocated repo. But the
guard only catches `PyjutsuError`:

```python
try:
    session.sync_colocated()
except PyjutsuError:
    notes.append("colocated git checkout not re-synced — run `gitman reconcile` …")
```

`AttributeError` is outside that hierarchy
(`PyjutsuError(Exception)` → `BackendError` → `GitError`), so it escapes the guard,
escapes the `canonical_tx` `__exit__`, and is not mapped by the CLI boundary
(`cli.py:main` maps only uncaught `PyjutsuError`/`GitmanError` to a clean exit code)
— hence the raw traceback and exit 1. **A tail that documents itself as "must never
undo the intent" should not be able to hard-fail the command over a missing
optional method.**

---

## Affected operations

Every intent whose commit path runs through `canonical_tx` →
`_export_colocated_git`: `start`, `subtask`, `save`, `split`, `land`, `abandon`,
`publish`, `push`, `untrack`, etc. Confirmed live on `start` and `save`.

`reconcile` uses the same `session.sync_colocated()` (`reconcile.py:81`) but only on
its **stale-recovery** branch (gated by `is_stale()`); a non-stale repo
short-circuits before the call (in the repro `gitman reconcile` returned CLEAN, no
error). So `reconcile` can hit the identical crash, but only when the workspace is
actually stale.

---

## Proposed fix

**Primary — gitman robustness (this repo).** Make the best-effort colocated-sync
tail actually best-effort so an old/mismatched pyjutsu degrades to the existing note
instead of a traceback. Any of:

- Broaden the guard: `except (PyjutsuError, AttributeError)` at
  `invariants.py:269` (and mirror in `reconcile.py:81`); or
- Feature-detect before calling:
  `if hasattr(self.ws, "sync_colocated"): self.ws.sync_colocated()` in
  `Session.sync_colocated` (`session.py:113`), else no-op + note; or
- Since the tail is explicitly "must never undo the intent", catch `Exception`
  there and downgrade to the same "run `gitman reconcile` if raw git looks stale"
  note.

This closes the class (any non-pyjutsu failure in the tail) — not just this one
missing method — and keeps the documented contract: the recorded intent must never
be turned into an exit-1 failure by a best-effort post-step.

**Secondary — the actual trigger is a downstream env skew (flora, not gitman).**
Re-sync the venv so pyjutsu satisfies gitman's declared `>=0.10`; the wheelhouse
already ships `pyjutsu-0.10.1`. Concretely for flora: refresh `repoman.lock` (its
`pyjutsu>=0.8` note is stale) and re-run repoman-sync, or
`uv pip install -U pyjutsu` against the wheelhouse. **Note for gitman maintainers:**
because gitman is commonly consumed as an *editable sibling*, a bump to a hard
pyjutsu floor (`>=0.10`) plus a *call* to a method that only exists at that floor is
a silent break for any consumer whose venv isn't re-resolved after the edit —
consider (a) the defensive guard above so the floor is advisory-safe, and/or
(b) a startup/`doctor` check that asserts the pyjutsu version actually provides the
methods gitman calls.

`gitman doctor` currently validates jj version + colocation + trunk; adding a
"pyjutsu provides `sync_colocated`" assertion there would surface this class loudly
instead of at the first mutating intent.

---

## Cross-refs (relate, don't conflate — this is a new regression)

- **Issue 13** (`13-raw-git-push-trunk-desync`) — no native trunk-push; the raw
  `git push <hash>:refs/heads/main` workaround. This bug forced that workaround
  again in flora, since the colocated HEAD was left lagging.
- **`sync_colocated` is the mechanism behind "export colocated git after every
  mutating intent."** With it silently a no-op, the stale-colocated-ref problem is
  effectively re-opened for any consumer on a pre-0.10 pyjutsu.
- flora memories `flora-gitman-colocation-gitignore-reconcile` and
  `flora-gitman-stale-after-sibling-land` — the HEAD-lag / "verify by hash, not
  `git status`" class this feeds.
