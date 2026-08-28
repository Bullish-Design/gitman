# 29 — Investigation guide: the colocated ref desync that happens with **no raw git**

**Written:** 2026-08-28, at trunk `8c9c028b` (gitman 0.5.0, pyjutsu 0.20.0 / jj-lib 0.44.0)
**For:** a fresh session. Read this file and
[`CONCURRENT_WORKING_ISSUE.md`](CONCURRENT_WORKING_ISSUE.md) first; nothing else is required.
**Goal:** name the cause of a `git ref(s) lag jj` desync that occurs while **only gitman
commands run**.

**Status when this was written: the mechanism is identified and a live specimen exists.**
Writing the guide turned into a partial investigation. §4 is no longer a hypothesis — the
swallowed error has been read, and a second, independent defect was confirmed along the way.
What remains is the *trigger*: the exact sequence that puts the repo into the state. Read §4
before anything else.

---

## 1. Why this is worth a session

This is the last unexplained defect standing between gitman and daily use. It has now been
observed **four times across two sessions and two repositories**. Nothing has been lost — but
`gitman reconcile`, the documented recovery, is now known **not** to repair the underlying
state (§4.3), and `status` and `doctor` both report the repo healthy while it is broken. A
silent fault in the component that owns "is this repo trustworthy" is the one bug you cannot
reason around.

The sibling report in this directory covers the case where a human ran **raw git**. That cause
is understood. **This guide is about the cases with no raw git at all**, which the existing
report does not explain.

---

## 2. The evidence

### Event 1 — project 32, `loci-core`, 2026-08-13

`save` / `publish` / `land` refused with `refusing: repo is off-canonical (1 bookmark(s) out of
sync with git … git ref(s) lag jj …)`. It appeared after a `uv run --project <gitman>` call,
with **no raw git command in between**. Not isolated at the time. See
[`../32-loci-core-adoption-issues/ISSUES.md`](../32-loci-core-adoption-issues/ISSUES.md) §G6,
event 1.

### Event 2 — project 35, gitman's own repo, 2026-08-28

Mid-session, `gitman save` refused:

```
refusing: repo is off-canonical (1 bookmark(s) out of sync with git: wheel-distribution
 — git ref(s) lag jj: wheel-distribution — run `gitman reconcile`.)
```

`gitman reconcile` repaired it and printed the two ids:

```
re-pointed colocated git ref(s) to jj: wheel-distribution 279b9de4 -> 9ba729d9
```

`279b9de4` is the exact commit `gitman publish` had pushed (independently confirmed — a uv
resolution against the branch at that moment reported the same id). So **jj moved from the
published commit to `9ba729d9` without the git ref following.**

Commands run between `publish` and the refusal, in order: `uv lock` in two throwaway
directories outside the repo, file edits, `ruff`, `pytest`, `gitman doctor`, several
`devenv shell` entries (each runs `uv sync`). **No gitman mutating intent, and no git command.**

### Event 3 — same session, minutes later

`gitman land` succeeded but printed **both** best-effort failure notes at once:

```
note: colocated git ref(s) stale for: some bookmarks — run `gitman reconcile` to re-sync.
note: colocated git checkout not re-synced — run `gitman reconcile` if raw git looks stale.
```

This is what pointed at the mechanism. See §4.

### Event 4 — same repo, 2026-08-28, **still live at the time of writing**

A routine `gitman land` printed `colocated git checkout not re-synced`. This time the
exception was read directly instead of being swallowed. See §4 — this event is the specimen.

### Context common to events 2 and 3

A **second jj workspace existed and was stale** the entire time
(`.worktrees/loci-adoption-fixes`; `gitman sync --all` reported `stale workspace(s):
loci-adoption-fixes — run gitman catchup`). It was never caught up. Event 1 also involved a
foreign-project invocation. Treat the stale second workspace as the leading correlate, not as
a conclusion.

---

## 3. Hypotheses already ruled out — do not repeat these

Both were tested at trunk `8c9c028b`. The probes are reproduced in §6.

