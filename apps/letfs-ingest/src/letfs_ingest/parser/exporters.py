import csv
import re
from collections import defaultdict
from pathlib import Path

from docling_core.transforms.serializer.common import create_ser_result
from docling_core.transforms.serializer.markdown import (
    MarkdownDocSerializer,
    MarkdownParams,
    MarkdownTableSerializer,
)
from docling_core.types.doc import (
    GroupItem,
    GroupLabel,
    ImageRef,
    ImageRefMode,
    PictureItem,
    RichTableCell,
    Size,
    TableItem,
)
from openpyxl import load_workbook
from openpyxl.utils.cell import get_column_letter

from letfs_ingest.parser.layout import Section, document_layout, ordinal
from letfs_ingest.parser.text_split import layout_limits


def slug(name: str) -> str:
    value = re.sub(r"[^\w-]+", "-", name, flags=re.UNICODE).strip("-_").lower()
    return value[:60] or "untitled"


class LinkedTables(MarkdownTableSerializer):
    def __init__(self, paths):
        self.paths = paths

    def serialize(self, *, item, doc_serializer, doc, **kwargs):
        if item.self_ref not in self.paths:
            return super().serialize(
                item=item, doc_serializer=doc_serializer, doc=doc, **kwargs
            )
        # Rich cell subtrees are already written to CSV.
        visited = kwargs.get("visited")
        if visited is not None:
            for cell in item.data.table_cells:
                if isinstance(cell, RichTableCell):
                    visited.update(
                        node.self_ref
                        for node, _ in doc.iterate_items(
                            root=cell.ref.resolve(doc),
                            with_groups=True,
                            traverse_pictures=True,
                        )
                    )
        captions = doc_serializer.serialize_captions(item=item, **kwargs).text
        footnotes = doc_serializer.serialize_footnotes(item=item, **kwargs).text
        name = self.paths[item.self_ref].name
        link = (
            f"[Table]({name})"
            if item.self_ref not in doc_serializer.get_excluded_refs(**kwargs)
            else ""
        )
        return create_ser_result(
            text="\n\n".join(part for part in (captions, link, footnotes) if part),
            span_source=item,
        )


def table_rows(document, table):
    serializer = MarkdownDocSerializer(doc=document)
    for row in table.data.grid:
        yield [
            serializer.serialize(item=cell.ref.resolve(doc=document)).text
            if isinstance(cell, RichTableCell)
            else cell.text
            for cell in row
        ]


