"""Stage 3: turn the reader's flat list of lines into the document's own outline (ADR-006).

    Chapter VI – Customer Due Diligence (CDD) Procedure            kind="chapter"
     └─ E. On-going Due Diligence                                    kind="section"
         └─ 38. Updation / Periodic Updation of KYC                  kind="para"
             ├─ (1) Banks shall adopt a risk-based approach ...      kind="paren_num"
             │   ├─ (i) Individuals ...                              kind="paren_roman"
             │   └─ (ii) Legal entities ...                          kind="paren_roman"
             └─ (2) ...

Every node knows its citation path, e.g. "Chapter VI > E. On-going Due Diligence > Para 38(1)(ii)".

How nesting below a paragraph is decided:
RBI documents don't use one fixed order of numbering styles: the new directions go 38. → (1) → (i) → (a),
the 2016 Master Direction goes 3. → (a) → i. → a. So the order isn't hard-coded. Inside a paragraph, a
numbering style we haven't seen yet nests one level deeper; a style we're already inside of means
"next sibling at that level" (pop back up to it).
"""

import re
from dataclasses import dataclass, field

from .models import Line, RawDocument

# ---------------------------------------------------------------- headings (must be bold)
CHAPTER = re.compile(r"^chapter\s+([IVXL]+)\b\.?\s*(?:[–-]\s*)?(.*)$", re.IGNORECASE)
PART = re.compile(r"^part\s+([IVX]+)\s*[-–]\s*(.+)$", re.IGNORECASE)
SECTION = re.compile(r"^([A-H](?:\.\d{1,2})?)\.?\s+(.+)$")              # "A. Short Title", "F.1 Enhanced ..."
ANNEX = re.compile(r"^annex(?:ure)?\s*[–-]?\s*([IVX]+|\d+)\b\.?\s*(.*)$", re.IGNORECASE)
INTRO = re.compile(r"^(introduction|preamble)\.?$", re.IGNORECASE)

LONE_MARKER = re.compile(r"^(?:[•●▪◦\-–]|\(?(?:\d{1,3}[A-Z]?|[a-z]{1,5})[.)])$")  # "v.", "4." or "•" alone
INDENT_TOLERANCE = 12.0   # pt: a paragraph number must start at (about) the left margin


@dataclass
class Marker:
    """A numbering marker found at the start of a line, e.g. '(ii) The bank shall ...'."""

    style: str    # "para" | "paren_num" | "num_paren" | "paren_roman" | "paren_alpha" | "dot_roman" | "dot_alpha"
    #               (the tree builder also uses "dot_num" for an indented "1." list inside a paragraph)
    label: str    # "38", "1", "ii", "a"
    rest: str     # the line's text after the marker


# ---------------------------------------------------------------- numbering markers
PARA = re.compile(r"^(\d{1,3}[A-Z]?)\.(?:\s+|$)(.*)$")   # "38. Updation ..."   "45A. Money ..."   "61." alone
PAREN_NUM = re.compile(r"^\((\d{1,2})\)\s*(.*)$")        # "(1) V-CIP Infrastructure"
NUM_PAREN = re.compile(r"^(\d{1,2})\)\s+(.*)$")          # "1) ..."
PAREN_LETTERS = re.compile(r"^\(([a-z]{1,5})\)\s*(.*)$")  # "(a) ...", "(ii) ...", "(i) ..." <- ambiguous!
DOT_LETTERS = re.compile(r"^([a-z]{1,5})\.\s+(.*)$")      # "a. ...", "xv. ...", "i. ..."    <- ambiguous!
ROMAN = re.compile(r"^[ivx]+$")                           # roman numerals RBI actually uses: i ... xxx


