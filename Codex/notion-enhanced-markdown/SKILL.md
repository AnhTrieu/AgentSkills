---
name: notion-enhanced-markdown
description: Generate Notion page content in Notion-flavored “Enhanced Markdown” (tabs for indentation, Notion block tags, mentions, callouts, tables, toggles, etc.). Use when drafting, converting, or validating documents intended to be pasted into Notion or sent via Notion tools/APIs that expect Notion Enhanced Markdown; and when fixing Notion rendering issues caused by indentation, escaping, or unsupported block types.
---

# Notion Enhanced Markdown

## Quick start

- Draft the document as Notion-flavored Enhanced Markdown (not GitHub Markdown).
- Follow the rules in `references/enhanced-markdown-spec.md` (load it when unsure).
- Keep indentation as literal **tabs** (never spaces) for nested children blocks.
- If you wrote the content in a file, lint it with `python3 scripts/lint_notion_markdown.py path/to/doc.md`.

## Workflow

### 1) Clarify target context

- Prefer “page content” blocks (callouts, toggles, columns, tables, etc.) only when the destination supports them.
- If the user is updating an existing Notion page via an API/tool: avoid accidental moves (see “Safety” below).

### 2) Lay out blocks first

- Use headings (up to `####`) and lists for structure.
- Use callouts for “TL;DR” or warnings; toggles for collapsible detail; tables only when rich-text-only cells are acceptable.

### 3) Write content with spec compliance

Use `references/enhanced-markdown-spec.md` as the source of truth. Common pitfalls:

- **Indentation**: Use literal tabs for nesting children blocks (no leading spaces).
- **Empty lines**: Don’t use blank lines; use `<empty-block/>` (alone on its line) only if an intentional empty block is required.
- **Lists**: Never emit an empty list item. Always include inline rich text after `- ` or `1. `.
- **Escaping**: Outside code blocks, escape these characters with backslash: `\\` `*` `~` `` ` `` `$` `[` `]` `<` `>` `{` `}` `|` `^`.
- **Code blocks**: Do **not** escape characters inside fenced code blocks; content is literal.
- **Headings**: Don’t use heading levels 5–6 (`#####` / `######`); Notion will coerce them.

### 4) Validate (optional but recommended)

- If you generated the document in a file, run `python3 scripts/lint_notion_markdown.py ...` and fix reported issues.
- If you pasted directly into a tool call, do a quick manual scan for tabs, blank lines, and empty list items.

## Safety

- Prefer `<mention-page>` / `<mention-database>` over `<page>` / `<database>` when referencing existing Notion entities; embedding `<page url="...">` or `<database url="...">` can MOVE them.
- For meeting notes blocks: when creating new ones, omit `<summary>` and `<transcript>`; include `<notes>` only if the user explicitly requested note content.

## Reference

- Full specification: `references/enhanced-markdown-spec.md`
- Tip: use `rg` to jump to a block type, e.g. `rg -n 'Meeting notes:' references/enhanced-markdown-spec.md`
