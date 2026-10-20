"""
Reads an uploaded requirement document (.docx, .pdf, .md, .txt) or a CSV
backlog of user stories, and splits it into sections small enough for one
generation call each: documents at their headings, a backlog one story per row.
"""
import io
import re
from dataclasses import dataclass

from core.file_import import MAX_UPLOAD_BYTES, FileImportError, parse_uploaded_rows

# Cap requirement length to avoid exceeding the model's context/token limit
# with a confusing error — ~40,000 characters is roughly ~10,000 tokens.
# The same limit applies to pasted text and to each section of a file.
MAX_REQUIREMENT_CHARS = 40000

SUPPORTED_SUFFIXES = ("docx", "pdf", "md", "txt", "csv")
MAX_PDF_PAGES = 500
# A preamble (title, purpose...) shorter than this goes with the first section
# instead of costing a generation call of its own.
SHORT_PREAMBLE_CHARS = 500

_ATX_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s{0,3}(```|~~~)")
_DOCX_HEADING = re.compile(r"^heading\s*(\d)$", re.IGNORECASE)
_UNSAFE_KEY = re.compile(r"[^\w.-]+", re.UNICODE)

_ID_HEADERS = ("id", "key", "issue key", "issue id", "story id", "story key", "ticket")
_TITLE_HEADERS = ("title", "summary", "name", "story", "user story", "subject")


class RequirementImportError(ValueError):
    """A requirement file that cannot be read, with a user-friendly message."""


@dataclass
class Section:
    """
    One part of the requirement, sent to the AI on its own. `key` is short and
    unique within the file (a story id, or S1, S2...): merged results prefix
    the criterion ids two sections share with it.
    """

    key: str
    title: str
    text: str


@dataclass
class _Block:
    level: int  # 0 = text before the first heading
    heading: str
    body: str

    def render(self) -> str:
        return "\n\n".join(part for part in (self.heading, self.body.strip()) if part)


def read_requirement_file(uploaded_file, max_chars: int = MAX_REQUIREMENT_CHARS) -> list[Section]:
    """
    uploaded_file: an object with `.name` and `.getvalue()`, like Streamlit's
    UploadedFile. Returns the sections in document order, each at most
    `max_chars` long. Raises RequirementImportError for an unsupported or
    unreadable file, or one without any text.
    """
    name = getattr(uploaded_file, "name", "") or ""
    suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if suffix not in SUPPORTED_SUFFIXES:
        raise RequirementImportError(
            f"Unsupported file type '.{suffix}'. Upload a .docx, .pdf, .md, .txt or .csv file."
        )
    raw = uploaded_file.getvalue()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise RequirementImportError("The uploaded file exceeds the 10 MiB size limit.")

    if suffix == "csv":
        sections = _csv_sections(uploaded_file, max_chars)
    else:
        if suffix in ("md", "txt"):
            blocks = _markdown_blocks(_decode(raw))
        elif suffix == "docx":
            blocks = _docx_blocks(raw)
        else:
            blocks = _pdf_blocks(raw)
        sections = split_into_sections(blocks, max_chars)

    if not sections:
        hint = " (a scanned PDF has no text to read)" if suffix == "pdf" else ""
        raise RequirementImportError(f"No text was found in the uploaded file{hint}.")
    return sections


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise RequirementImportError(f"Could not read the file as UTF-8 text: {error}") from error


# ---------- Reading each format into heading blocks ----------

def _markdown_blocks(text: str) -> list[_Block]:
    """ATX headings (# Title) split the text; a '#' inside a code fence is not a heading."""
    blocks = [_Block(0, "", "")]
    lines: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
        heading = None if in_fence else _ATX_HEADING.match(line)
        if heading and heading.group(2):
            blocks[-1].body = "\n".join(lines)
            lines = []
            blocks.append(_Block(len(heading.group(1)), heading.group(2), ""))
        else:
            lines.append(line)
    blocks[-1].body = "\n".join(lines)
    return blocks


def _docx_blocks(raw: bytes) -> list[_Block]:
    try:
        import docx
        from docx.table import Table
    except ImportError as error:  # pragma: no cover - listed in requirements.txt
        raise RequirementImportError(
            "The 'python-docx' package is needed to read .docx files: pip install -r requirements.txt"
        ) from error
    try:
        document = docx.Document(io.BytesIO(raw))
        items = list(document.iter_inner_content())
    except Exception as error:
        raise RequirementImportError(f"Could not read the Word file: {error}") from error

    blocks = [_Block(0, "", "")]
    lines: list[str] = []
    for item in items:
        if isinstance(item, Table):
            lines.extend(_table_lines(item))
            continue
        text = item.text.strip()
        if not text:
            lines.append("")
            continue
        style = (item.style.name if item.style is not None else "") or ""
        level = _DOCX_HEADING.match(style.strip())
        if level and int(level.group(1)) > 0:
            blocks[-1].body = "\n".join(lines)
            lines = []
            blocks.append(_Block(int(level.group(1)), text, ""))
        elif style.lower().startswith("list"):
            lines.append(f"- {text}")
        else:
            lines.append(text)
    blocks[-1].body = "\n".join(lines)
    return blocks


def _table_lines(table) -> list[str]:
    """A table as one line per row, cells joined by " | " (merged cells once)."""
    lines = [""]
    for row in table.rows:
        cells = []
        for cell in row.cells:
            text = " ".join(cell.text.split())
            if not cells or cells[-1] != text:
                cells.append(text)
        if any(cells):
            lines.append(" | ".join(cells))
    lines.append("")
    return lines


def _pdf_blocks(raw: bytes) -> list[_Block]:
    """
    A PDF has no heading styles. Its outline (bookmarks), when it has one,
    gives the sections, each starting at its page; without one the text is
    split by size alone.
    """
    try:
        from pypdf import PdfReader
    except ImportError as error:  # pragma: no cover - listed in requirements.txt
        raise RequirementImportError(
            "The 'pypdf' package is needed to read .pdf files: pip install -r requirements.txt"
        ) from error
    try:
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted and not reader.decrypt(""):
            raise RequirementImportError("The PDF is password-protected.")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise RequirementImportError(
                f"The PDF has more than {MAX_PDF_PAGES} pages. Split it into smaller files."
            )
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
        starts = _pdf_outline_starts(reader)
    except RequirementImportError:
        raise
    except Exception as error:
        raise RequirementImportError(f"Could not read the PDF file: {error}") from error

    if not starts:
        return [_Block(0, "", "\n\n".join(page for page in pages if page))]
    blocks = [_Block(0, "", "\n\n".join(pages[:starts[0][0]]))]
    for index, (page, title) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else len(pages)
        blocks.append(_Block(1, title, "\n\n".join(pages[page:end])))
    return blocks


def _pdf_outline_starts(reader) -> list[tuple[int, str]]:
    """(first page, title) of each top-level bookmark; bookmarks on one page share it."""
    by_page: dict[int, list[str]] = {}
    for item in reader.outline or []:
        if isinstance(item, list):  # the children of the previous bookmark
            continue
        try:
            page = reader.get_destination_page_number(item)
        except Exception:
            continue
        title = " ".join(str(getattr(item, "title", "") or "").split())
        if page is not None and page >= 0 and title:
            by_page.setdefault(page, []).append(title)
    return [(page, " / ".join(titles)) for page, titles in sorted(by_page.items())]


def _csv_sections(uploaded_file, max_chars: int) -> list[Section]:
    """One user story per row; the row's cells become "Column: value" lines."""
    try:
        rows, row_numbers = parse_uploaded_rows(uploaded_file)
    except FileImportError as error:
        raise RequirementImportError(str(error)) from error

    headers = list(rows[0].keys())
    id_column = _find_column(headers, _ID_HEADERS)
    title_column = _find_column(headers, _TITLE_HEADERS)
    sections = []
    for row, row_number in zip(rows, row_numbers):
        lines = [
            f"{header}: {str(value).strip()}"
            for header, value in row.items()
            if header and value is not None and str(value).strip()
        ]
        if not lines:
            continue
        story_id = " ".join(str(row.get(id_column) or "").split()) if id_column else ""
        story_title = " ".join(str(row.get(title_column) or "").split()) if title_column else ""
        label = " ".join(part for part in (story_id, story_title) if part) or lines[0]
        title = f"Row {row_number}: {_shorten(label)}"
        sections.extend(_sized(story_id or "", title, "\n".join(lines), max_chars))
    return _with_unique_keys(sections)


def _find_column(headers: list[str], names: tuple[str, ...]) -> str:
    lowered = {header.strip().lower(): header for header in headers if header}
    for name in names:
        if name in lowered:
            return lowered[name]
    return ""


def _shorten(text: str, limit: int = 80) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# ---------- Splitting into sections ----------

def split_into_sections(blocks: list[_Block], max_chars: int = MAX_REQUIREMENT_CHARS) -> list[Section]:
    """
    One section per top-level heading, with its subsections. The top level is
    the highest heading level used more than once, so a document whose only
    H1 is its title splits at its H2s. Text before the first section heading
    goes with the first section when short, and is a section of its own when
    long. A section longer than `max_chars` is split at paragraphs.
    """
    headed = [block.level for block in blocks if block.level > 0]
    levels = sorted(set(headed))
    top = levels[0] if levels else 0
    for level in levels:
        top = level
        if headed.count(level) > 1:
            break

    preamble: list[str] = []
    groups: list[tuple[str, list[str]]] = []
    for block in blocks:
        rendered = block.render()
        if block.level == 0 or (block.level < top and not groups):
            if rendered:
                preamble.append(rendered)
        elif block.level <= top or not groups:
            groups.append((block.heading, [rendered]))
        else:
            groups[-1][1].append(rendered)

    preamble_text = "\n\n".join(preamble).strip()
    sections: list[Section] = []
    if not groups:
        if preamble_text:
            sections.extend(_sized("", "Whole document", preamble_text, max_chars))
        return _with_unique_keys(sections)

    first_heading, first_parts = groups[0]
    if preamble_text and len(preamble_text) < SHORT_PREAMBLE_CHARS:
        groups[0] = (first_heading, [preamble_text, *first_parts])
    elif preamble_text:
        sections.extend(_sized("", "Introduction", preamble_text, max_chars))
    for heading, parts in groups:
        text = "\n\n".join(part for part in parts if part).strip()
        if text:
            sections.extend(_sized("", _shorten(heading) or "Untitled section", text, max_chars))
    return _with_unique_keys(sections)


def _sized(key: str, title: str, text: str, max_chars: int) -> list[Section]:
    pieces = split_text(text, max_chars)
    if len(pieces) == 1:
        return [Section(key, title, pieces[0])]
    return [
        Section(f"{key}-{number}" if key else "", f"{title} (part {number} of {len(pieces)})", piece)
        for number, piece in enumerate(pieces, start=1)
    ]


def _with_unique_keys(sections: list[Section]) -> list[Section]:
    """S1, S2... for sections without a key; a repeated key gets a suffix."""
    used: set[str] = set()
    for number, section in enumerate(sections, start=1):
        base = _UNSAFE_KEY.sub("_", section.key).strip("_") or f"S{number}"
        key, suffix = base, 2
        while key in used:
            key, suffix = f"{base}_{suffix}", suffix + 1
        used.add(key)
        section.key = key
    return sections


def split_text(text: str, max_chars: int) -> list[str]:
    """
    Pieces of at most `max_chars`, cut at blank lines, then at line ends, and
    only for a single overlong line at a space (or anywhere, as a last resort).
    """
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []
    units: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if len(paragraph) <= max_chars:
            units.append(paragraph)
            continue
        for line in paragraph.splitlines():
            units.extend(_cut_line(line.strip(), max_chars))
    pieces: list[str] = []
    current = ""
    for unit in units:
        if not unit:
            continue
        candidate = f"{current}\n\n{unit}" if current else unit
        if len(candidate) <= max_chars:
            current = candidate
        else:
            pieces.append(current)
            current = unit
    if current:
        pieces.append(current)
    return pieces


def _cut_line(line: str, max_chars: int) -> list[str]:
    pieces = []
    while len(line) > max_chars:
        cut = line.rfind(" ", 0, max_chars + 1)
        if cut <= 0:
            cut = max_chars
        pieces.append(line[:cut].strip())
        line = line[cut:].strip()
    if line:
        pieces.append(line)
    return pieces
