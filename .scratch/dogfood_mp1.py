"""MP1 dogfood: drive the full lane lifecycle through the migrated do_* over a Session."""
import tempfile
from pathlib import Path

from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.core import do_abandon, do_land, do_save, do_start, do_sync, do_undo
from gitman.session import Session
from gitman.state import capture_state

CFG = GitmanConfig(trunk="main")


def build(d: Path) -> None:
    ws = Workspace.init(d, colocate=True)
    (d / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")


def sess(d: Path) -> Session:
    return Session.load(d, CFG)


def check(label, cond):
    print(f"  {'OK ' if cond else 'XX '} {label}")
    assert cond, label


tmp = Path(tempfile.mkdtemp(prefix="dogfood-")); repo = tmp / "repo"; repo.mkdir()
build(repo)

print("== start feat ==")
r = do_start(sess(repo), "feat", workspace=False)
check("STARTED", r.outcome == "STARTED")
check("undo line", r.undo_command == "gitman undo")
st = capture_state(sess(repo))
check("lane feat present", [l.name for l in st.lanes] == ["feat"])
check("current_lane feat", st.current_lane == "feat")
check("canonical", st.canonical)

print("== save -m ==")
(repo / "f.txt").write_text("base\nfeat\n")
r = do_save(sess(repo), "add feat line")
check("SAVED", r.outcome == "SAVED")
check("described msg", r.messages == ['described: "add feat line"'])
st = capture_state(sess(repo))
check("lane has 1 change non-empty", st.lanes[0].change_count == 1 and not st.lanes[0].head.empty)

print("== save (no -m) NOOP echo ==")
r = do_save(sess(repo), None)
check("NOOP", r.outcome == "NOOP")
print("    echo:", r.messages[0])

print("== undo the save ==")
r = do_undo(sess(repo), op=None, list_=False)
check("UNDONE", r.outcome == "UNDONE")
st = capture_state(sess(repo))
check("after undo: change empty again (save reverted)", st.lanes[0].head.description == "")

print("== re-save (distinct content) then land ==")
(repo / "f.txt").write_text("base\nfeat2\n")
do_save(sess(repo), "add feat line v2")
trunk_before = capture_state(sess(repo)).trunk.commit_id
r = do_land(sess(repo), ["feat"])
check("LANDED", r.outcome == "LANDED")
st = capture_state(sess(repo))
check("lane retired", st.lanes == [])
check("trunk advanced", st.trunk.commit_id != trunk_before)
check("canonical after land", st.canonical)

print("== undo the land (trunk back) ==")
r = do_undo(sess(repo), op=None, list_=False)
check("UNDONE", r.outcome == "UNDONE")
st = capture_state(sess(repo))
check("trunk restored", st.trunk.commit_id == trunk_before)
check("lane feat back", [l.name for l in st.lanes] == ["feat"])

print("== abandon feat ==")
r = do_abandon(sess(repo), "feat")
check("ABANDONED", r.outcome == "ABANDONED")
st = capture_state(sess(repo))
check("no lanes", st.lanes == [])
check("canonical after abandon", st.canonical)

print("== sync (no remote) ==")
do_start(sess(repo), "lane2", workspace=False)
(repo / "g.txt").write_text("g\n")
do_save(sess(repo), "g work")
r = do_sync(sess(repo), all_=False)
check("SYNCED", r.outcome == "SYNCED")
check("sync exit 0", r.exit_code == 0)
check("canonical after sync", capture_state(sess(repo)).canonical)

print("== undo --list shows gitman:* ==")
r = do_undo(sess(repo), op=None, list_=True)
check("LIST", r.outcome == "LIST")
print("    rows:")
for row in r.messages:
    print("     ", row)
check("all rows gitman:", all("gitman:" in m for m in r.messages))

print("\nALL DOGFOOD CHECKS PASSED", tmp)
