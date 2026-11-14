
## When to Use

Use the low-level `Element` trait when:
- Need fine-grained control over layout calculation
- Building complex, performance-critical components
- Implementing custom layout algorithms (masonry, circular, etc.)
- High-level `Render`/`RenderOnce` APIs are insufficient

**Prefer `Render`/`RenderOnce` for:** Simple components, standard layouts, declarative UI

## Quick Start

Start with the complete [SimpleText implementation and draw test](element-examples.md).
It implements all trait methods, keeps a mutable `StyledText` across phases, and
has been compiled and exercised against the stated GPUI pin. Use the
[API reference](element-api.md) for the full method signatures.

## Core Concepts

### Three-Phase Rendering

1. **request_layout**: Calculate sizes and positions, return layout ID and state
2. **prepaint**: Create hitboxes, compute final bounds, prepare for painting
3. **paint**: Render element, set up interactions (mouse events, cursor styles)

### State Flow

```
RequestLayoutState → PrepaintState → paint
```

State flows in one direction through associated types, passed as mutable references between phases.

### Key Operations

- **Layout**: `window.request_layout(style, children, cx)` - Create layout node
- **Hitboxes**: `window.insert_hitbox(bounds, behavior)` - Create interaction area
- **Painting**: `window.paint_quad(...)` - Render visual content
- **Events**: `window.on_mouse_event(handler)` - Handle user input

## Reference Documentation

### Complete API Documentation
- **API**: See [element-api.md](element-api.md) — associated types, hitbox system, event handling, cursor styles
- **Examples**: See [element-examples.md](element-examples.md) — compiled text example; selection and child-management design notes
- **Patterns**: See [element-patterns.md](element-patterns.md) — text, container, interactive, composite, scrollable
- **Best Practices**: See [element-best-practices.md](element-best-practices.md) — performance, state, common pitfalls
- **Advanced**: See [element-advanced.md](element-advanced.md) — masonry/circular layouts, memoization, virtual lists
