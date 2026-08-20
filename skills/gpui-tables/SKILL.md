---
name: gpui-tables
description: Building tables in GPUI apps — from a small static HTML-table analog to a virtualized, spreadsheet-grade data grid (SQL result views, Excel-like sheets, log/keybinding tables). Covers hand-rolled flex tables, gpui-component's stateless Table and virtualized DataTable/TableDelegate/TableState, and Zed's ui::Table architecture. Use whenever the task involves rows-and-columns UI in GPUI - tabular data, data grids, column sizing/resizing/reordering/pinning, sortable or filterable columns, cell selection or editing, horizontal+vertical scrolling of large datasets, or virtualization in two axes. Trigger even if the user just says "show this query result / CSV / list of records in a table".
---

## The one core fact

GPUI has **no table layout primitive** — no `display: table`, no grid, no cross-row content
measurement. Layout is flexbox (Taffy). Every table in the ecosystem — Zed's `ui::Table`,
gpui-component's `Table` and `DataTable`, and anything hand-rolled — is the same shape:

> a vertical stack of independent row flexes, kept aligned by applying the **same explicit
> per-column widths** to the header and to every row.

Consequences worth internalizing before writing code:

- **Column alignment comes from widths you supply** (fixed `px`, or equal/fractional
  `flex_basis` shares) — never from content. "Auto-fit column to widest cell" over all rows
  does not exist, and can't: virtualized rows aren't laid out until scrolled into view.
  If auto-fit matters, compute widths yourself from data (measure a sample or use
  char-count heuristics) and pass them in as pixel widths.
- Each cell needs `overflow_hidden()` + `whitespace_nowrap()` + `text_ellipsis()` (or an
  explicit wrap strategy) or long content will blow the row layout apart.
- So a "traditional table view" is not *difficult* — it's just always an explicit-width
  flex construction. The hard parts are virtualization, scroll-sync, and resize, which
  the libraries below already solved.

## Choosing an approach

| Situation | Use | Reference |
|---|---|---|
| ≤ a few dozen rows, static display (`<table>` analog) | Hand-rolled flex rows, or gpui-component's stateless `Table`/`TableRow`/`TableCell` | [flex-tables.md](references/flex-tables.md) |
| Long uniform-row list, few columns, no column features | Raw `uniform_list` with a shared widths Vec | [flex-tables.md](references/flex-tables.md) |
| SQL viewer / spreadsheet / big grid: virtualization in X and/or Y, resize, reorder, pin, sort, selection, context menus, infinite load | gpui-component `DataTable` + `TableDelegate` + `TableState` | [data-table.md](references/data-table.md), then [data-table-features.md](references/data-table-features.md) |
| Filtering, cell editing, CSV export, live-updating cells | Delegate-side patterns on `DataTable` (none of these are built in) | [data-table-features.md](references/data-table-features.md) |
| Variable row heights (multiline cells, CSV preview) | `list()`/`ListState` body, or Zed's `Table::variable_row_height_list` pattern — **not** `DataTable` (uniform heights only) | [diy-and-zed.md](references/diy-and-zed.md) |
| Can't/won't depend on gpui-component; or studying how the mechanics work | Build on raw gpui, borrowing Zed's `ui::Table` architecture | [diy-and-zed.md](references/diy-and-zed.md) |

Rules of thumb:

- Default to **gpui-component's `DataTable`** for anything with column features or >~200
  rows. Reimplementing 2-axis virtualization + resize + pinned columns is a multi-week
  job; `DataTable` is production-tested (Longbridge's trading app) and smooth at
  hundreds of thousands of rows × hundreds of columns.
- Zed's `ui::Table` (`crates/ui`) is **GPL-3.0-or-later** — read it for architecture,
  don't vendor the code into a non-GPL app. gpui itself and gpui-component are
  Apache-2.0.
- A plain scrolling `div` lays out *every* row each frame; a few hundred rows already
  lags. Virtualize early.

## Project setup (gpui-component)

```toml
[dependencies]
gpui = { git = "https://github.com/zed-industries/zed" }
gpui_platform = { git = "https://github.com/zed-industries/zed", features = ["font-kit", "wayland", "x11"] }
gpui-component = { git = "https://github.com/longbridge/gpui-component" }
```

Call `gpui_component::init(cx)` once at app startup — it registers the `Theme` global and
the `DataTable` key bindings (arrows/tab/home/end/pageup/pagedown/escape under the
`"DataTable"` key context). Without it, tables render unthemed and keyboard nav is dead.

gpui-component is pre-1.0 (v0.5.x). v0.5 externalized table state (`TableState` is now an
entity you own; older code had state inside a `Table` view) and renamed several
components. Verify any API against the vendored checkout before trusting examples from
the web.

## Ground truth

When the project pins these crates via git, the vendored sources are ground truth — grep
them before answering nontrivial API questions:

- gpui: `~/.cargo/git/checkouts/zed-*/<rev>/crates/gpui/src/elements/uniform_list.rs`, `list.rs`
- gpui-component tables: `~/.cargo/git/checkouts/gpui-component-*/<rev>/crates/ui/src/table/`
  (`delegate.rs` = the trait, `column.rs` = Column builder, `state.rs` = all mechanics,
  `data_table.rs` = element + key bindings, `table.rs` = stateless family)
- virtual list (2nd-axis virtualization, usable standalone): `crates/base/src/virtual_list.rs`
- Real-world delegate example: `crates/story/src/stories/data_table_story.rs` in the
  gpui-component repo (5k-row stock table: sorting, group headers, load-more, live updates)

## Relationship to the `gpui` skill

This skill assumes the base `gpui` skill's material. Especially relevant there:
scrolling/`uniform_list` fundamentals (list-scroll reference), `min_h_0`/`min_w_0` flex
gotchas (layout reference), and the entity/state model. Load those for general questions;
load this skill's references for anything table-shaped.
