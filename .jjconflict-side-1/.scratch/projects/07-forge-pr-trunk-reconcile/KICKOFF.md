# KICKOFF PROMPT — build `gitman adopt`

> Paste everything below the line into a fresh gitman session to start the work.
> It is self-contained: it points at the issue + plan, states the resolved design
> decisions, and gives an explicit first-step / validation order so the new session
> doesn't re-derive what's already settled.

---

We're implementing **`gitman adopt`** — a first-class command to adopt a forge-merged
trunk (the `publish → PR → click-Merge → local trunk stranded behind origin/main` gap).

**Read first, in order:**
1. `.scratch/projects/07-forge-pr-trunk-reconcile/ISSUE.md` — the problem, root cause in
   code, the two "sharp edges", and acceptance criteria (§7).
2. `.scratch/projects/07-forge-pr-trunk-reconcile/PLAN.md` — the full implementation plan
   I'm asking you to execute. Follow it; deviate only with a stated reason.

**Project rules (non-negotiable):**
- Everything runs inside devenv: `devenv shell -- bash -c 'gitman:lint && gitman:test'`
  (or `devenv test`). Never bare `uv`/`python`/`pytest`.
- Dogfood version control through `gitman` — never raw `jj`/`git` (that breaks canonicity).
  `git` is only used by `tags.py`.
- jj-lib is embedded via pyjutsu (`../Pyjutsu`); there is no `jj` CLI and no `-T` templates.
  Reads go through `Session.view()`/`fresh_view()`; mutations through `ws.transaction(...)`.
- No AI-authorship trailers in commits/PRs/docs. Only commit/push when I ask; branch first.

**Design decisions already made (do NOT re-litigate):**
- Command surface = a **new top-level `gitman adopt`** verb (not `sync --adopt-remote`,
  not `land --remote`). Flags: `--force` (allow non-FF / discard un-pushed local trunk),
  `--dry-run` (report plan, no mutation).
- Forge-merged lanes **auto-retire** and are reported per-lane, with `gitman undo` support.
- Detection of "already forge-merged" is **content-based** via emptiness-after-rebase
  (pyjutsu has no patch-id) — see PLAN §1; must work for squash / merge-commit / rebase.
- `adopt` becomes the **second trunk-advancing intent** (I5 widens to `land` or `adopt`);
  the only invariants change is the one-line `_postcondition` exemption in PLAN §2.

**Build order (PLAN §7) — three slices, each lint+test green before the next:**
1. **PR-1**: status honesty (`origin/<trunk>` ahead/behind in `capture_state`/status) +
   make `do_sync` resilient to a server-deleted remote lane branch (sharp edge #1).
2. **PR-2**: the `do_adopt` core + `_postcondition` one-liner + content-merged detection +
   CLI wiring + `--force`/`--dry-run`.
3. **PR-3**: docs/concept/skill updates; deprecate the §4 manual "reconcile dance".

**Validate these unknowns FIRST (PLAN §8), before writing the main logic — they change the
shape of `do_adopt`:**
- Does `session.view()` reflect an in-flight `tx.rebase` so the post-rebase emptiness check
  works inside one transaction? If not, use two tx blocks under the same `canonical_guard`.
- Does pyjutsu `git_fetch` prune a dangling `<lane>@origin` row after the remote branch is
  deleted server-side?
- Is `tx.rebase(lane, onto=trunk, mode="branch")` a clean no-op when the lane is already an
  ancestor of trunk (merge-commit case)?
Write a tiny throwaway test (or use the `tests/test_colocated_git_sync.py` two-repo harness)
to answer each, then proceed.

**Definition of done:** all PLAN §9 acceptance criteria pass, including a regression test that
reproduces the squash-merge scenario (lane `m0`, 2 commits → squash-merged on origin as a new
SHA → `gitman adopt` → CANONICAL · 0 lanes, local `trunk == origin/trunk`, `gitman doctor`
HEALTHY), and `gitman sync` no longer wedges on a server-deleted lane branch.

Start with PR-1. Show me your plan for it (files + test names) before you write code, then
proceed once I confirm.
