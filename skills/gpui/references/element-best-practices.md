# Element Best Practices

**Contents:** [State Management](#state-management) · [Performance Considerations](#performance-considerations) · [Interaction Handling](#interaction-handling) · [Layout Strategies](#layout-strategies) · [Error Handling](#error-handling) · [Testing Element Implementations](#testing-element-implementations) · [Common Pitfalls](#common-pitfalls) · [Performance Checklist](#performance-checklist)

The abbreviated snippets below illustrate design choices. For a complete,
compiled implementation and draw test, use [SimpleText](element-examples.md).

## State Management

### Using Associated Types Effectively

**Good:** Use associated types to pass meaningful data between phases

```rust
// Good: Structured state with type safety
type RequestLayoutState = (StyledText, Vec<ChildLayout>);
type PrepaintState = (Hitbox, Vec<ChildBounds>);
```

**Bad:** Using empty state when you need data

```rust
// Bad: No state when you need to pass data
type RequestLayoutState = ();
type PrepaintState = ();
// Now you can't pass layout info to paint phase!
```

### Managing Complex State

For elements with complex state, create dedicated structs:

```rust
// Good: Dedicated struct for complex state
pub struct TextElementState {
    pub styled_text: StyledText,
    pub text_layout: TextLayout,
    pub child_states: Vec<ChildState>,
}

type RequestLayoutState = TextElementState;
```

**Benefits:**
- Clear documentation of state structure
- Easy to extend
- Type-safe access

### State Lifecycle

**Golden Rule:** State flows in one direction through the phases

```
request_layout → RequestLayoutState →
prepaint → PrepaintState →
paint
```

**Don't:**
- Make rendering itself change persistent application state; mutate the owning
  entity from an event/update callback and notify it there. The element methods
  may mutate their own transient rendering state.
- Retain borrowed context or element references in stored callbacks. Associated
  state is owned, then passed by mutable reference to subsequent phases.

## Performance Considerations

### Minimize Allocations in Paint Phase

**Critical:** Paint phase is called every frame during animations. Minimize allocations.

**Good:** Pre-allocate in `request_layout` or `prepaint`

```rust
impl Element for MyElement {
    fn request_layout(&mut self, .., window: &mut Window, cx: &mut App)
        -> (LayoutId, Vec<StyledText>)
    {
        // Allocate once during layout
        let styled_texts = self.children
            .iter()
            .map(|child| StyledText::new(child.text.clone()))
            .collect();

        (layout_id, styled_texts)
    }

    fn paint(&mut self, .., styled_texts: &mut Vec<StyledText>, ..) {
        // Just use pre-allocated styled_texts
        for text in styled_texts {
            text.paint(..);
        }
    }
}
```

**Bad:** Allocate in `paint` phase

```rust
fn paint(&mut self, ..) {
    // Bad: Allocation in paint phase!
    let styled_texts: Vec<_> = self.children
        .iter()
        .map(|child| StyledText::new(child.text.clone()))
        .collect();
}
```

### Cache Expensive Computations

Use memoization for expensive operations:

```rust
pub struct CachedElement {
    // Cache key
    last_text: Option<SharedString>,
    last_width: Option<Pixels>,

    // Cached result
    cached_layout: Option<TextLayout>,
}

impl Element for CachedElement {
    fn request_layout(&mut self, .., window: &mut Window, cx: &mut App)
        -> (LayoutId, TextLayout)
    {
        let current_width = window.bounds().width();

        // Check if cache is valid
        if self.last_text.as_ref() != Some(&self.text)
            || self.last_width != Some(current_width)
            || self.cached_layout.is_none()
        {
            // Recompute expensive layout
            self.cached_layout = Some(self.compute_text_layout(current_width));
            self.last_text = Some(self.text.clone());
            self.last_width = Some(current_width);
        }

        // Use cached layout
        let layout = self.cached_layout.as_ref().unwrap();
        (layout_id, layout.clone())
    }
}
```

### Lazy Child Rendering

Only render visible children in scrollable containers:

```rust
fn paint(&mut self, .., bounds: Bounds<Pixels>, paint_state: &mut Self::PrepaintState, ..) {
    for (i, child) in self.children.iter_mut().enumerate() {
        let child_bounds = paint_state.child_bounds[i];

        // Only paint visible children
        if self.is_visible(&child_bounds, &bounds) {
            child.paint(..);
        }
    }
}

fn is_visible(&self, child_bounds: &Bounds<Pixels>, container_bounds: &Bounds<Pixels>) -> bool {
    child_bounds.bottom() >= container_bounds.top() &&
    child_bounds.top() <= container_bounds.bottom()
}
```

## Interaction Handling

### Proper Event Bubbling

Always check phase and bounds before handling events:

```rust
fn paint(&mut self, .., prepaint: &mut Self::PrepaintState, window: &mut Window, cx: &mut App) {
    window.on_mouse_event({
        let hitbox = prepaint.hitbox.clone();
        // The closure is 'static — it cannot borrow &mut self, so capture a
        // cloned Entity holding the state to mutate.
        let state = self.state.clone();
        move |event: &MouseDownEvent, phase, window, cx| {
            // Check phase first
            if !phase.bubble() {
                return;
            }

            // Check if event is within bounds
            if !hitbox.is_hovered(window) {
                return;
            }

            // Handle event
            state.update(cx, |state, cx| {
                state.handle_click(event);
                cx.notify();
            });

            // Stop propagation if handled
            cx.stop_propagation();
        }
    });
}
```

**Don't forget:**
- Check `phase.bubble()` or `phase.capture()` as appropriate
- Check hitbox hover state or bounds
- Call `cx.stop_propagation()` if you handle the event

### Hitbox Management

Create hitboxes in `prepaint` phase, not `paint`:

**Good:**

```rust
fn prepaint(&mut self, .., bounds: Bounds<Pixels>, window: &mut Window, ..) -> Hitbox {
    // Create hitbox in prepaint
    window.insert_hitbox(bounds, HitboxBehavior::Normal)
}

fn paint(&mut self, .., hitbox: &mut Hitbox, window: &mut Window, ..) {
    // Use hitbox in paint
    window.set_cursor_style(CursorStyle::PointingHand, hitbox);
}
```

**Hitbox Behaviors:**

```rust
// Normal (default): tracks hover; doesn't affect mouse handling for other hitboxes
HitboxBehavior::Normal

// BlockMouse: hitboxes behind this one are never hovered — what `.occlude()` sets
HitboxBehavior::BlockMouse

// BlockMouseExceptScroll: blocks everything behind except scroll-wheel handling
HitboxBehavior::BlockMouseExceptScroll
```

### Cursor Style Guidelines

Set appropriate cursor styles for interactivity cues:

```rust
// Text selection
window.set_cursor_style(CursorStyle::IBeam, &hitbox);

// Clickable elements (desktop convention: use default, not pointing hand)
window.set_cursor_style(CursorStyle::Arrow, &hitbox);

// Links (web convention: use pointing hand)
window.set_cursor_style(CursorStyle::PointingHand, &hitbox);

// Resizable edges
window.set_cursor_style(CursorStyle::ResizeLeftRight, &hitbox);
```

**Desktop vs Web Convention:**
- Desktop apps: Use `Arrow` for buttons
- Web apps: Use `PointingHand` for links only

## Layout Strategies

### Fixed Size Elements

For elements with known, unchanging size:

```rust
fn request_layout(&mut self, .., window: &mut Window, cx: &mut App) -> (LayoutId, ()) {
    let layout_id = window.request_layout(
        Style {
            size: size(px(200.), px(100.)),
            ..default()
        },
        vec![], // No children
        cx
    );
    (layout_id, ())
}
```

### Content-Based Sizing

For elements sized by their content:

```rust
fn request_layout(&mut self, .., window: &mut Window, cx: &mut App)
    -> (LayoutId, Size<Pixels>)
{
    // Measure content
    let text_bounds = self.measure_text(window);
    let padding = px(16.);

    let layout_id = window.request_layout(
        Style {
            size: size(
                text_bounds.width() + padding * 2.,
                text_bounds.height() + padding * 2.,
            ),
            ..default()
        },
        vec![],
        cx
    );

    (layout_id, text_bounds)
}
```

### Flexible Layouts

For elements that adapt to available space:

```rust
fn request_layout(&mut self, .., window: &mut Window, cx: &mut App)
    -> (LayoutId, Vec<LayoutId>)
{
    let mut child_layout_ids = Vec::new();

    for child in &mut self.children {
        let layout_id = child.request_layout(window, cx);
        child_layout_ids.push(layout_id);
    }

    let layout_id = window.request_layout(
        Style {
            flex_direction: FlexDirection::Row,
            gap: size(px(8.), px(8.)).into(),
            size: Size {
                width: relative(1.0),  // Fill parent width
                height: auto(),        // Auto height
            },
            ..default()
        },
        child_layout_ids.clone(),
        cx
    );

    (layout_id, child_layout_ids)
}
```

## Error Handling

### Graceful Degradation

Handle errors in application-specific loading or shaping operations before
constructing the element, and provide a fallback when appropriate.
`Element::request_layout` returns a tuple, not a `Result`; do not match it as
`Ok`/`Err`.

### Defensive bounds checking

Validate selection indices against UTF-8 character boundaries, not just byte
length. Normalize reversed selections, handle empty ranges, and use the shaped
line geometry for painting. The checked `TextLayout` API has no
`rects_for_range` method; selection rectangles require application logic.

## Testing Element Implementations

Use the [complete headless draw test](element-examples.md#testing-the-rendering-phases)
to exercise layout, prepaint, and paint before checking final geometry.
For interactions, draw the control and dispatch input through `VisualTestContext`;
assert the owning entity's state and event effects. Test native behavior in a
visible app as described in [test.md](test.md#running-app-and-native-verification).

## Common Pitfalls

### ❌ Storing Layout State in Element Struct

**Bad:**

```rust
pub struct MyElement {
    id: ElementId,
    // Bad: This should be in RequestLayoutState
    cached_layout: Option<TextLayout>,
}
```

**Good:**

```rust
pub struct MyElement {
    id: ElementId,
    text: SharedString,
}

type RequestLayoutState = TextLayout; // Good: State in associated type
```

### ❌ Mutating Element in Paint Phase

**Bad:**

```rust
fn paint(&mut self, ..) {
    self.counter += 1; // Bad: Mutating element in paint
}
```

**Good:**

```rust
fn paint(&mut self, .., window: &mut Window, cx: &mut App) {
    // on_mouse_event closures are 'static: they cannot borrow &mut self.
    // Store mutable state in an Entity and update it from the handler.
    let state = self.state.clone(); // Entity<CounterState> held by the element
    window.on_mouse_event(move |event: &MouseDownEvent, phase, window, cx| {
        if phase.bubble() {
            state.update(cx, |state, cx| {
                state.counter += 1;
                cx.notify(); // Schedule re-render
            });
        }
    });
}
```

### ❌ Creating Hitboxes in Paint Phase

**Bad:**

```rust
fn paint(&mut self, .., bounds: Bounds<Pixels>, window: &mut Window, ..) {
    // Bad: Creating hitbox in paint
    let hitbox = window.insert_hitbox(bounds, HitboxBehavior::Normal);
}
```

**Good:**

```rust
fn prepaint(&mut self, .., bounds: Bounds<Pixels>, window: &mut Window, ..) -> Hitbox {
    // Good: Creating hitbox in prepaint
    window.insert_hitbox(bounds, HitboxBehavior::Normal)
}
```

### ❌ Ignoring Event Phase

**Bad:**

```rust
window.on_mouse_event(move |event, phase, window, cx| {
    // Bad: Not checking phase
    handle_click(event); // (state mutation via a cloned Entity, as above)
});
```

**Good:**

```rust
window.on_mouse_event(move |event, phase, window, cx| {
    // Good: Checking phase
    if !phase.bubble() {
        return;
    }
    handle_click(event); // (state mutation via a cloned Entity, as above)
});
```

## Performance Checklist

Before shipping an element implementation, verify:

- [ ] No allocations in `paint` phase (except event handlers)
- [ ] Expensive computations are cached/memoized
- [ ] Only visible children are rendered in scrollable containers
- [ ] Hitboxes created in `prepaint`, not `paint`
- [ ] Event handlers check phase and bounds
- [ ] Layout state is passed through associated types, not stored in element
- [ ] Element implements proper error handling with fallbacks
- [ ] Tests cover layout calculations and interactions