| # | Hypothesis | Result |
|---|---|---|
| R1 | A lane bookmark sits on `@`, so ordinary working-copy edits amend `@` and drag the bookmark past the exported git ref. | **False.** After `save`, an edit, and a bare `ws.snapshot()`, the jj bookmark and the git ref both stayed at `d7d38ab5`. |
| R2 | `capture_state` reports canonical while drift exists (the §"Confirmed status bug" in the sibling report). | **Not reproducible on this path.** `capture_state` returned `canonical=True` with jj and git genuinely equal. The sibling report's case involved raw git and may still be real; it is not what events 2–3 were. |

Also note: the op log shows `export git refs` operations firing where expected around the
gitman intents. Whatever fails, it is **not** a missing call to the exporter.

---

## 4. CONFIRMED: what is actually happening

`src/gitman/invariants.py::_export_colocated_git` (line ~470) is the only post-mutation
exporter. It contains **three** broad handlers that throw the diagnosis away:

```python
try:
    session.ws.git_export()
except Exception:                      # (a) the real error dies here
    ...
    try:
        mismatched, leftover = colocated_ref_desync(session.view(), session.ws)
    except Exception:                  # (b) and here
        mismatched, leftover = [], []
    stuck = sorted([n for n, _, _ in mismatched] + leftover)
    names = ", ".join(stuck) if stuck else "some bookmarks"
    notes.append(f"colocated git ref(s) stale for: {names} — …")
    notes += sync_colocated_refs(session)
try:
    session.sync_colocated()
except Exception:                      # (c) and here
    notes.append("colocated git checkout not re-synced — …")
```

**Read event 3 against this code.** The message was `stale for: some bookmarks` — the
`else` branch. That string is only reachable when `stuck` is empty, which means branch **(b)**
also fired: `colocated_ref_desync` *itself* raised. And the second note means **(c)** fired
too.

So during that `land`, `git_export()` failed, the fallback that would have named the stuck
refs failed, and the colocated checkout sync failed — **three failures, zero recorded
detail.** A single systemic fault is far more likely than three coincidences, and the code is
built to hide exactly that.

The comment above the handler says the type was widened deliberately
(`# was: except PyjutsuError — GitError/AttributeError on pyjutsu versions escapes`). That is
a reasonable robustness choice and it is also why nobody knows what is happening. The bug and
its own diagnostics were suppressed by the same commit.

### 4.1 The swallowed error, read at last

Calling the two failing functions directly on the live repo:

```
git_export     : GitError: Failed to update Git HEAD ref
sync_colocated : GitError: Failed to update Git HEAD ref
```

**It is not the bookmark refs. It is `.git/HEAD`.**

### 4.2 The repo state that produces it

```
jj @             c53e6b2a872f
jj @ parents     8f7dec5de7b0      <- current trunk head; where jj wants HEAD
.git/HEAD        e4686d3142bf      <- detached, and NOT an ancestor of main
HEAD object      exists (a commit)
```

`e4686d31` is the **abandoned version-bump commit from an operation that was undone earlier in
the session**. `.git/HEAD` is pinned to a commit that is no longer reachable from any branch.

jj will not move a HEAD it does not recognise — that guard exists so jj never clobbers an
out-of-band checkout. So the guard is firing correctly on a state that should not exist, and
**every colocated export from that moment on fails, permanently, until something repairs HEAD.**

### 4.3 The second defect: all three health surfaces say the repo is fine

At the exact moment both exports were failing:

```
$ gitman status      → CANONICAL · 1 lane
$ gitman doctor      → HEALTHY  (including "ok colocated-refs  jj bookmarks ↔ git refs in sync")
$ gitman reconcile   → CLEAN — "already canonical — no strays, refs in sync."
```

`reconcile` is the documented recovery for exactly this class of problem, and **it does not
detect or repair a stuck HEAD.** It compares bookmarks against refs; nothing looks at
`.git/HEAD`. This is independently actionable and arguably worse than the export failure: a
user following the tool's own advice is told everything is fine.

This also explains why the earlier events "recovered": `reconcile` fixed the *bookmark* drift
those events surfaced, while the HEAD problem either was not present or stayed hidden.

### 4.4 What is still unknown — the trigger

The obvious candidate was tested and **does not reproduce**: `init → start → save → land →
undo` leaves HEAD correct and both exports OK (probe in §6, extended with `do_land` /
`do_undo`). So a plain undo-after-land is not enough.

