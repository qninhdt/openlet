"""Jinja2 system-prompt loading, rendering, and version hashing."""

from __future__ import annotations

import hashlib
from functools import lru_cache
from typing import TYPE_CHECKING, Protocol

from jinja2 import Environment, FileSystemLoader

from leta.config import prompts_dir

if TYPE_CHECKING:
    from pathlib import Path

    from leta.config import ToolFlags


class PromptSettingsProtocol(Protocol):
    """Settings slice exposing enabled runtime tool flags."""

    @property
    def tools(self) -> ToolFlags:
        """Feature flags controlling enabled agent tools."""
        ...


class PromptServicesProtocol(Protocol):
    """Service container slice required for prompt rendering."""

    @property
    def settings(self) -> PromptSettingsProtocol:
        """Runtime settings instance."""
        ...


class PromptContext(Protocol):
    """Minimal agent context required to render the system prompt."""

    @property
    def is_root(self) -> bool:
        """Whether this agent is the root Leta."""
        ...

    @property
    def agent_name(self) -> str:
        """Display name of the agent."""
        ...

    @property
    def agent_title(self) -> str:
        """Role title of the agent."""
        ...

    @property
    def handle(self) -> str:
        """Agent handle without prefix."""
        ...

    @property
    def agent_description(self) -> str:
        """Short description of the agent's role."""
        ...

    @property
    def custom_instructions(self) -> str:
        """User- or parent-supplied custom instructions."""
        ...

    @property
    def parent_handle(self) -> str:
        """Parent agent handle for subagents."""
        ...

    @property
    def services(self) -> PromptServicesProtocol:
        """Service container exposing settings."""
        ...


@lru_cache(maxsize=4)
def _jinja_env(root: Path) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(root)),
        autoescape=False,  # noqa: S701  # LLM Markdown/XML prompts, not HTML.
        trim_blocks=True,
        lstrip_blocks=True,
    )


@lru_cache(maxsize=4)
def prompt_version_hash(
    is_root: bool,  # noqa: FBT001  # Positional API used by external callers/tests.
) -> str:
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


def render_system_prompt(rt: PromptContext) -> str:
    """Render the root Leta or subagent Jinja2 system prompt."""
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
