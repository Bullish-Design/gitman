# ISSUE — a stacked child that cannot rebase deadlocks its whole stack, and the escape hatch is destructive

> **RESOLVED (2026-09-23, project 51).** `sync` now materializes a conflicting stacked rebase
> instead of leaving the lane on its prior base (D1-a) — the deadlock this issue describes no
> longer reproduces. Full analysis: `RESEARCH_REPORT_49_50.md` (this directory). Fix and test
> matrix: `.scratch/projects/51-conflict-materialization-and-land-honesty/
> IMPLEMENTATION_GUIDE.md`. The text below is the original field report, kept as history.

> **Status:** open, captured 2026-09-23 from a `paloma-text-pipeline` session that landed a
> 10-lane narrative stack into trunk.
> **gitman version at capture:** 0.10.3 · pyjutsu 0.22.0 (jj-lib 0.44.0)
> **Scope:** changes to **gitman itself**, not its consumers.
> **Outcome of the session:** trunk landed and pushed, but only after `abandon`ing two child
> lanes and restoring their content from a manual filesystem backup.

---

## 1. TL;DR

A stacked lane whose rebase **would** conflict is left on its **prior base** and is never
marked conflicted. `gitman resolve` does not list it, so there are no markers to edit and
nothing to resolve. Because `gitman land` refuses a base that has a live child, **one
unrebasable child holds its entire stack hostage** — and the only escape gitman offers is
`gitman abandon`, which discards that child's change.

Three secondary defects made the session materially worse:

* refusal messages **recommend `abandon` on a change where abandoning would rewrite trunk**;
* a working copy parked on an **ancestor of trunk** is unusable and unrecoverable — `repair`,
  `switch`, `start` and `describe` all decline, and no verb moves `@` forward;
* `status --json` reports `conflict: false` for the exact lane `sync` just called conflicted.

---

## 2. How we hit it

Starting shape — a 10-lane stack, trunk-rooted base `narrative-replay` (draft, 12 behind
trunk) with three children, one of which carried a 6-deep published chain:

```
narrative-replay                                   draft      10 changes, 12 behind trunk
  narrative-replay+allowed-vocabulary-prompt        draft       1 change   (+321  −40)
  narrative-replay+narrative-experiments            published   1 change   (+5418  −6)
  narrative-replay+provider-parity                  published   1 change   (+1266 −161)
    …+ceiling → …+validation → …+full-run → …+quality → …+structured-followup
      → …+pipeline-retrospective
```

Goal: land the whole subtree into trunk.

### 2.1 What worked

`gitman workspace forget` (keeps the directory), `sync --all` for the first pass, and eight
consecutive `gitman land <name>` folds all behaved correctly. `land --dry-run` correctly
refused and **named all three blocking children** — a genuinely good message:

```
Gitman land — BLOCKED
landed: none
lane 'narrative-replay' has a live child stacked on it (narrative-replay+allowed-vocabulary-prompt,
narrative-replay+narrative-experiments, narrative-replay+provider-parity) — fold the child in
first (`gitman land narrative-replay+allowed-vocabulary-prompt`).
```

After the `provider-parity` chain folded, `narrative-replay` held 17 changes, `behind=0`,
`conflict=false`.

### 2.2 The deadlock

The two remaining siblings now needed rebasing onto the advanced base. Every attempt produced:

```
Gitman sync — CONFLICT
rebased embedding-plot-arc-integration, evaluation-hardening, narrative-replay, stage6-forensics,
stage6-tower-audit.
note: conflicts in …+allowed-vocabulary-prompt, …+narrative-experiments — not blocked;
`gitman resolve` (a stacked lane is left on its prior base — sync its base, then re-sync),
then continue.
```

Note the two siblings are **absent from the `rebased` list**. And afterwards:

| Lane | `behind` | `conflict` |
|---|---:|---|
| `narrative-replay` (the base) | 0 | false |
| `…+allowed-vocabulary-prompt` | **7** | **false** |
| `…+narrative-experiments` | **7** | **false** |

`gitman resolve --list` listed only two *unrelated* lanes:

