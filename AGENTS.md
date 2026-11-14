# Repository Guidelines

## Project Structure & Module Organization

This repository stores reusable agent skills as Markdown documents. Each skill
lives in `skills/<skill-name>/`, with a required `SKILL.md` entry point and optional
`references/` documents for detailed topics. Examples include `gpui`,
`automerge-rust`, `ratatui`, and `improve-skill`. `README.md` indexes the available
skills; update it when adding or renaming one. `LICENSE.md` contains the license.
Repository maintenance checks live in `tools/` and `validation/gpui/`. The latter
extracts selected Markdown recipes into a temporary Rust consumer for testing;
it is not an application shipped with the skills.

Keep activation guidance and core workflows in `SKILL.md`. Put longer API notes,
recipes, and examples in focused reference files, linked from the entry point.

## Build, Test, and Development Commands

There is no application build, development server, or configured formatter/linter.
Run these checks from the repository root:

- `rg --files skills` — inventory skill entry points and reference documents.
- `rg -n 'pattern' skills` — find related guidance before changing shared concepts.
- `git diff --check` — detect whitespace errors in tracked changes.
- `git diff --stat` and `git diff` — review the scope and content of tracked edits.
- `git status --short` — identify new files that ordinary diffs omit.
- `ruby tools/check-skills.rb` — validate frontmatter, fences, and local file links.
- `python3 validation/gpui/check.py` — compile and run the marked GPUI recipes;
  see `validation/gpui/README.md` for the required source pin and prerequisites.

## Coding Style & Naming Conventions

Use lowercase, hyphen-separated directory and reference names, such as
`gpui-editor` and `terminal-and-events.md`; retain uppercase `SKILL.md`.
Begin each skill with YAML frontmatter containing `name` and `description`.
Match `name` to the directory and describe when the skill should activate.

Use two-space indentation for multiline YAML values, language-tagged fenced code
blocks, relative Markdown links, and concise instructional headings. Follow the
surrounding formatting; use four-space indentation in Rust examples.

## Testing Guidelines

The GPUI harness covers only its explicitly marked recipes; there is no coverage
threshold or whole-repository API test suite. Files such as `references/test.md`
document testing in consumer projects. Before submitting, check frontmatter
syntax, relative link targets, code fences, and consistency between entry points
and references. For API
changes, verify examples against the target project's pinned dependencies or
upstream documentation, and state which examples were actually exercised.

## Commit & Pull Request Guidelines

History uses short, descriptive subjects such as `Adds ratatui` and
`Fix GPUI SVG color guidance and icon recipe`; Conventional Commit prefixes are
not established. Keep commits focused on a skill or coherent documentation change.

In pull requests, identify affected skills, explain the corrected behavior or new
coverage, and summarize validation. Link relevant issues or upstream sources when
applicable. Exclude credentials and private session transcripts from examples.
