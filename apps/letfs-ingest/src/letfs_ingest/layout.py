from dataclasses import dataclass
from pathlib import Path

from docling_core.types.doc import SectionHeaderItem, TableItem

from letfs_ingest.text_split import estimate_tokens


def ordinal(index: int, count: int) -> str:
    return str(index).zfill(len(str(count)))


@dataclass(frozen=True)
class Section:
    start: int
    end: int
    path: Path


def document_layout(items, minimum: int, split: int) -> list[Section]:
    counts = [0]
    for item, _ in items:
        text = getattr(item, "text", "")
        if hasattr(item, "data") and hasattr(item.data, "grid"):
            text += " ".join(cell.text for row in item.data.grid for cell in row)
        counts.append(counts[-1] + estimate_tokens(text))

    def size(start, end):
        return counts[end] - counts[start]

    headings = []
    table_level = None
    for i, (item, depth) in enumerate(items):
        if table_level is not None:
            if depth > table_level:
                continue
            table_level = None
        if isinstance(item, TableItem):
            table_level = depth
        elif isinstance(item, SectionHeaderItem):
            headings.append((i, item.level))

    def boundaries(start, end, minimum_count=2):
        candidates = [(i, level) for i, level in headings if start <= i < end]
        for level in sorted({level for _, level in candidates}):
            starts = [i for i, depth in candidates if depth == level]
            if len(starts) >= minimum_count:
                return list(zip(starts, starts[1:] + [end], strict=True))
        return []

    def merge(ranges):
        merged = []
        for start, end in ranges:
            if merged and size(*merged[-1]) < minimum:
                merged[-1] = (merged[-1][0], end)
            else:
                merged.append((start, end))
        if len(merged) > 1 and size(*merged[-1]) < minimum:
            merged[-2:] = [(merged[-2][0], merged[-1][1])]
        return merged

    root = Path("README.md")
    mains = merge(boundaries(0, len(items)))
    if counts[-1] <= split or len(mains) < 2:
        return [Section(0, len(items), root)]
    children = [merge(boundaries(start + 1, end, 1)) for start, end in mains]
    substantial = sum(
        size(start, end) > split and sum(size(a, b) >= minimum for a, b in subs) >= 2
        for (start, end), subs in zip(mains, children, strict=True)
    )
    two_levels = substantial > len(mains) / 2
    sections = [Section(0, mains[0][0], root)]
    for index, ((start, end), subs) in enumerate(zip(mains, children, strict=True), 1):
        name = f"{ordinal(index, len(mains))}-untitled"
        if not two_levels:
            sections.append(Section(start, end, Path(name + ".md")))
            continue
        folder = Path(name)
        if not subs:
            subs = [(start + 1, end)] if start + 1 < end else []
        intro_end = subs[0][0] if subs else end
        sections.append(Section(start, intro_end, folder / root))
        sections.extend(
            Section(a, b, folder / f"{ordinal(n, len(subs))}-untitled.md")
            for n, (a, b) in enumerate(subs, 1)
        )
    return sections
