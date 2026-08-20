---
name: automerge-rust
description: >-
  Write correct Rust code using Automerge CRDTs — the automerge, autosurgeon, and
  samod crates. Use this skill whenever the user is building, reading, or debugging
  Rust code that involves automerge documents, CRDTs, local-first sync, collaborative
  editing, rich text (marks, spans, blocks, Peritext), autosurgeon Reconcile/Hydrate
  derives, the automerge sync protocol, or samod repos — even if they only mention
  "CRDT", "local-first", "sync engine", "collaborative state", or a type like
  AutoCommit, DocHandle, or Reconcile without naming Automerge. Automerge's merge
  semantics make several natural-looking coding patterns silently wrong, so consult
  this before writing any automerge code.
---

# Automerge in Rust

Automerge is a CRDT library: a JSON-like document (nested maps, lists, text,
scalars) that multiple actors can modify concurrently and merge deterministically,
with full history. The Rust crates are the canonical implementation.

This skill targets these versions (released together 2026-08; they move in lockstep,
so pin compatible pairs):

| Crate | Version | Role |
|---|---|---|
| `automerge` | 0.11 | Core: document model, transactions, save/load, sync protocol, patches |
| `autosurgeon` | 0.13 | Derive `Reconcile`/`Hydrate` — map typed Rust structs ↔ documents |
| `samod` | 0.13 | automerge-repo in Rust: `Repo`/`DocHandle`, storage, websocket sync, JS-interoperable |
| `automerge-test` | 0.11 | Dev-dependency: `assert_doc!`/`map!`/`list!` for asserting doc shapes incl. conflicts |

Version pairing history: autosurgeon 0.13↔automerge 0.11, 0.12↔0.10, 0.11↔0.8.

**Work against the project's pinned versions.** In an existing project, resolve
the actual versions first (`cargo tree -i automerge`, `cargo tree -d`) and adapt
to that API rather than upgrading dependencies the task didn't ask you to touch.
If older versions are pinned, check the "API drift" sections at the end of the
reference files before trusting examples here. Never let two versions of
`automerge` into the graph — their `ObjId`, `Value`, and document types are
distinct Rust types and the errors are confusing; align your direct `automerge`
dependency with the range autosurgeon resolves to.

## Choosing a layer

- **App state with a known schema → `autosurgeon` (default choice).** Derive
  `Reconcile` + `Hydrate` on plain structs, call `reconcile(&mut doc, &value)` /
  `hydrate(&doc)`. It diffs against the document (not a blind overwrite), so
  concurrent edits merge at field granularity. The automerge crate's own docs
  recommend it: the raw API is deliberately low-level, "like hand-building JSON".
- **Dynamic/unknown shapes, fine-grained control, patches, history queries → raw
  `automerge`.** You'll use it underneath autosurgeon anyway for save/load/merge/sync.
- **Multi-peer document management → `samod`.** Document URLs, find/create,
  automatic persistence, websocket sync, JS automerge-repo interop (wire + disk).
  Pre-1.0 and self-described experimental, but actively developed and the declared
  successor to `automerge-repo-rs`. For a simple two-peer or client-server design
  you fully control, the built-in `automerge::sync` module is smaller and stable.
- **Never**: `automerge-persistent` (unmaintained since 2023), the
  `automerge-frontend`/`automerge-backend` split (long dead), `automerge_repo`
  (automerge-repo-rs — legacy, NOT compatible with JS peers on wire or disk).

## Setup

```toml
[dependencies]
automerge = "0.11"
autosurgeon = "0.13"            # add features = ["uuid"] for Uuid fields
# samod = { version = "0.13", features = ["tokio", "tungstenite"] }  # repo layer, if needed

[dev-dependencies]
automerge-test = "0.11"
```

`automerge` features that matter: text indices default to **Unicode code points**.
Two situations force a different encoding, and they conflict with each other:

- **Using `autosurgeon::Text`**: its splice positions are Rust byte offsets,
  forwarded unchanged into `splice_text` — correct only when the document uses
  UTF-8 code units. Enable the `utf8-indexing` feature, or create every document
  with `new_with_encoding(TextEncoding::Utf8CodeUnit)` AND load with matching
  `LoadOptions`. With the default encoding, non-ASCII content splices at the
  wrong positions. Always test with non-ASCII/emoji text.
