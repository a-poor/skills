# Local Agent History Sources

Agent storage formats change. Discover what exists, inspect schemas before relying
on them, and record the agent version when available. The locations and selectors
below are starting points, not permission to treat every textual match as usage.

Set a single normalized target name first. Skill names should be lowercase and
hyphen-separated, which keeps the sample regular expressions safe:

```bash
TARGET=gpui
```

Use `rg` for candidate discovery, `jq` for JSON Lines, and `sqlite3 -readonly` for
SQLite. Do not print whole matching transcripts. Extract IDs and locators first,
then read narrow context for the selected root sessions.

## Shared Controls

Before searching any store:

1. Record a UTC cutoff and the current audit lineage.
2. Record file counts and retained timestamp ranges.
3. Exclude post-cutoff records and the current audit lineage.
4. Normalize paths by replacing the home directory with `~` in reports.
5. Track parse failures; zero valid matches is different from an unreadable store.

Look for `skills-lock.json` in projects associated with candidate sessions:

```bash
rg --files -g 'skills-lock.json'
```

Read the target entry structurally with `jq`. The lock's `computedHash` is the
installed package fingerprint. It is not necessarily the SHA-256 of `SKILL.md`.

## Claude Code

### Common locations

| Path | Purpose |
|---|---|
| `~/.claude/history.jsonl` | Submitted prompt/command history; may outlive transcripts |
| `~/.claude/projects/**/*.jsonl` | Main and subagent transcripts |
| `~/.claude/file-history/` | Source snapshots; not invocation evidence |
| `~/Library/Application Support/Claude/local-agent-mode-sessions/` | macOS desktop audit and nested transcripts |
| `~/Library/Application Support/Claude/claude-code-sessions/` | Desktop session metadata |

Respect `CLAUDE_CONFIG_DIR` if it is set. Some stores may not exist.

### Native skill calls

Claude transcript rows commonly store a `Skill` tool call inside an assistant
message. Extract the content item and deduplicate by tool-use ID:

```bash
CLAUDE_ROOT="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"

rg --files "$CLAUDE_ROOT/projects" -g '*.jsonl' -0 |
  xargs -0 jq -rc --arg skill "$TARGET" '
    select(.type == "assistant") as $row
    | $row.message.content[]?
    | select(
        .type == "tool_use"
        and ((.name // "") | ascii_downcase) == "skill"
      )
    | (.input.skill // .input.name // "") as $loaded
    | select($loaded == $skill or ($loaded | endswith(":" + $skill)))
    | {
        source_file: input_filename,
        timestamp: $row.timestamp,
        session_id: ($row.sessionId // $row.session_id),
        native_id: .id,
        loaded_name: $loaded,
        args: (.input.args // null)
      }
  '
```

Namespaced names such as `plugin:gpui` still identify the base target when they
end in `:<target>`, but retain the full loaded name in evidence.

### Human slash commands

Submitted commands can survive in `history.jsonl` after their transcripts are
deleted:

```bash
jq -rc --arg skill "$TARGET" '
  (.display // .input // "") as $text
  | select($text | test("^/" + $skill + "([[:space:]]|$)"; "i"))
  | {
      timestamp: (.timestamp // null),
      session_id: (.sessionId // null),
      project: (.project // null),
      command: $text
    }
' "$CLAUDE_ROOT/history.jsonl"
```

Retained expanded commands commonly contain:

```xml
<command-name>/gpui</command-name>
```

Require a genuine human user record. Tool results and quoted transcripts can
contain identical XML. The expanded command, injected body, and subsequent
attribution still represent one logical invocation.

### Supporting and false-positive records

- `attachment.type == "skill_listing"` advertises availability only.
- `attributionSkill` marks later messages associated with a loaded skill; it does
  not represent a fresh invocation on every message.
- A user-role tool result is not a human prompt.
- Direct `Read`/shell access to `skills/<target>/SKILL.md` may be manual
  consultation, maintenance, evaluation, or a normal loader depending on context.
- Reads under `references/` are supporting usage. Associate them with the most
  recent activation in the same logical root.
