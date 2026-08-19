# Testing and debugging

CRDT bugs routinely survive single-user CRUD tests: code that works perfectly for
one writer loses data the first time two replicas merge. Test under branching,
concurrent edits, merge-in-both-directions, persistence round-trips, reconnection,
and schema skew.

## Contents

1. [Minimum test matrix](#1-minimum-test-matrix)
2. [Convergence test pattern](#2-convergence-test-pattern)
3. [Conflict assertions](#3-conflict-assertions)
4. [autosurgeon-specific tests](#4-autosurgeon-specific-tests)
5. [Persistence and sync tests](#5-persistence-and-sync-tests)
6. [Patch tests](#6-patch-tests)
7. [Failure diagnosis](#7-failure-diagnosis)

---

## 1. Minimum test matrix

| Concern | Assertion |
|---|---|
| round trip | raw and/or typed state has the expected shape after save/load |
| shared ancestry | all replicas fork/load from ONE initialized document, then merge |
| convergence | merging in both directions yields equal heads AND equal state |
| register conflicts | `get_all` contains every intended concurrent value |
| keyed lists | concurrent insert/edit/remove doesn't cross-wire entities |
| text | non-ASCII/emoji edits land correctly under the configured `TextEncoding` |
| counters | concurrent increments sum; a dirty hydrated counter is reconciled only once |
| persistence | full and incremental recovery preserve heads and conflicts |
| sync | loop reaches quiescence; reconnect with decoded per-peer state works |
| patches | an incrementally-patched view equals a fresh full materialization |
| schema evolution | old and new clients edit, merge, and converge |
| trust boundary | truncated/corrupted/oversized input fails safely |

Assert semantic invariants and final heads — never assert an arbitrary conflict
winner, actor ID, op ID, or exact serialized bytes unless that representation is
explicitly the contract (winners are deterministic but arbitrary; bytes are a
storage artifact, not a canonicalization promise).

## 2. Convergence test pattern

One shared base, two writers, merge both directions, compare heads and hydrated
state:

```rust
use automerge::{transaction::Transactable, AutoCommit, ReadDoc, ROOT};

let mut base = AutoCommit::new();
base.put(ROOT, "seed", true)?;

let mut left = base.fork();          // fork() = fresh actor, shared ancestry
let mut right = base.fork();
left.put(ROOT, "left", 1_u64)?;
right.put(ROOT, "right", 2_u64)?;

let left_bytes = left.save();
let right_bytes = right.save();
let mut merged_lr = AutoCommit::load(&left_bytes)?;
let mut merged_rl = AutoCommit::load(&right_bytes)?;
merged_lr.merge(&mut AutoCommit::load(&right_bytes)?)?;
merged_rl.merge(&mut AutoCommit::load(&left_bytes)?)?;

assert_eq!(merged_lr.get_heads(), merged_rl.get_heads());
assert_eq!(merged_lr.hydrate(ROOT, None)?, merged_rl.hydrate(ROOT, None)?);
```

Compare heads as well as state: equal materialized values can hide differing
unresolved history. For a domain model, additionally assert every invariant after
each merge (ID uniqueness, required references, valid ranges) — the CRDT
guarantees convergence, not business validity.

## 3. Conflict assertions

Construct conflicts intentionally from one shared base, then assert the *set* of
values, not the winner:

```rust
let mut base = AutoCommit::new();
base.put(ROOT, "status", "draft")?;
let mut left = base.fork();
let mut right = base.fork();
left.put(ROOT, "status", "ready")?;
right.put(ROOT, "status", "blocked")?;
left.merge(&mut right)?;

let mut values: Vec<String> = left
    .get_all(ROOT, "status")?
    .into_iter()
    .filter_map(|(value, _)| value.to_str().map(str::to_owned))
    .collect();
values.sort();
assert_eq!(values, ["blocked", "ready"]);
```

If application policy resolves the conflict, perform the resolution as a new
`put` after observing the merged state, then assert `get_all` has one value.
`automerge-test`'s `assert_doc!`/`map!`/`list!` express the same thing more
concisely (`"status" => { "ready", "blocked" }` asserts the 2-way conflict) —
see the testing section of the main SKILL.md.

## 4. autosurgeon-specific tests

For each typed persisted model, cover:

1. Reconcile → hydrate round trip.
2. Inspect the raw document shape too (`assert_doc!`), not only the typed view —
   hydration silently picks conflict winners.
3. Fork, mutate independently, reconcile on both branches, merge, rehydrate.
4. Concurrent insert/remove/reorder of `#[key]` list entities; a key *change*
   (should behave as replacement); duplicate keys (define app-level behavior).
5. Missing property vs explicit null; `missing =` handlers; `rename` migration.
6. Text: splice around multibyte chars/emoji; assert `doc.text_encoding()` is
   `Utf8CodeUnit`; hydrate → doc changes → reconcile hits `StaleHeads` (assert
   the error path rehydrates and replays the edit).
7. Counters: hydrate and increment on both branches → merged sum; a dedicated
   regression test that the same dirty counter is never reconciled twice.
8. Save/load around typed operations.

## 5. Persistence and sync tests

Persistence:

- Save, reload, compare heads + state; verify intentional conflicts survive.
- Rebuild from snapshot + every prefix of incremental chunks; replay a chunk
  twice (must be idempotent); truncate the final chunk (must fail safely).
- Simulate a failed durable write *after* `save_incremental()` was called, then
  retry with the retained bytes (the cursor has already advanced — see the
  durability caveat in `core-api.md` §5).
- Reject empty, truncated, and bit-flipped input at trust boundaries.

Sync:

- Distinct `sync::State` per (document, peer); alternate messages until both
  sides generate `None`; then assert equal heads.
- Drop a framed message and verify the transport retries that frame
  (`generate_sync_message` will NOT retransmit while it's in flight).
- Disconnect after every message boundary; reconnect with `State::decode` of the
  persisted state; reapply `read_only`-type policy after decode.
- Put a round limit in loop harnesses so a protocol regression fails instead of
  hanging (a test guard, not production logic).

## 6. Patch tests

After every edit/merge/applied change/sync message: apply the emitted patches to
your materialized view, independently materialize the document fresh
(`Automerge::current_state()` or `hydrate`), and assert the two are equal. Cover
deletions that expose a surviving conflict value, list splice ordering, text
splice offsets, and a diff-cursor reset/rebaseline. Never reuse a `PatchLog`
across documents (rejected with `PatchLogMismatch`).

## 7. Failure diagnosis

| Symptom | Likely cause → fix |
|---|---|
| Merging two "identical" documents yields duplicated/conflicting subtrees | Each peer initialized its own structure (no shared ancestry). Initialize once; every replica loads/forks those bytes. |
| Concurrent list edits mixed fields across entities | Unkeyed compound list items reconciled positionally. Add an immutable `#[key]`; re-test the same interleaving. |
| A peer's value "vanished" after merge | `get`/hydrate picked the deterministic winner. Inspect `get_all`; add explicit domain resolution. |
| Someone's edits reverted after a local write | Reconciled a struct hydrated before the merge (stale diff). Rehydrate after every merge/sync receive. |
| Text splices land at wrong positions / panic on non-ASCII | `TextEncoding` mismatch. For `autosurgeon::Text` the doc must be `Utf8CodeUnit` (on create AND load); for JS interop, `Utf16CodeUnit`. Compare `doc.text_encoding()` on all paths. |
| `ReconcileError::StaleHeads` | Doc changed between hydrate and reconcile of a `Text`/`Counter`. Rehydrate and replay the edit; don't bypass the check. |
| Counter drifted upward unexpectedly | Same dirty hydrated `Counter` reconciled more than once (pending delta re-applied). Reconcile once, rehydrate. |
| `DuplicateActorId` / `DuplicateSeqNumber` | Two replicas share an actor id (probably `clone()` instead of `fork()`). One actor per sequential writer. |
| Compile errors about two different `ObjId`/`Automerge` types | Two `automerge` versions in the graph. `cargo tree -d`, `cargo tree -i automerge`; align with autosurgeon's range. |
| Sync stalls, one side returns `None` forever | `None` may mean "awaiting ack" — check the transport delivered (and retried) the last frame, in order; verify one `State` per (doc, peer). |
| Incremental save data lost after a crash | Save cursor advanced before the write was durable. Retain returned bytes until committed, or use `save_after(&last_durable_heads)`. |
| A deleted secret is still readable | History retains everything (`*_at` reads). Rotate: build a fresh document with only allowed state, retire old replicas/backups. |

Diagnostics: `get_heads`, `get_missing_deps`, `get_changes_meta` for causal state;
`get_all` for conflicts; `stats()` for size/actor counts; `save_and_verify()` as a
slow high-assurance check; the in-repo `automerge-cli` (`examine`,
`examine-sync`, `export`) for poking at files and captured sync messages. When
minimizing a repro: one initialized document, two forks, the smallest interleaving
that fails — and record versions, features, and text encoding before filing
upstream.
