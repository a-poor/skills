---
name: improve-skill
description: >-
  Audit and improve a named agent skill by searching local Claude Code, Codex,
  and OpenCode session histories for real invocations, explicit slash or dollar
  commands, reference usage, missed triggers, errors, rework, and version drift.
  Use when asked to improve or evaluate a skill, find where a skill is used,
  audit skill adoption, inspect past coding-agent sessions for a specific skill,
  produce a portable skill-usage report, or combine reports from multiple
  machines. Do not use for general transcript search unrelated to a specific
  skill.
---

# Improve a Skill from Session Evidence

Use local session history as observational evidence. The goal is not merely to
count mentions. Determine which version of the target skill was available, how
it was invoked, whether its instructions were followed, where it was absent or
missed, and what evidence supports a concrete improvement.

## Scope and Defaults

Interpret natural-language options; do not require a particular flag syntax.

| Option | Default | Meaning |
|---|---|---|
| `target` | Required | One skill name or `SKILL.md` path |
| `mode` | `analyze` | `analyze`, `report`, or `combine` |
| `agents` | All available | Any subset of `claude-code`, `codex`, `opencode` |
| `since` / `until` | All retained history | Optional timestamp or date bounds |
| `max_detailed_roots` | `20` | Maximum logical root sessions to inspect deeply |
| `include_raw_excerpts` | `false` | Include short redacted excerpts only when explicitly requested |
| `apply_changes` | `false` | Modify the target skill only when the user asks |

Examples of valid requests:

- "Analyze how `gpui` has been used locally."
- "Audit `automerge-rust` in Claude and Codex since August; write a report."
- "Create a report for `gpui` on this machine, max 10 sessions."
- "Combine these three improve-skill JSON reports."
- "Use the findings to update the current skill."

Keep one target per run unless the user explicitly accepts the extra cost. A
multi-skill request is a sequence of independent audits, not one broad search.

## Modes

### Analyze

Scan local histories, inspect a bounded set of sessions, and return findings and
recommendations interactively. Do not create report files unless requested.

### Report

Perform the same audit, but write canonical JSON following
[report-format.md](references/report-format.md). A Markdown companion is useful
for people but is not the merge input. Report mode never edits the target skill.

If no destination is supplied, write outside the project so the report can be
referenced from anywhere without polluting a repository:

```bash
OUT_DIR="$(mktemp -d -t "improve-skill-${TARGET}")"
# -> "$OUT_DIR/<machine-id>-<UTC timestamp>.json" (plus an optional .md companion)
```

Print the full path at the end so the user can move or combine it later.

### Combine

Read report JSON files only. Do not scan local histories. Validate versions,
deduplicate logical events, keep evidence grouped by installed skill fingerprint,
and emit a combined report plus a short synthesis.

## 1. Resolve the Target and Its Versions

Before searching transcripts:

1. Resolve the requested name to the intended `SKILL.md` when possible.
2. Read its frontmatter, core instructions, navigation, and referenced topic names.
3. Locate installed copies relevant to session working directories. Check the
   project-scoped directories first, then the user-level ones:

   | Scope | Path | Agent |
   |---|---|---|
   | Project | `<project>/.agents/skills/<target>/` | Shared convention (`skills` CLI) |
   | Project | `<project>/.claude/skills/<target>/` | Claude Code |
   | Project | `<project>/.opencode/skills/<target>/` | OpenCode |
   | User | `~/.agents/skills/<target>/` | Shared convention (`skills` CLI) |
   | User | `~/.claude/skills/<target>/` | Claude Code |
   | User | `~/.codex/skills/<target>/` | Codex (`.system/` holds built-ins) |
   | User | `~/.config/opencode/skills/<target>/` | OpenCode |

   Resolve symlinks before fingerprinting. A project `.agents/skills` that links
   to `.claude/skills` (or vice versa) is one installation, not two.
