import re
import sys
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import openpyxl
from openlet_sdk.config import Config, load
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pypdf import PdfReader

from .filters import ImageArtifactWriter, ignored_repeated_digests, image_digest
from .layout import write_markdown
from .naming import slugify
from .tables import externalize_tables, write_rows

PDF_MEDIA = "application/pdf"
DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX_MEDIA = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

OFFICE_MEDIA = {DOCX_MEDIA, PPTX_MEDIA, XLSX_MEDIA}


class InvalidDocument(ValueError):
    pass


def page_limit(config: Config) -> int:
    return config["services"]["letfs_ingest"]["cpu"]["limits"]["max_pages"]


def _zip_expanded_bytes(source: Path, limit: int) -> None:
    try:
        with zipfile.ZipFile(source) as zf:
            total = sum(info.file_size for info in zf.infolist())
    except (zipfile.BadZipFile, OSError) as exc:
        raise InvalidDocument(f"corrupt archive: {exc}") from exc
    if total > limit:
        raise InvalidDocument(
            f"archive expanded size ({total} bytes) exceeds limit ({limit})"
        )


def preflight(source: Path, media: str, config: Config) -> None:
    limits = config["services"]["letfs_ingest"]["cpu"]["limits"]
    if media in OFFICE_MEDIA:
        _zip_expanded_bytes(source, limits["max_office_expanded_bytes"])
    if media == PDF_MEDIA:
        try:
            with source.open("rb") as fh:
                reader = PdfReader(fh)
                page_count = len(reader.pages)
                if page_count > limits["max_pages"]:
                    raise InvalidDocument(
                        f"PDF has {page_count} pages exceeding limit {limits['max_pages']}"
                    )
                for page in reader.pages:
                    box = page.cropbox
                    unit = float(getattr(page, "user_unit", 1.0) or 1.0)
                    w = float(box.width) * unit
                    h = float(box.height) * unit
                    if w * h > limits["max_page_pixels"]:
                        raise InvalidDocument("PDF page dimensions exceed pixel limit")
        except InvalidDocument:
            raise
        except Exception as exc:
            raise InvalidDocument(f"invalid PDF: {exc}") from exc
    if media == XLSX_MEDIA:
        try:
            wb: Any = openpyxl.load_workbook(source, read_only=True, data_only=True)
        except Exception as exc:
            raise InvalidDocument(f"invalid spreadsheet: {exc}") from exc
        try:
            if len(wb.sheetnames) > limits["max_sheets"]:
                raise InvalidDocument(
                    f"spreadsheet has {len(wb.sheetnames)} sheets exceeding limit {limits['max_sheets']}"
                )
            cells = 0
            for name in wb.sheetnames:
                ws = wb[name]
                cells += (ws.max_row or 0) * (ws.max_column or 0)
                if cells > limits["max_spreadsheet_cells"]:
                    raise InvalidDocument("spreadsheet cell count exceeds limit")
        finally:
            wb.close()


def _cell_str(val: object) -> str:
    if val is None:
        return ""
    if (
        isinstance(val, datetime)
        and val.hour == 0
        and val.minute == 0
        and val.second == 0
        and val.microsecond == 0
    ):
        return val.date().isoformat()
    return " ".join(str(val).splitlines()).strip()


def _is_numeric_cell(val: str) -> bool:
    cleaned = val.strip().replace(",", "").replace("$", "").replace("%", "")
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = cleaned[1:-1]
    if not cleaned:
        return False
    try:
        float(cleaned)
        return True
    except ValueError:
        return False


def _is_year_token(val: str) -> bool:
    return bool(re.fullmatch(r"(?:19|20)\d{2}(?:\.0)?", val.strip()))


@dataclass
class _SheetRegion:
    """Connected spreadsheet block with 0-based [r0, r1) x [c0, c1) bounds."""

    r0: int
    r1: int
    c0: int
    c1: int
    pts: set[tuple[int, int]]


def _anchor_rows(reg: _SheetRegion, cells: dict[tuple[int, int], str]) -> set[int]:
    return {r for r, c in reg.pts if (r, c) in cells}


def _anchor_cols(reg: _SheetRegion, cells: dict[tuple[int, int], str]) -> list[int]:
    return sorted({c for r, c in reg.pts if (r, c) in cells})


