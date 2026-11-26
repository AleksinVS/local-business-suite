"""Direct OKF editing in an authorized bundle, with publication at one Git revision."""

import hashlib
import json
import os
import posixpath
import re
import stat
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from django.core.exceptions import PermissionDenied, ValidationError

from .knowledge_files import KnowledgeFile, knowledge_repo_lock, knowledge_repo_root
from .wiki_config import wiki_article_id
from .wiki_reconcile import parse_wiki_frontmatter, read_wiki_snapshot, wiki_blob, wiki_head, wiki_tree


class WikiEditConflict(ValidationError):
    """The caller must reread the published version or resolve overlapping work."""


_ENTRY = re.compile(r"^[*-]\s+\[[^\]]*\]\(([^)\s]+)\)(?:\s*-.*)?$")
_PAGE_LINK = re.compile(r"\[[^\]\n]*\]\(([^)\s#:]+\.md)(?:#[^)\s]*)?\)")
_EDITABLE = {'title', 'description', 'sources', 'source_refs', 'confirmation_state', 'verified'}
_CREATION = _EDITABLE | {'type', 'knowledge_id', 'id', 'status', 'lifecycle', 'sensitivity'}
_MISSING = object()


def _relative_article(path):
    if not isinstance(path, str) or not re.fullmatch(r'[\w./-]+\.md', path):
        raise ValidationError('Invalid wiki article path.')
    parts = path.split('/')
    if any(not part or part.startswith('.') or part.casefold() in {'raw', 'schemas'} for part in parts):
        raise ValidationError('Reserved wiki path.')
    if parts[-1].casefold() in {'index.md', 'log.md'}:
        raise ValidationError('Wiki navigation is maintained by the host.')
    return path


def read_wiki_files(*, bundle, paths=None, revision=None, can_read):
    """Return exact published author text only for articles allowed by current policy."""
    root = knowledge_repo_root()
    head = wiki_head(root)
    if revision is not None and revision != head:
        raise WikiEditConflict('Wiki revision has changed.')
    snapshot = read_wiki_snapshot(bundle, head)
    requested = None if paths is None else {_relative_article(p) for p in paths}
    articles = []
    for note in snapshot.notes.values():
        path = PurePosixPath(note.path).relative_to(bundle.path).as_posix()
        if requested is not None and path not in requested:
            continue
        if can_read(note.knowledge_id, note.metadata):
            articles.append({'path': path, 'knowledge_id': note.knowledge_id,
                             'markdown': wiki_blob(root, note.blob_oid).decode('utf-8')})
    if requested is not None and len(articles) != len(requested):
        raise PermissionDenied('Requested wiki article is unavailable.')
    if wiki_head(root) != head:
        raise WikiEditConflict('Wiki revision moved while reading.')
    return {'revision': head, 'articles': sorted(articles, key=lambda article: article['path'])}


def _document(markdown):
    if not isinstance(markdown, str) or not markdown or '\x00' in markdown:
        raise ValidationError('A wiki article must be UTF-8 Markdown.')
    meta, body = parse_wiki_frontmatter(markdown.encode('utf-8'))
    note = KnowledgeFile(metadata=meta, body=body)
    if meta.get('type') != 'Note' or not note.body or any(
        not isinstance(meta.get(key), str) or not meta[key].strip() for key in ('title', 'description')
    ):
        raise ValidationError('An OKF Note needs a title, description and body.')
    refs = meta.get('source_refs') or meta.get('sources')
    if not isinstance(refs, list) or not refs:
        raise ValidationError('Wiki article needs a verifiable source.')
    return note


def _validate_edit(bundle, previous, note):
    meta = note.metadata
    if previous is not None and previous.metadata == meta and previous.body == note.body:
        return  # A pure relocation keeps the exact editorial verification.
    if previous is None:
        if (set(meta) - _CREATION or not meta.get('knowledge_id')
                or meta.get('lifecycle', 'current') != 'current'
                or meta.get('status', 'stable') not in ('stable', 'draft')
                or meta.get('sensitivity', bundle.sensitivity) != bundle.sensitivity):
            raise ValidationError('Invalid identity, lifecycle or protected metadata for a new wiki article.')
    else:
        old = previous.metadata
        if any(old.get(key, _MISSING) != meta.get(key, _MISSING) for key in (old.keys() | meta.keys()) - _EDITABLE):
            raise ValidationError('Protected OKF identity, status or metadata changed.')
    if meta.get('confirmation_state', 'working') not in ('working', 'needs_confirmation') or meta.get('verified') is not None:
        raise ValidationError('A changed article needs a fresh human confirmation. Remove the previous verification.')


