# Simple tables: flex construction & the stateless `Table`

For small, non-virtualized tables — the `<table>` analog. Verified against
gpui-component `crates/ui/src/table/table.rs` (v0.5.x) and Zed `crates/ui/src/components/data_table.rs`.

## Hand-rolled flex table (no dependencies beyond gpui)

The pattern every library uses internally — one widths array, applied twice:

```rust
const WIDTHS: [f32; 3] = [80., 240., 120.];   // or Vec<Pixels> on the view for resizability

fn cell(width: f32, child: impl IntoElement) -> Div {
    div()
        .w(px(width))
        .flex_shrink_0()          // don't let flex negotiate the width away
        .px_2()
        .py_1()
        .overflow_hidden()
        .whitespace_nowrap()
        .text_ellipsis()          // truncate, don't wrap — wrapping breaks row height
        .child(child)
}

fn row(cols: [AnyElement; 3], striped: bool) -> Div {
    div()
        .flex()
        .flex_row()               // NOT h_flex(): it sneaks in items_center(), decide that yourself
        .w_full()
        .when(striped, |d| d.bg(rgba(0xffffff0d)))
        .border_b_1()
        .children(cols.into_iter().zip(WIDTHS).map(|(c, w)| cell(w, c)))
}

// header: same `cell` + same widths, different bg/font — that's the whole alignment story
```

Variants for the width column of the table:

- **Fixed px per column** (above) — supports horizontal overflow + resize later.
- **Equal shares**: give each cell `.flex_1()` and no width — columns split the container
  evenly. This is Zed's `ColumnWidthConfig::auto()`.
- **Weighted shares**: `.flex_basis(relative(weight))` per column (this is how
  gpui-component's stateless table does col_span).

Last-cell tip: give the final column `.flex_1().min_w(px(min))` instead of a fixed width
so the table absorbs container-width slack gracefully.

## gpui-component stateless `Table` (shadcn-style)

Composable, `RenderOnce`, **no virtualization, no column management** — purely a styled
`<table>`:

```rust
use gpui_component::table::*;   // Table, TableHeader, TableBody, TableFooter,
                                // TableRow, TableHead, TableCell, TableCaption

Table::new()
    .small()                                    // Sizable: propagates cell padding to children
    .child(TableHeader::new().child(
        TableRow::new()
            .child(TableHead::new().child("Name"))
            .child(TableHead::new().col_span(2).text_center().child("Contact")),
    ))
    .child(TableBody::new().children(rows.iter().enumerate().map(|(ix, r)|
        TableRow::new()
            .child(TableCell::new().child(r.name.clone()))
            .child(TableCell::new().child(r.email.clone()))
            .child(TableCell::new().text_right().child(r.phone.clone())),
    )))
    .child(TableCaption::new().child("A list of recent invoices."))
```

Mechanics to know:

- Cells default to `flex_shrink_1` + `flex_basis(relative(col_span))` — i.e. weighted
  equal shares. Setting an explicit width via `Styled` (`.w(...)` on the cell) opts that
  cell out of the share system.
- Every cell has `min_w(px(100.) * col_span)` (MIN_CELL_WIDTH is 100px). Narrow "icon"
  columns need an explicit `.w(...)` to defeat it.
- `col_span(n)` = flex-basis weight n + n×min-width. It does not consult other rows —
  spans only *look* right if your spans per row sum consistently.
- Alignment: `.text_center()`/`.text_right()` on `TableHead`/`TableCell` (implemented as
  justify, so it works for any child, not just text).
- Theming comes from `cx.theme().tokens.table/table_head/table_foot` — needs
  `gpui_component::init(cx)`.

Use it when rows fit on screen (settings pages, small summaries, invoices). Past a
couple hundred rows, or the moment you need resize/sort/selection, switch to `DataTable`
(data-table.md).

## Long flat list, few columns: raw `uniform_list`

If you need scale but zero column features, skip `DataTable` and use `uniform_list`
directly with the hand-rolled row above (see the base gpui skill's list-scroll reference
for handles/gotchas). The table-specific additions:

- Render the header row **outside** the list, from the same widths array.
- Rows must be uniform height — enforce `whitespace_nowrap` + `text_ellipsis` in cells.
- Wide rows / horizontal scroll: `.with_horizontal_sizing_behavior(ListHorizontalSizingBehavior::Unconstrained)`
  makes the list adopt the widest item's width and scroll on x. The header then needs its
  x-offset synced to the list's scroll handle — at that point you're rebuilding a real
  table; see diy-and-zed.md for the sync patterns, or just use `DataTable`.
