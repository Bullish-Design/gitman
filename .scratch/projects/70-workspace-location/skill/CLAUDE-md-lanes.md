## Version control lanes

In repos that use gitman (or an equivalent lane-based VC skill), land and push
a lane by default once its verify step passes — do not stop to ask first. Run
the full loop: verify, save, land into trunk, push to origin.

The goal of every workspace is to land on `main`. Work is finished only when it
is on `main`, the main checkout shows it (`jj new main` there when its working
copy is empty), and `gitman done NAME` has removed the workspace. Before you
open a workspace, run `jj workspace list` and list any work in the workspaces
that `main` lacks; report it. Never end a session with work left in a workspace that the
user does not know about.

Still stop and ask before landing or pushing when something is unusual: verify
fails or is skipped, the lane touches shared or risky files (secrets, CI
config, release branches), a merge conflict appears, or the user gave
instructions that suggest they want to review the change first.
