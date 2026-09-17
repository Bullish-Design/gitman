# S6 — the verb surface matches the noun it moves

**Size:** medium · **Risk:** medium · **Closes:** issue 44 §7 · **Depends on:** S3
**Was:** issue 44 G5 / stage 6, minus issue 43 D2 — **D2 is already fixed, do not redo it**
(`SCOPING.md` §1).

Depends on S3 because S3 changes what `start`/`subtask` accept as a name. Renaming a verb and then
changing its argument grammar does the work twice.

## 1. The measurement

`probe_verb_drift.py` on this tree:

```
shipped    24 [abandon catchup doctor init land log publish pull push reconcile release resolve
               save seed shape split start status subtask switch sync undo untrack version]
groups     ['remote']
```

24 commands, one subgroup. `IMPLEMENTATION_GUIDE.md` §6 lists the consolidations.

## 2. The one rule that governs this whole stage

**Every rename ships behind a deprecating alias that warns once and forwards.** Gitman manages the
repo that configures it, so a hard removal locks the tool out of landing its own migration — the
trap `[version]` sprang in 0.5.0 (`GITMAN_CONCEPT.md` §15, "Retiring a config table"; and
`config.RETIRED_TABLES` **warns**, never fails, for exactly this reason).

There is already a deprecation channel: `cli.py:118` does
`result.notes.extend(load_config(_repo_root()).deprecations)`. Reuse that mechanism for verb
aliases rather than inventing a second one.

## 3. Steps

Do them in this order; each lands green alone.

### 1. `workspace` becomes a noun (issue 43 D3)

The highest-value item now that D2 is fixed. Today workspaces are created by `--workspace`,
surfaced in `status`, named in refusals, and can never be listed, forgotten or pruned. `cli.py`
mounts exactly one subgroup (`remote_app`, `cli.py:407-408`). Mount a second, the same way.

- `gitman workspace list` — annotate which registrations have **no live lane**.
- `gitman workspace forget <name>` — drop the jj registration. **Never `rmtree` a directory gitman
  did not create.** `_cleanup_workspace`'s `keep_foreign` path already encodes the rule and its
  reasoning — route through it, do not write a second policy.
- `gitman workspace prune` — the empty-and-laneless ones only.
- `land` / `abandon` release a lane's registration when its `@` is empty and it is not the caller's
  workspace. (Check whether `_cleanup_workspace` already does this before adding anything.)
- `status` mentions registrations with no lane, instead of leaving them invisible until they block
  a `start`.

The implementations live in `core.py` and the lifecycle in `lanes.py`; `cli.py` is only the mount.

### 2. `save` → `describe`

`save` imports the git mental model gitman exists to delete — jj already saved it — and issue 43's
incident ran through an operator who believed `save` was what protected the work. Rename, alias
`save` with a warning that names `describe`.

Rename the `do_*` function too (`do_save` → `do_describe`) and update `IntentResult.intent`. A
report whose `intent` field still says `save` under a `describe` command is the drift this whole
refactor is about. `--json` consumers key on that string: note the change in the progress doc.

### 3. `subtask` → `start`

`subtask api` on `T` is already exactly `start T+api` (`core.py:596`). Alias and remove. The guard
at `core.py:590` (single-segment leaf) is what `subtask` uniquely added; once it is an alias, that
guard belongs to the alias path only — a `start` call with a path argument must keep working.

### 4. `reconcile` → `repair`

Says what it does. Straight rename plus alias. Touches `reconcile.py`, `repairs.py`'s dispatch
names, and a lot of report text and docstrings — grep for the word, not just the symbol.

### 5. `sync` absorbs `pull` and `catchup`

The largest item, and the one to do **last** in this stage.

| Target | Meaning |
|---|---|
| `sync` | lane vs its base (today's `sync`) |
| `sync --trunk` | trunk vs origin (today's `pull`) |
| `sync --all` | every lane (today's `sync --all`) |
| `push` | keep as-is |

`catchup` folds in as whichever of these it duplicates — read it first and say in the progress note
which one it became; it is undocumented in the concept doc, so there is no spec to honour, only
behaviour.

`do_pull` is the hardest shape in the codebase (a trial merge as planning input, survivor rebase,
repark). **Do not restructure it here** — this stage moves the *entry point*, not the body. If S1
has landed, `do_pull` also now has an outer `repo_lock` and a post-guard delete-push; preserve both.

## 4. The alias mechanism — build it once, in step 1

Before the first rename, write the helper and its test:

```python
def _deprecated_alias(old: str, new: str) -> None:
    """Register `old` as a hidden Typer command that warns once and forwards to `new`."""
```

Requirements:
- `hidden=True`, so `gitman --help` shows the new name only and the verb count *drops*.
- The warning goes in the report's `notes`, not to stderr — reports are the interface (concept §16),
  and a note is what `--json` consumers can see.
- Forwarding preserves every option and the exit code. Test that: call the alias with a flag and
  assert the same `IntentResult` as the new name.

A table of `(old, new)` pairs plus one loop is better than five hand-written shims.

## 5. Tests

New file `tests/test_issue44_stage6_verbs.py`.

```python
def test_every_deprecated_alias_warns_and_forwards():
    """Table-driven over the (old, new) pairs: the alias returns the same outcome and exit code,
    and its report carries a note naming the replacement."""

def test_aliases_are_hidden_from_help():
    """`gitman --help` lists the new names only — the surface shrinks."""

def test_workspace_list_annotates_laneless_registrations(tmp_path):

def test_workspace_forget_never_removes_a_directory_gitman_did_not_create(tmp_path):
    """The D2 rule, asserted for the new verb. D2 destroyed operator state in the field."""

def test_workspace_prune_only_takes_empty_and_laneless(tmp_path):

def test_sync_trunk_is_the_old_pull(tmp_path):
    """Same effect, same report shape, via the new entry point."""
```

Expect churn across the existing suite — this is the stage most likely to touch every test file
that calls `do_save`. That is why it comes after the layers below have stopped moving.

## 6. Done when

- [ ] Old verb names still work, warn once in the report's notes, and name their replacement.
- [ ] `gitman --help` lists fewer verbs than the 24 it lists today; aliases are hidden.
- [ ] `workspace list` / `forget` / `prune` exist and route through the existing no-rmtree policy.
- [ ] `status` mentions laneless workspace registrations.
- [ ] `do_save` is `do_describe` and `IntentResult.intent` follows.
- [ ] Suite green (383 + ~6, minus whatever the renames consolidate).
- [ ] Mark G5 shipped in `.scratch/projects/44-report-integrity-and-intent-architecture/ISSUE.md`
      §10. **Do not update `GITMAN_CONCEPT.md` — that is S8's job**, and doing it here means doing
      it twice.
