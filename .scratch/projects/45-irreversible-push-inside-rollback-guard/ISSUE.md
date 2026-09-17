# Issue 45 — an irreversible push runs inside a rollback-able guard, behind a gate that drops remote commits

**Opened:** 2026-09-17 · **Source:** the stage-4d push incident, written up in
`.scratch/projects/44-report-integrity-and-intent-architecture/STAGE_4D_PUSH_INCIDENT_AND_HANDOFF.md`
**Severity:** correctness, core promise. Gitman claims to be the sole, safe writer. Both claims
broke in one push.

This issue re-derives the incident from the repository's live state, corrects the write-up's root
cause (it named the wrong mechanism), and specifies the fix.

---

## 1. What the write-up got right, and what it got wrong

Right: a network push runs inside `canonical_guard`'s rollback-able body, the guard rolled local
state back after the push had landed, and the report then claimed "nothing changed on the remote"
— which was false.

**Wrong: the cause of the fast-forward bypass.** §3.3 theorised a *stale* `main@origin` — that the
first push's rollback rewound jj's remote-tracking bookmark below `295f0ad`, so the second push's
gate compared against an out-of-date remote. That is not what happened.

`main@origin` is *still* `295f0ad` in this repo right now, so the exact pre-push condition is
reproducible read-only. Re-derived:

```
main        = d7484e7c79f3841aa393625ef60fbdb7fd9f7453
main@origin = 295f0ad9e085d46374aff5da28118e097fd4a3e7
behind (main..main@origin) = ['295f0ad9']
ahead  (main@origin..main) = ['d7484e7c']
_merge_tree_relation(local, origin) -> (forge_has_new=False, local_has_new=True)
_trunk_content_relation(...)        -> ('local-ahead', 1, 1, 'origin')
```

`main@origin` was **accurate** when the second push ran — `295f0ad` was the real remote tip. The
gate did not read stale data. It read correct data and approved anyway.

This distinction decides the fix. A stale-bookmark cause would be fixed by re-fetching before the
push. The real cause is the gate's own rule, and a fetch does not touch it.

## 2. Root causes

### D1 — the fast-forward gate is content-based, so it force-pushes away a remote commit

`do_push` (`core.py:2186`) documents its policy as "pyjutsu's `git_push` is an unconditional
force-with-lease, so gitman itself refuses a non-FF". It implements that as
`_trunk_content_relation(...) == "local-ahead"`.

`_trunk_content_relation` (`state.py:212`) answers a *content* question, not an ancestry one. When
both sides are ahead by ancestry it asks `_merge_tree_relation`, and if the remote contributes no
new **content** it returns `local-ahead`. So an ancestry-divergent remote tip whose content is
already contained locally reads as a clean fast-forward, and the gate approves.

That content check exists for a real case: the **re-hash twin**. A rebase re-hashes a commit, the
remote still names the pre-rebase sha, content is identical, and dropping the remote's sha is the
correct outcome. The function cannot tell that from a **foreign commit whose content was absorbed**
— which is exactly what `295f0ad` was, after `gitman pull --keep-local` folded its diff in.

The lane-level sibling already knows the missing discriminator. `find_divergent_lane_twins`
(`state.py:289`) refuses to call two sides twins unless their **change-ids match**;
`lane_twin_relation` is only consulted inside that gate. `_trunk_content_relation` has no such
requirement. Confirmed on the incident's commits:

```
main        change = uwknwlputzvlpwumvqyztqxzlzwzssxv
main@origin change = lsnuxoklqzsyrryvuopkkuxlntxopyzs   # matches nothing on local trunk
```

A change-id twin test would have refused this push. The content test approved it.

jj's push is a force-with-lease whose expectation *is* `main@origin`, so a push can only ever
succeed when `main@origin` matched reality at push time. That makes this purely a gate-policy bug:
**every successful gitman push overwrites exactly what the gate examined.** Here the gate examined
a divergence and called it a fast-forward.

Outcome this time: `origin/main` went `295f0ad` → `d7484e7`, dropping the commit object. Content
survived (`git diff --stat 295f0ad d7484e7` shows no `pyproject.toml`/`uv.lock` delta — the
pyjutsu-0.22.0 pin is byte-identical on both sides). A genuinely divergent commit would have been
dropped just as silently.

### D2 — the irreversible push sits inside `canonical_guard`'s rollback-able body

`canonical_guard` (`invariants.py:763`):

```python
try:
    yield canon                       # do_push / do_publish call git_push HERE
except Exception:
    session.ws.restore_operation(op_before)
    raise
if export:
    canon.notes += _export_colocated_git(session)
canon.state = _postcondition(...)     # can itself restore_operation(op_before) and raise
write_undo_checkpoint(...)
```

Two rollback sites run *after* the body: `_export_colocated_git` and `_postcondition`.
`restore_operation` unwinds local jj state; it cannot retract a completed push.

The incident's op log is that sequence exactly:

```
12:44:05  push to git remote 'origin'      <- irreversible, succeeded
12:44:05  import git refs                  <- _export_colocated_git's repair path
12:44:05  export git refs
12:44:05  restore to operation ...         <- _postcondition found a stray, rolled back
```

The stray came from the export step itself: `_export_colocated_git` fell back to
`sync_colocated_refs`, whose `git_import` adopted the git-only `295f0ad` as a change belonging to
no lane. `_postcondition` correctly saw a newly-introduced `stray-change` — **after** the push.

