# Actions & Keybindings

**Contents:** [Overview](#overview) · [Quick Start](#quick-start) · [Key Formats](#key-formats) · [Action Naming](#action-naming) · [Context-Aware Bindings](#context-aware-bindings) · [Best Practices](#best-practices)

## Overview

Actions provide declarative keyboard-driven UI interactions in GPUI.

API signatures and modifier behavior below were checked against Zed revision
`a19e19440d4102668830a9da579c3ee71d2fbf1a`. Check the project's pinned revision
before adapting the examples.

The simple actions, parameterized actions, and listener examples were also
compile-checked with minimal enclosing types on GPUI revision
`4c7244790a075e862eeb4e5ccc12d6c8f5da6f7e` (macOS). The newer OS-aware
`secondary` path was source-checked, not exercised by that compilation.

**Key Concepts:**
- Define actions with `actions!` macro or `#[derive(Action)]`
- Bind keys with `cx.bind_keys()`
- Handle with `.on_action()` on elements
- Context-aware via `key_context()`

## Quick Start

### Simple Actions

```rust
use gpui::{App, Context, IntoElement, KeyBinding, Render, Window, actions, div, prelude::*};

actions!(editor, [MoveUp, MoveDown, Save, Quit]);

const CONTEXT: &str = "Editor";

pub fn init(cx: &mut App) {
    // Explicit native application shortcuts also work on revisions without `secondary`.
    #[cfg(target_os = "macos")]
    let (save_key, quit_key) = ("cmd-s", "cmd-q");
    #[cfg(not(target_os = "macos"))]
    let (save_key, quit_key) = ("ctrl-s", "ctrl-q");

    cx.bind_keys([
        KeyBinding::new("up", MoveUp, Some(CONTEXT)),
        KeyBinding::new("down", MoveDown, Some(CONTEXT)),
        KeyBinding::new(save_key, Save, Some(CONTEXT)),
        KeyBinding::new(quit_key, Quit, Some(CONTEXT)),
    ]);
}

impl Render for Editor {
    fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        div()
            .key_context(CONTEXT)
            .on_action(cx.listener(Self::move_up))
            .on_action(cx.listener(Self::move_down))
            .on_action(cx.listener(Self::save))
    }
}

impl Editor {
    fn move_up(&mut self, _: &MoveUp, _window: &mut Window, cx: &mut Context<Self>) {
        // Handle move up
        cx.notify();
    }

    fn move_down(&mut self, _: &MoveDown, _window: &mut Window, cx: &mut Context<Self>) {
        cx.notify();
    }

    fn save(&mut self, _: &Save, _window: &mut Window, cx: &mut Context<Self>) {
        // Save logic
        cx.notify();
    }
}
```

`cx.listener` takes `Fn(&mut Self, &E, &mut Window, &mut Context<Self>)`, where
`E` is the concrete action or event type;
keep the window argument even when unused. These are fragments of an existing
`Editor`: attach its focus handle with `.track_focus(...)` and give it focus so
keyboard actions reach this subtree (see [focus-handle.md](focus-handle.md)).

### Actions with Parameters

```rust
use gpui::Action;
use schemars::JsonSchema;
use serde::Deserialize;

#[derive(Clone, PartialEq, Action, Deserialize, JsonSchema)]
#[action(namespace = editor)]
pub struct InsertText {
    pub text: String,
}

#[derive(Action, Clone, PartialEq, Eq)]
#[action(namespace = editor, no_json)]
pub struct Digit(pub u8);

cx.bind_keys([
    KeyBinding::new("0", Digit(0), Some(CONTEXT)),
    KeyBinding::new("1", Digit(1), Some(CONTEXT)),
    // ...
]);

impl Editor {
    fn on_digit(&mut self, action: &Digit, _window: &mut Window, cx: &mut Context<Self>) {
        self.insert_digit(action.0, cx);
    }
}

// Inside Editor::render:
div().on_action(cx.listener(Self::on_digit))
```

JSON-loadable actions require both `Deserialize` and `JsonSchema`; use the
versions compatible with the pinned GPUI dependency. `#[action(no_json)]`
allows programmatic bindings without those derives.

## Key Formats

```rust
// Modifiers
"cmd-s"         // Platform modifier: Command on macOS, Super/Windows elsewhere
"super-s"       // Alias of cmd-s (as is win-s)
"ctrl-c"        // Literal Control, including on macOS
"secondary-s"   // OS-aware parsing only: Command on macOS, Control elsewhere
"alt-f"         // Alt
"shift-tab"     // Shift
"cmd-ctrl-f"    // Multiple modifiers

// Keys
"a-z", "0-9"    // Letters and numbers
"f1-f12"        // Function keys
"up", "down", "left", "right"
"enter", "escape", "space", "tab"
"backspace", "delete"
"-", "=", "[", "]", etc.  // Special characters
```

At the revision above, `KeyBinding::new` uses `Keystroke::parse` without an OS.
Passing `"secondary-s"` to it fails parsing and panics. Use explicit platform
bindings as in the quick start, or the OS-aware `KeyBinding::load(..., cx)` path,
which calls `Keystroke::parse_with_os(..., cx.platform_info().os)`. Older revisions
have a different `load` signature and may not support `secondary` at all.

Sources: [listener signature](https://github.com/zed-industries/zed/blob/a19e19440d4102668830a9da579c3ee71d2fbf1a/crates/gpui/src/app/context.rs#L241-L250),
[modifier parser](https://github.com/zed-industries/zed/blob/a19e19440d4102668830a9da579c3ee71d2fbf1a/crates/gpui/src/platform/keystroke.rs#L140-L176),
[binding constructors](https://github.com/zed-industries/zed/blob/a19e19440d4102668830a9da579c3ee71d2fbf1a/crates/gpui/src/keymap/binding.rs#L31-L78).

## Action Naming

Prefer verb-noun pattern:

```rust
actions!([
    OpenFile,      // ✅ Good
    CloseWindow,   // ✅ Good
    ToggleSidebar, // ✅ Good
    Save,          // ✅ Good (common exception)
]);
```

## Context-Aware Bindings

```rust
const EDITOR_CONTEXT: &str = "Editor";
const MODAL_CONTEXT: &str = "Modal";

// Same key, different contexts
cx.bind_keys([
    KeyBinding::new("escape", CloseModal, Some(MODAL_CONTEXT)),
    KeyBinding::new("escape", ClearSelection, Some(EDITOR_CONTEXT)),
]);

// Set context on element
div()
    .key_context(EDITOR_CONTEXT)
    .child(editor_content)
```

## Best Practices

### ✅ Use Contexts

```rust
// ✅ Good: Context-aware
div()
    .key_context("MyComponent")
    .on_action(cx.listener(Self::handle))
```

### ✅ Name Actions Clearly

```rust
// ✅ Good: Clear intent
actions!([
    SaveDocument,
    CloseTab,
    TogglePreview,
]);
```

### ✅ Handle with Listeners

```rust
// ✅ Good: Proper handler naming
impl MyComponent {
    fn on_action_save(&mut self, _: &Save, _window: &mut Window, cx: &mut Context<Self>) {
        // Handle save
        cx.notify();
    }
}

div().on_action(cx.listener(Self::on_action_save))
```

