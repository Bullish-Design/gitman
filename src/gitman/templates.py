"""All jj template strings, in one place so they re-pin together on a jj upgrade.

Validated against jj 0.38.0 (see jj.EXPECTED_JJ_VERSION and concept §10). jj has **no
list/object literal** and `json()` rejects `.map()` results, so we build a custom JSON
object by concatenating `json()` of scalar leaves; list fields use
`"[" ++ xs.map(|x| json(x)).join(",") ++ "]"`. The result is `json.loads`-clean.

In these Python source strings, `\\"` becomes a literal `\"` that jj emits as `"`, and
`\\n` becomes `\n` that jj emits as a newline.
"""

from __future__ import annotations

# One JSON object per change. Use at any revset; pair with git numstat (keyed by
# commit_id) for diff numbers jj won't template. See concept §10.1.
CHANGE_OBJECT = (
    '"{"'
    ' ++ "\\"change_id\\":" ++ json(change_id.short())'
    ' ++ ",\\"commit_id\\":" ++ json(commit_id.short())'
    ' ++ ",\\"desc\\":" ++ json(description.first_line())'
    ' ++ ",\\"empty\\":" ++ json(empty)'
    ' ++ ",\\"conflict\\":" ++ json(conflict)'
    ' ++ ",\\"bookmarks\\":[" ++ bookmarks.map(|b| json(b.name())).join(",") ++ "]"'
    ' ++ "}\\n"'
)

# One JSON object per bookmark entry from `jj bookmark list`. `present` guards deleted /
# remote-only bookmarks whose local `normal_target()` is absent (calling .change_id() on it
# errors), so the target fields are emitted only when the bookmark is present locally —
# otherwise the line would be invalid JSON. parse_bookmarks then keeps present ones.
# See concept §10.2.
BOOKMARK_OBJECT = (
    '"{"'
    ' ++ "\\"name\\":" ++ json(name)'
    ' ++ ",\\"remote\\":" ++ json(remote)'
    ' ++ ",\\"present\\":" ++ json(present)'
    ' ++ ",\\"change_id\\":" ++ if(present, json(self.normal_target().change_id().short()), "null")'
    ' ++ ",\\"commit_id\\":" ++ if(present, json(self.normal_target().commit_id().short()), "null")'
    ' ++ "}\\n"'
)

# Op-log entries: {id, parents, time:{start,end}, description, is_snapshot, tags:{args}}.
# tags.args is the literal command behind each op — surfaced in undo reports. Concept §10.4.
OPLOG_OBJECT = 'json(self) ++ "\\n"'