def _union_region(a: _SheetRegion, b: _SheetRegion) -> _SheetRegion:
    return _SheetRegion(
        r0=min(a.r0, b.r0),
        r1=max(a.r1, b.r1),
        c0=min(a.c0, b.c0),
        c1=max(a.c1, b.c1),
        pts=a.pts | b.pts,
    )


def _bfs_regions(
    populated: set[tuple[int, int]],
    merged_rects: dict[tuple[int, int], tuple[int, int, int, int]],
    shadow_to_anchor: dict[tuple[int, int], tuple[int, int]],
) -> list[_SheetRegion]:
    """Group 4-connected non-empty cells and merged blocks via bottom-up BFS."""
    visited: set[tuple[int, int]] = set()
    regions: list[_SheetRegion] = []
    for start in sorted(populated):
        if start in visited:
            continue
        queue = [start]
        visited.add(start)
        pts: set[tuple[int, int]] = set()
        r0 = r1 = start[0]
        c0 = c1 = start[1]
        while queue:
            r, c = queue.pop()
            pts.add((r, c))
            r0 = min(r0, r)
            r1 = max(r1, r)
            c0 = min(c0, c)
            c1 = max(c1, c)
            neighbors: list[tuple[int, int]] = [
                (r - 1, c),
                (r + 1, c),
                (r, c - 1),
                (r, c + 1),
            ]
            anchor = shadow_to_anchor.get((r, c), (r, c))
            if anchor in merged_rects:
                mr0, mr1, mc0, mc1 = merged_rects[anchor]
                for mr in range(mr0, mr1):
                    for mc in range(mc0, mc1):
                        neighbors.append((mr, mc))
            for nr, nc in neighbors:
                if (nr, nc) in populated and (nr, nc) not in visited:
                    visited.add((nr, nc))
                    queue.append((nr, nc))
        regions.append(_SheetRegion(r0=r0, r1=r1 + 1, c0=c0, c1=c1 + 1, pts=pts))
    return regions


def _bind_left_labels(
    regions: list[_SheetRegion], cells: dict[tuple[int, int], str]
) -> list[_SheetRegion]:
    """Rule 1: bind narrow left text-label columns to aligned data blocks across blank cols."""
    working = sorted(regions, key=lambda g: (g.r0, g.c0))
    removed: set[int] = set()
    for i, left in enumerate(working):
        if i in removed:
            continue
        l_cols = _anchor_cols(left, cells)
        if not l_cols or len(l_cols) > 2 or left.c1 - left.c0 > 2:
            continue
        l_col = l_cols[-1]
        l_vals = [
            cells[(r, l_col)] for r in range(left.r0, left.r1) if (r, l_col) in cells
        ]
        if not l_vals:
            continue
        numeric_l = sum(
            1 for v in l_vals if _is_numeric_cell(v) and not _is_year_token(v)
        )
        if numeric_l * 2 >= len(l_vals):
            continue
        l_rows = _anchor_rows(left, cells)
        if not l_rows:
            continue

        candidates: list[tuple[int, int]] = []
        for j, right in enumerate(working):
            if j == i or j in removed or right.c0 < left.c1:
                continue
            gap = right.c0 - left.c1
            if gap > 6:
                continue
            r_rows = _anchor_rows(right, cells)
            shared = l_rows & r_rows
            if not shared or len(shared) * 2 < len(l_rows):
                continue
            if len(shared) < 2 and not (len(l_rows) == 1 and len(r_rows) == 1):
                continue
            candidates.append((right.c0, j))
        if not candidates:
            continue

        candidates.sort()
        _, best_j = candidates[0]
        right = working[best_j]
        shared = l_rows & _anchor_rows(right, cells)
        blocked = any(
            k not in removed
            and k not in {i, best_j}
            and working[k].c0 >= left.c1
            and working[k].c0 < right.c0
            and bool(_anchor_rows(working[k], cells) & shared)
            for k in range(len(working))
        )
        if blocked:
            continue
        r_cols = _anchor_cols(right, cells)
        if not r_cols:
            continue
        r_first = [
            cells[(r, r_cols[0])] for r in sorted(shared) if (r, r_cols[0]) in cells
        ]
        r_first_num = sum(1 for v in r_first if _is_numeric_cell(v))
        is_single_val_col = len(r_cols) == 1 and len(shared) >= 1
        if not is_single_val_col and (not r_first or r_first_num * 2 < len(r_first)):
            continue
        working[best_j] = _union_region(left, right)
        removed.add(i)

    return [g for idx, g in enumerate(working) if idx not in removed]


