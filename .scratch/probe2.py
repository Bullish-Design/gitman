"""Probe part 2: immutability config, empty tx, noop rebase, frozen reads, push-delete."""
import tempfile, subprocess
from pathlib import Path
from pyjutsu import Workspace
from pyjutsu import errors as E

def banner(s): print(f"\n===== {s} =====")

tmp = Path(tempfile.mkdtemp(prefix="probe2-"))
repo = tmp / "repo"; repo.mkdir()
ws = Workspace.init(repo, colocate=True)
(repo / "f.txt").write_text("base\n")
with ws.transaction("base") as tx:
    tx.describe("@", "base"); tx.create_bookmark("main", "@")
with ws.transaction("new") as tx:
    tx.new("main")

banner("3a. immutability: is main/trunk immutable by default in pyjutsu?")
# jj's default config: immutable_heads() = trunk() | tags(). Does pyjutsu load that?
try:
    with ws.transaction("describe main") as tx:
        tx.describe("main", "rewrite trunk tip")
    print("  describe(main) -> OK: main is NOT immutable in pyjutsu (no jj default config loaded?)")
except BaseException as ex:
    print("  describe(main) ->", type(ex).__name__, str(ex)[:80])

banner("3b. abandon root -> clean ImmutableCommitError or panic?")
try:
    with ws.transaction("abandon root") as tx:
        tx.abandon("root()")
except BaseException as ex:
    print("  abandon(root()) ->", type(ex).__name__, str(ex)[:80])

banner("4. empty transaction: does committing a no-op publish an op?")
a = ws.head_operation()
try:
    with ws.transaction("empty") as tx:
        pass
    b = ws.head_operation()
    print("  head moved on empty tx:", a != b)
except BaseException as ex:
    print("  empty tx ->", type(ex).__name__, str(ex)[:80])

banner("5. describe to SAME message: op published? (noop detection)")
cur = ws.resolve("main").description
a = ws.head_operation()
with ws.transaction("redescribe same") as tx:
    tx.describe("main", cur.rstrip("\n"))
b = ws.head_operation()
print("  head moved on same-desc describe:", a != b)

banner("6. reads frozen: ws.log sees on-disk edit only after snapshot?")
with ws.transaction("edit @") as tx:
    tx.edit("main")
(repo / "f.txt").write_text("UNSNAP\n")
print("  diff_stat before snapshot:", ws.diff_stat("@").total_insertions, "ins")
ws.snapshot()
print("  diff_stat after snapshot: ", ws.diff_stat("@").total_insertions, "ins")

banner("7. git_push delete semantics (no remote -> error type)")
try:
    ws.git_push("origin", "main", delete=True)
except BaseException as ex:
    print("  push delete no-remote ->", type(ex).__name__, str(ex)[:80])

banner("8. restore_operation returns? & undo() of a snapshot+mutation")
a = ws.head_operation()
(repo / "f.txt").write_text("change-for-undo\n")
with ws.transaction("desc2") as tx:
    tx.describe("@", "second")
print("  ops between:", [ (o.id[:8], o.is_snapshot) for o in ws.operations(limit=3)])
r = ws.undo()  # undo head op only
print("  after ws.undo(): @ desc =", repr(ws.working_copy().description), "f.txt=", (repo/'f.txt').read_text().strip())
print("  (note whether undo of just-head leaves the snapshot's file change)")

banner("9. workspace add: new @ base + stale detection across workspaces")
wpath = tmp / "ws-lane"
info = ws.add_workspace(wpath, name="lane")
print("  added workspace:", info.name, "wc_commit", info.wc_commit_id[:8])
ws_lane = Workspace.load(wpath)
print("  lane is_stale right after add:", ws_lane.is_stale())
# mutate from default ws in a way that moves the lane's @? operations move repo head
with ws.transaction("unrelated") as tx:
    tx.new("main")
print("  lane is_stale after default-ws op:", ws_lane.is_stale())

print("\nDONE", tmp)
