# skills

A central place for me to store some reusable skills.

- [gpui](./skills/gpui/SKILL.md): Skill for working with Rust and [GPUI](https://gpui.rs/)
- [gpui-editor](./skills/gpui-editor/SKILL.md): Skill for adding editor components to a [GPUI](https://gpui.rs/) app
- [gpui-style](./skills/gpui-style/SKILL.md): Skill for styling [GPUI](https://gpui.rs/) apps
- [automerge-rust](./skills/automerge-rust/SKILL.md): Skill for working with [Automerge](https://github.com/automerge/automerge) in Rust
- [ratatui](./skills/ratatui/SKILL.md): Skill for working building TUIs in Rust with [Ratatui](https://github.com/ratatui/ratatui)
- [smart-brevity](./skills/smart-brevity/SKILL.md): Skill for writing like Axios
- [improve-skill](./skills/improve-skill/SKILL.md): Skill for auditing how agent skills are used across local Claude Code, Codex, and OpenCode histories

## Validation

Run `ruby tools/check-skills.rb` for skill frontmatter, balanced fences, and local
file links, then `git diff --check` for whitespace. Link fragments and API
correctness require separate review. The [GPUI recipe harness](validation/gpui/README.md)
compiles and runs selected examples directly from the Markdown against a stated
Zed revision.