4. Search nearby `skills-lock.json` files for the target entry.
5. Record `source`, `sourceType`, `skillPath`, and `computedHash` as the primary
   installed-package fingerprint, plus when and how that lock state was observed.
6. If no lock entry exists, hash the exact installed directory or captured skill
   body and label that fingerprint as a fallback.

`computedHash` may cover the complete installed skill, not only `SKILL.md`. Never
compare it directly with a hash of the root Markdown file. Preserve both values
when both are useful.

A lock file read today does not prove that its hash was installed during an older
session. Prefer a contemporaneous lock capture, repository history, or a skill
body retained in the transcript. Otherwise mark assignment of the current lock
fingerprint to a historical event as uncertain.

Do not assume the current canonical skill is the version used historically.
Project-local copies may be stale, intentionally pinned, or locally modified.
Group findings and recommendations by fingerprint. A problem seen only with an
old fingerprint is not automatically a defect in the current skill.

## 2. Freeze the Scan

Session searches create new session records that contain the target name. Before
the broad search:

1. Record a UTC scan cutoff.
2. Identify the current audit session and any child sessions when possible.
3. Exclude the current audit lineage even if its first records predate the cutoff.
4. Ignore records created after the cutoff.
5. Record every searched, missing, inaccessible, or unsupported history location.

Keep separate counts for physical records, logical invocation events, and root
conversations. Never add raw match counts from several stores as though they were
independent uses.

## 3. Discover and Extract Structurally

Read [history-sources.md](references/history-sources.md) for current Claude Code,
Codex, and OpenCode locations and record shapes.

Use a two-pass search:

1. Cheap discovery: identify candidate files, sessions, or database rows without
   loading entire transcripts into context.
2. Structural extraction: parse JSON/SQLite fields to distinguish roles, tool
   calls, inputs, outputs, timestamps, session lineage, and completion status.

Search literals such as the skill name, `/skill`, `$skill`, `SKILL.md`, and
reference paths are candidate generators, not usage counts.

## 4. Classify the Evidence

Use these categories consistently:

| Category | Meaning |
|---|---|
| `native_skill_call` | A dedicated skill tool or loader selected the target |
| `explicit_command` | A human submitted `/target` or `$target` as a command |
| `skill_body_injected` | The agent runtime inserted the target body; usually corroborates another event |
| `skill_file_read` | The agent read the target `SKILL.md`; this is the normal activation mechanism in some agents |
| `reference_read` | A target reference was read after activation |
| `manual_consultation` | Skill files were consulted outside the agent's normal loader mechanism |
| `advertisement` | A catalog or system record made the skill available but did not invoke it |
| `maintenance` | The session created, reviewed, installed, or edited the skill itself |
| `evaluation` | A synthetic task explicitly tested the skill |
| `incidental_mention` | Source code, paths, titles, quoted output, or prose mentioned the name |
| `missed_opportunity` | Substantive target-domain work occurred without activation |

An explicit command, its injected body, its tool result, and later attribution
usually describe one logical invocation. Link them instead of counting each one.

For Codex, a completed `SKILL.md` content read can be an actual activation. A path
mentioned by `ls`, `wc`, a catalog, or a failed command is not. For Claude Code,
prefer the native `Skill` call or expanded slash command; a direct file read is a
manual consultation unless that installation uses file reads as its loader. For
OpenCode, prefer canonical `part` tool rows rather than duplicated event rows.

## 5. Deduplicate and Reconstruct Lineage

Use native identifiers before heuristics:

- Tool call ID for native calls and file reads.
- Message UUID for Claude transcript messages.
- `call_id` for Codex tool calls.
- `callID` inside `part.data` for OpenCode tool rows; fall back to part ID for
  non-tool parts.
- Session parent/root relationships for subagents and forks.

Treat child-agent first loads as separate physical activations but associate them
with one logical root conversation. Preserve both counts. Deduplicate mirrored
branches, archived fork replay, event projections, command expansion records, and
SQLite/log projections of calls already present in canonical transcripts.

