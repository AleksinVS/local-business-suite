import re
from pathlib import Path

from django.conf import settings


# Strict allow-list for skill identifiers to prevent path traversal.
_SKILL_ID_RE = re.compile(r"^[a-z0-9_-]+$")


def parse_skill_md(file_path):
    """Parses SKILL.md file and extracts YAML-like metadata and content."""
    content = ""
    file_path = Path(file_path)
    if file_path.exists():
        content = file_path.read_text(encoding="utf-8")

    metadata = {}
    # Simple regex to extract metadata between ---
    match = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)', content, re.DOTALL)
    if match:
        meta_section = match.group(1)
        body_section = match.group(2)
        for line in meta_section.split('\n'):
            if ':' in line:
                key, value = line.split(':', 1)
                metadata[key.strip()] = value.strip().strip('"')
        return metadata, body_section
    return {}, content


def _skills_dir():
    runtime_dir = settings.RUNTIME_CONTRACTS_DIR / "ai" / "skills"
    if runtime_dir.exists():
        return runtime_dir
    return settings.DEFAULT_CONTRACTS_DIR / "ai" / "skills"


def discover_skills():
    """Scans AI contract skill directories for available skills."""
    skills_dir = _skills_dir()
    catalog = []

    if not skills_dir.exists():
        return catalog

    for item_path in sorted(skills_dir.iterdir()):
        if item_path.is_dir():
            skill_md = item_path / "SKILL.md"
            if skill_md.exists():
                metadata, _ = parse_skill_md(skill_md)
                if metadata:
                    metadata["id"] = item_path.name
                    catalog.append(metadata)
    return catalog


def load_skill_content(skill_id):
    """Returns the full instructions for a specific skill."""
    if not _SKILL_ID_RE.match(skill_id):
        return None
    skill_path = _skills_dir() / skill_id / "SKILL.md"
    if skill_path.exists():
        _, body = parse_skill_md(skill_path)
        return body
    return None
