import csv
import hashlib
import io
import json
import re
from collections import Counter
from contextlib import ExitStack, closing
from pathlib import Path
from typing import cast

from docling_core.transforms.serializer.base import (
    BaseDocSerializer,
    SerializationResult,
)
from docling_core.transforms.serializer.common import create_ser_result
from docling_core.transforms.serializer.markdown import (
    MarkdownDocSerializer,
    MarkdownParams,
    MarkdownPictureSerializer,
    MarkdownTableSerializer,
    MarkdownTextSerializer,
)
from docling_core.types.doc.base import ImageRefMode
from docling_core.types.doc.common.reference import ImageRef
from docling_core.types.doc.document import DoclingDocument
from docling_core.types.doc.items.picture.picture import PictureItem
from docling_core.types.doc.items.table.table import TableItem
from docling_core.types.doc.items.table.table_data import RichTableCell
from docling_core.types.doc.items.text import (
    FormulaItem,
    ListItem,
    SectionHeaderItem,
    TextItem,
    TitleItem,
)
from docling_core.types.doc.labels import GroupLabel

from .layout import estimated_tokens, write_markdown


def keep_picture(item: PictureItem) -> bool:
    # Icons can carry safety instructions; only confident, uncaptioned logos are omitted.
    classification = item.meta.classification if item.meta is not None else None
    if item.captions or classification is None or not classification.predictions:
        return True
    top = max(classification.predictions, key=lambda p: p.confidence or 0.0)
    return top.class_name != "logo" or (top.confidence or 0.0) < 0.9


class Pictures(MarkdownPictureSerializer):
    def _serialize_image_part(
        self,
        item: PictureItem,
        doc: DoclingDocument,
        image_mode: ImageRefMode,
        image_placeholder: str,
        **kwargs: object,
    ) -> SerializationResult:
        if not keep_picture(item):
            return create_ser_result(text="", span_source=item)
        return super()._serialize_image_part(
            item=item,
            doc=doc,
            image_mode=image_mode,
            image_placeholder=image_placeholder,
            **kwargs,
        )


class Text(MarkdownTextSerializer):
    filenames: dict[str, str]

    def serialize(
        self,
        *,
        item: TextItem,
        doc_serializer: BaseDocSerializer,
        doc: DoclingDocument,
        is_inline_scope: bool = False,
        in_table_cell: bool = False,
        visited: set[str] | None = None,
        **kwargs: object,
    ) -> SerializationResult:
        if (
            isinstance(item, ListItem)
            and not item.text.strip()
            and not item.children
            and not item.enumerated
            and not any(character.isalnum() for character in item.marker)
        ):
            return create_ser_result(text="", span_source=item)
        if item.self_ref in self.filenames:
            return create_ser_result(
                text=f"![Formula]({self.filenames[item.self_ref]})", span_source=item
            )
        return super().serialize(
            item=item,
            doc_serializer=doc_serializer,
            doc=doc,
            is_inline_scope=is_inline_scope,
            in_table_cell=in_table_cell,
            visited=visited,
            **kwargs,
        )

    def _format_heading(
        self,
        text: str,
        item: TitleItem | SectionHeaderItem,
        in_table_cell: bool = False,
    ) -> str:
        return (
            super()._format_heading(text, item, in_table_cell=in_table_cell)
            if text.strip()
            else ""
        )


def csv_text(rows: list[list[str]]) -> str:
    buffer = io.StringIO(newline="")
    csv.writer(buffer).writerows(rows)
    return buffer.getvalue()


def write_rows(
    rows: list[list[str]], target: Path, max_text_bytes: int
) -> list[tuple[str, int, int]]:
    parts: list[tuple[str, int, int]] = []
    name, start = target.name, 0
    with ExitStack() as stack:
        stream = stack.enter_context(target.open("wb"))
        for index, row in enumerate(rows):
            data = csv_text([row]).encode()
            if len(data) > max_text_bytes:
                raise ValueError("table row exceeds text limit")
            if stream.tell() + len(data) > max_text_bytes:
                stream.close()
                parts.append((name, start, index))
                name = f"{target.stem}-part-{len(parts) + 1}{target.suffix}"
                start = index
                stream = stack.enter_context((target.parent / name).open("wb"))
            stream.write(data)
    parts.append((name, start, len(rows)))
    return parts


