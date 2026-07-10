# 21 — Tier 2 kickoff prompt (sanctioned trunk↔origin verbs + retire `adopt`)

**Date:** 2026-07-10
**Status:** KICKOFF — hand this to a clean session to plan+build Tier 2.
**Prereq:** Tier 1 (project 20) is landed to local trunk (`main`, unpushed twin, `4 ahead / 1 behind
origin`). The content relation primitive Tier 2 reuses lives in `state._trunk_content_relation` /
`_merge_tree_relation`.

---

Plan and build Tier 2 of gitman's single local-authored trunk model — the sanctioned trunk↔origin
verbs (`remote add`, `push`, `pull`, `untrack`) and the retirement of `adopt`. This is the tier that
finally lets gitman push its own trunk and migrate the re-hash twin. Do analysis → PLAN → build →
verify; write the PLAN to `.scratch/projects/21-trunk-model-tier2/PLAN.md` and confirm scope before
touching src/.

READ FIRST (authority, in order):
- `.scratch/projects/20-trunk-model-tier1/PLAN.md` — what Tier 1 just BUILT (the foundation). KEY: the
  content relation already exists — `state._trunk_content_relation` + `_merge_tree_relation` (read-only
  `git merge-tree --write-tree`, returns forge_has_new/local_has_new). REUSE it as the push/pull gate;
  do NOT rebuild the content question. `TrunkRef` has `remote`+`relation`. `@`-never-on-trunk +
  dirty-`@` guard are scoped to `land`; `sync_colocated()` runs in the guard tail.
- `.scratch/projects/19-trunk-model-deep-dive/ANALYSIS.md` — the authority. Read the ADDENDUM (single
  model, `adopt` DELETED), §1.1 (the `invariants.py` postcondition exemption — Tier 2 collapses
  `intent not in ("land","adopt")`), §1.2 + §1.5 (the ⟲ force-with-lease corrections — CRITICAL for
  push), and the Tier 2 line in the leverage-ordered path + the "verb name" open question.
- `.scratch/projects/16-local-authored-trunk-model/DECISION.md` — the reframed intent table (`pull` /
  `push-trunk` / retire `adopt`), content-aware forge relation, push-safety "option D", RC map.
- `Pyjutsu/.scratch/projects/13-gitman-trunk-model-bindings/OVERVIEW.md` — the "Shipped in 0.10.0"
  banner: `untrack_paths` (real), `sync_colocated`, and P1 (force-with-lease is already the ONLY push
  mode). Read the `untrack_paths` + `git_push` docstrings in the installed pyjutsu.
