"""One-off: re-park a stranded bare @ onto trunk head (main).

Documented recovery for the known post-adopt artifact where `@` is left on the
old trunk (adopt --force skips the update_stale/re-park a normal adopt does).
Moves only the empty working-copy commit onto `main`; touches neither trunk nor
any lane bookmark. See .scratch/projects/13-*/ISSUE.md.
"""

from pyjutsu import Workspace

ws = Workspace.load(".")

with ws.transaction("gitman:repark-wc-on-trunk", auto_snapshot=False) as tx:
    tx.new(["main"])  # fresh empty child of trunk becomes the new @

# materialize the new @ into the working copy + sync colocated git refs/HEAD
if ws.is_stale():
    ws.update_stale()
ws.git_export()
print("re-parked @ onto main; git_export done.")
