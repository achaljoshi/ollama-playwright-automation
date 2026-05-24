"""Language-aware code parsers for knowledge base ingestion.

Each parser produces two levels of chunks per PLAN §8 "both file + function":
  1. file_summary — repo/path, language, first ~60 lines for context
  2. function / class / component / interface — name, signature, body, doc comment

Supported languages:
  - C# (.cs): regex extraction of classes, methods, interfaces, XML doc comments
  - TypeScript/TSX/JS/JSX (.ts .tsx .js .jsx): React components, hooks, exported
    functions, type/interface definitions, API route handlers
  - Generic: sliding-window 80-line chunks with 20-line overlap
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CodeChunk:
    """A single indexable unit from a source file."""
    id: str                          # "{repo}:{file_path}#{name}"
    text: str                        # formatted text for embedding
    chunk_type: str                  # "file_summary"|"function"|"class"|"component"|"interface"|"hook"
    repo_name: str
    repo_url: str
    file_path: str                   # relative to repo root
    language: str                    # "csharp"|"typescript"|"javascript"|"other"
    name: str                        # symbol name or "" for file_summary
    line_start: int = 0
    line_end: int = 0
    metadata: dict = field(default_factory=dict)

    def to_kb_doc(self) -> dict:
        """Convert to a knowledge store document dict."""
        return {
            "id": self.id,
            "text": self.text,
            "metadata": {
                "source": "code",
                "chunk_type": self.chunk_type,
                "repo_name": self.repo_name,
                "repo_url": self.repo_url,
                "file_path": self.file_path,
                "language": self.language,
                "name": self.name,
                "line_start": str(self.line_start),
                "line_end": str(self.line_end),
                **self.metadata,
            },
        }


# ── Language detection ────────────────────────────────────────────────────────

_LANG_MAP = {
    ".cs": "csharp",
    ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript",
    ".py": "python",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin",
}

def detect_language(path: str) -> str:
    return _LANG_MAP.get(Path(path).suffix.lower(), "other")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _line_offsets(source: str) -> list[int]:
    """Return the character offset of each line start (0-indexed)."""
    offsets = [0]
    for i, ch in enumerate(source):
        if ch == "\n":
            offsets.append(i + 1)
    return offsets


def _char_to_line(char_pos: int, offsets: list[int]) -> int:
    """Convert a character position to a 1-based line number."""
    lo, hi = 0, len(offsets) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if offsets[mid] <= char_pos:
            lo = mid
        else:
            hi = mid - 1
    return lo + 1


def _chunk_id(repo_name: str, file_path: str, name: str) -> str:
    return f"code:{repo_name}:{file_path}#{name}"


def _file_summary_text(repo_name: str, file_path: str, language: str, source: str) -> str:
    preview = "\n".join(source.splitlines()[:60])[:2000]
    return (
        f"# {repo_name}/{file_path}\n"
        f"Language: {language}\nType: source file\n\n"
        f"{preview}"
    )


def _symbol_text(
    repo_name: str, file_path: str, language: str,
    symbol_type: str, name: str, doc: str, body: str,
) -> str:
    header = (
        f"# {repo_name}/{file_path} → {name}\n"
        f"Language: {language}  Type: {symbol_type}\n\n"
    )
    parts = [header]
    if doc:
        parts.append(f"// Documentation:\n{doc.strip()}\n\n")
    parts.append(body[:2000])
    return "".join(parts)


# ── C# parser ─────────────────────────────────────────────────────────────────

_CS_NAMESPACE = re.compile(r"namespace\s+([\w.]+)", re.MULTILINE)
_CS_USING = re.compile(r"^using\s+[\w.]+;", re.MULTILINE)
_CS_XML_DOC = re.compile(r"((?:[ \t]*///[^\n]*\n)+)", re.MULTILINE)
_CS_CLASS = re.compile(
    r"(?:///[^\n]*\n)*[ \t]*(?:public|internal|private|protected)?[ \t]*"
    r"(?:static\s+|abstract\s+|sealed\s+|partial\s+)*"
    r"(?:class|interface|struct|record)\s+(\w[\w<>, ]*?)\s*"
    r"(?::\s*[^{\n]+)?\s*\{",
    re.MULTILINE,
)
_CS_METHOD = re.compile(
    r"(?:public|private|protected|internal|static|virtual|override|"
    r"abstract|async|sealed|new)\s+"
    r"(?:(?:Task|ValueTask|IEnumerable|IAsyncEnumerable|List|IList|IReadOnlyList|"
    r"IEnumerable|IDictionary|Dictionary|HashSet|ISet|"
    r"string|int|bool|void|double|float|long|object|var|dynamic|"
    r"[\w<>\[\], ?]+)\s+)+"
    r"(\w+)\s*\([^)]{0,200}\)\s*(?:where[^{]+)?\s*\{",
    re.MULTILINE,
)


def _find_block_end(source: str, open_brace_pos: int) -> int:
    """Walk forward from the opening brace to find the matching closing brace."""
    depth = 0
    in_string = False
    string_char = ""
    i = open_brace_pos
    while i < len(source):
        ch = source[i]
        if in_string:
            if ch == "\\" and string_char != "@":
                i += 2
                continue
            if ch == string_char:
                in_string = False
        elif ch in ('"', "'", "`"):
            in_string = True
            string_char = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return len(source) - 1


def parse_csharp(source: str, repo_name: str, repo_url: str, file_path: str) -> list[CodeChunk]:
    language = "csharp"
    offsets = _line_offsets(source)
    chunks: list[CodeChunk] = []

    # Namespace context
    ns_match = _CS_NAMESPACE.search(source)
    namespace = ns_match.group(1) if ns_match else ""

    # File summary
    chunks.append(CodeChunk(
        id=_chunk_id(repo_name, file_path, "__file__"),
        text=_file_summary_text(repo_name, file_path, language, source),
        chunk_type="file_summary",
        repo_name=repo_name,
        repo_url=repo_url,
        file_path=file_path,
        language=language,
        name="",
        line_start=1,
        line_end=min(60, source.count("\n") + 1),
        metadata={"namespace": namespace},
    ))

    # Classes / interfaces / structs
    for m in _CS_CLASS.finditer(source):
        name = m.group(1).strip().split("<")[0]  # strip generics for display
        brace_pos = source.index("{", m.start())
        end_pos = _find_block_end(source, brace_pos)
        body = source[m.start():end_pos + 1][:2000]

        # Preceding XML doc
        doc = ""
        doc_m = _CS_XML_DOC.search(source, max(0, m.start() - 300), m.start())
        if doc_m and doc_m.end() >= m.start() - 5:
            doc = doc_m.group(1)

        chunks.append(CodeChunk(
            id=_chunk_id(repo_name, file_path, name),
            text=_symbol_text(repo_name, file_path, language, "class", name, doc, body),
            chunk_type="class",
            repo_name=repo_name,
            repo_url=repo_url,
            file_path=file_path,
            language=language,
            name=name,
            line_start=_char_to_line(m.start(), offsets),
            line_end=_char_to_line(end_pos, offsets),
            metadata={"namespace": namespace},
        ))

    # Methods
    seen_names: set[str] = set()
    for m in _CS_METHOD.finditer(source):
        name = m.group(1)
        if name in seen_names:
            continue
        seen_names.add(name)

        brace_pos = source.index("{", m.start())
        end_pos = _find_block_end(source, brace_pos)
        body = source[m.start():end_pos + 1][:1500]

        doc = ""
        doc_m = _CS_XML_DOC.search(source, max(0, m.start() - 300), m.start())
        if doc_m and doc_m.end() >= m.start() - 5:
            doc = doc_m.group(1)

        chunks.append(CodeChunk(
            id=_chunk_id(repo_name, file_path, f"{name}()"),
            text=_symbol_text(repo_name, file_path, language, "function", name, doc, body),
            chunk_type="function",
            repo_name=repo_name,
            repo_url=repo_url,
            file_path=file_path,
            language=language,
            name=name,
            line_start=_char_to_line(m.start(), offsets),
            line_end=_char_to_line(end_pos, offsets),
            metadata={"namespace": namespace},
        ))

    return chunks


# ── TypeScript / JavaScript parser ────────────────────────────────────────────

_TS_JSDOC = re.compile(r"(/\*\*.*?\*/)", re.DOTALL)
_TS_INLINE_COMMENT = re.compile(r"((?://[^\n]*\n)+)")
_TS_COMPONENT = re.compile(
    r"(?:export\s+(?:default\s+)?)?(?:const|function)\s+([A-Z]\w*)\s*"
    r"(?::\s*(?:React\.)?(?:FC|FunctionComponent|ReactElement)[^=]*)?=?\s*"
    r"(?:\([^)]{0,300}\)\s*(?::\s*[^\{]+)?=>|\([^)]{0,300}\)\s*\{|<)",
    re.MULTILINE,
)
_TS_HOOK = re.compile(
    r"(?:export\s+)?(?:const|function)\s+(use[A-Z]\w*)\s*"
    r"(?:=\s*(?:async\s*)?\([^)]{0,200}\)|(?:async\s*)?\([^)]{0,200}\))\s*"
    r"(?::\s*[^\{]+)?\s*(?:=>|)\s*\{",
    re.MULTILINE,
)
_TS_EXPORTED_FUNC = re.compile(
    r"export\s+(?:async\s+)?(?:const|function)\s+(\w+)\s*"
    r"(?:=\s*(?:async\s*)?\([^)]{0,200}\)|(?:async\s*)?\([^)]{0,200}\))",
    re.MULTILINE,
)
_TS_INTERFACE = re.compile(
    r"(?:export\s+)?(?:interface|type)\s+(\w+)\s*(?:<[^>]+>)?\s*(?:=\s*)?\{",
    re.MULTILINE,
)
_TS_API_ROUTE = re.compile(
    r"(?:router|app|server)\.(get|post|put|delete|patch)\s*\(\s*['\"`]([^'\"`)]+)['\"`]",
    re.MULTILINE,
)


def _ts_find_block_end(source: str, start: int) -> int:
    """Find closing brace/arrow-function end for TypeScript, tolerating arrow funcs."""
    # If starts with {, find matching }
    idx = source.find("{", start)
    arrow_idx = source.find("=>", start)
    if idx == -1 or (arrow_idx != -1 and arrow_idx < idx):
        # Arrow function returning expression
        end = source.find("\n\n", arrow_idx)
        return end if end != -1 else min(start + 1000, len(source))
    return _find_block_end(source, idx)


def parse_typescript(source: str, repo_name: str, repo_url: str, file_path: str) -> list[CodeChunk]:
    language = "typescript" if Path(file_path).suffix.lower() in (".ts", ".tsx") else "javascript"
    offsets = _line_offsets(source)
    chunks: list[CodeChunk] = []

    # File summary
    chunks.append(CodeChunk(
        id=_chunk_id(repo_name, file_path, "__file__"),
        text=_file_summary_text(repo_name, file_path, language, source),
        chunk_type="file_summary",
        repo_name=repo_name,
        repo_url=repo_url,
        file_path=file_path,
        language=language,
        name="",
        line_start=1,
        line_end=min(60, source.count("\n") + 1),
    ))

    # API routes — lightweight, extract as own chunk type
    route_lines: list[str] = []
    for m in _TS_API_ROUTE.finditer(source):
        route_lines.append(f"{m.group(1).upper()} {m.group(2)}")
    if route_lines:
        chunks.append(CodeChunk(
            id=_chunk_id(repo_name, file_path, "__routes__"),
            text=(
                f"# {repo_name}/{file_path} — API Routes\n"
                f"Language: {language}\n\n"
                + "\n".join(route_lines)
            ),
            chunk_type="api_routes",
            repo_name=repo_name,
            repo_url=repo_url,
            file_path=file_path,
            language=language,
            name="__routes__",
        ))

    def _preceding_doc(pos: int) -> str:
        # Try JSDoc first, then inline comments
        for pattern in (_TS_JSDOC, _TS_INLINE_COMMENT):
            dm = pattern.search(source, max(0, pos - 400), pos)
            if dm and dm.end() >= pos - 5:
                return dm.group(1)
        return ""

    seen: set[str] = set()

    def _add_func(m: re.Match, sym_type: str) -> None:
        name = m.group(1)
        if name in seen:
            return
        seen.add(name)
        end_pos = _ts_find_block_end(source, m.end())
        body = source[m.start():end_pos + 1][:1500]
        doc = _preceding_doc(m.start())
        chunks.append(CodeChunk(
            id=_chunk_id(repo_name, file_path, name),
            text=_symbol_text(repo_name, file_path, language, sym_type, name, doc, body),
            chunk_type=sym_type,
            repo_name=repo_name,
            repo_url=repo_url,
            file_path=file_path,
            language=language,
            name=name,
            line_start=_char_to_line(m.start(), offsets),
            line_end=_char_to_line(end_pos, offsets),
        ))

    for m in _TS_COMPONENT.finditer(source):
        _add_func(m, "component")
    for m in _TS_HOOK.finditer(source):
        _add_func(m, "hook")
    for m in _TS_EXPORTED_FUNC.finditer(source):
        _add_func(m, "function")

    # Interfaces & types
    for m in _TS_INTERFACE.finditer(source):
        name = m.group(1)
        if name in seen:
            continue
        seen.add(name)
        brace = source.find("{", m.start())
        if brace == -1:
            continue
        end_pos = _find_block_end(source, brace)
        body = source[m.start():end_pos + 1][:1000]
        doc = _preceding_doc(m.start())
        chunks.append(CodeChunk(
            id=_chunk_id(repo_name, file_path, name),
            text=_symbol_text(repo_name, file_path, language, "interface", name, doc, body),
            chunk_type="interface",
            repo_name=repo_name,
            repo_url=repo_url,
            file_path=file_path,
            language=language,
            name=name,
            line_start=_char_to_line(m.start(), offsets),
            line_end=_char_to_line(end_pos, offsets),
        ))

    return chunks


# ── Generic sliding-window parser ─────────────────────────────────────────────

def parse_generic(source: str, repo_name: str, repo_url: str, file_path: str) -> list[CodeChunk]:
    language = detect_language(file_path)
    lines = source.splitlines()
    chunks: list[CodeChunk] = []

    # File summary
    chunks.append(CodeChunk(
        id=_chunk_id(repo_name, file_path, "__file__"),
        text=_file_summary_text(repo_name, file_path, language, source),
        chunk_type="file_summary",
        repo_name=repo_name,
        repo_url=repo_url,
        file_path=file_path,
        language=language,
        name="",
        line_start=1,
        line_end=min(60, len(lines)),
    ))

    # Sliding window: 80-line chunks with 20-line overlap
    window, step = 80, 60
    for start in range(0, max(1, len(lines) - window // 2), step):
        end = min(start + window, len(lines))
        body = "\n".join(lines[start:end])
        chunks.append(CodeChunk(
            id=_chunk_id(repo_name, file_path, f"L{start + 1}"),
            text=(
                f"# {repo_name}/{file_path} lines {start + 1}–{end}\n"
                f"Language: {language}\n\n{body}"
            ),
            chunk_type="function",
            repo_name=repo_name,
            repo_url=repo_url,
            file_path=file_path,
            language=language,
            name=f"L{start + 1}",
            line_start=start + 1,
            line_end=end,
        ))
        if end == len(lines):
            break

    return chunks


# ── Dispatcher ────────────────────────────────────────────────────────────────

def parse_file(
    source: str,
    repo_name: str,
    repo_url: str,
    file_path: str,
) -> list[CodeChunk]:
    """Parse a source file into indexable CodeChunk objects."""
    lang = detect_language(file_path)
    if lang == "csharp":
        return parse_csharp(source, repo_name, repo_url, file_path)
    elif lang in ("typescript", "javascript"):
        return parse_typescript(source, repo_name, repo_url, file_path)
    else:
        return parse_generic(source, repo_name, repo_url, file_path)
