# 63 — `version` and `release` need a uv project; no Nix-only repo in the fleet has one

**Found:** 2026-10-02, releasing `nix-secrets` so `nix-meta` could pin its new commit as a
flake input.
**Status:** open — a design is proposed below, not yet agreed.
**Versions:** gitman 0.10.3 · pyjutsu 0.22.0 (jj-lib 0.44.0) · colocated repo.
**Line numbers below are current as of `main @ e6994c6` (2026-10-02)**, matching this
repository's own `gitman status` at the time of writing. Every citation was checked
against that commit.

## 1. What happened

`nix-secrets` is a Nix-only repository: NixOS modules, shell operator scripts, a sops
secrets store, a runbook. It is repoman-managed and has a `devenv.nix`. It has no
`pyproject.toml` and no `uv.lock` — there is nothing for uv to own. A lane had just landed
and trunk had just been pushed. The next step needed a `v0.1.1` tag so `nix-meta` could
pin the new commit.

Both of these refused, identically:

```
$ gitman release --version 0.1.1
Gitman release — REFUSED
reason: uv version --short failed: error: No `pyproject.toml` found in current directory or any parent directory

hint: If you meant to view uv's version, use `uv self version` instead
```

```
$ gitman release
Gitman release — REFUSED
reason: uv version --short failed: (same)
```

`gitman version` refuses the same way.

The detail that cost the most time: **`--version 0.1.1` does not skip the uv read.** The
flag's own help text, `cli.py:570`, reads `help="Set an explicit X.Y.Z."` — which reads
like it should remove the need for a version source entirely. It does not. Traced through
`release.py:20-26`:

```python
def _target_version(repo_root: Path, level: str | None, set_version: str | None) -> tuple[str, str]:
    from gitman.version import bump, parse_semver, read_version

    current = read_version(repo_root)
    if set_version:
        parse_semver(set_version)
        return current, set_version
```

`current = read_version(repo_root)`, at `release.py:23`, runs **unconditionally**, before
the `if set_version` check on `release.py:24` is even reached. `read_version`
(`version.py:60-64`) calls `uv version --short` through `_run_uv` (`version.py:48-57`),
which is exactly the call that fails with no `pyproject.toml`. The `set_version` value is
never consulted until after the failing call has already raised. The flag changes what
version gets tagged; it does not change what gitman needs to read first.

## 2. It is by design, not an accident

- `init.py:49` already states gitman's own diagnosis in plain words:
  `"no pyproject.toml version — \`version\`/\`release\` need a uv project"`. `init.py:46-48`
  detect a version source by checking for a `pyproject.toml` containing
  `version = "X.Y.Z"` (`init.py:46-48`, using the regex at `init.py:47`):
  ```python
  pyproject = repo_root / "pyproject.toml"
  if pyproject.is_file() and re.search(r'version\s*=\s*"\d+\.\d+\.\d+"', pyproject.read_text()):
      return "", 'pyproject.toml (`version = "X.Y.Z"`), read and written through uv'
  return "", "no pyproject.toml version — `version`/`release` need a uv project"
  ```
  `init` detects and names the gap correctly. Nothing downstream acts on that diagnosis —
  it is computed for `gitman init`'s own scaffold message and discarded.
- `version.py:1-11`, the module docstring, states the policy outright: *"Gitman owns the
  semver math and the tag/release flow. It does **not** own the version number: uv does."*
  It also records why: a configurable backend existed once, rewrote the manifest and
  stopped, and a uv project's `uv.lock` kept the old number while `release` tagged the
  drift (project 32, finding G2). uv became the single source of truth to close exactly
  that gap.
- The lock-agreement requirement lives in `check_lock` (`version.py:67-78`): it runs
  `uv lock --check` unless there is no `uv.lock` file, in which case it passes. It is
  called unconditionally at the top of `do_release` (`release.py:60`), inside a comment
  citing the same project-32 incident. It is harmless for a non-uv repo on its own — the
  failure happens one line earlier, at the version read.
- The write path is `write_version` (`version.py:81-92`): `uv version --no-sync <new>`,
  then `check_lock`, then a re-read to confirm uv wrote what was asked.
