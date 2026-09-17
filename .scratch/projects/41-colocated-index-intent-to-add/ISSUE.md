# ISSUE — a colocated snapshot stages every new file as the empty blob, and raw-git tooling reads that as data loss

> **Status:** SHIPPED (2026-09-17, project 46 S2 — `gitman doctor`'s `colocated-index` row +
> `state.intent_to_add_entries`; see `GUIDE_S2_doctor_intent_to_add.md` and
> `tests/test_issue41_intent_to_add.py`). Captured 2026-09-15 from a devman
> Project 038 cleanup session that measured the state across 53 repositories.
> **gitman version at capture:** 0.6.2 (jj-lib in-process through pyjutsu).
> **Scope:** gitman itself, plus one documentation change. The underlying
> behaviour belongs to jj and is correct; the defect is that gitman never
> explains it, and raw-git tooling misreads it as corruption.

---

## 1. TL;DR

Every gitman command snapshots the working copy. In a **colocated** repository
that snapshot exports to `.git/index`. A file that jj tracks but git has never
committed lands in the git index as an **intent-to-add** entry: mode `100644`,
blob `e69de29bb2d1d6434b8b29ae775ad8c2e48c5391` (the empty blob), a zeroed stat
cache, and `CE_EXTENDED | CE_INTENT_TO_ADD` (`flags 20004000`).

This is correct jj behaviour. It is how a colocated repository makes its
working-copy files visible to git and to Nix flake evaluation without staging
content.

**The problem is that it is indistinguishable, to an agent reading `git`, from
index corruption.** A reviewer runs:

```sh
git ls-files -s | awk '$2=="e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"'
```

…sees a 39 KB source file staged as empty, and concludes that the next commit
will overwrite it with nothing. That conclusion is wrong, but the reasoning is
sound given what git reports. On this machine it produced a fleet-wide repair
plan against 140 paths in 28 repositories, none of which needed repairing.

---

## 2. The measurement

Scanned `~/Documents/Projects`, 2026-09-15, for paths staged as the empty blob
whose working-tree file is non-empty:

| | Count |
|---|---|
| Repositories with at least one such path | **28** |
| Paths | **140** |
| Of those repositories, jj-colocated | **28 of 28** |
| Non-colocated repositories affected | **0** |

The correlation is exact in both directions among colocated repositories that
hold uncommitted new files. `.jj/working_copy` and `.git/index` mtimes match to
the same second in 18 of the 28.

Eleven repositories had their index rewritten between `22:37:22` and `22:38:12`
on 2026-09-13 with **no git command in shell history for any of them**. gitman
calls jj-lib in-process through pyjutsu, so nothing reaches the shell and
nothing reaches `atuin`. That silence is what made the cause hard to find: the
investigation first blamed `git add -A`, which is not capable of producing the
state.

### Reproduction

```sh
jj --version   # 0.44.0
git init -q . && git commit -qm init --allow-empty
jj git init --colocate
printf 'REAL CONTENT\n' > newfile.toml
jj status
git ls-files -s
#   100644 e69de29bb2d1d6434b8b29ae775ad8c2e48c5391 0  newfile.toml
git ls-files --debug -- newfile.toml
#   ctime 0:0  mtime 0:0  dev 0  ino 0  uid 0  gid 0  size 0  flags 20004000
git status --short
#    A newfile.toml
wc -c newfile.toml
#   13 newfile.toml          <- the working tree is intact
```

### What was eliminated

`git add -A`, `git restore --staged <path>`, `git reset -- <path>` and
`git rm --cached <path>` were each tested. None produces an intent-to-add entry.
The first stages real content; the other three leave the path untracked (`??`).

---

## 3. Why it is mostly harmless, and where it is not

Two states share the one symptom, and they differ in consequence.

| `git status --short` | Path in `HEAD`? | Count | What a commit does |
|---|---|---|---|
| `" A "` | no | **138** | A plain `git commit` ignores the path and leaves it on disk, even when other files are staged. `git commit -a` records the **real content**. No loss is reachable. |
| `"DA"` | **yes** | **2** | A plain `git commit` records a **deletion**. `git commit -a` records the real content. |

