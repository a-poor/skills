# `DataTable` features: selection, sorting, filtering, editing, big data

Patterns on top of data-table.md. "Not built in" below means: the library deliberately
leaves it to the delegate — these are the established patterns, not workarounds.

## Selection & events

Three modes (row / column / cell). Keyboard nav (arrows, tab/shift-tab, home/end,
pageup/pagedown, escape) is bound under the `"DataTable"` key context and works at
whichever granularity is active; it requires the table to have focus
(`TableState` is `Focusable`; the `DataTable` element tracks focus itself — click or
`window.focus(&state.focus_handle(cx))`).

```rust
// TableState is an EventEmitter<TableEvent>
cx.subscribe_in(&self.table, window, |this, _table, event: &TableEvent, window, cx| {
    match event {
        TableEvent::SelectRow(row_ix) => { /* single click / keyboard move */ }
        TableEvent::DoubleClickedRow(row_ix) => { /* open detail */ }
        TableEvent::SelectCell(row_ix, col_ix) => { /* cell mode */ }
        TableEvent::DoubleClickedCell(row_ix, col_ix) => { /* start editing */ }
        TableEvent::RightClickedRow(row_ix) => { /* Option<usize>; None = empty area */ }
        TableEvent::RightClickedCell(row_ix, col_ix) => {}
        TableEvent::SelectColumn(col_ix) => {}
        TableEvent::ColumnWidthsChanged(widths) => { /* Vec<Pixels> — persist */ }
        TableEvent::MoveColumn(from_ix, to_ix) => { /* persist order */ }
        TableEvent::ClearSelection => {}
    }
})
```

Cell-selection specifics: enabling `cell_selectable(true)` adds a narrow row-header
gutter on the left (hide with `.row_header(false)`; then clicking the selected cell
again escalates to row selection, if `row_selectable`). Mark action/button columns
`Column::selectable(false)` so clicks there don't fight the selection system.

## Sorting

Two switches must agree: `TableState.sortable` (master, default true) and
`Column::sortable()` per column. The table renders the indicator and flips the
`ColumnSort`; *you* reorder the data:

```rust
fn perform_sort(&mut self, col_ix: usize, sort: ColumnSort,
                _: &mut Window, _: &mut Context<TableState<Self>>) {
    let key = self.columns[col_ix].key.clone();
    match (key.as_ref(), sort) {
        ("name", ColumnSort::Ascending)  => self.rows.sort_by(|a, b| a.name.cmp(&b.name)),
        ("name", ColumnSort::Descending) => self.rows.sort_by(|a, b| b.name.cmp(&a.name)),
        (_, ColumnSort::Default)         => self.rows.sort_by_key(|r| r.id), // "unsorted"
        // float keys: total_cmp, not partial_cmp().unwrap()
        ("total", ColumnSort::Ascending) => self.rows.sort_by(|a, b| a.total.total_cmp(&b.total)),
        _ => {}
    }
}
```

Selection indices are row indices — after sorting (or filtering), a remembered
`selected_row` points at a different record. Either clear the selection or re-locate the
record by id and `set_selected_row`.

## Filtering (not built in — delegate-side)

Keep the full dataset plus a visible index; everything the table asks for goes through
the index:

```rust
struct Orders {
    all: Vec<Order>,
    visible: Vec<usize>,      // indices into `all`
    query: String,
    columns: Vec<Column>,
}
impl Orders {
    fn apply_filter(&mut self) {
        self.visible = self.all.iter().enumerate()
            .filter(|(_, o)| self.query.is_empty() || o.name.contains(&self.query))
            .map(|(i, _)| i).collect();
    }
    fn row(&self, row_ix: usize) -> &Order { &self.all[self.visible[row_ix]] }
}
// rows_count => self.visible.len();  render_td/cell_text => self.row(row_ix)
```

On query change (e.g. from an `InputState` you keep next to the table):

```rust
self.table.update(cx, |table, cx| {
    table.delegate_mut().query = q;
    table.delegate_mut().apply_filter();
    table.clear_selection(cx);          // indices shifted
    table.scroll_to_row(0, cx);
    cx.notify();
});
```

Sort the `visible` index (comparing through `all`) so sort and filter compose. For an
empty result, `render_empty` is shown automatically.

