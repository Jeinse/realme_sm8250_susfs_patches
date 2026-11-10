import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


sync = module('sync_jack')
publish = module('publish_candidate')


class SourceValidation(unittest.TestCase):
    def test_patch_rejects_path_traversal_and_renames(self):
        for path in ['../file', '/absolute', 'a/../../file', 'a\\file']:
            with self.assertRaises(sync.StopSync):
                sync.safe_path(path)
        for data in [b'diff --git a/x b/y\n', b'diff --git a/../x b/../x\n']:
            with self.assertRaises(sync.StopSync):
                sync.patch_paths(data)

    def test_rejection_line_drift_is_allowed_but_code_changes_are_not(self):
        first = '@@ -1,2 +1,3 @@ function\n old\n+new\n'
        moved = '@@ -99,2 +101,3 @@ function\n old\n+new\n'
        self.assertEqual(sync.rejected_blocks(first), sync.rejected_blocks(moved))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'fs').mkdir()
            path = root / 'fs/test.c.rej'
            path.write_text(moved)
            expected = [{'path': 'fs/test.c', 'body_sha256': sync.rejected_blocks(first)[0]}]
            self.assertEqual(sync.verify_rejections(root, expected), [path])
            path.write_text(moved.replace('+new', '+different hook'))
            with self.assertRaises(sync.StopSync):
                sync.verify_rejections(root, expected)

    def test_fixup_stays_within_the_five_reviewed_files(self):
        paths = sync.patch_paths((ROOT / 'compat/entropy-1.7-fixups.patch').read_bytes())
        self.assertEqual(set(paths), {'fs/Makefile', 'fs/namespace.c', 'fs/proc/task_mmu.c', 'fs/super.c', 'mm/memory.c'})
        self.assertEqual(len(sync.load(ROOT / 'compat/entropy-1.7-rejections.json')['expected_rejections']), 7)

    def test_current_payload_metadata(self):
        sync.verify_repository()

    def test_wrapper_ref_is_validated_before_source_access(self):
        result = subprocess.run(['bash', str(ROOT / 'susfs_inline_hook_patches.sh'), '--ref', '../main'],
                                text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('full lowercase commit SHA', result.stderr)

    def test_wrapper_rejects_missing_ref(self):
        result = subprocess.run(['bash', str(ROOT / 'susfs_inline_hook_patches.sh'), '--ref'], text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('requires a full commit', result.stderr)


class PublicationValidation(unittest.TestCase):
    def fixture(self, directory):
        config = sync.load(ROOT / 'config/sources.json')
        patch = b'diff --git a/fs/susfs.c b/fs/susfs.c\n--- /dev/null\n+++ b/fs/susfs.c\n@@ -0,0 +1 @@\n+candidate data\n'
        report = {'schema': 1, 'base_repository_commit': 'a' * 40,
                  'kernel': config['kernel'], 'bakasu': config['bakasu'],
                  'jack': {'repository': config['jack']['repository'], 'commit': 'b' * 40, 'branch': 'mainline'},
                  'branch': 'candidate/jack-' + 'b' * 12 + '-' + 'c' * 10,
                  'inputs': [{'path': Path(config['jack'][k]).name, 'sha256': 'a' * 64} for k in ['patch', 'inline_script']],
                  'adapter_hashes': {p: sync.digest((ROOT / p).read_bytes()) for p in sync.ADAPTER_FILES},
                  'patch': {'path': 'patches/entropy-1.7-susfs-2.3.0-jack.patch', 'sha256': sync.digest(patch), 'files': 1},
                  'changed_files': ['fs/susfs.c'],
                  'checks': {'clean_apply_check': True, 'clean_apply': True, 'reverse_check': True,
                             'bakasu_inline_check': True, 'upstream_core_verbatim': True, 'identical_result_files': 1},
                  'automatic_compilation': False,
                  'manual_validation': {'full_kernel_build': 'pending', 'device_flash_test': 'pending'}}
        (directory / 'candidate.patch').write_bytes(patch)
        sync.save(directory / 'report.json', report)
        return report

    def test_candidate_files_do_not_claim_manual_tests_passed(self):
        with tempfile.TemporaryDirectory() as temp:
            report = self.fixture(Path(temp))
            _, files = publish.candidate_files(Path(temp), 'a' * 40)
            manifest = json.loads(files['SOURCE_MANIFEST.json'])
            self.assertFalse(manifest['verification']['full_kernel_link'])
            self.assertFalse(manifest['verification']['device_boot_test'])
            self.assertEqual(manifest['verification']['compiled_changed_c_files'], 0)
            self.assertEqual(manifest['manual_validation'], report['manual_validation'])
            self.assertNotIn('.github/workflows/sync-jack-susfs.yml', files)

    def test_publication_refuses_tampered_artifact_and_stable_branch(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            report = self.fixture(directory)
            (directory / 'candidate.patch').write_bytes(b'changed')
            with self.assertRaises(ValueError):
                publish.candidate_files(directory, 'a' * 40)
            self.fixture(directory)
            report['branch'] = 'main'
            sync.save(directory / 'report.json', report)
            with self.assertRaises(ValueError):
                publish.candidate_files(directory, 'a' * 40)

    def test_wrapper_only_replaces_payload_constants(self):
        script = (ROOT / 'susfs_inline_hook_patches.sh').read_text()
        updated = publish.wrapper(script, 'entropy-1.7-susfs-2.4.0-jack.patch', 'a' * 64)
        self.assertEqual(updated.count("readonly PATCH_FILE='entropy-1.7-susfs-2.4.0-jack.patch'"), 1)
        self.assertIn("readonly PATCH_SHA256='" + 'a' * 64 + "'", updated)
        self.assertIn('--ref', updated)
        with self.assertRaises(ValueError):
            publish.wrapper(script, '../../workflow.yml', 'a' * 64)

    def test_publisher_has_no_stable_ref_update_or_auto_merge(self):
        source = (ROOT / 'scripts/publish_candidate.py').read_text()
        self.assertNotIn("method='PATCH'", source)
        self.assertNotIn("'/merges'", source)
        self.assertIn("'draft': True", source)


if __name__ == '__main__':
    unittest.main()
