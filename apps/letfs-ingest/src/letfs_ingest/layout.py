import re
from collections.abc import Sequence
from itertools import accumulate

from docling_core.types.doc.items.node import NodeItem


def section_name(number: int, count: int, heading: str) -> str:
    slug = re.sub(r"[^\w-]+", "-", heading).strip("-_").lower()[:60] or "section"
    return f"{number:0{len(str(count))}d}-{slug}"


def sections(items: Sequence[tuple[NodeItem, int]], minimum_tokens: int, split_tokens: int) -> list[tuple[int, int, str]]:
    from docling_core.types.doc.items.table.table import TableItem
    from docling_core.types.doc.items.text import SectionHeaderItem

    weights, headings = [], []
    table_depth = None
    for position, (item, depth) in enumerate(items):
        inside_table = table_depth is not None and depth > table_depth
        if not inside_table:
            table_depth = depth if isinstance(item, TableItem) else None
            if isinstance(item, SectionHeaderItem):
                headings.append((position, item.level, item.text))
        text = getattr(item, "text", "")
        if isinstance(item, TableItem):
            text += " ".join(cell.text for cell in item.data.table_cells)
        weights.append((len(text) + 3) // 4)
    totals = list(accumulate(weights, initial=0))

    def size(start: int, stop: int) -> int:
        return totals[stop] - totals[start]

    def groups(start: int, stop: int, required: int) -> list[tuple[int, int, str]]:
        candidates = [heading for heading in headings if start <= heading[0] < stop]
        for level in sorted({heading[1] for heading in candidates}):
            same_level = [(position, title) for position, depth, title in candidates if depth == level]
            if len(same_level) < required:
                continue
            merged = []
            for index, (position, title) in enumerate(same_level):
                end = same_level[index + 1][0] if index + 1 < len(same_level) else stop
                if merged and size(*merged[-1][:2]) < minimum_tokens:
                    merged[-1] = (merged[-1][0], end, merged[-1][2])
                else:
                    merged.append((position, end, title))
            if len(merged) > 1 and size(*merged[-1][:2]) < minimum_tokens:
                tail = merged.pop()
                merged[-1] = (merged[-1][0], tail[1], merged[-1][2])
            return merged
        return []

    mains = groups(0, len(items), 2)
    if totals[-1] <= split_tokens or len(mains) < 2:
        return [(0, len(items), "README.md")]
    children = [groups(start + 1, stop, 1) for start, stop, _ in mains]
    nested = sum(
        size(start, stop) > split_tokens
        and sum(size(a, b) >= minimum_tokens for a, b, _ in child) >= 2
        for (start, stop, _), child in zip(mains, children, strict=True)
    ) > len(mains) / 2
    result = [(0, mains[0][0], "README.md")]
    for number, ((start, stop, title), child) in enumerate(zip(mains, children, strict=True), 1):
        name = section_name(number, len(mains), title)
        if not nested:
            result.append((start, stop, f"{name}.md"))
            continue
        result.append((start, child[0][0] if child else stop, f"{name}/README.md"))
        result.extend(
            (a, b, f"{name}/{section_name(index, len(child), heading)}.md")
            for index, (a, b, heading) in enumerate(child, 1)
        )
    return result
