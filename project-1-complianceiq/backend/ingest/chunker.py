"""Stage 4: turn the structure tree into parent and child chunks (ADR-006).

- A PARENT is one numbered paragraph with all its clauses: what the LLM reads to answer.
  Very long paragraphs are split into several parents, only at clause boundaries.
- A CHILD is a small piece of one parent (a clause, or a few short clauses packed together):
  what we embed and search. Small children = precise matches; their parent = enough context.
- Every chunk gets a CONTEXT HEADER, e.g.
    "Reserve Bank of India (Commercial Banks – KYC) Directions, 2025 | RBI/DOR/2025-26/169 | 28 Nov 2025 |
     Chapter VI > D. Identification of Beneficial Owner > Para 38(1)"
  so a chunk that only says "the above limit" still says which rule, of which document, it belongs to.
- Tables become their own chunks, one "Header: value" line per row.
- Footnotes referenced inside a paragraph are attached to its parent as amendment notes.
"""

import hashlib
import re
from dataclasses import dataclass, field

from .models import RawDocument, Table
from .structure import Node

MAX_CHILD_WORDS = 220     # ~300 tokens: one or two clauses
MIN_CHILD_WORDS = 40      # smaller pieces get packed with their neighbours
MAX_PARENT_WORDS = 900    # ~1,200 tokens: one paragraph; longer ones split at clause boundaries
STRUCTURAL = ("root", "chapter", "section")


@dataclass
class Chunk:
    level: str                    # "parent" | "child"
    index: int                    # position within its level, per document
    section_path: str             # "Chapter VI > ... > Para 38(1)"
    content: str
    context_header: str = ""
    page_start: int | None = None
    page_end: int | None = None
    parent_index: int | None = None   # children only: index of their parent
    metadata: dict = field(default_factory=dict)

    @property
    def token_count(self) -> int:
        return int(len(self.content.split()) * 1.33)  # rough: English averages ~1.3 tokens per word

    @property
    def content_hash(self) -> str:
        """Fingerprint of the normalized text: identical rules in different documents share it."""
        norm = re.sub(r"\s+", " ", self.content.lower()).strip()
        return hashlib.sha256(norm.encode()).hexdigest()

    @property
    def embedding_text(self) -> str:
        return f"{self.context_header}\n{self.content}"


def _words(text: str) -> int:
    return len(text.split())


def _own_text(node: Node) -> str:
    """The node's marker + heading + its own lines (not its children)."""
    if node.kind == "para":
        prefix = f"{node.label}."
    elif node.kind in STRUCTURAL:
        prefix = ""
    else:
        prefix = f"({node.label})"
    body = " ".join(x for x in (node.title, node.text) if x)
    return f"{prefix} {body}".strip()


def _render(node: Node, depth: int = 0) -> str:
    """The node and all its descendants as indented text."""
    out = ["  " * depth + _own_text(node)] if _own_text(node) else []
    for child in node.children:
        out.append(_render(child, depth + (0 if node.kind in STRUCTURAL else 1)))
    return "\n".join(x for x in out if x.strip())


def _subtree(node: Node) -> list[Node]:
    """The node plus its descendants, except for chapters/sections/root (their children are separate parents)."""
    return [node] if node.kind in STRUCTURAL else list(node.walk())


def _pages(nodes: list[Node]) -> tuple[int | None, int | None]:
    pages = [p for n in nodes for d in _subtree(n) for p in d.pages]
    return (min(pages), max(pages)) if pages else (None, None)


def _common_citation(nodes: list[Node]) -> str:
    """Citation of the lowest common ancestor: (1)+(2) of Para 38 -> 'Para 38'."""
    if len(nodes) == 1:
        return nodes[0].citation()

    def chain(n: Node) -> list[Node]:
        out = []
        while n is not None:
            out.append(n)
            n = n.parent
        return out[::-1]

    chains = [chain(n) for n in nodes]
    common = None
    for level in zip(*chains, strict=False):
        if all(x is level[0] for x in level):
            common = level[0]
        else:
            break
    return common.citation() if common is not None else nodes[0].citation()


def _units(node: Node) -> list[tuple[list[Node], str]]:
    """Split a subtree into child-sized units: whole subtree if small enough, else recurse."""
    full = _render(node)
    if _words(full) <= MAX_CHILD_WORDS or not node.children:
        if _words(full) <= MAX_CHILD_WORDS:
            return [([node], full)]
        return [([node], w) for w in _windows(full)]          # a long leaf: overlapping windows
    units: list[tuple[list[Node], str]] = []
    own = _own_text(node)
    if own:
        units += [([node], w) for w in _windows(own)]
    for child in node.children:
        units += _units(child)
    return units


def _windows(text: str, size: int = MAX_CHILD_WORDS, overlap: int = 30) -> list[str]:
    words = text.split()
    if len(words) <= size:
        return [text]
    return [" ".join(words[i:i + size]) for i in range(0, len(words) - overlap, size - overlap)]


def _pack(units: list[tuple[list[Node], str]]) -> list[tuple[list[Node], str]]:
    """Greedy packing: join neighbouring small units up to MAX_CHILD_WORDS."""
    packed: list[tuple[list[Node], str]] = []
    nodes: list[Node] = []
    texts: list[str] = []
    for unit_nodes, text in units:
        if texts and _words(" ".join(texts)) + _words(text) > MAX_CHILD_WORDS \
                and _words(" ".join(texts)) >= MIN_CHILD_WORDS:
            packed.append((nodes, "\n".join(texts)))
            nodes, texts = [], []
        nodes = nodes + [n for n in unit_nodes if n not in nodes]
        texts.append(text)
    if texts:
        packed.append((nodes, "\n".join(texts)))
    return packed


