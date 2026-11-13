import csv
from collections import Counter
from pathlib import Path

from docling_core.transforms.serializer.base import (
    BaseDocSerializer,
    SerializationResult,
)
from docling_core.transforms.serializer.common import create_ser_result
from docling_core.transforms.serializer.markdown import (
    MarkdownDocSerializer,
    MarkdownParams,
    MarkdownTableSerializer,
)
from docling_core.types.doc.base import ImageRefMode
from docling_core.types.doc.common.reference import ImageRef
from docling_core.types.doc.document import DoclingDocument
from docling_core.types.doc.items.picture.picture import PictureItem
from docling_core.types.doc.items.table.table import TableItem
from docling_core.types.doc.items.table.table_data import RichTableCell
from docling_core.types.doc.labels import GroupLabel

from .layout import sections


class TableLinks(MarkdownTableSerializer):
    def __init__(self, filenames: dict[str, str]) -> None:
        self.filenames = filenames

    def serialize(self, *, item: TableItem, doc_serializer: BaseDocSerializer, doc: DoclingDocument, **kwargs: object) -> SerializationResult:
        visited = kwargs.get("visited")
        if isinstance(visited, set):
            for cell in item.data.table_cells:
                if isinstance(cell, RichTableCell):
                    visited.update(part.self_ref for part, _ in doc.iterate_items(
                        root=cell.ref.resolve(doc), with_groups=True, traverse_pictures=True,
                    ))
        parts = [doc_serializer.serialize_captions(item=item, **kwargs).text]
        if item.self_ref not in doc_serializer.get_excluded_refs(**kwargs):
            parts.append(f"[Table]({self.filenames[item.self_ref]})")
        parts.append(doc_serializer.serialize_footnotes(item=item, **kwargs).text)
        return create_ser_result(text="\n\n".join(part for part in parts if part), span_source=item)


def write_table(document: DoclingDocument, table: TableItem, target: Path) -> None:
    serializer = MarkdownDocSerializer(doc=document)
    with target.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        for row in table.data.grid:
            writer.writerow([
                serializer.serialize(item=cell.ref.resolve(document), _nested_in_table=True).text
                if isinstance(cell, RichTableCell) else cell.text
                for cell in row
            ])


def spreadsheets(document: DoclingDocument, source: Path, output: Path) -> None:
    from openpyxl import load_workbook
    from openpyxl.utils.cell import get_column_letter

    workbook = load_workbook(source, data_only=False, read_only=True)
    try:
        root = [f"# {source.stem}"]
        sheets = {group.name: group for group in document.groups if group.label == GroupLabel.SHEET}
        for number, sheet in enumerate(workbook.worksheets, 1):
            folder = output / f"sheet-{number}"
            folder.mkdir()
            root.append(f"- [{sheet.title}]({folder.name}/README.md)")
            content, covered = [f"# {sheet.title}"], set()
            group = sheets.get(sheet.title)
            items = list(document.iterate_items(root=group)) if group else []
            tables = [item for item, _ in items if isinstance(item, TableItem) and item.data.num_rows * item.data.num_cols > 1]
            for index, table in enumerate(tables, 1):
                box = table.prov[0].bbox
                first_row, first_col = int(box.t) + 1, int(box.l) + 1
                name = f"table-{index}.csv"
                write_table(document, table, folder / name)
                last_col = first_col + table.data.num_cols - 1
                last_row = first_row + table.data.num_rows - 1
                content.append(f"- [{get_column_letter(first_col)}{first_row}:{get_column_letter(last_col)}{last_row}]({name})")
                covered.update(
                    (first_row + cell.start_row_offset_idx, first_col + cell.start_col_offset_idx)
                    for cell in table.data.table_cells if cell.text
                )
            for row in sheet:
                for cell in row:
                    if cell.value is not None and (cell.row, cell.column) not in covered:
                        content.append(f"{cell.coordinate}: {cell.value}")
            pictures = [item for item, _ in items if isinstance(item, PictureItem)]
            for index, item in enumerate(pictures, 1):
                image = item.get_image(document)
                if image is not None:
                    name = f"image-{index}.png"
                    image.save(folder / name, format="PNG")
                    content.append(f"![Image]({name})")
            (folder / "README.md").write_text("\n\n".join(content), encoding="utf-8")
        (output / "README.md").write_text("\n\n".join(root), encoding="utf-8")
    finally:
        workbook.close()


def document(document: DoclingDocument, output: Path, minimum_tokens: int, split_tokens: int, presentation: bool = False) -> None:
    items = list(document.iterate_items(with_groups=True, traverse_pictures=True))
    layout = [(0, len(items), "README.md")] if presentation else sections(items, minimum_tokens, split_tokens)
    counters, tables = Counter(), {}
    for start, stop, relative in layout:
        folder = (output / relative).parent
        folder.mkdir(parents=True, exist_ok=True)
        for item, _ in items[start:stop]:
            if isinstance(item, PictureItem):
                image = item.get_image(document)
                if image is not None:
                    counters[folder, "image"] += 1
                    name = f"image-{counters[folder, 'image']}.png"
                    image.save(folder / name, format="PNG")
                    item.image = ImageRef.from_pil(image, dpi=72)
                    item.image.uri = Path(name)
            elif isinstance(item, TableItem):
                counters[folder, "table"] += 1
                name = f"table-{counters[folder, 'table']}.csv"
                tables[item.self_ref] = name
                write_table(document, item, folder / name)
    slides = [
        position for position, (item, _) in enumerate(items)
        if getattr(item, "label", None) in {GroupLabel.SLIDE, GroupLabel.CHAPTER}
        and item.parent is not None and item.parent.cref == document.body.self_ref
    ] if presentation else []
    for start, stop, relative in layout:
        serializer = MarkdownDocSerializer(doc=document, table_serializer=TableLinks(tables), params=MarkdownParams(
            start_idx=start, stop_idx=stop, image_mode=ImageRefMode.REFERENCED, traverse_pictures=True,
        ))
        if slides:
            parts = []
            if slides[0]:
                serializer.params.stop_idx = slides[0]
                parts.append(serializer.serialize().text)
            for number, position in enumerate(slides, 1):
                serializer.params.start_idx = position
                serializer.params.stop_idx = slides[number] if number < len(slides) else stop
                parts.append(f"<!-- slide {number} -->\n\n{serializer.serialize().text}")
            content = "\n\n".join(parts)
        else:
            content = serializer.serialize().text
        (output / relative).write_text(content, encoding="utf-8")