The `DA` case needs a divergence between jj's parent commit and git's `HEAD`:
jj sees the path as new, git sees it as tracked. Both instances found on this
machine were in one repository (`vendomat`), and both working-tree files were
byte-identical to `HEAD`, so nothing could have been lost even by a plain
commit.

**No commit anywhere in the fleet since 2026-06-01 recorded the empty blob for a
file that previously had content.** Verified with `git log --all --raw` over
every repository, matching destination blob `e69de29…` against a non-empty
source blob. Zero hits. The failure mode everyone feared has never occurred.

---

## 4. The cost

1. **A false alarm that scales.** The scan above reads as several hundred
   corrupted files. Two separate devman sessions (Project 038 Stage 38, and
   Wave 3 item 1) attributed it to `git add -A` and wrote repair plans. Wave 3
   item 1 unstaged nineteen `.devman/project.toml` entries one repository at a
   time.
2. **The repair does not hold.** `git restore --staged` on a path absent from
   `HEAD` leaves it untracked, and the next gitman command re-creates the
   intent-to-add entry. Any fleet-wide "repair" of the `" A "` state is churn.
3. **The real defect hides in the noise.** The `DA` state is worth catching. At
   a signal-to-noise ratio of 2 in 140 nobody will catch it by reading a list.
4. **`git stash` is a live hazard.** An intent-to-add entry interacts badly with
   several raw-git verbs. gitman already warns about raw-git use, but not about
   this specific shape.

---

## 5. Suggested fix

Three parts. The first is the one that matters.

### 5.1 `gitman doctor` — name the state, and separate the two cases

Add a check that reads the index once per repository and classifies. Cost is one
`git ls-files -s` plus one `git status --porcelain`.

- Report `" A "` entries as **informational**, with the explanation: *"N files
  are tracked by jj and not yet committed to git. The git index shows them as
  intent-to-add (the empty blob). This is expected in a colocated repository and
  needs no action. The working tree is intact."*
- Report `"DA"` / `"D "` entries as a **finding**: *"path is in git `HEAD` but
  the index holds an intent-to-add entry. A plain `git commit` would record a
  deletion. jj's parent and git's `HEAD` have diverged."* Name the repair.

Keying the check on the empty blob alone reproduces the false alarm in the
tool. The classifier must be `status` code plus `HEAD` presence, not blob hash.

### 5.2 Document it where an agent will read it

Add a short section to gitman's `AGENTS.md` or the skill — under whatever
already covers raw-git co-tenancy — stating the exact byte pattern
(`e69de29…`, `flags 20004000`, status `" A "`), that it is expected, and that
the working tree is never at risk. Give the one-line scan and its correct
interpretation. Anyone who greps the index will find this state eventually; the
document is what stops the next fleet-wide repair plan.

Cross-reference the existing raw-git desync records —
`29-concurrent-worktree-raw-git-desync` and `40-read-intent-desync` — this is
the same family: gitman's in-process snapshot changes git state that no shell
history records.

### 5.3 Consider a `gitman status` line

When the working copy holds jj-tracked files that git has never committed, one
line in `gitman status` would make the state visible at the moment it is
created, rather than months later during an audit. Worth weighing against
`status` output noise; 5.1 and 5.2 deliver most of the value.

### Explicitly not proposed

Do **not** stop exporting intent-to-add entries. Nix flake evaluation reads the
git tree, so an untracked new file is invisible to `nix flake check` and to
`nix build`. Suppressing the export would break every colocated repository that
evaluates a flake from a dirty tree — which is the whole fleet. The behaviour is
load-bearing. Only its legibility is broken.

---

## 6. Evidence

- devman Project 038, `.scratch/projects/038-devman-plane-redesign/` — the
  session that produced the measurement. `IMPLEMENTATION_LOG.md:2098-2099` and
  `:2160-2164` hold the incorrect `git add -A` attribution.
- `WAVE_3_EXECUTION_PROMPT.md:153-178` — the nineteen-repository repair that the
  correct diagnosis makes unnecessary.
- jj 0.44.0, git 2.54.0, pyjutsu in-process.
