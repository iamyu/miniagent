"""Skills loader - inspired by NanoBot's SkillsLoader, simplified."""

import re
from pathlib import Path
from typing import Any

import yaml


# Match YAML frontmatter: ---\n...\n--- (supports CRLF)
_FRONTMATTER_RE = re.compile(
    r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?",
    re.DOTALL,
)


class Skill:
    """A single skill with metadata and content."""

    def __init__(self, name: str, path: Path, content: str, metadata: dict[str, Any]):
        self.name = name
        self.path = path
        self.raw_content = content
        self.metadata = metadata
        self.description = metadata.get("description", name)
        self.triggers: list[str] = metadata.get("triggers", [])
        self.always = metadata.get("always", False)
        # Content with frontmatter stripped
        self.content = self._strip_frontmatter(content)

    @staticmethod
    def _strip_frontmatter(content: str) -> str:
        """Remove YAML frontmatter from markdown content."""
        if not content.startswith("---"):
            return content
        match = _FRONTMATTER_RE.match(content)
        if match:
            return content[match.end():].strip()
        return content


class SkillsLoader:
    """Load and manage skills from the skills directory.

    Each skill lives in: <skills_dir>/<skill_name>/SKILL.md
    """

    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self._cache: dict[str, Skill] = {}
        if skills_dir.exists():
            self._load_all()

    def _load_all(self) -> None:
        """Scan skills directory and load all skills."""
        if not self.skills_dir.exists():
            return
        for skill_dir in sorted(self.skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue
            name = skill_dir.name
            self._load_one(name, skill_file)

    def _load_one(self, name: str, path: Path) -> Skill | None:
        """Load a single skill from file."""
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

        metadata = self._parse_frontmatter(content)
        skill = Skill(name=name, path=path, content=content, metadata=metadata)
        self._cache[name] = skill
        return skill

    def _parse_frontmatter(self, content: str) -> dict[str, Any]:
        """Parse YAML frontmatter from markdown content."""
        if not content.startswith("---"):
            return {}
        match = _FRONTMATTER_RE.match(content)
        if not match:
            return {}
        try:
            parsed = yaml.safe_load(match.group(1))
            if isinstance(parsed, dict):
                return {str(k): v for k, v in parsed.items()}
        except yaml.YAMLError:
            pass
        return {}

    def get(self, name: str) -> Skill | None:
        """Get a skill by name."""
        if name in self._cache:
            return self._cache[name]
        # Try loading from disk (in case added after startup)
        path = self.skills_dir / name / "SKILL.md"
        if path.exists():
            return self._load_one(name, path)
        return None

    def list_all(self) -> list[Skill]:
        """List all available skills."""
        # Refresh from disk
        self._load_all()
        return list(self._cache.values())

    def match_triggers(self, user_input: str) -> list[Skill]:
        """Match skills whose triggers appear in user input.

        Returns skills sorted by number of triggered keywords (most matches first).
        """
        input_lower = user_input.lower()
        scored: list[tuple[int, Skill]] = []
        for skill in self._cache.values():
            if skill.always:
                scored.append((999, skill))
                continue
            if not skill.triggers:
                continue
            match_count = sum(
                1 for trigger in skill.triggers
                if trigger.lower() in input_lower
            )
            if match_count > 0:
                scored.append((match_count, skill))

        # Sort by match count descending
        scored.sort(key=lambda x: x[0], reverse=True)
        return [skill for _, skill in scored]

    def get_always_skills(self) -> list[Skill]:
        """Get skills marked as always=true."""
        return [s for s in self._cache.values() if s.always]

    def build_context(self, skills: list[Skill]) -> str:
        """Build formatted skills content for injection into system prompt.

        Args:
            skills: List of Skill objects to include.

        Returns:
            Formatted markdown string with all skill contents,
            including the absolute root directory for each skill.
        """
        if not skills:
            return ""
        parts: list[str] = []
        for s in skills:
            skill_root = s.path.parent  # absolute path to the skill directory
            parts.append(
                f"### Skill: {s.name}\n"
                f"**Skill root directory:** {skill_root}\n"
                f"(All relative paths and any paths referencing other tool ecosystems "
                f"(e.g. .workbuddy/, .claude/) in this skill's instructions "
                f"should be replaced with: {skill_root})\n\n"
                f"{s.content}"
            )
        return "\n\n---\n\n".join(parts)

    def build_summary(self) -> str:
        """Build a summary of all available skills.

        Used to let the LLM know what skills are available.
        """
        skills = self.list_all()
        if not skills:
            return "No skills available."

        lines = []
        for skill in skills:
            trigger_info = ""
            if skill.triggers:
                trigger_info = f" (triggers: {', '.join(skill.triggers)})"
            if skill.always:
                trigger_info = " (always active)"
            lines.append(f"- **{skill.name}** — {skill.description}{trigger_info}")

        return "\n".join(lines)

    def reload(self) -> None:
        """Reload all skills from disk."""
        self._cache.clear()
        self._load_all()