- **Interop with JS peers**: JS uses UTF-16 code units — enable `utf16-indexing`
  or JS-side indices disagree with yours. If you need both JS interop and typed
  text, don't use `autosurgeon::Text`; drive `splice_text` directly.

## Quickstart — autosurgeon (typed state)

```rust
use autosurgeon::{Hydrate, Reconcile, hydrate, reconcile};

#[derive(Debug, Clone, Reconcile, Hydrate, PartialEq)]
struct Contact {
    #[key]                 // identity for list merging — see rule 4 below
    id: u64,
    name: String,
    addresses: Vec<Address>,
}

#[derive(Debug, Clone, Reconcile, Hydrate, PartialEq)]
struct Address { line_one: String, city: String }

let mut doc = automerge::AutoCommit::new();
let contact = Contact { id: 1, name: "Sherlock".into(), addresses: vec![] };
reconcile(&mut doc, &contact)?;
let saved: Vec<u8> = doc.save();

// Fork (simulating another device), edit both sides, merge:
let mut doc2 = doc.fork().with_actor(automerge::ActorId::random());
let mut c2: Contact = hydrate(&doc2)?;
c2.name = "Dangermouse".into();
reconcile(&mut doc2, &c2)?;
doc.merge(&mut doc2)?;
let merged: Contact = hydrate(&doc)?;   // re-hydrate after every merge
```

## Quickstart — raw automerge

```rust
use automerge::{AutoCommit, ObjType, ReadDoc, ROOT, transaction::Transactable};

let mut doc = AutoCommit::new();
let contacts = doc.put_object(ROOT, "contacts", ObjType::List)?;
let alice = doc.insert_object(&contacts, 0, ObjType::Map)?;
doc.put(&alice, "name", "Alice")?;
doc.put(&alice, "email", "alice@example.com")?;

let bytes = doc.save();
let mut doc2 = AutoCommit::load(&bytes)?;

match doc2.get(ROOT, "contacts")? {
    Some((automerge::Value::Object(ObjType::List), list_id)) => {
        assert_eq!(doc2.length(&list_id), 1);
    }
    _ => panic!("expected a list"),
}
```

`AutoCommit` manages transactions implicitly (simplest; use by default). Use
`Automerge` + `doc.transact(...)` / `doc.transaction()` when you need explicit
change boundaries, per-change commit messages, or rollback-on-error. Note that on
`AutoCommit`, "whole document" operations (`save`, `get_heads`, `merge`, `sync()`)
take `&mut self` because they commit the pending implicit transaction first.

## Merge semantics — the rules that make code correct or silently wrong

Automerge merges deterministically: any two peers with the same set of changes have
identical state and agree on every conflict winner. Timestamps play no role — only
causal structure. Per type: concurrent `put`s to the same map key keep all values
and deterministically pick one winner (`get` returns the winner, `get_all` returns
every candidate); list elements are identified by internal element IDs so concurrent
inserts never clobber each other; text merges character-wise; counters sum all
actors' increments; a concurrent update beats a concurrent delete.

Those semantics make the following rules non-negotiable. Violating them compiles
fine and works in single-user testing, then loses data on merge:

1. **Mutate the smallest thing possible; never rebuild a subtree to "update" it.**
   `put_object` creates a NEW object with a new identity. If peer A replaces
   `root.config` with a fresh map while peer B edits a key inside the old one, the
   two *objects* conflict wholesale — one wins and the other's edits vanish from
   view. Update keys inside the existing object instead. (This is exactly why
   autosurgeon reconciles diffs in place.)
2. **Counters, not read-modify-write.** `put(obj, "n", old + 1)` is a register
   write — concurrent "increments" conflict and all but one are lost. Use
   `ScalarValue::counter(0)` + `doc.increment(obj, "n", 1)`, or
   `autosurgeon::Counter`. Concurrent increments then sum correctly. Counters are
   for quantities whose only operation is addition — not identifiers, and not
   invariant-bearing values like balances or quotas (nothing stops the merged sum
   going negative; enforce such invariants with a domain protocol above the CRDT).
