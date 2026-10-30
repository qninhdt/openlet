import csv
import re
from pathlib import Path

from docling_core.types.doc import (
    GroupItem,
    GroupLabel,
    ImageRef,
    ImageRefMode,
    PictureItem,
    SectionHeaderItem,
    Size,
    TableItem,
    TitleItem,
)
from openpyxl import load_workbook


def slug(name: str) -> str:
    value = re.sub(r"[^\w-]+", "-", name, flags=re.UNICODE).strip("-_").lower()
    return value[:60] or "untitled"


def markdown(document, output: Path, kind: str) -> None:
    # Saving a document slice re-encodes every image; attach relative refs once.
    (output / "images").mkdir(exist_ok=True)
    for number, picture in enumerate(document.pictures, 1):
        image = picture.get_image(document)
        if image is not None:
            relative = Path("images") / f"{number:03}.png"
            image.save(output / relative, format="PNG")
            picture.image = ImageRef(
                mimetype="image/png",
                dpi=picture.image.dpi if picture.image is not None else 72,
                size=Size(width=image.width, height=image.height),
                uri=relative,
            )
    items = list(document.iterate_items(with_groups=True, traverse_pictures=True))
    if kind == "pptx":
        starts = [
            (i, item)
            for i, (item, _) in enumerate(items)
            if isinstance(item, GroupItem)
            and item.parent is not None
            and item.parent.cref == document.body.self_ref
            and item.label in (GroupLabel.CHAPTER, GroupLabel.SLIDE)
        ]
        sections = []
        for number, (start, _) in enumerate(starts):
            end = starts[number + 1][0] if number + 1 < len(starts) else len(items)
            title = next(
                (
                    item.text
                    for item, _ in items[start:end]
                    if isinstance(item, TitleItem)
                ),
                f"slide-{number + 1}",
            )
            sections.append((start, end, f"{number + 1:03}-{slug(title)}.md"))
    else:
        headings = [
            (i, item)
            for i, (item, _) in enumerate(items)
            if isinstance(item, SectionHeaderItem)
        ]
        level = min((item.level for _, item in headings), default=0)
        starts = [(i, item) for i, item in headings if item.level == level]
        sections = [
            (
                0 if n == 0 else start,
                starts[n + 1][0] if n + 1 < len(starts) else len(items),
                f"{n + 1:03}-{slug(item.text)}.md",
            )
            for n, (start, item) in enumerate(starts)
        ]
    if not sections:
        sections = [(0, len(items), "content.md")]
    for start, end, name in sections:
        content = document.export_to_markdown(
            from_element=start,
            to_element=end,
            image_mode=ImageRefMode.REFERENCED,
            traverse_pictures=True,
        )
        (output / name).write_text(content, encoding="utf-8")


def spreadsheets(document, source: Path, output: Path) -> None:
    workbook = load_workbook(source, data_only=False, read_only=True)
    try:
        groups = [g for g in document.groups if g.label == GroupLabel.SHEET]
        for number, sheet in enumerate(workbook.worksheets, 1):
            folder = output / f"{number:03}-{slug(sheet.title)}"
            folder.mkdir()
            group = next((g for g in groups if g.name == sheet.title), None)
            items = list(document.iterate_items(root=group)) if group else []
            covered = set()
            table_number = 0
            for item, _ in items:
                if not isinstance(item, TableItem):
                    continue
                table_number += 1
                with (folder / f"{table_number:03}.csv").open("w", newline="") as file:
                    csv.writer(file).writerows(
                        [cell.text for cell in row] for row in item.data.grid
                    )
                if len(item.prov) != 1:
                    raise ValueError("spreadsheet table has no unique position")
                box = item.prov[0].bbox
                for row in item.data.table_cells:
                    if row.text:
                        covered.add(
                            (
                                int(box.t) + row.start_row_offset_idx + 1,
                                int(box.l) + row.start_col_offset_idx + 1,
                            )
                        )
            # Docling omits uncached formulas; retain uncovered cells by position.
            for row_index, row in enumerate(sheet.iter_rows(), 1):
                uncovered = [
                    (col, cell.value)
                    for col, cell in enumerate(row, 1)
                    if cell.value is not None and (row_index, col) not in covered
                ]
                if uncovered:
                    first, last = uncovered[0][0], uncovered[-1][0]
                    values = dict(uncovered)
                    name = f"cells-r{row_index}-c{first}.csv"
                    with (folder / name).open("w", newline="") as file:
                        csv.writer(file).writerow(
                            values.get(col, "") for col in range(first, last + 1)
                        )
            picture_number = 0
            for item, _ in items:
                if not isinstance(item, PictureItem):
                    continue
                image = item.get_image(document)
                if image is not None:
                    picture_number += 1
                    (folder / "images").mkdir(exist_ok=True)
                    image.save(folder / "images" / f"{picture_number:03}.png")
    finally:
        workbook.close()
