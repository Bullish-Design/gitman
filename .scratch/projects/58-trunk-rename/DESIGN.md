# Design — `gitman trunk rename`

All line anchors below were read at trunk on 2026-10-01 (commit `25c9dc5`, "docs: add project 56
and 57 design documents"). Re-check each one before editing; an earlier change in another lane
shifts later line numbers. fsdantic's commit ids were re-verified directly against that repo
today, not taken on faith from the task brief: `git rev-parse origin/main` →
`56e2d5f394a97d68a5c1642104a9adeeff216983`; `git rev-parse
fix/materialization-remove-exdev-fallback` → `01ca33851a1a5f3dc4530b0e0e63b46a675fbb93`;
`git merge-base --is-ancestor origin/main fix/materialization-remove-exdev-fallback` succeeds;
`git rev-list --count origin/main..fix/materialization-remove-exdev-fallback` → `4`; `04c91ce07050`
resolves to a real commit ("chore: adopt central agent surface").

## 1. The structural fact, precisely

**jj is authoritative for bookmarks; the colocated git ref is only a projection of jj's state, never
an independent source of truth.** This is not a design preference — it is what the three closed
routes in `README.md` §2 all run into from different angles, and it is why a trunk rename needs a
gitman verb and cannot be approximated with raw git plus a config edit.

1. **Route 1 (raw git creates the ref) fails because "leftover" is a name-only classification that
   never looks at content.** `colocated_ref_desync` (`src/gitman/state.py:460-487`) reads every
   `refs/heads/<name>` the colocated git side holds (`state.py:473`, `_git_refs_heads(ws)`) and
   every **local jj bookmark** (`state.py:474-480`, filtering `b.remote is None and not
   b.conflicted`). A git ref whose name matches a jj bookmark can be `mismatched` (`state.py:481-485`,
   if the two commits differ) and only a `mismatched` row ever reaches `classify_ref_desync`
   (`state.py:697-714`), which is the one function that produces `adopt` vs `rewrite`. A git ref
   whose name matches **no** jj bookmark at all is `leftover` (`state.py:486`:
   `sorted(name for name in refs if name not in local)`) and never reaches `classify_ref_desync` —
   there is no name to adopt onto. `main` in fsdantic is exactly this: no jj bookmark named `main`
   exists (trunk's jj bookmark is named after the fix branch), so the freshly created
   `refs/heads/main` is `leftover` by construction, regardless of which commit it names.
2. **The keep-guard that could save a leftover ref evaluates content, and the content here always
   says "known."** `sync_colocated_refs`'s leftover loop (`src/gitman/invariants.py:471-477`) is:
   ```python
   for name in leftover:  # (2) retire before the import, else it re-creates the bookmark
       git_id = git_refs_before.get(name)
       if git_id and not _known_to_jj(view, git_id) and not _ref_commit_on_remote(session, git_id):
           kept_leftovers.append(name)
           continue
       try:
           session.ws.git.delete_ref(name)
           deleted_leftovers.append(name)
       except PyjutsuError:
           pass
   ```
   (the `if` body is `invariants.py:473-476`; the delete is `invariants.py:478-482`.) The guard only
   keeps a leftover when its commit is **unknown** to jj AND absent from every remote-tracking ref.
   `_known_to_jj` (`state.py:630-650`) is `view.resolve(commit_id)` succeeding — and in fsdantic the
   new `main` ref names a commit that is already a **strict ancestor of the existing, frozen trunk
   bookmark** (confirmed above: origin/main is 4 commits behind trunk, so its commit is on trunk's
   own ancestry line). jj has known that commit since the repo was colocated; there is no import
   step that could make it newly unknown. `_known_to_jj` returns `True` unconditionally for this
   shape, the guard's `if` never fires, and the ref is deleted. No history is lost — the commit
   stays reachable from the existing trunk bookmark — but the one new pointer that would have told
   gitman "this name means something now" is gone. This is not a bug to fix; it is proof that a
   bare git ref can never carry the semantic "promote me to trunk" past gitman's own ref-sync pass,
   because that pass only ever asks "is this content already known," never "did an operator name
   this on purpose."
3. **Route 2 (flip config first) fails because the one function that could import the missing
   bookmark validates the OLD trunk invariant before it ever runs.** `do_repair`
   (`src/gitman/repair.py:47-96`) takes its survey from `capture_state(session)` at `repair.py:101`,
   and `capture_state` (`src/gitman/state.py:791-794`) is:
   ```python
   try:
       trunk_commit = view.resolve(trunk_name)
   except RevsetError as exc:
       raise GitmanError(f"configured trunk '{trunk_name}' not found — run `gitman doctor`.", exit_code=2) from exc
   ```
   `trunk_name` here is `session.config.trunk`, already flipped to `"main"` by the hand-edit.
   `"main"` resolves to no jj bookmark (route 1 never landed one), so this raises before line 133's
   `REPAIRS` dispatch loop — the loop that imports colocated ref drift — ever gets a turn. The
   verb that could fix the mismatch refuses to start because of the mismatch.
4. **Route 3 (`init --colocate --trunk main`) fails on the one-shot guard, correctly — `init` is
   not a retrunk path.** `src/gitman/init.py:81-82`:
   ```python
   if config.trunk:
       raise GitmanError(f"already initialized (trunk '{config.trunk}' is frozen).", exit_code=3)
   ```
   This guard exists to enforce I1 (`docs/GITMAN_CONCEPT.md:104`: "Trunk is resolved once at
   `init`, written to config, frozen. Runtime never re-detects."); it is correct as written and this
   design does not propose weakening it. §2 question 1 argues why a *dedicated* rename verb is a
   different act from re-running `init`, not a loophole in it.

**Net:** there is no sequence of raw-git-plus-config-edit operations that reaches the desired state,
because every step either produces a shape gitman's own machinery classifies as noise and deletes
(route 1), or trips a validation that exists specifically to keep trunk from drifting silently
(routes 2 and 3). A verb is required because only a verb can create the new bookmark through
`tx.create_bookmark` (a jj-side write, not a git-side one) in the same breath that it updates
`gitman.toml` — the two halves of "trunk" that must never independently disagree.

## 2. What the operation must do atomically, and the order

**Step order** (inside one `canonical_tx`/`canonical_guard`-shaped intent, `do_trunk_rename`):

1. **Precheck** (before the transaction, using the OLD config): resolve `old_trunk =
   require_trunk(session.config)` (`core.py:144-147`); validate `new_name` with the existing lane
   allowlist (`validate_lane_name`, `lanes.py:103-128`) — trunk is a bookmark like any other and
   must obey the same `[A-Za-z0-9._-]` segment rule, no leading `-`, no `@`/whitespace; reject
   `new_name == old_trunk` (exit 3, nothing to do); reject `new_name` already a live local bookmark
   name (exit 3 — see §3 question 5 for the full table). This step reads `session.config` as it
   is today — nothing has moved yet.
2. **Resolve trunk's current commit** on the frozen, pre-transaction view: `trunk_commit =
   view.resolve(old_trunk).commit_id`. This is the exact commit the new bookmark will be created
   at — content-free by construction, since it is the same commit under a new name.
3. **Inside one jj transaction** (`session.ws.transaction("gitman:trunk-rename",
   auto_snapshot=False)`, the same shape `do_remote_add`/project 56's `do_bookmark_track` use):
   `tx.create_bookmark(new_name, trunk_commit)`. A bookmark write, not a rewrite — no commit is
   touched, so this needs no `canonical_guard` relaxation and passes no `ignore_immutable=True`
   (AGENTS.md: "Bookmark and tag writes are not rewrites and stay allowed"). Then, **inside the
   same transaction**, dispose of the old bookmark per the operator's explicit choice (§3 question
   3) — `tx.delete_bookmark(old_trunk)` for the default (retire) outcome, or nothing at all for an
   explicit `--keep-lane`. Doing both bookmark writes in one transaction means a crash between them
   can never leave the repo with two live trunks and no old one, or neither.
4. **After the transaction commits, still inside `repo_lock`:** rewrite `gitman.toml`'s `trunk` key
   (§4 below — a targeted text substitution, not `do_init`'s blind `write_text`, because by now the
   file may carry other hand-edited tables: `[lanes]`, `[publish]`, project 57's proposed `[lanes]
   exclude`, etc. — none of which this verb may touch). Then set `session.config.trunk = new_name`
   in-process, so every subsequent read in this same process (including the postcondition's own
   `capture_state` call) sees the new name immediately. This ordering — jj write, then file write —
   mirrors `do_init`'s own ordering (`init.py:116-125`: the bookmark is created inside the
   transaction at line 117, the file is written after, at line 124): the irreversible-feeling file
   write happens last, after the reversible jj-side mutation has already succeeded, which is also
   when it is most likely to succeed (if trunk creation failed, nothing has touched the file).
5. **Postcondition.** `_postcondition` (`invariants.py:302-351`) computes `trunk_moved =
   (after.trunk.commit_id != trunk_before) and intent not in TRUNK_ADVANCING`
   (`invariants.py:319`). Because the new trunk bookmark was created at the **same commit** the old
   one already named, `after.trunk.commit_id == trunk_before` holds — this is true automatically,
   not because `trunk-rename` needs to join `TRUNK_ADVANCING` (`invariants.py:200`, currently
   `frozenset({"land", "pull"})`). **`trunk-rename` must NOT be added to `TRUNK_ADVANCING`** — that
   set exists for intents that are allowed to move trunk's *content*; this one never does, and
   adding it would silently permit a future bug (a rename that also moves the commit) to pass a
   check it should fail. The one genuinely new postcondition fact: `after.trunk.name` differs from
   `before.trunk.name`, which no existing field compares (`_postcondition` only ever compared
   `commit_id`) — harmless today because nothing else reads `trunk.name` as an invariant, but
   worth a one-line comment at the call site so the next reader does not assume `_postcondition`
   checks the name too.

**Why the config write cannot be inside the pyjutsu transaction, and what that means for undo.**
`gitman.toml` is a plain file; pyjutsu's `ws.transaction()` only ever covers jj-side operations
(bookmarks, commits, working-copy state). A file write can never be rolled back by
`session.ws.restore_operation(op_before)` (`invariants.py:971`, `:981`, the mechanism
`canonical_guard`'s exception handler and `_postcondition`'s violation path both use). This is new
territory for gitman: **every existing mutating intent's undo story is "replay the op log
backwards"** (`write_undo_checkpoint`/`read_undo_checkpoint`, `invariants.py:55-66`, consumed by
`do_undo`, `core.py:3259-3330`), because every existing intent's only durable state is jj's op log.
`gitman.toml` has been write-once since `init` (`config.py:4-5`: "written once by `gitman init`,
then frozen") precisely because nothing after `init` has ever needed to change it — this design is
the first intent that does. **Recommendation: extend the undo checkpoint, not `gitman undo`'s
mechanism.** `write_undo_checkpoint` already writes a small JSON sidecar
(`invariants.py:55-58`: `json.dumps({"op": op_before, "intent": intent})`); add an optional third
key, `config_before: str | None`, carrying the exact pre-rename bytes of `gitman.toml` when the
intent touched it (`None` for every other intent, so the sidecar's shape for existing call sites is
unchanged). `do_undo` (`core.py:3259-3330`) gains one new branch: after `session.ws.undo()` /
`restore_operation` succeeds in reverting the jj-side bookmark changes, if the checkpoint carries
`config_before`, write it back verbatim before returning. This keeps the promise "one `gitman undo`
reverts all of it" literally true, at the cost of one new, narrowly-scoped field that only
`trunk-rename` ever populates.

## 3. The eight questions

### 3.1 Surface

**Decision: a new verb, `gitman trunk rename <new-name>`, under a new `trunk_app` Typer sub-app.**

| | A — `gitman trunk rename <new>` | B — flag on an existing verb | C — `init --retrunk` |
|---|---|---|---|
| Shape | New noun sub-app, mirroring `remote_app` (`cli.py:467-469`), `workspace_app` (`cli.py:580-581`), and project 56's proposed `bookmark_app` | A flag bolted onto `init`, `repair`, or `doctor` | A guarded flag on `init` itself |
| Pro | One verb, one job, discoverable by `gitman trunk --help`; room for a later `gitman trunk show` (a plain read, not proposed here) without inventing a second noun | No new sub-app | Reuses `init`'s existing trunk-resolution code path (`detect_trunk`, `init.py:24-37`) |
| Con | One more noun to document | `init` is refused the instant `config.trunk` is set (`init.py:81-82`) — any flag on it inherits that refusal and would need its own carve-out, which is indistinguishable from a second verb wearing `init`'s clothes. `repair` and `doctor` are read/recovery intents with no concept of "take an argument naming a new bookmark" anywhere in their signatures (`repair.py:47`, `doctor.py` has no mutating entry point at all) | Same problem as the flag option, sharper: `--retrunk` directly contradicts the guard two lines above it. Carving an exception into the one guard that enforces "frozen means frozen" is a strictly worse place to put a rename than a verb that never touches that guard at all |

`trunk` as the noun (not `bookmark`) because trunk is conceptually distinct from an ordinary lane
bookmark everywhere else in the codebase (`TrunkRef` is its own model, `models.py:104-119`; `I1` is
its own invariant; `doctor.py:106-110` has its own trunk check) — folding trunk operations under a
hypothetical `bookmark` noun (project 56's proposal) would make `gitman bookmark rename` ambiguous
between "rename a lane" (not something gitman does today — lanes are retired and re-started, never
renamed) and "rename trunk" (a wholly different, much rarer act). A dedicated `trunk` noun removes
the ambiguity and leaves room for it to grow its own small vocabulary (`trunk rename`, potentially
`trunk show` later) without colliding with lane vocabulary.

**Does this respect I1, or break it?** I1's own wording (`docs/GITMAN_CONCEPT.md:104`): "Trunk is
resolved once at `init`, written to config, frozen. **Runtime never re-detects.**" The verb this
design forbids is exactly re-detection — some later read of the repo (a fetch, a status call, an
agent's heuristic) silently deciding trunk should now point somewhere else, the failure mode I1
exists to prevent (`config.py:4-5` names the same thing: "nothing at runtime re-detects it").
`gitman trunk rename <new-name>` is not detection — it takes an explicit, named argument from an
operator who has to type the new name, runs under the same `repo_lock`/transactional discipline as
every other mutating verb, writes an undo checkpoint, and leaves an audit trail in both the jj op
log and the intent's own report. The distinguishing fact is **who decides**: I1 forbids the tool
deciding; this verb is the operator deciding, through the one channel gitman offers for a
deliberate, auditable change to frozen state. The same distinction already exists elsewhere in the
codebase for a different frozen fact: lane names are never auto-renamed by `status` or `sync`, but
`gitman repair`'s `lane-legacy-name` auto-migration (`lanes.py:73-90`) *is* an automatic, no-operator
-input rename — and that one is scoped to a narrow, unambiguous, single-interpretation case
(`/` → `+`). Trunk's rename has no such single-interpretation default (there is no "obviously
correct" new trunk name the tool could guess), which is exactly why it needs an operator-named
argument rather than an auto-repair, and why this design never proposes making it automatic. If a
future case arose where gitman wanted to auto-rename trunk with no operator input, *that* would
break I1; this does not, because the one thing I1's own text singles out — "re-detects" — never
happens here.

### 3.2 Atomicity — covered in §2 above

Step order, the undo-checkpoint extension, and why `trunk-rename` must not join `TRUNK_ADVANCING`
are all in §2. One addition: should the new bookmark's creation and the old bookmark's disposal be
two separate verbs (`trunk rename` creates, a second call retires) or one? **One.** A trunk that
is "half-renamed" — two live bookmarks, config still pointing at the old one or now pointing at the
new one with the old one undisposed — is a worse state than either endpoint, and the hazard in
§3.3 below means the gap between the two halves is not merely untidy, it is actively dangerous
(the old bookmark is retire-on-sight to `gitman sync --trunk` the instant the new bookmark exists,
whether or not `gitman.toml` has caught up). One call, one transaction, one undo checkpoint.

### 3.3 The old bookmark

After the rename, the old trunk name is a local bookmark at the exact same commit as the new
trunk — an empty lane, in the vocabulary `state.py:905-910` already uses for "a published lane
whose content is already in trunk." **This is not a cosmetic leftover; it is a live hazard**,
confirmed by reading the exact code path that would fire next:

- `trunk..old_name` is empty **immediately**, not just after a future push — same commit, zero
  commits in the range, from the moment `tx.create_bookmark(new_name, trunk_commit)` lands.
- `gitman sync --trunk` (CLI name; implementing function `do_pull`, `core.py:2541`; `"pull":
  ("sync", ("--trunk",))` is the kept deprecated alias, `cli.py:623`) retires **every** surviving
  lane whose range against trunk is empty, unconditionally:
  `_repair_lane_against_adopted_trunk` (`core.py:2339-2408`), the merge-commit branch at
  `core.py:2380-2385`:
  ```python
  if not session.view().log(f"{trunk}..{lane}"):  # merge-commit: already an ancestor of trunk
      pending = _retire_lane(session, trunk, lane, published_before, notes)
      if pending is not None:
          pending_remote_deletes.append(pending)
      retired.append(lane)
      return
  ```
  `_retire_lane` (`core.py:2256-2276`) deletes the **local** bookmark unconditionally
  (`tx.delete_bookmark(lane)`, line 2273) and returns the lane name for remote deletion when `lane
  in published_before` — and `published_before = _lane_index(session.view())[1]`
  (`core.py:2567`) is built purely from bookmark *existence* (`b.remote is not None`,
  `state.py:85-98`, read in full by project 56's `DESIGN.md` §1 step 5), **independent of the
  `tracked` flag**. In fsdantic the old name is published (it has a `<name>@origin` row) — tracked
  or not makes no difference to this check. Back in `do_pull`, the deletion itself:
  `core.py:2650-2653`:
  ```python
  for lane in pending_remote_deletes:
      session.ws.git_push(pick_remote(session.ws), lane, delete=True)
      notes.append(f"deleted remote branch '{lane}' (one-way; `gitman undo` won't restore it).")
  ```
  one-way, by the code's own comment. There is **no flag on `gitman sync --trunk`** to opt a
  specific surviving lane out of this retirement — `_repair_lane_against_adopted_trunk` has no
  `keep` parameter, unlike `do_repair`'s `--keep local|origin` or `_retire_remote_branch`'s `keep:
  bool` (`core.py:1784-1808`, used by `land`/`abandon`). This means **untracking the old bookmark's
  remote twin does not defuse this** (project 56's `bookmark untrack` changes `tracked`, not
  publication); the only thing that defuses it is the old bookmark not existing as a live,
  trunk-identical lane at all by the time anyone runs `gitman sync --trunk`.

So the old bookmark's fate cannot be "leave it, decide later" without the design naming the
landmine it plants. **Decision: `gitman trunk rename <new-name>` requires an explicit disposal
choice, defaulting to retire, with no silent default that could surprise an operator who does not
read this far:**

- **`--retire` (default).** `tx.delete_bookmark(old_trunk)` inside the same transaction as the
  create (§2 step 3). The commit is not touched — deleting a bookmark never deletes a commit, and
  it remains reachable from the new trunk bookmark forever. If the old name was published
  (`<old_trunk>@<remote>` exists), the verb reports this explicitly and offers the same choice
  `_retire_remote_branch` already gives `land`/`abandon` (`core.py:1801-1805`): `--keep-remote`
  leaves the forge branch alone ("no gitman verb removes it later; delete it on the forge, or with
  `git push <remote> --delete <old_trunk>` outside gitman" — reused verbatim, not reworded, so the
  same sentence means the same thing everywhere it appears); its absence deletes the remote branch
  in the same call, with the same one-way framing `land`/`abandon` already use. This is the
  **recommended** default disposal, because it is the only one that removes the hazard rather than
  deferring it.
- **`--keep-lane`.** The old bookmark survives as an ordinary published lane. The verb's own report
  names the hazard explicitly in its `notes` (not buried in `--help`): "kept '<old_trunk>' as an
  ordinary lane at the same commit as trunk — the next `gitman sync --trunk` will retire it
  automatically (and delete its remote branch, since it is published) unless you `gitman bookmark
  untrack` first or deal with it before then." This is honest rather than silent, but it is still
  one `gitman sync --trunk` away from exactly the forge-branch deletion this design exists to
  avoid, so it is offered, not recommended.
- **No flag given, and the old name is published with no clean default:** this design does **not**
  propose a silent default when the old name is tracked and published — see the exit-code table
  (§4) for the exact refusal. An operator who has not stated a preference is refused, not guessed
  for, mirroring `repair --keep local|origin`'s own precedent (project 56 `DESIGN.md` §3.7:
  "`repair` already has a precedent for leaving exactly this kind of call to the operator").

Never proposed: silently deleting the remote branch with no mention in the report, and silently
deleting a **tag** under any circumstance (trunk rename never touches tags; `tags()` is untouched
immutable territory, `core.py:209-213`, unrelated to this design entirely).

### 3.4 Config write

**No, the rename does not reuse `do_init`'s writer verbatim, and cannot safely.** `do_init`'s
writer (`init.py:123-124`) is:
```python
gitman_toml = repo_root / "gitman.toml"
gitman_toml.write_text(f'trunk = "{trunk}"\n{version_snippet}')
```
a blind whole-file overwrite — safe at `init` time only because the file does not exist yet (or,
per `init.py:93-96`, pre-existing config lived in `pyproject.toml` and is merely shadowed, never
edited). By the time a rename could run, `gitman.toml` may carry hand-authored tables this verb
must not touch: `[lanes]`, `[publish]`, `[release]`, `[land]`, `[policy]`, and project 57's proposed
`[lanes] exclude`. **The repo has no TOML-writing dependency at all** — confirmed: `grep -n
"tomli_w\|tomlkit" pyproject.toml` returns nothing; `config.py` only ever calls `tomllib.load`
(read-only, stdlib, Python 3.11+). Round-tripping a full TOML document safely needs a writer that
preserves comments and table order, which gitman does not currently depend on and this design does
not propose adding just for one line.

**Proposed writer: a targeted, verified text substitution**, not a parse-and-re-emit:
1. Read the raw text of `gitman.toml` (or `pyproject.toml`'s `[tool.gitman]` block — see below for
   why that case is refused in v1).
2. Regex-match exactly one top-level `trunk = "<value>"` line (anchored to line-start, matching
   `GitmanConfig.trunk`'s own type, `config.py:60`). Before writing anything, assert the matched
   `<value>` equals `session.config.trunk` (the value this process already loaded) — if it does
   not, the file was edited since this process started (a concurrent hand-edit, or config drift
   between what gitman believes and what is on disk), and the verb refuses rather than clobbering
   an edit it cannot see (exit 2 — see §4 table). Assert exactly one match; zero or more than one
   is also a refusal (zero: the key is absent even though `session.config.trunk` is set, which
   cannot happen via `do_init`'s own writer but could via a hand-edited file — refuse rather than
   append a second, conflicting line; more than one: the file is already malformed in a way this
   verb should not try to repair).
3. Replace only that line's value, write the file back, byte-identical elsewhere.
4. **Verify by re-parsing**: load the new file with `tomllib`, assert every key except `trunk`
   round-trips to the same value the pre-write parse produced. A failure here means the
   substitution corrupted something subtle (an adjacent multi-line value, an escaped quote this
   design did not anticipate) — refuse and restore the pre-write bytes immediately (this is the one
   piece of this verb that is its own tiny transaction, independent of the jj side, precisely
   because it is the one piece jj's transaction cannot cover — see §2's undo-checkpoint discussion).

**`pyproject.toml`'s `[tool.gitman]` case: refused in v1, not silently attempted.** `find_config`
(`config.py:153-168`) already documents that `gitman.toml` wins when both exist; a repo whose trunk
lives only in `pyproject.toml` is rarer (most repos get `gitman.toml` from `do_init`,
`init.py:123`) but real — and `pyproject.toml` carries tables this verb has no business touching
(`[project]`, `[tool.uv]`, `[build-system]`). The same regex-substitution approach is *riskier*
there, not safer: a `trunk = "..."` line could plausibly collide with an unrelated key in another
`[tool.*]` table, and the cost of getting it wrong is corrupting the file uv and the build backend
both depend on. **Decision: `gitman trunk rename` refuses (exit 2) when `find_config` reports the
source is `pyproject.toml`, naming the fix**: "trunk is configured in pyproject.toml's
`[tool.gitman]` — `gitman trunk rename` only writes `gitman.toml`. Move the `[tool.gitman]` table
into a `gitman.toml` file by hand, then retry." This is a real gap, honestly named rather than
silently risking a shared file, and a candidate follow-on once (if) the project takes on a real
TOML-writer dependency.

**Dirty file / absent key:** both handled by the verify-then-substitute steps above — "dirty"
(on-disk value does not match `session.config.trunk`) and "absent key" (zero regex matches) are
both refusals, not guesses.

### 3.5 Preconditions and refusals

| Precondition | Refuse / proceed | Exit |
|---|---|---|
| `new_name` already a live local bookmark (any lane) | Refuse — "'<new_name>' already names a lane; pick another name or retire that lane first." | 3 |
| `new_name` exists on origin at a different commit than current trunk | Refuse — the rename only creates a *local* bookmark; a same-named, different-commit remote branch would make the first `gitman push` immediately contentious (non-fast-forward or a silent adopt of unrelated history). Name the forge commit and point at `gitman sync --trunk` on the *new* name after a manual look, rather than proceed into a push conflict this verb did not cause and cannot resolve | 2 |
| `new_name` exists on origin at the **same** commit as current trunk | Proceed — this is the common, intended shape (fsdantic: `origin/main` already names an ancestor of trunk; the rename's new local `main` and `origin/main` differ in commit today, which is exactly the "4 ahead" state `gitman sync`/`push` already know how to report — see §3.6) | 0 |
| Current trunk has un-landed lanes | Proceed — a rename never touches any lane but the old trunk bookmark itself; every other lane's `base`/`+`-path resolution reads live bookmarks by name (`lanes.py`/`state.py:862-910`), and the new trunk bookmark is live under its own name from the moment the transaction commits, so nothing here is left dangling | 0 |
| `@` is dirty (uncommitted edits, from the same `_unbookmarked_dirty` check `do_start` uses, `core.py:700-701`) | Proceed — this verb only reads trunk's current commit and writes bookmarks/config; it never touches `@`. Unlike `do_start`'s adoption logic, there is no ambiguity about what a dirty `@` means here, because nothing about this verb depends on `@` at all | 0 |
| Repo is off-canonical (any blocking anomaly whose `blocks` set should include this intent) | Refuse, same mechanism every other mutating verb already uses: `precheck_canonical`/`subjects_for` (`invariants.py:203-249`, `:252-299`). `trunk` is **always** in `subjects_for`'s returned set (`invariants.py:232`: `subjects: set[Subject] = {Subject(kind="trunk", name=state.trunk.name)}`) for every gated intent, so any trunk-tier anomaly (`trunk-conflicted`, `trunk-diverged`, both `ALL_MUTATING`-scoped or near it, `anomalies.py:83-87`) already blocks this verb with zero new wiring, the moment it is registered as a gated intent | 1 |
| `new_name` is not a legal bookmark name | Refuse — `validate_lane_name` (`lanes.py:103-128`), reused, not reimplemented | 3 |
| `new_name == old_trunk` | Refuse — nothing to do, named plainly rather than silently NOOPing (a NOOP here is more likely a typo than an idempotent retry, unlike project 56's Case 1) | 3 |
| Old name is published and no `--retire`/`--keep-lane` given | Refuse — §3.3's hazard, named explicitly: "'<old_trunk>' is published on '<remote>' — say `--retire` (deletes the lane, and the remote branch unless you add `--keep-remote`) or `--keep-lane` (keeps it, but the next `gitman sync --trunk` will retire it automatically since it is now content-empty against trunk)." | 3 |
| Old name is **not** published, no flag given | Proceed with the default (`--retire`, silently — no remote branch exists to warn about, so the hazard in §3.3 does not apply) | 0 |
| `gitman.toml` config source is `pyproject.toml` | Refuse — §3.4 | 2 |
| On-disk `gitman.toml` trunk value does not match loaded `session.config.trunk` | Refuse — §3.4's dirty-file guard | 2 |
| Repo not initialized (`config.trunk` is `None`) | Refuse — `require_trunk` (`core.py:144-147`), reused, not reimplemented: "repo not initialized — run `gitman init`" | 2 |

### 3.6 The remote

**Renaming trunk locally never touches origin's default branch, and this verb makes no attempt
to.** `gitman` has no verb that changes a forge's default-branch setting today (that is a
forge-API action — GitHub's "set default branch" — entirely outside git/jj and outside this
design's scope; `src/gitman/advanced/` is the deferred forge extra and this design does not touch
it). After the worked rename (§5 below), fsdantic's local `main` is 4 commits ahead of
`origin/main`exactly as `origin/<old_trunk>` was before the rename (the content didn't move, only
the local name pointing at it did) — a plain `gitman push` (`core.py:2847-2897`) fast-forwards
`origin/main` to match, bootstrapping it via the existing "first push of a never-pushed trunk"
path if `origin/main` were absent (it is not, here) or an ordinary fast-forward since
`_push_gate` (`core.py:2778-2808`) already classifies this relation as `local-ahead` (the content
check, `_trunk_content_relation`) with no divergence to refuse on. **What the rename's own report
says about this**, so the operator is not surprised later: a `notes` line, always present when the
new trunk name has any forge relation at all (fetched or not):
"local trunk is now '<new_name>'; origin's default branch is unchanged — if origin's default
branch should also become '<new_name>', do that on the forge directly (gitman has no verb for a
forge's default-branch setting). `gitman push` will fast-forward 'origin/<new_name>' to match once
you're ready." No attempt is made to infer or recommend a specific forge action beyond naming that
one exists and is out of scope.

### 3.7 Reporting

**`IntentResult`** (`models.py:229-249`), same shape every other mutating intent already returns:
`intent="trunk-rename"`, `outcome` one of `RENAMED` (success), `REFUSED` (any precondition in §3.5
tripped — `core.py:29` documents this is how every `GitmanError` already surfaces), `exit_code`
per §3.5/§4, `lane=None` (this is not a lane-scoped intent — the new field it could occupy,
`old_trunk`/`new_trunk`, does not exist on `IntentResult` today; see below), `messages` naming
exactly what happened (`created trunk bookmark 'main' at <commit>.`, `retired old trunk 'fix/...'
(deleted local lane; <kept|deleted> remote branch).` or `kept 'fix/...' as an ordinary lane —
see notes.`, `wrote gitman.toml (trunk now 'main').`), `notes` carrying the §3.6 remote-silence
line and, when applicable, the §3.3 hazard warning for `--keep-lane`, `undo_command="gitman
undo"`, `state=capture_state(session)` (now reflecting the new trunk under the new name,
automatically — nothing in `capture_state`/`render.py` hardcodes a trunk name anywhere; confirmed:
`render.py:74-88`'s `_remote_relation` reads `trunk.name`/`trunk.relation` generically).

**`--json` fields:** no new top-level field is needed on `IntentResult` itself — `messages`/`notes`
already carry the human-readable facts, and `state.trunk` (a `TrunkRef`, `models.py:104-119`)
already carries the new `name`/`commit_id`/`change_id` machine-readably the moment `state=` is
populated (the same reasoning project 56's `DESIGN.md` §Step 10 used to reject a redundant field:
"`RepoState.anomalies`... already carries the... row machine-readably once Step 4 ships. Do not add
a redundant field."). The one genuinely new fact with no existing home is **what the old trunk name
became** — a disposed lane, a kept lane, or nothing (never published). Add this as a field on the
`trunk-rename` intent's own result only, not a schema change to `IntentResult`'s shared shape:
`old_trunk_disposition: Literal["retired", "retired-remote-kept", "kept-as-lane"] | None = None` on
`IntentResult` (default `None` for every other intent, mirroring how `content` already exists as an
intent-specific field unused by every verb except `resolve --show`, `models.py:245-249`).

**`gitman doctor`'s trunk row, afterward:** unchanged code, correct new output, with zero edits.
`doctor.py:106-110`:
```python
if not cfg.trunk:
    checks.append(Check(WARN, "trunk", "trunk not configured — run `gitman init`"))
elif ws is not None and _bookmark_exists(ws, cfg.trunk):
    checks.append(Check(OK, "trunk", f"frozen trunk '{cfg.trunk}' present"))
else:
    checks.append(Check(FAIL, "trunk", f"configured trunk '{cfg.trunk}' not found in repo"))
```
reads `cfg.trunk` generically; once `gitman.toml` carries the new name and `_bookmark_exists`
(`doctor.py:278`) confirms the new jj bookmark exists (it does, created in step 3), this prints
`OK  trunk  frozen trunk 'main' present` with no changes to `doctor.py` at all. This is the
intended payoff of writing the config and creating the bookmark in the same atomic verb: every
piece of the codebase that already trusts `config.trunk` keeps working without having been told
about this feature's existence.

**`undo_command`:** `"gitman undo"`, same as every other mutating intent — but see §2's discussion
of the undo-checkpoint extension; without it, `gitman undo` would revert the jj-side bookmark
creation/deletion correctly (the op log covers that) while leaving `gitman.toml` pointing at the
new name, which is a worse state than either endpoint (jj says one thing, config says another —
exactly the `trunk-conflicted`-adjacent shape `state.py:775-778` already exists to detect, though
that specific detector is for a colocated git/jj mismatch, not a config/jj mismatch, and would not
fire here without the extension). The extension in §2 closes this; shipping without it would be
shipping a verb whose own `undo_command` lies.

### 3.8 Interaction with the landed `/`-trunk fix (commit `e28623a`)

**Does a rename-away-from-`/` make `e28623a`'s fix redundant? No — argued precisely, not
asserted.** `e28623a` ("fix(repair): never migrate a `/` trunk as a legacy lane name") fixed
`_repair_legacy_lane_names` so `gitman repair` no longer renames a `/`-separated **trunk** to `+`
(its regression test is `test_reconcile_never_renames_a_slash_trunk`,
`tests/test_issue44_stage4f_fractal_publish.py` per the commit's own diffstat: `src/gitman/repairs.py
| 12 ++++++++-` and `tests/test_issue44_stage4f_fractal_publish.py | 37 +++...`). That fix protects
every repo whose trunk is **already** `/`-named and has not been renamed — which, after this
design ships, is still most repos with that shape, because **renaming is opt-in, not automatic**.
This design adds a verb an operator can choose to run; it does not retroactively rename every
`/`-trunk repo in existence, and it must not — a repo owner who is fine with a `/`-named trunk
(the fix branch itself might be fine as a permanent trunk name for some repos) has every right to
never run `gitman trunk rename`. `e28623a`'s fix keeps protecting that operator's choice not to
rename. The two are complementary, not sequential: `e28623a` says "don't auto-migrate a `/`-trunk's
name without being asked"; this design says "here is the verb for when an operator *does* ask." A
repo that uses this design's verb to move off a `/`-trunk name no longer needs `e28623a`'s
protection for *that* repo's trunk specifically (there is no `/` left to protect), but every other
`/`-trunk repo in the world still needs it, and a single codebase serves all of them from the same
`_repair_legacy_lane_names` function — there is no way to "retire" the fix per-repo, nor should
there be.

## 4. The exit-code contract

Gitman's standing contract (AGENTS.md): `0` ok · `1` VC decision needed · `2` infra/config ·
`3` invalid usage.

| Outcome | Exit |
|---|---|
| Rename succeeds, old name not published (default `--retire`, no remote branch involved) | 0 — RENAMED |
| Rename succeeds, old name published, `--retire` (default), remote branch deleted | 0 — RENAMED, notes name the one-way remote deletion |
| Rename succeeds, old name published, `--retire --keep-remote` | 0 — RENAMED, notes name the kept remote branch |
| Rename succeeds, `--keep-lane` | 0 — RENAMED, notes carry the §3.3 hazard warning |
| Old name published, neither `--retire` nor `--keep-lane` given | 3 — invalid usage, names both flags |
| `new_name` already a live lane | 3 |
| `new_name` not a legal bookmark name | 3 |
| `new_name == old_trunk` | 3 |
| `new_name` exists on origin at a different commit | 2 |
| Repo not initialized | 2 |
| Config source is `pyproject.toml` | 2 |
| On-disk `gitman.toml` trunk value drifted from loaded config | 2 |
| Off-canonical on a trunk-tier anomaly | 1 |
| Repo-lock contention (another gitman process holds it) | 2 (existing `repo_lock` behaviour, `invariants.py:114-135`, unchanged) |

## 5. Worked example — fsdantic

```
$ cd ~/Documents/Projects/fsdantic
$ gitman doctor
...
FAIL  trunk  configured trunk 'fix/materialization-remove-exdev-fallback' not found in repo   # (only if route 1's leftover delete already ran and the hand-rolled config edit from route 2 is still in place — a real repo mid-experiment, not this design's fault)
```
Starting from the clean, never-hand-edited state (`gitman.toml` still names the fix branch, no
stray `main` ref):
```
$ gitman trunk rename main --retire
created trunk bookmark 'main' at 01ca3385 (same commit as current trunk).
retired old trunk 'fix/materialization-remove-exdev-fallback' (deleted local lane; deleted remote branch 'fix/materialization-remove-exdev-fallback' on origin — one-way; `gitman undo` won't restore it).
wrote gitman.toml (trunk now 'main').

note: local trunk is now 'main'; origin's default branch is unchanged — if origin's default
branch should also become 'main', do that on the forge directly (gitman has no verb for a forge's
default-branch setting). `gitman push` will fast-forward 'origin/main' to match once you're ready.

Undo: gitman undo
```
Exit 0. `gitman doctor` immediately after:
```
OK    trunk  frozen trunk 'main' present
```
`gitman status` shows `main` as trunk, 4 ahead of `origin/main` (the existing `local-ahead` content
relation, `state.py:796-799`, `_trunk_content_relation`) — the same "4 ahead" fact the brief
measured, now attached to the name the operator wanted. `gitman push` then fast-forwards
`origin/main` from `56e2d5f3` to `01ca3385`, and `fix/materialization-remove-exdev-fallback@origin`
is gone (deleted by the rename itself, not by the push). If the operator had instead typed
`gitman trunk rename main` with no `--retire`/`--keep-lane`, the verb refuses at exit 3, naming
both flags, because the old name is published — it does not guess.

## 6. Constraints honored

- No code path in this design passes `ignore_immutable=True` anywhere. Both bookmark writes
  (create the new trunk, delete/retain the old one) are bookmark operations, which pyjutsu already
  classifies as not-a-rewrite (AGENTS.md); no commit is ever touched.
- No tag is ever deleted, renamed, or otherwise touched by this design. `tags()` immutability
  (`core.py:209-213`) is unrelated and unchanged.
- A remote branch is deleted only on an explicit operator act (`--retire`, the default, which
  itself names the deletion in its own report before it happens — not a silent background act),
  never as a side effect of a read-only verb, and `--keep-remote` is offered for the operator who
  wants to defer that decision (reusing `_retire_remote_branch`'s existing escape hatch verbatim,
  `core.py:1801-1805`).
- Every claim about current behaviour above cites a `file:line` read directly from trunk on
  2026-10-01 (commit `25c9dc5`); re-verify before implementing, per this file's own header note.

## 7. Open questions left for the owner

1. **Should `--keep-lane` exist at all**, given §3.3 shows it is one `gitman sync --trunk` away
   from the exact hazard this design exists to avoid? This design keeps it (as an explicit,
   loudly-warned opt-out) rather than forbidding it outright, on the principle "say what to do, not
   only what not to do" — but the owner may prefer to remove the option entirely and force
   `--retire` always, accepting that an operator who truly wants to keep the old name as a lane
   can always re-create it by hand (`gitman start <old-name>` from the same commit) after the fact.
2. **The undo-checkpoint extension (§2)** is new ground for gitman — no existing intent needs
   `gitman undo` to restore a plain file. Confirm the `config_before` sidecar field is an acceptable
   shape before implementing, versus the alternative of accepting that `gitman trunk rename`'s
   `undo_command` is honest about a gap ("`gitman undo` reverts the bookmark change; re-run `gitman
   trunk rename <old-name> --retire` to fully reverse the config" ) rather than extending the undo
   mechanism's scope for the first time.
3. **Should a future `gitman trunk show` (a plain read: name, commit, published state) ship
   alongside `rename`** to justify the new `trunk_app` noun immediately, or is one subcommand under
   a new noun acceptable on its own? Not load-bearing on `rename`'s own behaviour.
4. **`new_name` exists on origin at the same commit, mid-fetch staleness:** the precondition table
   (§3.5) treats "same commit" as read from the last fetch's tracking ref (no network call this
   verb makes itself, consistent with every other read-only precheck in the codebase). An operator
   who has not fetched recently could see a stale "same commit" verdict that a fresh fetch would
   contradict. This design does not propose an implicit fetch inside `trunk rename` (no other verb
   does this either), but the owner may want the report to name the last-fetch time explicitly so
   staleness is visible rather than assumed accurate.
