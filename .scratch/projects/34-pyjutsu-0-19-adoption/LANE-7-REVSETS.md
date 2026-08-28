# Lane 7 — revset classification under the glob default flip

Deliverable of guide 2, lane 7. Every revset gitman builds, classified.

pyjutsu 0.15 parsed revsets with `ui.revsets-use-glob-by-default = false`. pyjutsu 0.16 took jj's
own default, `true`. The flip changes how a **string pattern inside a revset function** is read
(`tags("v1.0")`, `bookmarks("feat")`). It does not change how a bare symbol resolves.

Engine: pyjutsu 0.20.0 / jj-lib 0.44.0. Site list from:

```
grep -rnoE "(resolve|log|conflicts|diff_stat|try_merge|is_ancestor)\(\s*f?\"[^\"]*\"" src/gitman/
```

---

## The table

| Site | Revset | Kind | Exposed to the flip? |
|---|---|---|---|
| `core.py:221` | `f"{commit_id} & ::({term})"` | commit id + no-arg functions (`tags()`, `trunk()`, `untracked_remote_bookmarks()`) | No |
| `core.py:547`, `state.py:407` | `f"@ & ({trunk}..)"` | bare symbols | No |
| `core.py:777, 891, 1263, 1527, 1642, 1660, 1791`, `lanes.py:48` | `f"{base}..{lane}"` | bare symbols | No |
| `core.py:1510, 1511` | `f"{trunk}..{commit_id}"` | bare symbol + commit id | No |
| `core.py:1575, 1576` | `f"{trunk}..{tip}"` | bare symbol + commit id | No |
| `core.py:1751, 1842, 2039`, `state.py:218` | `f"{trunk}@{remote}"` | bare remote-bookmark symbol | No |
| `core.py:2188`, `state.py:579` | `conflicts("@")` | bare symbol | No |
| `release.py:76` | `is_ancestor("@", …)` | bare symbol | No |
| `state.py:221, 222` | `f"{trunk}..{trunk}@{remote}"` | bare symbols | No |
| `state.py:358, 367` | `f"({git_id}) & {reachable}"` | commit/change ids + a built revset of bare symbols | No |
| `state.py:514` | `f"{trunk_name}.."` | bare symbol | No |
| `state.py:540, 548` | `f"{base_ref}..{name}"` | bare symbols | No |
| `state.py:24` (`_stray_revset`) | `f"({trunk}..) ~ ::(bookmarks() \| remote_bookmarks() \| tags()) ~ @"` | bare symbols + no-arg functions | No |
| `state.py:160, 177, 196` | `try_merge(a, b)` | commit ids, not a revset | No |
| `state.py:531, 551` | `diff_stat(name)` | bare symbol | No |
| **`release.py:42`** | `f'tags(exact:"{tag}")'` | **string pattern in a function** | **No — explicit `exact:` prefix** |

**One** site passes a string pattern into a revset function, and it already carries an explicit
prefix. Explicit prefixes are immune to the default. No site needed a change.

---

## Why lane names cannot reach the glob parser

Gitman supports stacked lanes named `T/api`, so the question is whether a `/`-path bare symbol
survives, and whether a lane name can smuggle in a glob metacharacter.

`lanes._SEGMENT_RE` is an allowlist:

```python
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._-]*$")
```

`*`, `?`, and `[` are not in it, and every lane name is validated before it reaches a revset. A glob
metacharacter therefore cannot enter a gitman revset through a lane name at all. This is the
structural reason lane 7 needed no fix, and it is now pinned by
`tests/test_revset_glob_default.py::test_lane_names_cannot_carry_a_glob_metacharacter`.

The `/` itself is a plain symbol character in jj. `test_stacked_lane_round_trips_through_status_land_and_abandon`
drives a real stacked lane through `status`, `land` (child into parent, then parent into trunk), and
`abandon`, all by name.

`test_tag_lookup_is_exact_not_a_prefix_glob` pins the one pattern site: a prefix does not match, and
a glob does not match.

---

## Conclusion

No behavioural difference found, and the absence is proved by test rather than assumed. The
configuration option is deliberately not set: doing so would make gitman's revsets depend on a
setting the operator can change.