- The gitman skill states the policy even more flatly. The canonical copy for this work,
  `nix-meta/.claude/skills/gitman/SKILL.md:172-173`, reads: *"uv owns the version.
  \`gitman version bump\` calls uv, so \`pyproject.toml\` and \`uv.lock\` move together in
  one change. \`release\` refuses to tag while they disagree. Nothing is configurable."*
  That last sentence is the fleet-wide expectation this issue is reporting a gap against.

  One documentation-drift note, not pursued further here: `docman/skills/gitman/SKILL.md`
  carries a differently-worded Versioning section (`release` "refuses to tag a stale
  lock", and no "Nothing is configurable" sentence at all). The two copies of the same
  skill have drifted apart. `.scratch/projects/62-skill-md-sync` already exists to track
  skill-copy drift; this issue only needs the `nix-meta` wording above and defers the
  drift itself to project 62.

This is a closed, deliberate design, correctly built for the problem it was built to
solve (a uv project's manifest and lock drifting apart). It was not built with a non-uv
repository in mind, and nothing in `version.py`, `release.py`, or `init.py` offers that
repository a path through.

## 3. Fleet evidence: this is not a one-off

Checked today with read-only `git`, across every repository named below (`git -C <repo>
tag -l`, and `git -C <repo> for-each-ref --format='%(refname:short) %(objecttype)
%(contents:subject)' refs/tags` to tell an annotated tag — a tag object, with its own
message — from a lightweight one — a bare pointer at a commit, which is what a plain
`git tag v1` makes):

| Repo | `pyproject.toml` | Tags | Tag type | Message style |
|---|---|---|---|---|
| `nix-meta` | no | 0 | — | — |
| `nix-secrets` | no | 1 (`v0.1.0`) | lightweight (`commit`) | commit's own subject, not a tag message |
| `nixos-core` | no | 0 | — | — |
| `nix-terminal` | no | 0 | — | — |
| `nixbuild` | no | 0 | — | — |
| `nix-nvim` | no | 2 (`v0.1.0`, `v0.2.0`) | annotated (`tag`) | bespoke prose, e.g. "loci-rich Neovim 0.12 HM editor module; pins loci.nvim@v0.1.1 ..." |
| `nix-paseo` | no | 1 (`v0.1.1`) | annotated (`tag`) | bespoke prose, "enable Paseo plugins and declare directory sources" |
| `gitman` | yes | 21 | mostly annotated, 2 lightweight (`v0.4.1`, `v0.4.2`) | gitman's own, e.g. "Release 0.9.2" |
| `repoman` | yes | 15 | mostly annotated, 1 lightweight (`v0.4.0`) | gitman's own |
| `vendomat` | yes | 19 | mostly annotated, 1 lightweight (`v0.3.4`) | gitman's own |

The small number of lightweight tags inside `gitman`, `repoman`, and `vendomat` is itself
informative, not noise: `release.py:4-5`'s module docstring notes that pyjutsu made
lightweight jj tags the *default* until pyjutsu 0.17, after which gitman names the
annotated writer directly. The handful of early lightweight tags in gitman's own history
predate that pin; every tag made by a current `gitman release` is annotated.

**No Nix-only repository in this fleet has a gitman-made tag.** `nix-secrets`'s one tag is
lightweight — gitman has never produced a lightweight tag since pyjutsu 0.17, and gitman
cannot tag `nix-secrets` at all today (§1). `nix-nvim`'s and `nix-paseo`'s tags are
annotated, but the messages are hand-written sentences describing the release's content,
not the "Release X.Y.Z" / "`<repo>` X.Y.Z — ..." pattern gitman's own tag-writer produces
in `gitman`, `repoman`, and `vendomat`. Every tag in these six Nix-only repositories was
made by a person running `git tag` directly.

## 4. Why this matters beyond convenience

`vendomat/.scratch/projects/07-local-depot-release-bus/IMPLEMENTATION.md` (confirmed:
line 182 states the current graph has "24 repos and 28 edges") designs the whole
dependency graph to resolve flake inputs from the depot as
`git+file:///srv/git/<repo>.git?ref=refs/tags/vN` (line 26, repeated at lines 85, 353,
359). Tags are the addressing scheme for the entire graph, not a label on the side of it.

At least six of those 24 repositories — the six marked "no" in §3 that have no tags at
all yet, plus `nix-secrets` which already has one — are Nix-only with no `pyproject.toml`
and so cannot produce a tag through gitman at all.

`nix-meta/flake.nix:69-75` explains, in its own comment on the `nix-secrets` input, why a
tag and not a branch or a bare path:

```
# Consumed from the LOCAL working copy, pinned to a TAG. `git+file:` keeps
# the encrypted store on this box — a secret reaches the rebuild as soon as
# it is committed and tagged here, with no push to GitHub in the loop. The
# tag is what keeps that honest: `git+file:` sees committed files only, so a
# bare path or a branch ref would let an in-progress edit to the store slip
# into a rebuild.
```

`git+file:` resolves whatever a ref currently points at; a branch ref moves every time
someone commits, so an in-progress edit to the secrets store could be mid-rebuild before
it is reviewed. A tag is pinned once and does not move. That is the entire safety
property the release bus design depends on.

