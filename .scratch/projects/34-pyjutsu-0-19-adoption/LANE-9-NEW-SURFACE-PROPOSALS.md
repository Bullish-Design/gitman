# Lane 9 — proposals for the new pyjutsu surface

Deliverable of guide 2, lane 9. **Proposals only.** No intent was added, and no code changed in
this lane. Each candidate below states what it would buy, what it would cost, and whether it needs
a concept decision before code. The owner picks.

Engine: pyjutsu 0.20.0 / jj-lib 0.44.0.

> **Revised 2026-08-27.** The first draft of this document stated three things that the API and the
> gitman source contradict. Each is corrected in place below, and each changed the recommendation:
>
> 1. **Gitman already signs** (§8). `session.py:71` calls `Workspace.load(start)` with no
>    `sign_behavior`, so jj's own `signing.behavior` setting applies. The draft claimed gitman
>    writes unsigned commits.
> 2. **`gitman resolve` already exists** (§5). `cli.py:343` / `core.py:2181` ship a read-only
>    `resolve [--list]`. The decision is a write *mode*, not a new intent.
> 3. **`tx.absorb` carries a trunk hazard** (§7) that the draft did not name: its `into` default is
>    `mutable()`, which includes trunk on any repo where the `trunk()` term is inert.
>
> All three decisions are now taken. See the summary table at the end.

---

## 0. Already free — no work needed

**Bounded `log`.** `log(revset, limit=N)` now truncates commit ids before loading commit objects.
Gitman's seventeen `view.log()` calls benefit with no change. Measured on the gitman repository
itself (86 commits in `::@`), the effect is present but small at this size:

| Call | Rows | Time |
|---|---|---|
| `log("::@", limit=1)` | 1 | 0.5 ms |
| `log("::@", limit=10)` | 10 | 0.8 ms |
| `log("::@")` | 86 | 3.2 ms |

The published figure (818 ms → 6.7 ms) is for a 100,000-commit repository. Gitman is nowhere near
that, so this is a "costs nothing, scales for free" item, not a present-day win. Worth remembering
if gitman is ever pointed at a monorepo.

**Secondary workspaces are first-class.** The old caveat — that a commit authored from a secondary
workspace could differ in commit id from the CLI's, because a secondary `.jj/repo` is a pointer file
that skips the repository settings layer — is fixed in pyjutsu 0.16. Checked: no gitman comment
repeats that caveat, so there was nothing to delete.

---

## 1. `view.file_content(path, rev)` — read a version file without a subprocess

**Use.** `version.read_version` runs a user-configured **read hook** as a subprocess to get the
current version string. For the common cases (`pyproject.toml`, a plain `VERSION` file) the value
could be read straight out of a revision.

**Buys.** One less subprocess on the release path, and — the real gain — the ability to read the
version *at a revision* rather than from the working tree. `gitman release` could then report the
version trunk actually carries, not the version currently on disk.

**Costs.** The hook surface is a documented extension point and must stay. This would be a fast
path *beside* it, not a replacement, so it adds a branch to keep honest. Parsing `pyproject.toml`
in-process also means gitman owns a TOML read it does not own today.

**Recommendation.** Worth doing, scoped narrowly: use `file_content` only when the configured
version source is a plain file gitman already understands, and fall back to the hook otherwise.
Needs no concept decision.

---

## 2. `view.file_list(rev, paths)` — list lane contents in reports

**Use.** `status` and `land` reports currently carry file *counts* (`files_changed`, `+n −m` from
`diff_stat`).

**Buys.** A lane report could name the files it touches, which is what an agent usually wants next.

**Costs.** Report width. Gitman's reports are deliberately compact, and a lane touching forty files
would swamp the output. It would need a cap and a `… and N more` tail, which is a report-design
decision, not a plumbing one.

**Recommendation.** Only behind an explicit flag (`gitman status --files`). Low value, low risk.

---

## 3. `view.shortest_prefix(id)` — shorten commit ids in reports

**Use.** Gitman slices ids by hand: `cid[:12]`, `git_id[:8]`, `commit_id[:8]` in lane names.

**Buys.** A prefix guaranteed to resolve back to the same commit. Today's fixed slices are a guess
that happens to work; on a large repository an 8-hex prefix can become ambiguous, and the
`adopted-<commit_id[:8]>` lane names in `reconcile` are the sharp edge — an ambiguous prefix there
produces a lane name that does not resolve.

