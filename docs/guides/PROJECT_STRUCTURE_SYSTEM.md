# Инструкция: Система автоматического сбора структуры проекта (PROJECT_STRUCTURE.yaml)

Эта система предназначена для создания и поддержания актуальной «карты» репозитория, которую ИИ-агенты могут использовать для быстрого ориентирования в проекте. Она объединяет физическую структуру файлов с семантическими описаниями.

## Компоненты системы

### 1. Файлы описаний (`.desc.json`)
В каждой значимой директории проекта создается файл `.desc.json`. Это простой JSON-объект, где:
- Ключ `.` — описание текущей директории.
- Остальные ключи — имена файлов или поддиректорий с их кратким описанием.

Пример `.desc.json`:
```json
{
  ".": "Ядро бизнес-логики",
  "auth/": "Сервисы аутентификации",
  "api-client.ts": "Клиент для работы с внешним API"
}
```

### 2. Скрипт генератора (`generate-structure.js`)
Node.js скрипт, который рекурсивно обходит проект и собирает данные.

**Основные функции скрипта:**
- **Лимит глубины:** Ограничивает обход (например, до 3 уровней), чтобы файл не стал слишком огромным.
- **Исключения:** Игнорирует служебные папки (`node_modules`, `.git`, `.next`, `dist`).
- **Строгий фильтр:** В итоговый YAML попадают **только те файлы и папки, для которых найдено описание**. Это позволяет скрыть мелкие детали и оставить только архитектурно важные элементы.
- **Источники данных:** 
    1. Ключи из `.desc.json`.
    2. Поле `description` из `package.json` (как запасной вариант для папок).
- **Форматирование:** Генерирует YAML-подобную структуру, где описания добавлены в виде комментариев после `file` или `directory...`.

### 3. Итоговый артефакт (`PROJECT_STRUCTURE.yaml`)
Файл в корне проекта, который является «единственным источником истины» (SSOT) для структуры. Агенты должны читать его в начале сессии.

---

## Как внедрить систему в новый проект (Инструкция для ИИ-агента)

Если вы хотите внедрить такую же систему в другом проекте, выполните следующие шаги:

### Шаг 1: Создайте скрипт генерации
Разместите скрипт в `scripts/dev/generate-structure.js`. Ниже приведен эталонный код:

```javascript
const fs = require('fs');
const path = require('path');

const EXCLUDED = ['.git', 'node_modules', 'dist', '.tmp']; // Настройте под проект
const MAX_DEPTH = 3;
const OUTPUT_FILE = 'PROJECT_STRUCTURE.yaml';

function getDescriptions(dirPath) {
  const descs = {};
  const pkgPath = path.join(dirPath, 'package.json');
  if (fs.existsSync(pkgPath)) {
    try {
      const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'));
      if (pkg.description) descs['.'] = pkg.description;
    } catch (e) {}
  }
  const descPath = path.join(dirPath, '.desc.json');
  if (fs.existsSync(descPath)) {
    try {
      Object.assign(descs, JSON.parse(fs.readFileSync(descPath, 'utf8')));
    } catch (e) {}
  }
  return descs;
}

function buildTree(dirPath, depth = 0) {
  if (depth > MAX_DEPTH) return { node: "directory...", hasDescribedContent: false };

  const descs = getDescriptions(dirPath);
  const result = { _isDir: true, desc: descs['.'] || null, children: {} };
  let hasDescribedContent = result.desc !== null;

  const entries = fs.readdirSync(dirPath, { withFileTypes: true })
    .sort((a, b) => a.isDirectory() === b.isDirectory() ? a.name.localeCompare(b.name) : (a.isDirectory() ? -1 : 1));

  for (const entry of entries) {
    if (EXCLUDED.includes(entry.name) || entry.name.startsWith('.desc')) continue;
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
    const desc = node.desc ? ` # ${node.desc.replace(/\\n/g, ' ')}` : '';
    if (node._isDir) {
      const hasChildren = node.children && Object.keys(node.children).length > 0;
      yaml += `${spaces}${key}:${hasChildren ? desc + '\\n' + toYaml(node.children, indent + 1) : ' directory...' + desc + '\\n'}`;
    } else {
      yaml += `${spaces}${key}: file${desc}\\n`;
    }
  }
  return yaml;
}

const tree = buildTree(process.cwd());
const header = "# PROJECT STRUCTURE\\n# AUTO-GENERATED - DO NOT EDIT\\n\\n";
fs.writeFileSync(OUTPUT_FILE, header + toYaml(tree.node.children));
```

### Шаг 2: Создайте корневой `.desc.json`
Опишите основные папки и файлы в корне проекта.

### Шаг 3: Добавьте команду в `package.json`
```json
"scripts": {
  "gen:struct": "node scripts/dev/generate-structure.js"
}
```

### Шаг 4: Настройте правила для агентов
Добавьте в `AGENTS.md`, `GEMINI.md`, `CLAUDE.md` или `README.md` требование:
> "При любом изменении структуры (добавлении папок/важных файлов) необходимо обновить соответствующие `.desc.json` и запустить `npm run gen:struct`."

## Преимущества
1. **Чистый контекст:** Агент видит только то, что вы посчитали нужным описать.
2. **Семантика:** Вместо простого дерева файлов агент получает карту смыслов.
3. **Автоматизация:** Структура всегда актуальна, если следовать правилу обновления.
