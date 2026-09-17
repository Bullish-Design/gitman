"""The `Plan` value: intent + subjects + declarative steps + an additive postcondition.

`GITMAN_CONCEPT.md` §6 promises an intent-planner / executor split. Before this module every
`do_*` in `core.py` interleaved planning, execution and result-interpretation, so the anomaly
gate's subject list, the transaction wrapper, the inline undo line, `--dry-run` and partial-
progress bookkeeping were each re-derived per verb. A `Plan` written once makes all of them
free: the executor (`invariants.run_plan`) reads `subjects`, `steps` and `postcondition`, and
`describe_plan` renders the same steps for `--dry-run` without running them.

**D-D1 — a `Step` is a declarative record, not a closure.** The guide's recommendation, taken
literally for the step kinds the five migrated verbs (`describe`, `switch`, `start`, `split`,
`land`) actually use — no general jj-operation algebra. A closure would give the gate and the
undo line, but a closure cannot be described, so it cannot back `--dry-run`. The types below are
exactly the transaction operations those five verbs perform.

**D-D2 — `Plan.postcondition` is ADDITIVE.** `invariants._postcondition` runs a delta-based,
global check: any anomaly present after but not before was introduced by this intent. That check
is stronger than any per-plan predicate and must never be weakened, so the executor runs
`plan.postcondition` **after** `_postcondition` passes, never instead of it. The callable returns
`None` when the plan held, else a reason string for the failure report. (The guide sketches a
`bool`; a reason string is strictly more useful and still a predicate.)

The transaction steps and the outside steps are separated because jj operations must run inside
one `ws.transaction`, while a workspace cleanup or a colocated-ref delete publishes its own op
and must run after that transaction commits (matching the pre-migration code).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gitman.anomalies import Subject
    from gitman.models import RepoState


# --- transaction steps -----------------------------------------------------------------


@dataclass(frozen=True)
class New:
    """`tx.new(parents)` — a new change on top of `parents` (`None` = a child of the current `@`)."""

    parents: str | list[str] | None = None


@dataclass(frozen=True)
class Edit:
    """`tx.edit(revision)` — point `@` at an existing change."""

    revision: str


@dataclass(frozen=True)
class Describe:
    """`tx.describe(revision, message)` — set a change's description."""

    revision: str
    message: str


@dataclass(frozen=True)
class CreateBookmark:
    """`tx.create_bookmark(name, revision)` — refuses if the name already exists."""

    name: str
    revision: str


@dataclass(frozen=True)
class SetBookmark:
    """`tx.set_bookmark(name, revision)` — create-or-move a bookmark."""

    name: str
    revision: str


@dataclass(frozen=True)
class DeleteBookmark:
    """`tx.delete_bookmark(name)` — refuses if the name is absent."""

    name: str


@dataclass(frozen=True)
class Rebase:
    """`tx.rebase(revision, onto=onto, mode=mode)`.

    `conflict_reason` opts into a post-step conflict check: when the rebased commit comes back
    conflicted, the executor raises `GitmanError(conflict_reason, exit_code=1)` — the refusal the
    verb already produced. It is `None` by default because `mode="branch"` returns a STALE
    `has_conflict` when the rebased change has a descendant `@` (`land`'s non-trunk fold
    pre-checks that case textually instead and never trusts the returned flag)."""

    revision: str
    onto: str
    mode: str = "source"
    conflict_reason: str | None = None


@dataclass(frozen=True)
class Restore:
    """`tx.restore(target, from_=from_, paths=paths)` — replace content (or `paths`) from `from_`."""

    target: str
    from_: str
    paths: list[str] | None = None


@dataclass(frozen=True)
class Split:
    """`tx.split(change, selection, mode="siblings")`, then bookmark the carved side.

    The carved commit's change id does not exist until the step runs, so this step owns the
    bookmark-and-describe tail that the verb applies to the split result. `error_message` maps a
    pyjutsu refusal (empty/full selection) to the verb's exit-3 message."""

    change: str
    selection: dict[str, list[int] | None]
    bookmark: str
    message: str | None = None
    error_message: str | None = None


# --- steps that run after the transaction commits (they publish their own op) ----------


@dataclass(frozen=True)
class RetireGitRef:
    """Drop the colocated `refs/heads/<lane>` of a lane this intent just retired in jj."""

    lane: str


@dataclass(frozen=True)
class CleanupWorkspace:
    """Forget (and maybe remove) a retired lane's workspace registration."""

    lane: str
    keep_foreign: bool = False


Step = New | Edit | Describe | CreateBookmark | SetBookmark | DeleteBookmark | Rebase | Restore | Split
OutsideStep = RetireGitRef | CleanupWorkspace


# --- the plan --------------------------------------------------------------------------


@dataclass(frozen=True)
class Plan:
    """What an intent will do, as a value the executor can run and the renderer can describe.

    `subjects` is the anomaly gate's scope (`anomalies.Subject` set), computed by the verb through
    `invariants.subjects_for` — one implementation, so the plan and the gate can never disagree.
    `steps` run inside one `ws.transaction`; `outside_steps` run after it commits.
    `postcondition` is additive to the global delta check (D-D2); it returns `None` when the plan
    held, else the failure reason.
    """

    intent: str
    subjects: list[Subject]
    steps: list[Step] = field(default_factory=list)
    outside_steps: list[OutsideStep] = field(default_factory=list)
    postcondition: Callable[[RepoState], str | None] | None = None
    export: bool = False
    messages: list[str] = field(default_factory=list)
    lane: str | None = None


# --- the dry-run renderer --------------------------------------------------------------


def _rev(revision: str) -> str:
    """Quote a revset for the report, but leave the `@` sigil bare (it reads as itself)."""
    return revision if revision == "@" else f"'{revision}'"


def _step_line(step: Step | OutsideStep) -> str:
    if isinstance(step, New):
        if step.parents is None:
            return "new change at @"
        parents = [step.parents] if isinstance(step.parents, str) else list(step.parents)
        return f"new change on {', '.join(_rev(p) for p in parents)}"
    if isinstance(step, Edit):
        return f"move @ onto {_rev(step.revision)}"
    if isinstance(step, Describe):
        return f'describe {_rev(step.revision)} as "{step.message}"'
    if isinstance(step, CreateBookmark):
        return f"create bookmark '{step.name}' at {_rev(step.revision)}"
    if isinstance(step, SetBookmark):
        return f"set bookmark '{step.name}' to {_rev(step.revision)}"
    if isinstance(step, DeleteBookmark):
        return f"delete bookmark '{step.name}'"
    if isinstance(step, Rebase):
        return f"rebase {_rev(step.revision)} onto {_rev(step.onto)} (mode {step.mode})"
    if isinstance(step, Restore):
        tail = f" paths: {', '.join(step.paths)}" if step.paths else ""
        return f"restore {_rev(step.target)} from {_rev(step.from_)}{tail}"
    if isinstance(step, Split):
        return f"split {_rev(step.change)} into new lane '{step.bookmark}' ({len(step.selection)} path(s))"
    if isinstance(step, RetireGitRef):
        return f"retire colocated git ref '{step.lane}'"
    if isinstance(step, CleanupWorkspace):
        return f"forget workspace for '{step.lane}'"
    raise AssertionError(f"unrenderable plan step: {step!r}")  # every Step above is handled


def describe_plan(plan: Plan) -> list[str]:
    """Render a plan as one line per step, for `--dry-run`. Deterministic; never runs a step."""
    lines = [_step_line(step) for step in plan.steps]
    lines += [_step_line(step) for step in plan.outside_steps]
    return lines or ["nothing to do."]
