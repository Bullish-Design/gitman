# Issue 45 — what to do about `295f0ad`, and about this repo's stale `main@origin`

Answers the open question in
`.scratch/projects/44-report-integrity-and-intent-architecture/STAGE_4D_PUSH_INCIDENT_AND_HANDOFF.md`
§6.4.

## 1. `295f0ad` — no repository action needed

`295f0ad "chore: bump pyjutsu to 0.22.0"` was force-pushed out of `origin/main`'s reachable
history on 2026-09-17 at 12:44:05. Verified on 2026-09-17 at ~12:58:

```
$ git rev-parse refs/heads/main refs/remotes/origin/main    # both d7484e7
$ git ls-remote origin refs/heads/main                      # d7484e7
$ git merge-base --is-ancestor 295f0ad origin/main          # NO  (dropped)
$ git cat-file -t 295f0ad                                   # commit  (object present)
$ git diff --stat 295f0ad d7484e7                           # no pyproject.toml / uv.lock delta
```

The last line is the decisive one: **the content survived in full.** `295f0ad`'s entire diff was
the pyjutsu pin bump, and `pyproject.toml` line 67 on `d7484e7` is byte-identical to `295f0ad`'s:

```
pyjutsu = { url = ".../releases/download/v0.22.0/pyjutsu-0.22.0-cp313-abi3-manylinux_2_39_x86_64.whl" }
```

`gitman doctor` reports `pyjutsu 0.22.0 (jj-lib 0.44.0)` — the pin resolves, so the wheel the
write-up believed unpublished now exists. Nothing is missing and nothing needs restoring.

**Deliberately not done, and why:** re-pushing `295f0ad` would put a duplicate of trunk content
back on `origin/main` as a second parentage line, which is worse than the drop. Pinning it under a
bespoke ref (`refs/gitman/dropped/...`) invents a mechanism gitman does not have and nobody would
maintain. The object is already nameable from git's own reflog (`refs/heads/main@{0}` = `295f0ad`)
for the reflog expiry window, which is far longer than anyone will care.

## 2. The one real action is communication, not repair

The residual risk the write-up named is correct and is **not** a repository problem: if the session
that authored `295f0ad` still believes `main` is at `295f0ad`, its next operation will surprise it.
Concretely, from that view:

- `gitman push` → refused. Before issue 45's fix the gate would have approved it and re-dropped
  `d7484e7`; after the fix it refuses and names the commits at stake.
- `gitman pull` → the right move. Its content relation reads `forge-ahead` (origin holds
  `d7484e7`'s work, the local side holds nothing origin lacks), so it fast-forwards onto origin and
  the divergence disappears with no loss.
- raw `git push` → rejected as non-fast-forward, correctly.

So the message to whoever authored `295f0ad` is one line: **`origin/main` was rewritten from
`295f0ad` to `d7484e7`; your pin-bump content is on trunk; run `gitman pull`, not `gitman push`.**

That session cannot be identified from here. `ListAgents` shows several `gitman-*` peers but does
not say which one holds this working directory, and the commit's author line is the same account
that drives every session. Escalated to the user rather than broadcast to six peers.

**The durable fix for the underlying cause is not in this repo at all:** `295f0ad` was made with
raw `git commit` in a directory gitman owns. Gitman's I4 lock only serializes gitman writers. A
second agent using raw git bypasses it entirely — which is what `gitman status`'s `ref-mismatched`
(adopt-direction) detection is for, and it worked: it reported DESYNCHRONIZED and named the
git-only history. Detection is not prevention; two agents must not share one working directory.

## 3. This repo's stale `main@origin` — fixed by a fetch

The rolled-back push left jj believing `main@origin` is `295f0ad` while the real remote is
`d7484e7`. That is why `gitman status` reports a false `(1 ahead origin)` and advises a push, while
`gitman pull --dry-run` correctly says "already current" — the write-up flagged the disagreement as
unexplained, and it is simply that jj's `main@origin` and git's `refs/remotes/origin/main` are
independent. Only `ws.git_fetch()` moves the former; this machine's 180s background `git fetch`
poll moves only the latter.

Cure: one `gitman pull`, which fetches and re-derives the relation. Issue 45's F2 closes the window
that created the state, so it cannot recur from `push`/`publish`.