The real session did something more specific. The strongest remaining lead is that the undone
operation was a **version bump that had already been exported**, and that it was then
**re-applied** (the bump was undone and redone), leaving jj's recorded git-head and `.git/HEAD`
on divergent lines. A stale second workspace was also present throughout.

**Finding the trigger is the remaining work.** §5 is written for that.

### Secondary hypotheses for the trigger, in order

- **H2 — the stale second workspace.** A stale workspace has its own `@` and its own operation
  view. `git_export` may be refusing, or exporting a different workspace's idea of the
  bookmarks. Correlates with events 2 and 3; project 26
  (`worktree-land-checkout-catchup-desync`) is adjacent prior art.
- **H3 — concurrent `uv sync` racing the exporter.** Every `devenv shell` entry runs `uv sync`,
  which rewrites files in the repo. If that lands between jj's snapshot and `git_export`, the
  export could see a moving tree. Event 1's `uv run --project` fits this shape too. Note the
  repo lock (I4) serialises *gitman* writers only — it does not exclude uv.
- **H4 — a D/F ref conflict from fractal lane names.** The docstring names this as one of two
  things `git_export` refuses (`refs/heads/T` blocking `refs/heads/T/api`). `BASELINE.md` §9 in
  project 34 records a fractal-name ref written out of band as **unretirable** through pyjutsu.
  Both repos in question have carried `/`-path lanes; pyjutsu's repo still has 20 orphaned
  ones.

---

## 5. The protocol

### Step 0 — instrument (still worth doing; it is 20 minutes)

The error text is now known, but only because it was extracted by hand from a live repo. It
must not require that again.

Patch `_export_colocated_git` to record what it caught, on all three handlers. Keep the
best-effort behaviour — only add detail:

```python
except Exception as exc:
    notes.append(f"git_export failed: {type(exc).__name__}: {exc}")
```

Do the same for the `colocated_ref_desync` and `sync_colocated` handlers. Consider writing the
full traceback to `.gitman/export-failures.log` as well, since the note is size-limited and the
interesting case may be rare.

**Do not ship this as-is.** Decide at the end whether the final form is a note, a log, or a
`doctor` row.

### Step 1 — reproduce the trigger

Start from the known end state and work backwards. The assertion is cheap and exact:

```python
head = (repo / ".git" / "HEAD").read_text().strip()
ws.git_export()          # must not raise
```

Drive **gitman intents only**, checking after each. Concentrate on the sequence §4.4 names:
a bump that is exported, then undone, then re-applied. Then widen:

Build a harness (see §6 for a working skeleton) that drives **gitman intents only** and asserts
canonicity after every single one. Then add, one at a time, in this order:

1. A second workspace, deliberately left **stale** (`start --workspace`, land something on
   trunk, never `catchup`). Then run a normal lane loop in the main workspace.
2. A `uv sync` / `uv lock` interleaved between intents, in the same repo.
3. A `/`-path fractal lane (`T`, then `T/api`) alongside the above.

Assert after each intent:

```python
jj  = {b.name: b.target_ids for b in ws.bookmarks() if b.remote is None}
git = ws.git.refs()          # dict: ref name -> id
```

Compare directly. Do not use `capture_state().canonical` as the oracle — R2 shows it can
disagree with the raw comparison, and you want the ground truth.

### Step 2 — bisect the trigger

Once it reproduces, remove one ingredient at a time. The result you want is a one-sentence
statement of the form: *"`git_export` raises `<Type>: <message>` when `<condition>`, because
`<mechanism>`."*

### Step 3 — decide the fix

Only then. Candidates, depending on what you find:

- Narrow the handlers and let a genuinely unexpected error surface as exit 2.
- Make `land`/`save` **retry** the export once after `sync_colocated_refs`, rather than leaving
  the repo off-canonical for the *next* command to refuse.
- If H2 holds: refuse or repair at the point a stale workspace is detected, instead of noting
  it and continuing.
- If H4 holds: this may be a pyjutsu-side limit (see project 34 `BASELINE.md` §9). Escalate
  there rather than papering over it in gitman.

**Independently of the trigger, two fixes are already justified by §4.2–4.3:**

