const fs = require('fs');
const path = require('path');

const EXCLUDED = [
  '.git', 'node_modules', '__pycache__', '.venv', '.tmp',
  '.playwright-mcp', 'staticfiles', 'media', 'db', 'logs',
  'VOB3', '.pytest_cache', '.claude', '.codex', '.gemini',
  '.github', 'docker'
];
const MAX_DEPTH = 3;
const OUTPUT_FILE = 'PROJECT_STRUCTURE.yaml';

function getDescriptions(dirPath) {
  const descs = {};
  const descPath = path.join(dirPath, '.desc.json');
  if (fs.existsSync(descPath)) {
    try {
      Object.assign(descs, JSON.parse(fs.readFileSync(descPath, 'utf8')));
    } catch (e) {
      console.warn(`Warning: Failed to parse ${descPath}: ${e.message}`);
    }
  }
  return descs;
}

function buildTree(dirPath, depth = 0) {
  if (depth > MAX_DEPTH) return { node: "directory...", hasDescribedContent: false };

  const descs = getDescriptions(dirPath);
  const result = { _isDir: true, desc: descs['.'] || null, children: {} };
  let hasDescribedContent = result.desc !== null;

  let entries;
  try {
    entries = fs.readdirSync(dirPath, { withFileTypes: true })
      .filter(e => !EXCLUDED.includes(e.name) && !e.name.startsWith('.desc'))
      .sort((a, b) => a.isDirectory() === b.isDirectory() ? a.name.localeCompare(b.name) : (a.isDirectory() ? -1 : 1));
  } catch (e) {
    return { node: result, hasDescribedContent };
  }

  for (const entry of entries) {
    const entryDesc = descs[entry.name];
    const fullPath = path.join(dirPath, entry.name);

    if (entry.isDirectory()) {
      const child = buildTree(fullPath, depth + 1);
      if (child.hasDescribedContent || entryDesc) {
        if (entryDesc && !child.node.desc) child.node.desc = entryDesc;
        result.children[entry.name] = child.node;
        hasDescribedContent = true;
      }
    } else if (entryDesc) {
      result.children[entry.name] = { _isDir: false, desc: entryDesc };
      hasDescribedContent = true;
    }
  }
  return { node: result, hasDescribedContent };
}

function toYaml(obj, indent = 0) {
  let yaml = '';
  const spaces = '  '.repeat(indent);
  for (const [key, node] of Object.entries(obj)) {
    const desc = node.desc ? ` # ${node.desc.replace(/\n/g, ' ')}` : '';
    if (node._isDir) {
      const hasChildren = node.children && Object.keys(node.children).length > 0;
      yaml += `${spaces}${key}:${hasChildren ? desc + '\n' + toYaml(node.children, indent + 1) : ' directory...' + desc + '\n'}`;
    } else {
      yaml += `${spaces}${key}: file${desc}\n`;
    }
  }
  return yaml;
}

const tree = buildTree(process.cwd());
const header = "# PROJECT STRUCTURE\n# AUTO-GENERATED - DO NOT EDIT\n\n";
fs.writeFileSync(OUTPUT_FILE, header + toYaml(tree.node.children));
console.log(`Generated ${OUTPUT_FILE}`);
