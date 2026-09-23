# 52 — Follow-ups filed from project 51

**Filed:** 2026-09-23 · **Source:** `.scratch/projects/51-conflict-materialization-and-land-honesty/
IMPLEMENTATION_GUIDE.md` §10, and the research report it was built from
(`.scratch/projects/50-stacked-lane-rebase-conflict-deadlock/RESEARCH_REPORT_49_50.md`).
**Status:** REFERENCE — five independent items, confirmed but deliberately out of scope for
project 51. Pick any one off this list on its own; they do not depend on each other.

Project 51 fixed the stacked-lane conflict deadlock, gated `publish` on a conflicted lane, and made
`land`/`sync --dry-run` honest. Five more confirmed gaps surfaced during that investigation and were
deliberately not absorbed (§9 of the implementation guide explains why each one would have widened
scope). They are filed here instead of left as prose in a closed project's guide.

---

## 1. `gitman log` reports zero diff stats for every change

**Confirmed.** `state.log_range` passes no `DiffStat`, so every row `gitman log` prints reads
`files_changed: 0, insertions: 0, deletions: 0` regardless of the change's real content
(`state.py:1144-1155`, `state.py:59-70`).

**Why it matters.** It actively misleads. It caused a wrong conclusion in the project-50 field
session: the operator read two ancestor changes as empty from this output and reasoned from that —
`Change.empty` in the same row was honest (`False`), but the zeroed stats were not, and the
distinction cost real time.

**Fix shape.** Either compute a real `DiffStat` in `log_range` (mirror how `Lane`'s own
insertions/deletions/files_changed are populated from git numstat elsewhere in `state.py`), or omit
the stat fields from the emitted rows entirely rather than reporting zeros. Either is a one-file
change; no design decision needed.

---

## 2. `sync <lane>` and `sync <lane> --recursive` — targeted sync

**Confirmed gap.** `do_sync` targets exactly "the current lane" or "every lane" (`--all`); the CLI
exposes no lane argument (`cli.py`, `sync` command). To sync a lane you are not standing on, you
must `switch` to it (which refuses on a dirty unnamed `@`) or `cd` into its workspace.

**Why it matters.** In the field, `--all` rebased a lane the operator did not intend to touch and
left it permanently conflicted — the collateral-damage case that made the project-50 deadlock worse
than it needed to be. `do_sync`'s internals already support a `lanes` argument shape (`subjects_for`
takes a lane set), and `lanes.subtree` already computes subtrees for `--recursive`-style targeting.

**Fix shape.** Add a `lanes: list[str] | None` argument to `do_sync`, wire `--recursive` through
`lanes.subtree`, and a positional lane argument on the CLI `sync` command. Test: syncing one lane
leaves an unrelated behind lane untouched; `--recursive` rebases a subtree parent→child.

---

## 3. The stranded working copy — `@` parked on an ancestor of trunk

**Confirmed, and not touched by project 51.** When `@` sits on an existing historical commit that
is not a live lane's head (an ancestor of trunk, reached e.g. by an out-of-band `jj edit`), every
verb misreads it:

| Command | What it does today |
|---|---|
| `repair` | reports CLEAN — no anomaly kind exists for this shape |
| `switch <lane>` | refuses "uncommitted work would be stranded" — false; the commit isn't empty, it just isn't a lane |
| `start <flat>` | refuses "`@` holds uncommitted work that is not based on trunk" |
| `describe` / `sync` / `abandon` | "not on a lane" |

The root cause is one conflation: `switch`/`start` both use `not wc.is_empty` as a proxy for "has
uncommitted work," which is simply wrong for a working copy parked on an existing, named-elsewhere
commit.

**Fix shape (designed, not built — research report §7.1, §8 P50-D/P50-E).** A `working_copy` block
on `RepoState` (change-id, commit-id, bookmarks, empty, conflict, relation to trunk and to each
lane, descendant count); a note-only `wc-stranded` anomaly kind with a `repair` row (must be
note-only — a blocking kind here would roll back healthy intents, the same reasoning project 51
applied to a materialized conflict); and `gitman switch --trunk` to reseat `@` onto a fresh child of
trunk. This is the largest of the five follow-ups and was explicitly deferred pending real use of
project 51's fixes first.

---

## 4. `land --dry-run` omits the remote-branch deletion

**Confirmed.** The delete-push of a landed lane's remote branch is not a `Plan` step — it runs in
`_do_land_locked` after the guard closes (`core.py`), while `--dry-run` renders only
`Plan.steps` + `Plan.outside_steps`. `plan.py` has no step type for it. The real run prints "deleted
remote branch '<lane>' (one-way …)"; the dry run never mentions it — the one irreversible effect of
`land` is exactly the one a dry run doesn't warn about.

**Fix shape.** Add an `OutsideStep` (e.g. `DeleteRemoteBranch(lane, remote)`) to `plan.py`, move the
delete-push onto it so `describe_plan` renders it, and keep its execution **after** the guard closes
(the irreversible-call-after-the-guard rule, concept §11 — do not move the network call earlier).

---

## 5. A refusal naming a destructive verb should classify its target first

**Confirmed pattern, not just one bug.** `switch`'s stranded-`@` refusal (item 3 above) recommends
`gitman abandon`, which then itself refuses with "not on a lane" — the suggested escape doesn't
work. The general rule this misses (research report §2.4): *before gitman names a destructive verb
in a refusal, it must have classified the target as safe for that verb* — ancestor of trunk /
ancestor of a live lane / a genuine leaf, plus a descendant count.

**Fix shape.** A small helper over `view.is_ancestor` + descendant count, used at every refusal site
that currently names a verb without having checked it applies (`GitmanError.remedies` already
carries structured remedy names — `core.py`). Most naturally lands alongside item 3, since the
stranded-`@` refusal is the sharpest instance, but the helper is general and other refusal sites can
adopt it independently.