def _holders(root: Node) -> list[list[Node]]:
    """Groups of nodes that each become one or more parents: every paragraph, plus loose text
    that sits directly under the document / a chapter / a section (letters, preambles, annexes)."""
    groups: list[list[Node]] = []

    def visit(node: Node) -> None:
        if node.kind == "para":
            groups.append([node])
            return
        if node.kind in STRUCTURAL:
            loose = [c for c in node.children if c.kind not in STRUCTURAL and c.kind != "para"]
            if node.lines or loose:
                groups.append([node] + loose)   # heading text + any numbered items not inside a para
            for c in node.children:
                if c.kind in STRUCTURAL or c.kind == "para":
                    visit(c)

    visit(root)
    return groups


def _blocks(node: Node, depth: int = 0) -> list[tuple[list[Node], str]]:
    """A node as parent-sized text blocks: whole if it fits, else its own text + each child (recursively)."""
    text = _render(node, depth)
    if _words(text) <= MAX_PARENT_WORDS:
        return [([node], text)]
    if not node.children:
        return [([node], w) for w in _windows(text, MAX_PARENT_WORDS, 50)]
    own = _own_text(node)
    out = [([node], "  " * depth + own)] if own else []
    for child in node.children:
        out += _blocks(child, depth + 1)
    return out


def _split_parent(group: list[Node]) -> list[list[tuple[list[Node], str]]]:
    """A holder group -> one or more parents, each a list of (nodes, text) blocks, split at clause boundaries."""
    blocks: list[tuple[list[Node], str]] = []
    for node in group:
        if node.kind in STRUCTURAL:
            own = _own_text(node) if node.kind != "root" else node.text
            blocks += [([node], w) for w in _windows(own, MAX_PARENT_WORDS, 50)] if own else []
        else:
            blocks += _blocks(node)
    parents, current, size = [], [], 0
    for b in blocks:
        if current and size + _words(b[1]) > MAX_PARENT_WORDS:
            parents.append(current)
            current, size = [], 0
        current.append(b)
        size += _words(b[1])
    if current:
        parents.append(current)
    return parents


def _table_text(table: Table) -> list[str]:
    """Each row as 'Header: value; Header: value' (falls back to ' | ' when there is no clear header)."""
    rows = [r for r in table.rows if any(c for c in r)]
    if not rows:
        return []
    header = rows[0]
    if len(rows) > 1 and all(header):
        return [" | ".join(header)] + [
            "; ".join(f"{h}: {v}" for h, v in zip(header, r, strict=False) if v) for r in rows[1:]
        ]
    return [" | ".join(c for c in r if c) for r in rows]


def build_chunks(doc: RawDocument, tree: Node, header_prefix: str) -> tuple[list[Chunk], list[Chunk]]:
    """Return (parents, children). `header_prefix` = 'title | circular no. | date' for context headers."""
    footnotes = {f.marker: f.text for f in doc.footnotes}
    parents: list[Chunk] = []
    children: list[Chunk] = []

    def add_parent(nodes: list[Node], text: str, citation: str, extra: dict) -> int:
        p0, p1 = _pages(nodes)
        parents.append(Chunk("parent", len(parents), citation, text, f"{header_prefix} | {citation}",
                             p0, p1, metadata=extra))
        return len(parents) - 1

    def add_child(nodes: list[Node], text: str, parent_idx: int) -> None:
        citation = _common_citation(nodes)
        p0, p1 = _pages(nodes)
        children.append(Chunk("child", len(children), citation, text, f"{header_prefix} | {citation}",
                              p0, p1, parent_index=parent_idx))

    # --- paragraphs and loose text ---
    for group in _holders(tree):
        for blocks in _split_parent(group):
            nodes = [n for ns, _ in blocks for n in ns]
            text = "\n".join(t for _, t in blocks).strip()
            if not text:
                continue
            refs = [r for n in nodes for d in _subtree(n) for r in d.footnote_refs]
            notes = [f"[{r}] {footnotes[r]}" for r in dict.fromkeys(refs) if r in footnotes]
            if notes:
                text += "\nAmendment notes: " + " ".join(notes)
            citation = _common_citation(nodes)
            pidx = add_parent(nodes, text, citation, {"amendments": notes} if notes else {})
            units: list[tuple[list[Node], str]] = []
            for ns, t in blocks:
                node = ns[0]
                if _words(t) <= MAX_CHILD_WORDS:
                    units.append(([node], t.strip()))
                elif node.kind in STRUCTURAL or t.strip() == _own_text(node) or not node.children:
                    units += [([node], w) for w in _windows(t.strip())]
                else:
                    units += _units(node)
            for unit_nodes, unit_text in _pack(units):
                add_child(unit_nodes, unit_text, pidx)

    # --- tables ---
    for t_i, table in enumerate(doc.tables, start=1):
        lines = _table_text(table)
        if not lines:
            continue
        citation = f"Table {t_i} (page {table.page})"
        text = "\n".join(lines)
        parents.append(Chunk("parent", len(parents), citation, text, f"{header_prefix} | {citation}",
                             table.page, table.page, metadata={"table": True}))
        pidx = len(parents) - 1
        head = lines[0]
        for w in _windows("\n".join(lines[1:]) or head):
            children.append(Chunk("child", len(children), citation, f"{head}\n{w}" if w != head else w,
                                  f"{header_prefix} | {citation}", table.page, table.page, parent_index=pidx))

    return parents, children
