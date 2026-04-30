import os
import re
from pathlib import settings
from django.conf import settings

def parse_skill_md(file_path):
    """Parses SKILL.md file and extracts YAML-like metadata and content."""
    content = ""
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    
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

def discover_skills():
    """Scans config/ai/skills/ for available skills."""
    skills_dir = os.path.join(settings.BASE_DIR, 'config', 'ai', 'skills')
    catalog = []
    
    if not os.path.exists(skills_dir):
        return catalog

    for item in os.listdir(skills_dir):
        item_path = os.path.join(skills_dir, item)
        if os.path.isdir(item_path):
            skill_md = os.path.join(item_path, 'SKILL.md')
            if os.path.exists(skill_md):
                metadata, _ = parse_skill_md(skill_md)
                if metadata:
                    metadata['id'] = item  # folder name as id
                    catalog.append(metadata)
    return catalog

def load_skill_content(skill_id):
    """Returns the full instructions for a specific skill."""
    skill_path = os.path.join(settings.BASE_DIR, 'config', 'ai', 'skills', skill_id, 'SKILL.md')
    if os.path.exists(skill_path):
        _, body = parse_skill_md(skill_path)
        return body
    return None
