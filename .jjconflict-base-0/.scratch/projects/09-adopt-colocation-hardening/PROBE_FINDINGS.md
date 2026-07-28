# Round 09 — probe findings (validate-first)

Probes: `.scratch/projects/09-adopt-colocation-hardening/probes/{probe_gaps,probe_combined}.py`
Run in-process over pyjutsu against a colocated work repo + bare origin.

## Gap A — does `git_fetch` auto-FF local trunk?

- **Baseline clean-FF: YES, the fetch auto-FFs** local trunk to `origin/main` (`behind>0, ahead==0`).
- **Even with a deleted `refs/heads/main` (desynced colocated ref): still auto-FFs.**
- **Even after a real failed lane export (gap B) left stale state: the next fetch still auto-FFs.**

→ I could **not** reproduce the exact "fetch silently doesn't auto-FF" symptom in isolation; it's
state-specific. **But the conclusion is unchanged and stronger:** the fix is to make trunk
advancement *not depend on the fetch at all*. When origin is strictly ahead (`behind>0 && ahead==0`)
and trunk hasn't already reached origin, **explicitly `set_bookmark(trunk, trunk@remote)`**. When the
fetch already auto-FF'd, this is a harmless no-op (sets to the same commit). Deterministic either way.

Regression test simulates the symptom by wrapping `git_fetch` so it leaves local trunk behind
(origin tracking still advances), then asserts adopt advances trunk via the explicit set.

## Gap B — failed lane export

- A **moved jj lane bookmark + externally-diverged `refs/heads/<lane>`** → `git_export()` **RAISES**
  `failed to export some bookmarks: l0@git`.
- **KEY: trunk's git ref IS still written** even when the lane fails — `git::export_refs` writes every
  writable ref, collects failures, *then* pyjutsu raises. So "trunk's ref never updates" is **not**
  the real mechanism; trunk-safety already holds at the jj-lib layer.
- The real residue: pyjutsu raises **before committing the op**, so jj's `@git` tracking can lag, and
  the **stuck `refs/heads/<lane>` lingers** (e.g. an abandoned lane's leftover ref).
- `_export_colocated_git` swallows this **silently** → the stuck ref is invisible until something breaks.
- **Heal that works:** `git update-ref -d refs/heads/<stale>` → `git_import()` → `git_export()`.
  `git_import()` alone is **risky** (it would *resurrect* an abandoned lane from its lingering ref), so
  auto-import is not safe; deleting the leftover ref first is the correct recovery.

→ Fix: (1) keep export trunk-safe (already true) but **surface** the stuck bookmark via `canon.notes`
instead of silent swallow; (2) add a `gitman doctor` **colocated-refs** check (jj bookmark ↔
`refs/heads/*` desync, incl. leftover refs with no bookmark); (3) add a **reconcile** ref-heal that
deletes leftover refs and re-syncs (`git_import`/`git_export`).

## Gap C — survivor lane overlapping the adopted trunk (CONFIRMED, dangerous)

- With **`@` on the survivor lane**, adopt rebases it onto a conflicting trunk → **conflict committed**,
  working copy checked out onto the conflicted commit → **jj conflict markers written into the tracked
  file on disk** (`<<<<<<< … %%%%%%% … +++++++ … >>>>>>>`). `is_stale=False` (checkout happened).
- This is exactly the real-world corruption: had the file been `core.py`, the CLI bricks.

→ Fix: adopt must **never commit a conflicted survivor rebase**. Roll back that single rebase (raise
inside the tx → pyjutsu reverts it), leave the lane on its prior base, report it CONFLICT with
guidance (`gitman sync` to rebase+resolve, or `gitman abandon` if redundant). No checkout of a
conflicted commit ⇒ no markers on disk. Trunk advance + merged-lane retirement still succeed.

## Full forge-loop rehearsal (DoD bar)

Drove the **real `gitman` CLI** through `publish → (forge squash-merge + branch delete) → adopt` on
a scratch colocated repo + bare origin: `start/save/publish` two lanes, forge squash-merges one and
deletes its branch, `gitman adopt`. Result: **ADOPTED** — trunk advanced, `feat-a` retired,
`feat-b` rebased survivor; `status` CANONICAL, `doctor` HEALTHY (incl. `colocated-refs ok`), **zero
manual `pyjutsu`/`git` surgery**. Bar cleared.

Two findings from the rehearsal:

- **`adopt --dry-run` crashed (RevsetError, exit 3) on a conflicted trunk** — the survivor-preview
  loop ran `{trunk}..{lane}` revsets against a conflicted `<trunk>`. Real `adopt` blocks cleanly
  (raises GitmanError → `--force`), but dry-run didn't early-return. **Fixed**: classify divergence
  first, skip the survivor preview when diverged. Regression test added.
- **An *untracked* file in the worktree diverges local trunk** — building a lane with raw
  auto-snapshot tx while `@` still carries the trunk bookmark snapshots the untracked file *into
  trunk*, so a later forge squash conflicts. This is a **raw-ops/test artifact, not a gitman flow
  bug**: real `gitman start` runs over an empty `@` child of trunk and folds in-progress work into a
  *lane*, never trunk — and the skill mandates keeping `gitman.toml` **tracked on trunk**. The
  rehearsal commits the config to trunk and passes. (Worth remembering: don't leave non-gitignored
  untracked files sitting on a bare trunk `@`.)
