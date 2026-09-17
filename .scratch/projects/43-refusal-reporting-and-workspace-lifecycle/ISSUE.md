# Issue 43 — refusals are invisible, `start` under-adopts, and a workspace registration outlives its lane

**Date:** 2026-09-16
**Repo where it surfaced:** `paloma-text-pipeline` (`~/Documents/Projects/paloma-text-pipeline`),
during project 003-vllm-sampler-plugin, the canvas-injection blocker session
**Versions:** gitman `0.6.2` · pyjutsu `0.21.1` (jj-lib `0.44.0`) · colocated repo, 20 jj
workspaces, several live concurrently
**Lane shape:** fractal — `diffusion-experiment-rig`, `diffusion-experiment-rig/experiments`,
`diffusion-experiment-rig/injection-blocker`, …
**Outcome:** a finished change **landed into a published lane with an empty commit message**, and
an existing workspace checkout was **deleted by a refused command**. No content was lost in either
case, but only because jj auto-snapshots and because the deleted checkout happened to be at an
empty commit.

**Severity: HIGH.** Two independent silent-failure paths, both reached by following the tool's own
advice.

---

## 1. TL;DR

Five defects, one theme: **gitman's failures do not look like gitman's output, and its adoption and
workspace lifecycles do not match what it tells the operator.**

