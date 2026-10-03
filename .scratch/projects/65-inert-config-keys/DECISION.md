# 65 — Three declared config keys have no effect

**Date:** 2026-10-02. The operator chose the recommendations below.

## Measurement

`config.py` accepts `[policy] protected`, `[lanes] always_workspace`, and
`[publish] branch_prefix`. No production reader outside `config.py` uses any
of them. Two tests assert that the keys parse; neither tests their effect.
The current scan found zero configured uses among 70 active repository
`gitman.toml` files. A broader scan finds 78 files because it includes archived
repositories. The annotated example file named all three, but it is not a
fleet config. The handoff's active fleet count was correct.

`protected` has the greatest risk. It promises safety for a ref rewrite, but
does nothing when that rewrite matters. The workspace and prefix keys produce
visible outcomes, so their failure is easier to detect.

## Decision and change

| Key | Decision | Deciding fact | Other choices and cost |
|---|---|---|---|
| `protected` | Deleted the field and claim; a configured table warns | pyjutsu already protects commits under trunk, tags, and untracked remote bookmarks; this list cannot configure that rule | Implement: a second ref policy across rewrite and push paths can drift from pyjutsu. Keep: retain a setting that cannot protect a ref, even with a warning. |
| `always_workspace` | Implemented the default | `do_start` already has a workspace path; the key now selects it when the flag is absent | Delete: remove the advertised default. Keep: retain an inert key and a warning. |
| `branch_prefix` | Deleted the field and claim; a configured key warns | Invariant I3 sets the git branch name equal to the lane name | Implement: revise branch identity, publication, tracking, and branch retirement. Keep: retain an inert claim and warning. |

`do_start` now refuses `--adopt-all` and `--adopt-mine` with an isolated start.
The old workspace branch silently ignored those flags. This refusal prevents
the new default from turning an adoption request into a no-op.

The existing `RETIRED_TABLES` and `cfg.deprecations` flow provides the warning
for `[policy]`. A new `RETIRED_KEYS` entry warns for `branch_prefix` while
keeping `[publish]` active. `doctor` already warns when `on_fail = "block"`
has no verify command. Configured old keys keep the tool usable and print a
migration note.

## Proposed guard

Add one test that walks `GitmanConfig.model_fields` and its nested Pydantic
models. It should derive the declared leaf paths from the model, then parse the
22 production Python files outside `config.py` with `ast`. For each path, require
a runtime read or an explicit exception with a reason. Exclude load-time
metadata (`source_path`, `deprecations`) because these are not config input.
The old model declared 21 config leaf fields; the new model declares 19. The test should fail when a
new field has no reader, with the exact field path in its error. A short
exception table keeps deliberate declaration-only fields visible.

This costs one test module and maintenance when a field or its read path moves.
It must recognize `cfg`, `config`, and `session.config` paths; a text search
would confuse a comment or a string with a read. The guard proves that code
reads a field somewhere. It cannot prove that a read enforces the claim:
`allowed_paths` is read today, yet matching paths still cause a land refusal.

Project 041's `test_doctor.py` guard is the precedent. It parses `doctor.main()`
to derive the check list and requires each check to name a firing test or an
informational reason. It does not copy the check list by hand.

## Verification

The baseline suite passed: `675 passed in 32.12s`. The focused config and
workspace tests pass: `33 passed in 2.76s`. Ruff reports `All checks passed!`.
After the change, `pytest -q` reports `679 passed in 30.93s`.

## Left for other work

The proposed field-read guard is not implemented here. A read would not prove
that a key does what it claims; the existing `allowed_paths` defect is the
example. This work does not change land hooks or their snapshot rule.

`gitman doctor` reports `XX colocated` from this separate workspace because it
looks for `.git` and `.jj` in that directory. `gitman status` reports the lane
canonical, and `gitman doctor` from the main checkout reports healthy. This
workspace diagnostic is outside the three-key cleanup.
