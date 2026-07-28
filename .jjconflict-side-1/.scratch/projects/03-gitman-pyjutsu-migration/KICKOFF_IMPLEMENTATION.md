# Kickoff — implement the Gitman → Pyjutsu migration

> Paste this as the first message in a clean session **in the gitman repo**
> (`/home/andrew/Documents/Projects/gitman`). The plan has already been re-evaluated, pressure-tested
> against the real APIs, and **approved**. Your job is to **execute** it — not to re-litigate the
> design. Where the approved plan and the code disagree, trust the code and flag it; otherwise build.

## What's approved (read these first — they are authoritative)

In `.scratch/projects/03-gitman-pyjutsu-migration/`:
1. **`MIGRATION_PLAN_v2.md`** — the refined, sign-off-ready plan. This is your spec. (The older
   `MIGRATION_PLAN.md` is the superseded draft; ignore conflicts in it.)
2. **`DECISION_LOG.md`** — every design decision + the *why*, plus the verification matrix.
3. **`UPSTREAM_pyjutsu_immutability.md`** — context only; an upstream report. Do **not** wait on or
   depend on any pyjutsu change. gitman enforces trunk protection itself (see below).

Also read, as before: `docs/GITMAN_CONCEPT.md`, `CLAUDE.md`, the current `src/gitman/` source, and
`../Pyjutsu/README.md` + `../Pyjutsu/python/pyjutsu/` (the public API). The behavior probes used to
validate the plan are in `.scratch/probe_pyjutsu.py`, `probe2.py`, `probe3.py` — rerun them if you
want to re-confirm any pyjutsu behavior yourself.

## Two settled decisions (do not re-ask)

- **Distribution = build-from-sibling now.** gitman's devenv adds the Rust toolchain + maturin and
  `maturin develop`s `../Pyjutsu` (uv path dependency). Drop gitman's `nixpkgs-jj` pin and the `jj`
  package; keep `git` (for `tags.py`). The jj 0.38 pin lives solely in pyjutsu; gitman inherits it.
- **Trunk protection = gitman-enforced only.** Do not rely on pyjutsu/jj-lib immutability (it
  protects only the root commit). Enforce trunk protection in gitman policy: by-construction (only
  `land` advances trunk; every rebase targets `trunk..lane`) **plus** a transactional postcondition
  asserting trunk's `commit_id` is unchanged unless the intent is `land`.

## Verified pyjutsu facts you must build around (don't re-derive; do sanity-check)

1. **Reads are frozen** — a new/edited file is invisible to `diff_stat`/`log` until `ws.snapshot()`.
   So `status` and `start`'s adopt-check must snapshot first. (#1 correctness item.)
2. **`ws.transaction()` auto-snapshots a dirty `@` as a *separate preceding* op.** Use
   **snapshot-first + `transaction(intent, auto_snapshot=False)`** so each intent is exactly one
   mutation op with a deterministic parent.
3. **Rebase into a conflict does NOT raise** — it returns a commit with `has_conflict=True`. Branch
   on `head.has_conflict` after every rebase (as `land`/`sync` do today). There is no rebase
   exception to catch.
4. **No native "nothing changed" signal** — empty tx / already-based rebase succeed and publish an
   op. Delete all `"Nothing changed"`/`"immutable"` stderr string-matching; use typed exceptions +
   `has_conflict`.
5. **`ws.undo()` alone is wrong for multi-op intents.** Keep `.gitman/last-undo` (op-id string) and
   undo via `restore_operation(op_before)`, uniformly. Name ops `gitman:<intent>` so `undo --list`
   reads from `ws.operations()` (pyjutsu leaves `tags` empty but keeps your description verbatim).
6. **Capture a whole `status` from ONE frozen `RepoView`** (`view = fresh_view()`, then
   `view.bookmarks()/log()/diff_stat()/conflicts()/operations()`) for consistency + speed.
7. **Lane published?** = a `Bookmark` row with `remote not in (None, "git")`. Local lane =
   `remote is None`. (`ws.bookmarks()` replaces the `--all-remotes` parsing hack.)
