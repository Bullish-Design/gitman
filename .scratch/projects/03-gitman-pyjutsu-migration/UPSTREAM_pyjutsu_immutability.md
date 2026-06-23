# Upstream report for pyjutsu — commit immutability / trunk protection

**To:** pyjutsu maintainers · **From:** gitman (a downstream policy layer being ported onto
pyjutsu) · **Against:** pyjutsu 0.7.0, jj-lib 0.38.0 · **Date:** 2026-06-17

This is an evaluation request, not a bug demand. While porting gitman onto pyjutsu we found that
pyjutsu enforces **only root-commit** immutability, not jj's configurable `immutable_heads()`
(trunk / tags / untracked remote bookmarks). We also found one outright **bug** (a rewrite path
that *panics* instead of raising) that we think should be fixed regardless of how you decide the
larger policy question. Everything below was verified by probing the built extension and reading
the Rust source; file:line references are into pyjutsu's tree.

---

## TL;DR

- **Issue A (bug, please fix regardless):** `PyTransaction::describe` rewrites its target with **no
  root-commit guard**, so `tx.describe("root()", …)` triggers a jj-lib `assert!` and surfaces as a
  `pyo3_runtime.PanicException` across the FFI boundary — while `abandon`/`rebase`/`squash`/`restore`
  guard the root explicitly and `edit` maps the error cleanly. Inconsistent, and a Rust panic across
  PyO3 is hostile (it can poison the in-flight `MutableRepo`). It should raise `ImmutableCommitError`
  like its siblings.
- **Issue B (policy gap, for your evaluation):** pyjutsu deliberately does not replicate jj's
  configurable immutability (the code comment in `src/transaction.rs:260` says so). The result is
  that an in-process consumer can silently rewrite **trunk** or a **tagged release commit** with no
  error — the headline safety property of "a faithful jj engine" is absent. We outline four options
  (do-nothing → expose-a-query → opt-in-enforcement → seed-the-aliases) with trade-offs and a
  recommendation that stays consistent with pyjutsu's "primitives, not workflow policy" philosophy.

gitman itself will enforce trunk protection in its own policy layer either way, so **this is not a
blocker for us** — it's about ecosystem correctness and removing a foot-gun for every future
consumer.

---

## Background: how jj enforces immutability (and where the layers split)

In jujutsu, "you can't rewrite trunk/tags" is **not** enforced by `jj-lib`. jj-lib hard-protects
only the **root commit** (the synthetic empty commit with no parents). Everything else —
`immutable_heads()`, `trunk()`, tags, untracked remote bookmarks — is enforced by the **CLI crate**:

- The CLI's *built-in config* defines the revset aliases (jj 0.38, paraphrased):
  ```toml
  [revset-aliases]
  'builtin_immutable_heads()' = 'present(trunk()) | tags() | untracked_remote_bookmarks()'
  'immutable_heads()'         = 'builtin_immutable_heads()'
  'immutable()'               = '::(immutable_heads() | root())'
  'mutable()'                 = '~immutable()'
  ```
- Before any rewrite, the CLI evaluates `immutable()` once and refuses if a to-be-rewritten commit
  is a member (`cli/src/cli_util.rs::check_rewritable`, using a `containing_fn()` for cheap
  membership). jj-lib's `MutableRepo::rewrite_commit` / `record_abandoned_commit` themselves do **no
  such check** — they only assert on the root.

So a binding that talks to `jj-lib` directly (pyjutsu, by design) gets **root protection for free**
and **nothing else** unless it reproduces the CLI's policy. That's the crux of Issue B.

---

## Reproduction (verified against the built extension)

```python
from pyjutsu import Workspace
from pyjutsu import errors as E

ws = Workspace.init("/tmp/r", colocate=True)
# ... make a commit, bookmark it "main" (acting as trunk), put @ on a child ...

# Issue B: trunk is freely rewritable — NO error.
with ws.transaction("rewrite trunk tip") as tx:
    tx.describe("main", "rewrote the trunk tip")     # succeeds; main's commit_id changes

# Issue A: rewriting root panics instead of raising.
with ws.transaction("rewrite root") as tx:
    tx.describe("root()", "x")
    # -> pyo3_runtime.PanicException: assertion failed: !commit.parents.is_empty()

# Contrast: abandon/rebase/squash/restore DO raise cleanly on root.
with ws.transaction("abandon root") as tx:
    tx.abandon("root()")                              # ImmutableCommitError: cannot abandon the root commit
```

