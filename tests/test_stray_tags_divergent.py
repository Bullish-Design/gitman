"""Issue 06 — stray detection vs git tags (G1) + divergent-change reconcile (G2).

Built in-process over pyjutsu (no `jj` CLI), mirroring `test_remote_stray.py` /
`test_m3_integration.py`:

- **G1** — a *tagged* off-main commit is intentional history, not a stray. `state._stray_revset`
  now excludes `tags()`, so `find_strays` skips it while an *untagged* off-main commit is still
  flagged (regression).
- **G2** — a *divergent* change-id (one change_id → two commits, as manufactured by orphaned
  `refs/jj/keep/*` after a forge `git_import`) makes `tx.abandon(change_id)` /
  `tx.create_bookmark(name, change_id)` raise `Change ID … is divergent`, dead-ending `reconcile`
  (the sole recovery path). `do_reconcile` now targets — and *names* — each stray by `commit_id`,
  so both divergent sides adopt into two distinct lanes (or both abandon).
"""

from __future__ import annotations

import subprocess as sp
from pathlib import Path

import pytest
from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.core import do_abandon
from gitman.init import do_init
from gitman.reconcile import do_reconcile
from gitman.session import Session
from gitman.state import capture_state, find_strays


def _git(d: Path, *args: str, inp: str | None = None) -> sp.CompletedProcess[str]:
    return sp.run(["git", "-C", str(d), *args], input=inp, capture_output=True, text=True, check=True)


