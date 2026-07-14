"""Type-aware chunking for the corpus.

The word window treated every document as prose, which cuts functions
in half and welds unrelated config keys together. This module picks a
boundary strategy from what the document actually is:

    code    .py on top-level function/class boundaries via ast;
            .js/.ts family via a depth-zero statement scan
    prose   .md and extracted HTML text, split on headings and then
            paragraphs, never across sections
    config  .json per top-level key; .toml per table; .yaml per
            top-level key

Each chunk contributes chunk_type (plus symbol, heading, or key where
one exists) to its Chroma metadata, so retrieval can filter or weight
by kind later. Anything unrecognised, and any file a specialised
splitter cannot make sense of, falls back to the exact word window
the corpus has always used: a new file type degrades to the old
behaviour instead of failing an ingest pass.

Chunking is pure and deterministic; the same input always yields the
same chunk list, which the deterministic sha1(repo:path:index) ids
depend on for idempotent re-ingestion. Sizes are in words throughout,
matching settings.chunk_words.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath


@dataclass
class Chunk:
    """One chunk of a document plus the metadata it contributes."""

    text: str
    metadata: dict = field(default_factory=dict)


_CODE_LANGUAGES = {
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
}


def chunk_document(path: str, text: str, doc_type: str, size: int, overlap: int) -> list[Chunk]:
    """Split one document by the strategy its type calls for."""
    suffix = PurePosixPath(path).suffix.lower()
    if suffix == ".py":
        return _chunk_python(text, size, overlap)
    if suffix in _CODE_LANGUAGES:
        return _chunk_javascript(text, size, overlap, _CODE_LANGUAGES[suffix])
    if suffix == ".json":
        return _chunk_json(text, size, overlap)
    if suffix == ".toml":
        return _chunk_toml(text, size, overlap)
    if suffix in (".yaml", ".yml"):
        return _chunk_yaml(text, size, overlap)
    # Markdown, extracted HTML (which arrives here as plain text), and
    # anything else prose-shaped take the heading/paragraph path, which
    # degrades to the plain word window when no structure exists.
    return _chunk_markdown(text, size, overlap)


def word_window(text: str, size: int, overlap: int) -> list[str]:
    """The original corpus splitter, kept as the universal fallback.

    Deliberately duplicated from app.ingester.chunk_words rather than
    imported, so chunking has no import edge back into the ingest
    machinery and stays independently testable.
    """
    words = text.split()
    if not words:
        return []
    if len(words) <= size:
        return [" ".join(words)]
    step = max(1, size - overlap)
    chunks = []
    for start in range(0, len(words), step):
        window = words[start : start + size]
        chunks.append(" ".join(window))
        if start + size >= len(words):
            break
    return chunks


def _words(text: str) -> int:
    return len(text.split())


def _fallback(text: str, size: int, overlap: int, base: dict) -> list[Chunk]:
    pieces = word_window(text, size, overlap)
    if len(pieces) == 1:
        return [Chunk(pieces[0], dict(base))]
    return [Chunk(piece, {**base, "part": index}) for index, piece in enumerate(pieces)]


def _emit(segment: str, base: dict, size: int, overlap: int) -> list[Chunk]:
    """One segment to one or more chunks, keeping metadata through splits."""
    if _words(segment) <= size:
        return [Chunk(segment, dict(base))]
    return [
        Chunk(piece, {**base, "part": index})
        for index, piece in enumerate(word_window(segment, size, overlap))
    ]


# --------------------------------------------------------------------- #
# Code                                                                    #
# --------------------------------------------------------------------- #


def _chunk_python(text: str, size: int, overlap: int) -> list[Chunk]:
    """Top-level function/class boundaries via the ast module.

    Interstitial code (imports, module docstring, constants, anything
    between definitions) chunks under the symbol "(module)". A file
    that does not parse is chunked as plain text rather than dropped;
    a syntax error in a source file is a fact worth indexing, not a
    reason to lose the document.
    """
    base = {"chunk_type": "code", "language": "python"}
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return _fallback(text, size, overlap, base)
    lines = text.splitlines()
    spans: list[tuple[int, int, str]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = node.lineno
            if node.decorator_list:
                start = min(start, min(dec.lineno for dec in node.decorator_list))
            spans.append((start - 1, node.end_lineno or start, node.name))
    if not spans:
        return _fallback(text, size, overlap, base)

    chunks: list[Chunk] = []
    cursor = 0
    for start, end, name in spans:
        between = "\n".join(lines[cursor:start]).strip()
        if between:
            chunks.extend(_emit(between, {**base, "symbol": "(module)"}, size, overlap))
        body = "\n".join(lines[start:end]).strip()
        if body:
            chunks.extend(_emit(body, {**base, "symbol": name}, size, overlap))
        cursor = max(cursor, end)
    tail = "\n".join(lines[cursor:]).strip()
    if tail:
        chunks.extend(_emit(tail, {**base, "symbol": "(module)"}, size, overlap))
    return chunks or _fallback(text, size, overlap, base)


_JS_SYMBOL_RE = re.compile(
    r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?"
    r"(?:function\s*\*?\s*(?P<fn>[A-Za-z_$][\w$]*)"
    r"|class\s+(?P<cls>[A-Za-z_$][\w$]*)"
    r"|(?:const|let|var)\s+(?P<binding>[A-Za-z_$][\w$]*))"
)


def _js_statements(text: str) -> list[str] | None:
    """Split source into top-level statements with a depth scanner.

    Tracks strings, template literals (including ${} re-entry), and
    both comment styles; splits at depth-zero semicolons and closing
    braces. Regex literals are not modelled: a pathological one
    desynchronises the depth count, the scanner notices (depth below
    zero, or nonzero at end of input) and returns None so the caller
    falls back to the word window.
    """
    statements: list[str] = []
    depth = 0
    in_string: str | None = None
    template_depths: list[int] = []
    start = 0
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        peek = text[index + 1] if index + 1 < length else ""
        if in_string:
            if char == "\\":
                index += 2
                continue
            if in_string == "`":
                if char == "`":
                    in_string = None
                elif char == "$" and peek == "{":
                    template_depths.append(depth)
                    depth += 1
                    in_string = None
                    index += 2
                    continue
            elif char == in_string or char == "\n":
                in_string = None
            index += 1
            continue
        if char == "/" and peek == "/":
            newline = text.find("\n", index)
            index = length if newline == -1 else newline
            continue
        if char == "/" and peek == "*":
            close = text.find("*/", index + 2)
            index = length if close == -1 else close + 2
            continue
        if char in "'\"`":
            in_string = char
            index += 1
            continue
        if char in "([{":
            depth += 1
            index += 1
            continue
        if char in ")]}":
            depth -= 1
            if depth < 0:
                return None
            if char == "}" and template_depths and depth == template_depths[-1]:
                template_depths.pop()
                in_string = "`"
                index += 1
                continue
            if char == "}" and depth == 0:
                statements.append(text[start : index + 1])
                start = index + 1
            index += 1
            continue
        if char == ";" and depth == 0:
            statements.append(text[start : index + 1])
            start = index + 1
        index += 1
    if depth != 0 or in_string is not None:
        return None
    tail = text[start:]
    if tail.strip():
        statements.append(tail)
    return [statement for statement in statements if statement.strip()]


def _chunk_javascript(text: str, size: int, overlap: int, language: str) -> list[Chunk]:
    """Top-level statement boundaries for the JS/TS family.

    Named declarations big enough to stand alone (functions, classes,
    sizeable const bindings) become their own chunks carrying their
    symbol; runs of small statements (imports, exports, constants)
    pack together so a module head stays one coherent chunk.
    """
    base = {"chunk_type": "code", "language": language}
    statements = _js_statements(text)
    if statements is None:
        return _fallback(text, size, overlap, base)

    chunks: list[Chunk] = []
    buffer: list[str] = []

    def flush() -> None:
        if not buffer:
            return
        merged = "\n".join(buffer).strip()
        buffer.clear()
        if merged:
            chunks.extend(_emit(merged, {**base, "symbol": "(module)"}, size, overlap))

    for statement in statements:
        stripped = statement.strip()
        match = _JS_SYMBOL_RE.match(stripped)
        symbol = None
        callable_decl = False
        if match:
            groups = match.groupdict()
            if groups.get("fn"):
                symbol, callable_decl = groups["fn"], True
            elif groups.get("cls"):
                symbol, callable_decl = groups["cls"], True
            elif groups.get("binding"):
                symbol = groups["binding"]
        # A named function or class is always its own chunk: it is the
        # boundary retrieval wants. A const/let/var binding stands alone
        # only when it is substantial (multi-line, or a real fraction of
        # the chunk budget); trivial one-line bindings pack with imports.
        standalone = symbol is not None and (
            callable_decl or "\n" in stripped or _words(stripped) > max(20, size // 4)
        )
        if standalone:
            flush()
            chunks.extend(_emit(stripped, {**base, "symbol": symbol}, size, overlap))
        else:
            buffer.append(stripped)
            if sum(_words(item) for item in buffer) >= size:
                flush()
    flush()
    return chunks or _fallback(text, size, overlap, base)


# --------------------------------------------------------------------- #
# Prose                                                                   #
# --------------------------------------------------------------------- #

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def _chunk_markdown(text: str, size: int, overlap: int) -> list[Chunk]:
    """Heading-bounded sections, then whole paragraphs within them.

    A chunk never spans two sections, so retrieval of a decisions.md
    entry returns that entry, not that entry welded to its neighbour.
    Headings inside code fences are body text, not boundaries.
    """
    base = {"chunk_type": "prose"}
    sections: list[tuple[str, list[str]]] = [("", [])]
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            sections[-1][1].append(line)
            continue
        heading = None if in_fence else _HEADING_RE.match(line)
        if heading:
            sections.append((heading.group(2), [line]))
        else:
            sections[-1][1].append(line)

    chunks: list[Chunk] = []
    for heading_text, body_lines in sections:
        body = "\n".join(body_lines).strip()
        if not body:
            continue
        meta = dict(base)
        if heading_text:
            meta["heading"] = heading_text
        if _words(body) <= size:
            chunks.append(Chunk(body, meta))
            continue
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", body) if part.strip()]
        current: list[str] = []
        current_words = 0
        part = 0
        for paragraph in paragraphs:
            paragraph_words = _words(paragraph)
            if current and current_words + paragraph_words > size:
                chunks.append(Chunk("\n\n".join(current), {**meta, "part": part}))
                part += 1
                current, current_words = [], 0
            if paragraph_words > size:
                for piece in word_window(paragraph, size, overlap):
                    chunks.append(Chunk(piece, {**meta, "part": part}))
                    part += 1
                continue
            current.append(paragraph)
            current_words += paragraph_words
        if current:
            chunks.append(Chunk("\n\n".join(current), {**meta, "part": part}))
    return chunks or _fallback(text, size, overlap, base)


# --------------------------------------------------------------------- #
# Config                                                                  #
# --------------------------------------------------------------------- #


def _blocks_to_chunks(
    blocks: list[tuple[str, list[str]]], base: dict, size: int, overlap: int
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for name, block_lines in blocks:
        body = "\n".join(block_lines).strip()
        if not body:
            continue
        meta = dict(base)
        if name:
            meta["key"] = name
        chunks.extend(_emit(body, meta, size, overlap))
    return chunks


def _chunk_json(text: str, size: int, overlap: int) -> list[Chunk]:
    base = {"chunk_type": "config", "language": "json"}
    try:
        data = json.loads(text)
    except ValueError:
        return _fallback(text, size, overlap, base)
    if not isinstance(data, dict) or not data:
        return _fallback(text, size, overlap, base)
    chunks: list[Chunk] = []
    for key, value in data.items():
        rendered = json.dumps({key: value}, indent=2, ensure_ascii=False)
        chunks.extend(_emit(rendered, {**base, "key": str(key)}, size, overlap))
    return chunks


_TOML_TABLE_RE = re.compile(r"^\s*\[+\s*([^\]]+?)\s*\]+\s*$")


def _chunk_toml(text: str, size: int, overlap: int) -> list[Chunk]:
    """Textual split on top-level [table] headers, comments preserved.

    A parse-and-reserialise split would drop comments, which in this
    estate's config files carry the reasoning. Known limitation: a
    line inside a multi-line TOML string that looks like a table
    header will split early; the chunks stay searchable either way.
    """
    base = {"chunk_type": "config", "language": "toml"}
    blocks: list[tuple[str, list[str]]] = [("", [])]
    for line in text.splitlines():
        table = _TOML_TABLE_RE.match(line)
        if table:
            blocks.append((table.group(1), [line]))
        else:
            blocks[-1][1].append(line)
    return _blocks_to_chunks(blocks, base, size, overlap) or _fallback(text, size, overlap, base)


_YAML_KEY_RE = re.compile(r"""^["'A-Za-z0-9_-]+\s*:""")


def _chunk_yaml(text: str, size: int, overlap: int) -> list[Chunk]:
    """Textual split on column-zero keys; same reasoning as TOML."""
    base = {"chunk_type": "config", "language": "yaml"}
    blocks: list[tuple[str, list[str]]] = [("", [])]
    for line in text.splitlines():
        if _YAML_KEY_RE.match(line):
            name = line.split(":", 1)[0].strip().strip("\"'")
            blocks.append((name, [line]))
        else:
            blocks[-1][1].append(line)
    return _blocks_to_chunks(blocks, base, size, overlap) or _fallback(text, size, overlap, base)