def _git(root, *args, data=None, env=None):
    result = subprocess.run(['git', '-C', str(root), '--literal-pathspecs', '--no-replace-objects',
                             '-c', 'core.hooksPath=' + os.devnull, *args],
                            input=data, capture_output=True, env=env, check=False)
    if result.returncode:
        # Git's stderr may name unrelated private files. Do not return it to an agent.
        raise WikiEditConflict('Git could not complete the isolated wiki operation.')
    return result.stdout


def _nav_entry(title, link, description):
    title = ' '.join(title.split()).replace('[', '(').replace(']', ')')
    return f"* [{title}]({link}) - {' '.join(description.split())}"


def _index_text(original, folder, notes, subfolders):
    lines = (original or ('---\nokf_version: "0.2"\n---\n' if folder == '.' else '')).splitlines()
    for heading, changes in [('# Subdirectories', subfolders), ('# Notes', notes)]:
        pending = dict(changes)
        edited = []
        for line in lines:
            match = _ENTRY.match(line.strip())
            if match and match[1] in pending:
                replacement = pending.pop(match[1])
                if replacement:
                    edited.append(replacement)
            else:
                edited.append(line)
        lines = edited
        new = [entry for _, entry in sorted(pending.items()) if entry]
        if new:
            if heading not in lines:
                lines.extend(['', heading, ''])
            start = lines.index(heading) + 1
            end = next((i for i in range(start, len(lines)) if lines[i].startswith('#')), len(lines))
            lines[end:end] = [*new, '']
    return '\n'.join(lines).strip() + '\n'


def _navigation(changes, documents, load):
    folder_entries = {}
    child_entries = {}
    for path in changes:
        folder, name = posixpath.split(path)
        folder = folder or '.'
        note = documents.get(path)
        entry = _nav_entry(note.metadata['title'], name, note.metadata['description']) if note else None
        folder_entries.setdefault(folder, {})[name] = entry
        while folder != '.':
            parent, name = posixpath.split(folder)
            parent = parent or '.'
            link = f'{name}/index.md'
            parent_index = load(posixpath.normpath(posixpath.join(parent, 'index.md'))) or ''
            if not any((m := _ENTRY.match(line.strip())) and m[1] == link for line in parent_index.splitlines()):
                child_entries.setdefault(parent, {})[link] = _nav_entry(name, link, name.replace('-', ' '))
            folder = parent
    navigation = {}
    for folder in folder_entries.keys() | child_entries.keys():
        path = posixpath.normpath(posixpath.join(folder, 'index.md'))
        original = load(path)
        updated = _index_text(original, folder, folder_entries.get(folder, {}), child_entries.get(folder, {}))
        if original != updated:
            navigation[path] = updated
    lines = (load('log.md') or '# Wiki log').splitlines()
    today = '## ' + datetime.now(UTC).date().isoformat()
    heading = next((i for i, line in enumerate(lines) if line.startswith('## ')), len(lines))
    if heading == len(lines) or lines[heading] != today:
        lines[heading:heading] = ['', today, '']
        heading += 1
    entries = []
    for path in sorted(changes):
        note = documents.get(path)
        if note:
            title = ' '.join(note.metadata['title'].split()).replace('[', '(').replace(']', ')')
            entries.append(f'* **Edit**: [{title}]({path})')
        else:
            entries.append(f'* **Remove**: {path}')
    position = heading + 1
    if lines[position:position+1] == ['']:
        position += 1
    lines[position:position] = entries + ['']
    navigation['log.md'] = '\n'.join(lines).rstrip() + '\n'
    return navigation


