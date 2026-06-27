"""Compact agent-facing reports (plain Python, no deps). Testee-style: a header line
`Gitman <intent> — <OUTCOME>`, then the minimum an agent needs to act. Mutating reports
end with an inline Undo line. See concept §16.
"""

from __future__ import annotations

from gitman.doctor import FAIL, OK, WARN, DoctorReport
from gitman.models import IntentResult, Lane, RepoState

_GLYPH = {OK: "ok ", WARN: "!! ", FAIL: "XX "}


def render_doctor(report: DoctorReport) -> str:
    outcome = "HEALTHY" if report.exit_code == 0 else "PROBLEMS"
    lines = [f"Gitman doctor — {outcome}"]
    for c in report.checks:
        lines.append(f"  {_GLYPH.get(c.level, '   ')}{c.name:<14} {c.detail}")
    if report.exit_code != 0:
        lines.append("Fix the XX checks above, then re-run `gitman doctor`.")
    return "\n".join(lines)


def _diff_str(ins: int, dels: int) -> str:
    return f"+{ins} −{dels}"


def _remote_relation(trunk) -> str:
    """The `(… origin)` suffix on the trunk line — only when a remote trunk is known."""
    bits = []
    if trunk.behind_remote:
        bits.append(f"{trunk.behind_remote} behind")
    if trunk.ahead_remote:
        bits.append(f"{trunk.ahead_remote} ahead")
    if not bits:
        return ""
    return f"  ({', '.join(bits)} origin)"


def _lane_line(lane: Lane, current: str | None) -> str:
    here = lane.name == current
    marker = "*" if here else " "
    plural = "change" if lane.change_count == 1 else "changes"
    counts = f"{lane.change_count} {plural}, {_diff_str(lane.insertions, lane.deletions)}"
    extra = []
    if lane.workspace:
        extra.append(f"ws {lane.workspace}")
    if lane.conflict:
        extra.append("CONFLICT (not blocked — resolve later)")
    if lane.pr:
        extra.append(f"PR #{lane.pr.number}")
    if lane.behind:
        extra.append(f"{lane.behind} behind trunk")
    if here:
        extra.append("you are here")
    tail = ("   · " + "  · ".join(extra)) if extra else ""
    return f"{marker} {lane.name:<20} {lane.state.value:<10} {counts}{tail}"


def render_status(state: RepoState) -> str:
    if not state.canonical:
        diverged = bool(state.off_canonical) and "diverged" in state.off_canonical
        recover = (
            "Recover: `gitman adopt`  — adopt the forge-merged trunk (`--force` to take origin)."
            if diverged
            else "Recover: `gitman reconcile`  — adopt it into a lane, or abandon it."
        )
        return "\n".join(
            [
                f"Gitman status — {'DIVERGED' if diverged else 'OFF-CANONICAL'}",
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
    if not state.lanes:
        lines.append("No lanes yet — `gitman start <name>` to begin.")
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
