# `autosurgeon` crate reference (v0.13)

Verified against autosurgeon v0.13.0 source (pairs with automerge 0.11). Repo:
https://github.com/automerge/autosurgeon · docs: https://docs.rs/autosurgeon

## Contents

1. [What autosurgeon is](#1-what-autosurgeon-is)
2. [Traits — exact shapes](#2-traits--exact-shapes)
3. [Derive macros & attributes](#3-derive-macros--attributes)
4. [Keys and list merging mechanics](#4-keys-and-list-merging-mechanics)
5. [Special types](#5-special-types)
6. [Working with docs, transactions, save/load](#6-working-with-docs-transactions-saveload)
7. [Schema evolution / versioning](#7-schema-evolution--versioning)
8. [Pitfalls checklist](#8-pitfalls-checklist)
9. [Cargo.toml & version pairing](#9-cargotoml--version-pairing)
10. [API drift vs old tutorials](#10-api-drift-vs-old-tutorials)
11. [Manual impl templates](#11-manual-impl-templates)

---

## 1. What autosurgeon is

A serde-inspired mapping layer between Rust types and automerge documents. Two core
traits:

- **`Reconcile`** — "take a Rust value and update an automerge document to match
  it". This is NOT serialization: it *diffs* the value against the current document
  state and emits minimal automerge operations (puts/inserts/deletes/splices).
  Unchanged parts of the doc are untouched, so concurrent edits merge sensibly.
- **`Hydrate`** — "construct a Rust value from an automerge document"
  (deserialization analog).

Top-level functions (all re-exported at crate root):

```rust
pub fn reconcile<R: Reconcile, D: Doc>(doc: &mut D, value: R) -> Result<(), ReconcileError>;
pub fn reconcile_prop<'a, D: Doc, R: Reconcile, O: AsRef<automerge::ObjId>, P: Into<Prop<'a>>>(
    doc: &mut D, obj: O, prop: P, value: R) -> Result<(), ReconcileError>;
pub fn reconcile_insert<D: Doc, R: Reconcile>(
    doc: &mut D, obj: automerge::ObjId, idx: usize, value: R) -> Result<(), ReconcileError>;
pub fn hydrate<D: ReadDoc, H: Hydrate>(doc: &D) -> Result<H, HydrateError>;   // hydrates ROOT map
pub fn hydrate_prop<'a, D: ReadDoc, H: Hydrate, P: Into<Prop<'a>>, O: AsRef<automerge::ObjId>>(
    doc: &D, obj: O, prop: P) -> Result<H, HydrateError>;
pub fn hydrate_path<'a, D: ReadDoc, H: Hydrate, P: IntoIterator<Item = Prop<'a>>>(
    doc: &D, obj: &automerge::ObjId, path: P) -> Result<Option<H>, HydrateError>;
pub fn hydrate_key<'a, D: ReadDoc, H: Hydrate + Clone>(
    doc: &D, obj: &automerge::ObjId, outer: Prop<'a>, inner: Prop<'a>)
    -> Result<LoadKey<H>, ReconcileError>;
```

Crate root exports: `Counter`, `Text`, `Doc`, `ReadDoc`, the functions above,
`Hydrate`, `HydrateError`, `MaybeMissing`, `Reconcile`, `ReconcileError`,
`Reconciler`, `Prop`, the `bytes` module (`ByteArray<N>`, `ByteVec`), the
`map_with_parseable_keys` module, and the derive macros `Hydrate`/`Reconcile`.

`Prop<'a>` is autosurgeon's own enum (not automerge's): `Prop::Key(Cow<'a, str>)` |
`Prop::Index(u32)`. `From` impls for `&str`, `Cow<str>`, `u32`, `usize`,
`automerge::Prop`. So
`hydrate_path(&doc, &ROOT, vec!["companies".into(), 0usize.into(), "name".into()])`
works.

**Where the serde analogy breaks:**

- `reconcile` is stateful/diff-based: it reads the doc while writing. Writing the
  same value twice is a no-op; a changed value emits only the delta.
- No `Deserializer`-style visitor; `Hydrate` has *no required methods* — you
  override the `hydrate_*` method for the automerge type you expect
  (`hydrate_string`, `hydrate_map`, `hydrate_seq`, `hydrate_uint`, ...). Anything
  else returns `HydrateError::Unexpected(...)`.
- `Reconcile` carries an identity concept (`type Key<'a>`, `key()`,
  `hydrate_key()`) that serde has no analog for — it drives list/map merge identity
  (see §4).
- Incremental updates are not handled: after merging remote changes you must
  re-`hydrate` your structs from the doc. Special types (`Text`, `Counter`)
  additionally record the heads they were hydrated at and error with `StaleHeads`
  if the doc moved.
- Top level of a document must be a map: `reconcile(&mut doc, 5)` or a `Vec` at
  root fails with `ReconcileError::TopLevelNotMap`.

## 2. Traits — exact shapes

```rust
pub trait Reconcile {
    type Key<'a>: PartialEq;                 // use autosurgeon::reconcile::NoKey if none
    fn reconcile<R: Reconciler>(&self, reconciler: R) -> Result<(), R::Error>;  // required
    fn hydrate_key<'a, D: ReadDoc>(doc: &D, obj: &automerge::ObjId, prop: Prop<'_>)
        -> Result<LoadKey<Self::Key<'a>>, ReconcileError> { Ok(LoadKey::NoKey) } // default
    fn key(&self) -> LoadKey<Self::Key<'_>> { LoadKey::NoKey }                   // default
}

pub enum LoadKey<K> { NoKey, KeyNotFound, Found(K) }  // has .map()
pub struct NoKey;                                     // placeholder Key type

pub trait Hydrate: Sized {
    fn hydrate<D: ReadDoc>(doc, obj, prop) -> Result<Self, HydrateError>;  // default dispatches by value type
    fn hydrate_scalar(Cow<ScalarValue>) / hydrate_bool(bool) / hydrate_bytes(&[u8])
       / hydrate_f64(f64) / hydrate_counter(i64) / hydrate_int(i64) / hydrate_uint(u64)
       / hydrate_string(&str) / hydrate_timestamp(i64) / hydrate_unknown(u8, &[u8])
       / hydrate_map<D>(doc, obj) / hydrate_seq<D>(doc, obj) / hydrate_text<D>(doc, obj)
       / hydrate_none()
    // all default to Err(HydrateError::Unexpected(...))
}
```

The `Reconciler` trait (what you drive inside a manual `Reconcile::reconcile`):
scalar methods `none()`, `bytes(B)`, `timestamp(i64)`, `boolean(bool)`, `str(S)`,
`u64(u64)`, `i64(i64)`, `f64(f64)`; composite entry points `map() -> MapReconciler`,
`seq() -> SeqReconciler`, `text() -> TextReconciler`, `counter() -> CounterReconciler`;
plus `heads()`. Each scalar method checks the current doc value first — it only
writes if different.

These composite reconcilers are traits in `autosurgeon::reconcile` — import them
(`use autosurgeon::reconcile::{MapReconciler, SeqReconciler};` etc.) or their
methods won't resolve in manual impls.

- `MapReconciler`: `entries()`, `entry(prop)`, `put(prop, value)`, `delete(prop)`,
  `hydrate_entry_key::<R,_>(prop)`, `replace(prop, value)` (delete+put),
  `retain(pred)`.
- `SeqReconciler`: `items()`, `get(idx)`, `hydrate_item_key::<R>(idx)`,
  `insert(idx, value)`, `set(idx, value)`, `delete(idx)`, `len()`, `is_empty()`.
- `TextReconciler`: `splice(pos, delete: isize, insert)`, `update(new_text)`,
  `heads()`.
- `CounterReconciler`: `increment(by: i64)`, `set(value: i64)`.

Error types:

```rust
pub enum ReconcileError { Automerge(automerge::AutomergeError), TopLevelNotMap, StaleHeads(StaleHeads) }
pub struct StaleHeads { pub expected: Vec<ChangeHash>, pub found: Vec<ChangeHash> }
pub enum HydrateError { Automerge(...), Unexpected(Unexpected), ParseMapKey(Box<dyn Error+Send+Sync>) }
impl HydrateError { pub fn unexpected<S: AsRef<str>>(expected: S, found: String) -> Self }
```

`Doc`/`ReadDoc` abstractions: autosurgeon's `ReadDoc` is implemented for
`automerge::AutoCommit`, `automerge::Automerge`, and
`automerge::transaction::Transaction<'_>`. `Doc` (write side) is
blanket-implemented for any `T: Transactable + ReadDoc` — so both `AutoCommit` and
`Transaction` can be reconciled into; plain `Automerge` is read-only (hydrate only).

## 3. Derive macros & attributes

```rust
#[proc_macro_derive(Hydrate, attributes(autosurgeon))]
#[proc_macro_derive(Reconcile, attributes(key, autosurgeon))]
```

Note: `#[key]` is a *bare* attribute (`#[key]`, not `#[autosurgeon(key)]`),
registered only by the `Reconcile` derive.

### `#[autosurgeon(...)]` attribute forms

All values are string literals containing paths. Exact recognized names:
`reconcile`, `reconcile_with`, `with`, `hydrate`, `missing`, `rename`. Anything
else → "unknown attribute" compile error.

| Attribute | Where | Meaning |
|---|---|---|
| `#[autosurgeon(reconcile = "fn_path")]` | field or container (Reconcile derive) | function with the signature of `Reconcile::reconcile`: `fn f<R: Reconciler>(&T, R) -> Result<(), R::Error>`. Loses key info (wrapper uses `NoKey`). Not allowed on enum newtype fields. |
| `#[autosurgeon(reconcile_with = "module_path")]` | field or container | module providing `reconcile`, plus `type Key<'a>`, `fn hydrate_key`, `fn key` — keeps merge-identity support. Mutually exclusive with `reconcile` and `with`. |
| `#[autosurgeon(hydrate = "fn_path")]` | field or container (Hydrate derive) | function with the signature of `Hydrate::hydrate`: `fn f<D: ReadDoc>(&D, &automerge::ObjId, Prop<'_>) -> Result<T, HydrateError>`. |
| `#[autosurgeon(with = "module_path")]` | field or container | module with both `reconcile` and `hydrate` fns (and optionally `Key`/`hydrate_key`/`key` for keyed reconcile). Mutually exclusive with the others. |
| `#[autosurgeon(missing = "fn_path")]` | field (Hydrate derive) | zero-arg function returning the field value, used when the property is absent from the document. E.g. `missing = "Default::default"`. |
| `#[autosurgeon(rename = "name")]` | field or enum variant | use `name` as the map key / variant name in the document (both derives). Only `rename` is allowed on enum variants. |
| `#[key]` | field (named or tuple position) | marks the identity field for list/map merging. Only one per struct/variant. Also usable inside enum struct/tuple variants. |

Combining is allowed, e.g.
`#[key] #[autosurgeon(reconcile = "reconcile_userid", hydrate = "hydrate_userid")]`
on one field.

A `with=`/`reconcile_with=` module that supports keys looks like:

```rust
mod autosurgeon_userid {
    use autosurgeon::{hydrate::{hydrate_path, Hydrate, HydrateResultExt},
                      reconcile::LoadKey, ReadDoc, Reconcile, Reconciler};
    pub type Key<'a> = std::borrow::Cow<'a, String>;
    pub(super) fn reconcile<R: Reconciler>(id: &UserId, reconciler: R) -> Result<(), R::Error> {
        id.0.reconcile(reconciler)
    }
    pub(super) fn hydrate_key<'k, D: ReadDoc>(doc: &D, obj: &automerge::ObjId, prop: autosurgeon::Prop<'_>)
        -> Result<LoadKey<Key<'k>>, autosurgeon::ReconcileError> {
        let val = hydrate_path::<_, std::borrow::Cow<'_, String>, _>(doc, obj, std::iter::once(prop))
            .strip_unexpected()?;      // HydrateResultExt: turns Unexpected errors into None
        Ok(val.map(LoadKey::Found).unwrap_or(LoadKey::KeyNotFound))
    }
    pub(super) fn key(u: &UserId) -> LoadKey<Key<'_>> { LoadKey::Found(std::borrow::Cow::Borrowed(&u.0)) }
    pub(super) fn hydrate<D: ReadDoc>(doc: &D, obj: &automerge::ObjId, prop: autosurgeon::Prop<'_>)
        -> Result<UserId, autosurgeon::HydrateError> {
        Ok(UserId(String::hydrate(doc, obj, prop)?))
    }
}
```

### Document representation (serde-like)

```rust
struct W { a: i32, b: i32 }   // {"a":0,"b":0}          (map)
struct X(i32, i32);           // [0,0]                  (list)
struct Y(i32);                // 0                      (transparent newtype)
enum E { W{a:i32,b:i32}, X(i32,i32), Y(i32), Z }
E::W{..}  // {"W": {"a":0,"b":0}}
E::X(0,0) // {"X": [0,0]}
E::Y(0)   // {"Y": 0}
E::Z      // "Z"              (plain string!)
```

- Unit-only enums reconcile to a string and hydrate via `hydrate_string` (unknown
  string → `HydrateError::unexpected` listing expected variants).
- Non-unit variants reconcile to a single-key map. When the variant *changes*, the
  generated code retains only the new variant's key — old variant keys are deleted.
- Unit enum variants act as their own key (so `Vec<Fruit>` merges by value identity).
- Newtype structs are transparent for both derives, and their key passes through
  (a `Vec<SpecialCereal(Cereal)>` with `#[key] id` inside `Cereal` still merges by id).
- `#[key]` works in tuple structs (`struct NameWithIndex(String, #[key] u64)`) and
  in enum struct/tuple variants
  (`Vehicle::Car { #[key] id, ... }`, `TempReading::Celsius(#[key] String, f64)`).

The derived `Reconcile` for a struct with `#[key] id: T` generates
`type Key<'k> = Cow<'k, T>`, `key()` returning `LoadKey::Found(Cow::Borrowed(&self.id))`,
and `hydrate_key` that reads the `id` property — so the key field's type must
implement `Hydrate + Clone + PartialEq`.

## 4. Keys and list merging mechanics

Without keys, `Vec<T>` reconciliation runs an LCS diff (via the `similar` crate)
between old document items and new items, where "equality" is:

- both have keys → keys equal?
- exactly one has a key → not equal
- neither has a key → equal iff **same index** (purely positional)

So without `#[key]`, inserting at the front of a list is indistinguishable from
"update every element and append one" → merges produce conflicts and duplicates.
With `#[key]` the LCS aligns by identity and concurrent insert-at-front + remove
merges cleanly.

Update-vs-replace decision (`MapReconciler::put`, `SeqReconciler::set`, and
`reconcile_prop` all use identical logic):

```rust
let create_new_object = match (existing_key, new_key) {
    (LoadKey::Found(before), LoadKey::Found(after)) if before == after => false, // update in place
    (LoadKey::Found(_), _) | (_, LoadKey::Found(_)) => true,                     // replace with new object
    _ => false,                                                                  // no keys: update in place
};
```

Replacing creates a brand-new object rather than mutating the old one — important
for CRDT semantics: a "different identity" value doesn't inherit the merge history
of the old one.

`LoadKey::KeyNotFound` vs `NoKey`: `NoKey` = the type has no key concept;
`KeyNotFound` = has a key but it couldn't be loaded (e.g. `Option::None`, or absent
in doc).

Primitives (`String`, `str`, ints, floats, `bool`, `Uuid`) implement `key()` as
their own value — so `Vec<String>`/`Vec<Uuid>` merge by value identity, not
position. `Vec<T>` itself has `type Key = NoKey`.

Key hygiene: the key should be stable, unique, and semantically immutable —
changing it means "replace this object", not "edit it". Reconciliation does not
reject duplicate keys (duplicates make identity matching ambiguous — enforce
uniqueness in application validation), and float keys are a bad idea (`NaN`
comparisons). Generate IDs from a real ID source, never from list positions.

## 5. Special types

### `autosurgeon::Text`

Reconciles to `automerge::ObjType::Text`. Internal state: `Fresh(String)` (built
via `Text::with_value(s)` / `From<S: AsRef<str>>` / `Default`) or `Rehydrated`
(value + pending edits + source ObjId + the heads it was hydrated at).

API: `Text::with_value(s)`, `splice(pos: usize, del: isize, insert: S)` (negative
`del` deletes before `pos`; positions are byte indices that must be char boundaries
— use `char_indices`), `update(new_value)` (diffs old vs new by graphemes and
converts to splices), `as_str()`. `PartialEq`/`Eq` compare string content.

**Encoding requirement (verified in source)**: the recorded splices are Rust
`String` byte offsets, and autosurgeon's reconciler forwards `pos`/`del` unchanged
into `Transactable::splice_text` — where automerge interprets them in the
document's `TextEncoding` (default: Unicode code points). The two agree only for
ASCII. Any document using `autosurgeon::Text` with possibly-non-ASCII content must
use `TextEncoding::Utf8CodeUnit`: enable the `utf8-indexing` feature on
`automerge`, or use `new_with_encoding(TextEncoding::Utf8CodeUnit)` on creation
AND `LoadOptions::new().text_encoding(...)` on every load. Assert
`doc.text_encoding()` in a boundary test and exercise emoji/multibyte edits.

Intended workflow: hydrate struct → call `splice`/`update` → `reconcile` back into
the *same* doc state. Reconciling a `Rehydrated` Text checks the doc's heads and
returns `ReconcileError::StaleHeads` if the doc changed since hydration.
Reconciling a `Fresh` Text where a text object already exists **replaces it with a
new text object** (losing merge affinity with concurrent edits). Concurrent splices
on the same text object merge character-wise.

### `autosurgeon::Counter`

Reconciles to `ScalarValue::Counter`. `Counter::with_value(i64)`, `Default` (0),
`increment(by: i64)`, `value() -> i64`. `Fresh` counters `set` the value;
`Rehydrated` counters emit only the *increment delta* since hydration, so
concurrent increments sum on merge (+5 and +3 → 8).

Two hazards (verified in source): `Reconcile` takes `&self` and never clears the
pending delta, so reconciling the same incremented rehydrated `Counter` twice
applies the increment twice — treat a dirty counter as single-use and rehydrate
after reconciling. And `Counter` implements only `Clone`/`Debug` (no
`PartialEq`), so a struct containing one can't derive `PartialEq`; compare
`counter.value()` in tests.

### Numbers

- `u8/u16/u32/u64` → `ScalarValue::Uint`; `i8/i16/i32/i64` → `Int`; `f64` → `F64`;
  `f32` reconciles `as f64` and hydrates `as f32`.
- `usize`/`isize`/`u128`/`i128`: **no impls** — use fixed-size types.
- Hydration is strict per family: a doc `Int` hydrated into `u64` errors
  `unexpected int`; no cross-coercion among Int/Uint/F64. Out-of-range narrowing
  errors. Choose numeric types consistently on all peers (a JS peer writes
  `F64`/`Int` depending on the value — hydrating into `u64` will fail).

### `Option<T>`

`None` reconciles to `ScalarValue::Null`. Hydrate: `Null` → `None`; a *completely
absent* property → **error** (`unexpected("a ScalarValue::Null", "nothing at all")`),
not `None`! Use `#[autosurgeon(missing = "Default::default")]` or `MaybeMissing<T>`.
`Option<T>`'s reconcile key delegates to `T` (`None` → `KeyNotFound`).

### `MaybeMissing<T>`

`enum MaybeMissing<T> { #[default] Missing, Present(T) }` — hydrates to `Missing`
when the property is absent; `Missing` **writes nothing** on reconcile (it does not
delete an existing doc value either). Combine `MaybeMissing<Option<String>>` to
distinguish absent / null / value. Has `unwrap_or_else(f)`.

### Maps

`HashMap<K, V>` / `BTreeMap<K, V>`: `Reconcile` requires `K: AsRef<str>`, `Hydrate`
requires `K: From<String>` (+ `Hash+Eq` / `Ord`). Reconcile **deletes doc keys not
present in the map** and respects value keys (replaces the entry when `V::key`
differs). For non-string keys implementing `FromStr`/`ToString`:

```rust
#[derive(Reconcile, Hydrate)]
struct MyDocument {
    #[autosurgeon(with = "autosurgeon::map_with_parseable_keys")]
    items: std::collections::HashMap<u16, String>,
}
```

### Bytes

`autosurgeon::bytes::ByteArray<const N: usize>` and `ByteVec` (over `[u8; N]` /
`Vec<u8>`) reconcile to `ScalarValue::Bytes`. Plain `Vec<u8>` reconciles as a
*list of Uint* (via the generic Vec impl) — use `ByteVec` for byte blobs.

### Uuid (feature `uuid`)

`features = ["uuid"]` → `Reconcile`/`Hydrate` for `uuid::Uuid`, stored as
`ScalarValue::Bytes` (16 bytes), with itself as the key, so `Vec<Uuid>` merges by
identity.

### Timestamps / chrono

No chrono or SystemTime support in 0.13. The plumbing exists
(`Reconciler::timestamp(i64)` → `ScalarValue::Timestamp`,
`Hydrate::hydrate_timestamp(i64)`); to use timestamps write a manual impl or a
`with=` module calling those.

### Other std impls and known limitations

`Box<T>` (both traits), `&T` (Reconcile), `Cow<'_, T>` (Hydrate), `[T]` slices
(Reconcile only), `bool`, `String`/`str`.

NOT supported (verified by compile errors on 0.13): tuples (`(A, B)` has no
impls — use a tuple *struct*), fixed arrays `[T; N]` (use `Vec<T>`, or `ByteArray`
for bytes), unit structs (the derives reject them), `usize`/`isize`/128-bit ints.
There is also no hydrate-at-heads (no historical typed reads — use raw `*_at` for
that), no set type mapping, and no serde-style `skip`/`flatten`/`rename_all`/
aliases/tagging control — when the stored schema differs materially from the app
model, use a persisted DTO type or manual impls. One version-specific sharp edge:
`Option<TransparentNewtype>` hydration can bypass the newtype's derived method for
scalar values (autosurgeon issue #45) — if hit, write a manual scalar `Hydrate`
for the newtype and pin a regression test.

## 6. Working with docs, transactions, save/load

```rust
// AutoCommit (most common)
let mut doc = automerge::AutoCommit::new();
reconcile(&mut doc, &value)?;
let bytes = doc.save();                       // persist
let mut doc = automerge::AutoCommit::load(&bytes)?;
let value: MyType = hydrate(&doc)?;

// Explicit transaction on an Automerge document
let mut doc = automerge::Automerge::new();
let mut tx = doc.transaction();
reconcile(&mut tx, &value)?;                  // Transaction implements Doc
tx.commit();
let value: MyType = hydrate(&doc)?;           // Automerge implements ReadDoc (read-only)

// Fork/merge flow (the canonical pattern)
let mut doc2 = doc.fork().with_actor(automerge::ActorId::random());
let mut c2: Contact = hydrate(&doc2)?;
c2.name = "Dangermouse".into();
reconcile(&mut doc2, &c2)?;
contact.address.line_one = "221C Baker St".into();
reconcile(&mut doc, &contact)?;
doc.merge(&mut doc2)?;                        // merge-then-hydrate
let merged: Contact = hydrate(&doc)?;
```

Subtrees: `reconcile_prop(&mut doc, automerge::ROOT, "numbers", &vec![1,2,3])`
targets one property; `reconcile_insert` inserts into a list index (useful when the
type has no key); `hydrate_prop(&doc, &ROOT, "status")` reads one property;
`hydrate_path(&doc, &ROOT, vec!["companies".into(), 0usize.into(), "name".into()])`
walks a path, returning `Ok(None)` if any segment is missing.

When merge conflicts exist, hydrate reads automerge's deterministic winner;
conflicting values remain in the doc (visible via `get_all` / `assert_doc!`).

## 7. Schema evolution / versioning

- **Adding a field**: hydrating an old doc fails (`Unexpected` "nothing at all",
  even for `Option`). Fixes: `#[autosurgeon(missing = "Default::default")]` (or any
  zero-arg fn path returning the field type), or make the field `MaybeMissing<T>`.
  Example: `#[autosurgeon(missing="Visibility::default")] visibility: Visibility`
  with `#[derive(Hydrate, Default)] enum Visibility { #[default] Public, Private }`.
- **Removing a field**: derived struct `Reconcile` only `put`s its own fields — it
  never deletes unknown map keys (unlike `HashMap` reconcile). Stale keys persist
  in the doc; old readers keep working.
- **Enums gaining variants**: an old binary hydrating a doc with a new unit variant
  string gets `HydrateError::Unexpected`. There is no `#[serde(other)]` equivalent
  — handle by matching on `Err(HydrateError::Unexpected(_))` and substituting a
  default, or version the document (e.g. a `version: u64` root field checked before
  hydrating).
- **Renaming fields**: `#[autosurgeon(rename = "api-key")]` sets the *stored* name
  (useful for non-identifier names, or keeping the doc name stable while renaming
  the Rust field). It is NOT an alias for an old stored name — reading documents
  written under a previous name requires an explicit migration.
- Errors are non-granular: `HydrateError` doesn't carry the path to the failing
  field; add context yourself when it matters.

## 8. Pitfalls checklist

1. **Reconcile is a diff, not an overwrite.** Reconciling an unchanged value
   produces no ops. Reconciling stale data (hydrated before remote changes were
   merged) silently "reverts" others' changes for scalar fields — hydrate fresh
   after every merge. Only `Text`/`Counter` guard against this via `StaleHeads`.
2. **`Text` fresh vs rehydrated:** assigning `field = Text::with_value("new")` to a
   hydrated struct replaces the whole text object (new ObjId, loses merge affinity
   with concurrent edits); hydrate + `splice`/`update` to get character-level
   merging. Reconciling a rehydrated `Text` after the doc's heads moved →
   `ReconcileError::StaleHeads`.
3. **`String` vs `Text`:** a `String` field is a single LWW register — concurrent
   edits conflict wholesale. `Text` merges concurrent splices character-wise. Use
   `Text` for collaboratively edited prose.
4. **Lists without `#[key]` merge positionally** — concurrent insert-at-front +
   edit produces conflicted garbage. Put `#[key]` on a stable-id field of
   list-element structs. The key field must be scalar-hydratable + `Clone` +
   `PartialEq`.
5. **Number representation is strict** (see §5): no cross-coercion among
   Int/Uint/F64 on hydrate; no `usize`.
6. **Missing `Option` field errors** (see §7). Also `MaybeMissing::Missing` never
   deletes an existing doc value.
7. **`#[autosurgeon(reconcile = "fn")]` drops key support** (generates a `NoKey`
   wrapper); use `reconcile_with = "module"` / `with = "module"` (with `Key`,
   `hydrate_key`, `key` items) when the field participates in keyed list merging.
8. **HashMap reconcile deletes absent keys; derived structs don't.** Don't model
   open-ended maps as structs or vice versa.
9. **Top-level must be a map** (`TopLevelNotMap`); wrap root lists/scalars in a
   struct.
10. **Performance:** freshly created subtrees are batch-created in one call (fast
    bulk import into an empty doc). But reconciling a large `Vec` still hydrates
    every element's key and runs LCS each call, and there is no incremental hydrate
    (full re-hydrate after each merge) — for big docs, reconcile/hydrate targeted
    subtrees via `reconcile_prop`/`hydrate_prop`.
11. `reconcile` consumes `value: R` by value, but `&T: Reconcile`, so
    `reconcile(&mut doc, &contact)` is the normal call.

## 9. Cargo.toml & version pairing

```toml
[dependencies]
automerge = "0.11"        # autosurgeon 0.13 is built against automerge 0.11
autosurgeon = "0.13"
# with uuid support:
# autosurgeon = { version = "0.13", features = ["uuid"] }
# uuid = "1"

[dev-dependencies]
automerge-test = "0.11"   # assert_doc!, map!, list! macros
```

Only feature flag: `uuid`. Version pairing history: autosurgeon 0.13↔automerge
0.11, 0.12↔0.10, 0.11↔0.8, 0.9↔0.7, 0.8.6↔0.6, 0.8.0↔0.5.

## 10. API drift vs old tutorials

- **0.13.0**: automerge 0.11. **0.12.0**: automerge 0.10. **0.11.0**: automerge
  0.8; batch-import efficiency.
- **0.10.1**: fixes — fresh `Text` now replaces instead of splicing into existing
  text; `MapReconciler::put`/`SeqReconciler::set` now honor keys.
- **0.10.0**: added `rename =`.
- **0.9.0**: automerge 0.7; map/seq iterator item types changed to
  `Cow<str>`/`ValueRef` (old blog code with `(&str, Value)` won't compile).
- **0.8.2**: `missing=` + `MaybeMissing`. **0.8.3**: `Text::update`.
- **0.7.0** (BREAKING): map reconcile deletes keys absent from incoming data.
- **0.4.0**: enum variant switch deletes old variant's keys.

## 11. Manual impl templates

```rust
// Manual Hydrate for a map-shaped type
impl Hydrate for Employee {
    fn hydrate_map<D: ReadDoc>(doc: &D, obj: &automerge::ObjId) -> Result<Self, HydrateError> {
        Ok(Employee {
            name: hydrate_prop(doc, obj, "name")?,
            number: hydrate_prop(doc, obj, "number")?,
        })
    }
}

// Manual Hydrate for a string newtype
impl Hydrate for UserId {
    fn hydrate_string(s: &str) -> Result<Self, HydrateError> { Ok(UserId(s.to_string())) }
}

// Manual Reconcile with key
impl Reconcile for User {
    type Key<'a> = std::borrow::Cow<'a, String>;
    fn reconcile<R: Reconciler>(&self, mut reconciler: R) -> Result<(), R::Error> {
        use autosurgeon::reconcile::MapReconciler;  // brings .put()/.delete() into scope
        let mut m = reconciler.map()?;
        m.put("id", &self.id)?;
        m.put("name", &self.name)?;
        Ok(())
    }
    fn hydrate_key<'a, D: ReadDoc>(doc: &D, obj: &automerge::ObjId, prop: Prop<'_>)
        -> Result<LoadKey<Self::Key<'a>>, ReconcileError> {
        autosurgeon::hydrate_key(doc, obj, prop, "id".into())
    }
    fn key(&self) -> LoadKey<Self::Key<'_>> { LoadKey::Found(std::borrow::Cow::Borrowed(&self.id)) }
}
```
