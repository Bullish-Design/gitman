import tempfile, subprocess
from pathlib import Path
from pyjutsu import Workspace
from pyjutsu import errors as E
def banner(s): print(f"\n===== {s} =====")

tmp = Path(tempfile.mkdtemp(prefix="probe3-")); repo = tmp/"repo"; repo.mkdir()
ws = Workspace.init(repo, colocate=True)
(repo/"f.txt").write_text("base\n")
with ws.transaction("base") as tx:
    tx.describe("@","base"); tx.create_bookmark("main","@")
with ws.transaction("new") as tx: tx.new("main")

banner("A. snapshot-first + auto_snapshot=False -> single mutation op, ws.undo() correct?")
(repo/"f.txt").write_text("edited work\n")           # dirty @ (unsaved user work)
ws.snapshot()                                         # fold dirty @ into its own op
op_before = ws.head_operation()
with ws.transaction("save", auto_snapshot=False) as tx:
    tx.describe("@", "my save message")
print("  ops:", [(o.id[:8], o.is_snapshot, o.description) for o in ws.operations(limit=3)])
print("  -> head op is the single mutation:", ws.operations(limit=1)[0].description)
ws.undo()                                             # plain head undo
print("  after ws.undo(): @ desc =", repr(ws.working_copy().description))
print("  f.txt still has user work:", (repo/'f.txt').read_text().strip(), "(snapshot preserved)")

banner("B. clean frozen-read: add a NEW file, read before/after snapshot")
with ws.transaction("fresh") as tx: tx.new("main")
(repo/"brand_new.txt").write_text("x\ny\n")
print("  diff files before snapshot:", [f.path for f in ws.diff_stat('@').files])
ws.snapshot()
print("  diff files after snapshot: ", [f.path for f in ws.diff_stat('@').files])

banner("C. rebase already-based (nothing to do): raise / noop / return?")
with ws.transaction("lane") as tx:
    tx.new("main"); tx.create_bookmark("lane","@")
(repo/"l.txt").write_text("lane\n")
with ws.transaction("save lane") as tx:
    tx.describe("lane","lane work"); tx.set_bookmark("lane","@")
# lane already on main; rebase onto main again
try:
    with ws.transaction("rebase noop") as tx:
        r = tx.rebase("lane", onto="main", mode="branch")
        print("  rebase already-based returned:", r.commit_id[:8])
    print("  -> no raise")
except BaseException as ex:
    print("  rebase already-based ->", type(ex).__name__, str(ex)[:80])

banner("D. does an intent that does nothing but commits empty tx hurt undo target?")
# (already know empty tx publishes op) -> just confirm restore_operation rolls it back cleanly
a = ws.head_operation()
with ws.transaction("noop intent") as tx: pass
ws.restore_operation(a)
print("  restored, head==a:", ws.head_operation()==a)

banner("E. operation descriptions: can we identify gitman ops from op-log to avoid state file?")
with ws.transaction("gitman:save") as tx:
    tx.describe("main", "tagged op")
for o in ws.operations(limit=2):
    print(f"   op {o.id[:8]} desc={o.description!r} tags={o.tags}")

print("\nDONE", tmp)
