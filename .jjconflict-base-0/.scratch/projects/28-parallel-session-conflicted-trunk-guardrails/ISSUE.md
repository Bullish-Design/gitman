# 28 — Parallel-session conflicted trunk: guardrails so it never happens again

**Status:** open · **Date:** 2026-07-24
**Reported from:** a downstream consumer repo (`flora`) that uses gitman via the bundled skill.
**Severity:** high — gitman entered a state its own recovery commands could not exit (soft-lock),
and `status` actively reported the repo as healthy while it was broken.

---

## 1. Executive summary

In a consumer repo, **two agent sessions ran gitman concurrently** against the same colocated repo.
Their jj bookmark updates interleaved and left the `main` **bookmark conflicted** (pointing at both
a local commit and `origin/main` at once). From there:

- `gitman status` reported **`CANONICAL · 1 lane`, "2 ahead origin"** — i.e. *healthy* — while the
  trunk was in fact conflicted and diverged and did **not** contain origin's latest work.
- `gitman pull`, `gitman reconcile`, and `gitman reconcile --abandon` **all bailed out** with the
  same error — *"a bookmark diverged from its pushed branch (Name `main` is conflicted) — run
  `gitman reconcile`"* — and `reconcile` hit the same guard. **Infinite loop, no exit.**
- `jj` is not on PATH in that environment (gitman drives pyjutsu as a library), so there was **no
  CLI escape hatch** to hand-resolve the bookmark. The consumer had to stop and clear the other
  session manually.

No data was ultimately lost, but proving that required extensive manual forensics (tree-hash
superset checks, hand-recorded restore SHAs) that gitman should have made unnecessary.

This is the known `parallel-session-shared-worktree-hazard`, escalated: instead of one save
swallowing another's work, concurrency took out **trunk itself** and put gitman into a
non-recoverable-via-gitman state.

---

## 2. Reproduction (essence)

1. Repo colocated, on trunk `main`, tracking `origin/main`.
2. Session A begins a land/save; Session B runs a gitman mutating command against the same repo at
   an overlapping time.
3. The two jj bookmark moves interleave → `main` bookmark becomes conflicted (local land + moved
   origin).
4. Observed downstream state:
   - `gitman status` → `CANONICAL`, `trunk: main @ <local> (2 ahead origin)`.
   - `gitman doctor` → `XX trunk 'main' not found`, `!! colocated-refs 1 leftover git ref: main`.
   - `gitman pull` → `BLOCKED … Name 'main' is conflicted — run gitman reconcile`.
   - `gitman reconcile` / `reconcile --abandon` → same error. Loop.

---

## 3. Root-cause analysis

### 3.1 Primary — no concurrency control
Nothing serializes gitman mutating operations. Two sessions can interleave jj bookmark writes and
produce a conflicted trunk. There is no advisory lock and no "another gitman is running" detection.

### 3.2 `status` under-reports danger (trust bug)
`status` and `doctor` disagree: `status` said `CANONICAL` while `doctor` said `PROBLEMS` for the
same repo state. `status` is the command everyone runs; if it can be wrong about the single most
important invariant (is trunk healthy?), the whole tool feels untrustworthy. Additionally,
"2 ahead origin" was misleading — the local trunk had **diverged**, not fast-forward-advanced.

### 3.3 Recovery soft-locks on the condition it exists to fix
`reconcile` is documented as off-canonical recovery, yet refuses to run when the bookmark is
conflicted — which *is* an off-canonical condition. `pull` defers to `reconcile`; `reconcile`
defers to itself. The recovery path is gated behind a precondition only the recovery path can
establish → guaranteed loop.

### 3.4 No escape hatch when jj CLI is absent
gitman-as-a-library (pyjutsu) is great for embedding, but it means that when gitman itself is stuck,
there is no lower-level `jj` command available to resolve the bookmark. gitman must therefore be
able to resolve *every* state it can produce; there is no fallback.

### 3.5 Contributing — reconcile/rebase churn leaves strays
Earlier recovery attempts (and likely the concurrent ops) left a fan of duplicate-tree and
empty-message commits that were never cleaned up, turning any later investigation into archaeology.

---

## 4. The workflow we want gitman to guarantee

The consumer's explicit goal: gitman is **one opinionated, guardrailed workflow**, not a thin skin
over jj's flexibility. The whole happy path is:

```
gitman start <name> → save -m "…" → sync → land → push
```

