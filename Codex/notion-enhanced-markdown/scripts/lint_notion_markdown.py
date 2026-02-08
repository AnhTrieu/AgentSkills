#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Issue:
	line_no: int
	kind: str  # "ERROR" | "WARN"
	message: str


_NUMBERED_LIST_RE = re.compile(r"^(\d+)\.\s*(.*)$")


def _leading_whitespace(line: str) -> str:
	match = re.match(r"^[\t ]*", line)
	return match.group(0) if match else ""


def lint_text(text: str) -> list[Issue]:
	issues: list[Issue] = []

	in_code_block = False
	in_equation_block = False

	lines = text.splitlines()
	for idx, raw_line in enumerate(lines, start=1):
		line = raw_line.rstrip("\n")
		stripped = line.lstrip("\t ")
		leading = _leading_whitespace(line)

		# Detect block delimiters even when nested (indented).
		is_code_fence = stripped.startswith("```")
		is_equation_delim = stripped == "$$"

		# Indentation rule: use tabs for indentation (no leading spaces).
		# Do not enforce inside code/equation content (literal), but DO enforce on delimiters.
		if (" " in leading) and not (in_code_block or in_equation_block) and stripped != "":
			issues.append(
				Issue(
					line_no=idx,
					kind="ERROR",
					message="Leading spaces detected; use tabs for indentation.",
				)
			)
		elif (" " in leading) and (is_code_fence or is_equation_delim):
			issues.append(
				Issue(
					line_no=idx,
					kind="ERROR",
					message="Delimiter line is indented with spaces; use tabs for nesting.",
				)
			)

		# Track code blocks (fenced with ```).
		if is_code_fence:
			in_code_block = not in_code_block
			continue

		# Track equation blocks (delimited by $$ on its own line).
		if is_equation_delim:
			in_equation_block = not in_equation_block
			continue

		# Skip content checks inside literal blocks.
		if in_code_block or in_equation_block:
			continue

		# Empty lines are stripped by Notion; require explicit empty block if intended.
		if line.strip() == "":
			issues.append(
				Issue(
					line_no=idx,
					kind="ERROR",
					message="Blank line detected; remove it or use <empty-block/> on its own line.",
				)
			)
			continue

		# <empty-block/> should be alone on its line (allowing indentation with tabs).
		if stripped == "<empty-block/>":
			if stripped != line.strip():
				# Already ensured no spaces indentation above; this catches trailing junk.
				pass
			continue

		# Warn for heading levels 5+.
		if stripped.startswith("#####"):
			issues.append(
				Issue(
					line_no=idx,
					kind="WARN",
					message="Heading level 5+ detected; Notion coerces to heading 4.",
				)
			)

		# Empty list items render awkwardly.
		if stripped.startswith("- "):
			after = stripped[2:].strip()
			if after == "":
				issues.append(
					Issue(
						line_no=idx,
						kind="ERROR",
						message="Empty bulleted list item; add inline rich text after '- '.",
					)
				)

		m = _NUMBERED_LIST_RE.match(stripped)
		if m:
			after = (m.group(2) or "").strip()
			if after == "":
				issues.append(
					Issue(
						line_no=idx,
						kind="ERROR",
						message="Empty numbered list item; add inline rich text after 'N.'.",
					)
				)

		# Safety warnings: embedding existing entities can MOVE them.
		if "<page " in stripped and 'url="' in stripped:
			issues.append(
				Issue(
					line_no=idx,
					kind="WARN",
					message="Found <page url=\"...\">; embedding an existing page URL can MOVE the page. Prefer <mention-page> unless moving is intended.",
				)
			)
		if "<database " in stripped and 'url="' in stripped:
			issues.append(
				Issue(
					line_no=idx,
					kind="WARN",
					message="Found <database url=\"...\">; embedding an existing database URL can MOVE the database. Prefer <mention-database> unless moving is intended.",
				)
			)

	return issues


def main(argv: list[str]) -> int:
	parser = argparse.ArgumentParser(
		description="Lint Notion-flavored Enhanced Markdown for common spec violations."
	)
	parser.add_argument("path", type=Path, help="Path to a Notion markdown file")
	args = parser.parse_args(argv)

	text = args.path.read_text(encoding="utf-8")
	issues = lint_text(text)

	if not issues:
		print("OK: no issues found")
		return 0

	for issue in issues:
		print(f"{args.path}:{issue.line_no}: {issue.kind}: {issue.message}")

	return 1 if any(i.kind == "ERROR" for i in issues) else 0


if __name__ == "__main__":
	raise SystemExit(main(sys.argv[1:]))