def _init_main(d: Path) -> Workspace:
    """A colocated repo with a frozen `main` trunk (init creates the bookmark + `.gitman`)."""
    ws = Workspace.init(d, colocate=True)
    (d / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "1.0.0"\n')
    (d / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")  # NO bookmark yet — do_init freezes trunk=main
    do_init(Session.load(d, GitmanConfig()), trunk_opt=None)
    return ws


def _child_offmain(ws: Workspace, d: Path, fname: str, body: str, desc: str):
    """Create a non-empty child of `main`, then move `@` off it so it's an unbookmarked, off-`@`
    descendant of trunk. Returns the child Commit (carrying change_id + commit_id)."""
    with ws.transaction(desc) as tx:
        tx.new("main")
        tx.describe("@", desc)
    (d / fname).write_text(body)
    ws.snapshot()
    child = ws.working_copy()
    ws.git_export()
    with ws.transaction("move @") as tx:
        tx.new("main")  # @ becomes a fresh empty change; the child is left unbookmarked
    ws.snapshot()
    return child


def _forge_divergent_side(ws: Workspace, d: Path, change_id: str, body: str) -> str:
    """Forge a *second* git commit that shares `change_id` (the in-process way to manufacture a
    divergent change without the jj CLI — the orphaned-keep-ref scenario): write a distinct tree,
    stamp the same `change-id` header, anchor it under `refs/heads/_keep` so `git_import` picks it
    up, import, then drop the bookmark so both sides sit unbookmarked (and so the `tags()`
    exclusion can't hide it). Returns the forged commit's git sha."""
    main_sha = ws.resolve("main").commit_id
    blob = _git(d, "hash-object", "-w", "--stdin", inp=body).stdout.strip()
    tree = _git(d, "mktree", inp=f"100644 blob {blob}\tdiverge.txt\n").stdout.strip()
    commit = (
        f"tree {tree}\nparent {main_sha}\n"
        f"author Forge <x@y.z> 1782855900 -0400\n"
        f"committer Forge <x@y.z> 1782855900 -0400\n"
        f"change-id {change_id}\n\nforged divergent side\n"
    )
    sha = _git(d, "hash-object", "-t", "commit", "-w", "--stdin", inp=commit).stdout.strip()
    _git(d, "update-ref", "refs/heads/_keep", sha)
    ws.git_import()
    with ws.transaction("drop _keep") as tx:
        tx.delete_bookmark("_keep")
    ws.snapshot()
    return sha


# --- G1: tags are not strays ----------------------------------------------------------


def test_tagged_offmain_commit_is_not_a_stray(tmp_path: Path):
    ws = _init_main(tmp_path)
    child = _child_offmain(ws, tmp_path, "tagged.txt", "release\n", "tagged work")
    # An annotated git tag on the off-main commit, imported so jj's `tags()` resolves it.
    _git(tmp_path, "tag", "-a", "-m", "v1.0.0", "v1.0.0", child.commit_id)
    ws.git_import()

    view = Session.load(tmp_path, GitmanConfig(trunk="main")).fresh_view()
    assert find_strays(view, "main") == []
    state = capture_state(Session.load(tmp_path, GitmanConfig(trunk="main")))
    assert state.canonical, state.off_canonical


def test_untagged_offmain_commit_is_still_a_stray(tmp_path: Path):
    """Regression: G1 must only suppress *tagged* off-main commits — an ordinary stray still flags."""
    ws = _init_main(tmp_path)
    _child_offmain(ws, tmp_path, "stray.txt", "stray\n", "stray work")

    view = Session.load(tmp_path, GitmanConfig(trunk="main")).fresh_view()
    strays = find_strays(view, "main")
    assert len(strays) == 1
    state = capture_state(Session.load(tmp_path, GitmanConfig(trunk="main")))
    assert state.canonical is False
    assert "belong to no lane" in (state.off_canonical or "")


# --- lane 6c: a tag protects a commit from abandon -------------------------------------


def test_abandon_refuses_a_tagged_lane_and_names_the_tag(tmp_path: Path):
    """Project 34, lane 6c. Since pyjutsu 0.16 `tags()` is a term of `immutable_heads()`, so a
    tagged lane commit cannot be abandoned. gitman REFUSES and names the protection — it never
    opens a transaction with `ignore_immutable=True`. The lane survives the refusal intact."""
    from gitman.core import GitmanError, do_save, do_start

    ws = _init_main(tmp_path)
    sess = lambda: Session.load(tmp_path, GitmanConfig(trunk="main"))  # noqa: E731
    do_start(sess(), "tagged-lane", workspace=False)
    (tmp_path / "work.txt").write_text("work\n")
    do_save(sess(), "lane work")

    head = sess().fresh_view().resolve("tagged-lane").commit_id
    _git(tmp_path, "tag", "-a", "-m", "v2.0.0", "v2.0.0", head)
    ws.git_import()

    with pytest.raises(GitmanError) as exc:
        do_abandon(sess(), "tagged-lane")
    assert exc.value.exit_code == 1
    assert "a tag protects it" in str(exc.value)
    assert "ignore_immutable" not in str(exc.value)
    # Nothing was destroyed: the lane is still there.
    assert "tagged-lane" in {lane.name for lane in capture_state(sess()).lanes}


def test_gitman_never_overrides_immutability():
    """The lane 6c policy is checkable, not only stated: no gitman transaction passes
    `ignore_immutable=True`. Prose that names the escape hatch is fine; code that uses it is not,
    so the scan reads each line with its comment stripped."""
    import io
    import tokenize

    src = Path(__file__).resolve().parents[1] / "src" / "gitman"
    hits = []
    for path in sorted(src.rglob("*.py")):
        text = path.read_text()
        code = [
            tok.string
            for tok in tokenize.generate_tokens(io.StringIO(text).readline)
            if tok.type not in (tokenize.COMMENT, tokenize.STRING)
        ]
        if "ignore_immutable" in code:
            hits.append(str(path.relative_to(src)))
    assert hits == [], hits


# --- G2: reconcile recovers a divergent stray -----------------------------------------


def _divergent_strays(tmp_path: Path) -> Workspace:
    """A repo with a divergent off-main change: two commits sharing one change_id, both
    unbookmarked strays."""
    ws = _init_main(tmp_path)
    side_a = _child_offmain(ws, tmp_path, "a.txt", "AAA\n", "child A")
    _forge_divergent_side(ws, tmp_path, side_a.change_id, "BBB\n")
    return ws


def test_reconcile_adopts_both_divergent_sides(tmp_path: Path):
    _divergent_strays(tmp_path)
    # The divergent change-id breaks even a plain read, so the OLD change-id targeting dead-ended.
    pre = capture_state(Session.load(tmp_path, GitmanConfig(trunk="main")))
    assert pre.canonical is False

    res = do_reconcile(Session.load(tmp_path, GitmanConfig(trunk="main")), abandon_=False)
    state = capture_state(Session.load(tmp_path, GitmanConfig(trunk="main")))
    # H1 (I5) DETECTION: adopting keeps the two sides sharing one change_id, so the repo is still
    # honestly divergent — reconcile reports PARTIAL rather than falsely claiming success (the L9
    # self-report the H1 guide §5/§8 anticipates; the divergent-side auto-heal is deferred D3/D4).
    assert res.outcome == "PARTIAL"
    assert state.canonical is False
    assert "divergent" in (state.off_canonical or "")
    # Two distinct adopted lanes — one per divergent side. Keyed off commit_id, so the two sides
    # (which share a change_id) do NOT collide onto a single bookmark.
    adopted = sorted(lane.name for lane in state.lanes if lane.name.startswith("adopted-"))
    assert len(adopted) == 2, adopted
    assert len(set(adopted)) == 2, adopted


def test_reconcile_abandon_clears_both_divergent_sides(tmp_path: Path):
    _divergent_strays(tmp_path)

    res = do_reconcile(Session.load(tmp_path, GitmanConfig(trunk="main")), abandon_=True)
    assert res.outcome == "RECONCILED"
    state = capture_state(Session.load(tmp_path, GitmanConfig(trunk="main")))
    assert state.canonical, state.off_canonical
    assert not any(lane.name.startswith("adopted-") for lane in state.lanes)


# --- lane 5: garbage collection replaces adopt-time keep-ref pruning ------------------


def test_reconcile_collects_garbage_with_the_default_cutoff(tmp_path: Path, monkeypatch):
    """pyjutsu 0.17 removed `Workspace.init`'s adopt-time pruning of orphaned `refs/jj/keep/*` and
    replaced it with `ws.gc()`. An obsolete keep-ref makes one change_id resolve to two commits, and
    a divergent change_id dead-ends the transactions `reconcile` runs. So `reconcile` collects
    first — with pyjutsu's DEFAULT cutoff (two weeks, as `jj util gc`), never a forced expiry that
    could destroy objects a concurrent writer is mid-write on."""
    calls: list[tuple] = []
    real_gc = Workspace.gc

    def spy(self, *args, **kwargs):
        calls.append((args, kwargs))
        return real_gc(self, *args, **kwargs)

    monkeypatch.setattr(Workspace, "gc", spy)

    _divergent_strays(tmp_path)
    calls.clear()  # ignore the `do_init` call inside the fixture
    res = do_reconcile(Session.load(tmp_path, GitmanConfig(trunk="main")), abandon_=True)

    assert res.outcome == "RECONCILED"
    assert calls == [((), {})], calls  # called exactly once, no cutoff argument
    assert capture_state(Session.load(tmp_path, GitmanConfig(trunk="main"))).canonical


def test_reconcile_survives_a_failing_gc(tmp_path: Path, monkeypatch):
    """Garbage collection is best-effort: a repo that cannot collect must still reconcile. The
    failure is reported, never swallowed."""

    def boom(self, *a, **kw):
        raise RuntimeError("gc unavailable")

    _divergent_strays(tmp_path)
    monkeypatch.setattr(Workspace, "gc", boom)

    res = do_reconcile(Session.load(tmp_path, GitmanConfig(trunk="main")), abandon_=True)

    assert res.outcome == "RECONCILED"
    assert any("garbage collection skipped" in m for m in res.messages), res.messages
    assert capture_state(Session.load(tmp_path, GitmanConfig(trunk="main"))).canonical


def test_init_colocate_collects_garbage_when_adopting(tmp_path: Path, monkeypatch):
    """The adopt path is where the removed behaviour used to run, so `gitman init --colocate` calls
    `gc` there — and only there. Initializing an already-colocated repo collects nothing."""
    calls: list[tuple] = []
    monkeypatch.setattr(Workspace, "gc", lambda self, *a, **kw: calls.append((a, kw)))

    ws = Workspace.init(tmp_path, colocate=True)
    (tmp_path / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")

    do_init(Session.load(tmp_path, GitmanConfig()), trunk_opt=None, colocated_now=True)
    assert calls == [((), {})], calls

    calls.clear()
    (tmp_path / "gitman.toml").unlink()  # re-init the same repo, this time already colocated
    do_init(Session.load(tmp_path, GitmanConfig()), trunk_opt=None)
    assert calls == []


def test_reconcile_nondivergent_stray_unchanged(tmp_path: Path):
    """Happy path: a single, non-divergent stray still adopts into exactly one `adopted-*` lane
    (guards the commit-id naming change against altering the common case)."""
    ws = _init_main(tmp_path)
    _child_offmain(ws, tmp_path, "s.txt", "stray\n", "lone stray")

    res = do_reconcile(Session.load(tmp_path, GitmanConfig(trunk="main")), abandon_=False)
    assert res.outcome == "RECONCILED"
    state = capture_state(Session.load(tmp_path, GitmanConfig(trunk="main")))
    assert state.canonical, state.off_canonical
    assert len([lane for lane in state.lanes if lane.name.startswith("adopted-")]) == 1
