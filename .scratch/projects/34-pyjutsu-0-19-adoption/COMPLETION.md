# Project 34 — completion record

The refactor of `02-REFACTOR-GUIDE.md` is done. Engine: **pyjutsu 0.20.0 / jj-lib 0.44.0**.

Date: 2026-08-27.

---

## Lanes

Each lane landed on trunk and pushed as its own commit.

| Lane | What landed | Commit |
|---|---|---|
| 1 — deprecated git aliases | `core.has_remote()` consolidates eleven remote gates; three docstrings corrected. The `ws.git.*` renames themselves were already in `04578a2`. | `78aa82d` |
| 2 — workspace parent | `add_workspace(..., revisions="root()")`, docstring rewritten, regression test over a flat and a `/`-path lane. | `0342016` |
| 3 — release tags | **Annotated** kept, written through `ws.git.create_tag`; module docstring rewritten; test pins the object kind, the message, and the `tags(exact:)` read. | `f15dad6` |
| 4 — `PartialWorkspaceError` | Explicit branch before `WorkspaceError`, passing the recovery action through; `_start_workspace` forgets a surviving registration; two tests. | `5b8e9b2` |
| 5 — garbage collection | `ws.gc()` on the `init --colocate` adopt path and at the head of `reconcile`, default cutoff, best-effort; `core.py:130` comment rewritten; three tests. | `060fc57` |
| 6 — immutability | `core.explain_immutable` names the protection that fired; `abandon` and `reconcile` route through it; audit table; decisions 6c and 6d recorded; three tests. | `2e5c285` |
| 7 — glob default | Classification table; no code change needed; three tests (metacharacter rejection, stacked-lane round trip, exact tag lookup). | `7146b30` |
| 8 — version prose | Six files corrected to pyjutsu 0.20 / jj-lib 0.44.0; the `tags.py` subprocess claim removed; `AGENTS.md` gained the four capability changes. | `ccb2deb` |
| 9 — new surface | Proposals only, per the guide. No intent added. | this commit |

Deliverables in this directory: [`LANE-6-IMMUTABILITY-AUDIT.md`](LANE-6-IMMUTABILITY-AUDIT.md),
[`LANE-7-REVSETS.md`](LANE-7-REVSETS.md),
[`LANE-9-NEW-SURFACE-PROPOSALS.md`](LANE-9-NEW-SURFACE-PROPOSALS.md).

---

## Decisions

| Decision | Outcome | Where recorded |
|---|---|---|
| pyjutsu version to build (`01`, step C) | 0.20.0. Owner-approved before this work. | `BASELINE.md` §1 |
| Lightweight or annotated release tags (lane 3) | **Annotated.** The release message is part of a published artifact. | `release.py` module docstring + `test_release_tag_is_annotated_and_reads_back` |
| Immutable-commit policy (lane 6c) | **Refuse everywhere**, with a report naming the protection. `ignore_immutable=True` appears nowhere in `src/gitman/`, enforced by a token scan. | `LANE-6-IMMUTABILITY-AUDIT.md` §5 |
| Pin `immutable_heads()` in jj config (lane 6d) | **No.** Gitman writes no jj configuration. The consequence (a non-standard trunk name gets no `trunk()` protection) is documented. | `LANE-6-IMMUTABILITY-AUDIT.md` §6 |

---

## Definition of done

- [x] `ruff check src tests` clean.
- [x] `python -W error::DeprecationWarning -m pytest -q` — **278 passed**, zero deprecations.
- [x] `gitman doctor` — HEALTHY, pyjutsu 0.20.0 (jj-lib 0.44.0), all eight checks ok.
- [x] The guide-1 G5 live probe reports a canonical repository at every stage, `start --workspace`
      and `start T/api --workspace` included.
- [x] Every failure in `BASELINE.md` fixed. (All 16 were already fixed in `04578a2`; this project
      added the design work the guide asked for on top.)
- [x] Three DECISION points resolved and recorded.
- [x] Lane 6 audit table committed.
- [x] `grep` for `0.15` / `0.38` / `0.42` finds no stale pyjutsu or jj-lib claim. Two dated
      historical statements remain in `GITMAN_CONCEPT.md` (the 2026-06-15 jj 0.38 spike, and
      pyjutsu 0.15.0 adding hooks); both are accurate as history and are followed by the current
      number.
- [x] Every lane has a test proving its behaviour. Lane 8 is prose only and is covered by the
      grep in this list.
- [x] All lanes landed on trunk and pushed.

Test count: 260 at the baseline → **278**.

---

## Notes for the next agent

1. **The baseline's surprises were right and the guide's predictions were not, twice.** Lane 2's
   real defect was a missing parent directory, not a changed default parent; lane 4, 5, and 7
   produced no live failure at all. Their work was still done, because a lane with no failure today
   is a lane whose behaviour is now pinned by a test.
2. **`gc` is a no-op on a young repository.** Its default cutoff preserves objects newer than two
   weeks, so a test cannot assert keep-ref removal on a repo it just built. The lane 5 tests assert
   the call happens with the default cutoff and that the intents survive it — the honest assertion.
3. **A fractal-name ref written out of band is unretirable through pyjutsu** (the reflog D/F limit
   recorded in `BASELINE.md` §9). Gitman's "report stale, point at `reconcile`" stance is the only
   safe option there.
