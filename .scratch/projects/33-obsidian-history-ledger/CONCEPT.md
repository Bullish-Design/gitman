# 33 — Obsidian repository history ledger

**Date:** 2026-08-27  
**Status:** concept  
**Scope:** Gitman repository-history projection and reconstruction

## Summary

Gitman should provide an Obsidian-compatible map of a repository's lifetime.
The map should show current state, historical changes, lane ancestry, workspace
activity, conflicts, releases, remote movements, and the Gitman operations that
caused those transitions.

The recommended design is a hybrid:

```text
jj operation log + Gitman intent records
                 ↓
         canonical history ledger
                 ↓
       Obsidian Markdown projection
```

The ledger is the machine source for reconstruction. The Markdown vault is a
first-class, durable, human-facing projection. Immutable event notes preserve
history. Mutable object notes summarize the latest known state. Index and
timeline notes connect the graph.

This design does not make generated Markdown the sole authority for version
control truth. jj remains authoritative for commits, changes, refs, and the
operation log. Gitman remains authoritative for its lane model and intent
semantics.

## Problem

Gitman currently writes a snapshot containing `repository.md`, lane notes, and
observed head-change notes. That projection does not preserve the full lifetime
of a repository. It omits historical changes, operation events, conflicts,
workspace transitions, releases, and many relationships between objects.

A lifetime map needs more than a current `RepoState`. It needs stable event
identity, append-only history, deterministic replay, and links that Obsidian
can follow. It also needs to avoid making the projection self-invalidating when
the output directory is inside the repository.

## Goals

1. Preserve a reconstructable record of Gitman-observed repository history.
2. Produce ordinary Markdown files with YAML frontmatter and `[[wiki-links]]`.
3. Give every projected object a stable identity and predictable path.
4. Keep current object pages easy to browse in Obsidian.
5. Rebuild the projection after deletion, migration, or format changes.
6. Make repeated synchronization deterministic and idempotent.
7. Keep jj and Gitman authoritative for version-control facts.
8. Support a durable vault directory such as `.loci/gitman`.
9. Detect malformed, duplicated, missing, or manually modified ledger entries.
10. Keep the base Gitman package lean and make optional integrations explicit.

## Non-goals

- Replacing jj's operation log.
- Treating arbitrary Markdown edits as valid Gitman commands.
- Recording every file-system event outside Gitman or jj.
- Reconstructing information that jj has already garbage-collected without an
  available snapshot or imported event.
- Building a general-purpose Obsidian synchronization service.
- Making Pydantree or Templateer required for the base command path.

## Concepts

### Canonical history ledger

The ledger contains normalized Gitman history records. Each record has a stable
event ID, an event kind, an ordering key, source operation ID, timestamp, and a
typed payload. A record is immutable after publication.

The first implementation can use JSON Lines or SQLite as the private canonical
ledger. JSON Lines is easier to inspect and migrate. SQLite provides stronger
queries and integrity checks. The choice should remain behind a small ledger
interface.

The ledger must support these properties:

- **Idempotence:** replaying the same source operation does not create a second
  event.
- **Ordering:** events have a monotonic local sequence in addition to a wall
  clock timestamp.
- **Provenance:** each event names the jj operation, Gitman intent, workspace,
  and source version when known.
- **Schema versioning:** readers reject or migrate unknown record versions.
- **Integrity:** records have checksums or a chain hash so truncation and
  accidental edits are detectable.
- **Recovery:** a rebuild can rescan jj and Gitman state and report gaps rather
  than silently inventing history.

### Projected objects

The projection should model at least these object kinds:

| Object | Stable identity | Purpose |
|---|---|---|
| Repository | repository identity | Root index and current summary |
| Change | jj change ID | Stable work identity across rewrites |
| Commit observation | commit ID plus observation ID | Historical content observation |
| Lane | lane name plus lineage ID | Workstream and ancestry |
| Workspace | workspace identity | Agent/workspace lifecycle |
| Operation | jj operation ID | Undo and repository transition history |
| Gitman event | event ID | Semantic intent and state transition |
| Conflict | lane plus conflict identity | Conflict discovery and resolution |
| Release | tag/version identity | Version and release milestones |
| Remote movement | remote plus observation ID | Push, pull, and divergence history |

Change IDs should remain the main identity for work. Commit IDs are observations
and must not replace change IDs because jj rewrites commits.

### Markdown layers

The vault should contain four layers:

```text
repository.md                 current repository entry point
timeline/*.md                 immutable event and operation notes
objects/{kind}/*.md           current materialized object pages
indexes/*.md                  generated maps and navigation pages
```

The exact directory layout is configurable, but object paths must be stable and
must encode identities safely. Each generated page should contain a marker such
as `generated_by: gitman`, a schema version, the object kind, and the stable ID.

An event page should link to affected objects. An object page should link back
to related events. The repository page should link to the current lanes,
changes, releases, and timeline. An index page should provide a compact
Mermaid or plain Markdown view when that helps navigation, but wiki-links remain
the primary graph format.

### Current pages and historical pages

Event pages are append-only. Object pages are regenerated summaries. This
prevents a lane page from losing its earlier states while keeping normal
browsing compact.

