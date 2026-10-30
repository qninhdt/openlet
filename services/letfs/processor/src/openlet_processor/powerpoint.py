from docling.backend.mspowerpoint_backend import MsPowerpointDocumentBackend

MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
PRESENTATION = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
SUPPORTED_CHOICES = {
    "http://schemas.microsoft.com/office/drawing/2010/main",
    "http://schemas.openxmlformats.org/officeDocument/2006/math",
}


class PowerpointBackend(MsPowerpointDocumentBackend):
    def convert(self):
        # python-pptx skips shape-level AlternateContent; Docling handles inline math.
        if self.pptx_obj is not None:
            for slide in self.pptx_obj.slides:
                for alternate in list(slide._element.iter(MC + "AlternateContent")):
                    parent = alternate.getparent()
                    if parent.tag not in {
                        PRESENTATION + "spTree",
                        PRESENTATION + "grpSp",
                    }:
                        continue
                    branch = alternate.find(MC + "Fallback")
                    for choice in alternate.findall(MC + "Choice"):
                        required = choice.get("Requires", "").split()
                        if required and all(
                            choice.nsmap.get(prefix) in SUPPORTED_CHOICES
                            for prefix in required
                        ):
                            branch = choice
                            break
                    if branch is None:
                        raise ValueError("unsupported PowerPoint compatibility branch")
                    position = parent.index(alternate)
                    for child in list(branch):
                        parent.insert(position, child)
                        position += 1
                    parent.remove(alternate)
        return super().convert()