def _check_clean_paths(root, head, changes):
    paths = list(changes)
    if (_git(root, 'diff', '--no-ext-diff', '--cached', '--name-only', head, '--', *paths)
            or _git(root, 'diff', '--no-ext-diff', '--name-only', '--', *paths)):
        raise WikiEditConflict('An edited wiki file has unpublished changes.')
    for path in paths:
        target = root / path
        if any(p.is_symlink() for p in (target, *target.parents) if p.is_relative_to(root)):
            raise WikiEditConflict('A wiki file or parent is a symlink.')
        # Compare actual bytes as Git status may ignore an untracked, ignored,
        # skip-worktree or assume-unchanged file owned by another editor.
        entry = _git(root, 'ls-tree', head, '--', path).split(b'\t', 1)[0].split()
        if entry:
            if (entry[:2] != [b'100644', b'blob'] or not target.is_file()
                    or (os.name != 'nt' and target.stat().st_mode & stat.S_IXUSR)
                    or target.read_bytes() != wiki_blob(root, entry[2].decode())):
                raise WikiEditConflict('An edited wiki file has local changes.')
        elif target.exists():
            raise WikiEditConflict('An edited wiki path is occupied.')


def _operation_key(bundle, base, files, read_revisions):
    parts = [bundle.bundle_id, base, files]
    if read_revisions:
        parts.append(read_revisions)
    payload = json.dumps(parts, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(payload).hexdigest()


def _build_commit(root, head, changes, operation_key):
    # No staging or checkout in the canonical worktree until Git's fast-forward.
    with tempfile.TemporaryDirectory() as temp:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(temp) / 'index'))
        _git(root, 'read-tree', head, env=env)
        for path, markdown in sorted(changes.items()):
            if markdown is None:
                _git(root, 'update-index', '--force-remove', '--', path, env=env)
            else:
                oid = _git(root, 'hash-object', '-w', '--stdin', data=markdown.encode()).strip().decode()
                _git(root, 'update-index', '--add', '--cacheinfo', '100644', oid, path, env=env)
        tree = _git(root, 'write-tree', env=env).strip().decode()
        return _git(root, '-c', 'user.name=LBS Wiki', '-c', 'user.email=wiki@local',
                    'commit-tree', tree, '-p', head, '-m', 'Edit wiki articles',
                    '-m', 'LBS-Wiki-Operation: ' + operation_key).strip().decode()


def _check_authorized(authorize):
    if authorize() is False:
        raise PermissionDenied('Wiki editing is not available.')


def _require_ancestor(root, revision, head):
    if (not isinstance(revision, str)
            or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", revision)
            or _git(root, 'cat-file', '-t', revision).strip() != b'commit'):
        raise WikiEditConflict('Wiki base is not an available commit.')
    _git(root, 'merge-base', '--is-ancestor', revision, head)


def _path_entry(root, revision, path):
    # Include mode and kind: a symlink or a directory is not the same as a Note.
    return _git(root, 'ls-tree', '-z', revision, '--', path)


def _already_committed(root, base, head, key):
    if base == head:
        return False
    trailers = _git(root, 'log', '--format=%(trailers:key=LBS-Wiki-Operation,valueonly)',
                    '--fixed-strings', '--grep=LBS-Wiki-Operation: ' + key,
                    f'{base}..{head}').decode().splitlines()
    return key in trailers


