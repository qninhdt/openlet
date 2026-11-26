from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from ..config import prompts_dir
from .state import RuntimeContext


@lru_cache(maxsize=4)
def _jinja_env(root: Path) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(root)),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )


@lru_cache(maxsize=4)
def prompt_version_hash(is_root: bool) -> str:
    """Short content hash of Git-tracked Jinja2 prompt sources for trace attribution."""
    root = prompts_dir()
    h = hashlib.sha256()
    for name in ("common.j2", "leta.j2" if is_root else "leti.j2"):
        path = root / name
        if path.is_file():
            h.update(name.encode("utf-8"))
            h.update(b"\0")
            h.update(path.read_bytes())
    return h.hexdigest()[:12]


def render_system_prompt(rt: RuntimeContext) -> str:
    env = _jinja_env(prompts_dir())
    template_name = "leta.j2" if rt.is_root else "leti.j2"
    template = env.get_template(template_name)
    return template.render(
        tools=rt.services.settings.tools,
        agent_name=rt.agent_name,
        agent_title=rt.agent_title,
        agent_handle=rt.handle,
        agent_description=rt.agent_description,
        agent_instructions=rt.custom_instructions or "(No additional instructions.)",
        parent_handle=rt.parent_handle,
    ).strip()