Detached HEADs, conflicted bookmarks, diverged trunk, orphan snapshots, and concurrent writers are
states the user must **never** have to reason about. gitman should make them **unreachable**, or
**auto-heal** them, or **refuse** the operation that would create them — but never report
`CANONICAL` and let one fester, and never soft-lock.

---

## 5. Proposals (ordered by impact)

The top three each would independently have prevented this incident.

### P1 — Concurrency lock ⭐ (kills the root cause)
- Acquire an advisory lock (e.g. `.jj/gitman.lock`: PID + host + session id + command + timestamp)
  at the start of any mutating command; release on exit.
- If held → refuse: *"another gitman operation is running (session <id>, started <t>) — wait, or
  `gitman unlock --force` if stale."*
- Auto-expire stale locks (dead PID / age > N min) with a clear message.
- Directly prevents interleaved bookmark writes.

### P2 — `status` must never lie ⭐
- `status` runs the same invariants as `doctor`. It must **never** print `CANONICAL` when the
  bookmark is conflicted, trunk is diverged, or a leftover git ref exists.
- Add explicit `CONFLICTED` / `DIVERGED` headlines with the single fix command.
- Replace "N ahead origin" with divergence-aware wording when local trunk is not a fast-forward of
  origin.

### P3 — Recovery must resolve a conflicted trunk, never loop ⭐
- `reconcile` and `pull` must be able to resolve a conflicted `main` bookmark themselves.
- Provide opinionated resolutions for the common case:
  - `gitman reconcile --take-origin` → trunk becomes `origin/<trunk>`; local lands already present
    upstream are dropped (empty), genuinely-new lands are rebased onto origin.
  - `gitman reconcile --keep-local` → inverse.
  - Default: print the recommended one and the exact command; never dead-end.

### P4 — Auto-heal on entry
- `start` / `save` / `sync` / `land` detect a conflicted/diverged trunk up front and either
  auto-resolve when unambiguous (e.g. local lands ⊆ origin → fast-forward trunk to origin) or stop
  with one prescriptive command. Never proceed silently on a broken trunk.

### P5 — No detached HEAD, no stray commits left behind
- After every op, ensure `@` is on a lane or trunk — never detached.
- Detect and offer to remove empty-message and content-duplicate commits from prior churn:
  *"9 stray snapshots on no lane — `gitman gc` to remove."*

### P6 — `gitman doctor --fix`
- One command that diagnoses **and** applies the safe opinionated repair for each check (resolve
  conflicted bookmark → origin, drop leftover refs, re-park `@`, gc strays), showing a plan and
  confirming once. Today doctor diagnoses but every fix command loops — that's the trap.

### P7 — Loss-proofing surfaced by default
- Every mutating op stamps a restore ref (op-log already helps). Advertise it in every error:
  *"restore with `gitman undo` / `gitman undo --op <id>`; list with `gitman undo --list`."*
  Consumers should never need to hand-record SHAs to feel safe.

### P8 — Structural guard vs. concurrent sessions
- Reinforce (and, ideally, detect) the "isolate concurrent work with `gitman start --workspace`"
  guidance. Warn at `start` if a second live workspace/session is detected. Complements P1.

---

## 6. Acceptance criteria

- Two concurrent gitman mutating commands in one repo → the second is cleanly **refused**; no
  conflicted bookmark can result.
- `gitman status` **never** reports `CANONICAL` when `gitman doctor` reports `PROBLEMS`.
- From any conflicted/diverged trunk, **one** documented command resolves it — no loop, no reliance
  on a `jj` CLI that may be absent.
- After any op, `@` is on a lane/trunk (never detached), with no empty/duplicate strays (or they're
  reported with a gc command).
- The happy path `start → save → sync → land → push` never requires reasoning about jj internals.

---

## 7. Appendix — downstream incident specifics (for reference)

Consumer repo: `flora`. The trigger was a pushed feature appearing "missing" on another machine
because the local checkout was parked on a conflicted/diverged `main` that lacked it.

- Conflicted `main` was between a local land (065 runner work, already contained in and superseded
  by `origin/main`) and `origin/main` itself.
- Desired resolution was trivial once the bookmark was un-conflicted: trunk → `origin/main`, drop
  the redundant local land, rebase+land the one real outstanding lane, push. gitman could not get
  there on its own because of the loop in §3.3.
- Root cause per the user: a second agent session using gitman concurrently.
