# Repository Guidelines

## Project Structure & Module Organization

This repository stores reusable agent skills as Markdown documents. Each skill
lives in `skills/<skill-name>/`, with a required `SKILL.md` entry point and optional
`references/` documents for detailed topics. Examples include `gpui`,
`automerge-rust`, `ratatui`, and `improve-skill`. `README.md` indexes the available
skills; update it when adding or renaming one. `LICENSE.md` contains the license.
There are no application source, executable test, or asset directories.

Keep activation guidance and core workflows in `SKILL.md`. Put longer API notes,
recipes, and examples in focused reference files, linked from the entry point.

## Build, Test, and Development Commands

There is no repository build, development server, package manifest, or configured
formatter/linter. Run these checks from the repository root:

- `rg --files skills` — inventory skill entry points and reference documents.
- `rg -n 'pattern' skills` — find related guidance before changing shared concepts.
- `git diff --check` — detect whitespace errors in tracked changes.
- `git diff --stat` and `git diff` — review the scope and content of tracked edits.
- `git status --short` — identify new files that ordinary diffs omit.

## Coding Style & Naming Conventions

Use lowercase, hyphen-separated directory and reference names, such as
`gpui-editor` and `terminal-and-events.md`; retain uppercase `SKILL.md`.
Begin each skill with YAML frontmatter containing `name` and `description`.
Match `name` to the directory and describe when the skill should activate.

Use two-space indentation for multiline YAML values, language-tagged fenced code
blocks, relative Markdown links, and concise instructional headings. Follow the
surrounding formatting; use four-space indentation in Rust examples.

## Testing Guidelines

No automated test framework, coverage threshold, or executable test naming
convention is configured. Files such as `references/test.md` document testing in
consumer projects. Before submitting, check frontmatter syntax, relative link
targets, code fences, and consistency between entry points and references. For API
changes, verify examples against the target project's pinned dependencies or
upstream documentation, and state which examples were actually exercised.

## Commit & Pull Request Guidelines

History uses short, descriptive subjects such as `Adds ratatui` and
`Fix GPUI SVG color guidance and icon recipe`; Conventional Commit prefixes are
not established. Keep commits focused on a skill or coherent documentation change.

In pull requests, identify affected skills, explain the corrected behavior or new
coverage, and summarize validation. Link relevant issues or upstream sources when
applicable. Exclude credentials and private session transcripts from examples.
