# Rich text: marks, spans, blocks

Covers automerge 0.11's rich-text layer (the Peritext model): inline formatting
via **marks**, structured documents via **block markers**, rendering via
**spans**, and bulk editing via **update_spans**. All APIs and behaviors verified
against source and tests; every example compiles and runs against automerge 0.11.
Items that are JS-ecosystem conventions rather than Rust API are marked
**[convention]**.

Rich text is raw-automerge-only territory: **autosurgeon has no marks, blocks, or
spans support at all** (its `Text` reconciles via `update_text` only). Drive these
APIs directly, even in an otherwise autosurgeon-typed app.

This file covers the document-side APIs. For wiring an actual editor to them —
position mapping, the local/remote loops, undo, selection — read
`references/editor-integration.md` after this one.

Key imports:

```rust
use std::sync::Arc;
use automerge::{
    hydrate_list, hydrate_map,                 // macros at crate root
    iter::Span,                                // also re-exported as automerge::Span
    marks::{ExpandMark, Mark, MarkSet, UpdateSpansConfig},
    transaction::Transactable,
    AutoCommit, ObjType, ReadDoc, ScalarValue, ROOT,
};
```

## Contents

1. [Marks](#1-marks)
2. [Spans — rendering styled runs](#2-spans--rendering-styled-runs)
3. [Blocks — paragraphs and structure](#3-blocks--paragraphs-and-structure)
4. [update_spans — bulk diff of blocks + marks + text](#4-update_spans--bulk-diff-of-blocks--marks--text)
5. [Patches for rich text](#5-patches-for-rich-text)
6. [Merge semantics](#6-merge-semantics)
7. [Sharp edges checklist](#7-sharp-edges-checklist)

---

## 1. Marks

A mark attaches a named scalar value to a range of a Text object — bold, italic,
a link, a comment anchor. Each position can carry at most one value per mark
name; overlapping same-name marks resolve to an arbitrary-but-deterministic
winner on every replica.

```rust
pub struct Mark {
    pub start: usize,       // in the doc's TextEncoding units
    pub end: usize,         // exclusive
    pub name: SmolStr,      // also .name() -> &str
    pub value: ScalarValue, // also .value() -> &ScalarValue
}
Mark::new<V: Into<ScalarValue>>(name: String, value: V, start: usize, end: usize) -> Mark;

// Transactable — Text objects only (InvalidOp on maps/lists):
fn mark<O: AsRef<ExId>>(&mut self, obj: O, mark: Mark, expand: ExpandMark) -> Result<(), _>;
fn unmark<O: AsRef<ExId>>(&mut self, obj: O, key: &str, start: usize, end: usize,
    expand: ExpandMark) -> Result<(), _>;
```

Mark values are `ScalarValue` **only** — no nested maps/lists. The JS convention
for structured mark data is a JSON-serialized string, e.g. a `"link"` mark whose
value is `{"href":...,"title":...}` as a JSON string **[convention]**.

### ExpandMark — who inherits the mark at the boundaries

```rust
pub enum ExpandMark { Before, After, Both, None }   // Default = After
```

Controls whether text inserted *at a boundary* of the marked range inherits the
mark. `After` (default): typing at the end of a bold run stays bold; typing at
the start doesn't. Choose per mark type **[convention]**: formatting marks
(bold/italic) should expand (`After` or `Both`); links and comment anchors should
not (`None`). A zero-width mark with `ExpandMark::None` is silently ignored.

### Unmark is a null tombstone

`unmark(obj, name, start, end, expand)` is literally `mark` with
`ScalarValue::Null`. That means partial unmark works naturally — bold 0..9 then
unmark 6..9 leaves bold on 0..6 — and the tombstone participates in the same
winner resolution as any mark (see §6). The `expand` argument controls whether
the *unmark* range grows at its boundaries.

### Reading marks

```rust
fn marks<O>(&self, obj: O) -> Result<Vec<Mark>, AutomergeError>;      // active marks, coalesced,
                                                                      // tombstones stripped
fn marks_at<O>(&self, obj: O, heads: &[ChangeHash]) -> Result<Vec<Mark>, _>;  // historical —
                                                                      // "at heads", NOT "at index"!
fn get_marks<O>(&self, obj: O, index: usize, heads: Option<&[ChangeHash]>)
    -> Result<MarkSet, _>;                                            // marks active at ONE index
```

`MarkSet` public API in 0.11: `iter() -> (&str, &ScalarValue)`, `num_marks()`,
`len()`, `is_empty()`, `non_deleted_marks()` (a `PartialEq` view that ignores
Null tombstones), and `FromIterator<(String, ScalarValue)>` for building one by
hand (`without_unmarks`/`insert` are crate-private — don't copy docs.rs-era code
that calls them):

```rust
let ms: MarkSet = [("bold".to_string(), ScalarValue::from(true))].into_iter().collect();
```

All mark indices are in the document's `TextEncoding` units, like every other
text index (verified across encodings by the repo's `tests/text_encoding.rs`).

### Worked example — mark, read runs, unmark

```rust
let mut doc = AutoCommit::new();
let text = doc.put_object(ROOT, "text", ObjType::Text)?;
doc.splice_text(&text, 0, 0, "Hello bold world")?;

// bold "bold" (6..10); typing at its end stays bold
doc.mark(&text, Mark::new("bold".to_string(), true, 6, 10), ExpandMark::After)?;
// links should not expand
doc.mark(
    &text,
    Mark::new("link".to_string(), r#"{"href":"https://example.com"}"#.to_string(), 6, 10),
    ExpandMark::None,
)?;

let all: Vec<Mark> = doc.marks(&text)?;             // whole object
let at7: MarkSet = doc.get_marks(&text, 7, None)?;  // single index
assert_eq!(at7.num_marks(), 2);

doc.unmark(&text, "bold", 6, 10, ExpandMark::Both)?; // null tombstone
assert_eq!(doc.marks(&text)?.len(), 1);
```

## 2. Spans — rendering styled runs

`spans()` is how an editor/renderer consumes rich text: a single pass yielding
text runs (with their active marks) interleaved with block markers.

```rust
fn spans<O: AsRef<ExId>>(&self, obj: O) -> Result<Spans<'_>, AutomergeError>;   // Iterator<Item = Span>
fn spans_at<O: AsRef<ExId>>(&self, obj: O, heads: &[ChangeHash]) -> Result<Spans<'_>, _>;

pub enum Span {
    Text { text: String, marks: Option<Arc<MarkSet>> },
    Block(hydrate::Map),
}
// Span::as_str(); Block renders as "\u{fffc}"
```

Guarantees (from the test suite): consecutive text with identical active marks is
coalesced into one `Text` span; fully-unmarked runs report `marks: None`; a mark
spanning a block marker is reported on the text spans on both sides (the `Block`
span itself carries no marks); `spans_at` respects heads for both text and marks.

```rust
// styled runs for a renderer: Vec<(String, Vec<(name, value)>)>
let runs: Vec<(String, Vec<(String, ScalarValue)>)> = doc
    .spans(&text)?
    .filter_map(|span| match span {
        Span::Text { text, marks } => {
            let marks = marks
                .map(|m: Arc<MarkSet>| m.iter().map(|(n, v)| (n.to_string(), v.clone())).collect())
                .unwrap_or_default();
            Some((text, marks))
        }
        Span::Block(_) => None,
    })
    .collect();
```

## 3. Blocks — paragraphs and structure

A block marker is a **map object inserted as one element of the text sequence**.
It marks the start of a block (paragraph, heading, list item); the block's
content is the text that follows it up to the next marker.

```rust
fn split_block<O>(&mut self, obj: O, index: usize) -> Result<ExId, _>;  // insert marker, return its map's id
fn join_block<O>(&mut self, text: O, index: usize) -> Result<(), _>;    // delete marker at index
fn replace_block<O>(&mut self, text: O, index: usize) -> Result<ExId, _>; // join + split, new empty marker
```

The returned `ExId` is a plain, initially-empty map — use the ordinary map API
(`put`, `put_object`, `update_object`) to set its attributes. The Rust core does
not interpret block attributes at all; the schema is a JS-ecosystem convention
**[convention, automerge.org rich-text schema]** that the Rust test suite also
follows:

- `type`: `"paragraph"`, `"heading"`, `"code-block"`, `"blockquote"`,
  `"ordered-list-item"`, `"unordered-list-item"`, `"image"`, ...
- `parents`: list of the block types this block is nested inside (a paragraph in
  a blockquote has `parents: ["blockquote"]`).
- `attrs`: block-specific metadata map — headings: `level`; code blocks:
  `language`; images: `src`/`alt`/`title`.
- `isEmbed`: bool, for non-textual embeds.
- Standard mark names: `"strong"`, `"em"` (value `true`), `"link"`
  (JSON-string value). Custom block types and mark names should be prefixed
  `"__ext__..."`.

In `text()` output each marker appears as U+FFFC (OBJECT REPLACEMENT CHARACTER),
and `length()` counts it.

```rust
let mut doc = AutoCommit::new();
let text = doc.put_object(ROOT, "text", ObjType::Text)?;

let block1 = doc.split_block(&text, 0)?;
doc.update_object(&block1, &hydrate_map! {
    "type" => "paragraph",
    "parents" => hydrate_list![],
    "attrs" => hydrate_map!{},
}.into())?;
doc.splice_text(&text, 1, 0, "hello world")?;

let block2 = doc.split_block(&text, 12)?;
doc.put(&block2, "type", "unordered-list-item")?;   // plain map ops work too
doc.splice_text(&text, 13, 0, "a list item")?;

assert_eq!(doc.text(&text)?, "\u{fffc}hello world\u{fffc}a list item");

for span in doc.spans(&text)? {
    match span {
        Span::Block(map) => println!("block type: {:?}", map.get("type")),
        Span::Text { text, marks } => println!("text {text:?} marks {marks:?}"),
    }
}

doc.join_block(&text, 12)?;   // delete the marker: the two blocks merge
```

Caveat (a FIXME in the source): `join_block` does not verify the element at
`index` is actually a block marker — it is effectively a sequence delete, so a
wrong index silently deletes a text unit instead.

## 4. update_spans — bulk diff of blocks + marks + text

`update_spans` is the rich-text analogue of `update_text`: hand it the complete
desired sequence of `Span`s and it diffs (Myers) against current content,
emitting a reasonably minimal set of splices, block operations, and
mark/unmark calls. Use it when you get whole-document state from an editor
rather than individual edit events (individual events merge better — same
trade-off as `update_text`).

```rust
pub struct UpdateSpansConfig {
    pub default_expand: ExpandMark,                       // Default = After
    pub per_mark_expands: HashMap<String, ExpandMark>,
}
// builders: .with_default_expand(e), .with_mark_expand("name", e); fields are pub

fn update_spans<O: AsRef<ExId>, I: IntoIterator<Item = Span>>(
    &mut self, text: O, config: UpdateSpansConfig, new_text: I) -> Result<(), _>;
```

Build `Span` values literally; a no-op update produces zero patches:

```rust
let config = UpdateSpansConfig::default()
    .with_default_expand(ExpandMark::None)
    .with_mark_expand("bold", ExpandMark::After);

let bold: Option<Arc<MarkSet>> = Some(Arc::new(
    [("bold".to_string(), ScalarValue::from(true))].into_iter().collect::<MarkSet>(),
));

doc.update_spans(&text, config, [
    Span::Block(hydrate_map! {
        "type" => "heading", "parents" => hydrate_list![],
        "attrs" => hydrate_map!{ "level" => 1 },
    }),
    Span::Text { text: "hello".to_string(), marks: bold.clone() },
    Span::Text { text: " world".to_string(), marks: None },
])?;

let spans: Vec<Span> = doc.spans(&text)?.collect();  // round-trips to exactly the input
```

Semantics: pass 1 diffs text and block markers (blocks compare by full hydrated
map content; a changed block map is updated in place — deleting a key from a
block's map is expressed by omitting it from the new `Span::Block`). Pass 2
reconciles marks: unmarks anything not in the target set, marks anything
missing, using the per-mark/default expand from the config.

## 5. Patches for rich text

- `PatchAction::SpliceText { index, value: ConcreteTextValue, marks: Option<MarkSet> }` —
  `marks` carries **all marks active for the inserted span** (including inherited
  expand marks), so a UI can style remote insertions immediately without
  re-querying. `value.make_string()` extracts the text.
- `PatchAction::Mark { marks: Vec<Mark> }` — marks added or removed on existing
  text; a removal arrives as a `Mark` whose `value` is `ScalarValue::Null` over
  the range. Apply each mark over `[start, end)`, treating Null as "clear this
  name".
- Block operations surface as ordinary object patches: `split_block` produces a
  `PatchAction::Insert` whose element is a `Value::Object(ObjType::Map)`, then
  normal map patches inside the block (the patch `path` includes
  `(text_id, Prop::Seq(index))`).
- **Do not feed mark patches into `hydrate::Value::apply_patches`**: in 0.11
  `hydrate::Text`'s handler for `PatchAction::Mark` is an unimplemented `todo!()`
  and will **panic**. Maintain your own styled view from spans/patches; hydrated
  text also flattens block markers to `\u{fffc}` and ignores patches inside
  block maps.

## 6. Merge semantics

All verified by tests or by fork/merge execution:

- **Concurrent overlapping same-name marks** converge everywhere: per position,
  the mark op with the greatest OpId (Lamport counter, then actor) wins. Two
  forks marking `color=red` on 0..8 and `color=blue` on 3..11 converge on both
  replicas to `[Mark{0..3, red}, Mark{3..11, blue}]`.
- **Unmark vs concurrent mark**: an unmark tombstone only suppresses marks with
  lower OpId — a concurrent re-mark with higher OpId survives it.
- **Insertion at an expand boundary** by a remote peer inherits the mark exactly
  as a local insertion would, and produces identical patches either way.
- **Deleted marked text does not resurrect marks**: delete a marked range, insert
  new text at the same position → unmarked.
- **Merging a block insert** produces the same Insert-map patch shape on the
  receiving side as creating it locally.

## 7. Sharp edges checklist

1. One value per mark name per position; the winner is deterministic but
   arbitrary — don't build UI logic that assumes "my mark won".
2. Mark values are scalars only; structured data goes in as a JSON string
   (the JS `link` convention) or into an adjacent block map.
3. `mark`/`unmark`/`split_block`/`spans` work only on `ObjType::Text` (marks on
   Lists error with `InvalidOp`, despite doc comments saying "sequence").
4. `marks_at` is marks *at heads* (historical), not *at an index* — the
   positional query is `get_marks(obj, index, heads)`.
5. `MarkSet::without_unmarks`/`insert` are private in 0.11 — build with
   `FromIterator`, filter Null values via `non_deleted_marks()`.
6. `join_block` doesn't validate its target is a block marker.
7. `hydrate::Text` panics (`todo!()`) on `PatchAction::Mark` — never route rich
   text patches through `hydrate::Value::apply_patches`.
8. **Encoding trap**: U+FFFC is 3 UTF-8 code units, so under
   `TextEncoding::Utf8CodeUnit` each block marker occupies **3 index units**
   (1 unit under every other encoding) — and `update_spans`' internal mark-offset
   pass counts blocks as width 1 regardless, which disagrees. Avoid combining
   `Utf8CodeUnit` with blocks (this also collides with `autosurgeon::Text`'s
   UTF-8 requirement — one more reason rich text and autosurgeon don't mix).
9. `text()` interleaves `\u{fffc}` for every marker and `length()` counts them —
   account for markers when mapping editor coordinates to document indices.
10. 0.11 rejects (at load) documents whose mark-end ops precede their starts
    (produced by old bugs); `Automerge::rescue(&bytes)` recovers the current
    value of such documents as a `hydrate::Value`.
11. autosurgeon: zero support for marks/blocks/spans; its `Text` uses
    `update_text` only. Rich text means the raw API.
