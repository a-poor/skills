# gpui-component `DataTable` — core setup

The full-featured virtualized grid. Verified against gpui-component v0.5.x
`crates/ui/src/table/{delegate,column,state,data_table}.rs`.

Architecture: you implement **`TableDelegate`** (data + cell rendering) on your own
struct, wrap it in a **`TableState<D>`** entity that you own, and render a
**`DataTable`** element (cheap `RenderOnce` wrapper) each frame. Rows are virtualized
with `uniform_list`; columns are virtualized per-row with a horizontal `virtual_list`.
Both axes handle very large counts (the demo runs 1M rows and hundreds of columns).

## Minimal working table

```rust
use gpui_component::table::{Column, DataTable, TableDelegate, TableState};

struct Orders {
    rows: Vec<Order>,
    columns: Vec<Column>,
}

impl TableDelegate for Orders {
    fn columns_count(&self, _: &App) -> usize { self.columns.len() }
    fn rows_count(&self, _: &App) -> usize { self.rows.len() }

    // Called only on prepare/refresh — not per frame. Cheap clone is fine.
    fn column(&self, col_ix: usize, _: &App) -> Column {
        self.columns[col_ix].clone()
    }

    fn render_td(
        &mut self, row_ix: usize, col_ix: usize,
        _: &mut Window, cx: &mut Context<TableState<Self>>,
    ) -> impl IntoElement {
        let row = &self.rows[row_ix];
        match self.columns[col_ix].key.as_ref() {
            "id"     => row.id.to_string().into_any_element(),
            "name"   => row.name.clone().into_any_element(),
            "total"  => div().text_color(cx.theme().green)
                            .child(format!("{:.2}", row.total)).into_any_element(),
            _ => "".into_any_element(),
        }
    }
}

// In your view's constructor:
let table: Entity<TableState<Orders>> =
    cx.new(|cx| TableState::new(delegate, window, cx));

// In render():
DataTable::new(&self.table)
    .stripe(true)        // alternating row bg (default false)
    .bordered(true)      // rounded outer border (default true)
    .small()             // row height via Sizable; or .with_size(px(48.))
    .scrollbar_visible(true, true)
```

Give the table's container a constrained size (`flex_1().min_h_0()` chain or fixed
height) — the vertical `uniform_list` scrolls itself, same rule as any gpui list.

Requires `gpui_component::init(cx)` at startup (theme + `"DataTable"` key bindings).

## `Column` — per-column configuration

Identity + geometry + capabilities, built fluently. Match on `column.key` in
`render_td`, don't hardcode indices — users can reorder columns.

```rust
Column::new("symbol", "Symbol")   // key (stable id), display name
    .width(px(80.))               // default 100px; f32 works too via Into<Pixels>
    .min_width(px(40.))           // default 20px  — resize clamps
    .max_width(px(300.))          // default f32::MAX
    .sortable()                   // sort = Some(ColumnSort::Default); or .ascending()/.descending()
    .text_right()                 // or .text_center(); default left
    .fixed_left()                 // pin to the left edge under horizontal scroll
    .resizable(false)             // default true
    .movable(false)               // default true (drag header to reorder)
    .selectable(false)            // default true; false = excluded from col/cell selection (action columns)
    .paddings(px(0.))             // or .p_0(); override the size-derived cell padding
```

Widths are **always explicit pixels** — there is no auto/flex column in `DataTable`
(that's the price of column virtualization). Compute data-driven widths yourself before
building the `Column`s.

## `TableState` — feature switches & control surface

Builder-style at creation (each also exists as a `pub` field for later toggling +
`cx.notify()`):

```rust
TableState::new(delegate, window, cx)
    .row_selectable(true)     // default true
    .col_selectable(true)     // default true
    .cell_selectable(false)   // default false — see data-table-features.md
    .row_header(true)         // row-selector gutter in cell mode
    .sortable(true)           // master switch; column also needs .sortable()
    .col_resizable(true)
    .col_movable(true)
    .loop_selection(true)     // arrow-key wrap at ends
```

Control methods (call inside `table.update(cx, |state, cx| ...)`):

- `delegate()` / `delegate_mut()` — reach your data. After mutating rows, `cx.notify()`.
- `refresh(cx)` — re-reads `columns_count`/`column()` and rebuilds column groups +
  header layout. **Required after adding/removing/replacing columns**; plain data
  changes only need `cx.notify()`.
- `scroll_to_row(ix, cx)` / `scroll_to_col(ix, cx)`
- `selected_row/col/cell()`, `set_selected_row/col/cell(...)`, `clear_selection(cx)`
- `visible_range()` → `TableVisibleRange { rows(), cols() }` of what's on screen
- `dump(cx)` → `(Vec<String>, Vec<Vec<String>>)` headers + all cells via `cell_text`

`TableState` is `Focusable` and an `EventEmitter<TableEvent>` — subscribe for
selection/resize/reorder events (data-table-features.md).

## The delegate's optional surface (what exists, so you don't reinvent it)

| Method | Purpose |
|---|---|
| `render_th(col_ix, ...)` | Custom header cell content (default: column name) |
| `render_tr(row_ix, ...) -> Stateful<Div>` | Row wrapper — attach `.id(...)`, `on_click`, per-row styling |
| `render_td(row_ix, col_ix, ...)` | **required** — the cell |
| `group_headers(cx)` | Multi-level grouped header rows (`Vec<Vec<ColumnGroup>>`; spans must sum to `columns_count`) |
| `render_group_th(...)` | Custom group header cell |
| `perform_sort(col_ix, sort, ...)` | Sort your data when a header is clicked |
| `move_column(col_ix, to_ix, ...)` | Commit a header drag-reorder to your `Vec<Column>` |
| `context_menu(row_ix, menu, ...)` | Right-click `PopupMenu` for rows |
| `render_empty(...)` / `loading(cx)` / `render_loading(...)` | Empty & skeleton states |
| `has_more` / `load_more_threshold` / `load_more` | Infinite scroll (features doc) |
| `visible_rows_changed` / `visible_columns_changed` | Viewport hooks — keep them fast |
| `cell_text(row_ix, col_ix, cx)` | Plain-text cell value for export/`dump` |
| `render_last_empty_col(...)` | Trailing filler column (default 12px spacer) |

## Sizing summary

- **Row height**: uniform, derived from the `Size` set on `DataTable` (`.small()`,
  `.large()`, `.with_size(px(48.))`, …). Header rows use the same height. Variable row
  heights are **not supported** — for those see diy-and-zed.md.
- **Column width**: `Column::width` initially; user drags update internal runtime widths
  (and emit `ColumnWidthsChanged`) without touching your `Column`s — persist and re-apply
  them yourself if you want widths to survive restart.
- **Cell padding**: from the table `Size`, unless the column sets `.paddings(...)` —
  then your `render_td`/`render_th` content controls its own padding (useful for
  full-bleed cells like tinted percentage backgrounds).

## Embedding in a scrollable page

Wheel events over the table stay in the table (it installs `ScrollableMask`s); a
`DataTable` inside a scrollable page hands the wheel to the outer scroller only at its
scroll extents or outside its bounds. Working example:
`examples/table_in_scrollable/` in the gpui-component repo.
