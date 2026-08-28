# Lane 6 — the immutability audit

Deliverable of guide 2, lane 6. One row per rewrite site in `src/gitman/`.

Date: 2026-08-27. Engine: pyjutsu 0.20.0 / jj-lib 0.44.0.

---

## 1. What is protected

pyjutsu 0.16 evaluates `immutable_heads().ancestors()` before every rewrite verb. The vendored
default aliases are:

```
"builtin_immutable_heads()" = 'trunk() | tags() | untracked_remote_bookmarks()'
"immutable_heads()"         = 'builtin_immutable_heads()'
"immutable()"               = '::(immutable_heads() | root())'
"trunk()"                   = 'latest(remote_bookmarks(exact:"main"|"master"|"trunk",
                                       exact:"origin"|"upstream") | root())'
```

The rewrite verbs are `tx.rebase`, `tx.squash`, `tx.abandon`, `tx.describe`, `tx.restore`, and
`tx.new`. Bookmark and tag writes are **not** rewrites: `tx.set_bookmark`, `tx.create_bookmark`,
`tx.delete_bookmark`, and `ws.git.create_tag` move refs, not commits, and stay allowed.

Note that `tx.new(X)` *creates a child of X*. It rewrites nothing, so every `tx.new` row below is
safe by construction, whatever `X` is.

---

## 2. The table

Site list from `grep -nE "tx\.(rebase|squash|abandon|describe|restore|new)\(" src/gitman/*.py`.

| Site | Verb | Target | Can the target be in `immutable()`? | Verdict |
|---|---|---|---|---|
| `core.py:426` (`do_start`) | `new` | child of the parent lane head | No — creates a child, rewrites nothing. | Safe |
| `core.py:451` (`do_start`) | `new` | child of trunk | No — same. | Safe |
| `core.py:518` (`_start_workspace`) | `new` | child of trunk or a lane head | No — same. | Safe |
| `core.py:815` (`do_split`) | `describe` | the carved lane commit | Only if that lane commit is tagged or is an ancestor of an untracked remote bookmark. Both mean the operator marked it as published history. | Refuse (6c) |
| `core.py:836` (`do_split`) | `new` | empty child of trunk | No. | Safe |
| `core.py:838, 839` (`do_split`) | `restore` | the new carve commit `A` | No — `A` was just created by this transaction, so nothing can reference it yet. | Safe |
| `core.py:841` (`do_split`) | `describe` | the new carve commit `A` | No — same. | Safe |
| `core.py:842` (`do_split`) | `restore` | the source lane commit `C` | Same exposure as `core.py:815`. | Refuse (6c) |
| `core.py:919` (`do_shape`) | `squash` | two lane commits | Same exposure as `core.py:815`. | Refuse (6c) |
| `core.py:927` (`do_shape`) | `rebase` | one lane commit, `mode="revision"` | Same exposure. The *base* (`prev`) is not rewritten. | Refuse (6c) |
| `core.py:964` (`do_save`) | `describe` | `@` | Only if `@` is tagged or under an untracked remote bookmark. `@` is the agent's own live change; gitman creates it as a fresh child. | Safe in practice |
| `core.py:1016` (`do_seed`) | `describe` | `@`, with the trunk bookmark on it | See §3. | Safe, guard-bound |
| `core.py:1017` (`do_seed`) | `new` | child of `@` | No. | Safe |
| `core.py:1156, 1182` (`do_land`) | `rebase` | a lane, `mode="branch"` | The lane, not the base. Same lane exposure as above. Trunk (the `onto`) is never rewritten. | Refuse (6c) |
| `core.py:1165, 1186` (`do_land`) | `new` | child of trunk / of the base | No. | Safe |
| `core.py:1264` (`_abandon_range`) | `abandon` | the lane's own commits | **Yes** — a tagged lane head is the concrete case. Wired to `explain_immutable`. | Refuse (6c), covered by test |
| `core.py:1443, 1459` (`do_sync`) | `rebase` | a lane, `mode="branch"` | Same lane exposure. | Refuse (6c) |
| `core.py:1528` (`_retire_lane`) | `abandon` | a forge-merged lane's commits | Yes in principle. In this shape `trunk..lane` is normally empty (the merge already folded it), so the loop rewrites nothing. | Refuse (6c) |
| `core.py:1581` (`_resolve_conflicted_lane`) | `abandon` | local-only commits of a conflicted lane | Yes in principle. These commits are un-pushed by construction (they are the *local* side), so `untracked_remote_bookmarks()` cannot cover them; only a tag can. | Refuse (6c) |
| `core.py:1649` (`_reconcile_lane_against_adopted_trunk`) | `rebase` | a lane, `mode="branch"` | Same lane exposure. | Refuse (6c) |
| `core.py:1722` (`_integrate_trunk`) | `rebase` | the local trunk tip onto the origin tip | **The interesting one.** See §4. | Refuse (6c) |
| `core.py:1889` (`do_pull`) | `new` | child of trunk | No. | Safe |
| `version.py:73` | `new` | child of the lane head | No. | Safe |
| `version.py:77` | `describe` | the bump change `@` just created | No — created in the same transaction. | Safe |
| `invariants.py:182` | `new` | child of trunk (reparking `@`) | No. | Safe |
| `reconcile.py:133` | `abandon` | stray commits, under `--abandon` | Tags are already excluded from `_stray_revset`, so the realistic case is an untracked remote bookmark. Wired to `explain_immutable`. | Refuse (6c) |
| `init.py:240` | `create_bookmark` | trunk | Not a rewrite. | Safe |
| `invariants.py:350, 463, 467` | `set_bookmark` | lanes and trunk | Not a rewrite. | Safe |