```
Gitman resolve — CONFLICTS
conflicted lanes: evaluation-hardening, evaluation-hardening+x4-path-h-controlled
Not blocked — edit the files (jj markers: <<<<<<< %%%%%%% +++++++ >>>>>>>), then continue.
```

So: `sync` says these two lanes conflict. `status` says they do not. `resolve` does not know
about them. They stay 7 behind forever.

The note's own advice — *"sync its base, then re-sync"* — was **already satisfied**: the base
was `behind=0`. We re-ran `sync --all` twice more, and ran `sync` while standing on the lane in
a healthy dedicated workspace. Identical result every time.

We were then stuck in a closed loop:

* `land <child>` → `BLOCKED — lane conflicts with its base 'narrative-replay' — gitman sync, resolve, then land`
* `sync` → declines to rebase, leaves it on the prior base
* `resolve` → does not list it
* `land <base>` → `BLOCKED — has a live child`

**The only exit was `gitman abandon <child>`**, discarding `+5418 −6` of probe scripts and a
`+321 −40` provider fix. We backed both up by `cp -a` out of the workspace directories first,
because gitman offered no way to preserve them.

### 2.3 Refusals that recommend a destructive action

Two workspaces had `@` on an **unnamed, empty** change. `gitman switch` refused:

```
Gitman switch — REFUSED
reason: uncommitted work on an unnamed change would be stranded — `gitman describe -m …`
(if it's a lane), `gitman start <name>` (to name it), or `gitman abandon` first.
```

Both times we checked ancestry ourselves before acting:

```
$ gitman log --revset "::main & nkzoropqmlllpnznmmlplwympkskrrlo"
nkzoropqmlllpnznmmlplwympkskrrlo          # ← it IS an ancestor of trunk
$ gitman log --revset "::narrative-replay & mtnokxvpwrnurzwwpxlnppponkwzqxlu"
mtnokxvpwrnurzwwpxlnppponkwzqxlu          # ← ancestor of the lane head, 9 descendants
```

Both changes reported `files_changed: 0, insertions: 0, deletions: 0`. Both were **ancestors**.
Following gitman's own `abandon` suggestion would have **rewritten trunk and every lane** in the
first case, and rewritten 9 changes in the second. Nothing in the refusal message distinguishes
"empty leaf, safe to drop" from "ancestor of trunk, catastrophic to drop".

### 2.4 A working copy parked on an ancestor of trunk is unrecoverable

The default (repo-root) workspace had `@` on an older trunk commit — 0 file changes, an ancestor
of `main`. Every recovery verb declined:

| Command | Result |
|---|---|
| `gitman repair` | `CLEAN — already canonical, no strays, refs in sync` |
| `gitman switch <lane>` | `REFUSED — uncommitted work on an unnamed change would be stranded` |
| `gitman start <flat-name>` | `REFUSED — @ holds uncommitted work that is not based on trunk 'main'` |
| `gitman describe -m …` | `REFUSED — not on a lane` |
| `gitman sync` | `REFUSED — not on a lane` |

`status` showed `current_lane: null` and a persistent note *"working copy @ has unbookmarked
work — `gitman start <name>` to adopt it into a lane"* — advice that `start` itself refuses.
The repo's default workspace was unusable for lane work for the entire session; we had to
borrow a different lane's workspace to make any progress.

Note also that `repair` calling this state **CLEAN** is itself a reporting gap: `status` prints a
`run gitman repair` hint for it, then `repair` finds nothing to do.

### 2.5 `sync --all` has no narrower form

We needed to rebase one subtree. There is no `gitman sync <lane-name>` and no `--subtree`, so
`--all` was the only option from outside a workspace. It rebased `evaluation-hardening` (45
behind trunk, unrelated, explicitly out of scope) and left it **permanently conflicted**. That
lane is still conflicted now, as collateral damage of a command aimed at a different subtree.

### 2.6 Remote-branch deletion is invisible to `--dry-run`

Eight `land` operations each printed:

```
note: deleted remote branch '<lane>' (one-way; `gitman undo` won't restore it).
```

`land --dry-run` never mentioned this. A dry run that omits the only irreversible effect of the
intent is the one case where dry-run matters most.