## Cell editing (not built in — two established patterns)

**A. Edit-in-place on double-click.** Keep one editing slot + one `InputState` in the
delegate; swap the cell's renderer while it's being edited:

```rust
struct Orders {
    editing: Option<(usize, usize, Entity<InputState>)>,   // row, col, editor
    ...
}

// on TableEvent::DoubleClickedCell(row, col):
let input = cx.new(|cx| InputState::new(window, cx).default_value(current_text));
window.focus(&input.focus_handle(cx));                  // so typing lands in the editor
table.update(cx, |t, _| t.delegate_mut().editing = Some((row, col, input)));

// in render_td:
if let Some((r, c, input)) = &self.editing {
    if (*r, *c) == (row_ix, col_ix) {
        return Input::new(input).into_any_element();    // Input is a thin view over InputState
    }
}
// commit: cx.subscribe_in(&input, ...) for InputEvent::PressEnter / InputEvent::Blur;
// read input.read(cx).value(cx), parse, write into the row, editing = None, cx.notify().
// escape-to-cancel: just drop the editing slot without writing.
```

One editor entity, created per edit, is the right shape — an `InputState` per cell would
create thousands of entities and fight virtualization.

**B. Edit in a side panel / modal**: on `DoubleClickedCell`/`DoubleClickedRow`, open a
form bound to the record. More robust for multi-field validation; the table stays
read-only. Prefer this for SQL-editor-style workflows with commit/rollback.

Enter-to-edit keyboard flow: the built-in bindings don't include Enter; add your own
action bound in the `"DataTable"` context that reads `selected_cell()` and starts
pattern A.

## Infinite scroll / load-more

```rust
fn has_more(&self, _: &App) -> bool { self.next_page.is_some() }
fn load_more_threshold(&self) -> usize { 100 }   // trigger when ≤100 rows remain below

fn load_more(&mut self, _: &mut Window, cx: &mut Context<TableState<Self>>) {
    if self.fetching { return }                  // it fires repeatedly near the bottom — you gate it
    self.fetching = true;
    cx.spawn(async move |table, cx| {
        let page = fetch_page().await;           // off the main thread
        table.update(cx, |table, cx| {
            let d = table.delegate_mut();
            d.fetching = false;
            d.rows.extend(page.rows);
            d.next_page = page.next;
            cx.notify();
        }).ok();
    }).detach();
}
```

`loading(cx)` → `render_loading` (skeleton) is for the *initial* full-table load, not
for load-more.

## Very large / live data

- Both axes are virtualized: `render_td` only runs for visible cells. Costs that scale
  with total size belong in the delegate's data prep, not in render.
- Live tickers: update only what's visible — `visible_rows_changed(range, ...)` (and
  `visible_columns_changed`) tell you the viewport; alternatively read
  `state.visible_range()` from a timer task and mutate just those rows, then
  `cx.notify()`. Keep both hooks fast; they fire on every scroll.
- Store rows compactly (plain structs, `SharedString` for repeated strings). Format
  numbers in `render_td` at paint time rather than caching formatted strings for a
  million rows.

## Export

Implement `cell_text(row_ix, col_ix, cx) -> String`, then
`state.dump(cx)` returns `(headers, all_rows)` ready for CSV writing. `dump` walks every
row — fine for tens of thousands, spawn it off-thread for millions.

## Persisting user layout

Listen for `ColumnWidthsChanged(Vec<Pixels>)` and `MoveColumn(from, to)`; store; on
startup apply the order to your `Vec<Column>` and the widths via `Column::width` before
constructing the delegate. In `move_column`, mirror the reorder into your own vec:
`let col = self.columns.remove(col_ix); self.columns.insert(to_ix, col);`.

## Grouped (multi-level) headers

```rust
fn group_headers(&self, cx: &App) -> Option<Vec<Vec<ColumnGroup>>> {
    Some(vec![vec![
        ColumnGroup::new("Identity", 2),      // spans leaf columns 0..2
        ColumnGroup::new("Market Data", 3),   // spans 2..5
    ]])
}
```

Each inner Vec is one extra header row above the leaf header; **spans in every row must
sum to `columns_count`** (including any trailing/extra columns) or group cells drift off
their columns. Group cell width = sum of its leaf columns' runtime widths, so it follows
resizing automatically.
