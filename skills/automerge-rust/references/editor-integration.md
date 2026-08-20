# Building an editor on automerge: the binding architecture

How to wire a real text editor (GPUI/egui/iced GUI, a TUI, or a headless
collaboration server) to an automerge Text object. There is no Rust editor
binding to copy yet, but the official ProseMirror binding
(https://github.com/automerge/automerge-prosemirror, TypeScript, ~3,300 lines)
is the canonical reference implementation — and the Rust `spans`/`update_spans`
/ block APIs were built to serve it, so its architecture maps directly onto the
Rust crate. This file describes that architecture with the Rust API named for
every piece. File:line references are into the automerge-prosemirror source;
everything here was extracted from that source, not from docs.

Read `references/rich-text.md` first — this file assumes marks/spans/blocks.

## Contents

1. [The shape of the whole thing](#1-the-shape-of-the-whole-thing)
2. [Local loop: editor edit → automerge](#2-local-loop-editor-edit--automerge)
3. [Position mapping between editor tree and flat spans](#3-position-mapping-between-editor-tree-and-flat-spans)
4. [Remote loop: patches → editor](#4-remote-loop-patches--editor)
5. [Selection, undo, echo suppression](#5-selection-undo-echo-suppression)
6. [Schema adaptation and lossless unknowns](#6-schema-adaptation-and-lossless-unknowns)
7. [Gotchas from the reference binding](#7-gotchas-from-the-reference-binding)
8. [Port-to-Rust checklist](#8-port-to-rust-checklist)

---

## 1. The shape of the whole thing

The automerge document is the **single source of truth**; the editor document is
a projection of `spans()`. The binding keeps almost no state — one re-entrancy
flag and, during remote-patch application, a spans snapshot. Two unidirectional
loops connect editor and doc:

- **Local**: user edit → translate editor operations into
  `splice_text`/`mark`/`unmark`/`update_spans` → then *verify*: diff the doc
  (heads-before → heads-after), re-project, and patch the editor if the
  projection disagrees with what the editor shows.
- **Remote**: incoming patches (from merge/sync/another view) → translate
  `PatchAction`s into editor edits against a spans snapshot taken at the
  *before* heads.

The most important design decision to copy: **fine-grained ops for plain text,
regenerate-and-diff for structure** — on both loops.

## 2. Local loop: editor edit → automerge

On each editor transaction (syncPlugin.ts:52-144):

1. Capture `heads_before = doc.get_heads()` and the current spans.
2. Translate the editor's steps, re-reading spans between steps so each step's
   positions map against post-step state:
   - **Plain text insert/delete within one text run** (the common case — typing):
     map the editor range to an automerge range (§3), then
     `splice_text(obj, pos, del, text)`. Then **reconcile marks**: automerge
     gives inserted text the marks implied by neighbors' expand rules, which can
     differ from editor intent (stored marks toggled at the caret) — read
     `get_marks(obj, index, None)` over the inserted range and issue corrective
     `mark`/`unmark` calls (pmToAm.ts:238-286).
   - **Mark add/remove**: batch consecutive add-mark steps (editors emit one per
     text node!) and coalesce adjacent equal `(name, value, expand)` ranges —
     including ranges separated only by block markers — into single
     `mark(obj, Mark::new(..), expand)` calls (pmToAm.ts:141-208). Expand policy
     comes from the mark's schema (`inclusive` in PM terms): formatting →
     `ExpandMark::Both`, links → `ExpandMark::None`.
   - **Anything structural** — Enter (paragraph split), heading toggle, list
     nesting, multi-block delete, structured paste: serialize the *whole* editor
     tree back to a flat `Vec<Span>` (§3 reverse projection) and call
     `update_spans(obj, config, spans)`. The reference binding **never calls
     `split_block`/`join_block` directly** — `update_spans` computes those ops
     internally, and getting the diff right by hand is not worth it
     (pmToAm.ts:54-139).
3. **Reconciliation pass** (syncPlugin.ts:82-143): compute
   `patches = doc.diff(&heads_before, &doc.get_heads())`, translate them into
   hypothetical editor edits, and compare with what the editor already did. If
   they differ (normalization deltas — e.g. after Enter the editor's new
   paragraph wasn't yet tagged as corresponding to a real block marker), rebuild
   the affected range from a fresh projection and patch the editor. This
   write-then-verify cycle is what makes the binding robust: local translation
   is *not* trusted to be lossless.

Rust APIs: `get_heads`, `spans`, `splice_text`, `get_marks`, `mark`, `unmark`,
`update_spans` + `UpdateSpansConfig`, `diff`.

## 3. Position mapping between editor tree and flat spans

The core problem: automerge is flat (1 unit per char, 1 unit per block marker),
tree editors count node boundaries (open + close of every node = 1 unit each),
and wrapper nodes (a `<ul>` around list items, an auto-inserted paragraph) have
**no representation in spans at all**.

The reference solution (traversal.ts) uses **no precomputed index table**. Both
directions replay a canonical traversal of the span list that emits an event
stream — `openTag`/`closeTag`/`leafNode` (each +1 editor unit), `text` (+n
both), `block` (+1 automerge unit only) — with each event tagged
`explicit` (backed by a block marker) or `render-only` (exists only to satisfy
the editor schema). All three mapping functions are O(n) scans over this
stream:

- `am_splice_idx_to_editor_idx` — where does an automerge splice land in the
  editor? Tracks the last "insertable" position (just inside the most recent
  textblock) so an insert at a block boundary goes *inside* the following block,
  not between node tokens.
- `editor_range_to_am_range` — for splices and marks; mid-text positions are
  offset arithmetic, node-boundary positions snap past the block marker.
- `am_idx_to_editor_block_idx` — block-marker index → position inside that block.

Generating the stream requires a *schema oracle*: given the current stack of
open nodes and the next span, which wrappers must close/open, and what must be
auto-filled (text at top level gets wrapped in a paragraph; a closing list item
must contain at least one block)? ProseMirror gets this from its `ContentMatch`
automaton; a Rust binding with a fixed schema can hand-write it. A block
marker's `parents` list (e.g. `["blockquote"]`) drives wrapper reconstruction.

The reverse projection (editor tree → `Vec<Span>`, feeding `update_spans`) does
a DFS emitting the same events, with a per-node decision "does this node emit a
block marker?": nodes the projection tagged as marker-backed always do; wrappers
and auto-fill content that match what the schema would generate emit nothing.
The reference binding stores that tag as a hidden node attribute
(`isAmgBlock: bool`) set during projection — port that idea: **each editor node
must remember whether it corresponds to a real block marker**.

Two conventions to port exactly (top source of off-by-one bugs): the traversal's
am-index starts at −1 ("index of last consumed unit"), so conversions end in
`+1`; and all character counting must use the document's `TextEncoding` (the JS
binding counts UTF-16 because JS strings do; a Rust binding should pick one
encoding and use it on both sides — see the rich-text.md encoding notes).

## 4. Remote loop: patches → editor

Input: `Vec<Patch>` from a merge, sync receive, or another view of the same doc
(`diff_incremental()`, a `PatchLog`, or `diff(&before, &after)`).

Patch indices are relative to the document state *after the previous patch in
the batch*, and the doc itself is already fully updated — so you cannot read
intermediate states from it. The binding therefore takes a spans snapshot at the
before-heads (`spans_at(obj, &heads_before)`) and **mutates that snapshot in
lock-step** as it consumes patches (maintainSpans.ts):

- `SpliceText { index, value, marks }` → insert into the snapshot (split spans /
  merge equal-marked neighbors) and emit a fine-grained editor text-insert at
  the mapped position, styled from `marks`.
- `DeleteSeq { index, length }` — but first check whether the index is a **block
  marker**: if so this is structural, not text deletion. Text deletes emit
  editor deletes; block-touching ones go to the rebuild path.
- `Mark { marks }` → split snapshot spans at boundaries, set/clear mark entries
  (a `Null` value = removal), emit editor add-mark/remove-mark over the mapped
  range.
- `Insert` of a map element = a new (initially empty) block marker; subsequent
  deeper patches (`PutMap` etc. with paths through the marker) fill in its
  `type`/`parents`/`attrs`. All block-group patches: apply to the snapshot,
  rebuild the editor tree from it, tree-diff against the current editor doc, and
  apply the minimal replace — same regenerate-and-diff philosophy as the local
  loop.

The snapshot maintainer (`fn patch_spans(&mut Vec<Span>, &Patch)`) is the
fiddliest component — span split/merge invariants — and the one most worth
porting the reference test suite for (its `test/` dir covers it well).

## 5. Selection, undo, echo suppression

**Selection**: the reference binding relies on the editor's own step-position
mapping and, after reconciliation rebuilds, a best-effort restore. A Rust
binding can do strictly better with automerge cursors: capture
`get_cursor(obj, pos, None)` at the selection endpoints before applying a remote
batch, resolve with `get_cursor_position` after, and convert to an editor
position via §3. Cursors are CRDT-stable across concurrent edits:

```rust
// selection endpoint at index 6 ("world" in "hello world")
let sel = doc.get_cursor(&text, 6usize, None)?;
// ... a remote peer concurrently prepends ">> "; we merge their changes ...
doc.merge(&mut remote)?;
let new_idx = doc.get_cursor_position(&text, &sel, None)?;  // == 9
assert_eq!(&doc.text(&text)?[new_idx..], "world");           // still on "world"
```

**Undo/redo is editor-local.** The stock editor history holds inverse
operations; undoing replays them through the normal local loop as *new*
automerge changes (never automerge history rewinds/rollback). The one essential
rule: remote-originated transactions are flagged so they never enter the local
undo stack (`addToHistory: false` in the reference). Reconciliation fixups
should undo together with the user edit that triggered them.

**Echo suppression**: each loop triggers the other's input events, so the
binding wraps both in a single re-entrancy flag (works because everything is
synchronous single-threaded). In async Rust, route both loops through one owner
task, or tag changes with an origin and have the view skip its own patch
batches. The glue interface a repo layer must provide is small: current-doc read
access, a change entry point (closure over `Transactable`), and a patch feed for
every change this view didn't make, with the before-heads. Raw automerge (via
`diff_incremental`) and samod's `DocHandle::changes()` can both supply this.

## 6. Schema adaptation and lossless unknowns

A `SchemaAdapter` compiles the editor schema into: a block-name ↔ node-type
table (with context-dependent entries — a `list_item` maps to
`"ordered-list-item"` or `"unordered-list-item"` depending on its parent, and
the block's `parents` list captures the nesting); attr codec fns per block type;
a mark table with value codecs (attr-carrying marks like links serialize attrs
as a **JSON string**, since mark values are scalars); and the per-mark expand
policy that also feeds `UpdateSpansConfig`.

For documents co-edited by apps with *different* schemas, the reference binding
round-trips unknown content losslessly through reserved editor attrs: an
unknown block type renders as a designated fallback node carrying the entire
original marker map in an attr (emitted back verbatim on write); unknown attrs
on known blocks and unknown marks are likewise stashed and restored. If your
Rust editor may ever co-edit with other automerge apps, build these passthrough
slots in from the start — dropping unknown data on write is silent corruption
for the other app.

## 7. Gotchas from the reference binding

- After `splice_text`, verify inserted-range marks with `get_marks` and correct
  them — expand inheritance and editor stored-marks disagree routinely.
- A `DeleteSeq` at a block-marker index is structural — always check before
  treating a delete patch as text.
- Editors emit one add-mark step per text node: batch and coalesce, or one
  bold press writes N tiny mark ranges into the doc.
- Filter `Null` mark values on read; treat `Null` in mark patches as removal.
- An empty document projects as one render-only empty paragraph — editors can't
  represent truly empty docs.
- Never trust mark values from the network: parse link-JSON defensively with an
  empty fallback.
- IME/composition: commit nothing to the doc for in-flight composition text;
  splice once on commit. (The reference gets this free from the browser layer —
  a native Rust editor must handle it explicitly.)
- The JS binding's surrogate-pair diff fixups are UTF-16 artifacts; the Rust
  equivalent is respecting char boundaries in whatever `TextEncoding` you chose.

## 8. Port-to-Rust checklist

Each component with the Rust API it calls (mutators on
`transaction::Transactable`, implemented by `AutoCommit`/`Transaction`):

1. **Schema adapter** (pure data): block/node table, mark table + value codecs,
   expand policy → `UpdateSpansConfig`, unknown-content passthrough slots.
2. **Projection** spans → editor tree: `spans()` / `spans_at()`, a schema
   oracle for auto-wrapping, and a marker-backed flag on each produced node.
3. **Reverse projection** editor tree → `Vec<Span>`: feeds `update_spans`.
4. **Index mapping**: the §3 event-stream scans; consistent `TextEncoding`.
5. **Local edit translator**: `splice_text` + `get_marks` + `mark`/`unmark`
   (batched) for text and marks; reverse-project + `update_spans` for structure.
6. **Local reconciliation**: `get_heads` before, `diff(&before, &after)` after,
   compare, patch editor from a fresh projection on mismatch.
7. **Remote patch translator**: consume `PatchAction::{SpliceText, DeleteSeq,
   Insert, Mark, PutMap...}` against a `spans_at(&heads_before)` snapshot.
8. **Span snapshot maintainer**: `fn patch_spans(&mut Vec<Span>, &Patch)` with
   split/merge invariants — port the reference tests.
9. **Echo guard**: one doc owner; origin-tagged updates; remote updates flagged
   out of undo history.
10. **Selection preservation**: `get_cursor`/`get_cursor_position` around remote
    batches + index mapping.
11. **Editor-local undo stack** of inverse edits; automerge history untouched.
12. **Headless server variant**: components 1-8 without the editor — per-client
    spans snapshots, protocol ops ↔ `splice_text`/`mark`/`update_spans`,
    patches out via `diff_incremental`.
