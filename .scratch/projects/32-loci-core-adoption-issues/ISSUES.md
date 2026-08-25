# 32 — Issues found while driving gitman through a real release in loci-core

**Date:** 2026-08-13
**gitman version:** 0.4.2
**Consumer repo:** `../loci-core` (jj-colocated, devenv-managed, Python 3.13)
**Session:** landed four lanes, cut two releases (`v0.4.0`, `v0.4.1`), ran
`split` / `switch` / `sync` / `publish` / `land` / `push` / `reconcile` /
`version bump` / `release`.

**Verdict:** the lane model worked. Every VC operation did what the skill said
it would, `split` handled a genuinely entangled draft correctly, and `land`
refused an off-canonical repo rather than corrupting it. The issues below are
about **adoption, contract accuracy, and release mechanics** — not the core
model.

---

## G1 — `--json` is documented but implemented nowhere

**Severity:** Serious

**Symptom.** The skill promises machine-readable output:

> `.agents/skills/gitman/SKILL.md` — "Pass `--json` for structured output."

No subcommand accepts it.

```
$ gitman status --json
No such option: --json
```

Checked `status`, `save`, `land` — zero mentions of `json` in any `--help`.

**Cause.** The exit-code section of the shipped skill documents a flag the CLI
never grew.

**Consequence.** An agent driving gitman has to scrape human-formatted output
with box-drawing characters. In this session I parsed `status` with `grep` and
`tail`, which is exactly what the my-ai law's "structured plain-text reports"
rule exists to prevent. It also violates law §3 directly: rich coloring is
emitted unconditionally, with no `--json` escape.

**Fix.** Either implement `--json` on the read commands (`status`, `version`,
`managers`-equivalent) or delete the sentence from the skill. Implementing it is
the better half — `status` in particular is what every automation reads first.

---

## G2 — `version bump` leaves `uv.lock` stale, and `release` tags the drift

**Severity:** Serious

**Symptom.** After a bump, the manifest and the lockfile disagree:

```
$ gitman version bump patch      # 0.4.0 → 0.4.1
$ git diff --stat
 pyproject.toml | 2 +-           # ← only this
$ grep -A1 'name = "loci-core"' uv.lock
version = "0.4.0"                # ← still the old one
```

`gitman release` then tagged `v0.4.1` against a tree whose lockfile said
`0.4.0`. The drift persisted until an unrelated `uv sync` regenerated the file,
which produced a stray working-copy change **after** the release had been
pushed. I had to land a follow-up commit (`chore: sync uv.lock to version
0.4.1`) to clean it up.

**Cause.** `version bump` rewrites the version location named in
`gitman.toml` / the skill (`pyproject.toml`) and stops there. A uv project keeps
a second copy of its own version inside `uv.lock`.

**Consequence.** Every release in a uv-managed repo ships a lockfile that
disagrees with the manifest, and the correction lands *after* the tag. Anyone
building from the tag gets an inconsistent pair.

**Fix, in order of preference.**

1. After rewriting the manifest, run the project's lock refresh
   (`uv lock --offline`, or `--no-update` equivalent) when a `uv.lock` is
   present, and include the result in the same change.
2. Failing that, **detect** the stale lockfile and refuse the bump with a typed
   exit `1`, naming the command to run. A refusal is far better than a silent
   drift that surfaces after the tag is pushed.
3. At minimum, document it in the skill's Versioning section.

---

## G3 — gitman cannot be adopted by a repo that lacks vendomat's exact wheelhouse

**Severity:** Serious — this is the one that blocks the standing law

**Symptom.** loci-core's `AGENTS.md` and the my-ai law both say "route version
control through gitman." Adding gitman to the repo's dev extra fails outright:

```
$ uv sync --extra dev
  × No solution found when resolving dependencies:
  ╰─▶ Because pyjutsu was not found in the package registry and gitman==0.4.2
      depends on pyjutsu>=0.15.0, we can conclude that gitman==0.4.2 cannot
      be used.
```

The documented escape — vendomat's prebuilt wheelhouse — did not work either.
loci-core imports vendomat, but pinned to a **different revision** (a filtered
source-catalog snapshot). Enabling `vendor.libs = [ "pyjutsu" ]` there produces
a *different* wheelhouse derivation that is not in the store and must compile
the maturin extension:

```
error: could not compile `serde` (build script) due to 1 previous error
note: collect2: fatal error: cannot find 'ld'
error: Cannot build '…-vendomat-wheelhouse.drv'
```

This also **broke the devenv shell entirely** until the change was reverted,
because the shell derivation depends on `vendor-status`.

**Cause.** `pyjutsu` is a maturin extension that is not published to PyPI.
gitman's own `pyproject.toml` records the workaround as a comment:

> No `[tool.uv.sources]` for pyjutsu: it resolves from vendomat's prebuilt
> wheelhouse via `UV_FIND_LINKS` (set by the imported vendomat devenv module)

That works in gitman's own repo, whose vendomat input is the full repo. It does
not generalize: a consumer must import the *same vendomat revision* gitman was
built against, or build Rust.

**Consequence.** gitman is effectively un-adoptable in any repo not already
wired to that exact vendomat revision. In loci-core the fallback is:

```bash
devenv shell -- uv run --project ~/Documents/Projects/gitman gitman <cmd>
```

which works but has its own cost — see G5.

**Fix options, roughly in order of reach.**

1. **Publish `pyjutsu` wheels** (PyPI, or a self-hosted index / GitHub release
   assets referenced from `[tool.uv.sources]`). This makes `uv add gitman` work
   anywhere and removes the whole class of problem.
2. **Ship a `[tool.uv.sources]` entry** for pyjutsu pointing at a wheel URL, so
   a consumer needs no nix module at all.
