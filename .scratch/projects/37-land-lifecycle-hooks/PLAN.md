# 37 — Implementation plan

1. Add typed land-hook configuration and event payload models.
2. Add a standard-library command runner with JSON input, timeout, and output
   capture.
3. Add a repository-relative working-tree fingerprint and allowed-path checks.
4. Extend `canonical_guard` with an internal already-locked mode.
5. Wrap the complete land invocation with the shared repository lock.
6. Run the pre-hook before canonical snapshotting and VCS mutation.
7. Run the post-hook after lock release and preserve honest result fields.
8. Add focused integration and unit tests for configuration, path changes,
   hooks, land ordering, failures, JSON output, and compatibility.
9. Run lint and the complete test suite, then commit and push through Gitman.
