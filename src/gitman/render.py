"""Compact agent-facing reports (plain Python, no deps). Testee-style: a header line
`Gitman <intent> — <OUTCOME>`, then the minimum an agent needs to act. Mutating reports
end with an inline Undo line. See concept §16.
"""

from __future__ import annotations

from gitman.anomalies import ANOMALY_ORDER, REGISTRY
from gitman.doctor import FAIL, OK, WARN, DoctorReport
from gitman.lanes import name_parent
from gitman.models import IntentResult, Lane, LaneState, RepoState

_GLYPH = {OK: "ok ", WARN: "!! ", FAIL: "XX "}

# Issue 44 stage 3c (guide §3.8): the status headline + recovery hint, keyed on the anomaly's
# `kind` rather than substring-matched out of the composed `off_canonical` prose. The prose is no
# longer load-bearing anywhere — this is the one authoring site for "what to tell the operator",
# same as `off_canonical` is the one authoring site for "what happened" (models.RepoState). When
# more than one kind is present, `ANOMALY_ORDER` breaks the tie (below) — the same fixed severity
# order `state.py` composes `off_canonical` in.
_STATUS_BY_KIND: dict[str, tuple[str, str]] = {
    # A locally-conflicted trunk (jj vs colocated git) is NOT the origin-divergence case — both
    # read as trunk breakage, but `sync --trunk` cannot resolve a jj↔git conflict; only `repair`
    # can.
    "trunk-conflicted": (
        "DIVERGED",
        "Recover: `gitman repair`  — keeps jj's side as trunk, adopts git's side into a lane.",
    ),
    "trunk-diverged": (
        "DIVERGED",
        "Recover: `gitman sync --trunk`  — rebase your local lands onto origin/<trunk>.",
    ),
    "lane-conflicted": ("OFF-CANONICAL", "Recover: `gitman repair`  — resolve the conflicted lane bookmark."),
    "stray-change": ("OFF-CANONICAL", "Recover: `gitman repair`  — adopt it into a lane, or abandon it."),
    "lane-non-linear": ("OFF-CANONICAL", f"Recover: {REGISTRY['lane-non-linear'].manual}."),
    # Stage 3d gave this kind a real repair, so the hint names the repair, not the manual fallback
    # — `manual` is now the genuine-fork residue, which only `repair` itself can report on
    # (it is the verb that knows the content relation).
    "lane-divergent": (
        "OFF-CANONICAL",
        "Recover: `gitman repair`  — classifies the lane against its forge twin by content.",
    ),
    # Not "re-sync refs to jj" any more — repair now heals in whichever direction the drift
    # runs, adopting git-only history instead of discarding it (issue 31).
    "ref-mismatched": (
        "DESYNCHRONIZED",
        "Recover: `gitman repair`  — heal jj and colocated git; no commits are discarded.",
    ),
}
_DEFAULT_STATUS = ("OFF-CANONICAL", "Recover: `gitman repair`  — adopt it into a lane, or abandon it.")


def render_doctor(report: DoctorReport) -> str:
    has_warn = any(c.level == WARN for c in report.checks)
    has_fail = any(c.level == FAIL for c in report.checks)
    if has_fail:
        outcome = "PROBLEMS"
    elif has_warn:
        outcome = "WARNINGS"
    else:
        outcome = "HEALTHY"
    lines = [f"Gitman doctor — {outcome}"]
    for c in report.checks:
        lines.append(f"  {_GLYPH.get(c.level, '   ')}{c.name:<14} {c.detail}")
    if report.exit_code != 0:
        lines.append("Fix the XX checks above, then re-run `gitman doctor`.")
    return "\n".join(lines)


def _diff_str(ins: int, dels: int) -> str:
    return f"+{ins} −{dels}"


def _remote_relation(trunk) -> str:
    """The `(… <remote>)` suffix on the trunk line — the content-aware relation, only when a
    remote trunk is known (`trunk.relation` set). Named for the actual remote, never a hard-coded
    `origin`."""
    if not trunk.remote or not trunk.relation:
        return ""
    r = trunk.remote
    if trunk.relation == "in-sync":
        return f"  (in sync with {r})"
    if trunk.relation == "local-ahead":
        return f"  ({trunk.ahead_remote} ahead {r})"
    if trunk.relation == "forge-ahead":
        return f"  ({trunk.behind_remote} behind {r})"
    if trunk.relation == "diverged":
        return f"  (diverged from {r}: {trunk.behind_remote} behind, {trunk.ahead_remote} ahead)"
    return ""


