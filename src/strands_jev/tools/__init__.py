"""The tools, by group. ``ALL_TOOLS`` is every tool; hand it to ``Agent(tools=ALL_TOOLS)``."""

from __future__ import annotations

from ._common import JEV_STATE_KEY, configure
from .cookbooks import COOKBOOK_TOOLS
from .patterns import PATTERN_TOOLS
from .primitives import PRIMITIVE_TOOLS

ALL_TOOLS = [*PRIMITIVE_TOOLS, *PATTERN_TOOLS, *COOKBOOK_TOOLS]

__all__ = ["ALL_TOOLS", "COOKBOOK_TOOLS", "JEV_STATE_KEY", "PATTERN_TOOLS", "PRIMITIVE_TOOLS", "configure"]