def _is_header_band(top: _SheetRegion, cells: dict[tuple[int, int], str]) -> bool:
    if top.r1 - top.r0 > 4 or len(_anchor_cols(top, cells)) < 2:
        return False
    for r, c in top.pts:
        val = cells.get((r, c), "")
        if val and _is_numeric_cell(val) and not _is_year_token(val):
            return False
    return True


def _starts_new_table_header(
    bot: _SheetRegion, cells: dict[tuple[int, int], str]
) -> bool:
    first_row = min((r for r, c in bot.pts if (r, c) in cells), default=bot.r0)
    row_vals = [cells[(r, c)] for r, c in bot.pts if r == first_row and (r, c) in cells]
    if len(row_vals) <= 1:
        # Single-cell subheader (e.g., "Operating expenses") continues table if next row has numbers.
        next_rows = sorted({r for r, c in bot.pts if r > first_row and (r, c) in cells})
        if not next_rows:
            return True
        next_vals = [
            cells[(r, c)] for r, c in bot.pts if r == next_rows[0] and (r, c) in cells
        ]
        return not any(_is_numeric_cell(v) for v in next_vals)
    # Multi-cell row: if every cell is non-numeric text (not year/data), it is a new table header.
    return not any(_is_numeric_cell(v) for v in row_vals)


def _is_numeric_or_placeholder(val: str) -> bool:
    return _is_numeric_cell(val) or val.strip().lower() in {"na", "n/a", "nm", "-"}


def _unit_note_blocker(
    blockers: list[int],
    working: list[_SheetRegion],
    top: _SheetRegion,
    bot: _SheetRegion,
    cells: dict[tuple[int, int], str],
) -> int | None:
    """Return index of a single 1x1 left-gutter unit note sitting between header and body."""
    if len(blockers) != 1 or bot.r0 - top.r1 != 2:
        return None
    mid_idx = blockers[0]
    mid = working[mid_idx]
    mid_cols = _anchor_cols(mid, cells)
    if (
        mid.r0 < top.r1
        or mid.r1 > bot.r0
        or mid.r1 - mid.r0 != 1
        or len(mid_cols) != 1
        or mid.c0 > top.c0
    ):
        return None
    mid_val = cells.get((mid.r0, mid_cols[0]), "")
    return None if not mid_val or _is_numeric_cell(mid_val) else mid_idx


