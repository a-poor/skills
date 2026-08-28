# Improve-Skill Report Format

JSON is the canonical interchange format for report and combine modes. Markdown
is an optional human-readable rendering. Reports must be safe to move between
machines without copying complete transcripts.

## Required Top-Level Shape

```json
{
  "schema_version": 1,
  "report_id": "rpt_20260828T180306Z_ab12cd34",
  "generated_at": "2026-08-28T18:03:06Z",
  "scan": {
    "machine_id": "sha256:12-char-prefix",
    "cutoff": "2026-08-28T18:03:06Z",
    "agents": ["claude-code", "codex", "opencode"],
    "since": null,
    "until": null,
    "max_detailed_roots": 20,
    "excluded_session_ids": [],
    "locations": []
  },
  "target": {
    "requested": "gpui",
    "resolved_name": "gpui",
    "canonical_path": "~/projects/skills/skills/gpui/SKILL.md"
  },
  "installations": [],
  "counts": [],
  "events": [],
  "missed_opportunities": [],
  "recommendations": [],
  "limitations": []
}
```

All timestamps are UTC ISO 8601. Use `null` for an unknown scalar and an empty
array only when the collection was successfully checked and found empty.

## Scan Locations

Each `scan.locations` entry records coverage:

```json
{
  "agent": "claude-code",
  "path": "~/.claude/projects",
  "store_type": "jsonl-transcripts",
  "status": "scanned",
  "files_or_rows": 107,
  "retained_from": "2026-05-01T00:00:00Z",
  "retained_until": "2026-08-28T18:03:05Z",
  "notes": null
}
```

`status` is one of `scanned`, `missing`, `inaccessible`, `unsupported`, or
`partially_scanned`. An inaccessible or unsupported source contributes unknown
coverage, not zero matches.

Use a non-sensitive stable `machine_id`. A short SHA-256 of the hostname is
acceptable; do not include the raw hostname unless the user requests it.

## Installations and Fingerprints

```json
{
  "installation_id": "github:a-poor/skills:skills/gpui/SKILL.md:3f9c1a7e",
  "project": "~/projects/my-app",
  "installed_path": "~/projects/my-app/.claude/skills/gpui/SKILL.md",
  "lock_path": "~/projects/my-app/skills-lock.json",
  "source": "a-poor/skills",
  "source_type": "github",
  "skill_path": "skills/gpui/SKILL.md",
  "computed_hash": "3f9c1a7e5b2d4c8f0a6e9d1b7c3f5a2e8d4b6c0f1a9e7d3b5c2f8a4e6d0b1c7f",
  "body_sha256": null,
  "fingerprint_basis": "current_lock",
  "observed_at": "2026-08-28T18:03:06Z",
  "relationship_to_canonical": "older",
  "notes": null
}
```

Prefer the complete `skills-lock.json` tuple. `body_sha256` is a fallback or an
additional identity for a transcript-captured body. It is not interchangeable
with `computed_hash`.

`installation_id` is `<source_type>:<source>:<skill_path>:<hash prefix>`. Lock
entries do not always include `skillPath`; when it is absent, set `skill_path`
to `null` and use the lock entry's key (the skill name) in its place, e.g.
`github:shadcn/ui:shadcn:5e8d2c1a`. Resolve symlinked install directories to one
`installed_path` so the same files are not recorded as two installations.

`fingerprint_basis` is one of `historical_lock`, `current_lock`, `captured_body`,
`directory_hash`, or `unknown`. A current lock is not proof of the version loaded
by a historical event. Set an event's `installation_id` to `null` or lower its
confidence when no contemporaneous evidence links that event to the installation.

`relationship_to_canonical` is one of `same`, `older`, `newer`, `modified`, or
`unknown`. Do not infer chronological ordering from unequal hashes alone; use
content, lock history, or repository history.

## Counts

Keep physical storage records separate from deduplicated behavior:

```json
{
  "agent": "codex",
  "candidate_records": 5546,
  "physical_invocation_records": 101,
  "logical_invocation_events": 97,
  "root_conversations_with_use": 9,
  "explicit_commands": 0,
  "maintenance_roots": 1,
  "evaluation_roots": 0,
  "high_confidence_misses": 1,
  "detailed_roots_inspected": 9
}
```

Candidate records are diagnostic and must never be presented as uses.

## Events

Every deduplicated event has a stable report-local ID and evidence locators:

```json
{
  "event_id": "evt_codex_0198f2a1_call_abc",
  "kind": "skill_file_read",
  "classification": "actual_use",
  "agent": "codex",
  "session_id": "0198f2a1-6b3c-7d4e-8f50-a1b2c3d4e5f6",
  "root_session_id": "0198f2a1-6b3c-7d4e-8f50-a1b2c3d4e5f6",
  "native_id": "call_abc",
  "timestamp": "2026-08-25T00:19:49Z",
  "cwd": "~/projects/my-app",
  "installation_id": "github:a-poor/skills:skills/gpui/SKILL.md:3f9c1a7e",
  "confidence": "high",
  "task_summary": "Implemented an animated list view in a GPUI app.",
  "references_read": ["async.md", "component.md", "entity.md"],
  "outcome_signals": ["source_verified", "compiled"],
  "evidence": [
    {
      "type": "tool_call",
      "locator": "~/.codex/sessions/2026/08/01/rollout-...jsonl:120",
      "summary": "Completed content read of the installed GPUI SKILL.md."
    }
  ],
  "notes": null
}
```