So a hand-made tag on one of these repos is not a cosmetic deviation from house style —
it is an ungated write to the one thing the release bus keys its addressing on. A tag made
by hand never runs `[release].verify` or `[publish].verify`; `release.py:63-66` runs that
verify step before any tag is written, and a hand-made `git tag` has no equivalent gate.
gitman cannot refuse to tag a commit that fails its own gate, because gitman is not the
tool making the tag.

## 5. Smaller usability points

- The refusal surfaces a raw `uv` error and a `uv` hint — "If you meant to view uv's
  version, use `uv self version` instead" — that has nothing to do with gitman's actual
  requirement and actively misleads: the fix is not a different `uv` subcommand, it is
  having a `pyproject.toml` at all, or not needing one. The message should name gitman's
  own requirement and point at the fix, the way `init.py:49` already phrases it for
  `init`'s own scaffold step.
- `gitman init` already detects and names the missing version source (`init.py:46-49`),
  but nothing carries that detection forward. `gitman doctor`'s checklist (seen directly
  in this session — `devenv`, `pyjutsu`, `git`, `colocated`, `remote`, `trunk`, `uv`,
  `publish-verify`, `colocated-head`, `colocated-refs`, `colocated-index`) has no row for
  the version source. Adding one would surface this before a `release` attempt, not
  during one.

## 6. How this should work

Four shapes, in increasing order of how much they change:

**Option A — make `--version X.Y.Z` self-sufficient.** The smallest fix: when
`set_version` is given, skip `read_version` and `check_lock` entirely and tag at that
version directly. The flag's help text already promises exactly this read. What gitman
loses by stopping here: no version is ever persisted anywhere, so a later `gitman
release` (no flag) still cannot infer "the previous version" for a `bump`, and `gitman
version bump <level>` still does not work in a non-uv repo — there would be nothing to
bump. Useful as an immediate stopgap; does not close the gap on its own.

**Option B — a pluggable version source in `gitman.toml`.** A `[version]` table naming a
provider:
- `uv` — today's behaviour, and the default whenever `pyproject.toml` exists (no change
  for any of the three uv-backed repos above).
- `tag` — derive the current version from the newest `v*` tag already in the repo. Needs
  no file at all, commits nothing new, and matches what `nix-nvim` and `nix-paseo` are
  already doing by hand: the tag history already *is* the version history for a Nix
  repository. `bump` would compute the next semver from the newest tag and pass it
  straight to the existing tag-writing code in `release.py`; it would never call `uv`.
- `file` — a path and a pattern, for a repo that tracks its version somewhere other than
  `pyproject.toml` (e.g. a `VERSION` file or a Nix attribute).

Under this option, the `check_lock` call at `release.py:60` has to become conditional on
the provider rather than unconditional — it is meaningless once there is no
`pyproject.toml`/`uv.lock` pair to compare, and should simply not run for `tag` or `file`.

**Option C — a `none`/`tagless` mode.** `gitman version` refuses with a clear, gitman-
authored message (reusing `init.py:49`'s wording) in a repo with no configured provider,
while `gitman release` still works given an explicit `--version` (Option A) or a
tag-derived version (Option B's `tag` provider, used only for reading, never for `version
bump`). This is really Option A and Option B's `tag` provider combined into one named
mode, not a fourth independent design.

**Recommendation: Option B, with `tag` as the default provider whenever `gitman init`
finds no `pyproject.toml`.** `read_version` (`version.py:60`), `check_lock`
(`version.py:67`), and `write_version` (`version.py:81`) all take a `repo_root: Path` and
nothing else as their contract with the rest of `release.py` and `do_version`
(`version.py:152`) — the provider boundary already exists at exactly this seam, so adding
a second provider behind it is additive, not a rewrite of the call sites. Nothing in the
source changed my mind about this versus Option A: Option A alone leaves `version bump`
permanently broken for every non-uv repo, and this fleet already has at least seven of
them with no sign that count will shrink. Option A is still worth doing as an immediate,
small stopgap — it fixes today's exact failure — but it should not be the final answer.

## 7. The workaround used today

The tag was made by hand: `git tag -a v0.1.1`, directly in `nix-secrets`, as a deliberate,
explicitly authorised, one-step exception to the standing rule that all version control
in this fleet goes through gitman.

Cost of the exception: the tag was not gated by `[release].verify` or `[publish].verify`
— nothing checked that `nix-secrets` was in a releasable state before the tag was
written, the way `release.py:63-66` would have. The exception is not a one-time fix; it
has to be re-granted, by hand, for every future `nix-secrets` release (and for every
other Nix-only repo's release) until one of §6's options ships.
