"""RankStein — autonomous AI SEO content engine.

This package is the canonical home for the next iteration of RankStein.
Today it only ships ``rankstein.config`` (a unified, validated settings layer
that supersedes the dual systems in ``backend/core/config.py`` and
``pinterest_automation/config.py``). Other modules (``rankstein.mcp.tools``,
``rankstein.cli``, etc.) will land here as the existing monolithic
``rankstein_mcp_server.py`` is split.

Adding the package alone does not change runtime behaviour; existing imports
keep working until callers migrate to ``rankstein.config``.
"""

__version__ = "0.1.0"