def classify_marker(text: str, last_alpha: str | None = None) -> Marker | None:
    """Recognise the numbering marker at the start of `text`.

    `last_alpha` is the label of the most recent *alphabetic* item in the same list (e.g. "h"), or None.

    Rules (tests/test_structure.py checks each one):
      1. "38. text"  -> Marker("para", "38", "text")      (PARA; also "45A." -> label "45A")
      2. "(1) text"  -> Marker("paren_num", "1", "text")  (PAREN_NUM)
      3. "1) text"   -> Marker("num_paren", "1", "text")  (NUM_PAREN)
      4. "(x) text" with letters inside (PAREN_LETTERS):
           - letters form a roman numeral (ROMAN) -> "paren_roman", else -> "paren_alpha"
           - BUT the single letters "i", "v", "x" are ambiguous: (i) comes after (h) in a lettered list.
             They are ALPHA if last_alpha is the letter just before them ("h"->"i", "u"->"v", "w"->"x"),
             otherwise ROMAN.
      5. "xv. text" / "a. text" (DOT_LETTERS): same logic as rule 4, styles "dot_roman" / "dot_alpha".
      6. Anything else -> None.
    Check the regexes in the order above: the first match wins.

    """
    if m := PARA.match(text):
        return Marker("para", m.group(1), m.group(2).strip())
    if m := PAREN_NUM.match(text):
        return Marker("paren_num", m.group(1), m.group(2).strip())
    if m := NUM_PAREN.match(text):
        return Marker("num_paren", m.group(1), m.group(2).strip())
    for regex, prefix in ((PAREN_LETTERS, "paren"), (DOT_LETTERS, "dot")):
        if m := regex.match(text):
            letters = m.group(1)
            is_roman = bool(ROMAN.match(letters))
            # "(i)" right after "(h)" is the letter i, not roman one (same for v after u, x after w)
            if letters in ("i", "v", "x") and last_alpha == chr(ord(letters) - 1):
                is_roman = False
            return Marker(f"{prefix}_{'roman' if is_roman else 'alpha'}", letters, m.group(2).strip())
    return None


# ---------------------------------------------------------------- the tree
@dataclass
class Node:
    kind: str                     # "root" | "chapter" | "section" | "para" | a Marker.style
    label: str = ""               # "VI", "E", "38", "1", "ii"
    title: str = ""               # heading text, if the node has one
    lines: list[str] = field(default_factory=list)   # body text lines that belong directly to this node
    pages: list[int] = field(default_factory=list)
    footnote_refs: list[str] = field(default_factory=list)
    children: list["Node"] = field(default_factory=list)
    parent: "Node | None" = field(default=None, repr=False)

    def add(self, child: "Node") -> "Node":
        child.parent = self
        self.children.append(child)
        return child

    @property
    def text(self) -> str:
        """This node's own text, with wrapped lines joined (a trailing hyphen joins without a space)."""
        out = ""
        for ln in self.lines:
            out = out + ln if out.endswith("-") else f"{out} {ln}" if out else ln
        return out.strip()

    def citation(self) -> str:
        """Human citation path, e.g. 'Chapter VI > E. On-going Due Diligence > Para 38(1)(ii)'."""
        parts, para = [], ""
        node: Node | None = self
        chain = []
        while node is not None and node.kind != "root":
            chain.append(node)
            node = node.parent
        for n in reversed(chain):
            if n.kind == "chapter":
                parts.append(f"Chapter {n.label}" if n.label else n.title)
            elif n.kind == "section":
                parts.append(f"{n.label}. {n.title}".strip(". ") if n.label else n.title)
            elif n.kind == "para":
                para = f"Para {n.label}"
            else:
                para += f"({n.label})"
        if para:
            parts.append(para)
        return " > ".join(parts) or "Preamble"

    def walk(self):
        """Depth-first iteration over this node and all its descendants."""
        yield self
        for c in self.children:
            yield from c.walk()


def _heading(line: Line) -> tuple[str, str, str] | None:
    """(kind, label, title) if this bold line is a chapter/section-level heading."""
    if not line.bold:
        return None
    t = line.text
    if m := CHAPTER.match(t):
        return "chapter", m.group(1).upper(), m.group(2).strip()
    if m := ANNEX.match(t):
        return "chapter", "", f"Annex {m.group(1)} {m.group(2)}".strip()
    if INTRO.match(t):
        return "chapter", "", t.strip().title()
    if m := PART.match(t):
        return "section", f"Part {m.group(1)}", m.group(2).strip()
    if m := SECTION.match(t):
        return "section", m.group(1), m.group(2).strip()
    return None