1. **`reconcile` must check and repair `.git/HEAD`.** Detect a HEAD that jj does not recognise
   or that is unreachable from any branch, re-point it at the working copy's parent, and report
   the move with both ids like every other ref repair.
2. **`doctor` must have a HEAD row.** A repo whose every export is failing must not report
   HEALTHY. This is the cheapest guard against the whole class.

Both can land before the trigger is understood, and both would have turned three of the four
sightings into a one-line diagnosis.

---

## 6. A working probe skeleton

This ran successfully at trunk `8c9c028b` and is the basis for the R1/R2 results. It needs
only `devenv shell -- python <file>` from the gitman repo.

```python
import pathlib, tempfile
from pyjutsu import Workspace
from gitman.session import Session
from gitman.config import GitmanConfig
from gitman.core import do_start, do_save
from gitman.init import do_init

tmp = pathlib.Path(tempfile.mkdtemp())
ws = Workspace.init(tmp, colocate=True)
(tmp / "pyproject.toml").write_text(
    '[project]\nname = "d"\nversion = "1.2.3"\nrequires-python = ">=3.13"\ndependencies = []\n'
)
(tmp / "app.py").write_text("print(1)\n")
with ws.transaction("initial") as tx:
    tx.describe("@", "initial")
do_init(Session.load(tmp, GitmanConfig()), trunk_opt=None)

def drift(label):
    """Ground truth: compare jj bookmarks against colocated git refs directly."""
    w = Workspace.load(tmp)
    jj = {b.name: ",".join(t[:8] for t in b.target_ids) for b in w.bookmarks() if b.remote is None}
    git = {n.split("/")[-1]: w.git.refs()[n][:8] for n in w.git.refs()}
    bad = {k: (jj.get(k), git.get(k)) for k in jj | git if jj.get(k) != git.get(k)}
    print(f"{label:34} {'DRIFT ' + str(bad) if bad else 'in sync'}")

do_start(Session.load(tmp), "demo", workspace=False)
(tmp / "app.py").write_text("print(2)\n")
do_save(Session.load(tmp), message="work")
drift("after save")
```

Model API notes that cost time to discover:

- `Bookmark` fields are `name`, `remote`, `target_ids`, `tracked` — there is **no** `commit_id`.
  Local bookmarks are `remote is None`.
- `ws.git.refs()` returns a **dict** of ref name to id, not a list of objects.
- `ws.diff(rev)` returns a `Diff` with `.files`, each a `FileChange` with `.path`.
- `RepoState` has no `reason`; the field is `off_canonical`.

---

## 7. What "done" looks like

1. A named, reproducible trigger, written up in this directory.
2. A regression test in `tests/` that fails before the fix and passes after — assert on the
   raw jj-vs-git comparison, not on `canonical`.
3. A decision recorded on whether the broad `except Exception` handlers stay, narrow, or gain
   permanent logging. **This choice is the real deliverable**: it is why the bug survived three
   sightings.
4. Project 32's G6 event 1 marked explained or explicitly still open.

If it does not reproduce after a solid attempt, that is a real result too. Record what was
tried and what was ruled out, and add the instrumentation from Step 0 permanently so the next
sighting arrives with evidence attached.

---

## 8. Files to know

| Path | Why |
|---|---|
| `src/gitman/invariants.py` `_export_colocated_git` (~470) | The exporter and its three silent handlers. **Start here.** |
| `src/gitman/invariants.py` `sync_colocated_refs` (~267) | The single ref-writing classifier; decides which side wins. Issue 31 was a second copy of this logic. |
| `src/gitman/state.py` `colocated_ref_desync` (~275) | Drift detection; feeds `status` and `doctor`. Raised during event 3. |
| `src/gitman/reconcile.py` | The repair that always worked. Whatever it does correctly, the mutating path is failing to do. |
| `src/gitman/session.py` `sync_colocated` (~105) | HEAD + index sync; handler (c). |
| `CONCURRENT_WORKING_ISSUE.md` | The raw-git variant, already understood. |
| `../26-worktree-land-checkout-catchup-desync/` | Prior art for H2. |
| `../32-loci-core-adoption-issues/ISSUES.md` §G6 | Event 1. |
| `../34-pyjutsu-0-19-adoption/BASELINE.md` §9 | The unretirable fractal-name ref, for H4. |
