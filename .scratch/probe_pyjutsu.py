"""Probe the pyjutsu behaviors the migration plan depends on. Ground truth > prose."""
import tempfile, os, subprocess
from pathlib import Path
from pyjutsu import Workspace
from pyjutsu import errors as E

def sh(cwd, *args):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)

def banner(s): print(f"\n===== {s} =====")

tmp = Path(tempfile.mkdtemp(prefix="probe-"))
repo = tmp / "repo"
repo.mkdir()
ws = Workspace.init(repo, colocate=True)

# make an initial trunk commit
(repo / "f.txt").write_text("base\n")
with ws.transaction("init trunk") as tx:
    tx.describe("@", "base")
    tx.create_bookmark("main", "@")
with ws.transaction("new on top") as tx:
    tx.new("main")

banner("1. auto_snapshot: is the snapshot a SEPARATE preceding op?")
# dirty @ then open a transaction with auto_snapshot
(repo / "dirty.txt").write_text("dirty\n")
before = ws.head_operation()
print("head before:", before[:12])
with ws.transaction("describe with dirty @") as tx:
    tx.describe("@", "msg1")
ops = ws.operations(limit=5)
print("ops after (newest first):")
for o in ops:
    print(f"  {o.id[:12]} snap={o.is_snapshot} desc={o.description!r}")
print("=> restore to `before` and see if dirty.txt edit + describe both revert")
ws.restore_operation(before)
print("   dirty.txt exists after restore:", (repo / "dirty.txt").exists())
print("   @ description after restore:", repr(ws.working_copy().description))

banner("2. rebase that CONFLICTS: raise, or first-class conflict commit?")
# build two divergent lanes editing same file
ws2 = ws  # reuse
# reset: create lane editing f.txt, trunk also edits f.txt
with ws.transaction("trunk edit") as tx:
    tx.edit("main")
(repo / "f.txt").write_text("trunk-change\n")
with ws.transaction("snapshot+describe trunk") as tx:
    tx.describe("main", "trunk edits f")
    tx.set_bookmark("main", "@")
# new lane off the *old* main parent
main_commit = ws.resolve("main")
with ws.transaction("start lane") as tx:
    tx.new([main_commit.parent_ids[0]])
    tx.create_bookmark("lane", "@")
(repo / "f.txt").write_text("lane-change\n")
with ws.transaction("snapshot lane") as tx:
    tx.describe("lane", "lane edits f")
    tx.set_bookmark("lane", "@")
print("attempting rebase of lane (branch mode) onto main...")
try:
    with ws.transaction("rebase lane onto main") as tx:
        r = tx.rebase("lane", onto="main", mode="branch")
        print("  rebase returned commit:", r.commit_id[:12], "has_conflict=", r.has_conflict)
    print("  -> NO exception raised; checking lane conflict state")
    lane_head = ws.resolve("lane")
    print("  lane has_conflict:", lane_head.has_conflict)
    print("  conflicts():", ws.conflicts("lane"))
except E.PyjutsuError as ex:
    print("  RAISED:", type(ex).__name__, ex)

banner("3. immutability: does rebasing/abandoning trunk-immutable raise?")
# jj default immutable_heads is trunk()|tags; here no remote/trunk() config. Test root + main.
try:
    with ws.transaction("try rewrite root") as tx:
        tx.describe("root()", "x")
except E.PyjutsuError as ex:
    print("  rewrite root ->", type(ex).__name__)
# does describing main (a bookmark, not configured immutable) raise? probably not
try:
    with ws.transaction("describe main") as tx:
        tx.describe("main", "still trunk edits f")
    print("  describe main -> OK (no immutability by default for bookmarks)")
except E.PyjutsuError as ex:
    print("  describe main ->", type(ex).__name__, ex)

banner("4. empty transaction: does committing a no-op publish an op?")
op_a = ws.head_operation()
with ws.transaction("empty tx") as tx:
    pass
op_b = ws.head_operation()
print("  head moved on empty tx:", op_a != op_b, "(a", op_a[:8], "b", op_b[:8], ")")

banner("5. rebase that is already-based (nothing to do): raise or noop?")
try:
    with ws.transaction("rebase noop") as tx:
        tx.rebase("lane", onto="main", mode="branch")
    print("  second rebase -> OK no raise")
except E.PyjutsuError as ex:
    print("  second rebase ->", type(ex).__name__, ex)

banner("6. reads frozen: does ws.log see on-disk edit without snapshot?")
(repo / "f.txt").write_text("UNSNAPSHOTTED EDIT\n")
wc = ws.working_copy()
print("  working_copy desc (no snapshot):", repr(wc.description))
ds = ws.diff_stat("@")
print("  diff_stat totals before snapshot: +", ds.total_insertions, "-", ds.total_deletions)
ws.snapshot()
ds2 = ws.diff_stat("@")
print("  diff_stat totals after snapshot:  +", ds2.total_insertions, "-", ds2.total_deletions)

banner("7. bookmarks(): remote field shape for local vs git-backing")
for b in ws.bookmarks():
    print(f"  name={b.name} remote={b.remote!r} tracked={b.tracked}")

print("\nDONE. tmp:", tmp)
