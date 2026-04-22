from __future__ import annotations

import logging
from pathlib import Path

import frontmatter
from copilot.session import CustomAgentConfig

logger = logging.getLogger(__name__)

AGENTS_DIR = Path(__file__).parents[3] / ".github" / "agents"

# Filenames (not paths) to skip during discovery
EXCLUDED_AGENTS: frozenset[str] = frozenset({"tony.agent.md", "sem_anal.agent.md","sem_anal.md"})


def load_agent_configs(extra_exclude: set[str] | None = None) -> list[CustomAgentConfig]:
    """Load all .agent.md files from .github/agents/ as CustomAgentConfig dicts."""
    excluded = EXCLUDED_AGENTS | (extra_exclude or set())
    configs: list[CustomAgentConfig] = []

    for path in sorted(AGENTS_DIR.glob("*.agent.md")):
        if path.name in excluded:
            logger.debug(f"skipping excluded agent: {path.name}")
            continue

        try:
            post = frontmatter.load(str(path))
        except Exception:
            logger.warning(f"failed to parse agent file: {path.name}", exc_info=True)
            continue

        name: str = post.metadata.get("name", path.stem)
        description: str = post.metadata.get("description", "")
        prompt: str = post.content.strip()
        raw_tools = post.metadata.get("tools")

        config: CustomAgentConfig = {
            "name": name,
            "description": description,
            "prompt": prompt,
        }
        if raw_tools:
            config["tools"] = [str(t) for t in raw_tools]

        configs.append(config)
        logger.debug(f"loaded agent: {name!r} from {path.name}")

    logger.info(f"loaded {len(configs)} custom agents from {AGENTS_DIR}")
    return configs