- Field reports Tier 2 closes: `.scratch/projects/13-raw-git-push-trunk-desync/ISSUE.md` (raw-push
  desync + the 5 recs), `.scratch/projects/15-.../ISSUES.md` (RC1 force, RC4/RC5 untrack),
  `.scratch/projects/18-bootstrap-remote-first-trunk-push/ISSUE.md` (bootstrap remote+push),
  `.scratch/projects/07-forge-pr-trunk-reconcile/` (adopt's logic, which folds into `pull`).
- `CLAUDE.md` — lane model + invariants I1–I5 + transactional-rollback style.

HEED THESE ⟲ CORRECTIONS (they change the design):
- pyjutsu `git_push` is ALREADY an unconditional force-with-lease (lease = remote-tracking ref; jj-lib
  has no FF guard). Therefore:
  * Everyday `push` strict-FF is a **gitman POLICY**, not engine-enforced — gitman must content-check
    (reuse `_trunk_content_relation`: `forge-ahead`/`diverged` ⟹ refuse → `pull`) and refuse a non-FF
    ITSELF. The engine will happily lease-force a non-descendant.
  * `push --reset-origin` = the SAME `ws.git_push(remote, trunk)` call with gitman's FF/content gate
    LIFTED. No raw git, no flag, no new binding. The lease still refuses to clobber out-of-band work.

TIER 2 SCOPE (exactly these; resolve the open decisions in the PLAN):
1. `remote add <url>` — in-process `ws.add_remote(name, url)`; never touches git HEAD (sidesteps the
   detached-HEAD `gh` trap, 18-RC2).
2. `push` (trunk) — content-gated strict-FF: `in-sync`/`local-ahead` → FF-push the `<trunk>` bookmark
   via `ws.git_push`; `forge-ahead`/`diverged` → refuse → `pull`. Plus `push --reset-origin` — same
   call, gate lifted (one-shot twin migration). Guard a dirty trunk-`@` before pushing (extend Tier 1's
   guard). Fixes 13-RC1 + all of 18.
3. `pull` — fetch origin; content-aware: FF local trunk when local has no un-pushed lands, else rebase
   un-pushed lands/lanes onto the newer origin trunk; content-retire forge-merged lanes. Absorbs
   `adopt`'s fetch+advance+survivor-rebase+content-retire (`do_adopt`, `_adopt_dry_run`,
   `_reconcile_lane_against_adopted_trunk`, `_retire_lane`, `_trunk_diverged_no_ff`, `_SurvivorConflict`).
   Must repark `@` onto the advanced trunk (reuse land's repark / `update_stale`) — pull advances trunk,
   so extend the `@`-never-on-trunk invariant + the postcondition trunk-moved exemption to `pull`.
   Never triggered by re-hash twins (content check).
4. `untrack <path>` — `ws.untrack_paths` + ensure `.gitignore` so the next snapshot doesn't re-add;
   `init`/`status` warn on tracked-but-gitignored paths. 15-RC4/RC5.
5. Delete `adopt` as a verb (logic folded into `pull`). Decide: outright removal (project 19) vs a
   deprecated alias → `pull` for one release (DECISION 16). Collapse the `invariants` exemptions.

KEY CODE: `cli.py` (new Typer intents; remove/alias `adopt`); `core.py` (`do_adopt`+helpers →
`do_pull`; new `do_push`/`do_remote_add`/`do_untrack`; `pick_remote`; note `do_land` catches
GitmanError→BLOCKED result rather than raising — mirror that for multi-step intents); `state.py`
(`_trunk_content_relation`/`_merge_tree_relation` REUSE + tracked-ignored warning); `invariants.py`
(`_postcondition` trunk-moved + `@`-invariant exemptions → land+pull; dirty-`@` guard → +push);
`session.py` (pyjutsu boundary: `git_push`/`git_fetch`/`add_remote`/`untrack_paths`/`update_stale`);
`tags.py` (`remote_default_branch` raw-git — optional in-process move); SKILL.md/docs (minimal update
for the new verbs; full rewrite is Tier 3).

RESOLVE IN THE PLAN (open decisions): (a) verb name `push` vs `push-trunk` given `publish` owns lanes
(19 leans `push`); (b) `adopt` deleted outright vs deprecated alias; (c) how much SKILL/doc rewrite is
Tier 2 vs deferred to Tier 3.

DOGFOOD / MIGRATION TARGET: gitman's own `main` is `4 ahead / 1 behind origin` — a re-hash twin
carrying the LANDED Tier 1 work, currently UNPUSHED. Tier 2's `push --reset-origin` is exactly the
migration this whole model was built for: content-check confirms local ⊇ origin (forge_has_new=False),
then one lease-force push makes origin == local; afterward `status` reads `in-sync` and everyday `push`
is a clean FF forever. Do this deliberately (it rewrites origin/main once) — and only after the verbs
are built, tested, and you've confirmed the content gate says local-ahead.

VERIFY: `devenv shell -- bash -c 'cd "$DEVENV_ROOT" && "$DEVENV_STATE"/venv/bin/ruff check src tests &&
"$DEVENV_STATE"/venv/bin/pytest -q'` (note: `gitman:lint`/`gitman:test` are devenv scripts NOT on PATH
non-interactively; run the venv binaries directly, or `devenv test`). Add regression tests against a
bare origin: push FF happy path; push refuses non-FF (forge-ahead/diverged) → pull; `push
--reset-origin` migrates a content-equal twin (origin ends at local SHA) and a stale-lease push is
rejected; pull FF fast-path; pull rebases un-pushed lands onto moved origin; pull content-retires a
forge-merged lane; untrack removes from tree + leaves file on disk + not re-added after snapshot +
check-ignore truthful; remote add bootstraps; `@`-repark + dirty-`@` guard hold for pull/push. Tests
that reuse a `Workspace` handle across `do_*` calls hit concurrent-checkout — load a FRESH workspace.
Use /verify to drive push/pull end-to-end against a bare origin.

GROUND RULES: route VC through gitman; in-repo cmds inside devenv; jj-lib in-process via pyjutsu 0.10.0
(no jj CLI, no `-T` templates); branch (lane) first; commit on lanes regularly. Write the PLAN and
confirm scope before building. No AI-authorship trailers.