class Tables(MarkdownTableSerializer):
    def __init__(
        self,
        doc: DoclingDocument,
        output: Path,
        split_tokens: int,
        max_text_bytes: int,
        formulas: dict[str, str],
    ) -> None:
        self.contents: dict[str, str] = {}
        self.doc, self.output = doc, output
        self.split_tokens, self.max_text_bytes = split_tokens, max_text_bytes
        self.serializer = MarkdownDocSerializer(
            doc=doc,
            picture_serializer=Pictures(),
            table_serializer=self,
            text_serializer=Text(filenames=formulas),
            params=MarkdownParams(
                include_picture_classification=False,
                image_mode=ImageRefMode.REFERENCED,
                traverse_pictures=True,
            ),
        )
        self.children = {
            table.self_ref: {
                node.self_ref
                for cell in table.data.table_cells
                if isinstance(cell, RichTableCell)
                for node, _ in doc.iterate_items(
                    root=cell.ref.resolve(doc), traverse_pictures=True
                )
                if isinstance(node, TableItem)
            }
            for table in doc.tables
        }
        self.nested = {ref for children in self.children.values() for ref in children}

    def rows(self, table: TableItem) -> list[list[str]]:
        rich: dict[str, str] = {}
        result: list[list[str]] = []
        for row in table.data.grid:
            values: list[str] = []
            for cell in row:
                if isinstance(cell, RichTableCell):
                    ref = cell.ref.cref
                    if ref not in rich:
                        rich[ref] = self.serializer.serialize(
                            item=cell.ref.resolve(self.doc), _nested_in_table=True
                        ).text
                    values.append(rich[ref])
                else:
                    values.append(cell.text)
            result.append(values)
        return result

    def emit(
        self, rows: list[list[str]], name: str, ref: str, *, nested: bool = False
    ) -> str:
        raw = csv_text(rows)
        fence = "`" * max(
            3, 1 + max((len(m[0]) for m in re.finditer(r"`+", raw)), default=0)
        )
        rich = ref.startswith("#/tables/") and any(
            isinstance(cell, RichTableCell)
            for cell in self.doc.tables[int(ref.rsplit("/", 1)[1])].data.table_cells
        )
        metadata = json.dumps(
            dict(source=name + ".csv", ref=ref, rich=rich), ensure_ascii=False
        )
        inline = f"<!-- artifact-table {metadata} -->\n\n{fence}csv\n{raw}{fence}"
        if (
            not nested
            and estimated_tokens(inline) <= self.split_tokens
            and len(inline.encode()) <= self.max_text_bytes
        ):
            return inline
        parts = write_rows(rows, self.output / (name + ".csv"), self.max_text_bytes)
        text = [
            f"[Table]({filename})"
            if len(parts) == 1
            else f"[Table, part {i}/{len(parts)}, rows {start + 1}-{stop}]({filename})"
            for i, (filename, start, stop) in enumerate(parts, 1)
        ]
        if len(parts) > 1:
            text.append(
                f"Column labels and table context: [first part]({parts[0][0]}). "
                "Parts continue the original rows without repeating headers."
            )
        metadata = json.dumps(
            dict(
                source=name + ".csv",
                ref=ref,
                rich=rich,
                parts=[part[0] for part in parts],
            ),
            ensure_ascii=False,
        )
        return f"<!-- artifact-table {metadata} -->\n\n" + "\n\n".join(text)

    def serialize(
        self,
        *,
        item: TableItem,
        doc_serializer: BaseDocSerializer,
        doc: DoclingDocument,
        **kwargs: object,
    ) -> SerializationResult:
        if (
            item.self_ref not in self.contents
            and item.self_ref not in doc_serializer.get_excluded_refs(**kwargs)
        ):
            rows = self.rows(item)
            values = [cell.strip() for row in rows for cell in row if cell.strip()]
            # Only transparent rich containers can alias an existing child table.
            child = next(
                (
                    value
                    for ref, value in self.contents.items()
                    if ref in self.children[item.self_ref] and values == [value]
                ),
                None,
            )
            self.contents[item.self_ref] = (
                child
                if child is not None
                else self.emit(
                    rows,
                    f"table-{int(item.self_ref.rsplit('/', 1)[1]) + 1}",
                    item.self_ref,
                    nested=item.self_ref in self.nested,
                )
            )
        visited = kwargs.get("visited")
        if isinstance(visited, set):
            visited = cast(set[str], visited)
            for cell in item.data.table_cells:
                if isinstance(cell, RichTableCell):
                    visited.update(
                        part.self_ref
                        for part, _ in doc.iterate_items(
                            root=cell.ref.resolve(doc),
                            with_groups=True,
                            traverse_pictures=True,
                        )
                    )
        parts = [doc_serializer.serialize_captions(item=item, **kwargs).text]
        if item.self_ref not in doc_serializer.get_excluded_refs(**kwargs):
            parts.append(self.contents[item.self_ref])
        parts.append(doc_serializer.serialize_footnotes(item=item, **kwargs).text)
        return create_ser_result(
            text="\n\n".join(part for part in parts if part), span_source=item
        )