| # | Defect | Severity |
|---|---|---|
| D1 | A refusal is not rendered as a gitman report, so any output filter loses it entirely | **high** |
| D2 | `start --workspace` **deletes the target directory** when it refuses on a duplicate name | **high** |
| D3 | A jj workspace registration outlives its lane, permanently burning the lane name, and no gitman verb forgets it | **high** |
| D4 | ~~`start <T/leaf>` does **not** adopt a dirty unbookmarked `@`, though `status` says it will~~ **FIXED (2026-09-17, project 46 S4).** `_adoptable_work` now tests descent from the ACTUAL intended base (trunk or the parent lane's head) with `is_ancestor`, and `do_start` bookmarks the dirty `@` itself instead of creating a fresh sibling change beside it. A dirty `@` that is NOT based on the intended base now refuses with a reason (exit 1) rather than stranding the work. | **high** |
| D5 | `land` folds a change with an empty description without warning | medium |
| D6 | ~~On fractal lanes the git ref desyncs after essentially every write, so `reconcile` becomes a required prefix to every `save`~~ **FIXED (2026-09-17, project 46 S3, issue 44 stage 4f).** Took the first "what I expected" option below: `+` (not `/`) is now the lane-path separator everywhere, a legal git ref character with no parent/child collision — see §7. | medium |

D1 is the root of the expensive one: D6 makes refusals frequent, D1 makes them invisible, and D5
lets the resulting undescribed change land.

---

## 2. D1 — a refusal is not a gitman report (HIGH)

Every gitman **success** prints a banner line:

```
Gitman save [diffusion-experiment-rig/name-exemption] — SAVED
Gitman reconcile — RECONCILED
Gitman land — LANDED
```

Every gitman **refusal** prints a bare lowercase sentence with no banner, no verb, and no status
token:

```
refusing: repo is off-canonical (1 bookmark(s) out of sync with git:
diffusion-experiment-rig/name-exemption — git ref(s) lag jj) — run `gitman reconcile`.
```

```
not on a lane — run `gitman start <name>` first.
```

The exit code is correct — **1**, matching the documented contract (`0` ok · `1` a VC decision is
needed). The defect is purely in the rendering, and it is enough on its own:

```bash
$ gitman save -m "<40-line message>" | sed -n '/^Gitman/,$p'
$          # <- nothing. Looks exactly like a quiet success.
```

This is how the incident happened. gitman's own output convention teaches you that its report
starts with `Gitman`; filtering on that is the natural way to strip the shell banner this repo
prints before every command. Two consecutive saves were swallowed this way. The lane still showed
the right `+140 −34` — because jj had auto-snapshotted the working copy — so nothing looked wrong,
and `gitman land` then folded the change into the published `diffusion-experiment-rig` lane **with
an empty description**.

### Compounding: the pipeline exit-code trap

The obvious guard is to check `$?`. Through a pipe it is the **last** command's status:

```bash
$ gitman save -m "..." 2>&1 | tail -20; echo "EXIT=$?"
EXIT=0          # tail's status. gitman really returned 1.
```

That is a shell fact, not gitman's fault, but it removes the one safeguard an operator would
otherwise have, and it is worth naming in the docs next to the exit-code contract.

### What I expected

A refusal is an **outcome**, and should be reported in the same shape as every other outcome:

```
Gitman save — REFUSED
reason: repo is off-canonical (1 bookmark(s) out of sync with git: <lane> — git ref(s) lag jj).
Recover: `gitman reconcile`
```

Then `| sed -n '/^Gitman/,$p'`, `| grep '^Gitman'`, and every other banner-oriented filter surface
the failure instead of hiding it. `--json` should carry the same thing structurally
(`{"verb":"save","status":"REFUSED","reason":...}`), so scripted callers do not have to
string-match either.

This generalises the D0b/G6 complaints in issue 42: there the problem was a `Recover:` line naming
a verb that also refuses; here it is that a refusal does not announce itself as one.

---

## 3. D2 — `start --workspace` deletes the target directory when it refuses (HIGH)

```
$ gitman start diffusion-experiment-rig/phase2 --workspace
workspace named 'diffusion-experiment-rig/phase2' already exists
```

`.worktrees/diffusion-experiment-rig/phase2/` — a full checkout, ~40 entries, including a nested
`plugin/` workspace — **was gone afterwards.**

Evidence chain (no `ls` was captured in the same command as the failure, so this is causal
inference from an ordered sequence, not a single atomic observation):

1. `ls .worktrees/diffusion-experiment-rig/phase2/` listed a full checkout (`AGENTS.md`,
   `devenv.nix`, `src`, `plugins`, `plugin`, …).
2. `cd .worktrees/diffusion-experiment-rig/phase2/plugin && gitman status` succeeded — so both
   directories existed.
3. `gitman start diffusion-experiment-rig/phase2 --workspace` → the refusal above.
4. `cd .worktrees/diffusion-experiment-rig/phase2` → `no such file or directory`; the parent now
   contained only `experiments`.

No other mutating command ran between 2 and 4.

**A command that refuses must not have side effects**, and the most destructive possible side
effect is removing an existing checkout. The likely shape is create-dir-then-register with a
cleanup on the registration error that does not check whether the directory pre-existed.

### What I expected

- The duplicate-name check runs **before** anything touches the filesystem.
- If cleanup is needed at all, it removes only a directory this invocation created — record that
  and gate the cleanup on it.
- The refusal names the collision and what to do:
  `workspace 'X' is already registered (dir: <path>, @ at <commit>, empty). Reuse it with `gitman
  switch`, or forget it with `gitman workspace forget X`.`

---

## 4. D3 — a workspace registration outlives its lane (HIGH)

The prior session landed `diffusion-experiment-rig/phase2/plugin` into
`diffusion-experiment-rig/phase2`, then that into `diffusion-experiment-rig`. Both lanes retired
correctly. Their **jj workspaces did not**:

```
$ jj workspace list
diffusion-experiment-rig/phase2:        smozznrk 13fc3f28 (empty) (no description set)
diffusion-experiment-rig/phase2/plugin: tnxxvtwu a5d17956 (empty) (no description set)
```

Neither appears in `gitman status`. Both are at empty commits. The consequence is that **those two
lane names are now permanently unusable**: `gitman start <name> --workspace` refuses on the stale
registration (and deletes the directory, per D2), and `gitman start <name>` without `--workspace`
would move `@` in the shared main folder, which is not an option when other sessions live there.

gitman has **no workspace verb at all** — `gitman --help` lists no `workspace` command, so there is
no supported way to list, forget, or re-derive one. `catchup` mentions "refresh stale workspaces"
but does not forget retired ones, and reaching for raw `jj workspace forget` is exactly what gitman
exists to prevent.

This is the kickoff-prompt-level workaround we ended up documenting for the next session: *"do not
try to reuse those lane names."* That is a scar, not a fix.

### What I expected

- `land` / `abandon` release the lane's workspace registration as part of retiring the lane, when
  its `@` is empty and it is not the current workspace.
- A `gitman workspace` verb group: `list` (annotating which registrations have no live lane),
  `forget <name>`, and `prune` for the empty-and-laneless ones.
- `gitman status` mentions registrations with no lane, rather than leaving them invisible until
  they block a `start`.

---

## 5. D4 — `start <T/leaf>` does not adopt a dirty unbookmarked `@` (HIGH)

After a `land`, gitman reparks `@` onto a fresh change. Edits made there are unbookmarked, and
`status` says so — and names the remedy:

```
note: working copy @ has unbookmarked work — `gitman start <name>` to adopt it into a lane.
```

Following that advice did not adopt anything:

```
$ gitman start diffusion-experiment-rig/name-exemption
Gitman start [diffusion-experiment-rig/name-exemption] — STARTED
lane 'diffusion-experiment-rig/name-exemption' stacked on 'diffusion-experiment-rig'.

$ gitman status
    diffusion-experiment-rig/name-exemption draft  1 change, +0 −0  · ↳ on diffusion-experiment-rig
note: working copy @ has unbookmarked work — `gitman start <name>` to adopt it into a lane.
```

The lane was created **empty**, at its own new change, and `@` was left where it was — a *sibling*
carrying the 7 modified files, still unbookmarked. The advice printed again, verbatim, after doing
what it said. Measured:

```
Working copy  (@) : qxzrqoro 8c467850 (no description set)      <- 7 modified files, no bookmark
Parent commit (@-): tvxokyqq 2f98eba6 diffusion-experiment-rig*
$ jj log -r 'diffusion-experiment-rig/name-exemption'
tmxlupvkqvms dc35ad065b66 empty:yes                             <- the new lane, elsewhere
```

Reproduced twice in the session, both times after a `land`.

Note this is the **mirror image** of issue 42 §7a and issue 38: there `start` adopts *too much*,
sweeping unrelated working-copy files into a lane; here it adopts *nothing* when it says it will.
Both are the same underlying gap — `start`'s adoption semantics are not specified anywhere the
operator can see, and differ by the state `@` happens to be in.

### The recovery that worked

Worth recording because it is not obvious:

1. Back up the modified files outside the repo.
2. Restore the working copy to match `@-` (`jj file show -r @- <path> > <path>`), until
   `jj status` reports no changes.
3. `gitman start <lane>` — now works, because `@` is clean.
4. Copy the files back.
5. `gitman reconcile` (see D6), then `gitman save`.

### What I expected

`gitman start <name>` with a dirty unbookmarked `@` bookmarks **that change** as the lane, which is
what the status note promises. If there is a reason it cannot — e.g. `@` is not a descendant of the
intended base — say so and name the fix, rather than silently creating an empty lane next to the
work and re-printing the same advice.

---

## 6. D5 — `land` folds an undescribed change without warning (MEDIUM)

```
$ gitman land
Gitman land — LANDED
folded diffusion-experiment-rig/injection-blocker→diffusion-experiment-rig.
```

The folded change had an **empty description** (D1 had swallowed both `save` attempts). `land` said
nothing. The result is a published integration lane whose tip commit has no message — visible only
by going to raw `jj log`, which in this repo is otherwise discouraged.

Recovery, once noticed: `gitman switch <parent-lane>` then `gitman save -m "..."`, which describes
the parent lane's tip. That works well and is a nice property, but it is undocumented.

### What I expected

`land` refuses, or at minimum warns loudly, when the change it is about to fold has no description:

```
Gitman land — REFUSED
reason: 'diffusion-experiment-rig/injection-blocker' has no description.
Recover: `gitman save -m "<message>"`, or `gitman land --allow-empty-message`
```

This is cheap and it closes the D1 → D5 chain: even with the refusal hidden, the undescribed change
cannot reach a published lane.

---

## 7. D6 — fractal lanes desync the git ref after nearly every write (MEDIUM) — FIXED

**Fixed 2026-09-17** (project 46 S3, issue 44 stage 4f, decision D-A2 — signed off, `SCOPING.md`
§2.2): `+` is now the lane-path separator everywhere — jj bookmark, git ref, remote branch,
report, and user input (`/` is accepted only as input sugar, normalised away at the CLI boundary).
`+` is a legal git ref character with no parent/child directory collision, so this is the first
"what I expected" option below, taken directly rather than the `refs/gitman/` namespace
alternative. A pre-migration `/`-named repo is detected (note-only `lane-legacy-name` anomaly) and
migrated by `gitman reconcile` (same commit, new name). The section below is kept as the original
report.

This is issue 42's / the known slash-path ref collision, filed here for its **operational cost**
rather than its mechanism. In a repo whose lanes are `/`-paths, the colocated git ref falls behind
jj after essentially every working-copy snapshot, so:

```
$ gitman save -m "..."
refusing: repo is off-canonical (... git ref(s) lag jj ...) — run `gitman reconcile`.
$ gitman reconcile
Gitman reconcile — RECONCILED
$ gitman save -m "..."
Gitman save — SAVED
```

`reconcile` became a mandatory prefix to every single `save` and `land` in the session — roughly a
dozen times. Combined with D1, each of those is a chance to silently lose a write.

Every `reconcile` also emitted, to stderr:

```
error: cannot lock ref 'refs/heads/diffusion-experiment-rig': 'refs/heads/diffusion-experiment-rig/experiments'
exists; cannot create 'refs/heads/diffusion-experiment-rig'
error: failed to run reflog
```

…followed by `RECONCILED`. git cannot hold both `refs/heads/X` and `refs/heads/X/child`, so a lane
that has children can never have a clean git ref. That is structural.

### What I expected

Either:

- **Encode the hierarchy in a way git can hold** — e.g. export fractal lanes as
  `refs/heads/<lane with a separator git tolerates>`, or under a `refs/gitman/` namespace, so the
  parent/child collision cannot arise; or
- **Stop treating a structurally-impossible ref as a desync.** If `X` has a live child, gitman
  knows `refs/heads/X` cannot exist; it should not then gate writes on that ref being in sync, nor
  print an error the operator is told to ignore.

The current behaviour makes the canonical-state gate fire constantly for a condition the tool
itself creates and cannot fix.

---

## 8. Minor — `doctor` reports a workspace checkout as "not a colocated jj repo"

```
$ cd .worktrees/<lane> && gitman doctor
  XX colocated      not a colocated jj repo — colocate it: `python -c '...Workspace.init(".", colocate=True)'`
```

`gitman status` in the same directory reports CANONICAL and works fine. A prior session in this
repo had already confirmed the warning is a `--workspace`-checkout artifact rather than a real
problem, and recorded it as such. The remedy it prints — re-colocating — would be actively harmful
if followed. `doctor` should recognise a secondary workspace and either skip the check or report it
as informational.

---

## 9. Proposed fixes

| # | Fix | Where | Severity |
|---|---|---|---|
| **G1** | **Render refusals as `Gitman <verb> — REFUSED` + `reason:` + `Recover:`**, same shape as every other outcome; mirror in `--json` as a `status` field | output/report layer | **highest** |
| G2 | `start --workspace` must perform the duplicate-name check before touching the filesystem, and must never delete a directory it did not create | `start.py` | high |
| G3 | Release a lane's workspace registration on `land`/`abandon` when its `@` is empty and it is not the caller's workspace | `land.py` / `abandon.py` | high |
| G4 | Add a `gitman workspace` verb group: `list`, `forget <name>`, `prune` | `cli.py` | high |
| G5 | `start <name>` with a dirty unbookmarked `@` must bookmark **that** change, per the `status` note; if it cannot, refuse and explain | `start.py` | high |
| G6 | `land` refuses (or warns) on a change with an empty description; `--allow-empty-message` to override | `land.py` | medium |
| G7 | Do not gate writes on a git ref that cannot exist because the lane has children; stop reporting it as a desync | `state.py` / export | medium |
| G8 | `doctor` recognises a secondary jj workspace instead of reporting it uncolocated | `doctor.py` | low |
| G9 | Document, next to the exit-code contract, that `$?` through a pipe is not gitman's status | docs | low |

G1 is the root fix: D6 makes refusals routine, and D1 makes routine refusals invisible. With G1 in
place this session's incident does not happen, even with every other defect left as-is. G6 is the
cheap belt-and-braces that stops the worst consequence.

---

## 10. Cross-references

- `gitman/.scratch/projects/42-divergent-lane-bookmark-livelock/` — §3b (`reconcile` vs `status`
  disagreeing) and G6 (naming a remedy that does not work) are the same reporting-integrity theme;
  §7a is D4's mirror image
- `gitman/.scratch/projects/38-working-copy-co-tenancy/` — `start`/`switch` moving the working copy
  under the operator; D4 is the under-adoption face of it
- `gitman/.scratch/projects/29-concurrent-worktree-raw-git-desync/` — this repo runs several live
  workspaces, which is the context for D2/D3
- `gitman/.scratch/projects/31-reconcile-git-ahead-ref-reset-data-loss/` — `reconcile` removing
  colocated refs; seen here too, as `removed leftover colocated git ref(s): …/phase2, …/phase2/plugin`
- `paloma-text-pipeline` `.loci/projects/003-vllm-sampler-plugin/02-progress/001-progress.md`
  §"Two gitman traps this session paid for" — the operator-side write-up
- `paloma-text-pipeline` `.loci/projects/003-vllm-sampler-plugin/00-planning/008-bars-run-kickoff-prompt.md`
  §1 — the workarounds the next session has to carry