Observed: `describe(main)` and `describe(root())` confirm both issues; `abandon(root())` confirms
the sibling paths already do the right thing.

---

## Root-cause analysis (file:line)

**Config loading is fine but incomplete for this purpose.** `src/workspace.rs:104
load_user_settings` builds `StackedConfig::with_defaults()` + user config (`JJ_CONFIG` / platform
dir) + the repo's `.jj/repo/config.toml`. But `with_defaults()` is **jj-lib's** defaults — it does
**not** include the CLI's `builtin_immutable_heads()` / `immutable_heads()` aliases (those live in
the cli crate). So unless the *user's own* config happens to define `immutable_heads()`, the alias is
simply unresolvable in pyjutsu, and even a consumer who wanted to check it can't.

**Enforcement is root-only, and inconsistently so.** In `src/transaction.rs`:
- `abandon` (`:262`), `rebase` (`:309`), `squash` (`:366`), `restore` (`:419`) each **explicitly
  guard** `target.id() == repo.store().root_commit_id()` and return `ImmutableCommitError`.
- `edit` (`:238`) maps `EditCommitError::RewriteRootCommit → ImmutableCommitError`
  (`src/errors.rs:87`).
- **`describe` (`:161`)** calls `repo.rewrite_commit(&commit).set_description().write()`
  (`:175–179`) with **no root guard** → hits jj-lib's `assert!(!commit.parents.is_empty())` in the
  store → `PanicException`. This is the bug.
- The comment at `src/transaction.rs:260` states the policy choice explicitly: *"Only the root is
  enforced — jj's configurable `immutable_heads()` set is CLI workflow policy, which the thin layer
  deliberately does not replicate."* — i.e. Issue B is a known, intentional omission, which is why
  we're raising it as an evaluation rather than a bug.

---

## Issue A — fix the panic (recommended unconditionally)

Add the same root guard `describe` is missing, and audit every rewrite entry point so **no** path
can panic across FFI:

- In `describe`, before `rewrite_commit`, guard `target.id() == root_commit_id()` →
  `ImmutableCommitError("cannot rewrite the root commit")` (matching the sibling wording).
- Sweep `transaction.rs` for any `rewrite_commit`/`record_abandoned_commit`/`assert*`/`unwrap`
  reachable from a public method; ensure each maps to a typed error, never a panic. (Rationale: a
  Rust panic that unwinds through PyO3 becomes a `BaseException` the Python consumer can't reasonably
  handle, and it may leave the borrowed `MutableRepo` half-mutated for the rest of the `with` block.)

Low risk, strictly-better, independent of the Issue B decision. A regression test per rewrite verb
against `root()` (`with pytest.raises(ImmutableCommitError)`) would lock it in.

---

## Issue B — configurable immutability: four options

Ordered from least to most engine involvement. They are **not** mutually exclusive — (4) is a
prerequisite that makes (2)/(3) faithful, and our recommendation combines (4)+(2).

### Option 1 — Status quo + documentation
Keep root-only enforcement; document clearly that *all* other immutability is the consumer's
responsibility, and that `immutable_heads()` is unavailable unless the consumer defines it in config.

- **Pro:** maximally thin; matches the stated philosophy; zero engine work (beyond Issue A).
- **Con:** every consumer re-implements the same `immutable()` membership check; the "faithful jj
  engine" promise is materially weaker than the CLI for the one operation users most fear (a silent
  trunk/tag rewrite); the alias isn't even resolvable, so consumers can't easily match jj semantics.

### Option 2 — Expose immutability as a read-only query (recommended baseline)
Add a non-enforcing primitive so consumers can ask the engine, cheaply and faithfully, whether a
commit is immutable — leaving *enforcement* as consumer policy:

```python
view.is_immutable("main")            # -> bool, evaluates the configured immutable() set
view.immutable_heads()               # -> list[Commit] (or the resolved revset), optional
```

Implementation: build the `immutable()` `RevsetExpression` once per `RepoView`/call, evaluate to a
`containing_fn()` (as the CLI does), and test membership. Pair with Option 4 so `immutable_heads()`
resolves to jj's builtin by default.

