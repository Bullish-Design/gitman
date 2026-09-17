# Stage 4d session write-up: what landed, and a push-safety bug it surfaced

**Date:** 2026-09-17 · **Lane:** `issue44-stage4d-export-on-demand` (already landed + pushed)
**Status of this note:** written to disk but **not yet committed** — the session that wrote it
paused all further git/jj mutation after finding evidence of a concurrent session racing on this
same working directory (see §4). A future session should commit this file as part of its own work,
not assume it's already tracked.

This note has two parts: (1) what was done and landed this session (pyjutsu 0.22.0 confirmation,
stage 4d implementation), and (2) a serious, previously-unknown bug it surfaced while landing,
which needs its own investigation before anyone runs `gitman push`/`gitman publish` again with
confidence.

---

## 1. Pyjutsu 0.22.0 — confirmed correct, still unpublished

A prior turn handed off a kickoff prompt to add `GitIndexEntry.intent_to_add` to pyjutsu (needed
for issue 44 stage 4e). That work came back as pyjutsu commit `5700f6e` ("feat: add intent_to_add
to GitIndexEntry, bump to 0.22.0"), landed on pyjutsu's own `main`. This session verified it in
full: the Rust read (`gix::index::entry::Flags::INTENT_TO_ADD`, read-only, correct boundary), the
pydantic model field + docstring, the golden field list, and a real test (`git add -N` → flag is
`True`). No tweaks needed.

**It is not published.** `gh release list` on the pyjutsu repo still tops out at `v0.21.1`.
Publishing needs `pyjutsu:wheel` + `pyjutsu:publish` (cuts a tag + sdist only) + a separate
`vendomat publish pyjutsu` for the actual wheel — and `pyjutsu:publish` refuses on a dirty working
tree, which the pyjutsu repo has (unrelated, pre-existing `devenv.lock`/`devenv.nix`/`devenv.yaml`
changes). Given the complexity and unfamiliar `vendomat` step, the user chose to skip publishing
for this session and work on stage 4d instead (which doesn't depend on it). **4e is still blocked**
on this: `doctor` cannot classify the issue-41 `git add -N` state from porcelain alone until
gitman's own `[tool.uv.sources]` pin can move to a real 0.22.0 release.

## 2. Stage 4d — export on demand — implemented, tested, landed

Full detail is in `STAGE_4_PROGRESS.md` (already updated in this session) — summary here:

- `invariants.canonical_tx`/`canonical_guard` gained `export: bool = False`. Only `do_publish` and
  `do_push` pass `export=True`. Every other mutating intent (`start`, `save`, `switch`, `split`,
  `shape`, `land`, `sync`, `pull`, `untrack`, `release`, `version`) no longer touches the colocated
  `.git` — refs catch up at the next `publish`/`push`, or a `status` read's best-effort
  `mirror_snapshot_refs`.
- Confirmed guide item 2 ("stop gating on ref state") was already satisfied by stage 4c —
  `ref-mismatched`/`ref-lagging` both have empty `blocks`.
- **Deliberately did NOT attempt guide item 3** ("total ref encoding" — wiring stage 4a's
  `ref_for_lane`/`lane_for_ref`). Traced jj-lib 0.44.0's `git.rs`: `to_git_ref_name` is an
  unconditional `format!("refs/heads/{name}")` off the jj bookmark's own name, with no rename hook,
  and pyjutsu's `git_export()` binding wraps the all-or-nothing `export_refs`, not the filterable
  `export_some_refs` jj-lib also exposes. Making a fractal lane like `T/api` export without a D/F
  collision against a live `T` needs either a new pyjutsu capability or renaming the underlying jj
  bookmark itself everywhere gitman creates/reads/resolves lanes — its own large/high-risk project.
  Recorded as deferred stage **4f** in `STAGE_4_PROGRESS.md`.
- Fixed 6 tests broken by the behavior change (3 anticipated by research, 3 found only by actually
  running the suite — raw `git status`/`ls-files` checks a grep-based pre-scan missed). All fixes
  followed the codebase's existing idiom: an explicit `ws.git_export()`/`sync_colocated()` in the
  test right before a raw-git assertion.
- 377 tests passing, `ruff check`/`format --check` clean (same pre-existing `init.py` exception as
  before).
- Landed via `gitman start` → `gitman save` → `gitman land`, all clean.

## 3. What went wrong while pushing — a real, pre-existing bug

> **Correction (2026-09-17, follow-up session).** The bug in §3 is real and is now fixed, but
> §3.3's *mechanism* is wrong. It theorised a stale `main@origin`. `main@origin` was **accurate**
> at push time — the gate read correct data and approved anyway, because it asks a *content*
> question, not an ancestry one. The condition was still reproducible read-only in the repo, and is
> re-derived from live state in
> `.scratch/projects/45-irreversible-push-inside-rollback-guard/ISSUE.md`. Do not implement §6.3's
> option (a) ("re-fetch before the push") — it fixes a cause that was not there. §6.4 is answered
> in that project's `RESOLUTION.md`.


Pushing the landed lane hit a rejection: `origin/main` had moved since gitman's last known
position. Investigating *why* surfaced a genuine correctness bug, not something to paper over.

### 3.1 The external state that triggered it

Another actor had committed directly to this repo's colocated `.git` with **raw `git commit`**
(bypassing gitman/jj entirely): commit `295f0ad "chore: bump pyjutsu to 0.22.0"`, editing
`pyproject.toml`/`uv.lock` to point at the pyjutsu 0.22.0 release URL — the same one confirmed
unpublished in §1. `git log`'s author line reads `Bullish-Design <bullishdesignllc@gmail.com>`
(the same account driving this session) with `Co-Authored-By: Claude Sonnet 5`, timestamped
`12:33:37`, about 10 minutes before this session's own stage-4d land. `ListAgents` at the time
showed several other `gitman-*`-named peer sessions active. **Evidence strongly indicates another
Claude Code session is working in this exact same directory concurrently** (see §4) — not a
separate clone.

This surfaced correctly as a `ref-mismatched` (adopt-direction) anomaly — `gitman status` reported
DESYNCHRONIZED, naming that git held history jj hadn't imported. That detection is working exactly
as stage 4c intended. The trouble started with what came next.

### 3.2 The sequence (from the jj op log, exact timestamps)

```
12:42:52  gitman:start                          (this session's stage-4d lane)
12:42:58  gitman:save
12:43:01  gitman:land
12:43:06  restore to operation ...               (FIRST `gitman push` — remote rejected: "stale info")
12:43:54  fetch from git remote 'origin'          (user-approved `gitman pull`)
12:43:54  gitman:pull-keep-local
12:44:05  push to git remote 'origin'             (SECOND `gitman push` attempt)
12:44:05  import git refs
12:44:05  export git refs
12:44:05  restore to operation ...               (`gitman push` reports BLOCKED: stray-change)
```

The second `gitman push`'s own report said: `reverted: change(s) ... belong to no lane; no change
applied.` and `note: nothing changed on the remote.`

**That note is false.** The op log shows `push to git remote 'origin'` completing *before* `import
git refs`, `export git refs`, and the final `restore to operation` that undid local state. The
network push had already succeeded when the postcondition found a newly-adopted stray commit and
rolled back — but `restore_operation(op_before)` only undoes *local* jj state. It cannot retract an
already-sent push.

### 3.3 Worse: it was a silent non-fast-forward

`do_push`'s own docstring states policy: "pyjutsu's `git_push` is an unconditional force-with-lease,
so gitman itself refuses a non-FF → `pull`" (checked via `_trunk_content_relation` before calling
`git_push`, gated on `relation == "local-ahead"`). No `--reset-origin` flag was passed.

Despite that, the push that succeeded (`d7484e7`, "feat: issue 44 stage 4d...") is **not a
descendant of `295f0ad`** — confirmed directly:

```
$ git rev-list --parents -n1 d7484e7
d7484e7c... 2c0758a603eb...          # sole parent is 2c0758a, NOT 295f0ad
$ git merge-base --is-ancestor 295f0ad d7484e7 && echo YES || echo NOT
NOT
```

So gitman's own FF-refusal gate approved a push that, against the *real* remote, was not a
fast-forward. The likely mechanism: the FIRST push attempt's rollback (12:43:06) reverted jj's
`main@origin` bookmark to a position *older than* `295f0ad` (jj never actually saw `295f0ad` — it
was written by raw git, not through jj). When the SECOND push ran its `_trunk_content_relation`
gate, it compared local trunk against that stale `main@origin` and saw a clean `local-ahead` —
satisfying the policy check — while the *actual* remote had already moved past that point. The
underlying `git_push` force-with-lease then succeeded (or the lease check itself was against a
stale expectation too), overwriting `origin/main` with a history that doesn't contain `295f0ad`.

**Net outcome, checked and confirmed benign this time:** no content was actually lost.
`295f0ad`'s pyjutsu-pin-bump content is present in `d7484e7`'s diff (`gitman pull`'s rebase folded
it in while resolving the conflict before the push). The `295f0ad` commit object itself is still
present in the local object store (`git cat-file -t 295f0ad` → `commit`), just no longer reachable
from any ref. But this was luck-adjacent — a genuine divergent edit instead of a folded-in one
could have been silently dropped from `origin/main`'s history by the same mechanism.

### 3.4 Is this bug new (from stage 4d) or pre-existing?

**Pre-existing.** `do_publish` has the identical shape — `session.ws.git_push(...)` called inside
`with canonical_guard(session, "publish", export=True) as canon:` — so it has the same hazard.
Both call sites have *always* called `git_push` inside the guard body, before the guard's own
`except Exception: restore_operation(op_before); raise`. That ordering problem is not something
stage 4d introduced. What stage 4d changed is that `_postcondition` now runs against freshly
exported ref state specifically at push/publish time (since export now happens exactly there,
not after every prior intent too) — which may make a stray introduced concurrently with a push
easier to *notice* via the postcondition, but the "can't undo a completed network push" gap itself
predates this session's change entirely.

## 4. Evidence of a live concurrent session on this exact directory

Two things converged to suggest this isn't a stale-clone problem but active, real-time concurrent
use of `/home/andrew/Documents/Projects/gitman` by another agent session:

- `ListAgents` showed peer sessions named `gitman-62`, `gitman-22`, `gitman-84`, `gitman-6f`,
  `gitman-a9`, `gitman-93`, and `pyjutsu-b3`, several started within the hour. No sibling directory
  (`gitman-2`, a worktree, etc.) exists next to this repo — `ls ..  | grep -i gitman` finds only
  `gitman` itself.
- Two back-to-back **read-only** `git reflog show refs/heads/main` calls, moments apart with *no
  mutating command from this session in between*, returned different newest-entry (`@{0}`) values
  — one showing `295f0ad` as the latest local ref update, the next `git rev-parse` showing
  `d7484e7`. That kind of inconsistency between two immediately-sequential reads is a strong signal
  of another process writing to the same `.git`/`.jj` state concurrently.

This session stopped all further git/jj-mutating action at that point, per the "don't act on a
system you can't currently reason about safely" principle — not because of a specific new finding
of harm, but because further commands' effects couldn't be predicted with another live writer in
the same directory.

## 5. Current known state (as of when this session stopped acting)

- Local trunk (`main`) and `origin/main` both resolved to `d7484e7` (content-identical, confirmed
  by hash).
- `gitman doctor` reported HEALTHY, `colocated-refs` in sync.
- `gitman status` reported `CANONICAL`, but with a confusing `(1 ahead origin)` — traced to jj's
  own `main@origin` bookmark still pointing at the stale `295f0ad`-adjacent position (a direct
  pyjutsu query confirmed `main` and `main@origin` have different `commit_id`s despite the real
  remote and local trunk matching). `gitman pull --dry-run` correctly reported "already current"
  (it does its own fresh fetch+relation check), while `gitman status`'s cached ancestry-based
  relation did not — these two code paths can disagree when `main@origin`'s bookmark is stale but
  content-caught-up, which is itself worth understanding precisely in a follow-up.
- The pre-existing, unrelated `loci-adoption-fixes` lane is still `CONFLICT (not blocked)`, 50
  behind trunk — untouched by anything in this session; not this session's responsibility.
- No other branch/tag on `origin` was touched (`git ls-remote origin` checked — `main` was the only
  ref this session's push affected).

---

## 6. What a follow-up session needs to do

1. **Re-verify current state from scratch, first** — do not trust anything above as still true.
   Another session may have changed things further since this was written. Start with
   `gitman status`, `gitman doctor`, `ListAgents` (check who else is active on this repo right
   now), and `git fetch origin && git log --oneline origin/main -10` before touching anything.
2. **If another session appears actively live on this same directory**, coordinate before running
   any mutating `gitman`/`git`/`jj` command — this session's incident happened specifically because
   two writers touched the same repo without coordination.
3. **Investigate and fix the `do_push`/`do_publish` ordering bug** (§3): a network push inside
   `canonical_guard`'s body is not safe against the guard's own exception-triggered
   `restore_operation`. Needs a real design decision, not a quick patch — options include:
   moving the FF/relation check to be re-validated immediately before the network call inside the
   lock (closing the stale-`main@origin` window), refusing to characterize a post-push failure as
   "nothing changed on the remote" once `git_push` has actually run, or restructuring so
   `_postcondition`'s anomaly check happens *before* the irreversible network call wherever
   possible.
4. **Decide what to do about the `295f0ad`/`d7484e7` history**, if anything — the content is safe,
   but if the other session's local view still believes `main` is at `295f0ad`, their next
   `gitman`/`git` operation against `origin` may surprise them. Worth a heads-up if that session
   can be identified/reached.
5. **This file itself is uncommitted** — land it (as part of the fix work, or standalone) once the
   above is sorted out.
