import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import SimpleTestCase

from apps.memory.wiki_config import WikiBundle
from apps.memory.wiki_files import WikiEditConflict, edit_wiki_files, read_wiki_files


def article(kid='knw-alpha', title='Alpha', body='First rule'):
    return (f'---\ntype: Note\nknowledge_id: {kid}\ntitle: {title}\ndescription: Scope of {title}\n'
            f'source_refs:\n  - id: fixture-v1\n---\n\n{body}\n')


@pytest.mark.integration
class WikiFileTests(SimpleTestCase):
    def setUp(self):
        self.scratch = TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.env = patch.dict(os.environ, {'LOCAL_BUSINESS_KNOWLEDGE_REPO_DIR': str(self.root)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.bundle = WikiBundle('field', 'org/crow/field', ('org:all',))
        self.wiki = self.root / self.bundle.path
        self.wiki.mkdir(parents=True)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@localhost')
        (self.wiki / 'index.md').write_text('---\nokf_version: "0.2"\n---\n\n# Notes\n\n')
        (self.root / 'unrelated').write_text('initial')
        self.git('add', '.')
        self.git('commit', '-qm', 'base')
        self.base = self.git('rev-parse', 'HEAD')

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.root, check=True,
                              capture_output=True, text=True).stdout.strip()

    def edit(self, files, rev=None, **kwargs):
        return edit_wiki_files(bundle=self.bundle, expected_revision=rev or self.base, files=files,
                               authorize=kwargs.pop('authorize', lambda: True), **kwargs)

    def test_batch_commit_exact_files_navigation_reread_and_retry(self):
        other = self.root / 'unrelated'
        other.write_text('staged')
        self.git('add', 'unrelated')
        other.write_text('unstaged')
        (self.root / 'other-untracked').write_text('mine')
        edits = {'engineering/alpha.md': article(), 'engineering/beta.md': article('knw-b', 'Бета')}
        result = self.edit(edits)
        self.assertTrue(result['committed'])
        commit = result['revision']
        self.assertEqual(self.git('rev-parse', 'HEAD^'), self.base)
        self.assertEqual(self.git('show', 'HEAD:unrelated'), 'initial')
        self.assertEqual(self.git('show', ':unrelated'), 'staged')
        self.assertEqual(other.read_text(), 'unstaged')
        self.assertEqual((self.root / 'other-untracked').read_text(), 'mine')
        self.assertIn('[engineering](engineering/index.md)', (self.wiki / 'index.md').read_text())
        self.assertIn('[Бета](beta.md)', (self.wiki / 'engineering/index.md').read_text())
        self.assertRegex((self.wiki / 'log.md').read_text(), r'## \d{4}-\d{2}-\d{2}')
        self.assertEqual(self.git('rev-list', '--count', 'HEAD'), '2')
        self.assertFalse(self.edit(edits, commit)['committed'])
        self.assertEqual(self.edit(edits), {'revision': commit, 'committed': False, 'changed_paths': []})
        with self.assertRaises(WikiEditConflict):
            self.edit({'engineering/alpha.md': article(body='Other edit')})
        (self.wiki / 'engineering/alpha.md').write_text('uncommitted secret')
        view = read_wiki_files(bundle=self.bundle, can_read=lambda kid, meta: kid == 'knw-alpha')
        self.assertEqual(view['articles'], [{'path': 'engineering/alpha.md', 'knowledge_id': 'knw-alpha',
                                              'markdown': edits['engineering/alpha.md']}])
        with self.assertRaises(PermissionDenied):
            read_wiki_files(bundle=self.bundle, paths=['engineering/beta.md'], can_read=lambda *a: False)

    def test_existing_edits_in_article_or_navigation_are_never_captured(self):
        commit = self.edit({'alpha.md': article()})['revision']
        for path, staged in [('alpha.md', False), ('alpha.md', True), ('log.md', False), ('log.md', True)]:
            with self.subTest(path=path, staged=staged):
                target = self.wiki / path
                target.write_text('existing local draft')
                if staged:
                    self.git('add', str(target))
                with self.assertRaises(WikiEditConflict):
                    self.edit({'alpha.md': article(body='my change')}, commit)
                self.assertEqual(self.git('rev-parse', 'HEAD'), commit)
                self.assertEqual(target.read_text(), 'existing local draft')
                if staged:
                    self.assertEqual(self.git('show', f':{self.bundle.path}/{path}'), 'existing local draft')
                self.git('restore', '--source=HEAD', '--staged', '--worktree', '--', str(target))

    def test_untracked_and_ignored_files_symlinks_are_not_overwritten(self):
        (self.root / '.git/info/exclude').write_text('ignored.md\n')
        for path in ('untracked.md', 'ignored.md'):
            (self.wiki / path).write_text('other author')
            with self.assertRaises(WikiEditConflict):
                self.edit({path: article()})
            self.assertEqual((self.wiki / path).read_text(), 'other author')
        (self.wiki / 'link').symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(WikiEditConflict):
            self.edit({'link/change.md': article()})
        self.assertFalse((self.root / 'change.md').exists())

    def test_failure_before_publication_does_not_modify_canonical_files(self):
        before = (self.wiki / 'index.md').read_bytes()
        checks = iter([True, False])
        with self.assertRaises(PermissionDenied):
            self.edit({'alpha.md': article()}, authorize=lambda: next(checks))
        self.assertFalse((self.wiki / 'alpha.md').exists())
        self.assertFalse((self.wiki / 'log.md').exists())
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.base)
        self.assertEqual((self.wiki / 'index.md').read_bytes(), before)
        self.assertFalse(self.git('diff', '--cached', '--name-only'))

    def test_preserve_native_identity_metadata_and_no_privilege_escalation(self):
        native = article().replace('knowledge_id: knw-alpha', 'id: native-a\ncustom: native-data')
        (self.wiki / 'native.md').write_text(native)
        self.git('add', str(self.wiki / 'native.md'))
        self.git('commit', '-qm', 'native')
        rev = self.git('rev-parse', 'HEAD')
        for bad in (native.replace('native-a', 'changed'), native.replace('custom: native-data\n', ''),
                    native.replace('type: Note', 'type: Note\nacl: all'),
                    native.replace('type: Note', 'type: Note\nconfirmation_state: confirmed'),
                    native.replace('type: Note', 'type: Note\nverified: true')):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                self.edit({'native.md': bad}, rev)
        result = self.edit({'native.md': native.replace('First rule', 'Updated rule')}, rev)
        self.assertTrue(result['committed'])
        self.assertEqual((self.wiki / 'native.md').read_text(), native.replace('First rule', 'Updated rule'))

    def test_move_preserves_id_and_requires_incoming_links_in_same_commit(self):
        edits = {'one.md': article(), 'linked.md': article('other', 'Linked', 'See [Alpha](one.md).')}
        rev = self.edit(edits)['revision']
        move = {'one.md': None, 'two.md': article()}
        with self.assertRaises(ValidationError):
            self.edit(move, rev)
        move['linked.md'] = edits['linked.md'].replace('](one.md)', '](two.md)')
        result = self.edit(move, rev)
        self.assertEqual(self.git('rev-parse', 'HEAD^'), rev)
        self.assertTrue(result['committed'])
        nav = (self.wiki / 'index.md').read_text()
        self.assertNotIn('](one.md)', nav)
        self.assertIn('](two.md)', nav)

    def test_concurrent_authors_one_revision_wins(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier

        start = Barrier(2)

        def writer(kid):
            start.wait(timeout=3)
            try:
                return self.edit({f'{kid}.md': article(kid)})['committed']
            except WikiEditConflict:
                return False

        with ThreadPoolExecutor(2) as workers:
            self.assertCountEqual(workers.map(writer, ['one', 'two']), [True, False])
        self.assertEqual(self.git('rev-list', '--count', 'HEAD'), '2')

    def test_new_links_and_identity_must_match_an_article_in_this_bundle(self):
        for path, text in [('../a.md', article()), ('raw/a.md', article()), ('index.md', article()),
                           ('a.md', article(body='See [missing](missing.md)')),
                           ('a.md', article(body='See [private](../private/a.md)')),
                           ('a.md', article().replace('knw-alpha', 'invalid id')),
                           ('a.md', article().replace('type: Note', 'type: Note\ntype: Note'))]:
            with self.subTest(path=path, text=text), self.assertRaises(ValidationError):
                self.edit({path: text})
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.base)

    def test_unknown_okf_resource_must_not_be_replaced_or_deleted(self):
        (self.wiki / 'source.md').write_text('---\ntype: Source\n---\n\nBody')
        self.git('add', str(self.wiki / 'source.md'))
        self.git('commit', '-qm', 'native resource')
        latest = self.git('rev-parse', 'HEAD')
        for replacement in (None, article()):
            with self.assertRaises(ValidationError):
                self.edit({'source.md': replacement}, latest)
        self.assertEqual(self.git('rev-parse', 'HEAD'), latest)

    def test_native_crow_checks_host_navigation_and_published_tree(self):
        from importlib.util import find_spec
        if not find_spec('llmw2'):
            self.skipTest('Optional CROW provider is not installed.')
        from llmw2.bundle.check import check

        self.edit({'it/reference/a.md': article(), 'it/b.md': article('knw-b', 'Beta')})
        self.assertEqual(check(self.wiki), [])

    def test_source_authorization_failure_and_noop_do_not_touch_checkout(self):
        def reject(*args):
            raise PermissionDenied('Source unavailable.')

        before = self.git('count-objects', '-v')
        with self.assertRaises(PermissionDenied):
            self.edit({'alpha.md': article()}, validate_content=reject)
        self.assertEqual(self.git('count-objects', '-v'), before)
        self.assertFalse((self.wiki / 'alpha.md').exists())
        self.assertFalse(self.edit({}, validate_content=reject)['committed'])
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.base)

    def test_fast_forward_preserves_unrelated_staged_rename_delete_and_add(self):
        (self.root / 'delete-me').write_text('original')
        self.git('add', 'delete-me')
        self.git('commit', '-qm', 'baseline for deletion')
        rev = self.git('rev-parse', 'HEAD')
        self.git('mv', 'unrelated', 'renamed')
        (self.root / 'renamed').write_text('author working copy')
        self.git('rm', 'delete-me')
        (self.root / 'added').write_text('staged content')
        self.git('add', 'added')
        (self.root / 'added').write_text('unstaged content')
        before = self.git('diff', '--cached', '--binary')
        after_worktree = self.git('diff', '--binary')
        self.edit({'alpha.md': article()}, rev)
        self.assertEqual(self.git('diff', '--cached', '--binary'), before)
        self.assertEqual(self.git('diff', '--binary'), after_worktree)
        self.assertEqual(self.git('show', 'HEAD:delete-me'), 'original')
        self.assertEqual(self.git('show', 'HEAD:unrelated'), 'initial')