def build_tree(doc: RawDocument) -> Node:
    """Build the outline tree from the document's lines."""
    root = Node(kind="root", title="Preamble")
    current = root
    heading_open: Node | None = None   # a heading whose title may continue on the next bold line
    last_alpha: str | None = None
    last_para: tuple[int, str] | None = None   # (number, suffix) of the last paragraph, reset per chapter
    margin = _left_margin(doc.lines)

    for line in _merge_lone_markers(doc.lines):
        text = line.text

        # --- chapter / section headings ---
        if (h := _heading(line)) is not None:
            kind, label, title = h
            if kind == "chapter":
                current = root.add(Node(kind="chapter", label=label, title=title, pages=[line.page]))
                last_para = None                 # numbering may restart in a new chapter/annex
            else:
                chapter = _ancestor(current, "chapter") or root
                current = chapter.add(Node(kind="section", label=label, title=title, pages=[line.page]))
            heading_open, last_alpha = current, None
            continue

        # --- a heading's title can continue on the next bold line, but only if it is clearly unfinished:
        #     "CHAPTER I" | "PRELIMINARY"   or   "Chapter IX – ... International Agreements -" | "Communications ..."
        marker = classify_marker(text, last_alpha)
        if (heading_open is not None and line.bold and marker is None
                and (not heading_open.title or heading_open.title.endswith(("-", "–", ",")))):
            heading_open.title = f"{heading_open.title} {text}".strip()
            continue
        heading_open = None

        # --- sanity checks on paragraph numbers ---
        if marker is not None and marker.style == "para":
            key = _para_key(marker.label)
            if line.x0 > margin + INDENT_TOLERANCE:
                marker = Marker("dot_num", marker.label, marker.rest)   # indented "1." = a list inside a para
            elif last_para is not None and key <= last_para:
                marker = None   # out of sequence, e.g. a wrapped reference: "...paragraphs 26 and" / "27."
            else:
                last_para = key

        # --- numbered lines open new nodes ---
        if marker is not None:
            if marker.style == "para":
                container = _ancestor(current, "section") or _ancestor(current, "chapter") or root
                node = container.add(Node(kind="para", label=marker.label))
                last_alpha = None
            else:
                parent = _nesting_parent(current, marker.style)
                node = parent.add(Node(kind=marker.style, label=marker.label))
                if marker.style.endswith("alpha"):
                    last_alpha = marker.label
            if line.bold:                       # "38. Updation / Periodic Updation of KYC" is a heading
                node.title = marker.rest
            elif marker.rest:
                node.lines.append(marker.rest)
            node.pages.append(line.page)
            node.footnote_refs += line.footnote_refs
            current = node
            continue

        # --- plain text: continuation of the current node ---
        current.lines.append(f"• {text[1:].strip()}" if text[:1] in "•●▪◦" else text)
        if line.page not in current.pages:
            current.pages.append(line.page)
        current.footnote_refs += line.footnote_refs

    return root


def _merge_lone_markers(lines: list[Line]):
    """Glue a marker that sits alone on its line ("4.", "v.", "•") to the text on the next line.

    PDFs often put the number in its own text box: "4." | "These directions shall also apply ...".
    If the next line starts with its own marker ("61." | "(a) A Unique Customer ..."), keep both as they are.
    """
    i = 0
    while i < len(lines):
        ln = lines[i]
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        if LONE_MARKER.match(ln.text) and nxt is not None and classify_marker(nxt.text) is None:
            yield Line(ln.page, f"{ln.text} {nxt.text}", nxt.size, ln.bold or nxt.bold, ln.x0, ln.y0,
                       ln.footnote_refs + nxt.footnote_refs)
            i += 2
        else:
            yield ln
            i += 1


def _left_margin(lines: list[Line]) -> float:
    """The most common left edge of body lines = the page's left margin."""
    counts: dict[int, int] = {}
    for ln in lines:
        counts[round(ln.x0)] = counts.get(round(ln.x0), 0) + 1
    return float(max(counts, key=counts.get)) if counts else 0.0


def _para_key(label: str) -> tuple[int, str]:
    """'45A' -> (45, 'A'), so 45 < 45A < 46."""
    m = re.match(r"(\d+)([A-Z]?)", label)
    return (int(m.group(1)), m.group(2)) if m else (0, "")


def _ancestor(node: Node, kind: str) -> Node | None:
    while node is not None and node.kind != kind:
        node = node.parent
    return node


def _nesting_parent(current: Node, style: str) -> Node:
    """Where does a new item of `style` go? See the module docstring."""
    # Walk up from the current node, staying inside the paragraph.
    node = current
    while node.kind not in ("para", "section", "chapter", "root"):
        if node.kind == style:
            return node.parent          # same style already open: new item is its sibling
        node = node.parent
    return current                      # new style inside this paragraph: nest one level deeper