def _merge_vertical_continuations(
    regions: list[_SheetRegion], cells: dict[tuple[int, int], str]
) -> list[_SheetRegion]:
    """Rule 2: bridge spacer rows between header bands, unit notes, and aligned table bodies."""
    working = list(regions)
    changed = True
    while changed:
        changed = False
        working.sort(key=lambda g: (g.r0, g.c0))
        for i in range(len(working)):
            top = working[i]
            top_cols = _anchor_cols(top, cells)
            if len(top_cols) < 2:
                continue
            top_is_hdr = _is_header_band(top, cells)
            merged_now = False
            for j in range(len(working)):
                if i == j:
                    continue
                bot = working[j]
                bot_cols = _anchor_cols(bot, cells)
                if len(bot_cols) < 2:
                    continue
                gap = bot.r0 - top.r1
                if gap not in {0, 1, 2}:
                    continue
                if gap == 0 and not (top_is_hdr and top.c0 > bot.c0):
                    continue
                if gap == 2 and (
                    not top_is_hdr or _starts_new_table_header(bot, cells)
                ):
                    continue
                overlap_c = min(top.c1, bot.c1) - max(top.c0, bot.c0)
                min_w = min(top.c1 - top.c0, bot.c1 - bot.c0)
                if min_w <= 0 or overlap_c * 2 < min_w:
                    continue
                corridor_c0, corridor_c1 = min(top.c0, bot.c0), max(top.c1, bot.c1)
                corridor_r0, corridor_r1 = min(top.r0, bot.r0), max(top.r1, bot.r1)
                blockers = [
                    k
                    for k in range(len(working))
                    if k not in {i, j}
                    and working[k].r0 < corridor_r1
                    and working[k].r1 > corridor_r0
                    and min(working[k].c1, corridor_c1)
                    > max(working[k].c0, corridor_c0)
                ]
                absorb_mid: int | None = None
                if blockers:
                    if top_is_hdr and not _starts_new_table_header(bot, cells):
                        absorb_mid = _unit_note_blocker(
                            blockers, working, top, bot, cells
                        )
                    if absorb_mid is None:
                        continue
                if gap == 0:
                    bot_first_cols = [
                        c for r, c in bot.pts if r == bot.r0 and (r, c) in cells
                    ]
                    if len(bot_first_cols) > 1 and _starts_new_table_header(bot, cells):
                        continue

                if top_is_hdr:
                    should_merge = True
                elif abs(
                    top_cols[0] - bot_cols[0]
                ) <= 1 and not _starts_new_table_header(bot, cells):
                    should_merge = True
                else:
                    should_merge = False

                if should_merge:
                    merged_reg = _union_region(top, bot)
                    if absorb_mid is not None:
                        merged_reg = _union_region(merged_reg, working[absorb_mid])
                    working[i] = merged_reg
                    pops = [j, *([absorb_mid] if absorb_mid is not None else [])]
                    for pop_idx in sorted(pops, reverse=True):
                        working.pop(pop_idx)
                    changed = True
                    merged_now = True
                    break
            if merged_now:
                break
    return sorted(working, key=lambda g: (g.r0, g.c0))


def _merge_horizontal_continuations(
    regions: list[_SheetRegion], cells: dict[tuple[int, int], str]
) -> list[_SheetRegion]:
    """Rule 3: attach numeric year/quarter sub-blocks separated by a single empty total column."""
    working = list(regions)
    changed = True
    while changed:
        changed = False
        working.sort(key=lambda g: (g.r0, g.c0))
        for i in range(len(working)):
            left = working[i]
            l_cols = _anchor_cols(left, cells)
            if not l_cols:
                continue
            l_rows = _anchor_rows(left, cells)
            l_first = [
                cells[(r, l_cols[0])] for r in sorted(l_rows) if (r, l_cols[0]) in cells
            ]
            l_first_num = sum(
                1 for v in l_first if _is_numeric_cell(v) and not _is_year_token(v)
            )
            if not l_first or l_first_num * 2 >= len(l_first):
                continue
            merged_now = False
            for j in range(len(working)):
                if i == j:
                    continue
                right = working[j]
                r_rows = _anchor_rows(right, cells)
                shared = l_rows & r_rows
                if len(shared) < 2 or len(shared) < len(r_rows):
                    continue
                row_left_c1 = max(
                    (c + 1 for r, c in left.pts if r in shared and (r, c) in cells),
                    default=-1,
                )
                if right.c0 - row_left_c1 != 1:
                    continue
                if any(
                    r in shared and right.c0 <= c < right.c1
                    for r, c in left.pts
                    if (r, c) in cells
                ):
                    continue
                min_sr, max_sr = min(shared), max(shared)
                if any(
                    k not in {i, j}
                    and working[k].r0 <= max_sr
                    and working[k].r1 > min_sr
                    and min(working[k].c1, right.c0) > max(working[k].c0, row_left_c1)
                    for k in range(len(working))
                ):
                    continue
                r_all = [cells[(r, c)] for r, c in right.pts if (r, c) in cells]
                r_num = sum(1 for v in r_all if _is_numeric_cell(v))
                r_ok = sum(1 for v in r_all if _is_numeric_or_placeholder(v))
                if not r_num or r_ok * 4 < len(r_all) * 3:
                    continue
                working[i] = _union_region(left, right)
                working.pop(j)
                changed = True
                merged_now = True
                break
            if merged_now:
                break
    return sorted(working, key=lambda g: (g.r0, g.c0))