**Costs.** Report ids become variable-width, which makes column alignment slightly harder.

**Recommendation.** **The strongest candidate in this list.** Adopt it for the `reconcile` lane
names first (correctness, not cosmetics), and consider it for report display second. Needs no
concept decision.

---

## 4. `view.conflict_content` / `view.conflict_sides` — richer conflict reports

**Use.** `status` reports conflicted files by name via `view.conflicts("@")`. `do_resolve`
(`core.py:2197`) already prints each path with its `num_sides`, so part of this is shipped.

**Buys.** The report could show the sides themselves, so an agent can decide whether to resolve or
to abandon without opening the file.

**Costs.** Content in a report means content in `--json`, which means a model change (`ConflictFile`
gains fields) and a size question. Conflicts can be large.

**Recommendation.** Adopt `conflict_sides` (structural, small, bounded) — it pairs with §5's write
mode. Leave `conflict_content` to §5's `--show`, where the marked text has a caller that needs it.

---

## 5. `tx.resolve_conflict(path, content)` — a write mode for `gitman resolve`

**Correction.** The intent exists. `cli.py:343` declares `resolve [--list]`, and `core.py:2181`
implements it as a read: it lists conflicted paths at `@` with their side count, returns exit 1
`CONFLICTS`, and tells the operator to edit the files on disk. What is missing is the **write**
half, not the intent.

**What the binding gives.** `tx.resolve_conflict(path, content)` rewrites `@` **only**, preserves
the change id, and **honors conflict markers left in `content`** — so a partial resolution is a
legal, expressible outcome. It raises `ConflictError` for a path that is not conflicted, and
`ImmutableCommitError` for an immutable `@`. UTF-8 only; binary is out of scope. `@`-only is not a
gap: `do_resolve` reports conflicts at `@` and nowhere else.

**The options considered.**

| | A — content in | B — side selection | C — both | D — stay read-only |
|---|---|---|---|---|
| Shape | `resolve <path> --from <file>` or stdin | `resolve <path> --take <n>`, over `conflict_sides` | A plus B | `conflict_sides` in the report only |
| Pro | Matches how an agent works: it computed the merged text, it writes the merged text | No content round trip for the common case | Covers both cases | No new surface |
| Con | Needs a paired read of the marked text | **The vocabulary is unsound.** jj conflicts have N sides; `--ours`/`--theirs` is git wording that maps cleanly only onto a regular 3-way | B's naming problem survives, plus two ways to do one thing | An agent that computed a resolution still writes a file and re-snapshots |
| Implication | `resolve` gains an exit-0 outcome (cleared); partial stays exit 1, honest because the markers survive | Must refuse `num_sides > 2` or select by index, which reintroduces A's read | Both of the above | None |

**Decision: A, with the paired read.** Ship `gitman resolve <path> --show` (marked text out, via
`conflict_content`) and `gitman resolve <path> --from -` (resolved text in). That closes the loop
for an agent, invents no vocabulary, and leaves `--take` available later if the mechanical case
proves common. `ImmutableCommitError` routes into lane 6's `explain_immutable` with no new work.

---

## 6. `view.evolution(change_id)` — lane history for `gitman undo`

**Use.** `gitman undo` reports the operation it reverted.

**Buys.** `undo` could show how a change evolved (described, squashed, rebased) rather than only
which operation was rewound, which makes the "is this the undo I want?" question answerable from
the report.

**Costs.** Read-only and additive, so the cost is report width again.

**Recommendation.** Adopt for `gitman undo --list`, where the operator is already reading history.
Needs no concept decision.

---

## 7. `tx.absorb`, `tx.duplicate`, `tx.fix` — new intents

**Use.** None today.

**Buys.** `absorb` (fold working-copy edits into the commits that introduced the lines) is a genuine
fit for the lane model and would be a strong `gitman absorb`. `duplicate` and `fix` are further from
gitman's concerns.

**The signature.** `tx.absorb(source, into="mutable()")` → `AbsorbResult(rewritten_source,
rewritten_destinations, num_rebased, skipped_paths)`. Only ancestors of `source` are candidates.
Each hunk moves to the closest mutable ancestor that last touched its lines; **hunks with no unique
ancestor stay behind** — absorb is partial by design. An immutable source is refused. The source is
abandoned when it becomes empty and carries no description.

