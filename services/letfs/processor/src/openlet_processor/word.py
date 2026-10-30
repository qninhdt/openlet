from docling.backend.msword_backend import MsWordDocumentBackend


class WordBackend(MsWordDocumentBackend):
    def _is_rich_table_cell(self, cell):
        # Plain cell.text omits content controls; Docling's rich walker retains them.
        return cell._tc.find(
            ".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}sdt"
        ) is not None or super()._is_rich_table_cell(cell)