def _group_header_fills(
    reg: _SheetRegion,
    cells: dict[tuple[int, int], str],
    merged_rects: dict[tuple[int, int], tuple[int, int, int, int]],
    kept_cols: list[int],
) -> dict[tuple[int, int], str]:
    """Repeat horizontal merged group headers only when >=2 columns lie beneath them."""
    fills: dict[tuple[int, int], str] = {}
    for (ar, ac), (mr0, mr1, mc0, mc1) in merged_rects.items():
        if mr1 - mr0 != 1 or mc1 - mc0 <= 1:
            continue
        if not (reg.r0 <= ar < reg.r1 and reg.c0 <= ac < reg.c1):
            continue
        # Never broadcast a lone full-row banner title at the top of a table.
        row_anchors = sum(1 for c in kept_cols if (ar, c) in cells)
        if ar == reg.r0 and row_anchors == 1:
            continue
        val = cells.get((ar, ac), "")
        if not val or ar + 1 >= reg.r1:
            continue
        children_under = sum(1 for c in range(mc0, mc1) if (ar + 1, c) in cells)
        if children_under >= 2:
            for c in range(mc0, mc1):
                fills[(ar, c)] = val
    return fills


_DIRECT_CELL_REF_RE = re.compile(
    r"^=\s*(?:(?:'((?:[^']|'')+)'|([A-Za-z0-9_.\s]+))!)?\$?([A-Za-z]{1,3})\$?(\d+)\s*$"
)


def _col_letters_to_index(col: str) -> int:
    idx = 0
    for ch in col.upper():
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx


def _extract_formula_text(val: object) -> str:
    if isinstance(val, str):
        return val.strip()
    text = getattr(val, "text", None)
    if isinstance(text, str):
        return text.strip()
    return ""


def _resolve_formula_fallback(
    wb_cached: object,
    wb_formulas: object,
    sheet_name: str,
    r1: int,
    c1: int,
) -> str:
    """Resolve uncached formula cells by following simple cell refs or emitting the formula."""
    cached_wb = cast(Any, wb_cached)
    formula_wb = cast(Any, wb_formulas)
    cur_sheet, cur_r, cur_c = sheet_name, r1, c1
    visited: set[tuple[str, int, int]] = set()
    first_formula = ""
    for _ in range(8):
        key = (cur_sheet, cur_r, cur_c)
        if key in visited:
            break
        visited.add(key)
        if cur_sheet not in formula_wb.sheetnames:
            break
        f_cell = getattr(formula_wb[cur_sheet], "_cells", {}).get((cur_r, cur_c))
        formula = _extract_formula_text(getattr(f_cell, "value", None))
        if not formula.startswith("="):
            break
        if not first_formula:
            first_formula = formula
        m = _DIRECT_CELL_REF_RE.match(formula)
        if not m:
            return first_formula
        ref_sheet = m.group(1) or m.group(2)
        if ref_sheet is not None:
            ref_sheet = ref_sheet.replace("''", "'").strip()
            if ref_sheet not in cached_wb.sheetnames:
                return first_formula
            cur_sheet = ref_sheet
        cur_c = _col_letters_to_index(m.group(3))
        cur_r = int(m.group(4))
        c_cell = getattr(cached_wb[cur_sheet], "_cells", {}).get((cur_r, cur_c))
        cached_txt = _cell_str(getattr(c_cell, "value", None))
        if cached_txt:
            return cached_txt
    return first_formula


