# GPUI recipe validation

Run from the repository root with Python 3, Cargo, and a clean Zed checkout at
`4c7244790a075e862eeb4e5ccc12d6c8f5da6f7e`:

```sh
python3 validation/gpui/check.py --zed-checkout /path/to/zed
```

Omit `--zed-checkout` to find that revision in Cargo's git cache. The script
checks the revision and tracked source changes, extracts marked Rust fences
directly from the skill references, and runs a disposable consumer crate. It
copies the pinned workspace's lockfile and applies GPUI's required `async-task`
patch. Cargo may prune that copied lockfile or add the generated root package;
the upstream checkout is not modified.

The default is offline. Use `--online` once if the dependencies are not cached.
Use a Rust toolchain compatible with the checkout and install its host build
prerequisites. This harness was exercised on macOS with Rust 1.100.0.
Build outputs go to the ignored `validation/gpui/target` directory; use
`--target-dir /path/to/target` to reuse another cache. Generated source and the
consumer manifest are removed after the run, including on failure.

Coverage:

- Entity creation, updates, and reads without a window.
- A self-subscription receiving the emitted value.
- Awaited and detached tasks updating their owner.
- Timers remaining pending until the test clock reaches the deadline.
- Deferred selection updates occurring after the current borrow ends.
- A complete text element's layout, prepaint, and paint phases, with ASCII and
  multibyte text and matching text/hitbox geometry.

The `gpui-check` comments identify the exact fences compiled; there are no
separate copies of those recipes. Add a marked block to `RECIPES` in `check.py`
when expanding coverage. Missing or duplicate markers fail validation.

This harness does not validate every GPUI reference, rendering pixels, native
window movement, or platform controls. The earlier focused audit also exercised
actions, themes, globals, model/view notifications, and modal keyboard navigation
in temporary fixtures; those tests have not all been migrated here. Follow the
[native checklist](../../skills/gpui/references/window.md#platform-differences-and-native-verification)
in a visible consumer app for titlebar changes. The window reference records the
separate native probe's passing checks and remaining verification gaps.