Retired objects remain as pages with a terminal state and links to the event
that retired them. The projection must never delete user-authored files. It may
only update files marked as Gitman-generated, and it must report generated files
that no longer correspond to ledger records.

## Write and recovery protocol

Gitman cannot atomically commit a jj transaction and a Markdown or ledger write.
The protocol must therefore be replayable:

1. Capture the pre-operation jj operation ID.
2. Execute the Gitman transaction.
3. Capture the resulting jj operation ID and post-state.
4. Derive an idempotent event record from the intent and post-state.
5. Append the event to the ledger using its stable source-operation identity.
6. Materialize Markdown pages from the ledger and current state.
7. Record projection success or failure without rolling back the VCS operation.

If the process stops between steps 3 and 5, the next `history sync` must detect
the unrecorded operation and import it or report a recoverable gap. If it stops
during projection, the next run must safely rewrite incomplete generated files.

`gitman history rebuild` should discard only generated projection output, replay
the ledger, and recreate all pages. A separate `gitman history repair` should
inspect ledger integrity and propose fixes before writing.

## Templateer and Pydantree

Templateer is a good fit for the rendering boundary. Gitman can define typed
projection models and use MiniJinja templates for event, object, index, and
timeline pages. Its Markdown output mode and deterministic rendering match the
projection requirements. Gitman should retain responsibility for object
planning, paths, backlinks, atomic writes, stale-page handling, and vault
layout. Templateer should be optional or reused through a small internal
adapter so the base package does not gain an unnecessary runtime dependency.

Pydantree is not the history engine. It is useful if Gitman needs to read
Markdown back into typed rows, validate complex Markdown structure, or import
user-authored annotations. Its tree-sitter extraction model can materialize
frontmatter, headings, links, and fenced regions into Pydantic models. Gitman
must still implement event identity, ordering, deduplication, replay, and graph
reduction. For Gitman-generated pages with a simple schema, direct Pydantic
validation is preferable at first.

## Obsidian compatibility

Generated pages should use:

- YAML frontmatter with scalar IDs and explicit schema versions.
- `[[relative/path|label]]` links for relationships.
- Stable filenames that do not depend on mutable descriptions.
- Normal Markdown headings and lists.
- No Obsidian plugin requirement for basic navigation.
- Optional Dataview-friendly fields, without making Dataview mandatory.

The renderer should avoid commit IDs and diff counts in tracked projections
unless the page is explicitly an immutable observation. Revision-dependent
facts can cause a projection inside the repository to change the repository
again. Immutable event notes can include them when they are part of the event
record and the resulting feedback loop is handled by the ledger boundary.

## Phased implementation

### Phase 1 — ledger seam

- Define event and object Pydantic models.
- Add a ledger interface and a JSON Lines implementation.
- Record Gitman intent name, source operation ID, sequence, timestamp, and
  post-state identity.
- Add deduplication and integrity checks.
- Add tests for replay and interrupted writes.

### Phase 2 — full projection

- Refactor the current Markdown projection into a planner and renderer.
- Add immutable event notes and historical change notes.
- Add object pages for operations, conflicts, workspaces, releases, and remote
  movements.
- Add repository, timeline, and index pages with Obsidian links.
- Preserve current `GITMAN_MARKDOWN_DIR` behavior.

### Phase 3 — rebuild and repair

- Add `history sync`, `history rebuild`, and `history repair`.
- Detect missing or edited generated pages.
- Import discoverable jj operations that lack ledger records.
- Report irrecoverable history gaps explicitly.

### Phase 4 — rendering integration

- Evaluate Templateer as an optional renderer backend.
- Add template metadata and output validation if external templates are useful.
- Evaluate Pydantree only for Markdown import or complex page validation.

## Acceptance criteria

The concept is implemented when:

1. A repository's Gitman operations produce stable, immutable event records.
2. A fresh vault rebuild produces the same files and links as the original.
3. Repeating synchronization produces no content changes.
4. Change pages survive commit rewrites because they use change IDs.
5. Retired lanes and changes remain discoverable through the timeline.
6. Obsidian opens the vault and follows links without a plugin.
7. A partial write is recoverable without duplicating events.
8. Manual edits to generated pages are detected and never silently treated as
   Gitman state.
9. Projection failures do not falsely claim that the VCS transaction rolled
   back.
10. The base package remains usable without Templateer or Pydantree.

## Open decisions

- JSON Lines or SQLite for the first ledger implementation.
- Whether the ledger lives inside `.gitman`, beside the vault, or in a separate
  user-local state directory.
- Whether immutable event Markdown is committed to the repository or exported
  to a separate vault.
- How much jj operation history can be imported after Gitman adoption.
- Whether event pages include commit IDs and diff statistics by default.
- Whether external templates are a supported public extension point or only an
  internal implementation detail.

## Recommendation

Implement the ledger seam and projection planner first. Keep Markdown as a
durable, Obsidian-compatible history export and materialized graph. Do not make
Pydantree or Templateer prerequisites for the initial implementation. Add them
behind explicit adapters after the event model, replay contract, and recovery
behavior are tested.