def convert_xlsx(source: Path, output: Path, config: Config) -> None:
    storage = config["services"]["letfs"]
    limits = config["services"]["letfs_ingest"]["cpu"]["limits"]
    max_text = storage["max_text_bytes"]
    max_blob = storage["processing"]["max_artifact_blob_bytes"]
    max_output = limits["max_output_bytes"]

    wb: Any = openpyxl.load_workbook(source, read_only=False, data_only=True)
    wb_formulas: Any = openpyxl.load_workbook(source, read_only=False, data_only=False)
    output.mkdir(parents=True, exist_ok=True)
    writer = ImageArtifactWriter(output, max_blob=max_blob, max_output=max_output)
    readme_lines: list[str] = ["# Workbook Index\n"]
    table_idx = 0

    try:
        for sheet_name in wb.sheetnames:
            ws: Any = wb[sheet_name]
            ws_f: Any = wb_formulas[sheet_name]
            readme_lines.append(f"\n## Sheet: {sheet_name}\n")

            cells: dict[tuple[int, int], str] = {}
            cached_cells: dict[tuple[int, int], Any] = getattr(ws, "_cells", {})
            formula_cells: dict[tuple[int, int], Any] = getattr(ws_f, "_cells", {})
            for coord in set(cached_cells) | set(formula_cells):
                r1, c1 = int(coord[0]), int(coord[1])
                c_cell = cached_cells.get(coord)
                txt = _cell_str(getattr(c_cell, "value", None))
                if not txt and coord in formula_cells:
                    txt = _resolve_formula_fallback(wb, wb_formulas, sheet_name, r1, c1)
                if txt:
                    cells[(r1 - 1, c1 - 1)] = txt

            if cells:
                merged_rects: dict[tuple[int, int], tuple[int, int, int, int]] = {}
                shadow_to_anchor: dict[tuple[int, int], tuple[int, int]] = {}
                populated = set(cells)
                for rng in ws.merged_cells.ranges:
                    ar, ac = int(rng.min_row) - 1, int(rng.min_col) - 1
                    if (ar, ac) not in cells:
                        continue
                    mr0, mr1 = ar, int(rng.max_row)
                    mc0, mc1 = ac, int(rng.max_col)
                    merged_rects[(ar, ac)] = (mr0, mr1, mc0, mc1)
                    for mr in range(mr0, mr1):
                        for mc in range(mc0, mc1):
                            populated.add((mr, mc))
                            shadow_to_anchor[(mr, mc)] = (ar, ac)

                regions = _bfs_regions(populated, merged_rects, shadow_to_anchor)
                regions = _bind_left_labels(regions, cells)
                regions = _merge_vertical_continuations(regions, cells)
                regions = _merge_horizontal_continuations(regions, cells)

                pending_title: str | None = None
                for idx, reg in enumerate(regions):
                    kept_cols = _anchor_cols(reg, cells)
                    if not kept_cols:
                        continue
                    fills = _group_header_fills(reg, cells, merged_rects, kept_cols)
                    raw_rows: list[list[str]] = []
                    for r in range(reg.r0, reg.r1):
                        row = [
                            cells.get((r, c)) or fills.get((r, c), "")
                            for c in kept_cols
                        ]
                        if any(row):
                            raw_rows.append(row)
                    if not raw_rows:
                        continue

                    peeled_titles: list[str] = []
                    while len(raw_rows) >= 2:
                        row_vals = [v for v in raw_rows[0] if v]
                        max_below = max(len([v for v in r if v]) for r in raw_rows[1:])
                        if len(row_vals) == 1 and max_below >= 2:
                            peeled_titles.append(row_vals[0])
                            raw_rows.pop(0)
                        else:
                            break

                    non_empty = [v for r in raw_rows for v in r if v]
                    if len(non_empty) <= 2 and sum(len(v) for v in non_empty) <= 3:
                        continue

                    active_cols = sum(
                        1
                        for ci in range(len(kept_cols))
                        if any(r[ci] for r in raw_rows)
                    )
                    if (
                        len(raw_rows) == 1
                        and len(non_empty) <= 2
                        and idx + 1 < len(regions)
                    ):
                        pending_title = " - ".join([*peeled_titles, *non_empty])
                        continue

                    if active_cols <= 1 and (
                        len(raw_rows) <= 3 or any(len(v) > 25 for v in non_empty)
                    ):
                        note = " - ".join([*peeled_titles, *non_empty])
                        readme_lines.append(f"- {note}")
                        continue

                    table_idx += 1
                    sheet_slug = slugify(sheet_name, limit=24)
                    filename = f"{table_idx:02d}-{sheet_slug}.csv"
                    parts = write_rows(raw_rows, output / "tables" / filename, max_text)
                    header_preview = " | ".join(c for c in raw_rows[0] if c)[:100]
                    label = (
                        pending_title
                        or (" - ".join(peeled_titles) if peeled_titles else "")
                        or f"{sheet_name} table {table_idx}"
                    )
                    pending_title = None
                    for part_name, first_r, last_r in parts:
                        row_count = last_r - first_r
                        desc = f"{label} ({row_count}x{active_cols})"
                        if header_preview:
                            desc += f": {header_preview}"
                        readme_lines.append(f"- [{desc}](tables/{part_name})")

            for img in getattr(ws, "_images", []):
                try:
                    raw_img: bytes = img._data()
                except Exception:
                    continue
                before = writer.count
                try:
                    keep, rel = writer.save(raw_img)
                except ValueError as exc:
                    raise InvalidDocument(f"spreadsheet {exc}") from exc
                if keep and rel is not None and writer.count > before:
                    readme_lines.append(
                        f"- ![{sheet_name} image {writer.count}]({rel})"
                    )
    finally:
        wb.close()
        wb_formulas.close()

    readme = _fit_utf8_bytes("\n".join(readme_lines).strip() + "\n", max_text)
    (output / "README.md").write_text(readme, encoding="utf-8")