def edit_wiki_files(*, bundle, expected_revision, files, authorize, validate_content=None,
                    read_revisions=None):
    """Publish exact article Markdown as a single commit and preserve unrelated edits."""
    if not isinstance(expected_revision, str) or not re.fullmatch('[0-9a-f]{40}|[0-9a-f]{64}', expected_revision):
        raise ValidationError('Expected an immutable Git commit SHA.')
    if not isinstance(files, dict):
        raise ValidationError('Expected wiki files by bundle-relative path.')
    for path, markdown in files.items():
        _relative_article(path)
        if markdown is not None and not isinstance(markdown, str):
            raise ValidationError('Expected complete Markdown or a deletion.')
    if read_revisions is None:
        read_revisions = {}
    if not isinstance(read_revisions, dict):
        raise ValidationError('Expected article paths and their read revisions.')
    for path, revision in read_revisions.items():
        _relative_article(path)
        if not isinstance(revision, str) or not re.fullmatch('[0-9a-f]{40}|[0-9a-f]{64}', revision):
            raise ValidationError('Expected an immutable Git commit SHA for each read article.')
    root = knowledge_repo_root().resolve()
    with knowledge_repo_lock(root) as lock:
        _check_authorized(authorize)
        head = wiki_head(root)
        _require_ancestor(root, expected_revision, head)
        for revision in set(read_revisions.values()) - {expected_revision}:
            _require_ancestor(root, revision, head)
        key = _operation_key(bundle, expected_revision, files, read_revisions)
        # Check a lost-response retry before considering a new edit. A later
        # author may have changed or reverted the target; never replay over them.
        replay = _already_committed(root, expected_revision, head, key)
        for path in files.keys() | read_revisions.keys():
            full = f'{bundle.path}/{path}'
            before = _path_entry(root, read_revisions.get(path, expected_revision), full)
            current = _path_entry(root, head, full)
            if path in read_revisions and not before.startswith(b'100644 blob ') and not before.startswith(b'100755 blob '):
                raise WikiEditConflict('A declared read article is unavailable.')
            if before != current and not replay:
                raise WikiEditConflict('A target or declared basis changed. Review the diff and relevant context.')
        snapshot = read_wiki_snapshot(bundle, head)
        tree = wiki_tree(root, head, bundle.path)

        def load(path):
            oid = tree.get(f'{bundle.path}/{path}')
            return wiki_blob(root, oid).decode('utf-8') if oid else None

        documents = {PurePosixPath(n.path).relative_to(bundle.path).as_posix(): n for n in snapshot.notes.values()}
        if not replay and any(path not in documents for path in read_revisions):
            raise WikiEditConflict('A declared read article is unavailable.')
        for path in files:
            full = f'{bundle.path}/{path}'
            entry = _path_entry(root, head, full)
            if entry and path not in documents:
                raise ValidationError('Only thematic Notes may be edited or removed.')
        changes = {p: text for p, text in files.items() if text != load(p)}
        if replay and changes:
            raise WikiEditConflict('This operation was already applied; a later edit changed its result.')
        if not changes:
            return {'revision': head, 'committed': False, 'changed_paths': []}
        updated = dict(documents)
        for path, markdown in changes.items():
            if path not in documents and f'{bundle.path}/{path}' in tree:
                raise ValidationError('Only thematic Notes may be edited or removed.')
            if markdown is None:
                updated.pop(path, None)
                continue
            note = _document(markdown)
            try:
                kid = wiki_article_id(bundle, note.metadata)
            except ValueError as exc:
                raise ValidationError('Invalid wiki article identity.') from exc
            previous = documents.get(path) or snapshot.notes.get(kid)
            _validate_edit(bundle, previous, note)
            updated[path] = note
        ids = set()
        aliases = set()
        for path, note in updated.items():
            kid = wiki_article_id(bundle, note.metadata)
            native = note.metadata.get('id')
            if kid in ids or (native is not None and native in aliases):
                raise ValidationError('Duplicate wiki article identity.')
            ids.add(kid)
            aliases.add(native)
            for link in _PAGE_LINK.findall(note.body):
                dest = posixpath.normpath(posixpath.join(posixpath.dirname(path), link))
                if dest in documents and dest not in updated:
                    raise ValidationError('Deleted wiki article still has an incoming link.')
                if path in changes and dest not in updated:
                    # An existing CROW note may cite native raw through its
                    # unchanged links. Never introduce cross-bundle or missing links.
                    previous = documents.get(path)
                    if previous is None or link not in _PAGE_LINK.findall(previous.body):
                        raise ValidationError('Article link does not resolve to a Note in this bundle.')
        changes.update(_navigation(changes, updated, load))
        owned = {f'{bundle.path}/{path}': content for path, content in changes.items()}
        _check_authorized(authorize)
        if validate_content:
            for path, markdown in files.items():
                if path in changes and markdown is not None:
                    validate_content(path, markdown, updated[path].metadata)
        _check_clean_paths(root, head, owned)
        # Only approved text may enter Git, even as an unreachable object.
        revision = _build_commit(root, head, owned, key)
        lock.assert_current()
        # --no-autostash and --no-overwrite-ignore also protect edits made by
        # external clients. Checkout/index/ref publication is performed by Git.
        if wiki_head(root) != head:
            raise WikiEditConflict('Wiki revision moved before publication.')
        _git(root, '-c', 'merge.autoStash=false', 'merge', '--ff-only', '--no-autostash',
             '--no-overwrite-ignore', revision)
        if wiki_head(root) != revision:
            raise WikiEditConflict('Wiki revision moved during publication.')
        return {'revision': revision, 'committed': True, 'changed_paths': sorted(changes)}