def _lane_line(lane: Lane, current: str | None) -> str:
    here = lane.name == current
    marker = "*" if here else " "
    # Fractal lanes: indent by task-tree depth. Alphabetical enumeration of `/`-path names IS pre-order
    # DFS (`T`, `T/api`, `T/api/handler`, `T/web`), so the indent alone renders the work-breakdown tree.
    indent = "  " * lane.depth
    # A conflicted lane bookmark (head is None) names no single commit — show the divergence, not a
    # diff summary, and point at the recovery verb.
    if lane.head is None:
        counts = "CONFLICTED (diverged from origin — `gitman repair`)"
    else:
        plural = "change" if lane.change_count == 1 else "changes"
        counts = f"{lane.change_count} {plural}, {_diff_str(lane.insertions, lane.deletions)}"
    extra = []
    if lane.orphaned:
        # I3′: name-parent deleted out-of-band — the node is valid but its stack link is dangling.
        parent = name_parent(lane.name)
        extra.append(f"ORPHANED (name-parent '{parent}' gone — `gitman repair`)")
    elif lane.base:
        extra.append(f"↳ on {lane.base}")  # fractal lanes: this lane is stacked on <base>
    if lane.workspace:
        extra.append(f"ws {lane.workspace}")
    if lane.conflict and lane.head is not None:
        extra.append("CONFLICT (not blocked — resolve later)")
    if lane.non_linear:
        extra.append("NON-LINEAR (merge commit — `gitman repair`)")
    if lane.divergent:
        extra.append("DIVERGENT (change-id → multiple commits — `gitman repair`)")
    if lane.state == LaneState.merged:
        extra.append("merged on the forge — `gitman sync --trunk` retires it locally")
    if lane.pr:
        extra.append(f"PR #{lane.pr.number}")
    if lane.behind:
        extra.append(f"{lane.behind} behind {lane.base or 'trunk'}")
    if here:
        extra.append("you are here")
    tail = ("   · " + "  · ".join(extra)) if extra else ""
    return f"{marker} {indent}{lane.name:<20} {lane.state.value:<10} {counts}{tail}"


def render_status(state: RepoState) -> str:
    if not state.canonical:
        by_kind = {a.kind for a in state.anomalies}
        headline, recover = next(
            (_STATUS_BY_KIND[k] for k in ANOMALY_ORDER if k in by_kind and k in _STATUS_BY_KIND),
            _DEFAULT_STATUS,
        )
        return "\n".join(
            [
                f"Gitman status — {headline}",
                f"Reason: {state.off_canonical}",
                recover,
                "Exit: 1",
            ]
        )

    n = len(state.lanes)
    header = f"Gitman status — CANONICAL · {n} lane{'' if n == 1 else 's'}"
    trunk = state.trunk
    trunk_line = f"trunk: {trunk.name} @ {trunk.commit_id or '?'}{_remote_relation(trunk)}"
    lines = [header, trunk_line]
    for lane in state.lanes:
        lines.append(_lane_line(lane, state.current_lane))
    for note in state.notes:
        lines.append(f"note: {note}")
    # Issue 38 / 44 G3 (S4): the field, rendered — never re-derived here. A co-tenant's work is a
    # real condition on a CANONICAL repo, so it is not an anomaly; it is a warning block.
    if state.foreign_paths:
        ident = state.session_identity or "this session"
        shown = state.foreign_paths[:8]
        lines.append("")
        lines.append(f"!! {len(state.foreign_paths)} path(s) in @ were not written by this session ({ident}):")
        lines.extend(f"     {path}" for path in shown)
        if len(state.foreign_paths) > len(shown):
            lines.append(f"     … and {len(state.foreign_paths) - len(shown)} more")
        lines.append("   Another session may be working here. `gitman describe` describes ALL of it —")
        lines.append("   carve theirs out first: `gitman split --paths <theirs> --into parked/other`.")
    if not state.lanes:
        lines.append("No lanes yet — `gitman start <name>` to begin.")

    # Surfaced recovery hint: when CANONICAL but behind/ahead origin, name the catch-up/publish
    # verb. Mirrors the off-canonical recovery pattern so the next action is always discoverable.
    relation = state.trunk.relation
    if relation in ("forge-ahead", "diverged"):
        lines.append("")
        lines.append(f"Recover: `gitman sync --trunk`  — your {state.trunk.name} is behind origin.")
    elif relation == "local-ahead" and state.trunk.ahead_remote:
        lines.append("")
        lines.append(f"Recover: `gitman push`  — publish your local {state.trunk.name} to origin.")

    return "\n".join(lines)


def render_intent(result: IntentResult) -> str:
    """Compact report for a mutating intent; ends with an inline Undo line (concept §16)."""
    lane = f" [{result.lane}]" if result.lane else ""
    lines = [f"Gitman {result.intent}{lane} — {result.outcome}"]
    lines.extend(result.messages)
    lines.extend(f"note: {n}" for n in result.notes)
    if result.undo_command:
        lines.append(f"Undo: `{result.undo_command}`")
    return "\n".join(lines)
