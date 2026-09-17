"""S2 / issue 44 stage 4e: `doctor` classifies the colocated index's intent-to-add entries.

jj's snapshot stages a jj-tracked, git-uncommitted file as an intent-to-add entry (mode 100644,
the empty blob, `CE_INTENT_TO_ADD`) — correct and load-bearing (Nix flake evaluation reads the
git tree), but indistinguishable to a raw-git reader from index corruption (issue 41). The
classifier splits it by consequence: `expected` (absent from git HEAD — a plain `git commit`
ignores it, nothing at risk) vs `diverged` (present in git HEAD — a plain `git commit` would
record a deletion, because jj's parent and git's HEAD disagree about the path).
"""

from __future__ import annotations

from pathlib import Path

from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.core import do_land, do_save, do_start
from gitman.doctor import OK, WARN, run_doctor
from gitman.init import do_init
from gitman.session import Session
from gitman.state import intent_to_add_entries


def _repo(d: Path) -> Workspace:
    ws = Workspace.init(d, colocate=True)
    (d / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
    do_init(Session.load(d, GitmanConfig()), trunk_opt=None)
    with ws.transaction("advance") as tx:
        tx.new("main")
    ws.git_export()
    ws.sync_colocated()
    return ws


def _check(report, name):
    return next(c for c in report.checks if c.name == name)


def test_expected_intent_to_add_is_informational(tmp_path: Path):
    """A jj-tracked, git-uncommitted file classifies as `expected`, and doctor stays OK."""
    d = tmp_path
    ws = _repo(d)

    do_start(Session.load(d), "work", workspace=False)
    (d / "new.txt").write_text("new\n")
    do_save(Session.load(d), "add new.txt")
    # Index/checkout sync is a publish/push-only side effect since stage 4d; force it here to get
    # the shape a real publish/push (or a hand-run `sync_colocated`) leaves — an ordinary `save`
    # alone doesn't touch the colocated index at all.
    ws.sync_colocated()

    session = Session.load(d)
    expected, diverged = intent_to_add_entries(session.view(), session.ws)
    assert "new.txt" in expected
    assert diverged == []

    check = _check(run_doctor(d), "colocated-index")
    assert check.level == OK
    assert "1" in check.detail


def test_classifier_ignores_the_blob_hash(tmp_path: Path):
    """A genuinely empty, committed file is NOT reported — the classifier keys on the flag.

    This is the regression test that matters — it is the exact false positive issue 41 documents:
    keying on the empty blob alone would flag this file too, and it must not.
    """
    d = tmp_path
    ws = _repo(d)

    do_start(Session.load(d), "work", workspace=False)
    (d / "empty.txt").write_text("")
    do_save(Session.load(d), "add empty.txt")
    do_land(Session.load(d), ["work"])
    ws.git_export()
    ws.sync_colocated()  # empty.txt now genuinely committed to git HEAD, real (empty) blob

    session = Session.load(d)
    expected, diverged = intent_to_add_entries(session.view(), session.ws)
    assert "empty.txt" not in expected
    assert "empty.txt" not in diverged

    check = _check(run_doctor(d), "colocated-index")
    assert check.level == OK
    assert "no intent-to-add entries" in check.detail


class _FakeHead:
    def __init__(self, oid: str | None) -> None:
        self.oid = oid


class _FakeEntry:
    def __init__(self, path: str, intent_to_add: bool) -> None:
        self.path = path
        self.intent_to_add = intent_to_add


class _FakeGit:
    def __init__(self, entries: list[_FakeEntry], head_oid: str | None) -> None:
        self._entries = entries
        self._head_oid = head_oid

    def index_entries(self) -> list[_FakeEntry]:
        return self._entries

    def head(self) -> _FakeHead:
        return _FakeHead(self._head_oid)


class _FakeWs:
    def __init__(self, entries: list[_FakeEntry], head_oid: str | None) -> None:
        self.git = _FakeGit(entries, head_oid)


class _FakeView:
    def __init__(self, head_paths: list[str]) -> None:
        self._head_paths = head_paths

    def file_list(self, oid: str) -> list[str]:
        return self._head_paths


def test_diverged_intent_to_add_warns():
    """A path in git HEAD that is intent-to-add in the index is the DA case — doctor WARNs.

    Building the end-to-end shape (jj's parent and git's HEAD genuinely disagreeing about one
    path, in a real colocated repo) needs a rewind-without-reexport that also has to dodge an
    ordinary ref-mismatch on the same bookmark — fragile enough that a scratch probe could not
    pin it reliably. Per the guide's own fallback, this asserts the classifier directly on a
    synthesised `(entries, head_paths)` pair instead; the end-to-end DA case is untested (recorded
    in the S2 progress note).
    """
    entries = [_FakeEntry("a.txt", False), _FakeEntry("b.txt", True), _FakeEntry("c.txt", True)]
    view = _FakeView(head_paths=["a.txt", "b.txt"])  # b.txt is BOTH intent-to-add AND in HEAD
    ws = _FakeWs(entries, head_oid="deadbeef")

    expected, diverged = intent_to_add_entries(view, ws)  # type: ignore[arg-type]

    assert diverged == ["b.txt"]
    assert expected == ["c.txt"]


def test_doctor_warns_on_a_diverged_result(tmp_path: Path, monkeypatch):
    """Wired the other way round: given a `diverged` result, `doctor`'s row WARNs and names it."""
    import gitman.state as state

    d = tmp_path
    _repo(d)
    monkeypatch.setattr(state, "intent_to_add_entries", lambda view, ws: ([], ["b.txt"]))

    check = _check(run_doctor(d), "colocated-index")
    assert check.level == WARN
    assert "b.txt" in check.detail
    assert "gitman repair" in check.detail
