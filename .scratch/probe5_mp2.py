"""Probe 5 (MP2): version-bump snapshot flow + git annotated tag on a jj commit + reconcile."""
import subprocess
import tempfile
from pathlib import Path

from pyjutsu import Workspace

def banner(s): print(f"\n===== {s} =====")

tmp = Path(tempfile.mkdtemp(prefix="probe5-")); repo = tmp / "repo"; repo.mkdir()
ws = Workspace.init(repo, colocate=True)
(repo / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "1.2.3"\n')
with ws.transaction("initial") as tx:
    tx.describe("@", "initial"); tx.create_bookmark("main", "@")
# a lane
with ws.transaction("start rel") as tx:
    tx.new("main"); tx.create_bookmark("rel", "@")

banner("A. version-bump flow: new -> write file -> snapshot -> describe + set_bookmark (3 ops)")
op_before = ws.head_operation()
lane = "rel"
# 1) dedicated empty change on @
with ws.transaction("gitman:version", auto_snapshot=False) as tx:
    tx.new("@")
# 2) write the bumped version on disk (now @ is the new empty change)
txt = (repo / "pyproject.toml").read_text().replace('version = "1.2.3"', 'version = "1.3.0"')
(repo / "pyproject.toml").write_text(txt)
# 3) fold the file into @ via snapshot (own op)
ws.snapshot()
# 4) describe + advance the lane bookmark to the bump change
with ws.transaction("gitman:version", auto_snapshot=False) as tx:
    tx.describe("@", "Bump version to 1.3.0")
    tx.set_bookmark(lane, "@")

head = ws.resolve("rel")
print("  rel head desc:", repr(head.description), "empty:", head.is_empty)
print("  rel ahead of main:", len(ws.log("main..rel")), "changes")
print("  file on disk:", "1.3.0" in (repo / "pyproject.toml").read_text())
print("  diff_stat of bump change files:", [f.path for f in ws.diff_stat("rel").files])
# undo: restore op_before should revert the whole bump (file too)
ws.restore_operation(op_before)
print("  after undo: file back to 1.2.3:", "1.2.3" in (repo / "pyproject.toml").read_text())
print("  after undo: rel ahead:", len(ws.log("main..rel")), "changes")

banner("B. git annotated tag on a jj-authored commit_id (colocated)")
# land rel-ish: just tag main's commit. First advance main to a real change.
with ws.transaction("work") as tx:
    tx.new("main"); tx.describe("@", "real work")
(repo / "f.txt").write_text("hi\n")
ws.snapshot()
with ws.transaction("bm") as tx:
    tx.set_bookmark("main", "@")
commit = ws.resolve("main").commit_id
print("  main commit_id:", commit[:12])
r = subprocess.run(["git", "tag", "-a", "v9.9.9", "-m", "Release 9.9.9", commit],
                   cwd=repo, capture_output=True, text=True)
print("  git tag rc:", r.returncode, "stderr:", r.stderr.strip()[:120])
r2 = subprocess.run(["git", "rev-parse", "-q", "--verify", "refs/tags/v9.9.9"],
                    cwd=repo, capture_output=True, text=True)
print("  tag exists:", r2.returncode == 0, r2.stdout.strip()[:12])

banner("C. reconcile-style: adopt a stray via tx.create_bookmark (no precheck)")
# make a stray: non-empty unbookmarked change off main, @ elsewhere
with ws.transaction("stray") as tx:
    tx.new("main"); tx.describe("@", "stray work")
(repo / "s.txt").write_text("stray\n")
ws.snapshot()
with ws.transaction("move @") as tx:
    tx.edit("main")
stray_revset = "(main..) ~ ::(bookmarks() | remote_bookmarks()) ~ @"
strays = [c for c in ws.log(stray_revset) if not c.is_empty]
print("  strays found:", [(c.change_id[:8], c.description) for c in strays])
with ws.transaction("gitman:reconcile", auto_snapshot=False) as tx:
    for c in strays:
        tx.create_bookmark(f"adopted-{c.change_id[:8]}", c.change_id)
remaining = [c for c in ws.log(stray_revset) if not c.is_empty]
print("  strays after adopt:", len(remaining), "-> canonical:", len(remaining) == 0)

print("\nDONE", tmp)
