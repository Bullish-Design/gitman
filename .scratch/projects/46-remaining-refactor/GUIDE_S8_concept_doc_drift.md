# S8 — the concept doc becomes authoritative, and stays that way

**Size:** medium · **Risk:** low · **Closes:** issue 44 §7 drift · **Depends on:** S3, S5, S6, S7
**Was:** issue 44 G8 / stage 8.

Last by construction: it documents the verb set and the architecture that S3, S5, S6 and S7 settle.
Writing it earlier means writing it twice.

## 1. The measurement

`AGENTS.md` names `docs/GITMAN_CONCEPT.md` "the authority". It is not authoritative.
`probe_verb_drift.py` against §7's table:

```
shipped    24 [abandon catchup doctor init land log publish pull push reconcile release resolve
               save seed shape split start status subtask switch sync undo untrack version]
groups     ['remote']
documented 19 [abandon land publish pull push release remote-add resolve save seed split start
               status subtask switch sync undo untrack version]

SHIPPED BUT UNDOCUMENTED: ['catchup', 'doctor', 'init', 'log', 'reconcile', 'shape']
DOCUMENTED BUT UNSHIPPED: ['remote add']          # a Typer group, not a command
```

**Six verbs, not the two the inherited guide names** (`SCOPING.md` §4). `doctor`, `init` and
`reconcile` appear in §7's *prose preamble* but have no table row. And `shape` is listed under §7
**Deferred** while it ships.

Three further drifts, all verified:

- **§6 promises a planner/executor architecture that does not exist** until S7 builds it.
- **§7 says "The fractal-lanes model is complete."** Until S3, its publish path is broken for every
  non-leaf tree (`SCOPING.md` §2).
- **§7's `push` row** says "strict fast-forward (refuses non-FF → `pull`)". Issue 45 proved that
  false — the gate was content-based and force-pushed a divergent remote commit away. The shipped
  behaviour is now two gates (content **and** ancestry+change-id). The row must say so.

## 2. Steps

### 1. Re-run the measurement first

Do not trust the numbers above. S3, S6 and S7 will have changed the verb set — S6 in particular
should have *reduced* it. Re-run `.scratch/probes/probe_verb_drift.py` and work from its output.

### 2. Write the test before the prose

Inverting the guide's order on purpose: the failing test tells you exactly which rows to write, and
guarantees the doc you produce is the one the test accepts.

```python
def test_concept_doc_matches_cli_verbs():
    """The intent table in GITMAN_CONCEPT.md §7 lists exactly the shipped commands."""

def test_no_shipped_verb_is_listed_as_deferred():
    """§7's Deferred paragraph must not name a verb that ships (`shape` did, for a year)."""
```

Four rules for the test, each from a way this drift already happened:

1. **Compare against the table only, never the prose.** A test that accepts a prose mention is a
   test that permits the next drift — `doctor`/`init`/`reconcile` are undocumented *because* they
   were mentioned in a sentence.
2. **Set equality, both directions.** "Documented but unshipped" is how `shape` survived.
3. **Handle Typer groups explicitly.** `remote add` is a group plus a subcommand, not a command.
   Compare `app.registered_commands` against table rows, and assert each `registered_group` has its
   own documented rows — do not special-case `remote add` with a string exception, or the next
   subgroup (S6 adds `workspace`) slips through.
4. **Parse strictly.** A regex that silently matches nothing is a test that always passes. Assert
   the parsed row count is non-zero and equals the table's line count before comparing sets.

Reference parse, verified against the current table shape (rows begin `| \`<verb>\` |`):

```python
sec = doc.split("## 7. Intent vocabulary")[1].split("**Global flags:**")[0]
documented = set(re.findall(r"^\| `([a-z][a-z -]*)`", sec, re.M))
```

### 3. Rewrite §7 — the table

Add a row per undocumented verb, in the existing column shape
(`Intent | Signature | What it does | Underneath`). Move `shape` out of **Deferred** and give it a
row; keep its *unbuilt* part (hunk-level/interactive split) in Deferred, named precisely, so the
distinction between "the verb ships" and "this flag does not" survives.

Correct the `push` row to the post-issue-45 behaviour: two gates, and `--reset-origin` names the
commits it would drop. Add `workspace` rows from S6. Reflect S3's lane-name separator wherever §7
and §8 show a `/`-path — including the fractal-lanes paragraph, which S3 was told to touch with one
line and leave the rest to this stage.

### 4. Rewrite §6 — the architecture

From the code as it stands after S7. §6 currently describes a planner/executor split as though it
ships. After S7 it *does*, for five verbs, with `pull` deliberately excluded. **Document the
exclusion.** A doc that claims uniformity the code does not have is how §6 got wrong in the first
place.

### 5. Rewrite §11 — enforcement

§11 covers invariants and transactional rollback. Four things landed since it was written and each
changes it:

- stage 3b's **delta-based** postcondition (anomaly present after but not before), which replaced
  the absolute `not after.canonical` check;
- stage 4c's **note-only** anomaly kinds, which do not roll an intent back;
- stage 4d: **git refs are a publication artifact** — only `publish`/`push` export;
- issue 45 F2: **an irreversible network call runs after the guard closes**, not inside its body.
  This is now an invariant of the architecture and §11 is where it belongs.

### 6. Reconcile §5's invariants with the code

§5 lists I1-I5. Check each against `invariants.py` as it stands. I3 ("branch = lane name") is
materially changed by S3 if D-A1 was chosen (two representations) and unchanged if D-A2 was. State
which.

### 7. Sweep the other two docs

`docs/USING_GITMAN.md` and `docs/JUJUTSU_PRIMER.md` also carry `/`-path examples and the old verb
names. The drift test covers only §7 of the concept doc; these need a read-through. Consider
extending the test to assert no `docs/*.md` file names a deprecated verb outside a migration note —
cheap, and it is the same class of guard.

## 3. Done when

- [ ] `test_concept_doc_matches_cli_verbs` passes, compares the table only, asserts both
      directions, handles groups generically, and fails loudly on a zero-row parse.
- [ ] `test_no_shipped_verb_is_listed_as_deferred` passes.
- [ ] §6, §7 and §11 describe the shipped code, including S7's deliberate `pull` exclusion.
- [ ] §7 no longer claims the fractal-lanes model is complete unless S3 has made it so.
- [ ] The `push` row describes both gates.
- [ ] `USING_GITMAN.md` and `JUJUTSU_PRIMER.md` carry no stale verb names or lane separators.
- [ ] Suite green.
- [ ] Mark G8 shipped in `ISSUE.md` §10 — and issue 44 **closed**, with a one-paragraph summary of
      what shipped across all eight stages and what was deliberately left (`pull` on the old
      executor form; issue 33's ledger unbuilt).