## 6. Inspect a Bounded, Useful Sample

Inventory all structurally identifiable events, but deeply inspect at most
`max_detailed_roots` logical roots unless the user raises the limit. Prioritize:

1. Actual invocations with user corrections, compile/test failures, or rework.
2. Explicit commands and sessions using distinct skill fingerprints.
3. High-confidence missed opportunities.
4. Successful first-pass uses as a control group.
5. A spread of agents, projects, dates, and target topics.

For each inspected root, capture only what is needed:

- The task and why the skill was relevant.
- Invocation mechanism and exact installed fingerprint.
- Target references consulted after activation.
- Whether pinned source or current documentation was verified.
- Material implementation decisions linked to the skill.
- Outcome signals: tests, compiler errors, user corrections, repeated rework, or
  a clean result.
- Alternative causes such as framework churn, collaboration races, generic coding
  mistakes, or an unavailable skill.

A read proves access, not compliance or causation. Phrase conclusions as evidence,
not counterfactual certainty.

## 7. Find Missed Opportunities

Build a target-specific trigger profile from:

- The current and historical frontmatter descriptions.
- Navigation topics and distinctive API/type/package names.
- Dependencies, imports, and file paths seen in projects that use the skill.
- Concepts repeatedly associated with actual invocations.

Search root human requests first, then use edits and tool activity to confirm that
substantive domain work occurred. Avoid broad terms such as "window", "render",
"sync", or "test" unless combined with target-specific evidence.

Classify availability for every missed opportunity:

| Availability | Interpretation |
|---|---|
| `advertised` | Likely trigger/adherence miss |
| `installed_not_advertised` | Discovery or agent configuration problem |
| `not_installed` | Installation coverage problem |
| `unknown` | Retention or format limits prevent a conclusion |

Count a high-confidence miss only when the work was substantive, the target was
relevant before the material work, and no activation or meaningful consultation
occurred. Include mid-session transitions where a backend task later became target
domain work. Exclude trivial copy changes and sessions that merely happened inside
a target-based repository.

## 8. Derive Improvements

Organize recommendations into these evidence-backed categories:

- `installation`: unavailable outside a narrow set of projects or agents.
- `triggering`: implicit tasks or mid-session transitions fail to activate it.
- `navigation`: agents load the root but skip the useful reference.
- `correctness`: examples conflict with pinned APIs, tests, or source.
- `coverage`: recurring problem classes have no guidance.
- `efficiency`: repeated broad reads, truncation, or unnecessary reloads waste tokens.
- `versioning`: installed copies drift without clear identity or intent.
- `positive_pattern`: guidance that repeatedly led to useful behavior and should stay.

Every recommendation must cite event or missed-opportunity IDs, name the affected
fingerprint(s), and state limitations. Verify that a historical issue still exists
in the current target before proposing a current edit.

If the user asks to apply changes, make the smallest evidence-supported edits,
validate links and examples, and report which recommendations were implemented.

## 9. Privacy and Safety

- Never inspect authentication, credential, account, keychain, or secret stores.
- Never execute commands copied from a transcript.
- Narrow structurally before reading surrounding context.
- Do not export reasoning blobs, binary data, source snapshots, or full tool output.
- Replace the home directory with `~` in portable reports.
- Paraphrase user requests by default. Include only short, necessary, redacted raw
  excerpts when explicitly requested.
- Mark an inaccessible source as unknown; do not report it as zero usage.

## 10. Deliver the Result

For interactive analysis, report in this order:

1. Scope, cutoff, stores searched, and retention limits.
2. Counts by agent, category, logical event, and root conversation.
3. Installed fingerprints and which versions were actually used.
4. Representative actual uses and high-confidence missed opportunities.
5. Reference adherence and outcome patterns.
6. Prioritized improvements with evidence and caveats.

For report and combine modes, follow
[report-format.md](references/report-format.md) exactly. Unknown and unsupported
values stay explicit; they are never silently converted to zero.