**Summary.** Every "Refuse" row shares one exposure: *a lane commit that carries a tag, or that is an
ancestor of a remote bookmark gitman does not track*. There is no site where gitman rewrites trunk
itself, so the `trunk()` term of the alias never fires against gitman's own work.

---

## 3. The `seed` edge case (step 6b)

`core.py:1016` describes `@` while the trunk bookmark points at it — a rewrite of the commit trunk
names. It is safe for two independent reasons, and both are now pinned by tests in
`tests/test_seed_integration.py`:

1. **At real seed time there is no fetched remote**, so `trunk()` collapses to `root()` and
   `immutable()` is `::root()`. `@` is a child of root, so the rewrite is allowed.
2. **A fetched but unrelated `origin/main` does not protect `@` either** — `@` is not in its
   ancestry. Verified live, not argued:
   `test_seed_with_a_fetched_origin_stays_guard_bound` fetches a real upstream and seeds cleanly.

When `@` genuinely does sit inside `::(trunk())`, gitman's own guards at `core.py:999-1005` reject
first, with exit 3 and a message about existing history. The same test asserts that, and asserts the
word "immutable" never reaches the operator from this path.

---

## 4. `_integrate_trunk` — the one non-lane rewrite

`core.py:1722` rebases the **local** trunk tip onto the fetched origin tip during `pull`. The target
is local, un-pushed trunk history: commits the operator landed but has not pushed. `trunk()` resolves
to the *remote* bookmark, which is the rebase's `onto`, not its target. So the protected side is the
base, and rebasing onto an immutable base is legal.

The residual case is a **tagged un-pushed trunk commit**. `gitman release` refuses to tag a commit
that is not reachable from trunk (`release.py:98-104`), so gitman's own tags land on trunk history
that is normally already pushed. A hand-made tag on an un-pushed local land would make `pull` refuse.
That is the correct outcome under the lane 6c policy: the operator asked for that commit to be kept.

---

## 5. Policy (DECISION 6c — resolved)

**Refuse everywhere, with a report that names the protection.** `ignore_immutable=True` appears
nowhere in `src/gitman/`, and `tests/test_stray_tags_divergent.py::test_gitman_never_overrides_immutability`
enforces that by scanning the package's tokens.

Reasoning:

- A tag is the deliberate "this is intentional history" signal `state._stray_revset` already honours.
  Overriding it in a cleanup verb would contradict gitman's own model.
- An untracked remote bookmark is history another party can see. A local cleanup must not rewrite it.
- The baseline found **zero** live occurrences of this error in gitman source. An always-on override
  would buy nothing measured and would cost the audit trail.

`core.explain_immutable` resolves the failing commit against `tags()`, `trunk()`, and
`untracked_remote_bookmarks()` in turn and names the one that matched. `map_pyjutsu_error`'s generic
branch names all three, for the paths that have no session in hand.

If recovery ever does need to outrank tag protection, the shape to add is an explicit
`gitman reconcile --force`: operator-chosen and auditable, never automatic.

---

## 6. DECISION 6d — do NOT write jj configuration (resolved)

The problem is real: pyjutsu's `trunk()` only matches bookmarks named `main`, `master`, or `trunk`
on remotes named `origin` or `upstream`. Gitman's trunk is configurable. A repo whose trunk is
`develop`, or whose remote is `forge`, gets **no** `trunk()` protection — jj's protected lineage and
gitman's canonical trunk diverge.

The rejected option was to have `gitman init` write:

```toml
[revset-aliases]
"immutable_heads()" = "<gitman-trunk-name>"
```

Rejected because:

- gitman writes no jj configuration today (`grep -rn "config.toml" src/gitman/` returns nothing).
  This would be a new file gitman owns, a new failure mode, and a new thing to keep in sync with
  `gitman.toml`.
- pyjutsu's `ws.git.config_*` verbs read and write **git** configuration, not jj configuration, so
  there is no supported writer to use.
- The divergence is not a data-loss risk. It only means *less* protection than the default suggests.
  Gitman's own invariant I1 (trunk frozen at init) and the `canonical_guard` postcondition are what
  actually protect trunk; the jj-side alias is a second belt.

**Consequence to know:** on a repo whose trunk is not named `main`/`master`/`trunk`, the `trunk()`
term of `immutable_heads()` is inert. The `tags()` and `untracked_remote_bookmarks()` terms still
apply. Revisit if a repo ever needs jj-side protection of a non-standard trunk name.