def markdown(document, output: Path, kind: str) -> None:
    minimum, split = layout_limits()
    items = list(document.iterate_items(with_groups=True, traverse_pictures=True))
    sections = (
        [Section(0, len(items), Path("README.md"))]
        if kind == "pptx"
        else document_layout(items, minimum, split)
    )
    owners = {}
    for section in sections:
        (output / section.path.parent).mkdir(parents=True, exist_ok=True)
        for item, _ in items[section.start : section.end]:
            if item.self_ref in owners:
                raise ValueError("document item has multiple owners")
            owners[item.self_ref] = section.path.parent
    if len(owners) != len(items):
        raise ValueError("document item has no unique owner")

    pictures = defaultdict(list)
    tables = defaultdict(list)
    for item, _ in items:
        folder = owners[item.self_ref]
        if isinstance(item, PictureItem):
            image = item.get_image(document)
            if image is not None:
                pictures[folder].append((item, image))
        elif isinstance(item, TableItem):
            tables[folder].append(item)
    for folder, entries in pictures.items():
        for index, (picture, image) in enumerate(entries, 1):
            name = f"untitled-{ordinal(index, len(entries))}.png"
            image.save(output / folder / name, format="PNG")
            picture.image = ImageRef(
                mimetype="image/png",
                dpi=picture.image.dpi if picture.image is not None else 72,
                size=Size(width=image.width, height=image.height),
                uri=Path(name),
            )
    paths = {}
    for folder, entries in tables.items():
        for index, table in enumerate(entries, 1):
            name = f"untitled-{ordinal(index, len(entries))}.csv"
            paths[table.self_ref] = folder / name
            with (output / folder / name).open("w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerows(table_rows(document, table))

    for section in sections:
        serializer = MarkdownDocSerializer(
            doc=document,
            table_serializer=LinkedTables(paths),
            params=MarkdownParams(
                start_idx=section.start,
                stop_idx=section.end,
                image_mode=ImageRefMode.REFERENCED,
                traverse_pictures=True,
            ),
        )
        content = serializer.serialize().text
        if kind == "pptx":
            # Slide-group boundaries survive even when slides have no title.
            slides = [
                i
                for i, (item, _) in enumerate(items)
                if isinstance(item, GroupItem)
                and item.label in (GroupLabel.SLIDE, GroupLabel.CHAPTER)
                and item.parent is not None
                and item.parent.cref == document.body.self_ref
            ]
            if slides:
                bodies = []
                if slides[0]:
                    serializer.params.start_idx = 0
                    serializer.params.stop_idx = slides[0]
                    bodies.append(serializer.serialize().text)
                for number, start in enumerate(slides, 1):
                    serializer.params.start_idx = start
                    serializer.params.stop_idx = (
                        slides[number] if number < len(slides) else len(items)
                    )
                    bodies.append(
                        f"<!-- slide {number} -->\n\n{serializer.serialize().text}"
                    )
                content = "\n\n".join(bodies)
        (output / section.path).write_text(content, encoding="utf-8")


def spreadsheets(document, source: Path, output: Path) -> None:
    workbook = load_workbook(source, data_only=False, read_only=True)
    try:
        groups = [g for g in document.groups if g.label == GroupLabel.SHEET]
        root = [f"# {document.name}"]
        for number, sheet in enumerate(workbook.worksheets, 1):
            name = f"{ordinal(number, len(workbook.worksheets))}-untitled"
            folder = output / name
            folder.mkdir()
            root.append(f"- [{sheet.title}]({name}/README.md)")
            group = next((g for g in groups if g.name == sheet.title), None)
            items = list(document.iterate_items(root=group)) if group else []
            covered = set()
            tables = []
            for item, _ in items:
                if not isinstance(item, TableItem):
                    continue
                if len(item.prov) != 1:
                    raise ValueError("spreadsheet table has no unique position")
                box = item.prov[0].bbox
                # Singleton detections are prose, not standalone tables.
                if item.data.num_rows * item.data.num_cols > 1:
                    tables.append(item)
                    for cell in item.data.table_cells:
                        if cell.text:
                            covered.add(
                                (
                                    int(box.t) + cell.start_row_offset_idx + 1,
                                    int(box.l) + cell.start_col_offset_idx + 1,
                                )
                            )
            content = [f"# {sheet.title}"]
            for index, table in enumerate(tables, 1):
                filename = f"untitled-{ordinal(index, len(tables))}.csv"
                with (folder / filename).open("w", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerows(table_rows(document, table))
                box = table.prov[0].bbox
                cell_range = (
                    f"{get_column_letter(int(box.l) + 1)}{int(box.t) + 1}:"
                    f"{get_column_letter(int(box.l) + table.data.num_cols)}"
                    f"{int(box.t) + table.data.num_rows}"
                )
                content.append(f"- [{cell_range}]({filename})")
            for row_index, row in enumerate(sheet.iter_rows(), 1):
                for col, cell in enumerate(row, 1):
                    if cell.value is not None and (row_index, col) not in covered:
                        coordinate = f"{get_column_letter(col)}{row_index}"
                        content.append(f"{coordinate}: {cell.value}")
            pictures = [
                (item, item.get_image(document))
                for item, _ in items
                if isinstance(item, PictureItem)
            ]
            pictures = [(item, image) for item, image in pictures if image is not None]
            for index, (_, image) in enumerate(pictures, 1):
                filename = f"untitled-{ordinal(index, len(pictures))}.png"
                image.save(folder / filename, format="PNG")
                content.append(f"![Image]({filename})")
            (folder / "README.md").write_text("\n\n".join(content), encoding="utf-8")
        (output / "README.md").write_text("\n\n".join(root), encoding="utf-8")
    finally:
        workbook.close()