def _fit_utf8_bytes(text: str, limit: int) -> str:
    raw = text.encode("utf-8")
    return text if len(raw) <= limit else raw[:limit].decode("utf-8", errors="ignore")


def _iter_shapes_in_order(shapes: object) -> list[Any]:
    items = list(cast(list[Any], shapes))
    ordered = sorted(
        items,
        key=lambda s: (int(getattr(s, "top", 0) or 0), int(getattr(s, "left", 0) or 0)),
    )
    out: list[Any] = []
    for shape in ordered:
        if getattr(shape, "shape_type", None) == MSO_SHAPE_TYPE.GROUP:
            out.extend(_iter_shapes_in_order(shape.shapes))
        else:
            out.append(shape)
    return out


def _render_markdown_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    lines = [
        "| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |"
        for row in rows
    ]
    lines.insert(1, "| " + " | ".join(["---"] * len(rows[0])) + " |")
    return "\n".join(lines)


def _render_chart_markdown(shape: object) -> str:
    chart: Any = getattr(shape, "chart")
    lines: list[str] = []
    title_text = ""
    if getattr(chart, "has_title", False):
        title_text = _cell_str(chart.chart_title.text_frame.text)
    lines.append(f"### Chart: {title_text}" if title_text else "### Chart")
    try:
        plot = chart.plots[0]
        categories = [_cell_str(c.label) for c in getattr(plot, "categories", [])]
        series_list = list(getattr(plot, "series", []))
        if series_list:
            headers = [
                "Category",
                *[
                    _cell_str(s.name) or f"Series {i + 1}"
                    for i, s in enumerate(series_list)
                ],
            ]
            rows = [headers]
            max_len = max(
                [len(categories), *[len(s.values) for s in series_list]], default=0
            )
            for idx in range(max_len):
                cat = categories[idx] if idx < len(categories) else str(idx + 1)
                vals = [
                    _cell_str(s.values[idx]) if idx < len(s.values) else ""
                    for s in series_list
                ]
                rows.append([cat, *vals])
            lines.append("")
            lines.append(_render_markdown_table(rows))
    except Exception:
        pass
    return "\n".join(lines)


def _render_table_markdown(table: object) -> str:
    tbl: Any = table
    rows = [[_cell_str(cell.text) for cell in row.cells] for row in tbl.rows]
    return _render_markdown_table(rows)