`do_land` already solved this shape for its own irreversible call: its delete-push is deliberately
placed after the postcondition, with a comment citing "review L1". `do_push`/`do_publish` never
adopted that pattern. `_retire_lane` (`core.py:1713`, the pull path) has the same defect at lower
severity — it delete-pushes a forge-merged lane inside `do_pull`'s guard.

### D3 — the report asserts a falsehood, and the rollback corrupts gitman's memory of the remote

Two separate harms.

**The note lies.** `do_push` attaches `notes=["nothing changed on the remote."]` to *any*
`GitmanError` escaping the guard (`core.py:2267`) — including one raised after the push landed.
`do_publish` has no such note but its `reverted: ...; no change applied.` message is equally false.

**The rollback rewinds remote-tracking state.** `restore_operation(op_before)` reverts the
`main@origin` bookmark the push had just advanced. That is the live state of this repo: jj believes
`main@origin` is `295f0ad` while the real remote is `d7484e7`. Consequences:

- `gitman status` reports `(1 ahead origin)` and advises `gitman push` — both false.
- `gitman pull --dry-run` correctly reports "already current", because it does its own fresh fetch.
  The write-up flagged this disagreement as a mystery; it is not one. jj's `main@origin` and git's
  `refs/remotes/origin/main` are independent, and only `ws.git_fetch()` moves the former. A raw
  `git fetch` (this machine runs one on a 180s poll) updates git's ref and leaves jj's untouched.
- The next push's lease expectation is wrong, so it is rejected as "stale info" — which is what the
  *first* push failure at 12:43:06 was.

## 3. Fix

Three changes, one per root cause. D3 mostly falls out of D2: once the push is the last thing that
happens, "nothing changed on the remote" is true for every failure inside the guard.

### F1 — an ancestry-and-change-id push safety gate (fixes D1)

Add `trunk_push_safety(view, trunk, remote)` to `state.py`, returning
`("fast-forward" | "twin-rewrite" | "drops-remote-commits" | "unknown", dropped_commits)`:

- no remote-only commits (`{trunk}..{trunk}@{remote}` empty) → `fast-forward`
- every remote-only commit's change-id also appears in `{trunk}@{remote}..{trunk}` → `twin-rewrite`
  (the re-hash case the content check was built for)
- otherwise → `drops-remote-commits`, naming the remote-only commits that are **not** twins

`do_push` then requires `relation == "local-ahead"` **and** `safety != "drops-remote-commits"`.
Both conditions are necessary: the content check still guards a twin whose remote side was amended,
and the new check guards a foreign commit whose content was absorbed.

`_trunk_content_relation` is **left alone**. It is correctly named and documented as the content
signal, and `capture_state`/`render` depend on those semantics. One word for one meaning: the
content relation answers "who holds more content", the new gate answers "would this push drop a
commit object the remote has".

The refusal now names the commits at stake, so `--reset-origin` is an informed choice:

```
refusing to push: origin/main holds 1 commit local lacks —
  295f0ad9 chore: bump pyjutsu to 0.22.0
Its content is already on local main, but pushing would drop the commit itself from origin's
history. Run `gitman pull` first, or `gitman push --reset-origin` to drop it deliberately.
```

### F2 — the push runs after the guard closes, inside the lock (fixes D2)

Adopt `do_land`'s pattern in `do_push` and `do_publish`: an outer `repo_lock`, then
`canonical_guard(..., acquire_lock=False, export=True)`, then the `git_push` **after** the guard
returns.

Neither intent runs a `ws.transaction` in its guard body, so nothing local depends on the push. The
guard's job is precheck → export → postcondition → undo checkpoint; it proves local state is
canonical *before* any network I/O. Replayed against the incident: the export imports `295f0ad`,
the postcondition finds the stray, the intent refuses — and the remote is never touched.

This also makes the late safety gate load-bearing rather than cosmetic. `_export_colocated_git`'s
repair path can call `git_import` and move bookmarks *between* the early gate and the push, so F1's
gate is re-evaluated on a fresh view immediately before the push, under the same lock.

**Rejected: re-fetching before the push.** The write-up's option (a) assumed a stale bookmark, and
§1 shows there wasn't one. jj's force-with-lease already makes a stale-older `main@origin` *safe* —
it gets rejected. A fetch would only improve the wording of a pre-flight refusal, and it would
introduce a new unrollback-able import after the postcondition has already passed. Not worth it.

### F3 — honest remote-effect reporting (fixes D3)

- Failures inside the guard: keep `nothing changed on the remote.` — now true by construction.
- `HookAbort` from the push: nothing changed, and say why (a pre-push veto precedes network I/O).
- `PostHookError`: the push **landed**; only the post-hook failed. `map_pyjutsu_error` already
  words this correctly (`core.py:71`) — route to it instead of claiming "push failed".
- Any other `PyjutsuError` from the push: report what the engine said, assert nothing about the
  remote. This is already the existing behaviour and stays.

`do_publish` gets the same treatment, including the missing remote-effect note.

## 4. Out of scope, recorded

- `_retire_lane`'s delete-push inside `do_pull`'s guard (D2, lower severity) — same fix shape,
  separate change.
- Whether `restore_operation` should ever rewind remote-tracking bookmarks. With F2 the window
  closes for push/publish, so this stops being reachable from these intents.
- The live stale `main@origin` in this repo. A `gitman pull` refreshes it; see `RESOLUTION.md`.
