# 60 — Switch hook request (external, from devman project 041)

**Status:** proposed — not yet agreed.
**Source:** devman project 041, open question O4. Filed by the consumer, not by a gitman
maintainer.
**Scope:** add a `pre_switch` hook to `gitman switch`, reusing the existing land-hook
mechanism as-is. No new event model. No path set.
**Line numbers below are current as of `main @ e6994c6` (2026-10-02).** This repository
advanced by several commits while this document was being written, including one
directly relevant to §"Addendum" below; every citation was re-checked against that
commit before filing.

## Addendum (2026-10-02): the land-hook snapshot itself blocks devenv-style verify steps

**Lead finding, independent of the `switch` ask above, filed here because it is the same
mechanism and because it changes whether the mechanism is usable at all today.** This is
not a bug report — the strict snapshot is a defensible design: a hook that edits the tree
mid-land genuinely is dangerous, and refusing that is correct. **The problem is that the
rule as implemented cannot distinguish "the hook edited my source" from "a build tool
touched its own cache,"** and in a devenv-based fleet the second is unavoidable the moment
a `[land.pre_hook]` runs the repository's own verify step.

**The failure is intermittent, which is the worst shape it could take.** Re-verified
today in a throwaway `mktemp -d` repository under `/tmp` (colocated, no remote, deleted
after the test): a `[land.pre_hook]` that **exits 0** and writes one file under
`.devenv/` (simulating a cache side effect of running the repo's own verify command)
produced, on the **first** `gitman land`:
```
Gitman land — BLOCKED
pre-land hook changed paths outside allowed_paths: .devenv/nix-eval-cache.db-wal; describe or repair the changes, then retry.
```
exit code 1, trunk unchanged. Running the identical `gitman land` a **second** time —
nothing else changed — produced `Gitman land — LANDED`, exit code 0, trunk advanced.
The gate compares the filesystem before and after *this hook run*, not tree cleanliness
against history, so a hook with a one-time cache side effect blocks the first land and
silently passes the second, once the cache file already exists and the run only rewrites
it identically. A deterministic refusal is a bug someone fixes. An intermittent one is a
mechanism people quietly stop trusting.

Three things make this worse than a plain incompatibility:

1. `filesystem_snapshot` (`src/gitman/hooks.py:117-133`) excludes only `_IGNORED_DIRS`
   (`src/gitman/hooks.py:26`): `.git`, `.jj`, `.gitman`, `.worktrees`. It does **not**
   exclude `.devenv/` or `.direnv/`, and it does not consult `.gitignore`. A hook that
   runs the repository's own verify step through devenv — the most obvious thing to put
   in `[land.pre_hook]` — blocks the land every time devenv's own caches change.
2. **`allowed_paths` does not rescue it.** Re-verified in the same throwaway repo: with
   `allowed_paths = [".devenv/nix-eval-cache.db-wal"]` set and the hook writing *different*
   content each run (so a real change is detected), `gitman land` still printed
   `Gitman land — BLOCKED` — only the message changed, to
   `pre-land hook changed allowed paths: .devenv/nix-eval-cache.db-wal; describe the
   changes, then retry land.` Reading `describe_changes` confirms why
   (`src/gitman/hooks.py:159-175`): it returns a non-`None` string whenever any path
   changed, whether or not that path matched `allowed_paths` — `allowed` only picks which
   sentence comes back. The caller blocks on any non-`None` return, at both call sites
   (`src/gitman/core.py:1646` for `post_land`, `:1874` for `pre_land`):
   `if not hook_result.succeeded or changes:`. `allowed_paths` changes the message, not
   the outcome. A maintainer reading the config schema will assume it is the escape
   hatch. It is not one today.
3. **This is not hypothetical for gitman's own repository.** This document's line
   numbers shifted during drafting because `main` advanced past the commit
   `d6a2966 config: gate land on the test suite (project 54 finding B)` (2026-10-02),
   which added gitman's **own** `[land.pre_hook]`:
   ```toml
   [land.pre_hook]
   command = ["pytest", "-q"]
   timeout_seconds = 600.0
   allowed_paths = [".pytest_cache/*", "*__pycache__/*", ".coverage*"]
   ```
   (`gitman/gitman.toml`, current). That commit followed a direct recommendation in
   `.scratch/projects/54-phase-a-release-bus-findings/issue.md` finding B to use
   `[land].pre_hook` as "a future gated land path." The `allowed_paths` entry suggests the
   author expected those three patterns to be the escape hatch — per point 2 above, they
   are not; any change under `.pytest_cache/`, `__pycache__/`, or a `.coverage*` file
   still blocks the land, it only gets the "allowed paths" message. **Gitman's own
   dogfood config, landed today, is already exposed to the exact bug this addendum
   reports.**

A fleet-wide check corrects an earlier number attributed to this project: a scan of every
`gitman.toml` under `~/Documents/Projects` (79 files found; 4 under `.archive/` and 1
template at `gitman/examples/gitman.toml` with the hook commented out, 74 live
candidates) found **exactly one** repository with an active `[land.pre_hook]` or
`[land.post_hook]` command — gitman's own, added hours ago by the commit above. Not
"0 of 74" — **1 of 74**, and that one example is itself mid-exposure to the bug. Offered
as a hypothesis, not a conclusion, since this is one repository's history, not a survey of
why the other 73 have none: in a fleet where most repositories verify through devenv, the
obvious hook — "run my own verify step before landing" — may be the thing that trips this,
which would explain why so few have adopted `[land.pre_hook]` even though it has existed
since project 37.

**Remedies, for the maintainer to choose between — none picked here as settled:**
- exclude `.devenv/` and `.direnv/` from `filesystem_snapshot` alongside the existing four;
- or skip gitignored paths when a snapshot is taken;
- or make `allowed_paths` actually permissive (a change inside it passes) and document it
  as the escape hatch it already looks like;
- or add a per-hook `allow_writes` opt-out.

**Scoping note, so this does not read as sinking the `switch` request above:** the
`[switch.pre_hook]` example in this document (`devman central-verify --phase post`) writes
nothing and does not enter a devenv shell, so it is unaffected by this addendum and the
case for it stands independent of this finding. It is specifically the "hook runs devenv"
shape that breaks — which, per the fleet scan above, appears to be the shape most repositories
would reach for first.

## Problem: three silent incidents, one shared cause

On 2026-10-01, three gitman operations against `~/.config/devman` each did real damage.
`gitman status` and `git status` reported no problem in any of the three.

| Operation | Damage | What caught it |
|---|---|---|
| `gitman split` | deleted two live bootstrap targets, `projects/{linkman,mnemonix}/devenv.local.nix` | a downstream project's gate failed with `bootstrap central target does not exist` |
| `gitman land` | 78 generated files left the working copy until a `gitman sync` | counting them by hand |
| `gitman switch` | reverted a completed change — `projects/.archive/` vanished and two retired projects reappeared | a count in an agent's prompt, which the agent correctly refused to proceed past |

**The shared cause is correct, documented jj behaviour, not a gitman defect.** In a
colocated jj repository the working copy is a commit. Moving `@` between lanes rewrites
the tree, and content held only in an unlanded lane leaves disk when the rewrite lands
somewhere that doesn't carry it. gitman is not doing anything wrong. It becomes a hazard
only when the repository's working tree is also live machine state — which
`~/.config/devman` is: its files are symlink targets for 325 live symlinks across 66
repositories.

Measured 2026-10-01: 12 of those 325 live views currently point at content reachable
only from an unlanded lane, across four repositories — including three
`devenv.local.nix` bootstrap links. Nix reads `devenv.local.nix` before any shell hook
runs, so a dangling one fails shell entry with a trace nothing can intercept. Three
repositories are one `gitman switch` away from being unable to open a shell.

## A second, independent precedent

`devman/.scratch/projects/035-config-repo-cleanup/README.md` §2.3 recorded, three weeks
earlier, the same class of blind spot in a different check: `gitman doctor` reported
`ok colocated-head  git HEAD reachable from a bookmark` against a HEAD that was two
commits *ahead* of the only bookmark and on no branch, and
`ok colocated-refs  jj bookmarks ↔ git refs in sync` while git held two commits jj could
not resolve at all. `gitman status` likewise reported `CANONICAL`. That report
recommended a check comparing `git rev-parse HEAD` against the jj commit set, and it was
never built. Same tool, same shape of gap — a sanctioned health check reporting `ok` on a
genuinely bad state — twice, three weeks apart, in two different checks. This is a
pattern, not an accusation.

## The ask, kept small

Extend the **existing** land-hook mechanism to `switch` (and, ideally, `split` and
`abandon`, by the same pattern):

- Reuse `LandHookConfig` (`src/gitman/config.py:44-49`) and `LandHookEvent`
  (`src/gitman/models.py:84-101`) as they stand.
- Add `"pre_switch"` to the event `Literal` at `src/gitman/models.py:88`, and a
  `[switch.pre_hook]` config table beside `[land.pre_hook]` / `[land.post_hook]`
  (`src/gitman/config.py:52-56`).
- Run the hook before the working-copy rewrite. A non-zero exit blocks the switch,
  exactly as `_land_hook_blocked` (`src/gitman/core.py:1602`) already blocks `land`.
- **No new event model. No path set.**

That last point is the one this request leans on, and it is worth stating plainly: **an
earlier draft asked gitman to compute and pass the set of paths the rewrite would
remove. That is unnecessary**, and dropping it is what turns this from a feature into a
call site.

The consumer's predicate is: *is any live symlink target currently reachable only from a
lane?* It answers that from the filesystem, without gitman's help — it already has to,
because the same question applies to `split` and `abandon`, and because the answer
doesn't depend on which paths a specific rewrite touches. If the answer is no, every
switch is safe. If yes, refuse regardless of direction. gitman does not need to compute
or hand over a path set for this to work. The hook only needs to run before the rewrite
and be able to block it — which is exactly what `[land.pre_hook]` already does for
`land`.

## Why a third guard point here is idiomatic, not foreign

`do_switch` (`src/gitman/core.py:819`) already carries two guards of exactly this
character — "refuse before you strand something" — a few lines apart in the same
function:

1. Refuses to orphan an unnamed change that has on-disk work (`core.py:863-872`):
   ```python
   if cur is None:
       ...
       if not wc.is_empty:
           raise GitmanError(
               "uncommitted work on an unnamed change would be stranded — "
               "`gitman describe -m …` (if it's a lane), `gitman start <name>` (to name it), "
               "or `gitman abandon` first.",
               exit_code=1,
           )
   ```
2. Refuses a second checkout of a lane that already has its own `--workspace`
   (`core.py:877-881`):
   ```python
   other_workspaces = {w.name for w in session.ws.workspaces()} - {session.ws.name}
   if name in other_workspaces:
       raise GitmanError(
           f"lane '{name}' is checked out in another workspace — `cd` to its workspace dir to resume it.",
           exit_code=1,
       )
   ```

Both guards exist to stop `switch` from stranding or corrupting something *before* the
rewrite runs. A `pre_switch` hook is a third instance of the same stance, not a new
category of behaviour for this verb — just delegated to an external predicate instead of
a built-in one.

## Claims verified for this request

1. **`do_switch` carries two pre-rewrite guards already** — confirmed above, quoted from
   `src/gitman/core.py:863-872` and `src/gitman/core.py:877-881`.

2. **`run_verify` has exactly two call sites, and `do_land` is not one of them:**
   ```
   src/gitman/release.py:64:    ok, out = run_verify(verify_cmds, repo_root, config.publish.verify_timeout)
   src/gitman/core.py:182:def run_verify(...                                    # the definition
   src/gitman/core.py:1508:                ok, out = run_verify(                 # do_publish
   ```
   `core.py:1508` is inside `do_publish`; `release.py:64` is `do_release`. Neither is
   `do_land`, and `do_switch` calls neither. `[publish].verify` is not an alternative
   route to this request's goal — it never runs on `switch`, `split`, or `abandon`, and a
   consumer who only wires `publish` gets no protection on navigation at all.

3. **The land hook works with no git remote.** Re-measured today (2026-10-01) in a
   throwaway `mktemp -d` repository under `/tmp`, colocated, no remote configured,
   deleted after the test:
   - `[land.pre_hook]` set to `["/bin/sh", "-c", "exit 1"]`: `gitman land` printed
     `Gitman land — BLOCKED` / `pre_land hook failed with exit 1: ...`, exit code **1**,
     and trunk's git branch stayed at the pre-land commit.
   - `[land.post_hook]` set the same way: `gitman land` printed `Gitman land — LANDED`,
     `note: post-land hook failed: post_land hook failed with exit 1: ...`, `note: land
     succeeded; no rollback was attempted.`, exit code **1**, and the jj-authoritative
     trunk bookmark advanced (`gitman status` reported the new commit as `main`).
     One honest caveat from the re-measurement, not a correction of the claim: the
     colocated *git* branch ref lagged jj's bookmark until `gitman status` flagged it
     (`note: 1 git ref(s) lag jj: main — gitman repair brings them forward`) — this is
     gitman self-reporting a known export-timing gap, not a silent wrong answer, and it
     is orthogonal to whether the hook ran and blocked correctly. Both phases ran and
     reported exactly as the original claim stated. No remote was configured at any
     point.

4. **`switch`, `split`, and `abandon` have no hook of any kind today.**
   ```
   grep -rn "run_hook\|pre_land\|post_land\|LandHookConfig\|LandHookEvent\|pre_hook\|post_hook" src/gitman/*.py
   ```
   returns matches only in `hooks.py` itself, `config.py:44/55/56`, `models.py:84/88`,
   and `core.py` lines 1573-1948 — all inside `_land_hook_event`, `_land_hook_blocked`,
   and `do_land`. `do_switch` (`core.py:819-881`), `do_split` (`core.py:1098`), and
   `do_abandon` (`core.py:2018`) contain no reference to any of these names. Confirmed.

All four claims hold as stated; none needed correction.

## Does gitman already discuss or reject this?

No. `docs/GITMAN_CONCEPT.md` and `.scratch/projects/37-land-lifecycle-hooks/{ISSUE,PLAN}.md`
are the authority on the existing hook surface. Project 37's non-goals list is explicit
about what it excluded — "filesystem watching, automatic generated-file inclusion,
repair mode, durable event delivery, a general event language, Python callbacks,
branch/tag hooks, or forge and pull-request hooks" — and does not mention navigation
verbs (`switch`, `split`, `abandon`) at all, in either direction. There is no recorded
rejection of hooking a rewrite verb. This request is open ground, not a re-litigation.

## Worked example of the consumer side

```toml
[switch.pre_hook]
command = ["/run/current-system/sw/bin/devman", "central-verify", "--phase", "post"]
timeout_seconds = 120
```

The command is an absolute, system-profile path on purpose. `run_hook`
(`src/gitman/hooks.py:65-66`) returns `"hook command not found: ..."` with exit 2 on
`FileNotFoundError`, which blocks the operation. A bare command name would make the
repository unusable the moment the toolchain is off `PATH` — a plausible state in a
repository whose job is to configure the toolchain in the first place.

## What this costs gitman

A config table, one literal added to an enum, three call sites (wiring the hook into
`do_switch`, and ideally `do_split` / `do_abandon` the same way), and tests. Beyond this
one consumer, the general benefit is that any gitman repository gains the ability to
refuse a destructive navigation — not just a destructive land.

## What this costs the consumer if gitman declines

There is no interception point on devman's side. By the time devman reads the
filesystem, the rewrite has already happened — both the `split` and `switch` incidents
above were caught *after the fact*, by a failed downstream gate and by a human noticing a
count. The fallback is a discipline (keep lane-only content at zero) plus a nightly
detector, which is strictly weaker: it catches damage, it does not prevent it.

## Priority: low, stated honestly

Of the 325 live symlink views, 313 point at content already on trunk, and no lane
operation can remove those — a `switch` cannot remove a path trunk holds, because every
lane descends from trunk. The hazard is not a property of the repository; it is a
property of *unlanded new content* in it, and its size is exactly the count of
lane-only views (12, today). The consumer's primary mechanism is keeping that count at
zero — landing promptly, not leaving bootstrap files parked on a lane. **This hook is
insurance for the window while new content sits on a lane. It is not the fix.** A request
that oversells its own urgency gets discounted; this one is filed at the priority it
actually has.
