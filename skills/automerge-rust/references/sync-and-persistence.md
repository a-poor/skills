# Sync, persistence, and the ecosystem

Covers the `automerge::sync` protocol, storage patterns, the `samod` repo layer,
and the crate landscape. Verified against automerge 0.11.0 and samod 0.13.0
(2026-08).

## Contents

1. [Merge semantics recap](#1-merge-semantics-recap)
2. [The sync protocol](#2-the-sync-protocol)
3. [Storage patterns without samod](#3-storage-patterns-without-samod)
4. [samod — automerge-repo in Rust](#4-samod--automerge-repo-in-rust)
5. [automerge-repo-rs status](#5-automerge-repo-rs-status)
6. [Debugging tools & other pieces](#6-debugging-tools--other-pieces)
7. [Crate landscape table](#7-crate-landscape-table)

---

## 1. Merge semantics recap

What an agent must internalize to design document schemas:

- **Eventual consistency guarantee**: any two peers that have applied the same set
  of changes (in any order) have identical document state and agree on all conflict
  winners. Merging is commutative, associative, idempotent. Timestamps play NO role
  in conflict resolution — only causal (concurrent-or-not) structure.
- **Map key conflict**: concurrent `put`s to the same key → one winner, chosen
  arbitrarily but deterministically (all replicas agree); losers retrievable via
  `get_all`.
- **Lists**: elements are identified by internal element IDs, not indices, so
  concurrent inserts never clobber each other; concurrent inserts at the same
  position both survive, deterministically ordered, and a single replica's
  insertion run stays contiguous.
- **Delete vs concurrent update**: the update wins (the value survives). Concurrent
  deletes: it's gone.
- **Text**: merged character-by-character with the same element-ID logic.
- **Counter**: merges by summing all actors' increments.
- **The object-identity footgun**: `put_object` creates a NEW object. Replacing a
  subtree (delete + re-add) while a peer mutates inside the old subtree resolves
  the conflict at the parent slot — one object wins wholesale, the other subtree's
  edits are invisible (still in history, not in the winning view). Mutate the
  smallest thing possible.

## 2. The sync protocol

Module `automerge::sync`, based on https://arxiv.org/abs/2012.00472. Assumes a
**reliable, in-order** transport (websocket, TCP — not bare UDP).

- **One `sync::State` per (document, peer) pair.** The type is `sync::State` (there
  is no root-level `SyncState` in current versions).
- **Loop until convergence**: each side alternates
  `receive_sync_message`/`generate_sync_message`. `generate_sync_message` returns
  `None` when there is nothing to send (peer up to date, or an unacked message is
  in flight). Convergence = both sides generate `None`; both docs then have equal
  heads. Bloom filters keep the exchange bandwidth-efficient; false positives are
  healed by explicit need-requests in later rounds. The first sync to an empty peer
  sends the whole compressed document.

Full two-peer loop (the doctest from the crate, works verbatim):

```rust
use automerge::{transaction::Transactable, sync::{self, SyncDoc}, ReadDoc};

let mut peer1 = automerge::AutoCommit::new();
peer1.put(automerge::ROOT, "key", "value")?;
let mut peer1_state = sync::State::new();
let message1to2 = peer1.sync().generate_sync_message(&mut peer1_state).unwrap();

let mut peer2 = automerge::AutoCommit::new();
let mut peer2_state = sync::State::new();
peer2.sync().receive_sync_message(&mut peer2_state, message1to2)?;

loop {
    let two_to_one = peer2.sync().generate_sync_message(&mut peer2_state);
    if let Some(message) = two_to_one.as_ref() {
        peer1.sync().receive_sync_message(&mut peer1_state, message.clone())?;
    }
    let one_to_two = peer1.sync().generate_sync_message(&mut peer1_state);
    if let Some(message) = one_to_two.as_ref() {
        peer2.sync().receive_sync_message(&mut peer2_state, message.clone())?;
    }
    if two_to_one.is_none() && one_to_two.is_none() { break; }
}
```

In a real app the two peers are on opposite ends of a connection and each runs:
on local change → `generate_sync_message`, send if `Some`; on message received →
`receive_sync_message`, then `generate_sync_message` again (repeat until `None`).
Wire format: `Message::encode() -> Vec<u8>` / `Message::decode(&[u8])`.

- **Ephemeral vs persisted sync state**: `State::encode()` "only encodes state
  which should be reused across connections" — essentially `shared_heads`. Persist
  it keyed by (peer id, doc id) if you'll re-sync with the same peer across
  sessions; on reconnect, `State::decode(saved)` instead of `State::new()` — this
  shrinks the first exchange. Session-local fields (`sent_hashes`, `in_flight`,
  bloom filters, `their_heads`, ...) are NOT encoded and reset on decode. **Never
  reuse a live in-memory `State` across reconnects** — its in-flight bookkeeping
  assumes the old transport delivered everything. After a failed/aborted
  connection, either re-decode the persisted state or start with `State::new()`;
  correctness is preserved either way, fresh state only costs bandwidth. If a peer
  reports lost state the protocol auto-resets. Two further consequences: decode
  also resets policy fields like `read_only` — reapply them after decoding; and
  persisted sync state must stay consistent with the persisted document — if
  restored `shared_heads` could be ahead of the durable doc bytes (state saved but
  doc write lost), discard the state and start fresh.
- **The transport owns retries.** While a message is in flight (unacked),
  `generate_sync_message` returns `None` rather than retransmitting — so a
  dropped frame must be retried by your transport layer with the same encoded
  message. `None` therefore means either "caught up" or "waiting for ack"; keep
  driving both receive and send sides until the whole exchange is quiescent.
- **Read-only mode**: `State::new_read_only()` / `state.set_read_only(bool)` —
  ignore incoming changes but still serve ours; `state.is_peer_read_only()`.
- `doc.has_our_changes(&state) -> bool` — has the peer (per this state) got
  everything we have.
- `receive_sync_message_log_patches(&mut state, msg, &mut patch_log)` feeds a
  `PatchLog` so a UI can apply incremental updates from sync.

### Direct change exchange (the simpler alternative)

When the application already has acknowledgement, retry, and durable peer-state
machinery of its own, raw change exchange can replace the sync state machine:
receiver sends its known heads → sender calls `get_changes(&their_heads)` →
transmit the encoded changes → receiver `apply_changes(...)`. Applying an
already-known change is idempotent, and changes whose causal dependencies haven't
arrived yet wait until they do (`get_missing_deps` shows what's missing) — so
test duplicate and out-of-order delivery. Otherwise prefer the sync module; its
bloom-filter exchange handles "what does the peer need" for you.

### Security boundaries

The sync machinery authenticates nothing and encrypts nothing. Authenticate the
remote identity and authorize per-document read/write before exchanging data;
actor IDs, document IDs, and sync states are not credentials. Bound message size,
queued bytes, document count, and history growth before accepting untrusted
input, and validate domain invariants after applying remote changes — a
syntactically valid change can still express an unauthorized business action.

## 3. Storage patterns without samod

The automerge binary format makes a simple, concurrency-safe storage convention
possible (this is the same model JS automerge-repo and samod use on disk):

- Two chunk types under a per-document prefix:
  - **incremental**: on every local change (or received sync batch), append
    `doc.save_incremental()` bytes as a new chunk keyed by the hash of the chunk
    bytes: `[<doc_id>, "incremental", <hash>]`.
  - **snapshot**: occasionally compact — write `doc.save()` (full compressed doc)
    to `[<doc_id>, "snapshot", <heads-at-compaction>]`, then delete only the
    incremental chunks *you previously loaded or wrote* (not everything under the
    prefix).
- Why this is concurrency-safe: snapshot keys include the heads, and document
  content is uniquely determined by heads, so two processes compacting the same doc
  write identical-or-distinct keys and never corrupt each other; each process only
  deletes chunks it knows it folded into its snapshot.
- Loading: list everything under `[<doc_id>]`, then `Automerge::load(a_snapshot)` +
  `doc.load_incremental(chunk)` for every other chunk — **order does not matter**
  (loading changes is commutative and idempotent).
- Compaction triggers are your choice: N incremental chunks, incremental bytes >
  snapshot bytes, or clean shutdown.
- JS/samod-compatible filesystem layout: splay the doc id by its first two
  characters, e.g. `dataDir/2a/kvofn.../incremental/<hex-hash>`.
- Document URLs in the automerge-repo ecosystem: `automerge:<bs58check(doc-id)>`,
  e.g. `automerge:2akvofn6L1o4RMUEMQi7qzwRjKWZ`.

Do NOT reach for `automerge-persistent` (+`-fs`, `-sled`) — unmaintained since
2023, pinned to an ancient automerge.

## 4. samod — automerge-repo in Rust

`samod` (https://github.com/alexjg/samod, crate `samod`) is the Rust
implementation of the automerge-repo pattern: document lifecycle, storage, and
websocket sync, **interoperable with JS automerge-repo both over the network and
on disk** (verified by in-repo JS interop tests — Rust clients against a JS sync
server and vice versa).

Status: pre-1.0, README says "very much a work in progress... don't use this
anywhere serious yet"; the author's stated objective is to replace
automerge-repo-rs with it. It is the actively developed path. Note docs.rs builds
of recent versions are broken — read the repo's source/README, not docs.rs.

Cargo: `samod = { version = "0.13", features = ["tokio", "tungstenite"] }` —
features: `tokio`, `axum` (ws server), `tungstenite` (ws client), `gio`,
`threadpool`. samod 0.13 pairs with automerge 0.11. Workspace also contains
`samod-core` (sans-IO state machine, FFI-oriented).

### Core API shapes

```rust
// Repo construction (builder pattern)
let repo = samod::Repo::build_tokio()               // or Repo::builder(runtime_handle)
    .with_storage(samod::storage::TokioFilesystemStorage::new("/data/dir"))
    .with_announce_policy(|_doc_id, _peer_id| true) // AnnouncePolicy, closure ok
    .load().await;
// also: build_gio(), build_localpool(); RepoBuilder::load_local() for !Send runtimes

// Documents
let handle: DocHandle = repo.create(automerge::Automerge::new()).await?;  // Result<_, Stopped>
let found: Option<DocHandle> = repo.find(doc_id).await?;                  // storage, then peers
handle.document_id(); handle.url();           // AutomergeUrl "automerge:<bs58check>"
let r = handle.with_document(|doc: &mut automerge::Automerge| doc.transact(|tx| { /*...*/ Ok::<_, automerge::AutomergeError>(()) }));
handle.with_document_async(|doc| { /*...*/ }).await;  // doesn't block the task
let mut changes = handle.changes();           // Stream<Item = DocumentChanged>, 'static
handle.ephemera();                            // Stream<Item = Vec<u8>> (ephemeral msgs)
handle.broadcast(bytes);                      // send ephemeral message to peers

// Networking: dialers (outbound, auto-reconnect w/ backoff) and acceptors (inbound)
let dialer = repo.dial_websocket(url, BackoffConfig::default())?;  // `tungstenite`
dialer.established().await?;                  // wait for first connection+handshake
let acceptor = repo.make_acceptor(url)?;
acceptor.accept_axum(ws_socket)?;             // `axum` — plug into an axum ws route
acceptor.accept_tungstenite(ws)?;
repo.when_connected(peer_id); repo.connected_peers(); repo.peer_id(); repo.stop().await;
```

- `Repo::find` checks storage first, then requests from connected peers (subject to
  the announce policy), and waits for in-progress dialers before returning
  `Ok(None)` — no need to sequence dial-then-find manually.
- **The default announce policy announces every managed document to every
  connected peer** and searches all peers. For anything with per-document access
  control, pass `with_announce_policy(...)` — and remember authorization and
  authentication still live outside samod.
- All changes made via `with_document` are automatically persisted to storage and
  synced to peers; incoming remote changes surface via `changes()`.
- `with_document` holds a mutex — wrap long operations in `spawn_blocking` or use
  `with_document_async`.

### Storage trait

```rust
pub trait Storage: Send + Clone + 'static {
    fn load(&self, key: StorageKey) -> impl Future<Output = Option<Vec<u8>>> + Send;
    fn load_range(&self, prefix: StorageKey) -> impl Future<Output = HashMap<StorageKey, Vec<u8>>> + Send;
    fn put(&self, key: StorageKey, data: Vec<u8>) -> impl Future<Output = ()> + Send;
    fn delete(&self, key: StorageKey) -> impl Future<Output = ()> + Send;
}
// + LocalStorage (no Send bounds)
```

`StorageKey` = `Vec<String>` path; components never contain "/" (safe to join for
flat KV backends). Designed for concurrent multi-process access to shared storage.
Built-in impls: `InMemoryStorage` (default), `TokioFilesystemStorage` (`tokio`
feature), `GioFilesystemStorage`. Key layout matches the chunk pattern in §3
(`[<doc_id>, "incremental"|"snapshot", <hash>]`), with the two-char splayed,
JS-compatible filesystem layout.

### samod vs raw `automerge::sync`

Use **samod** when the app needs: automerge-repo semantics (doc URLs,
find/create, announce policies), websocket sync with JS automerge-repo peers or
sync-server infrastructure, automatic persistence, auto-reconnect, or ephemeral
messages. Use **raw automerge + sync module** when you have your own
transport/storage, a two-peer or client-server design you fully control, no JS
interop needs, and want zero extra deps — the sync module is small and stable.
Caveats for samod: experimental, breaking changes at nearly every minor release,
single primary author (an automerge core dev).

## 5. automerge-repo-rs status

`automerge_repo` (github.com/automerge/automerge-repo-rs, crate v0.3.0) is the
older repo layer. Its own README states its filesystem layout and websocket
protocol are **not compatible** with JS automerge-repo, and points at samod as the
JS-compatible implementation; samod's README states it aims to replace
automerge-repo-rs. Treat tutorials using
`automerge_repo::{Repo, DocHandle, RepoHandle}` as legacy: prefer samod for new
code; touch automerge-repo-rs only to maintain existing deployments that already
use its incompatible formats.

## 6. Debugging tools & other pieces

- **automerge-cli** (`rust/automerge-cli` in the main repo; unpublished — build
  from source): `export` (doc → JSON), `import`, `examine` (inspect doc/changes),
  `examine-sync` (decode a sync message), `merge` (merge doc files), `anonymize`.
  Handy for inspecting on-disk chunks and captured sync traffic.
- **hexane**: the columnar storage engine underneath automerge ≥0.11 ("columnar
  compression you can edit in place"). Apps don't use it directly; know the name so
  it isn't mysterious in backtraces and dependency trees.
- **FFI**: `automerge-c` (in-tree C API; basis for automerge-swift). `samod-core`
  is designed sans-IO for future FFI wrapping. No uniffi bindings exist in-tree.
- **automerge-wasm** is the internal JS glue — JS consumers should use
  `@automerge/automerge`, and Rust code never needs it.
- **Third-party crates to evaluate skeptically** (all exist on crates.io as of
  2026-08): `automerge_sedimentree` (0.10, Sedimentree-style decentralized chunk
  replication — only for that specific architecture, not a `save`/`load` or sync
  replacement); `automorph` (0.2, alternative derive mapper — audit its merge
  behavior against autosurgeon before adopting; don't mix mapping layers in one
  stored schema); `serde-automerge` (0.1, stale since early 2024 — serde-shaped
  convenience typically does whole-tree replacement, destroying fine-grained
  merge intent; audit before use).

## 7. Crate landscape table

| Crate | Version (2026-08) | Role | Maintenance | Use when |
|---|---|---|---|---|
| `automerge` | 0.11 | Core CRDT: doc model, transactions, save/load, sync, patches | Active (automerge org) | Always — the foundation |
| `autosurgeon` | 0.13 | Derive Reconcile/Hydrate: typed structs ↔ documents | Active (lockstep with automerge) | Typed app state; default over raw put/get |
| `samod` | 0.13 | automerge-repo in Rust: Repo/DocHandle, storage, ws sync, JS-interoperable | Active, experimental/pre-1.0 | Multi-peer sync, JS interop, sync servers, auto persistence |
| `samod-core` | 0.13 | Sans-IO repo state machine (FFI-oriented) | Active, experimental | Custom runtimes / FFI wrappers |
| `automerge_repo` (automerge-repo-rs) | 0.3 | Older repo layer; NOT JS-compatible | Superseded by samod | Only maintaining existing deployments |
| `automerge-test` | 0.11 | Test asserts: `assert_doc!`, `map!`, `list!` | Active | Testing doc shapes incl. conflicts |
| `hexane` | 1.0.0-alpha | Columnar storage engine under automerge ≥0.11 | Active | Indirect dependency |
| `automerge-c` | 0.2 (in-tree) | C API for FFI/bindings | Active | Binding to C/Swift/etc. |
| `automerge-persistent` (+-fs/-sled) | 0.4 (2023) | Old persistence wrapper | Unmaintained | Never (warn against) |

Key URLs: https://github.com/automerge/automerge ·
https://github.com/automerge/autosurgeon · https://github.com/alexjg/samod ·
https://automerge.org/docs/hello/ ·
https://automerge.org/docs/under-the-hood/merge_rules/ ·
https://automerge.org/docs/under-the-hood/storage/ · https://docs.rs/automerge