**The hazard the first draft missed.** The `into` default is `mutable()`. Per
[`LANE-6-IMMUTABILITY-AUDIT.md`](LANE-6-IMMUTABILITY-AUDIT.md) §6, the `trunk()` term of
`immutable_heads()` is **inert** on a repo whose trunk is not named `main`/`master`/`trunk`, or that
has no remote yet — and gitman supports exactly those repos (the local-authored trunk model,
projects 16–21). On such a repo trunk commits are inside `mutable()`, so an unscoped absorb can move
a hunk into a trunk commit. That violates I1 (trunk frozen) and I5 (trunk advances only via `land`).
`canonical_guard` would catch it and roll back — but after the fact, which is the one place gitman
deliberately does not rely on the postcondition.

**Decision: build `gitman absorb`, with `into` pinned to the lane's own range** (`lanes.lane_base`
… head), never the `mutable()` default. Scoped that way it cannot cross the lane base, so it
inherits the same "no invariant exemption" property §D5 claims for squash/reorder, and the guard
becomes a second belt rather than the first. It diverges from `jj absorb` semantics, so the docs
must say why. `skipped_paths` and `num_rebased` map straight onto a compact honest report — the
fields for saying "partial" are already in the result.

**Pin at build time:** when `source` is `@` and `@` carries the lane bookmark, an emptied source is
abandoned and the bookmark moves to the parent. That is canonical, but the report must name it.

`duplicate` and `fix` stay out — neither has a lane-model story.

---

## 8. `Workspace.load(..., sign_behavior=…)` — commit signing

**Correction.** The first draft said gitman writes unsigned commits and that a repo requiring
signatures could not be driven by gitman. Both are false. `session.py:71` calls
`Workspace.load(start)` and passes no `sign_behavior`. The default `None` means "use jj's own
`signing.behavior` setting", so **gitman already signs wherever the repo's jj configuration says to
sign**. `doctor.py:98` and `core.py:516` load the same way.

**What the knob actually is.** `sign_behavior` takes `'drop' | 'keep' | 'own' | 'force'`. The
backend and the key still come from jj's `signing.*` configuration — pyjutsu adds no configuration
keys of its own. With no backend configured, nothing is signed whatever the value says. So the knob
cannot make an unconfigured repo sign; it can only change behaviour where a backend exists.

**What is genuinely missing** is visibility. `Commit.is_signed` is a plain read field, and
`CommitSignature` carries `status`/`key`/`display`, but no gitman report mentions either.

**The options considered.**

| | A — observe only | B — expose an override | C — nothing |
|---|---|---|---|
| Shape | A `doctor` check reading `is_signed`; report the repo's signing posture | A `gitman.toml` knob mapping to `sign_behavior` | — |
| Pro | Consistent with decision 6d — gitman writes and owns no jj configuration. Answers the real question at near-zero cost | An operator could force signing without editing jj config | Today's behaviour is already correct |
| Con | Cannot make gitman sign where jj has no backend — but neither can B | **Two sources of truth for one policy**, and jj holds the key. Contradicts 6d. It applies per invocation, so it silently governs every mutating intent in that call | A misconfigured backend produces unsigned commits and gitman never says so |

**Decision: A.** One new `doctor` row — a `log` plus a field read. The same field feeds a
pre-`push` warning ("trunk's last land is unsigned") if that proves wanted. No configuration key.

---

## Summary

| Candidate | Verdict |
|---|---|
| `shortest_prefix` for `reconcile` lane names | Adopt — fixes a latent correctness bug |
| `file_content` for the version read | Adopt, scoped to file sources, hook stays |
| `evolution` in `undo --list` | Adopt — additive |
| `conflict_sides` in `resolve` / `status` | Adopt; the marked text ships as `resolve --show` |
| `file_list` in reports | Only behind `--files` |
| `tx.resolve_conflict` | **Decided** — `resolve --show` / `resolve --from -`; no `--ours`/`--theirs` |
| `tx.absorb` | **Decided** — build it, `into` pinned to the lane range; `duplicate`/`fix` out of scope |
| signing | **Decided** — `doctor` detection via `Commit.is_signed`; no configuration key |

The three items that the first draft left as "design note first" are resolved above. None of them
needs a further note; each is now a lane. They are catalogued in
[`24-deferred-backlog/BACKLOG.md`](../24-deferred-backlog/BACKLOG.md) as D8, D9, and D10 so that a
future session finds them where every other unbuilt item lives.
