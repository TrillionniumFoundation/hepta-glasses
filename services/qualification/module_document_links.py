"""Validate the narrow, stable anchor profile used by module primary documents.

This is navigation consistency, not semantic design review or release evidence.
Primary fragments must use a standalone explicit anchor immediately before a
Markdown heading (blank lines and HTML comments may intervene). A module marker,
a heading's renderer-dependent slug, a code example or a duplicate ID is not a
replacement for that anchor. Repository path custody is checked by the caller.
"""
from __future__ import annotations

import re
from pathlib import Path

MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
FRAGMENT = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
ANCHOR = re.compile(r''' {0,3}<a id=(["'])([a-z0-9]+(?:-[a-z0-9]+)*)\1></a>\s*''')
HEADING = re.compile(r" {0,3}#{1,6}\s+\S")
FENCE = re.compile(r" {0,3}(`{3,}|~{3,})(.*)")


class ModuleLinkError(ValueError):
    """The primary reference has no unambiguous, heading-bound explicit target."""


def _visible_lines(text: str) -> list[str]:
    visible: list[str] = []
    fence: str | None = None
    in_comment = False
    for line in text.splitlines():
        if fence is not None:
            close = re.fullmatch(r" {0,3}" + re.escape(fence[0]) +
                                 "{" + str(len(fence)) + r",}\s*", line)
            if close:
                fence = None
            visible.append("")
            continue
        parts: list[str] = []
        rest = line
        while rest:
            if in_comment:
                end = rest.find("-->")
                if end < 0:
                    rest = ""
                else:
                    rest = rest[end + 3:]
                    in_comment = False
            else:
                start = rest.find("<!--")
                if start < 0:
                    parts.append(rest)
                    rest = ""
                else:
                    parts.append(rest[:start])
                    rest = rest[start + 4:]
                    in_comment = True
        rendered = "".join(parts)
        opening = FENCE.fullmatch(rendered)
        if opening:
            fence = opening.group(1)
            visible.append("")
        else:
            visible.append(rendered)
    return visible


def validate_primary_fragment(document: Path, reference: str) -> None:
    """Reject absent, ambiguous or example-only primary fragment targets.

    No-fragment references retain the enclosing validator's existing path checks.
    This deliberately does not pretend to implement every Markdown renderer.
    """
    if "#" not in reference:
        return
    if reference.count("#") != 1:
        raise ModuleLinkError("primary reference has multiple fragment delimiters")
    fragment = reference.split("#", 1)[1]
    if not FRAGMENT.fullmatch(fragment):
        raise ModuleLinkError("primary fragment must be a stable lowercase identifier")
    if document.is_symlink() or not document.is_file():
        raise ModuleLinkError("primary fragment document is missing or linked")
    with document.open("rb") as source:
        raw = source.read(MAX_DOCUMENT_BYTES + 1)
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise ModuleLinkError("primary fragment document exceeds the size limit")
    try:
        lines = _visible_lines(raw.decode("utf-8"))
    except UnicodeError:
        raise ModuleLinkError("primary fragment document is not UTF-8") from None
    positions = [i for i, line in enumerate(lines)
                 if (match := ANCHOR.fullmatch(line)) and match.group(2) == fragment]
    if len(positions) != 1:
        raise ModuleLinkError("primary fragment requires exactly one explicit anchor")
    following = next((line for line in lines[positions[0] + 1:] if line.strip()), "")
    if HEADING.match(following) is None:
        raise ModuleLinkError("primary fragment anchor must immediately precede a heading")
