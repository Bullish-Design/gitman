"""Probe 4: confirm LAND, ABANDON, and start --workspace recipes for MP1."""
import tempfile, shutil
from pathlib import Path
from pyjutsu import Workspace
from pyjutsu import errors as E

def banner(s): print(f"\n===== {s} =====")

tmp = Path(tempfile.mkdtemp(prefix="probe4-")); repo = tmp / "repo"; repo.mkdir()
ws = Workspace.init(repo, colocate=True)
(repo / "f.txt").write_text("base\n")
with ws.transaction("base") as tx:
    tx.describe("@", "base"); tx.create_bookmark("main", "@")

def stray_revset(trunk): return f"({trunk}..) ~ ::(bookmarks() | remote_bookmarks()) ~ @"

banner("LAND: rebase(branch)->set_bookmark(trunk,lane)->delete_bookmark(lane) in 1 tx")
# build a lane with one non-empty change
with ws.transaction("start feat") as tx:
    tx.new("main"); tx.create_bookmark("feat", "@")
(repo / "feat.txt").write_text("feat\n")
ws.snapshot()
with ws.transaction("save feat") as tx:
    tx.describe("feat", "feat work")
trunk_before = ws.resolve("main").commit_id
op_before = ws.head_operation()
# move @ off the lane so it's like landing another lane (also test @ on lane below)
with ws.transaction("gitman:land", auto_snapshot=False) as tx:
    rebased = tx.rebase("feat", onto="main", mode="branch")
    print("  rebased has_conflict:", rebased.has_conflict)
    tx.set_bookmark("main", "feat")
    tx.delete_bookmark("feat")
print("  trunk advanced:", ws.resolve("main").commit_id != trunk_before)
print("  feat gone:", "feat" not in [b.name for b in ws.bookmarks() if b.remote is None])
print("  strays after land:", [c.change_id[:8] for c in ws.log(stray_revset("main"))])
print("  @ desc after land:", repr(ws.working_copy().description), "empty:", ws.working_copy().is_empty)
ws.restore_operation(op_before)
print("  restored: feat back:", "feat" in [b.name for b in ws.bookmarks() if b.remote is None])

banner("ABANDON: abandon each trunk..lane change_id then delete_bookmark, 1 tx")
# rebuild lane state already there after restore
change_ids = [c.change_id for c in ws.log("main..feat")]
print("  trunk..feat change_ids:", [c[:8] for c in change_ids])
op_before2 = ws.head_operation()
with ws.transaction("gitman:abandon", auto_snapshot=False) as tx:
    for cid in change_ids:
        tx.abandon(cid)
    tx.delete_bookmark("feat")
print("  feat gone:", "feat" not in [b.name for b in ws.bookmarks() if b.remote is None])
print("  strays after abandon:", [c.change_id[:8] for c in ws.log(stray_revset("main"))])
print("  canonical-ish (no strays):", len(ws.log(stray_revset("main"))) == 0)

banner("ABANDON with @ ON the lane")
ws.restore_operation(op_before2)
with ws.transaction("edit onto feat") as tx:
    tx.edit("feat")
print("  @ on feat now, @ bookmarks:", ws.working_copy().bookmarks)
cids = [c.change_id for c in ws.log("main..feat")]
with ws.transaction("gitman:abandon2", auto_snapshot=False) as tx:
    for cid in cids:
        tx.abandon(cid)
    tx.delete_bookmark("feat")
print("  after abandon @-on-lane: @ empty:", ws.working_copy().is_empty,
      "strays:", len(ws.log(stray_revset("main"))))

banner("START --workspace: add_workspace + sub tx on shared op-log")
op_before3 = ws.head_operation()
wpath = tmp / "ws-lane"
info = ws.add_workspace(wpath, name="lane")
print("  added ws:", info.name, "@ commit", info.wc_commit_id[:8])
print("  head moved by add_workspace:", ws.head_operation() != op_before3)
sub = Workspace.load(wpath)
print("  sub @ before tx, parents=root?:", sub.working_copy().parent_ids)
with sub.transaction("gitman:start", auto_snapshot=False) as tx:
    tx.new("main")
    tx.create_bookmark("lane", "@")
print("  default ws sees 'lane' bookmark:", "lane" in [b.name for b in ws.bookmarks() if b.remote is None])
print("  lane head desc/empty:", ws.resolve("lane").is_empty)
print("  strays from default ws:", [c.change_id[:8] for c in ws.log(stray_revset("main"))])
print("  default ws @ is_stale:", ws.is_stale())
# now test guard rollback: restore op_before3 should unwind both the add_workspace AND sub tx
ws.restore_operation(op_before3)
print("  after restore: lane bookmark present:", "lane" in [b.name for b in ws.bookmarks() if b.remote is None])
print("  after restore: workspaces:", [w.name for w in ws.workspaces()])
# cleanup half-made workspace dir
if wpath.exists(): shutil.rmtree(wpath, ignore_errors=True)

print("\nDONE", tmp)