- File-history snapshots, authored-artifact metadata, source imports, and project
  paths are not usage.
- Mirrored branches can repeat the same tool-use ID. Message UUID and tool-use ID
  are stronger deduplication keys than file path.

## Codex

### Common locations

| Path | Purpose |
|---|---|
| `~/.codex/sessions/**/*.jsonl` | Active rollout transcripts |
| `~/.codex/archived_sessions/**/*.jsonl` | Archived rollouts and possible fork replay |
| `~/.codex/history.jsonl` | Partial prompt history |
| `~/.codex/session_index.jsonl` | Thread `id`, `thread_name`, `updated_at`; cheap title/recency lookup without opening rollouts |
| `~/.codex/state_*.sqlite` | Thread metadata and lineage |
| `~/.codex/thread_history_*.sqlite` | Thread projections; can duplicate rollouts |
| `~/.codex/logs_*.sqlite` | Diagnostics that may recover calls missing from rollouts |
| `~/Library/Logs/com.openai.codex/` | macOS desktop operational logs |

Rollout JSONL is the canonical source when present. SQLite and logs supplement
missing rollouts; do not add their duplicated records to canonical counts.

### Canonical tool-call extraction

Codex often loads a skill by reading its `SKILL.md` through an `exec`-style tool,
not through a dedicated skill tool. Extract canonical tool inputs first:

```bash
CODEX_ROOT="${CODEX_HOME:-$HOME/.codex}"

rg --files "$CODEX_ROOT/sessions" "$CODEX_ROOT/archived_sessions" -g '*.jsonl' -0 |
  xargs -0 jq -rc '
    select(.type == "response_item")
    | select(
        .payload.type == "function_call"
        or .payload.type == "custom_tool_call"
        or .payload.type == "mcp_tool_call"
      )
    | {
        source_file: input_filename,
        timestamp,
        call_id: (.payload.call_id // .payload.id),
        tool: (.payload.name // null),
        input: (
          (.payload.arguments // .payload.input // "")
          | if type == "string" then . else tojson end
        )
      }
  ' |
  rg -i "(^|/)${TARGET}/SKILL\\.md"
```

Confirm the corresponding tool output succeeded and actually returned content.
Commands such as `cat`, a content-bearing `sed` range, or a direct read usually
qualify. `ls`, `test -f`, `wc -l`, a path-only grep result, and failed reads do not.

Also detect newer structured skill tools if present rather than assuming file
reads are the only mechanism.

### Commands, injected bodies, and advertisements

Extract only canonical `response_item` user message text before testing for an
anchored `/target` or `$target`. User-role wrappers can contain plugin lists,
approval transcripts, or inherited child prompts, so confirm human/root origin.

An injected payload such as this is strong evidence of activation:

```xml
<skill><name>gpui</name>...</skill>
```

Link it to the originating command or loader instead of counting it separately.

Developer skill catalogs and `world_state.host_skills` prove availability only.
Catalog paths may use aliases such as `r8/gpui/SKILL.md`; resolve the alias before
assigning an installation fingerprint.

### Deduplication and lineage

- Use `call_id` for tool calls.
- Ignore `event_msg` and completion projections when the canonical
  `response_item` exists.
- Archived forks can replay identical call IDs from an active rollout.
- Child agents can replay the root human request as a user message.
- Approval/review agents can embed entire transcripts as user-role data.
- Count a first skill read in each isolated child as a physical activation, then
  associate all descendants with their logical root conversation.
- Repeated reads in later turns may follow compaction or topic changes. Report
  them, but do not equate every reread with a new user task.
- Diagnostic SQLite rows can recover calls from missing rollouts. Join by thread
  and call ID before adding them.

## OpenCode

### Common locations

Respect XDG overrides:

| Path | Purpose |
|---|---|
| `${XDG_DATA_HOME:-~/.local/share}/opencode/opencode.db` | Canonical SQLite transcripts |
| `${XDG_STATE_HOME:-~/.local/state}/opencode/prompt-history.jsonl` | Prompt history without reliable session timestamps |
| `${XDG_DATA_HOME:-~/.local/share}/opencode/log/` | Operational logs |
| `${XDG_DATA_HOME:-~/.local/share}/opencode/storage/` | Legacy/migration metadata in newer versions |

