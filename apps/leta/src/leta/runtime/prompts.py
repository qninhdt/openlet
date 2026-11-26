from __future__ import annotations

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
