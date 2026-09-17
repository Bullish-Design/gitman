# Kickoff prompt — Stages 3e and 3f: repair hygiene, then registry-driven repair

Paste everything below into a fresh session.

---

Work on gitman issue 44, **Stage 3e** (repair hygiene) and then **Stage 3f** (the registry
dispatches the repair). Both are written up in full in
`.scratch/projects/44-report-integrity-and-intent-architecture/IMPLEMENTATION_GUIDE.md` §3.12 and
§3.13. Read those two sections before you write anything — they carry the decisions, the traps, and
the "must not change" list. This prompt is the framing, not the spec.

## Where things stand

Stages 3a–3d are landed and pushed. Trunk is `43ef935`. `gitman status` is CANONICAL. The suite is
**343 passing**; `ruff check src tests` is clean; `ruff format --check` flags only
`src/gitman/init.py`, which is pre-existing and not yours.

Stage 3d gave `lane-divergent` a content-aware repair: `state.lane_twin_relation` classifies a
published lane against its own `<lane>@<remote>` twin, `reconcile` resolves the three relations
where one side contains the other, and `gitman reconcile --keep local|origin` is the operator's
choice on a genuine fork. `REGISTRY["lane-divergent"].repair` is now `"reconcile"`.

A review of that work found one latent defect and two pieces of friction (3e), and one
architectural gap (3f). Nothing below is a bug report against a passing test — the 3d tests are
right and must keep passing unchanged.

## Why there are two stages, in this order

3e is small, clearly right, and touches the code 3f rewrites. Landing 3e first keeps 3f a pure
refactor with no behaviour change to argue about. **Land them as separate lanes.** Do not merge
them into one.

## Stage 3e — three fixes (guide §3.12)

1. **`adopted-<commit>` is minted four ways with three collision policies** — and the site stage 3d
   added (`reconcile.py:94`) has no collision check at all. Measured: `tx.create_bookmark` raises
   `PyjutsuError: bookmark '<name>' already exists`, which aborts and rolls back the whole recovery
   verb. Narrow trigger, real defect, and the inconsistency is the actual problem. One minter in
   `lanes.py`; all four sites route through it.
2. **`_resolve_lane_twin` runs a full `capture_state` per twin** (`reconcile.py:107`) to answer a
   one-lane question, duplicating the capture `do_reconcile` already does at the end. Replace with
   one re-survey after the loop — cheaper *and* a truer postcondition.
3. **Two type gaps**: `TrunkRef.relation` and `LaneTwin.relation` spell the same four-word
   vocabulary two ways with two conventions for "unknown"; `do_reconcile`'s `keep` takes any
   string and silently degrades a bad one. Declare `ContentRelation` and `KeepSide` once.

The guide gives the exact signatures and the one thing to check before tightening
`TrunkRef.relation`.

## Stage 3f — make the registry load-bearing (guide §3.13)

Today `REGISTRY[kind].repair` is an assertion *about* the world; nothing reads it. `do_reconcile`
hand-maintains a survey tuple, an early-return `and not X` chain, and a branch per shape — five of
each. Adding a kind means editing three places, and nothing fails if you forget one. Issue 42 §4a
named this pattern as the thing to stop repeating, and stage 3d repeated it.

Build `src/gitman/repairs.py`: a table from kind to repair callable, with an **import-time,
two-way assertion** that `REGISTRY` and `REPAIRS` agree. That turns "detected but unfixable" from a
runtime livelock into an import error — the same trick `anomalies.py:112` already plays.

**Read §3.13.2's two traps before designing.** Both will bite mid-refactor if you meet them by
surprise:

- The stray subject carries a **change_id**, but the stray loop must target by **commit_id**
  (issue 06 §G2). A dispatch that feeds each repair its subjects would reintroduce that bug. The
  anomaly list picks *which* repairs run; each repair keeps its own precise survey.
- **`ANOMALY_ORDER` is a prose order, not a repair order.** Colocated-ref healing must run first
  (31-RC6). `REPAIRS` needs its own declared order, and the reason written down where it is
  declared.

§3.13.4 lists what must not change — six landed fixes with issue numbers. Read it. §3.13.5 gives a
five-step order of work where steps 1–2 land green on their own.

## Scope boundaries

- Two lanes, normal gitman hygiene. Verify with
  `devenv shell -- bash -c 'ruff check src tests && python -m pytest tests -q'`, or `devenv test`.
- **3f is a refactor.** Every existing test passes *unchanged*. If a 3d test needs editing to make
  3f pass, stop — the refactor changed behaviour and that is the finding, not the edit.
- Do not touch stage 3b's gate (`precheck_canonical`/`_postcondition`) or stage 3c's `render.py`
  kind dispatch beyond what the table-driven residue report needs.
- No AI attribution in commits or docs.

## Definition of done

Per stage, in the guide: §3.12.4 for 3e, §3.13.6 for 3f. The one-line version — after 3f, adding an
anomaly kind with `repair="reconcile"` and no registered callable must be an **import error**, and
`do_reconcile` must have no per-shape early-return chain and no per-shape branch left.

## One open question, not a blocker

§3.14. Nobody has established how the `devman` repo actually reached the `lane-divergent` shape.
Stage 3d's fixture is a reconstruction, and two facts measured while building it contradict issue
42 §2's stated trigger: a plain amend after a publish does **not** diverge, and amending locally
while the forge side re-hashes produces a *conflicted* bookmark, which is a different anomaly with
a different repair. If a snapshot of that repo still exists, its op log would settle it — and might
show the repairable shape needs widening. Worth an hour, but do not let it block either stage.

Report honestly: what the two-way assertion caught when you first wired it, anything in §3.13.4
that turned out to be already broken, and anything above that is stale by the time you start.