def convert_pptx(source: Path, output: Path, config: Config) -> None:
    storage = config["services"]["letfs"]
    parser = config["services"]["letfs_ingest"]["cpu"]
    limits = parser["limits"]
    max_text = storage["max_text_bytes"]
    max_blob = storage["processing"]["max_artifact_blob_bytes"]
    max_output = limits["max_output_bytes"]

    prs: Any = Presentation(str(source))
    slides = list(prs.slides)
    if len(slides) > limits["max_pages"]:
        raise InvalidDocument(
            f"presentation has {len(slides)} slides exceeding limit {limits['max_pages']}"
        )

    # Identify repeating template logos/watermarks across slides.
    digest_slides: Counter[bytes] = Counter()
    for slide in slides:
        seen_on_slide: set[bytes] = set()
        for shape in _iter_shapes_in_order(slide.shapes):
            if hasattr(shape, "image"):
                try:
                    seen_on_slide.add(image_digest(bytes(shape.image.blob)))
                except Exception:
                    continue
        for d in seen_on_slide:
            digest_slides[d] += 1
    ignored: set[bytes] = (
        ignored_repeated_digests(digest_slides, min_count=max(3, len(slides) // 2))
        if len(slides) >= 3
        else set()
    )

    output.mkdir(parents=True, exist_ok=True)
    writer = ImageArtifactWriter(
        output, max_blob=max_blob, max_output=max_output, ignored_digests=ignored
    )
    slide_blocks: list[str] = []

    for slide_num, slide in enumerate(slides, 1):
        parts: list[str] = [f"<!-- slide {slide_num} -->"]
        title_shape = slide.shapes.title
        title_text = (
            _cell_str(title_shape.text_frame.text)
            if title_shape is not None and title_shape.has_text_frame
            else ""
        )
        parts.append(f"# {title_text}" if title_text else f"# Slide {slide_num}")

        for shape in _iter_shapes_in_order(slide.shapes):
            if shape == title_shape:
                continue
            if getattr(shape, "has_table", False):
                md_table = _render_table_markdown(shape.table)
                if md_table:
                    parts.append(md_table)
                continue
            if getattr(shape, "has_chart", False):
                parts.append(_render_chart_markdown(shape))
                continue
            if hasattr(shape, "image"):
                try:
                    raw_blob = bytes(shape.image.blob)
                except Exception:
                    continue
                try:
                    keep, rel_path = writer.save(raw_blob)
                except ValueError as exc:
                    raise InvalidDocument(f"presentation {exc}") from exc
                if not keep or rel_path is None:
                    continue
                alt = (
                    _cell_str(getattr(shape, "name", "")) or f"Slide {slide_num} figure"
                )
                parts.append(f"![{alt}]({rel_path})")
                continue
            if getattr(shape, "has_text_frame", False):
                tf_lines: list[str] = []
                for para in shape.text_frame.paragraphs:
                    txt = _cell_str(para.text)
                    if not txt:
                        continue
                    lvl = int(getattr(para, "level", 0) or 0)
                    indent = "  " * max(0, lvl - 1)
                    tf_lines.append(f"{indent}- {txt}" if lvl > 0 else txt)
                if tf_lines:
                    parts.append("\n".join(tf_lines))

        if getattr(slide, "has_notes_slide", False):
            notes_tf = getattr(slide.notes_slide, "notes_text_frame", None)
            notes = _cell_str(notes_tf.text) if notes_tf is not None else ""
            if notes:
                parts.append(f"> Speaker Notes: {notes}")

        slide_blocks.append("\n\n".join(parts))

    body = "\n\n".join(slide_blocks).strip()
    if not body:
        raise InvalidDocument("presentation contains no extractable content")
    body = externalize_tables(body, output, parser["split_tokens"], max_text)
    write_markdown(body, output, parser["split_tokens"], max_text)


def convert(source: Path, media: str, output: Path, config: Config) -> None:
    preflight(source, media, config)
    if media == XLSX_MEDIA:
        convert_xlsx(source, output, config)
    elif media == PPTX_MEDIA:
        convert_pptx(source, output, config)
    else:
        raise InvalidDocument(f"unsupported local conversion media type: {media}")
    validate_output(output, config)


def validate_output(output: Path, config: Config) -> None:
    storage = config["services"]["letfs"]
    proc = storage["processing"]
    limits = config["services"]["letfs_ingest"]["cpu"]["limits"]
    files = sorted(p for p in output.rglob("*") if p.is_file())
    if len(files) > proc["max_artifacts"]:
        raise InvalidDocument("converted output exceeds max_artifacts limit")
    total_text = 0
    total_blob = 0
    for file in files:
        size = file.stat().st_size
        if file.suffix in {".md", ".csv", ".html"}:
            if size > storage["max_text_bytes"]:
                raise InvalidDocument(
                    f"text artifact {file.name} exceeds max_text_bytes"
                )
            total_text += size
        else:
            if size > proc["max_artifact_blob_bytes"]:
                raise InvalidDocument(
                    f"binary artifact {file.name} exceeds max_artifact_blob_bytes"
                )
            total_blob += size
    if total_text > proc["max_manifest_text_bytes"]:
        raise InvalidDocument("total text exceeds max_manifest_text_bytes")
    if total_blob > limits["max_output_bytes"]:
        raise InvalidDocument("total binary output exceeds max_output_bytes")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(
            "usage: python -m letfs_ingest.convert <source> <media_type> <output>"
        )
    convert(Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), load())
