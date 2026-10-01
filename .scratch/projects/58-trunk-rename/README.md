# 58 — a trunk-rename capability for Gitman

**Filed:** 2026-10-01 · gitman 0.10.3 · pyjutsu 0.22.0 (jj-lib 0.44.0) · **Status: DESIGN — no code changed.**

## 1. The problem

`~/Documents/Projects/fsdantic`'s `gitman.toml` is one line: `trunk =
"fix/materialization-remove-exdev-fallback"` — a fix branch frozen as trunk, not a mainline.
Confirmed today: origin carries `main` at `56e2d5f394a97d68a5c1642104a9adeeff216983`, a **strict
ancestor** of trunk at `01ca33851a1a5f3dc4530b0e0e63b46a675fbb93`, exactly 4 commits behind
(`git rev-list --count origin/main..fix/materialization-remove-exdev-fallback` = 4). The owner
wants `main` to be the trunk. **Gitman ships no verb that does this.** Three routes were tried
today and all three closed.

## 2. The three closed routes

| # | Route | Result | Why it closes (file:line) |
|---|---|---|---|
| 1 | Create `refs/heads/main` with raw git, keep `gitman.toml` pointed at the old name, run `gitman repair` | `REPAIRED` / "removed leftover colocated git ref(s): main." Repair **deleted** the new ref. | `colocated_ref_desync` (`src/gitman/state.py:460-487`) builds `leftover` from git refs whose **name** matches no jj bookmark (`state.py:486`) — `main` is not a jj bookmark name here, so it is `leftover` by construction and never reaches `classify_ref_desync`'s adopt/rewrite split (`state.py:697-714`), which only processes `mismatched` (an existing jj bookmark of the same name, `state.py:481-485`). The keep-guard that could save a leftover (`src/gitman/invariants.py:471-477`, specifically line 473: `if git_id and not _known_to_jj(view, git_id) and not _ref_commit_on_remote(session, git_id): kept_leftovers.append(name)`) does not fire, because `_known_to_jj` (`state.py:630-650`) resolves the commit successfully — it is already a strict ancestor of the frozen trunk bookmark, so jj's index has always known it, import or no import. The `else` branch deletes the ref. No commit was lost (it stays reachable from the existing trunk bookmark), but the new ref is gone. |
| 2 | Flip `gitman.toml` to `trunk = "main"` first, then run `gitman repair` | `REFUSED` / "configured trunk 'main' not found — run `gitman doctor`." exit 2. | `do_repair` (`src/gitman/repair.py:101`) calls `capture_state(session)` before any `REPAIRS` dispatch runs. `capture_state` (`src/gitman/state.py:791-794`) resolves the configured trunk name as a jj bookmark and raises `GitmanError(exit_code=2)` the instant it fails to resolve — and `repair` is the only verb whose dispatch loop (`repair.py:133-139`) could have imported the ref that would make `main` resolve. Deadlock: the validation that would let repair proceed runs before the import repair would have performed. |
| 3 | `gitman init --colocate --trunk main` | Refused immediately. | `src/gitman/init.py:81-82`: `if config.trunk: raise GitmanError(f"already initialized (trunk '{config.trunk}' is frozen).", exit_code=3)`. `init` is a one-shot bootstrap, not a re-trunk path, by design (invariant I1). |

`gitman start` cannot help either: fsdantic's `@` is parented on `04c91ce07050` ("chore: adopt
central agent surface"), the commit *before* trunk — a sibling, not a descendant. `_adoptable_work`
(`src/gitman/core.py:704-720`) requires `view.is_ancestor(base_id, wc.commit_id)`, which is false
here, so `do_start` refuses at `core.py:510-514`: "@ holds uncommitted work that is not based on
trunk '<trunk>' — describe/land it first, or start a lane on its own base...".

## 3. The structural fact

A sibling investigation in `~/Documents/Projects/paloma-image-pipeline` found the mirror image:
deleting `refs/heads/<lane>` with raw git does not remove the jj bookmark — the lane came back
byte-for-byte in `gitman status` (same commit id, same change id, same timestamps), and `status`
did not even re-export the ref.

Together: **jj is authoritative for bookmarks; the colocated git ref is only a projection.** Raw
git cannot add a bookmark (route 1 prunes the orphan ref right back out) and cannot remove one
(the paloma result). Every bookmark change — including which bookmark is trunk — has to go through
a Gitman verb that talks to jj directly. That is why a trunk rename needs a verb and cannot be
scripted around with `git branch -m` plus a config edit. See `DESIGN.md` §1 for the full chain.

## 4. The decision

- **New verb: `gitman trunk rename <new-name>`**, under a new `trunk_app` noun sub-app (mirroring
  `remote_app`/`workspace_app`, `src/gitman/cli.py:467`,`:580`, and project 56's proposed
  `bookmark_app`). Rejected: a flag on an existing verb (no existing verb's shape fits) and a
  `--retrunk` flag on `init` (violates `init`'s one-shot contract, `init.py:81-82`). See
  `DESIGN.md` §1.
- **One `canonical_tx`/`canonical_guard`-shaped transaction**: create the new trunk bookmark at
  trunk's current commit (content-free — same commit, new name), decide the old bookmark's fate,
  rewrite `gitman.toml`'s `trunk` key, update `session.config.trunk` in-process. See `DESIGN.md` §2
  for step order and why the config write cannot be a bare file edit left outside the undo path.
- **The old bookmark is the sharpest hazard in this design, and it is worse than the brief
  measured.** The moment trunk is renamed, the old bookmark's range against the new trunk
  (`trunk..old_name`) is empty — not eventually, *immediately*, same commit. `gitman sync --trunk`
  (CLI name; the implementing function is still called `do_pull`, `core.py:2541`;
  `"pull": ("sync", ("--trunk",))` at `cli.py:623` is the kept deprecated alias) retires **any**
  surviving lane in that shape unconditionally (`_repair_lane_against_adopted_trunk`,
  `core.py:2380-2385`), and if it is published (`published_before = _lane_index(session.view())[1]`,
  `core.py:2567` — true regardless of tracked state), deletes its remote branch
  (`core.py:2650-2653`) with no flag to opt out. In fsdantic the old name is also **tracked**
  (verified: `tracked=True` is not the issue here — publication, not tracking, is what
  `_lane_index` checks). So the very next `gitman sync --trunk` on this repo, run by anyone,
  deletes `origin/fix/materialization-remove-exdev-fallback` — a real branch that may carry an
  open PR — with no second confirmation beyond having run an ordinary sync. The rename verb must
  not leave the repo in this shape without an explicit operator choice. See `DESIGN.md` §3
  (question 3).
- **Trunk is frozen (I1), and this respects it rather than breaking it.** I1 says runtime never
  *re-detects* trunk (`docs/GITMAN_CONCEPT.md:104`); it says nothing about a deliberate, named,
  one-shot act that re-freezes a new value and leaves an audit trail. See `DESIGN.md` §3 (question
  1) for the argument made precisely, and for where it would stop holding.

See `DESIGN.md` for the full failure chain, the eight questions, the worked example on fsdantic's
real commit ids, and the exit-code contract; see `IMPLEMENTATION.md` for the ordered build plan.

## 5. Relationship to projects 56 and 57

Independent of both. Project 56 (`bookmark track`) fixes a *different* lane's untracked forge
twin; nothing in this design creates or removes a `lane-untracked-twin` shape. Project 57
(declarative lane exclusion) lets an owner mark a bookmark as never-a-lane; the old trunk name
after a rename is the opposite case — it genuinely *was* the lane-shaped thing trunk always is,
and this design's own disposal choice (§3 below) is what decides whether it continues to exist as
an ordinary lane at all. Neither project's machinery substitutes for this one's.
