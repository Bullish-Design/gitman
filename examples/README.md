# Gitman examples

- **[`lane-loop.sh`](lane-loop.sh)** — a runnable end-to-end demo of the lane loop in a
  throwaway colocated repo (init → start → save → status → land → undo → conflict rollback
  → reconcile). It never touches your real repo:

  ```bash
  devenv shell -- bash examples/lane-loop.sh
  ```

- **[`gitman.toml`](gitman.toml)** — an annotated sample config covering every key
  (`trunk`, `[lanes]`, `[publish]` verify hook, `[version]`, `[release]`, `[policy]`).

For adopting Gitman in your own repo, see [`../docs/USING_GITMAN.md`](../docs/USING_GITMAN.md).
