"""Pinned command behavior with the accepted candidate-superset hook contract.

Native RPC correctness is tested separately against real PostgreSQL/SpiceDB.
This fixture isolates Mirage's command parsing/final matching from that backend.
"""

import pytest
from mirage import Workspace
from mirage.types import MountMode
from mirage.utils.key_prefix import mounted_path
from mirage.vfs import RAMVFS


class CandidateFixture(RAMVFS):
    def __init__(self, enabled, incomplete):
        super().__init__()
        self.enabled = enabled
        self.incomplete = incomplete
        self.calls = []

    async def files_containing(self, path, text, *, whole_word, ignore_case):
        self.calls.append(("files", text, whole_word, ignore_case))
        if not self.enabled or self.incomplete:
            return None
        # Deliberately include a false positive. Mirage must perform final matching.
        names = ["a.txt", "extra.txt"]
        if text != "needle" or ignore_case:
            names.append("unicode.txt")
        return [mounted_path(path, "/" + name) for name in names]

    async def lines_containing(self, path, text, *, ignore_case):
        self.calls.append(("lines", text, ignore_case))
        if not self.enabled or self.incomplete:
            return None
        if path.vfs_path.strip("/") == "a.txt" and text == "needle" and not ignore_case:
            # Preserve independently fixed bytes, including the final fragment.
            return b"needle twice needle\r\nlast needle"
        return await super().read(path)


@pytest.mark.parametrize("incomplete", [False, True])
async def test_mirage_literal_hooks_preserve_real_command_results(incomplete):
    commands = [
        "grep -r -F needle /home",
        "rg needle /home",
        "rg -n needle /home",
        "rg -A 1 needle /home",
        "rg -w needle /home",
        "rg -i needle /home",
        "rg -i k /home",
        "rg -i s /home",
        "rg -i i /home",
        "rg 'needle.*needle' /home",
        "rg -F '%_' /home",
        "rg 'absent-pattern' /home",
    ]
    outputs = []
    for enabled in (False, True):
        backend = CandidateFixture(enabled, incomplete)
        workspace = Workspace({"/home": (backend, MountMode.WRITE)}, network=False)
        try:
            workspace.create_session("search-compatibility")
            for name, body in {
                "a.txt": "before\nneedle twice needle\r\nlast needle",
                "extra.txt": "false positive\nliteral %_\\\n",
                "unicode.txt": "K K k\nſ S s\nİ i ı\nmixed NeedLe\n",
            }.items():
                result = await workspace.tools.write("/home/" + name, body)
                assert not result.is_error, result.text
            output = []
            for command in commands:
                result = await workspace.tools.shell(command)
                output.append((result.is_error, result.text))
            assert "needle twice needle" in output[0][1]
            assert "NeedLe" in output[5][1]
            assert backend.calls, "commands must dispatch candidate hooks"
            assert any(call[0] == "lines" for call in backend.calls)
            outputs.append(output)
        finally:
            await workspace.close()
    assert outputs[0] == outputs[1], "hooks must preserve bytes, paths and ordering"
