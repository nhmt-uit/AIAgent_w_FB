"""
Prompt loader — the mechanism that makes "editing a skill file" equal to
"retraining the agent", with no separate reload step.

How it works: every agent run calls load_agent_prompt(agent_name) here,
which reads the agent's spec file (docs/agents/<agent_name>.md) AND every
skill file it lists in that spec's `reads_before_acting` frontmatter field,
straight from disk, and concatenates them into one system prompt. Because
this reads from disk on every call (nothing is cached at import time),
editing any of those .md files takes effect on the very next run — that is
the entire "make the agent learn again" mechanism described in
README.md section 4 and 6.

If you add a new skill file, just add its filename to the relevant agent's
`reads_before_acting` list in docs/agents/<agent_name>.md — you do not need
to touch this module.
"""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = PROJECT_ROOT / "docs" / "agents"
SKILLS_DIR = PROJECT_ROOT / "docs" / "skills"

# Minimal YAML frontmatter reader — avoids adding a PyYAML dependency for
# just this. Frontmatter in this project is always simple `key: value` or
# `key: [a, b, c]` lines between two `---` markers.
def _parse_frontmatter(text: str) -> dict:
    """
    Minimal YAML-ish frontmatter reader. Supports both list styles used in
    docs/agents/*.md:
        reads_before_acting: [a.md, b.md]
    and:
        reads_before_acting:
          - a.md
          - b.md
    """
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}
    raw = text[4:end]
    lines = raw.splitlines()

    result: dict[str, str | list[str]] = {}
    current_list_key: str | None = None

    for line in lines:
        stripped = line.strip()

        # Continuation of a multi-line "- item" list under the previous key
        if current_list_key is not None and stripped.startswith("- "):
            result.setdefault(current_list_key, [])
            result[current_list_key].append(stripped[2:].strip())  # type: ignore[union-attr]
            continue
        else:
            current_list_key = None

        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()

        if value == "":
            # Might be the start of a multi-line list on following lines.
            current_list_key = key
            continue
        if value.startswith("[") and value.endswith("]"):
            items = [v.strip() for v in value[1:-1].split(",") if v.strip()]
            result[key] = items
        else:
            result[key] = value

    return result


def _read(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(
            f"Expected doc not found: {path}. Every agent/skill file referenced in "
            f"frontmatter must exist — see docs/architecture.md."
        )
    return path.read_text(encoding="utf-8")


def load_agent_prompt(agent_name: str) -> str:
    """
    Build the full system prompt for an agent by reading its spec file plus
    every skill file it declares under `reads_before_acting`, fresh from
    disk. `agent_name` matches a filename stem under docs/agents/, e.g.
    "human-bot-executor", "content-strategist", "safety-monitor".
    """
    agent_path = AGENTS_DIR / f"{agent_name}.md"
    agent_text = _read(agent_path)
    frontmatter = _parse_frontmatter(agent_text)
    skill_files = frontmatter.get("reads_before_acting", [])
    if isinstance(skill_files, str):
        skill_files = [skill_files]

    sections = [f"# Agent spec: {agent_name}\n\n{agent_text}"]
    for skill_ref in skill_files:
        # frontmatter lists these as "skills/foo.md" or "foo.md" — normalize.
        skill_filename = Path(skill_ref).name
        skill_path = SKILLS_DIR / skill_filename
        sections.append(f"# Skill: {skill_filename}\n\n{_read(skill_path)}")

    return "\n\n---\n\n".join(sections)


def list_available_agents() -> list[str]:
    return sorted(p.stem for p in AGENTS_DIR.glob("*.md"))


if __name__ == "__main__":
    # Quick manual check: `python3 -m human_bot.prompt_loader human-bot-executor`
    import sys

    name = sys.argv[1] if len(sys.argv) > 1 else "human-bot-executor"
    print(f"Available agents: {list_available_agents()}\n")
    print(load_agent_prompt(name))
