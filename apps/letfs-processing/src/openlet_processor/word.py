from docling.backend.msword_backend import MsWordDocumentBackend


class WordBackend(MsWordDocumentBackend):
    def _is_rich_table_cell(self, cell):
        # Plain cell.text omits wrapped runs; Docling's rich walker retains them.
        return bool(
            cell._tc.xpath(".//w:sdt | .//w:ins")
        ) or super()._is_rich_table_cell(cell)