8. **Tags:** jj-lib is read-only on tags and jj has no annotated-tag creation — keep a ~30-line
   `tags.py` git subprocess (the only retained subprocess).

## Critical correctness items (the things most likely to bite)

- **Anchor `.gitman/` (lock + undo checkpoint) at the SHARED repo root**, not
  `resolve_repo_root()` — in a secondary workspace the latter is the workspace dir, so today's lock
  doesn't serialize parallel agents. Fix this as part of `session.py`.
- **Explicit snapshot** before working-copy-reflecting reads (item 1).
- **Trunk-unchanged postcondition** (the trunk-protection decision).
- **Conflicts are commits, not exceptions** (item 3).
- **Remote-branch delete on `land`:** `git_push(remote, lane, delete=True)` needs the remote-tracking
  ref present — order the deletion before dropping local tracking.

## Working rules

- **Everything runs inside devenv.** Batch commands: `devenv shell -- bash -c '...'`. Building
  pyjutsu the first time is ~6 min (jj-lib); it caches after.
- **Dogfood:** route gitman's own version control through `gitman` once each milestone is green;
  never raw `jj`/`git`.
- **Keep the split sacred:** primitives in pyjutsu, policy in gitman. Don't push lane/canonicity
  concepts into pyjutsu.
- **Don't regress the contract:** report formats, exit codes (0/1/2/3), and the `--json` shape are
  user-facing — keep them byte-stable where possible; flag any unavoidable change.
- **No AI-generated attribution** in commits/PRs/docs.
- Work **milestone by milestone** (below); after each, run `devenv shell -- bash -c 'gitman:lint &&
  gitman:test'` (or `devenv test`) and dogfood the milestone's gate before moving on.

## Milestones (from MIGRATION_PLAN_v2.md §10 — follow it for detail)

- **MP0 — wiring + read path.** gitman devenv builds pyjutsu (sibling); add `session.py` (shared-root
  resolution + snapshot/view policy); rewrite `state.py` over one `fresh_view()`; rewrite `status` +
  `doctor`. Delete `templates.py` + jj read/parse + git numstat/rev_count as they fall out.
  *Gate:* `gitman status`/`doctor` green on gitman's own repo + integration reads pass.
- **MP1 — mutating intents + invariants.** Rewrite `invariants.py` (`canonical_tx`: shared-root lock
  + snapshot-first + `auto_snapshot=False` + canonical/trunk-unchanged postcondition); migrate
  `start`/`save`/`land`/`abandon`/`sync`; `undo` over the op-log; typed errors replace string
  matching. *Gate:* full lane lifecycle dogfood + conflict-via-`has_conflict` + stale handling + undo
  round-trips.
- **MP2 — publish, version, release, init, reconcile.** `publish` → `ws.git_push`; `version`/`release`
  over pyjutsu tx + `tags.py`; `init` trunk bookmark via tx; `reconcile` via `view.log` + tx +
  `update_stale`. Delete the rest of `git.py`.
- **MP3 — delete & polish.** Remove `jj.py`, `templates.py`, dead tests/fixtures
  (`test_parse_jj.py`, `test_parse_git.py`, `tests/fixtures/`, `scripts/gen_fixtures.py`); update
  `CLAUDE.md`/`README`/concept; drop the jj pin; re-dogfood end-to-end (a real
  publish→land→release against the remote); `devenv test` green; cut a clean release.

## Start here

1. Read `MIGRATION_PLAN_v2.md` + `DECISION_LOG.md` and skim the current `src/gitman/` + pyjutsu API.
2. Build pyjutsu (`cd ../Pyjutsu && devenv shell -- maturin develop --release`) and confirm
   `import pyjutsu` reports `JJ_VERSION 0.38.0`.
3. Begin **MP0**. Show me the devenv wiring + `session.py` design before deleting any read-path code,
   then proceed through the gate. Stop at each milestone gate for a quick check-in.
