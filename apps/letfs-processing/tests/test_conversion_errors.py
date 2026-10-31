import pytest

from openlet_processor import convert_child


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (MemoryError(), 3),
        (RuntimeError("DefaultCPUAllocator: can't allocate memory: allocation"), 3),
        (RuntimeError("ONNXRuntimeError: std::bad_alloc"), 3),
        (ValueError("Decoded image exceeds size limit of 20971520 bytes."), 3),
        (ValueError("invalid document"), 2),
        (RuntimeError("unexpected converter defect"), 4),
    ],
)
def test_converter_failure_classification(
    tmp_path, monkeypatch, capsys, error, expected
):
    def convert(*args):
        raise error

    monkeypatch.setattr(convert_child, "convert", convert)
    monkeypatch.setattr(convert_child.resource, "setrlimit", lambda *args: None)
    monkeypatch.setattr(convert_child.os, "umask", lambda *args: 0)
    monkeypatch.setattr(
        convert_child.sys,
        "argv",
        ["converter", "source.pdf", str(tmp_path), "pdf", "models", "512", "10000"],
    )
    assert convert_child.main() == expected
    diagnostic = capsys.readouterr().err
    assert f"exit={expected}" in diagnostic
    assert type(error).__name__ in diagnostic
    if str(error):
        assert str(error) not in diagnostic
