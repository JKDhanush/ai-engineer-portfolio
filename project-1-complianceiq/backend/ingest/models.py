"""Plain data containers passed between pipeline stages.

Each stage takes one of these and returns the next, so every stage can be tested on its own:
    pdf_reader:  PDF file      -> RawDocument (clean body lines + footnotes + tables)
    metadata:    RawDocument   -> DocMetadata (circular numbers, date, title)
    structure:   RawDocument   -> section tree           (next step)
    chunker:     section tree  -> parent/child chunks    (next step)
"""

from dataclasses import dataclass, field
from datetime import date


@dataclass
class Line:
    """One visual line of body text on a page."""

    page: int                    # 1-based page number
    text: str                    # text with footnote markers removed
    size: float                  # largest font size on the line (pt)
    bold: bool                   # True if every text span on the line is bold
    x0: float = 0.0              # left edge (pt from page left), useful for indentation
    y0: float = 0.0              # top edge (pt from page top)
    footnote_refs: list[str] = field(default_factory=list)  # e.g. ["112"] for "112Updation"


@dataclass
class Footnote:
    """A footnote at the bottom of a page. RBI uses them to record amendment history."""

    page: int
    marker: str                  # "1", "112", ...
    text: str                    # "Inserted with effect from ... vide ..."


@dataclass
class Table:
    """A table found on a page, as a list of rows (each row a list of cell strings)."""

    page: int
    rows: list[list[str]]


@dataclass
class RawDocument:
    """Everything the reader extracted from one PDF, with page noise already removed."""

    path: str
    page_count: int
    lines: list[Line]
    footnotes: list[Footnote]
    tables: list[Table]
    dropped: dict[str, int] = field(default_factory=dict)  # what was removed, for debugging


@dataclass
class DocMetadata:
    """Facts about a document read from its page-1 header block."""

    circular_nos: list[str]      # e.g. ["RBI/DOR/2025-26/169", "DOR.AML.REC.No.88/14.01.002/2025-26"]
    issued_on: date | None       # e.g. date(2025, 11, 28)
    title: str | None            # e.g. "Reserve Bank of India (Commercial Banks – Know Your Customer) Directions, 2025"
