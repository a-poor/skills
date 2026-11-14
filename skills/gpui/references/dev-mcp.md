# Development MCP and screenshot inspection

Consider a small, app-specific MCP interface when repeated inspection of a
running GPUI app would improve development. Reuse existing automation when it
meets the task. Adding a bridge is an optional project decision, not a prerequisite
for ordinary UI work or a request to build a general GPUI automation framework.

The useful unit is an interaction, an observable state change, and a screenshot
of the resulting frame. A semantic command or a plausible image alone does not
establish that the user workflow works.

## Architecture and scope

A local IPC endpoint in the app can serve a stdio MCP adapter; a CLI can reuse the
same endpoint. Keep the endpoint and registration behind an explicit development
feature, disabled in normal builds. Use a process-specific local socket or an
equivalently restricted local transport, with an explicit app-instance identity.

Receive requests off the UI thread, then dispatch UI operations onto GPUI's
application thread using the project's existing foreground dispatch mechanism.
Do not access `Window`, `App`, or entities directly from the IPC worker. Bound
request waits and report closed windows or disconnected instances as errors.

## Suggested tools

These are proposed app tools, not built-in GPUI APIs. Start with the subset needed
by the app's workflows.

| Tool | Contract |
|---|---|
| `list_windows` | Return stable window IDs, titles, bounds, scale factors, and activation state. |
| `inspect_controls` | Return app-registered control IDs, roles, labels, enabled/focused state, and current bounds for a chosen window. |
| `input` | Click, move/drag, type text, press/release keys, or scroll through the normal input path. Identify the target window and coordinate space. |
| `wait_for_state` | Wait for a specific observable predicate with a timeout; return the resulting state revision. |
| `capture_window` | Capture the selected window after the requested state has been rendered; return an image and capture metadata. |
| `setup_fixture` (optional) | Load fixtures or reset state. Label this as semantic setup that bypasses user input. |

GPUI is not a browser DOM. Expose controls and state deliberately; do not promise
automatic inspection of every custom element. Use control IDs that survive
rerenders and resolve their latest bounds before an action. Return the bounds'
coordinate space (window-local logical pixels, physical pixels, or screen
coordinates) and scale factor so the adapter can map input correctly.

Distinguish OS-level input, injected GPUI events, and semantic state mutations in
tool results. An injected GPUI event can test the app's dispatch path without
testing AppKit or another native backend. A direct call to a button's business
logic tests neither focus nor hit testing. Keep fixture setup separate from
user-like input, and preserve normal focus, hit testing, and keyboard routing
for interaction tools.

## Wait for the resulting frame

A successful input response means the request was handled, not that its effect
has been painted. For each capture:

1. Apply input through the chosen path and wait for the expected observable
   state. Async work may complete after the input handler returns.
2. Request a redraw from handler/update context if needed. Wait until a completed
   frame includes that state; record an app-owned state/frame revision or another
   explicit completion signal.
3. Capture that frame on the application thread and return its window ID,
   dimensions, scale factor, state/frame revision, and capture method.

Do not substitute a fixed sleep for readiness. Verify the ordering of any frame
callbacks against the pinned GPUI source: a callback named "next frame" is not
by itself proof that the requested scene has finished rendering. On timeout,
report the last observed state instead of returning an old image as current.

## Screenshot support and fallback

At Zed revision `a19e19440d4102668830a9da579c3ee71d2fbf1a`,
[`Window::render_to_image()`](https://github.com/zed-industries/zed/blob/a19e19440d4102668830a9da579c3ee71d2fbf1a/crates/gpui/src/window.rs#L3091-L3098)
returns an RGBA image of the most recently rendered scene. It does not advance
the app, render pending state, or present the frame on screen.

- It is gated behind `cfg(test)` or GPUI's `test-support` feature. A consumer's
  own `cfg(test)` does not enable that configuration on a dependency. Wire the
  required GPUI and backend features into the development build after checking
  the pinned manifests.
- Backend support is required. The
  [platform default](https://github.com/zed-industries/zed/blob/a19e19440d4102668830a9da579c3ee71d2fbf1a/crates/gpui/src/platform.rs#L1482-L1488)
  returns an unsupported error; the
  [macOS backend](https://github.com/zed-industries/zed/blob/a19e19440d4102668830a9da579c3ee71d2fbf1a/crates/gpui_macos/src/window.rs#L2400-L2404)
  forwards to its renderer. Do not assume feature availability guarantees capture
  on every backend, renderer, or headless test platform.
- Scene capture covers GPUI-rendered content. OS-provided titlebar controls,
  menus, dialogs, and other native UI may be outside that scene.

When scene capture is unavailable or native UI is relevant, use the host's window
or screen-capture facility for the selected app window. Respect required OS
permissions and report capture failures. Identify the method in the result and
account for window position, display scaling, and any occlusion/cropping behavior
of that facility. Do not silently substitute a scene-only image for a native
window capture. Encode or save the image in a form the agent can actually view.

## Keep real-app interaction testing

After using MCP tools, the coding agent should still exercise the changed user
workflow through the visible UI and inspect its result, using native input tools
where available. If that path cannot be exercised, report the verification gap.
Semantic setup and screenshots can bypass broken focus, hit testing, keyboard
handling, or native window behavior.

For example, a tab reorder test can pass while dragging a real tab moves the
whole macOS window. Follow the
[native titlebar checks](window.md#platform-differences-and-native-verification)
for that case. Combine state assertions, visual inspection, and native input
checks according to what changed; passing MCP checks alone is not proof that
the app works.
