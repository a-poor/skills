# Window chrome & appearance

## Custom titlebar (macOS-first, cross-platform notes below)

### Interactive tabs and application-owned dragging

On Zed revision `a19e19440d4102668830a9da579c3ee71d2fbf1a`, the macOS backend's
`on_hit_test_window_control` ignores its callback. Tagging a bar with
`WindowControlArea::Drag` and stopping GPUI event propagation therefore does not
prevent AppKit from moving the window when a user drags a tab.

For custom macOS titlebars with interactive or reorderable content, opt into
application-owned dragging:

```rust
WindowOptions {
    titlebar: Some(TitlebarOptions {
        appears_transparent: true,
        traffic_light_position: Some(point(px(9.), px(9.))),
        ..Default::default()
    }),
    app_owns_titlebar_drag: true,
    ..Default::default()
}
```

Then start native window movement only from empty titlebar chrome. For example,
place this empty spacer beside the tabs and controls in a horizontal titlebar:

```rust
div()
    .id("titlebar-drag-space")
    .flex_1()
    .h_full()
    .on_mouse_down(MouseButton::Left, |event, window, _cx| {
        match event.click_count {
            1 => window.start_window_move(),
            2 => window.titlebar_double_click(),
            _ => {}
        }
    })
```

Give the titlebar a nonzero height and reserve space for the traffic lights
(for example, `.pl(px(80.))`). Keep the empty drag region separate from interactive
elements. If a drag handler is attached to an ancestor containing tabs or buttons,
those controls must stop **mouse-down** propagation in their existing handlers,
after performing their own selection or drag setup:

```rust
.on_mouse_down(MouseButton::Left, |_event, _window, cx| {
    // Perform this control's mouse-down behavior here.
    cx.stop_propagation();
})
```

Stopping only `on_click` is too late for an ancestor's mouse-down handler. Child
controls must also keep double-clicks from reaching titlebar behavior. Use
`window.titlebar_double_click()` for empty chrome so the native user preference
is respected; do not hardcode maximize. The example handles it on the second
mouse-down, so do not also invoke it from `on_click`.

`app_owns_titlebar_drag` defaults to `false`. Leave it false when relying on
AppKit's native titlebar dragging. Once it is true, the app must supply the drag
handler. Do not substitute `is_movable: false`: titlebar ownership is independent
of window movability and preserves Window-menu tiling.

Sources at the checked revision:
[WindowOptions](https://github.com/zed-industries/zed/blob/a19e19440d4102668830a9da579c3ee71d2fbf1a/crates/gpui/src/platform.rs#L2653-L2664),
[macOS hit-test callback](https://github.com/zed-industries/zed/blob/a19e19440d4102668830a9da579c3ee71d2fbf1a/crates/gpui_macos/src/window.rs#L2083-L2084),
[AppKit drag ownership](https://github.com/zed-industries/zed/blob/a19e19440d4102668830a9da579c3ee71d2fbf1a/crates/gpui_macos/src/window.rs#L3661-L3679).
Check these APIs against the consumer project's pin.

The options and handler snippets were compile-checked on macOS against GPUI
revision `4c7244790a075e862eeb4e5ccc12d6c8f5da6f7e`. Native interaction checks
are separate; compilation does not establish the behavior listed below.

A small native probe at that revision was also exercised through macOS app
automation. Tab reordering kept the window in place, tab-close worked, empty
chrome double-click zoomed/restored once per double-click, tab double-click did
not invoke that action, and Window-menu left tiling worked. Empty-chrome drag
attempts through that automation path did not move the window; the cause remains
unresolved. First-click behavior in an inactive window and the traffic lights
were not verified. Keep these checks in the consumer app's native test pass.

### Platform differences and native verification

- macOS: `WindowControlArea` tags do not control AppKit titlebar dragging at the
  revision above. Use application ownership for interactive custom titlebars.
- Windows: use `WindowControlArea::Drag` for native drag hit-testing and tag
  custom caption buttons with `WindowControlArea::Close`/`Min`/`Max`.
- Linux: use `WindowDecorations::Client` and `window.start_window_move()` for
  client-drawn drag regions, checking backend behavior at the pinned revision.

Headless GPUI pointer tests can verify tab state without exercising AppKit window
movement. Test the running native app with real mouse input:

- Drag a tab: it reorders while the window stays in place.
- Drag empty chrome: the window moves.
- Activate a tab and use tab-close and other controls: their actions work without
  starting a window move, including the first click into an inactive window.
- Double-click empty chrome: the configured native action occurs once; doing so
  on a tab or control does not trigger it.
- Check the traffic lights and Window-menu tiling remain functional.

Some GPUI revisions have shown disappearing traffic lights while a transparent-titlebar window is
unfocused (they reappear on hover). Check whether `window_did_change_key_status` only repositions them
when active before applying a workaround.
App-side workaround: `cx.observe_window_activation(...)` → `window.set_traffic_light_position(...)`,
deferring one frame (`window.on_next_frame`) if it races.

## Reacting to OS appearance (light/dark)

Entity constructors have no `Window`, and appearance lives on the window. Pattern:

- Resolve the initial palette inside `open_window`'s callback (a real `Window` exists there) from
  `window.appearance()`.
- In the root view's first `render`, lazily create and store an `Option<Subscription>` from
  `window.observe_window_appearance(...)`; the callback re-resolves the palette (typically stored in a
  `Global`) and calls `cx.refresh_windows()` to repaint everything.

The same lazy-subscription-in-first-render trick applies to `cx.observe_window_activation` (e.g. pausing
a cursor-blink timer while the window is inactive).
