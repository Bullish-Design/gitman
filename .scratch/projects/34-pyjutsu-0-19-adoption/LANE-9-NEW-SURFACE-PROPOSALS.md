# Lane 9 — proposals for the new pyjutsu surface

Deliverable of guide 2, lane 9. **Proposals only.** No intent was added, and no code changed in
this lane. Each candidate below states what it would buy, what it would cost, and whether it needs
a concept decision before code. The owner picks.

Engine: pyjutsu 0.20.0 / jj-lib 0.44.0.

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

**Use.** `status` reports conflicted files by name via `view.conflicts("@")`.

**Buys.** The report could show which sides conflict and how large the conflicted region is, so an
agent can decide whether to resolve or to abandon without opening the file.

**Costs.** Content in a report means content in `--json`, which means a model change (`ConflictFile`
gains fields) and a size question. Conflicts can be large.

**Recommendation.** Adopt `conflict_sides` (structural, small, bounded). Leave `conflict_content`
behind a flag if it is wanted at all.

---

## 5. `tx.resolve_conflict(path, content)` — a real `gitman resolve`

**Use.** Gitman reports conflicts and tells the operator to resolve them on disk.

**Buys.** A first-class `gitman resolve <path>` intent, so an agent that has computed a resolution
can apply it through gitman instead of writing the file and re-snapshotting.

**Costs.** A new intent, a new report shape, and a real design question: does `resolve` take content
on stdin, from a file, or a strategy name (`--ours`/`--theirs`)? Each is a different contract.

**Recommendation.** **Needs a concept decision before code.** The plumbing is ready; the interface
is not designed. Worth a short design note of its own.

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

**Costs.** Each is a new intent with its own report, guards, and undo semantics. `absorb` in
particular rewrites several commits at once, which interacts with the lane 6 immutability policy:
absorbing into a tagged commit must refuse the whole operation, not half of it.

**Recommendation.** **Out of scope without a design decision.** If one is picked, pick `absorb`.

---

## 8. `Workspace.load(..., sign_behavior=…)` — commit signing

**Use.** None today. Gitman writes unsigned commits.

**Buys.** Repositories that require signed commits could be driven by gitman at all. Today they
cannot without a post-hoc re-sign.

**Costs.** A configuration design (where does the key come from? per-repo or per-agent?), a failure
mode when signing is unavailable, and a `doctor` check. It also touches every mutating intent.

**Recommendation.** **Needs a concept decision.** The right first step is a `doctor` check that
*detects* a repo requiring signatures and says gitman cannot satisfy it, rather than silently
writing unsigned commits.

---

## Summary

| Candidate | Verdict |
|---|---|
| `shortest_prefix` for `reconcile` lane names | Adopt — fixes a latent correctness bug |
| `file_content` for the version read | Adopt, scoped to file sources, hook stays |
| `evolution` in `undo --list` | Adopt — additive |
| `conflict_sides` in `status` | Adopt; `conflict_content` behind a flag |
| `file_list` in reports | Only behind `--files` |
| `tx.resolve_conflict` | Design note first |
| `tx.absorb` | Design note first; `duplicate`/`fix` out of scope |
| signing | Design note first; start with a `doctor` detection |
