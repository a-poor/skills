# Building tables on raw gpui & Zed's `ui::Table` architecture

For when gpui-component isn't an option, for variable-height rows, or to understand the
mechanics. Verified against Zed `crates/ui/src/components/data_table.rs` and
`redistributable_columns.rs`, gpui `elements/uniform_list.rs`, and gpui-component
`crates/base/src/virtual_list.rs`.

**License note first**: Zed's `ui` crate is **GPL-3.0-or-later**. Read it, learn from
it, describe its patterns — but don't copy its source into a non-GPL project. gpui
itself is Apache-2.0; gpui-component (and its `gpui-base` crate) are Apache-2.0.

## Zed's `ui::Table` in one page

Zed's table (flagship consumer: the keymap editor) is a `RenderOnce` builder — a good
map of which problems exist and their minimal solutions:

```rust
Table::new(COLS)                              // column count is asserted per row
    .interactable(&self.table_interaction_state)  // Entity<TableInteractionState>:
                                              //   focus handle + vertical UniformListScrollHandle
                                              //   + horizontal ScrollHandle + scrollbars
    .striped()
    .width_config(ColumnWidthConfig::redistributable(self.current_widths.clone()))
    .header(vec!["", "Action", "Arguments", "Keystrokes", "Context", "Source"])
    .uniform_list("keymap-table", row_count,
        cx.processor(move |this, range: Range<usize>, window, cx| {
            range.map(|ix| /* Vec<AnyElement>, one per column */).collect()
        }))
```

Three row backends: eager `Vec` rows (`.row(...)` calls), `uniform_list` (uniform
heights, big data), and `variable_row_height_list(row_count, ListState, render_row_fn)`
(gpui's `list()` underneath — for multiline/CSV-ish content; slower, measures each row).

Three column-width models — a genuinely useful taxonomy when designing any table UI:

| `ColumnWidthConfig` | Drag semantics | Table width |
|---|---|---|
| `Static { Auto }` | none — every col `flex_1` | container |
| `Static { Explicit(widths) }` | none — fixed `DefiniteLength`s | fixed or container |
| `Redistributable(state)` | dragging a divider moves space **between neighbors**; total width constant (panel-style, keymap editor) | fixed |
| `Resizable(state)` | dragging changes that column's absolute width; **table grows/shrinks** (spreadsheet-style) | sum of columns → horizontal scroll |

Other transferable pieces: `pin_cols(n)` (frozen left columns), `column_filter`
(hide-columns mask; static-width variants redistribute the hidden width), `map_row`
(wrap/replace a row element — selection styling, drag targets), `empty_table_callback`,
double-click a divider to reset a column.

## The mechanics worth stealing (pattern by pattern)

### Cell style baseline

Every cell: explicit width or `flex_1`, plus `overflow_hidden` + `whitespace_nowrap` +
`text_ellipsis`, plus small horizontal padding. Rows: `.flex().flex_row()` (not
`h_flex()`, which injects `items_center`).

### Horizontal scrolling, header and rows in lockstep

The core trick (used for Zed's pinned layout): give the header's scrollable strip and
**every row's** scrollable strip their own `overflow_x_scroll()` div, all tracking the
**same `ScrollHandle`**:

```rust
// one handle on the view/state:
horizontal_scroll_handle: ScrollHandle::new(),

// in the header AND in each row:
div().id(("row-scroll", row_ix))
    .flex_grow_1()
    .overflow_x_scroll()
    .track_scroll(&self.horizontal_scroll_handle)   // shared → lockstep
    .restrict_scroll_to_axis()                      // let vertical wheel reach the uniform_list
    .child(div().flex().flex_row().children(scrollable_cells))
```

gpui keeps trackers of one handle in sync natively — no per-scroll re-render, no manual
offset math. Pinned columns are simply cells rendered *before* this strip in the same
row flex (`flex_shrink_0`), so row heights stay consistent across frozen and scrolling
sections.

Simpler alternative when nothing is pinned: make the `uniform_list` itself scroll
horizontally with `.with_horizontal_sizing_behavior(ListHorizontalSizingBehavior::Unconstrained)`
(list + items take the widest item's width), and render the header inside an
`overflow_x_scroll` div tracking the list's x offset.

### Column virtualization (hundreds/thousands of columns)

`uniform_list` virtualizes one axis. For the second axis use gpui-component's
`virtual_list` (Apache-2.0, exported as `gpui_component::{h_virtual_list, v_virtual_list}`,
lives in the `gpui-base` crate) — like `uniform_list` but **per-item sizes**:

```rust
let col_widths: Rc<Vec<Size<Pixels>>> = /* width per column, height ignored */;
h_virtual_list(cx.entity(), ("row", row_ix), col_widths,
    move |this, visible_cols: Range<usize>, window, cx| {
        visible_cols.map(|col_ix| render_cell(this, row_ix, col_ix)).collect()
    })
.track_scroll(&self.h_scroll_handle)      // VirtualListScrollHandle, shared across rows
```

This is exactly how `DataTable` does 2-axis virtualization: `uniform_list` of rows, each
row an `h_virtual_list` of cells, one shared horizontal handle. If you need that
combination, seriously consider just using `DataTable`.

### Column resizing

Zed's approach, reduced: an absolutely-positioned overlay of 1px divider hitboxes over
the table; each divider is draggable (`on_drag` with a payload naming the column, global
`on_drag_move::<DraggedColumn>` on the table root doing the math):

- accumulate widths left→right to place dividers;
- on drag: `new_width = drag_x - left_edge_of_column`, clamp to min (and max);
- **compensate for horizontal scroll**: `drag_x -= h_scroll_handle.offset().x`
  (offset is negative when scrolled right);
- redistribute-style: give the delta to the neighbor instead of the total;
- double-click divider/header → reset to initial width;
- store widths in an entity (`Entity<WidthsState>`) so header, rows, and overlay all
  read one source; `cx.notify()` on change.

### Variable row heights

`DataTable` can't do them (uniform_list measures one row and multiplies). Use gpui's
`list()`/`ListState` as the body — items are measured individually. Costs: slower,
no built-in second-axis virtualization, and horizontal alignment still comes from the
shared-widths rule. Zed's `Table::variable_row_height_list` is precisely this. For
mostly-uniform data with occasional tall cells, prefer clamping cells to a uniform
height with `text_ellipsis` and showing full content in a tooltip/detail pane — much
cheaper.

### Sticky group rows

For section headers that pin to the top while their section scrolls (file trees, grouped
result sets): Zed's `sticky_items` (`crates/ui/src/components/sticky_items.rs`) is a
`UniformListDecoration` — a compute_fn picks the "current" group for the visible range,
a render_fn paints it floating over the list. Same idea is portable: any
`UniformListDecoration` can paint overlays given the visible range.

### Focus & keyboard

Put one `FocusHandle` on the table container (`.track_focus`), a `key_context`
(e.g. `"Table"`), bind arrow/page keys to actions, and translate actions into
selection-index changes + `scroll_to_item`. Both Zed (`TableInteractionState`) and
gpui-component (`TableState`) hang focus + both scroll handles + selection on one state
entity — do the same; it keeps `render` a pure function of that entity.