3. **Document a consumer contract**: state plainly, in gitman's README and
   skill, that adopting gitman requires importing `vendomat/modules` at a named
   revision, with the exact `devenv.yaml` and `devenv.nix` stanzas. Today a
   consumer discovers this by watching their shell break.
4. **Make the vendored path degrade**: if the wheelhouse for the consumer's
   vendomat revision is not in the store, fail with a typed message naming the
   revision mismatch, instead of starting a Rust build that dies on a missing
   linker.

---

## G4 — `release <level>` cannot bump, so the documented one-shot is really five steps

**Severity:** Moderate

**Symptom.** The skill documents:

```
gitman release [<level>|--version X.Y.Z]   # (bump →) tag vX.Y.Z → push tag
```

In practice, on a repo with any live lane:

```
$ gitman release minor
release <bump> would tag an unlanded lane commit that `land` will rewrite.
Run `gitman version bump <level>` -> `gitman land` -> `gitman release`
(tags trunk), or land this lane first.
```

**Assessment.** The refusal is **correct and well-worded** — tagging a commit
that `land` will rewrite is a real bug it successfully prevented, and the
message names the fix. The issue is only that the skill advertises a one-shot
that is rarely available.

The real sequence I had to run, twice:

```bash
gitman start <name>-version-bump
gitman version bump <level>
gitman save -m "chore: bump version to X.Y.Z"
gitman land
gitman push
gitman release            # no level — tags trunk
```

**Fix.** Pick one:

1. Let `release <level>` do the bump-lane itself when trunk is clean: start a
   lane, bump, save with a generated message, land, push, tag. That matches
   what the skill already promises.
2. Or correct the skill: document `release` as tagging trunk only, and show the
   six-step sequence above as the canonical release procedure.

Option 2 is cheap and removes the mismatch today.

---

## G5 — running gitman from a foreign uv project mutates the target repo's venv

**Severity:** Moderate

**Symptom.** Because of G3, every gitman call in this session ran as:

```bash
devenv shell -- uv run --project ~/Documents/Projects/gitman gitman <cmd>
```

Each invocation printed package churn against **loci-core's** active venv:

```
Uninstalled 5 packages in 9ms
Installed 7 packages in 7ms
```

It installed `gitman` and `pyjutsu` into `.devenv/state/venv/bin` and removed
loci-core's own packages. This made `repoman doctor` report
`OK installed:git — gitman` — a **false positive**. The next `uv sync --extra
dev` pruned both back out:

```
- pyjutsu==0.15.0
```

**Cause.** `uv run --project X` respects the ambient `VIRTUAL_ENV` /
`UV_PROJECT_ENVIRONMENT` that devenv exports for the *host* repo, so the
foreign project's dependency closure is materialized into the host's venv.
This is uv behavior, not gitman's — but G3 forces users into it.

**Consequence.** Transient, misleading toolchain state, and unnecessary churn
in a venv another tool owns.

**Fix.** Primarily: fix G3 so nobody needs this invocation. Secondarily, if the
checkout-invocation is going to be the documented fallback, document it with an
isolating form (`UV_PROJECT_ENVIRONMENT=` unset, or a dedicated `uv tool
install`) rather than the bare `uv run --project`.

---

## G6 — two off-canonical events in one session

**Severity:** Moderate — reported for pattern data, one cause confirmed

**Symptom.** `save` / `publish` / `land` refused twice with:

```
refusing: repo is off-canonical (1 bookmark(s) out of sync with git:
<lane> — git ref(s) lag jj: <lane> — run `gitman reconcile`.)
```

`gitman reconcile` recovered cleanly both times, re-pointing the colocated git
ref to jj. **The refusal behavior is correct** — it stopped rather than
corrupting, and named the recovery.

**Causes.**

- **Event 2: confirmed my fault.** I ran a raw `git add -A .claude/skills`,
  which is exactly what the law forbids. Self-inflicted; no gitman defect.
- **Event 1: unexplained.** It appeared after a `uv run --project` gitman call
  (see G5), with no raw git command in between. Possibly the venv churn, but I
  did not isolate it.

**Why it is worth filing.** Existing project `29-concurrent-worktree-raw-git-desync`
covers the raw-git trigger. Event 1 may be a second trigger — a foreign-uv
invocation — and if so it belongs with 29. Suggest reproducing: from a devenv
shell in repo A, run gitman via `uv run --project <gitman>` and check
canonicity before and after, with no git commands involved.

---

## What held

Attacked or leaned on hard, and it did not break:

- **`split --paths`** carved 18 paths out of a 59-path entangled draft onto a
  new sibling lane, cleanly, first try. This was the single most valuable
  command of the session — the alternative was a commit mixing two projects.
- **`land` refusing an off-canonical repo.** Twice. It printed the recovery and
  changed nothing.
- **`release` refusing to tag a rewritable commit.** Prevented a real bug.
- **`sync`** rebased a 3-behind lane onto a trunk that had moved twice, with no
  conflicts and no lost work.
- **`reconcile`** recovered both desyncs with an explicit before → after ref
  report.
- **`undo` footers.** Every mutating command printed its own undo path. This
  materially lowered the cost of acting.
- **Exit codes.** Refusals were distinguishable from failures throughout.

## Suggested order

1. **G3** — it blocks the standing law in every new repo. Everything else is
   quality of life by comparison.
2. **G2** — silent release drift; cheap to fix, expensive to discover.
3. **G1** — one flag, or one deleted sentence.
4. **G4** — skill correction is a five-minute change.
5. **G5 / G6** — largely fall out of G3; G6 event 1 needs a reproduction first.