def assets(document: DoclingDocument, output: Path) -> dict[str, str]:
    formulas: dict[str, str] = {}
    images: dict[tuple[str, tuple[int, int], bytes], str] = {}
    counters: Counter[str] = Counter()
    for item, _ in document.iterate_items(with_groups=True, traverse_pictures=True):
        if not isinstance(item, (PictureItem, FormulaItem)):
            continue
        if isinstance(item, PictureItem) and not keep_picture(item):
            continue
        if isinstance(item, FormulaItem) and item.text:
            continue
        image = item.get_image(document)
        if image is None:
            continue
        if isinstance(item, PictureItem):
            key = image.mode, image.size, hashlib.sha256(image.tobytes()).digest()
            name = images.get(key)
            if name is None:
                counters["image"] += 1
                name = f"image-{counters['image']}.png"
                image.save(output / name, format="PNG")
                images[key] = name
            item.image = ImageRef.from_pil(image, dpi=72)
            item.image.uri = Path(name)
        else:
            counters["formula"] += 1
            name = f"formula-{counters['formula']}.png"
            image.save(output / name, format="PNG")
            formulas[item.self_ref] = name
    return formulas


def sheet_rows(
    tables: list[TableItem],
    renderer: Tables,
    split_tokens: int,
) -> tuple[list[list[str]], bool]:
    grid: dict[tuple[int, int], str] = {}
    maxrow = maxcol = 0
    for table in tables:
        box = table.prov[0].bbox
        row, col = int(box.t) + 1, int(box.l) + 1
        for i, values in enumerate(renderer.rows(table), row):
            for j, value in enumerate(values, col):
                if (i, j) in grid and grid[i, j] != value:
                    return [], False
                grid[i, j] = value
                maxrow, maxcol = max(maxrow, i), max(maxcol, j)
    # Avoid manufacturing a large empty rectangle around sparse regions.
    if maxrow * maxcol > 2 * len(grid) + 4 * split_tokens:
        return [], False
    return [
        [grid.get((i, j), "") for j in range(1, maxcol + 1)]
        for i in range(1, maxrow + 1)
    ], True