3. **`Text` objects, not `String` scalars, for collaboratively edited text.**
   A string scalar is a register: concurrent edits conflict wholesale. Create
   `ObjType::Text` and edit with `splice_text`/`update_text` (or use
   `autosurgeon::Text`), which merges concurrent edits character-wise.
4. **Put `#[key]` on a stable-id field of any struct stored in a `Vec`.** Without
   it, autosurgeon aligns list items positionally (LCS diff), so a concurrent
   insert-at-front misaligns every element and merges produce conflicted duplicates.
   With `#[key]`, items align by identity, and a changed key correctly *replaces*
   the object (new identity) instead of mutating the old one.
5. **`fork()`, never `clone()`, for a divergent copy.** All changes by one actor
   must be sequential; two documents edited under the same actor id corrupt
   (`DuplicateActorId`/`DuplicateSeqNumber`). `fork()` assigns a fresh random actor.
   One actor id per device/process/thread-of-execution; `ActorId::random()` per
   process is safe (each distinct actor costs a little space forever, so persist
   and reuse a device's actor when convenient).
6. **Initialize shared structure once, not on every device.** If two fresh devices
   each run `put_object(ROOT, "todos", ObjType::List)` and then sync, there are TWO
   list objects in conflict — one wins and the other's items seem to vanish. Create
   the skeleton once, `save()`, and have every device `load()`/`fork()` those bytes
   (or sync from an initialized peer) so all edits share one ancestor object.
7. **Re-hydrate after every merge or received sync message** (autosurgeon).
   `reconcile` diffs your value against the *current* doc; reconciling a struct
   hydrated before a merge silently reverts other peers' scalar changes. Only
   `autosurgeon::Text`/`Counter` guard against this (they error with `StaleHeads`).
   A mutated hydrated `Counter`/`Text` is also **single-use**: reconciling the same
   dirty value twice re-applies its pending increments/splices — reconcile once,
   then rehydrate.
8. **Batch related edits into one transaction/commit.** Each commit creates a
   Change with overhead; a transaction is also the unit of atomicity and gets the
   commit message. For bulk imports use `batch_create_object`/
   `init_root_from_hydrate` (or autosurgeon, which batch-creates fresh subtrees
   automatically) rather than one op per node.
9. **Surface conflicts where they matter.** `get` silently returns the
   deterministic winner. Use `get_all(obj, prop)` to show all concurrent values;
   a subsequent `put` resolves the conflict by superseding all of them. Patches and
   range iterators carry a `conflict` flag.
10. **Deleting a map key vs. setting it `Null` are different states**, and in
    autosurgeon an *absent* property fails to hydrate even into `Option<T>` — use
    `#[autosurgeon(missing = "Default::default")]` or `MaybeMissing<T>` for fields
    added after documents already exist (schema evolution).

## Persistence in one paragraph

`doc.save()` → full compact document; `AutoCommit::load(&bytes)` restores it.
`doc.save_incremental()` → only changes since the last save, suitable for appending
to a log; `doc.load_incremental(&bytes)` applies either format into an existing doc
(loading changes is commutative and idempotent). The standard pattern: append
incremental chunks on every change, occasionally compact by writing a full `save()`
and deleting only the chunks you already folded in. Details, the JS-compatible
on-disk layout, and samod's `Storage` trait: `references/sync-and-persistence.md`.

## Sync in one paragraph

The `automerge::sync` module implements an efficient peer-to-peer protocol: one
`sync::State` per (document, peer), loop `generate_sync_message` /
`receive_sync_message` until both sides generate `None`. Requires a reliable,
in-order transport. Persist `state.encode()` (only the safe subset survives) to
speed up reconnects; never reuse a live `State` across connections. `AutoCommit`
exposes it via `doc.sync()`. Full loop example and semantics:
`references/sync-and-persistence.md`.

## Security and trust boundaries

Automerge supplies convergence, not a collaboration security system. Actor IDs and
document IDs are ordering/addressing metadata, never credentials — authenticate
and authorize peers outside Automerge, and add transport encryption yourself (the
sync protocol has none). Treat bytes from peers or disk as untrusted: keep load
verification on, and bound message/document/history sizes before parsing. And
remember the document retains full history: deleting a value hides it from the
current view but any replica can still read it via `*_at` — if historical removal
is a real requirement (secrets, GDPR), create a fresh document containing only the
allowed current state and retire the old replicas.

## Testing

Test CRDT behavior, not just CRUD: fork from one ancestor, edit both sides
concurrently, merge in both directions, and assert both heads and state converge.
Use `automerge-test` (dev-dependency) to assert whole-document shape including
conflicts:

```rust
use automerge_test::{assert_doc, map, list};

assert_doc!(&doc, map! {
    "todos" => { list![ { map! { "title" => { "water plants" } } } ] }
});
```

Every value sits in `{ ... }` because each property is a *set* of conflicting
values — `"field" => { "one", "two" }` asserts a 2-way conflict. `sorted_actors()`
gives two actors with a known order for deterministic conflict winners. The full
test matrix (convergence, keyed lists, text encoding, persistence crash points,
sync reconnect, schema skew) and a failure-diagnosis guide are in
`references/testing-and-debugging.md` — read it before writing tests for any
collaborative feature.

## Old tutorials will mislead you

Automerge's Rust API has churned. Red flags that code predates the current API:
`OpObserver`/`VecOpObserver` (removed 0.5 — use `PatchLog` + `make_patches`, or
`AutoCommit::diff_incremental`), `TextRepresentation` (removed 0.7 — `TextEncoding`),
`SyncState` as a root-level type (it's `sync::State`), `Mark::data`/`MarkData`
(now `Mark::{name, value}`), range iterators yielding `(&str, Value)` (now
`Cow<str>`/`ValueRef`), `automerge-frontend`/`automerge-backend` crates (ancient),
`automerge_repo::RepoHandle` (legacy automerge-repo-rs — recommend samod instead).
Full changelog maps are at the end of each reference file.

## Reference files — read before writing non-trivial code

- **`references/core-api.md`** — the full `automerge` crate surface: reading and
  conflicts, all mutation methods, text/cursors, save/load options, history
  and time travel (`*_at` variants, `diff`, `isolate`), explicit transactions,
  patches/`PatchLog`, `hydrate`/serde interop, feature flags, 14 detailed pitfalls.
  Read when working with the raw API, patches, history, or plain text.
- **`references/rich-text.md`** — the rich-text layer (raw automerge only;
  autosurgeon has no support for it): marks and `ExpandMark` semantics, unmark
  tombstones, rendering styled runs from `spans()`, block markers and the
  paragraph/heading schema conventions, `update_spans` bulk diffing, rich-text
  patches, merge semantics for concurrent marks, and the sharp edges (including a
  block-marker width bug under `Utf8CodeUnit`). Read before ANY marks, blocks,
  spans, or collaborative-editor formatting work.
- **`references/editor-integration.md`** — how to wire an actual editor (GUI,
  TUI, or headless collab server) to an automerge Text object, distilled from the
  official automerge-prosemirror binding with every piece mapped to its Rust API:
  the two unidirectional loops, position mapping between tree editors and flat
  spans, the "splice for text / update_spans for structure" split, the
  write-then-diff-then-verify pass, remote patch application against a spans
  snapshot, selection via cursors, editor-local undo, echo suppression, schema
  adaptation with lossless unknown-content round-tripping. Read before building
  any editor binding or collaboration server on top of automerge.
- **`references/autosurgeon.md`** — traits and exact derive attribute forms
  (`#[key]`, `reconcile=`, `reconcile_with=`, `with=`, `hydrate=`, `missing=`,
  `rename=`), enum representations, list-merge key mechanics, `Text`/`Counter`/
  `MaybeMissing`/maps/bytes/uuid, manual impl templates, schema evolution. Read
  whenever deriving or hand-implementing `Reconcile`/`Hydrate`.
- **`references/sync-and-persistence.md`** — the sync protocol (full two-peer loop,
  state persistence rules, durability coupling), storage chunk pattern and
  JS-compatible file layout, samod (`Repo`/`DocHandle`/`Storage`/websockets) with
  API shapes, ecosystem landscape table, debugging with automerge-cli. Read when
  building sync, storage, or multi-peer infrastructure.
- **`references/testing-and-debugging.md`** — minimum test matrix, convergence and
  conflict test patterns, autosurgeon-specific test checklist, persistence/sync
  failure-mode tests, and a symptom → likely-cause diagnosis table. Read when
  writing tests or chasing a merge/sync bug.
