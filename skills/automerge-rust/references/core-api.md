# `automerge` crate reference (v0.11)

Verified against the automerge repo at crate version 0.11.0. File paths below are
relative to `rust/automerge/` in https://github.com/automerge/automerge — consult
them (or https://docs.rs/automerge) when you need to go deeper.

## Contents

1. [Mental model & key types](#1-mental-model--key-types)
2. [Creating and mutating documents](#2-creating-and-mutating-documents)
3. [Reading & conflicts](#3-reading--conflicts)
4. [Text, cursors, marks](#4-text-cursors-marks)
5. [Save / load / fork / merge / actor IDs](#5-save--load--fork--merge--actor-ids)
6. [History and time travel](#6-history-and-time-travel)
7. [Sync protocol summary](#7-sync-protocol-summary)
8. [Patches and observing changes](#8-patches-and-observing-changes)
9. [Explicit transactions on `Automerge`](#9-explicit-transactions-on-automerge)
10. [hydrate, serde, automerge-test](#10-hydrate-serde-automerge-test)
11. [Cargo features](#11-cargo-features)
12. [Pitfalls](#12-pitfalls)
13. [API drift vs older tutorials](#13-api-drift-vs-older-tutorials)

---

## 1. Mental model & key types

An automerge document is a CRDT: a tree of nested maps/lists/text rooted at a map
(`ROOT`). Any replica can be modified locally and merged with any other replica of
the same document lineage; merges are automatic and deterministic.

Two document types:

- **`Automerge`** — the core document. Read-only unless you explicitly open a
  `transaction::Transaction` (via `doc.transaction()`, `doc.transact(...)`, etc.).
  Implements `ReadDoc` and `sync::SyncDoc` directly.
- **`AutoCommit`** — wraps an `Automerge` and manages transactions for you: every
  mutating call implicitly opens a transaction; it is implicitly committed by any
  "whole document" operation (`save`, `merge`, `get_heads`, `sync()`,
  `apply_changes`, `diff`, ...) or explicitly by `commit()` /
  `commit_with(CommitOptions)`. Implements `ReadDoc` + `Transactable` directly;
  sync via `doc.sync()` which returns an `impl SyncDoc`.

Rule of thumb: **use `AutoCommit` by default**. Use `Automerge` +
`transact`/`transaction()` when you need explicit change boundaries, commit
messages per logical change, rollback-on-error semantics, or `transaction_at`.

Key traits:

- **`ReadDoc`** (`src/read.rs`) — all read operations; implemented by `Automerge`,
  `AutoCommit`, and `Transaction`. Nearly every method has a
  `*_at(..., heads: &[ChangeHash])` historical variant. Note `get_heads` is NOT on
  `ReadDoc` (on `AutoCommit` it needs `&mut self` because it commits the pending
  transaction).
- **`transaction::Transactable: ReadDoc`** — all mutating operations; implemented
  by `AutoCommit`, `Transaction<'_>`, `OwnedTransaction`.
- **`sync::SyncDoc`** — `generate_sync_message` / `receive_sync_message`.

Key types (all re-exported at crate root):

```rust
pub use exid::{ExId as ObjId, ObjIdFromBytesError};      // note: ObjId IS ExId
pub const ROOT: ObjId = ObjId::Root;                     // root map of every document

pub enum ExId { Root, Id(u64 /*counter*/, ActorId, usize /*actor idx, doc-internal*/) }
// PartialEq/Hash/Ord use only (counter, ActorId) -> ExIds compare equal across replicas.
// Persist with ExId::to_bytes() / TryFrom<&[u8]>; or doc.import_obj("123@<actor-hex>")
// / doc.import(s) -> (ExId, ObjType); "_root" imports ROOT.

pub enum ObjType { Map /*default*/, Table /*legacy, ==Map*/, List, Text }

pub enum Prop { Map(String), Seq(usize) }   // From<&str>, From<String>, From<usize>, From<f64>

pub enum Value<'a> { Object(ObjType), Scalar(Cow<'a, ScalarValue>) }
// helpers: Value::str/int/uint/f64/counter/timestamp/bytes/map/list/text,
// .is_object(), .to_str(), .to_i64(), .to_scalar(), .to_objtype(), .into_owned()

pub enum ScalarValue {
    Bytes(Vec<u8>), Str(SmolStr), Int(i64), Uint(u64), F64(f64),
    Counter(Counter), Timestamp(i64) /*ms since epoch*/, Boolean(bool),
    Unknown { type_code: u8, bytes: Vec<u8> }, Null,
}
// ScalarValue::counter(n: i64) constructs a Counter. From impls exist for
// &str, String, i64, i32, u64, u32, f64, bool, char, Vec<u8>, () (-> Null).

pub struct ActorId(/* bytes */);   // ActorId::random(), TryFrom<&str> (hex),
                                   // From<&[u8]>/Vec<u8>, .to_hex_string(), .to_bytes()
pub struct ChangeHash(pub [u8; 32]);
pub struct Change;                 // .hash(), .message() -> Option<&str>, .deps(),
                                   // .actor_id(), .seq(), .timestamp(), .raw_bytes(),
                                   // Change::from_bytes(Vec<u8>)
```

Module layout: `automerge::{transaction, sync, marks, hydrate, patches, iter, error}`;
root re-exports `Automerge, AutoCommit, AutoSerde, Cursor, CursorPosition, MoveCursor,
OpCursor, Patch, PatchAction, PatchLog, ReadDoc, Stats, ScalarValue, Value, ObjType,
Prop, ActorId, ChangeHash, TextEncoding, LoadOptions, SaveOptions, OnPartialLoad,
StringMigration, VerificationMode, AutomergeError, Parents, ValueRef, ScalarValueRef,
Span`.

The API is deliberately low-level (like hand-building JSON). For struct mapping the
crate docs themselves point at **`autosurgeon`** (`references/autosurgeon.md`).

## 2. Creating and mutating documents

The `Transactable` trait (exact signatures, `src/transaction/transactable.rs`):

```rust
fn put<O: AsRef<ExId>, P: Into<Prop>, V: Into<ScalarValue>>(&mut self, obj: O, prop: P, value: V)
    -> Result<(), AutomergeError>;
fn put_object<O: AsRef<ExId>, P: Into<Prop>>(&mut self, obj: O, prop: P, object: ObjType)
    -> Result<ExId, AutomergeError>;                      // returns the new object's id
fn insert<O: AsRef<ExId>, V: Into<ScalarValue>>(&mut self, obj: O, index: usize, value: V)
    -> Result<(), AutomergeError>;                        // lists only: insert BEFORE index
fn insert_object<O: AsRef<ExId>>(&mut self, obj: O, index: usize, object: ObjType)
    -> Result<ExId, AutomergeError>;
fn increment<O: AsRef<ExId>, P: Into<Prop>>(&mut self, obj: O, prop: P, value: i64)
    -> Result<(), AutomergeError>;                        // target must be a Counter
fn delete<O: AsRef<ExId>, P: Into<Prop>>(&mut self, obj: O, prop: P)
    -> Result<(), AutomergeError>;
fn splice<O: AsRef<ExId>, V: Into<hydrate::Value>, I: IntoIterator<Item = V>>(
    &mut self, obj: O, pos: usize, del: isize, vals: I) -> Result<(), AutomergeError>;
    // list splice; del<0 deletes BEFORE pos; values may be nested hydrate::Values
fn splice_text<O: AsRef<ExId>>(&mut self, obj: O, pos: usize, del: isize, text: &str)
    -> Result<(), AutomergeError>;
fn update_text<S: AsRef<str>>(&mut self, obj: &ExId, new_text: S) -> Result<(), AutomergeError>;
    // NB: takes &ExId, not AsRef<ExId>
fn mark<O: AsRef<ExId>>(&mut self, obj: O, mark: Mark, expand: ExpandMark) -> Result<(), _>;
fn unmark<O: AsRef<ExId>>(&mut self, obj: O, key: &str, start: usize, end: usize,
    expand: ExpandMark) -> Result<(), _>;
fn split_block<O: AsRef<ExId>>(&mut self, obj: O, index: usize) -> Result<ExId, _>;
fn join_block<O: AsRef<ExId>>(&mut self, text: O, index: usize) -> Result<(), _>;
fn replace_block<O: AsRef<ExId>>(&mut self, text: O, index: usize) -> Result<ExId, _>;
fn update_spans<O: AsRef<ExId>, I: IntoIterator<Item = Span>>(&mut self, text: O,
    config: UpdateSpansConfig, new_text: I) -> Result<(), _>;
fn update_object<O: AsRef<ExId>>(&mut self, obj: O, new_value: &hydrate::Value)
    -> Result<(), error::UpdateObjectError>;              // diff-and-apply a whole subtree
fn batch_create_object<O: AsRef<ExId>, P: Into<Prop>>(&mut self, obj: O, prop: P,
    value: &hydrate::Value, insert: bool) -> Result<ExId, _>;  // fast bulk create
fn init_root_from_hydrate(&mut self, value: &hydrate::Map) -> Result<(), _>;
fn pending_ops(&self) -> usize;
fn base_heads(&self) -> Vec<ChangeHash>;
```

Canonical example:

```rust
use automerge::{ObjType, AutoCommit, transaction::Transactable, ReadDoc};

let mut doc = AutoCommit::new();
let contacts = doc.put_object(automerge::ROOT, "contacts", ObjType::List)?;
let alice = doc.insert_object(&contacts, 0, ObjType::Map)?;
doc.put(&alice, "name", "Alice")?;
doc.put(&alice, "email", "alice@example.com")?;
let data: Vec<u8> = doc.save();
```

Scalars, counters, timestamps:

```rust
doc.put(&obj, "n", 42_i64)?;                                  // Int
doc.put(&obj, "flag", true)?;                                 // Boolean
doc.put(&obj, "pi", 3.14_f64)?;                               // F64
doc.put(&obj, "name", "str")?;                                // ScalarValue::Str (a register!)
doc.put(&obj, "raw", vec![1u8, 2])?;                          // Bytes
doc.put(&obj, "nothing", ())?;                                // Null
doc.put(&obj, "likes", automerge::ScalarValue::counter(0))?;  // Counter
doc.increment(&obj, "likes", 3)?;                             // += 3; MissingCounter if not a counter
doc.put(&obj, "at", automerge::ScalarValue::Timestamp(1_700_000_000_000))?; // ms since epoch
```

- **Counters merge by addition**: concurrent `increment`s from different actors all
  apply. A plain `Int` is a register — concurrent writes conflict and one wins.
- **Timestamp** is just a tagged i64 (ms since Unix epoch); no special merge behavior.
- `Prop` is either a map key or list index: `doc.put(&list, 3, "x")` overwrites
  element 3, while `doc.insert(&list, 3, "x")` inserts before it. `put` on an index
  that doesn't exist errors (`InvalidIndex`); to append use
  `insert(&list, doc.length(&list), v)` or `splice`.

Bulk creation (much faster than one call per node):

```rust
use automerge::{hydrate, hydrate_map, hydrate_list, ROOT};
let value = hydrate::Value::Map(hydrate_map! {
    "a" => "hello",
    "b" => 42_i64,
    "outer" => hydrate_map! { "inner" => "deep" },
    "list" => hydrate_list![1_i64, 2_i64, 3_i64],
});
let obj_id = doc.batch_create_object(ROOT, "data", &value, false)?; // insert=false: put
// or initialize an empty document's root wholesale:
doc.init_root_from_hydrate(&hydrate_map! { "todos" => hydrate_list![] })?;
```

(`Automerge` also has `init_from_hydrate(&hydrate::Map)` which wraps a transaction.)

## 3. Reading & conflicts

All on `ReadDoc` (`src/read.rs`); `*_at(..., heads: &[ChangeHash])` variants exist
for everything:

```rust
fn get<O: AsRef<ExId>, P: Into<Prop>>(&self, obj: O, prop: P)
    -> Result<Option<(Value<'_>, ExId)>, AutomergeError>;
fn get_all<O: AsRef<ExId>, P: Into<Prop>>(&self, obj: O, prop: P)
    -> Result<Vec<(Value<'_>, ExId)>, AutomergeError>;   // all conflicting values
fn keys<O>(&self, obj: O) -> Keys<'_>;                    // Iterator<Item = String>
fn values<O>(&self, obj: O) -> Values<'_>;                // Iterator<Item = (Value<'_>, ExId)>
fn map_range<'a, O, R: RangeBounds<String> + 'a>(&'a self, obj: O, range: R) -> MapRange<'a>;
fn list_range<O, R: RangeBounds<usize>>(&self, obj: O, range: R) -> ListRange<'_>;
fn length<O>(&self, obj: O) -> usize;                     // 0 if obj unknown (no error!)
fn object_type<O>(&self, obj: O) -> Result<ObjType, AutomergeError>;
fn text<O>(&self, obj: O) -> Result<String, AutomergeError>;
fn parents<O>(&self, obj: O) -> Result<Parents<'_>, AutomergeError>;  // walk up to ROOT
fn iter(&self) -> DocIter<'_>;                            // whole doc, causal order
fn hydrate<O>(&self, obj: O, heads: Option<&[ChangeHash]>) -> Result<hydrate::Value, _>;
fn stats(&self) -> Stats;         // num_ops, num_changes, num_actors, versions
fn text_encoding(&self) -> TextEncoding;
fn get_missing_deps(&self, heads: &[ChangeHash]) -> Vec<ChangeHash>;
fn get_change_by_hash(&self, hash: &ChangeHash) -> Option<Change>;
```

`MapRange` yields `MapRangeItem { key: Cow<str>, value: ValueRef<'_>, conflict: bool, .. }`
(plus `.id() -> ExId`); `ListRange` yields `ListRangeItem { index, value, conflict, .. }`.
(Since 0.7 the range item `value` is a `ValueRef`, not `Value`.)

The `ExId` returned by `get`/`values` is: the object's id if the value is
`Value::Object(_)` — use it for nested access — otherwise the id of the op that
created the scalar (useful for disambiguating conflicts).

Reading pattern:

```rust
let contacts = match doc.get(automerge::ROOT, "contacts")? {
    Some((automerge::Value::Object(ObjType::List), contacts)) => contacts,
    _ => panic!("contacts should be a list"),
};
```

### Conflicts

When two actors concurrently `put` the same (obj, prop), automerge keeps **all**
values and deterministically (but arbitrarily) picks one winner. `get` returns the
winner; `get_all` returns every candidate as `(Value, ExId)` — the ExId tags which
op wrote it, and the winner is the same on every replica. Resolve a conflict simply
by doing a new `put` (it supersedes all conflicting predecessors). Conflict flags
also surface in `MapRangeItem::conflict` / `ListRangeItem::conflict` and in patches
(`PatchAction::PutMap { conflict, .. }`, `PatchAction::Conflict { prop }`).

```rust
let mut doc1 = AutoCommit::new();
let mut doc2 = AutoCommit::new();
doc1.put(ROOT, "field", "one")?;
doc2.put(ROOT, "field", "two")?;
doc1.merge(&mut doc2)?;
let all = doc1.get_all(ROOT, "field")?;   // len == 2, deterministic winner via get()
```

## 4. Text, cursors, marks

- Create with `let text = doc.put_object(ROOT, "content", ObjType::Text)?;`
- Edit with `doc.splice_text(&text, pos, del, "insertion")?` — `del: isize`;
  negative `del` deletes *before* `pos`.
- `doc.update_text(&text, "entire new value")?` diffs current vs new and emits
  minimal splices — use when you can't capture the user's individual edits (merges
  worse than real edit capture, but correct).
- Read with `doc.text(&text)? -> String`, historical `text_at(&text, &heads)`.
- Length: `doc.length(&text)` — in *encoding units*, not necessarily chars.
- `doc.put(&text, idx, 'c')` / `get(&text, idx)` also work on individual positions.

**Index units / TextEncoding**:

```rust
pub enum TextEncoding { UnicodeCodePoint, Utf8CodeUnit, Utf16CodeUnit, GraphemeCluster }
TextEncoding::platform_default()  // = UnicodeCodePoint unless a feature overrides it
```

- Default (no features): **Unicode code points** (i.e. Rust `char` count).
- Cargo feature `utf8-indexing` → `Utf8CodeUnit` (byte offsets); `utf16-indexing` →
  `Utf16CodeUnit` (what automerge JS/wasm uses — pick this to match a JS peer's
  indices).
- Per-document override: `Automerge::new_with_encoding(enc)` /
  `AutoCommit::new_with_encoding(enc)`, and `LoadOptions::new().text_encoding(enc)`.
  The encoding affects EVERY index into a text object: splice_text, mark start/end,
  cursors, length, patches. (See the exhaustive test `tests/text_encoding.rs`.)

**Cursors** (stable positions across edits):

```rust
fn get_cursor<O, I: Into<CursorPosition>>(&self, obj: O, position: I,
    at: Option<&[ChangeHash]>) -> Result<Cursor, AutomergeError>;   // MoveCursor::After
fn get_cursor_moving<O, I>(&self, obj: O, position: I, at: Option<&[ChangeHash]>,
    move_cursor: MoveCursor) -> Result<Cursor, AutomergeError>;
fn get_cursor_position<O>(&self, obj: O, cursor: &Cursor, at: Option<&[ChangeHash]>)
    -> Result<usize, AutomergeError>;

pub enum Cursor { Start, End, Op(OpCursor) }        // to_bytes()/TryFrom<&[u8]>, Display/FromStr
pub enum CursorPosition { Start, End, Index(usize) }  // From<usize>
pub enum MoveCursor { Before, After }                 // what to do if the char is deleted
```

```rust
let cursor = doc.get_cursor(&text, 9usize, None)?;
doc.splice_text(&text, 2, 0, "more")?;
let new_idx = doc.get_cursor_position(&text, &cursor, None)?;
```

**Marks / rich text** (Peritext model):

```rust
use automerge::marks::{Mark, ExpandMark};
doc.mark(&text, Mark::new("bold".to_string(), true, 1, 5), ExpandMark::Both)?;
doc.unmark(&text, "bold", 1, 5, ExpandMark::Both)?;

pub struct Mark { pub start: usize, pub end: usize, pub name: SmolStr, pub value: ScalarValue }
// Mark::new<V: Into<ScalarValue>>(name: String, value: V, start: usize, end: usize)
pub enum ExpandMark { Before, After, Both, None }   // Default = After
// ExpandMark controls whether text inserted at the boundary inherits the mark.
```

Reading marks (ReadDoc): `marks(&obj) -> Result<Vec<Mark>, _>`, `marks_at(&obj, heads)`
(historical, at heads — not positional), `get_marks(&obj, index, heads)` (marks
active at one index). Only one mark of a given name per position; overlapping
conflicting values resolve deterministically. Removing a mark stores a Null-valued
tombstone.

Blocks (`split_block`/`join_block`/`replace_block`), `spans()` iteration for
rendering, `update_spans` bulk diffing, rich-text patches, mark merge semantics,
and the rich-text sharp edges are covered in depth in
**`references/rich-text.md`** — read that before any marks/blocks work.

## 5. Save / load / fork / merge / actor IDs

```rust
// Whole-document (compact, compressed, deduplicated) format:
let bytes: Vec<u8> = doc.save();                 // AutoCommit: &mut self (commits first)
let doc2 = AutoCommit::load(&bytes)?;            // or Automerge::load
doc.save_nocompress();                           // skip DEFLATE
doc.save_with_options(SaveOptions { deflate: true, retain_orphans: true });
doc.save_and_verify()?;                          // save + test-load (slow, for paranoia)

// Incremental: only changes since last save()/save_incremental() — raw change bytes,
// suitable for appending to a log/file:
let delta: Vec<u8> = doc.save_incremental();     // AutoCommit only (tracks a save cursor)
let n = other.load_incremental(&delta)?;         // applies into existing doc; accepts either format
doc.save_after(&heads);                          // everything not a dependency of `heads`
                                                 // (the primitive save_incremental uses)

// Verification / partial loads:
AutoCommit::load_unverified_heads(&bytes)?;      // skip hash verification (debugging)
AutoCommit::load_with_options(&bytes, LoadOptions::new()
    .on_partial_load(OnPartialLoad::Ignore)      // or ::Error (default)
    .verification_mode(VerificationMode::DontCheck)  // or ::Check (default)
    .migrate_strings(StringMigration::ConvertToText) // convert Str scalars -> Text objects
    .text_encoding(TextEncoding::Utf16CodeUnit))?;
Automerge::rescue(&bytes)?;  // -> hydrate::Value; recover docs w/ invalid mark ordering
```

Typical persistence strategy: append `save_incremental()` output to a file after
each change (or after receiving sync messages); occasionally compact by rewriting
the file with `save()`. `load`/`load_incremental` accept concatenated change bytes
and document chunks. (Full pattern: `references/sync-and-persistence.md`.)

**Durability caveat**: `save()`/`save_incremental()` advance the AutoCommit-managed
save cursor *when called*, before you've durably written the returned bytes. If
the disk write fails, calling `save_incremental()` again does NOT regenerate the
lost batch — keep the exact returned bytes in a retry buffer until the write is
committed. For explicit durability semantics, track your own
`last_durable_heads: Vec<ChangeHash>`, produce chunks with
`save_after(&last_durable_heads)`, and advance that frontier only after the write
succeeds.

**Fork / merge:**

```rust
let mut doc2 = doc1.fork();                  // clone with a NEW random actor id
let mut doc3 = doc1.fork_at(&heads)?;        // fork as of a historical point
doc1.merge(&mut doc2)?;                      // -> Vec<ChangeHash> of applied changes
// AutoCommit::merge commits both sides' pending transactions first.
```

Prefer `fork()` over `clone()` for divergent copies: `clone()` keeps the same actor
id, and two documents making changes with the same actor id is corruption
(`AutomergeError::DuplicateActorId("possible document clone")`, `DuplicateSeqNumber`).

**Actor IDs**: every change is attributed to an `ActorId`; all changes by one actor
must be sequential — so an actor id must only ever be used from ONE place at a time
("at least one actor ID per device"). It's fine to generate a fresh actor per
session, but each distinct actor costs space forever, so reuse where possible.

```rust
doc.set_actor(ActorId::random());       // &mut Self; AutoCommit commits pending tx first
let doc = AutoCommit::new().with_actor(actor);
let actor: &ActorId = doc.get_actor();
let actor = ActorId::try_from("a3f9...")?;   // hex string
```

`AutoCommit::new()` / `Automerge::new()` already start with a random actor. Set it
explicitly when you want stable per-device identity persisted across restarts.

## 6. History and time travel

- `doc.get_heads() -> Vec<ChangeHash>` — current head hashes (like git: >1 hash
  when there are un-merged concurrent branches). `Automerge::get_heads(&self)`;
  `AutoCommit::get_heads(&mut self)` (commits pending tx first).
- Every `ReadDoc` read has an `*_at(..., &[ChangeHash])` variant: `get_at`,
  `get_all_at`, `keys_at`, `values_at`, `map_range_at`, `list_range_at`,
  `length_at`, `text_at`, `spans_at`, `marks_at`, `parents_at`, `iter_at`; cursors
  take `at: Option<&[ChangeHash]>`.
- `doc.get_changes(have_deps: &[ChangeHash]) -> Vec<Change>` — changes not
  reachable from `have_deps` (pass `&[]` for full history). `get_changes_meta` /
  `get_change_meta_by_hash` return `ChangeMetadata` cheaply — use these if you only
  need message/actor/timestamp (`Change` values are decompressed on demand).
- `doc.get_change_by_hash(&hash)`; `doc.get_last_local_change()`;
  `doc.get_changes_added(&mut other)` (changes in other not in self);
  `doc.hash_for_opid(&exid) -> Option<ChangeHash>`.
- `doc.apply_changes(changes)?` / `apply_changes_batch(changes)?` (batch is atomic
  and faster).
- `doc.diff(&before_heads, &after_heads) -> Vec<Patch>` — patches to transform the
  view at `before` into the view at `after` (either direction).

History walk example:

```rust
for change in doc1.get_changes(&[]) {
    let length = doc1.length_at(&cards, &[change.hash()]);
    println!("{} {}", change.message().unwrap_or(""), length);
}
```

- **Isolation** (`AutoCommit`): `doc.isolate(&heads)` pins the doc to a historical
  branch — reads AND new transactions operate against those heads (merges/sync
  received while isolated are hidden but not lost); `doc.integrate()` returns to
  the full document. On `Automerge` the analogue is
  `transaction_at(PatchLog, &heads) -> Result<Transaction, PatchLogMismatch>`.
- `doc.empty_change(CommitOptions) -> ChangeHash` — a change with no ops whose deps
  are all current heads ("merge commit").

## 7. Sync protocol summary

Types: `sync::State` (per-peer state — note: NOT a root-level `SyncState` type),
`sync::Message`, `sync::SyncDoc` trait, `sync::Have`, `sync::BloomFilter`.

```rust
pub trait SyncDoc {
    fn generate_sync_message(&self, sync_state: &mut State) -> Option<Message>;
    fn receive_sync_message(&mut self, sync_state: &mut State, message: Message)
        -> Result<(), AutomergeError>;
    fn receive_sync_message_log_patches(&mut self, sync_state: &mut State, message: Message,
        patch_log: &mut PatchLog) -> Result<(), AutomergeError>;
}
```

`Automerge` implements `SyncDoc` directly; for `AutoCommit` call `doc.sync()` to
get an `impl SyncDoc + '_` (commits pending tx first). Wire format:
`Message::encode(self) -> Vec<u8>`, `Message::decode(&[u8])`. Requires a
**reliable, in-order** transport; one `State` per (document, peer) pair.

The full two-peer loop, state-persistence rules, and read-only mode are in
`references/sync-and-persistence.md`.

## 8. Patches and observing changes

There is **no OpObserver** (removed in 0.5) — the patch-based API replaced it. Two
workflows:

**a) AutoCommit managed diff cursor** (easiest, for a UI materialized view):

```rust
let mut doc = AutoCommit::new();
// ... make changes / merge / receive sync messages ...
let patches: Vec<Patch> = doc.diff_incremental();   // patches since last call
// equivalent long-hand:
let heads = doc.get_heads();
let cursor = doc.diff_cursor();
let patches = doc.diff(&cursor, &heads);
doc.update_diff_cursor();
// doc.reset_diff_cursor() disables the (small) indexing overhead when not needed.
// doc.diff_obj(&obj, before, after, recursive)? scopes patches to one subtree.
```

The diff cursor starts inactive; call `doc.update_diff_cursor()` once after loading
to begin indexing, then `diff_incremental()` after each batch of changes.

**b) Explicit `PatchLog`** (works on `Automerge`, sync, load, merge):

```rust
use automerge::{PatchLog, Patch, PatchAction, sync::SyncDoc};
let mut patch_log = PatchLog::active();     // or PatchLog::inactive() / ::null()
doc.receive_sync_message_log_patches(&mut state, msg, &mut patch_log)?;
doc.merge_and_log_patches(&mut other, &mut patch_log)?;
doc.load_incremental_log_patches(&bytes, &mut patch_log)?;
doc.apply_changes_log_patches(changes, &mut patch_log)?;
let patches: Vec<Patch> = doc.make_patches(&mut patch_log);   // drains the log
// Automerge::current_state() -> Vec<Patch>  == diff(&[], heads): materialize from scratch
```

A `PatchLog` is bound to one document — using it with another document's
transaction methods returns `Err(PatchLogMismatch)`.

**Patch shape**:

```rust
pub struct Patch { pub obj: ObjId, pub path: Vec<(ObjId, Prop)>, pub action: PatchAction }
pub enum PatchAction {
    PutMap { key: String, value: (Value<'static>, ObjId), conflict: bool },
    PutSeq { index: usize, value: (Value<'static>, ObjId), conflict: bool },
    Insert { index: usize, values: SequenceTree<(Value<'static>, ObjId, bool)> },
    SpliceText { index: usize, value: ConcreteTextValue, marks: Option<MarkSet> },
    Increment { prop: Prop, value: i64 },
    Conflict { prop: Prop },
    DeleteMap { key: String },
    DeleteSeq { index: usize, length: usize },
    Mark { marks: Vec<Mark> },
}
```

`ConcreteTextValue::make_string()` extracts spliced text. A UI layer matches on
`action`, using `path`/`obj` to locate the widget (see `examples/watch.rs` in the
repo for a complete match). `hydrate::Value::apply_patches(&mut self, TextEncoding,
patches)` can maintain a plain hydrated mirror of the doc automatically.

## 9. Explicit transactions on `Automerge`

```rust
// Closure style — commits on Ok, rolls back on Err:
pub fn transact<F, O, E>(&mut self, f: F) -> transaction::Result<O, E>
    where F: FnOnce(&mut Transaction<'_>) -> Result<O, E>;
pub fn transact_with<F, O, E, C>(&mut self, c: C, f: F) -> transaction::Result<O, E>
    where C: FnOnce(&O) -> CommitOptions;    // c builds commit options from the result
// + transact_and_log_patches / transact_and_log_patches_with (patch_log in Success)

pub type transaction::Result<O, E> = std::result::Result<Success<O>, Failure<E>>;
pub struct Success<O> { pub result: O, pub hash: Option<ChangeHash>, pub patch_log: PatchLog }
pub struct Failure<E> { pub error: E, pub cancelled: usize }

// Manual style:
let mut tx = doc.transaction();                       // Transaction<'_>
tx.put(ROOT, "k", "v")?;
let (hash, patch_log) = tx.commit();                  // or tx.commit_with(CommitOptions)
// tx.rollback() -> usize (ops cancelled). Dropping an uncommitted Transaction ROLLS BACK.

pub struct CommitOptions { pub message: Option<String>, pub time: Option<i64> }
CommitOptions::default().with_message("Add card").with_time(now_secs); // time = unix SECONDS
```

Canonical pattern (note the turbofish to pin the error type):

```rust
let (cards, card1) = doc1.transact_with::<_, _, AutomergeError, _>(
    |_| CommitOptions::default().with_message("Add card".to_owned()),
    |tx| {
        let cards = tx.put_object(ROOT, "cards", ObjType::List)?;
        let card1 = tx.insert_object(&cards, 0, ObjType::Map)?;
        tx.put(&card1, "title", "Rewrite everything in Clojure")?;
        tx.put(&card1, "done", false)?;
        Ok((cards, card1))
    },
).unwrap().result;
```

`AutoCommit` commit surface: `commit() -> Option<ChangeHash>`,
`commit_with(CommitOptions)`, `rollback() -> usize` (undoes the *pending*
uncommitted ops), `empty_change(CommitOptions)`. A transaction with zero ops
commits to `None` (no change created).

## 10. hydrate, serde, automerge-test

**`automerge::hydrate`** — plain-Rust snapshot values:

```rust
pub enum hydrate::Value { Scalar(ScalarValue), Map(Map), List(List), Text(Text) }
// From impls: &str, i64/i32/u64/u32/f64/f32, ScalarValue, Map, List, Text, HashMap<&str, Value>
let v: hydrate::Value = doc.hydrate(&obj, None)?;             // ReadDoc method; heads optional
// macros: hydrate_map!{ "k" => v, ... }, hydrate_list![v1, v2], hydrate_text!("s")
// Value::apply_patches(&mut self, text_encoding, patches) keeps a snapshot in sync.
```

Used as input for `splice`, `batch_create_object`, `update_object`,
`init_root_from_hydrate`.

**Serde**: `automerge::AutoSerde::from(&doc)` implements `serde::Serialize` for any
`ReadDoc` — JSON export in one line:

```rust
let serialized = serde_json::to_string(&automerge::AutoSerde::from(&doc)).unwrap();
```

(Conflicts silently resolve to the winner; counters serialize as ints.) There is no
built-in Deserialize — for typed struct mapping use `autosurgeon`.

**`automerge-test` crate** (dev-dependency `automerge-test = "0.11"`):

```rust
use automerge_test::{assert_doc, assert_obj, map, list, new_doc, sorted_actors, mk_counter};

let mut doc = new_doc();     // AutoCommit with a fresh random actor
// ... build doc ...
assert_doc!(&doc, map! {
    "todos" => { list![ { map!{ "title" => { "water plants" } } } ] }
});
```

- `assert_doc!(doc_ref, expected)` — compares the *whole realized document*,
  including conflicts. Every value is wrapped in `{ ... }` because each prop is a
  **set** of conflicting values: `map!{ "field" => { "one", "two" } }` asserts a
  2-way conflict.
- `assert_obj!(doc, obj_id, prop, expected)` — scope to a subtree.
- `new_doc()`, `new_doc_with_actor(actor)`, `sorted_actors()` (two actors with
  known order — deterministic conflict winners), `mk_counter(i64)`.
- Works with anything implementing `ReadDoc`; pass `&doc` for `AutoCommit`.

## 11. Cargo features

- *(none by default)* — text indices are Unicode code points.
- `utf8-indexing` — default `TextEncoding` = UTF-8 code units.
- `utf16-indexing` — default = UTF-16 code units (matches automerge JS/wasm peers).
- `wasm` — js-sys/wasm-bindgen glue for the automerge-wasm build (not needed for
  ordinary wasm32 users).
- `optree-visualisation`, `slow_path_assertions` — debugging/internal.

MSRV: Rust 1.90 (v0.11). `AutoCommit` is `Send` but NOT `Sync` — wrap in a mutex
for shared access.

## 12. Pitfalls

1. **ExId validity**: `ObjId` == `ExId` and encodes `(op counter, ActorId)` —
   equality/hash ignore the doc-internal index, so IDs are stable across forks,
   merges, save/load of the *same document lineage*. But resolving an ExId in a
   document that never contained that object errors (`InvalidObjId`). Never mix IDs
   between unrelated documents. After `merge(&mut doc2)`, IDs obtained from doc2
   are valid in doc1.
2. **`put` vs `insert` on lists**: `put(list, i, v)` *overwrites* index i (error if
   out of bounds); `insert(list, i, v)` shifts right (i may equal `length` to
   append). Confusing them silently corrupts intent or errors with `InvalidIndex`.
3. **Strings are registers; Text is a CRDT**: `doc.put(obj, "k", "some string")`
   stores `ScalarValue::Str` — concurrent edits conflict wholesale. For
   collaborative editing use `put_object(obj, "k", ObjType::Text)` +
   `splice_text`/`update_text`. `LoadOptions::migrate_strings(StringMigration::ConvertToText)`
   exists to migrate old docs.
4. **Text index units**: all text indices/lengths are in the document's
   `TextEncoding` units (default: unicode code points, NOT bytes and NOT graphemes).
   `doc.length(&text)` ≠ `doc.text(&text)?.len()` in general. Interoperating with
   automerge JS requires `utf16-indexing` (or `new_with_encoding`) or indices will
   disagree. Splicing mid-codepoint errors (`InvalidCharacter`).
5. **Counter merge semantics**: counters sum concurrent increments — never emulate
   a counter with `put(get+1)`. `increment` on a non-counter fails with
   `MissingCounter`.
6. **Duplicate objects on concurrent init**: two fresh devices each running
   `put_object(ROOT, "todos", ObjType::List)` then merging yields TWO conflicting
   list objects — one wins, the other's contents seem to vanish (visible via
   `get_all`). Initialize once and distribute the bytes.
7. **One actor per device/thread of execution**: same actor id used concurrently in
   two replicas ⇒ `DuplicateActorId`/`DuplicateSeqNumber` and potential corruption.
   Use `fork()` (fresh actor), not `clone()`.
8. **AutoCommit `&mut` reads**: `get_heads`, `get_changes`, `save`, `document()`
   etc. take `&mut self` because they commit the implicit transaction. This
   surprises code holding `&AutoCommit`.
9. **Dropped `Transaction` rolls back** silently. Always `commit()`/`commit_with`
   (or use the `transact*` closures; returning `Err` rolls back all ops).
10. **`load` verification**: `load` verifies change hashes. `load_unverified_heads`
    / `VerificationMode::DontCheck` skip it (debugging, or trusted local storage
    for speed); `OnPartialLoad::Ignore` salvages a truncated file;
    `Automerge::rescue` recovers docs with invalid mark ordering.
11. **Performance**: batch many ops into one transaction/commit; prefer
    `batch_create_object`/`init_root_from_hydrate`/`splice` for bulk data; prefer
    `save_incremental()` over repeated full `save()`; `apply_changes_batch` over
    looped `apply_changes`; `get_changes_meta` over `get_changes` when you only
    need metadata; `reset_diff_cursor` when patches aren't needed.
12. **Sync**: reliable in-order transport required; one `sync::State` per peer per
    doc; only persist `state.encode()`; keep calling `generate_sync_message` after
    every receive until it returns `None`.
13. **`length` of an unknown object returns 0** rather than erroring — check
    `object_type` to distinguish "missing" from "empty".
14. **`Prop::from(f64)` exists** (JS interop); prefer `usize` for list indices.

## 13. API drift vs older tutorials

Things an agent will trip on when copying pre-2024 blog/tutorial code:

- **0.5.0**: `OpObserver`/`VecOpObserver` REMOVED → patch API (`*_log_patches`
  methods + `PatchLog` + `make_patches`; `AutoCommit::{diff, diff_incremental}`).
  Added `Cursor`, `isolate`/`integrate`, `transaction_at`.
- **0.5.6**: added `update_text`. **0.5.10**: block/spans APIs.
- **0.6.0**: `new_with_encoding`; cursor Start/End + `MoveCursor`.
- **0.7.0** (big rewrite — columnar storage at runtime, ~100x lower steady-state
  memory): `get_changes` et al. return owned `Change`; `TextRepresentation` type
  REMOVED (`TextEncoding` replaces it); `Mark` lost its lifetime param and
  `Mark::data` split into `Mark::{name, value}`; `MapRangeItem`/`ListRangeItem`
  `value` is now `ValueRef`, `key` is `Cow<str>`, `id` field → `.id()` method;
  `Span::Text` became a struct variant; added `ReadDoc::iter`,
  `apply_changes_batch`.
- **0.8.0**: `splice` takes `Into<hydrate::Value>` items; added
  `batch_create_object`, `init_root_from_hydrate`; fixed O(n²) `load_incremental`.
- **0.9.0**: read-only sync (`State::new_read_only`, `set_read_only`);
  `sync::Message::supported_capabilities` → `Message::flags`.
- **0.10.0**: `transaction_log_patches`/`transaction_at`/`into_transaction` return
  `Result<_, PatchLogMismatch>` (breaking).
- **0.11.0**: MSRV 1.90; `Change::message` returns `Option<&str>`; strict
  mark-ordering validation on load (use `Automerge::rescue` for old corrupt docs);
  new `hexane` columnar engine underneath; `anonymize()`.

Also: the Rust crate has no `Repo`/`DocHandle` — that's the automerge-repo pattern
(JS, and `samod` in Rust — see `references/sync-and-persistence.md`).