def spreadsheets(
    document: DoclingDocument,
    source: Path,
    output: Path,
    max_text_bytes: int,
    split_tokens: int = 4096,
) -> None:
    from openpyxl import load_workbook
    from openpyxl.utils.cell import get_column_letter

    renderer = Tables(
        document, output, split_tokens, max_text_bytes, assets(document, output)
    )
    with (
        closing(load_workbook(source, data_only=False, read_only=True)) as workbook,
        closing(load_workbook(source, data_only=True, read_only=True)) as cached,
    ):
        content = [f"# {' '.join(document.name.split())}"]
        sheets = {
            group.name: group
            for group in document.groups
            if group.label == GroupLabel.SHEET
        }
        for number, sheet in enumerate(workbook.worksheets, 1):
            content.append(f"# {sheet.title}")
            covered: set[tuple[int, int]] = set()
            group = sheets.get(sheet.title)
            items = list(document.iterate_items(root=group)) if group else []
            tables = [
                item
                for item, _ in items
                if isinstance(item, TableItem)
                and item.data.num_rows * item.data.num_cols > 1
            ]
            merged, safe = sheet_rows(tables, renderer, split_tokens)
            views = (
                [(1, 1, merged, f"sheet-{number}", f"sheet-{number}-cells")]
                if safe and merged
                else [
                    (
                        int(table.prov[0].bbox.t) + 1,
                        int(table.prov[0].bbox.l) + 1,
                        renderer.rows(table),
                        table.self_ref,
                        f"table-{int(table.self_ref.rsplit('/', 1)[1]) + 1}",
                    )
                    for table in tables
                ]
            )
            for row, col, data, ref, name in views:
                label = f"{get_column_letter(col)}{row}:{get_column_letter(col + len(data[0]) - 1)}{row + len(data) - 1}"
                content.append(
                    f"Table {label}; columns {get_column_letter(col)}-{get_column_letter(col + len(data[0]) - 1)}"
                )
                content.append(renderer.emit(data, name, ref))
            for table in tables:
                row, col = int(table.prov[0].bbox.t) + 1, int(table.prov[0].bbox.l) + 1
                covered.update(
                    (row + cell.start_row_offset_idx, col + cell.start_col_offset_idx)
                    for cell in table.data.table_cells
                    if cell.text
                )
            for row, cached_row in zip(sheet, cached[sheet.title], strict=True):
                for cell, rendered in zip(row, cached_row, strict=True):
                    if cell.value is None or (cell.row, cell.column) in covered:
                        continue
                    value = cell.value
                    if cell.data_type == "f":
                        formula = (
                            value
                            if isinstance(value, str)
                            else getattr(value, "text", None)
                        )
                        value = formula or "[formula without cached value]"
                        if rendered.value is not None:
                            value = str(rendered.value)
                            if formula:
                                value += f" (formula: {formula})"
                    content.append(f"{cell.coordinate}: {value}")
            content.extend(
                f"![Image]({item.image.uri})"
                for item, _ in items
                if isinstance(item, PictureItem)
                and keep_picture(item)
                and item.image is not None
            )
        write_markdown("\n\n".join(content), output, split_tokens, max_text_bytes)


def document(
    document: DoclingDocument,
    output: Path,
    split_tokens: int,
    max_text_bytes: int,
    presentation: bool = False,
) -> None:
    formulas = assets(document, output)
    tables = Tables(document, output, split_tokens, max_text_bytes, formulas)
    items = list(document.iterate_items(with_groups=True, traverse_pictures=True))
    serializer = MarkdownDocSerializer(
        doc=document,
        picture_serializer=Pictures(),
        table_serializer=tables,
        text_serializer=Text(filenames=formulas),
        params=MarkdownParams(
            include_picture_classification=False,
            image_mode=ImageRefMode.REFERENCED,
            traverse_pictures=True,
        ),
    )
    slides = [
        position
        for position, (item, _) in enumerate(items)
        if presentation
        and getattr(item, "label", None) in {GroupLabel.SLIDE, GroupLabel.CHAPTER}
        and item.parent is not None
        and item.parent.cref == document.body.self_ref
    ]
    if slides:
        content: list[str] = []
        if slides[0]:
            serializer.params.stop_idx = slides[0]
            content.append(serializer.serialize().text)
        for number, position in enumerate(slides, 1):
            serializer.params.start_idx = position
            serializer.params.stop_idx = (
                slides[number] if number < len(slides) else len(items)
            )
            content.append(f"<!-- slide {number} -->\n\n{serializer.serialize().text}")
        text = "\n\n".join(content)
    else:
        text = serializer.serialize().text
    write_markdown(text, output, split_tokens, max_text_bytes)