- **Pro:** stays "primitives, not policy"; composable; jj-faithful; lets gitman/others check before
  mutating without re-deriving the revset; trivial to reason about.
- **Con:** opt-in — doesn't prevent the foot-gun for a consumer who forgets to call it; needs
  Option 4 (or a user-defined alias) to be meaningful.

### Option 3 — Opt-in enforcement in transactions
A flag that makes the binding evaluate `immutable()` and raise `ImmutableCommitError` on any rewrite
of a member, mirroring the CLI's `check_rewritable`:

```python
with ws.transaction("…", enforce_immutable=True) as tx:   # default off (thin) or on (jj-faithful)
    tx.describe("main", "…")   # -> ImmutableCommitError
```

Evaluate the immutable set **once** when the transaction opens and reuse a `containing_fn()` across
all rewrites in that tx (avoid per-call revset evaluation — that's the CLI's perf model too).

- **Pro:** real protection; closest to jj parity; one switch instead of per-call checks.
- **Con:** moves workflow policy into the binding (philosophy tension); needs Option 4; a default-on
  choice would be a behavior change; must decide semantics for a rewrite that *moves* an immutable
  commit only as a descendant rebase, etc. (match the CLI's "rewrite set" definition exactly).

### Option 4 — Seed jj's builtin immutability aliases into the config stack (enabler)
Today `load_user_settings` omits the CLI's builtin revset-aliases. Seed
`builtin_immutable_heads()` / `immutable_heads()` / `immutable()` / `mutable()` (vendored from jj's
CLI default config, version-pinned alongside the jj-lib pin) as a **built-in (lowest-precedence)**
layer, so a user/repo config can still override `immutable_heads()` exactly as in jj.

- **Pro:** makes `immutable_heads()`/`immutable()` *resolvable and jj-identical* — required for (2)
  and (3) to mean what they mean in jj; also lets consumers who write their own revsets reference
  `immutable()` directly.
- **Con:** these aliases are CLI-crate config, not jj-lib, so pyjutsu must vendor/track the TOML and
  re-pin it on jj upgrades (one more thing pinned to the jj version — but you already pin jj-lib, so
  it slots into the same discipline).

---

## Recommendation

1. **Do Option A now** (the describe root-guard + a no-panic audit) — it's a clean bug fix.
2. **Do Option 4 + Option 2** as the philosophy-consistent baseline: seed the builtin aliases so
   `immutable()` is jj-faithful, and expose `is_immutable(rev)` as a read-only query. This gives
   every consumer a cheap, correct membership check without pyjutsu taking on enforcement policy.
3. **Consider Option 3** (opt-in `enforce_immutable`, default **off**) as a follow-up convenience for
   consumers that want engine-level guarantees without writing the check themselves. Defaulting it
   **on** would be the most jj-faithful but is a behavior change worth a deliberate major-version
   call.

This keeps pyjutsu thin (enforcement stays opt-in / consumer-side) while restoring jj parity for the
*detection* of immutable commits and removing the silent-trunk-rewrite foot-gun.

## What gitman will do regardless
gitman enforces trunk protection in its own policy layer (only its `land` intent advances trunk; all
rebases target `trunk..lane`; a transactional postcondition asserts trunk's `commit_id` is unchanged
outside a land). So we are **not blocked**. If Option 2 lands we'd switch our postcondition to call
`view.is_immutable(...)` for a jj-faithful check; if Option 3 lands we'd turn it on as
defense-in-depth. Issue A's panic is the only item that actively bites us today (we simply never
target `root()`, so it's low-severity for us, but it's a sharp edge for the next consumer).

## Suggested tests (whichever options you take)
- `describe(root())` → `ImmutableCommitError` (Issue A); same for every rewrite verb.
- With builtin aliases seeded: `is_immutable("trunk()")` / a tagged commit → `True`; a normal lane
  commit → `False`; a user config overriding `immutable_heads()` changes the result.
- With `enforce_immutable=True`: rewriting trunk/tag/untracked-remote-bookmark → `ImmutableCommitError`;
  rewriting a mutable lane commit → succeeds; verify the immutable set is evaluated once per tx.