---

## 3. What we expected instead

### 3.1 A conflicted rebase should be enterable

Either:

* **(preferred)** `sync` should *apply* the rebase and record jj conflicts in the lane — which is
  what the note already promises ("not blocked … edit the files") and what it does for
  trunk-rooted lanes. Then `resolve --list` shows the lane, the markers are on disk, and the
  operator can resolve and continue; or
* `sync` should **refuse loudly** (`REFUSED`, non-zero exit) and say plainly: *"lane X cannot
  rebase onto its base without conflict; gitman cannot currently materialise this conflict for a
  stacked lane. Options: …"* — instead of reporting `CONFLICT` and then silently doing nothing.

The current behaviour is the worst of both: it claims a conflict exists, does not apply it, and
points at a verb that cannot see it.

### 3.2 `status` and `sync` must agree

If `sync` names a lane as conflicted, `status --json` must report `conflict: true` for it, or
`sync` must not name it. A consumer script cannot currently determine whether a lane needs
resolution.

### 3.3 A non-destructive escape from the deadlock

Any one of these would have saved the session:

* `gitman land <base> --detach-children` — land the base, leave the children re-rooted on the
  new trunk (they'd then be trunk-rooted lanes needing their own rebase);
* `gitman reparent <lane> --onto <trunk|lane>` — or, since a lane's base is derived from its
  name, a `gitman rename <old> <new>` that re-roots by renaming;
* `gitman split`-like extraction that lifts a child's own change onto a fresh trunk-rooted lane;
* failing all of those, `gitman abandon --save-patch <path>` so the discarded change is at least
  recoverable without a manual `cp -a`.

### 3.4 Classify a change before suggesting `abandon`

Any refusal that offers `abandon` should first determine whether the change is an ancestor of
trunk or of any lane, and whether it has descendants. Suggested message shape:

```
Gitman switch — REFUSED
reason: @ is on an unnamed change (0 file changes) that is an ANCESTOR of trunk 'main'
        with 9 descendants. Do NOT abandon it — that would rewrite trunk and every lane.
fix:    `gitman switch --trunk` to reseat @ on trunk's tip.
```

The safety-critical fact (ancestor vs leaf) should never be something the operator has to
discover by hand-writing revsets.

### 3.5 A verb to reseat `@`

`gitman switch --trunk` (or `gitman switch main`) to move a stranded `@` onto trunk's tip. Or
`repair` should reseat an off-lane, empty `@` onto trunk and report it as a fix — rather than
reporting `CLEAN` while `status` simultaneously advises running `repair`.

### 3.6 Narrower `sync` targeting

`gitman sync <lane-name>` (from anywhere, no workspace needed) and `gitman sync <lane>
--recursive` for a subtree. `--all` should not be the only way to rebase a lane you are not
standing in.

### 3.7 `land --dry-run` should enumerate irreversible effects

Specifically the remote branches it will delete.

---

## 4. Minimal repro sketch

1. Create a trunk-rooted lane `T` with a change touching `foo.py`.
2. Create two children, `T+a` and `T+b`, each independently modifying the **same lines** of
   `foo.py`.
3. `gitman land T+a` — succeeds, `T` advances.
4. `gitman sync --all` — reports `conflicts in T+b — not blocked; gitman resolve … then continue`.
5. `gitman status --json` — `T+b` shows `conflict: false`, `behind: 1`.
6. `gitman resolve --list` — `T+b` absent.
7. `gitman land T+b` — `BLOCKED — conflicts with its base`.
8. `gitman land T` — `BLOCKED — has a live child`.
9. No non-destructive exit exists.

---

## 5. What gitman got right, for the record

* `workspace forget` keeping the directory is exactly the right default, and it is what made
  the manual content backup possible at all.
* `land --dry-run` naming every blocking child by name is a genuinely good refusal.
* `[lane]` markers in `workspace list` made the topology legible.
* Whole-intent `undo` meant every reversible step felt safe to attempt.
* The ten sequential `land` folds were fast and reported clearly.

The deadlock is narrow. Everything around it worked.
