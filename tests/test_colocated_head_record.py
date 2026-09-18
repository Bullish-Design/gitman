"""S9: `doctor`/`reconcile` were blind to jj's OWN record of colocated-git state going stale.

`colocated_ref_desync` compares jj bookmarks against the actual `refs/heads/*` — the two can
agree (so the old code reported CLEAN/HEALTHY) while jj's *records* of them are still stale: a
`restore_operation` (an `undo`, or a rolled-back postcondition) rewinds jj's memory of git-side
writes that genuinely happened, leaving `.git/HEAD` and a bookmark's `<name>@git` row behind.

The detection is NOT "HEAD != `@`'s parent" — that alone is true almost always under ordinary
operation (`HEAD`/the index only move via `sync_colocated`, a publish/push-only side effect since
stage 4d, so `HEAD` legitimately lags every local write between two publishes). `HEAD` and every
`<name>@git` row only ever move TOGETHER, so the real signal is `HEAD` disagreeing with EVERY
`<name>@git` record, not merely lagging `@`. Built here with direct raw-git writes (the same
"a test may do what gitman may not" idiom `test_orphaned_git_head.py` uses) reproducing the
measured live-repo shape: three genuinely different commits for `HEAD`, `main@git`, and the actual
ref (`.scratch/projects/46-remaining-refactor/GUIDE_S9_colocated_head_blindspot.md` §1).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.core import do_abandon, do_land, do_save, do_start
from gitman.doctor import FAIL, OK, WARN, run_doctor
from gitman.init import do_init
from gitman.repair import do_reconcile
from gitman.session import Session
from gitman.state import capture_state, colocated_head_lag, colocated_record_stale, orphaned_git_head


def _repo(d: Path) -> Workspace:
    ws = Workspace.init(d, colocate=True)
    (d / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
    do_init(Session.load(d, GitmanConfig()), trunk_opt=None)
    with ws.transaction("advance") as tx:
        tx.new("main")  # @ off trunk, so HEAD has something real to detach onto
    ws.git_export()
    ws.sync_colocated()  # establish refs/heads/main + main@git + .git/HEAD, all in sync
    return ws


def _land(d: Path, lane: str, fn: str) -> str:
    do_start(Session.load(d), lane, workspace=False)
    (d / fn).write_text(f"{lane}\n")
    do_save(Session.load(d), f"add {fn}")
    do_land(Session.load(d), [lane])
    return Session.load(d).view().resolve("main").commit_id


def _stale_bookmark_record(d: Path, ws: Workspace) -> str:
    """Land a lane (jj's `main` advances, no export per stage 4d), then force the raw ref to
    jj's new position WITHOUT export/import — `refs/heads/main` now agrees with jj's bookmark,
    but jj's own `main@git` record (and `.git/HEAD`) are both still at the pre-land commit. This
    is the ordinary, self-healing lag for `HEAD` (still matches `main@git`) — only the bookmark
    record is stale. Returns the new (current) commit id."""
    main_now = _land(d, "lane1", "a.txt")
    ws.git.write_ref("main", main_now)
    return main_now


def _stale_full_record(d: Path, ws: Workspace) -> tuple[str, str, str]:
    """The measured live-repo shape: `HEAD`, `main@git`, and the actual ref end up at three
    genuinely DIFFERENT commits (SCOPING.md §4a). Built directly (raw-git writes are the state
    under test, not a supported operation — `test_orphaned_git_head.py`'s own idiom):

      1. land + full sync -> `HEAD` = `main@git` = ref = commit1.
      2. land again, no sync at all (ordinary lag: all three still agree, at commit1).
      3. force the raw ref only to commit2 (jj's bookmark) -> bookmark record stale.
      4. force `.git/HEAD` only back to commit0 -> HEAD record stale, and distinct from BOTH
         `main@git` (commit1) and the ref (commit2) — the three-way split.

    Returns `(commit0, commit1, commit2)`.
    """
    commit0 = Session.load(d).view().resolve("main").commit_id
    commit1 = _land(d, "lane1", "a.txt")
    ws.git_export()
    ws.sync_colocated()
    commit2 = _land(d, "lane2", "b.txt")
    ws.git.write_ref("main", commit2)
    (d / ".git" / "HEAD").write_text(commit0 + "\n")
    return commit0, commit1, commit2


def _check(report, name):
    return next(c for c in report.checks if c.name == name)


def test_doctor_warns_when_head_lags_at_parent(tmp_path: Path):
    """`HEAD` matching no `<name>@git` record at all -> WARN naming the distance, not OK.

    (Merely lagging `@`'s parent is NOT enough — see the module docstring; this specifically
    breaks `HEAD`'s pairing with `main@git`.)
    """
    d = tmp_path
    ws = _repo(d)
    assert _check(run_doctor(d), "colocated-head").level == OK

    _commit0, _commit1, commit2 = _stale_full_record(d, ws)

    check = _check(run_doctor(d), "colocated-head")
    assert check.level == WARN
    assert commit2[:12] in check.detail  # names @'s parent (where HEAD should be)
    assert "commit(s) behind" in check.detail
    assert "gitman repair" in check.detail


def test_doctor_does_not_warn_on_the_ordinary_self_healing_lag(tmp_path: Path):
    """`HEAD` behind `@` but still matching the `<name>@git` it was last synced to -> OK.

    The false-positive this detection must avoid: under stage 4d, `HEAD` legitimately lags every
    local write between two publishes, which would fire on almost every actively-developed repo
    if merely "behind `@`'s parent" were the trigger.
    """
    d = tmp_path
    ws = _repo(d)

    _stale_bookmark_record(d, ws)  # bookmark record goes stale, but HEAD still matches main@git

    check = _check(run_doctor(d), "colocated-head")
    assert check.level == OK


def test_doctor_still_fails_on_a_stranded_head(tmp_path: Path):
    """Project 29's FAIL is unchanged — the new WARN must not swallow it."""
    d = tmp_path
    ws = _repo(d)

    do_start(Session.load(d), "doomed", workspace=False)
    (d / "app.py").write_text("x\n")
    do_save(Session.load(d), "work")
    stranded = Session.load(d).view().resolve("doomed").commit_id
    do_abandon(Session.load(d), lane="doomed")
    (d / ".git" / "HEAD").write_text(stranded + "\n")

    assert orphaned_git_head(Session.load(d).view(), ws) == stranded
    check = _check(run_doctor(d), "colocated-head")
    assert check.level == FAIL
    assert "repair" in check.detail


def test_reconcile_detects_and_repairs_a_stale_git_head_record(tmp_path: Path):
    """reconcile reports the condition (not CLEAN), repairs it, and `git status` is empty after."""
    d = tmp_path
    ws = _repo(d)
    _commit0, _commit1, commit2 = _stale_full_record(d, ws)

    head_note, stale_bookmarks = colocated_record_stale(Session.load(d).view(), ws)
    assert head_note is not None
    assert stale_bookmarks == ["main"]

    result = do_reconcile(Session.load(d), abandon_=False)

    assert result.outcome == "REPAIRED", result.messages
    session = Session.load(d)
    assert colocated_record_stale(session.view(), ws) == (None, [])
    assert ws.git.head().oid == commit2
    assert session.view().resolve("main@git").commit_id == commit2

    out = subprocess.run(["git", "-C", str(d), "status", "--porcelain=v1"], capture_output=True, text=True)
    assert out.stdout.strip() == "", out.stdout


def test_the_repair_never_adopts_an_unreachable_commit_as_a_stray(tmp_path: Path):
    """An object present in the store but unreachable from every ref stays unreachable."""
    d = tmp_path
    ws = _repo(d)

    # A genuinely unreachable commit: land+abandon leaves it visible only in the op log.
    do_start(Session.load(d), "gone", workspace=False)
    (d / "b.txt").write_text("b\n")
    do_save(Session.load(d), "add b")
    unreachable = Session.load(d).view().resolve("gone").commit_id
    do_abandon(Session.load(d), lane="gone")

    before_lanes = {lane.name for lane in Session.load(d).view().bookmarks() if lane.remote is None}
    _stale_full_record(d, ws)

    do_reconcile(Session.load(d), abandon_=False)

    session = Session.load(d)
    after_lanes = {b.name for b in session.view().bookmarks() if b.remote is None}
    # No new lane/bookmark appeared for the abandoned commit — in particular no `adopted-*` lane,
    # which is how a resurrected stray would surface (a bare `resolve()` by commit id succeeds on
    # any object still in the store, hidden or not, so that alone isn't evidence of resurrection).
    assert after_lanes - before_lanes <= {"lane1", "lane2"}  # only the legitimate lands' lanes, if any residue
    assert not any(b.name.startswith("adopted-") for b in session.view().bookmarks())
    assert unreachable not in {c.commit_id for c in session.view().log("trunk()..")}


def test_note_only_never_blocks_an_intent(tmp_path: Path):
    """A `save` on a repo in this state succeeds."""
    d = tmp_path
    ws = _repo(d)
    _stale_full_record(d, ws)

    do_start(Session.load(d), "work", workspace=False)
    (d / "c.txt").write_text("c\n")
    result = do_save(Session.load(d), "add c")

    assert result.outcome == "DESCRIBED", result.messages


def _raw_git_commit(d: Path, msg: str, fn: str = "raw.txt") -> str:
    """Move `refs/heads/main` through raw git plumbing, past a commit jj never imports — the way
    an IDE, CI, or an agent that skips gitman moves a colocated branch (`test_colocated_refs.py`'s
    `_raw_git_commit` idiom, reused here). A scratch index keeps jj's own index and `@` untouched,
    so only the git side moves: the ADOPT direction, one-way."""
    import os

    env = {**os.environ, "GIT_INDEX_FILE": str(d / ".git" / "gitman-test-index")}

    def run(*args: str, inp: str | None = None) -> str:
        p = subprocess.run(["git", *args], cwd=d, env=env, input=inp, check=True, capture_output=True, text=True)
        return p.stdout.strip()

    blob = run("hash-object", "-w", "--stdin", inp=msg + "\n")
    run("read-tree", "main")
    run("update-index", "--add", "--cacheinfo", f"100644,{blob},{fn}")
    tree = run("write-tree")
    sha = run("-c", "user.email=t@t.t", "-c", "user.name=T", "commit-tree", tree, "-p", "main", "-m", msg)
    run("update-ref", "refs/heads/main", sha)
    return sha


def test_a_git_only_ref_move_is_not_reported_as_a_stale_record(tmp_path: Path):
    """`_known_to_jj` must exclude the ADOPT direction from `colocated_record_stale`.

    A raw-git commit jj has never imported moves `refs/heads/main` off the commit jj's bookmark
    still names. That is the ADOPT shape — git holds history jj hasn't seen — and `ref-mismatched`
    already reports it correctly. Without the `_known_to_jj` guard, `colocated_record_stale` would
    ALSO flag `main` as a stale record, reporting the same raw-git commit twice under two
    different anomalies.
    """
    d = tmp_path
    ws = _repo(d)
    _git_sha = _raw_git_commit(d, "raw commit")

    session = Session.load(d)
    _head_note, stale_bookmarks = colocated_record_stale(session.view(), ws)
    assert "main" not in stale_bookmarks  # excluded — this is ADOPT, not a stale record

    kinds = {(a.kind, a.subject.name) for a in capture_state(session).anomalies}
    assert ("ref-mismatched", "main") in kinds  # the correct anomaly for this shape
    assert ("colocated-record-stale", "main") not in kinds  # not double-reported


def test_head_at_working_copy_parent_is_never_stale(tmp_path: Path):
    """Issue 47: `HEAD` on `@`'s parent is healthy, even when no bookmark names that commit.

    jj parks `HEAD` at `@`'s parent on every `@` move. So an `@` that sits off trunk — one behind
    it, or on any unbookmarked change — drags `HEAD` away from every `<name>@git` target. That is
    not staleness, and `repair` cannot change it: `git_import` + `sync_colocated` never move `HEAD`
    off `@`'s parent, so a report here would re-fire forever.
    """
    d = tmp_path
    ws = _repo(d)
    session = Session.load(d)
    view = session.view()
    head = ws.git.head()
    parent_ids = view.working_copy().parent_ids
    assert head is not None and parent_ids and head.oid == parent_ids[0], "fixture: HEAD tracks @"

    assert colocated_head_lag(view, ws) is None
    kinds = {a.kind for a in capture_state(Session.load(d)).anomalies}
    assert "colocated-record-stale" not in kinds
