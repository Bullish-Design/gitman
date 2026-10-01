# 56 — a `gitman bookmark track` verb

**Filed:** 2026-10-01 · pyjutsu 0.16–0.22 (jj-lib 0.44.0) · **Status: DESIGN — no code changed.**

## 1. The problem

pyjutsu 0.16 refuses to rewrite any commit under
`::(trunk() | tags() | untracked_remote_bookmarks())`. Gitman explains the refusal through
`explain_immutable` (`src/gitman/core.py:216`), and for the `untracked_remote_bookmarks()` term its
advice — "drop the tag or the remote branch outside gitman" — is wrong. In the field shape below,
the untracked bookmark IS the lane's own published twin, at the identical commit. Dropping it does
not free anything (a re-fetch recreates it untracked); deleting the real remote ref would destroy
published history. The only safe fix is to make jj **track** the bookmark. pyjutsu already exposes
`Transaction.track_bookmark` (confirmed below); gitman calls it nowhere.

`gitman status` makes this worse: it classifies a lane as `published` from the mere existence of a
`<lane>@<remote>` bookmark row (`src/gitman/state.py:85`, `:157`), never from jj's `tracked` flag.
So `status` reports PUBLISHED while `land`/`publish`/`abandon`/`sync` refuse outright — the report
and the refusal disagree, and the refusal lands on the operator with no warning.

## 2. The measured evidence (2026-10-01, four repos, six lanes)

| Repo | Lane | `<lane>@git` | `<lane>@origin` | Same commit? |
|---|---|---|---|---|
| structured-agents-v2 | project19-moe-moa-reactive-inference | tracked=True | tracked=**False** | yes, `caec43ee5` |
| structured-agents-v2 | project21-arrow-adapter-routing | tracked=True | tracked=**False** | yes, `7318390f7` |
| structured-agents-v2 | training-token-monitor | tracked=True | tracked=**False** | yes, `32dd5f9ec` |
| tyo3 | 039-devman-item3-tyo3 | tracked=True | tracked=**False** | yes, `51cff3da2` |
| llama-infernal | feat+p2-nanbeige-hats | tracked=True | `feat/p2-nanbeige-hats@origin` tracked=**False** | yes, `be11e36ac` |
| paloma-story-generation | research/write-in-text-gen-baseline | tracked=True | tracked=**False** | yes, `6e0cdb945` |

In every row the lane's own remote twin sits at the identical commit, and jj does not track it.
Five rows are the exact-name case; the `llama-infernal` row is the legacy-separator case — the
untracked bookmark is named with the pre-migration `/` separator (`feat/p2-nanbeige-hats`), not the
lane's own `+`-separated name (`feat+p2-nanbeige-hats`). §3.3 of `DESIGN.md` treats this case
separately: name-matching alone misses it.

`pyjutsu.Transaction` exposes the fix already:

```
['track_bookmark', 'untrack_bookmark']
```

(confirmed interactively: `from pyjutsu import Transaction; [n for n in dir(Transaction) if 'track' in n]`).
`grep -rn track_bookmark src/` returns nothing today.

## 3. The decision

- **New verb: `gitman bookmark track <lane> [--remote NAME] [--as NAME]`**, under a new `bookmark`
  noun sub-app — not a flat `gitman track <lane>`. A flat `track` reads as the mirror of
  `gitman untrack <path>` (`src/gitman/cli.py:458`), which untracks a machine-local **file**, a
  wholly different object. Namespacing under `bookmark` removes the collision outright and matches
  the existing noun-subcommand precedent (`remote add` at `cli.py:467`, `workspace
  list/forget/prune` at `cli.py:580`). `gitman bookmark untrack <lane>` ships alongside it for
  symmetry with pyjutsu's own pairing, though `track` is the one that fixes this issue.
- **`gitman repair` auto-tracks the safe case** (exact-name twin, identical commit) — it is a
  bookmark write, not a rewrite, so it carries none of the ambiguity `repair --keep` exists for.
  The legacy-name and divergent-commit cases stay explicit, operator-named acts.
- **A new anomaly kind, `lane-untracked-twin`**, reported by `status`/`doctor` BEFORE a verb
  refuses, so the refusal is never a surprise. It blocks `land`/`publish`/`push` (mirroring what
  pyjutsu itself already refuses) and is NOT note-only, because it genuinely blocks.
- **Tag and trunk refusals are untouched.** `ignore_immutable=True` is never proposed. See
  `DESIGN.md` §2.

See `DESIGN.md` for the full failure chain, the options considered, and the open questions; see
`IMPLEMENTATION.md` for the ordered build plan.