Do not assume legacy `storage/` contains current transcripts. Inspect the live
database schema first:

```bash
sqlite3 -readonly "$HOME/.local/share/opencode/opencode.db" '.tables'
sqlite3 -readonly "$HOME/.local/share/opencode/opencode.db" '.schema session'
sqlite3 -readonly "$HOME/.local/share/opencode/opencode.db" '.schema message'
sqlite3 -readonly "$HOME/.local/share/opencode/opencode.db" '.schema part'
```

Do not open a WAL-mode live database with `immutable=1`; that can hide committed
data still present in the WAL. Use `-readonly` and `PRAGMA query_only=ON`.

### Canonical part rows

In the observed schema, `message.data` contains the role and `part.data` contains
text or tool state. Adapt after schema inspection if the installed version differs:

```bash
DB="${XDG_DATA_HOME:-$HOME/.local/share}/opencode/opencode.db"
CUTOFF_MS=$(( $(date +%s) * 1000 ))

sqlite3 -readonly -json "$DB" "
  PRAGMA query_only=ON;
  SELECT
    s.id AS session_id,
    s.parent_id AS parent_session_id,
    p.id AS part_id,
    p.time_created,
    json_extract(m.data, '$.role') AS role,
    json_extract(p.data, '$.type') AS part_type,
    json_extract(p.data, '$.tool') AS tool,
    json_extract(p.data, '$.callID') AS call_id,
    coalesce(
      json_extract(p.data, '$.state.input.name'),
      json_extract(p.data, '$.state.input.skill')
    ) AS skill_name,
    coalesce(
      json_extract(p.data, '$.state.input.filePath'),
      json_extract(p.data, '$.state.input.path')
    ) AS file_path,
    json_extract(p.data, '$.state.status') AS status,
    json_extract(p.data, '$.text') AS text
  FROM part p
  JOIN message m ON m.id = p.message_id
  JOIN session s ON s.id = p.session_id
  WHERE p.time_created < $CUTOFF_MS
    AND instr(lower(p.data), lower('$TARGET')) > 0;
"
```

Classify from canonical parts:

- A completed tool named `skill` whose input name equals the target is a native
  skill call.
- A completed read of a path ending in `/<target>/SKILL.md` is a skill-file read.
- A user text beginning with `/target` followed by whitespace or end-of-string is
  an explicit command candidate.
- Parent sessions distinguish human root prompts from task-generated child prompts.
- Deduplicate tool rows by `call_id` (`part.data.callID`); it survives `event`
  table projections where the part row ID may not.

The `event` table can contain repeated snapshots of the same part. Do not count it
when canonical `part` rows exist. Session titles, tool search inputs, tool outputs,
and the current audit request are frequent self-referential false positives.

Runtime system prompts and complete advertised skill catalogs may not be persisted.
Absence of an advertisement record is therefore `unknown`, not proof that the
skill was unavailable.

Prompt history can confirm submitted slash commands, but it may lack timestamps
and session IDs. Logs can confirm command dispatch, permission checks, or completed
file touches, but search commands echoed into logs are not usage.

## Missed-Trigger Search Across Agents

After identifying actual uses, derive a short list of distinctive trigger cues
from the target description and navigation. Search root human prompts for those
cues, then confirm relevance using project dependencies, imports, and material
edits. Require more than a broad keyword.

Use these checks in order:

1. Was the target advertised, installed, or unavailable in that session?
2. Did substantive target-domain work occur?
3. Was the skill activated before the relevant work?
4. Was the full skill or a relevant reference manually consulted instead?
5. Is the session maintenance, evaluation, or a trivial change?
6. Did relevance emerge only in a later turn?

Store high-confidence misses separately from weak candidates. A missing skill in
an unrelated workspace supports an installation recommendation, not a claim that
the agent ignored an available skill.