Allowed `kind` values:

- `native_skill_call`
- `explicit_command`
- `skill_body_injected`
- `skill_file_read`
- `reference_read`
- `manual_consultation`
- `advertisement`
- `maintenance`
- `evaluation`
- `incidental_mention`

Allowed `classification` values are `actual_use`, `supporting_evidence`,
`availability_only`, `maintenance`, `evaluation`, and `excluded_false_positive`.
Reports normally omit individual incidental mentions after recording aggregate
candidate counts, unless one explains a deduplication decision.

`confidence` is `high`, `medium`, or `low`. Evidence summaries are paraphrases,
not raw transcript dumps.

## Missed Opportunities

```json
{
  "miss_id": "miss_claude_7c1e4b2a",
  "agent": "claude-code",
  "session_id": "7c1e4b2a-9d3f-4a6e-b8c0-2f5d7e9a1b3c",
  "root_session_id": "7c1e4b2a-9d3f-4a6e-b8c0-2f5d7e9a1b3c",
  "timestamp": "2026-08-25T00:51:48Z",
  "cwd": "~/projects/my-app",
  "availability": "advertised",
  "installation_id": "github:a-poor/skills:skills/gpui/SKILL.md:3f9c1a7e",
  "confidence": "high",
  "task_summary": "Refactored GPUI panel entities without loading the skill.",
  "rationale": "The task changed GPUI entity ownership and rendering, and the advertised skill covered both concepts.",
  "evidence": [
    {
      "type": "human_prompt",
      "locator": "~/.claude/projects/.../7c1e4b2a.jsonl:6",
      "summary": "Requested a panel-entity architecture change."
    }
  ],
  "notes": null
}
```

`availability` is `advertised`, `installed_not_advertised`, `not_installed`, or
`unknown`. Keep medium/low candidates if useful, but only high-confidence misses
belong in headline counts.

## Recommendations

```json
{
  "recommendation_id": "rec_animation_reference",
  "category": "coverage",
  "priority": "medium",
  "applicable_installation_ids": [
    "github:a-poor/skills:skills/gpui/SKILL.md:3f9c1a7e"
  ],
  "evidence_ids": ["evt_codex_0198f2a1_call_abc"],
  "finding": "Animation tasks repeatedly required source research because the skill had no dedicated guidance.",
  "suggested_change": "Add a focused animation reference covering stable IDs, mounting, state ownership, and spring updates.",
  "caveat": "Some rework was caused by parallel edits rather than missing documentation."
}
```

`category` is one of `installation`, `triggering`, `navigation`, `correctness`,
`coverage`, `efficiency`, `versioning`, or `positive_pattern`. `priority` is
`high`, `medium`, or `low`.

Recommendations without evidence IDs are invalid. When evidence applies only to
an old installation, say so and do not list the current installation unless the
problem was independently verified there.

## Combining Reports

Combine mode follows these rules:

1. Reject or migrate unsupported `schema_version` values explicitly.
2. Ignore duplicate `report_id` inputs.
3. Require matching resolved target names unless the user supplies an alias map.
4. Preserve every installation fingerprint. Do not collapse unequal
   `computed_hash` values into one version.
5. Deduplicate events by `(machine_id, agent, native_id)` when `native_id` exists.
6. Otherwise use `(machine_id, agent, session_id, timestamp, kind, locator)`.
7. If two records share a deduplication key but conflict, retain both evidence
   sets and add a limitation instead of silently choosing one.
8. Aggregate physical records, logical events, and root conversations separately.
9. Cluster recommendations only when category, suggested change, and applicable
   fingerprints are compatible. Preserve all source evidence IDs.
10. Carry forward inaccessible, unsupported, and retention limitations.

A combined report adds provenance:

```json
{
  "combined_from": ["rpt_machine_a", "rpt_machine_b"],
  "combine_warnings": []
}
```

The combined Markdown synthesis should emphasize cross-machine recurrence,
version-specific differences, installation gaps, and recommendations supported by
independent roots. Frequency strengthens a finding but does not prove causation.

## Privacy Checks Before Writing

- Replace the home directory with `~`.
- Do not include raw hostname, username outside normalized paths, secrets, auth
  records, environment values, full source files, reasoning blobs, or binary data.
- Paraphrase prompts and outputs by default.
- If raw excerpts were requested, keep them short and redact unrelated details.
- Verify that report locators are useful without embedding transcript content.
