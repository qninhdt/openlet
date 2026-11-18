from docling.backend.mspowerpoint_backend import MsPowerpointDocumentBackend
from docling_core.types.doc.document import DoclingDocument


class Powerpoint(MsPowerpointDocumentBackend):
    def convert(self) -> DoclingDocument:
        # python-pptx omits shapes wrapped in markup compatibility branches.
        supported = {
            "http://schemas.microsoft.com/office/drawing/2010/main",
            "http://schemas.openxmlformats.org/officeDocument/2006/math",
        }
        if self.pptx_obj is not None:
            for slide in self.pptx_obj.slides:
                for wrapper in slide.element.xpath(
                    ".//*[local-name()='AlternateContent']"
                ):
                    parent = wrapper.getparent()
                    if parent.tag.rsplit("}", 1)[-1] not in {"spTree", "grpSp"}:
                        continue
                    branches = list(wrapper)
                    selected = next(
                        (
                            branch
                            for branch in branches
                            if branch.tag.endswith("}Choice")
                            and branch.get("Requires")
                            and all(
                                branch.nsmap.get(prefix) in supported
                                for prefix in branch.get("Requires").split()
                            )
                        ),
                        None,
                    )
                    if selected is None:
                        selected = next(
                            (
                                branch
                                for branch in branches
                                if branch.tag.endswith("}Fallback")
                            ),
                            None,
                        )
                    if selected is None:
                        raise ValueError(
                            "PowerPoint shape has no supported compatibility branch"
                        )
                    for element in list(selected):
                        wrapper.addprevious(element)
                    parent.remove(wrapper)
        return super().convert()
