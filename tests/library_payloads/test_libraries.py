"""Regression tests use existing ELF binaries, not a compiler or installed RPMs."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
HELPER = REPO / 'ts/bin/ts-library-deps'
loader = importlib.machinery.SourceFileLoader('ts_libraries', str(HELPER))
spec = importlib.util.spec_from_loader(loader.name, loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)


def host_library(name):
    for directory in ('/usr/lib64', '/lib64', '/usr/lib/x86_64-linux-gnu', '/usr/lib/aarch64-linux-gnu'):
        path = Path(directory) / name
        if path.is_file():
            return path.resolve()
    raise unittest.SkipTest(f'Test ELF fixture {name} is not available')


class TreeCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ts-lib-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.image = self.root / 'image'
        self.image.mkdir()
        m.dynamic.cache_clear()

    def put(self, logical, data=b'x', root=None):
        path = (root or self.image) / logical.lstrip('/')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def link(self, logical, target, root=None):
        path = (root or self.image) / logical.lstrip('/')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(target)
        return path


class ResolverTests(TreeCase):
    def test_relative_chain(self):
        real = self.put('/usr/lib64/libtest.so.1.2')
        self.link('/usr/lib64/libtest.so.1', 'libtest.so.1.2')
        self.link('/usr/lib64/libtest.so', 'libtest.so.1')
        self.assertEqual(m.resolve(self.image, '/usr/lib64/libtest.so'), real)

    def test_absolute_chain_stays_in_image(self):
        real = self.put('/usr/lib64/libc-real.so.6')
        self.link('/usr/lib64/libc.so.6', '/usr/lib64/libc-real.so.6')
        self.assertEqual(m.resolve(self.image, '/usr/lib64/libc.so.6'), real)

    def test_absolute_link_does_not_use_host(self):
        self.link('/usr/lib64/probe.so', str(host_library('libc.so.6')))
        with self.assertRaises(FileNotFoundError):
            m.resolve(self.image, '/usr/lib64/probe.so')

    def test_merged_aliases(self):
        real = self.put('/usr/lib64/libtest.so.1')
        for target in ('/lib64/libtest.so.1', '/lib/libtest.so.1', '/usr/lib/libtest.so.1', '../../lib64/libtest.so.1'):
            link = self.link('/usr/lib64/probe.so', target)
            self.assertEqual(m.resolve(self.image, '/usr/lib64/probe.so', merged=True), real)
            link.unlink()

    def test_symlinked_directory(self):
        real = self.put('/usr/lib64/libtest.so.1')
        self.link('/lib', 'usr/lib64')
        self.assertEqual(m.resolve(self.image, '/lib/libtest.so.1'), real)

    def test_cycle_is_rejected(self):
        self.link('/usr/lib64/one.so', 'two.so')
        self.link('/usr/lib64/two.so', 'one.so')
        with self.assertRaises(m.LibraryError):
            m.resolve(self.image, '/usr/lib64/one.so')

    def test_escape_is_rejected(self):
        self.link('/usr/lib64/probe.so', '../../../../outside')
        with self.assertRaises(m.LibraryError):
            m.resolve(self.image, '/usr/lib64/probe.so')

    def test_destination_does_not_follow_parent(self):
        outside = self.root / 'outside'
        outside.mkdir()
        self.link('/usr/lib64/evil.so', str(outside))
        with self.assertRaises(m.LibraryError):
            m.safe_destination(self.image, '/usr/lib64/evil.so/nested/libx.so')
        self.assertEqual(list(outside.iterdir()), [])


class ReductionTests(TreeCase):
    def setUp(self):
        super().setUp()
        self.data = host_library('libz.so.1').read_bytes()
        self.real = self.put('/usr/lib64/libz.so.1.99.0', self.data)

    def check_reduced(self):
        m.reduce_sonames(self.image)
        dest = self.image / 'usr/lib64/libz.so.1'
        self.assertFalse(dest.is_symlink())
        self.assertEqual(dest.read_bytes(), self.data)
        self.assertEqual(sorted(p.name for p in dest.parent.iterdir()), ['libz.so.1'])
        m.reduce_sonames(self.image)
        self.assertEqual(dest.read_bytes(), self.data)

    def test_multihop_basename_chain(self):
        self.link('/usr/lib64/libz.so', 'libz.so.1')
        self.link('/usr/lib64/libz.so.1', 'libz.so.1.99.0')
        self.check_reduced()

    def test_absolute_aliases(self):
        self.link('/usr/lib64/libz.so', '/usr/lib64/libz.so.1.99.0')
        self.link('/usr/lib64/libz.so.1', '/usr/lib64/libz.so.1.99.0')
        self.check_reduced()

    def test_legacy_and_relative_aliases(self):
        self.link('/usr/lib64/libz.so', '../../lib64/libz.so.1')
        self.link('/usr/lib64/libz.so.1', '/lib64/libz.so.1.99.0')
        self.check_reduced()

    def test_conflicting_sonames_leave_originals(self):
        second = self.put('/usr/lib64/libz-other.so', self.data + b'conflicting-payload')
        with self.assertRaises(m.LibraryError):
            m.reduce_sonames(self.image)
        self.assertEqual(self.real.read_bytes(), self.data)
        self.assertEqual(second.read_bytes(), self.data + b'conflicting-payload')

    def test_unrelated_linker_script_is_preserved(self):
        script = self.put('/usr/lib64/libscript.so', b'GROUP ( libz.so.1 )\n')
        m.reduce_sonames(self.image)
        self.assertEqual(script.read_bytes(), b'GROUP ( libz.so.1 )\n')

    def test_cross_directory_alias_keeps_its_target(self):
        self.link('/usr/lib64/plugins/z.so', '../libz.so.1.99.0')
        m.reduce_sonames(self.image)
        self.assertTrue(self.real.exists())
        self.assertEqual(m.resolve(self.image, '/usr/lib64/plugins/z.so'), self.real)
        self.assertFalse((self.image / 'usr/lib64/libz.so.1').is_symlink())

    def test_cycle_fails_before_mutation(self):
        self.link('/usr/lib64/libcycle.so.1', 'libcycle.so.2')
        self.link('/usr/lib64/libcycle.so.2', 'libcycle.so.1')
        with self.assertRaises(m.LibraryError):
            m.reduce_sonames(self.image)
        self.assertTrue(self.real.exists())


class ClosureTests(TreeCase):
    def setUp(self):
        super().setUp()
        self.source = self.root / 'source'
        self.source.mkdir()
        self.libc = host_library('libc.so.6')
        self.put('/usr/bin/probe', Path('/usr/bin/true').read_bytes())
        # libc needs the dynamic loader; keep it in the isolated source tree.
        for needed in m.dynamic(str(self.libc))['NEEDED']:
            self.put('/usr/lib64/' + needed, host_library(needed).read_bytes(), self.source)

    def collect(self, cache=None):
        collector = m.Collector(self.image, None, [self.source], cache)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            ok = collector.collect()
        return ok, collector

    def test_regular_file_and_recursive_dependency(self):
        self.put('/usr/lib64/libc.so.6', self.libc.read_bytes(), self.source)
        ok, collector = self.collect()
        self.assertTrue(ok, collector.errors)
        self.assertGreaterEqual(len(collector.copied), 2)

    def test_two_hop_dependency_is_regular_file(self):
        self.put('/usr/lib64/libc-real.so.6', self.libc.read_bytes(), self.source)
        self.link('/usr/lib64/libc-hop.so.6', 'libc-real.so.6', self.source)
        self.link('/usr/lib64/libc.so.6', 'libc-hop.so.6', self.source)
        ok, collector = self.collect()
        self.assertTrue(ok, collector.errors)
        dest = self.image / 'usr/lib64/libc.so.6'
        self.assertFalse(dest.is_symlink())
        self.assertEqual(dest.read_bytes(), self.libc.read_bytes())

    def test_absolute_dependency_is_regular_file(self):
        self.put('/usr/lib64/libc-real.so.6', self.libc.read_bytes(), self.source)
        self.link('/usr/lib64/libc.so.6', '/usr/lib64/libc-real.so.6', self.source)
        ok, collector = self.collect()
        self.assertTrue(ok, collector.errors)
        self.assertFalse((self.image / 'usr/lib64/libc.so.6').is_symlink())

    def test_unresolved_dependency_fails(self):
        ok, collector = self.collect()
        self.assertFalse(ok)
        self.assertTrue(any(e['needed'] == 'libc.so.6' for e in collector.errors))

    def test_explicit_exception_is_reported(self):
        collector = m.Collector(self.image, None, [], allow=['libc.so.6'])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(collector.collect())
        self.assertEqual(collector.exemptions, [{'file': '/usr/bin/probe', 'needed': 'libc.so.6'}])

    def test_wrong_elf_class_is_not_used(self):
        data = bytearray(self.libc.read_bytes())
        data[4] = 1 if data[4] == 2 else 2
        self.put('/usr/lib64/libc.so.6', data, self.source)
        ok, _ = self.collect()
        self.assertFalse(ok)

    def test_origin_runpath(self):
        self.put('/usr/bin/private/libc.so.6', self.libc.read_bytes())
        collector = m.Collector(self.image, None, [])
        info = dict(NEEDED=['libc.so.6'], RPATH=[], RUNPATH=['$ORIGIN/private'], SONAME=[])
        found = collector.present('libc.so.6', m.elf_id(self.libc), '/usr/bin/probe', info)
        self.assertEqual(found, self.image / 'usr/bin/private/libc.so.6')

    def test_deep_private_sibling_satisfies_dependency_without_global_copy(self):
        # Private modules can be launched with a wrapper's library path.
        (self.image / 'usr/bin/probe').unlink()
        self.put('/usr/lib64/vendor/plugins/plugin.so', Path('/usr/bin/true').read_bytes())
        local = self.put('/usr/lib64/vendor/plugins/libc.so.6', self.libc.read_bytes())
        ok, collector = self.collect()
        self.assertTrue(ok, collector.errors)
        self.assertEqual(collector.present(
            'libc.so.6', m.elf_id(self.libc), '/usr/lib64/vendor/plugins/plugin.so',
            dict(NEEDED=['libc.so.6'], RPATH=[], RUNPATH=[], SONAME=[])), local)
        self.assertFalse((self.image / 'usr/lib64/libc.so.6').exists())
        self.assertFalse(any(x['needed'] == 'libc.so.6' for x in collector.copied))

    def test_flat_library_does_not_assume_sibling_directory(self):
        local = self.put('/usr/lib64/security/libc.so.6', self.libc.read_bytes())
        info = dict(NEEDED=['libc.so.6'], RPATH=[], RUNPATH=[], SONAME=[])
        collector = m.Collector(self.image, None, [])
        self.assertIsNone(collector.present('libc.so.6', m.elf_id(self.libc),
                                            '/usr/lib64/security/pam_probe.so', info))
        self.assertTrue(local.is_file())

    def test_explicit_runpath_takes_precedence_over_private_sibling(self):
        self.put('/usr/lib64/vendor/plugins/libc.so.6', self.libc.read_bytes())
        info = dict(NEEDED=['libc.so.6'], RPATH=[], RUNPATH=['$ORIGIN/other'], SONAME=[])
        collector = m.Collector(self.image, None, [])
        self.assertIsNone(collector.present('libc.so.6', m.elf_id(self.libc),
                                            '/usr/lib64/vendor/plugins/plugin.so', info))

    def test_p11_kit_install_drops_only_identical_versioned_file(self):
        script = REPO / 'ts/build/packages/p11-kit/build/install'
        with tempfile.TemporaryDirectory(prefix='p11-install-') as directory:
            temp = Path(directory)
            pkg = temp / 'packages/p11-kit/usr/lib64'
            pkg.mkdir(parents=True)
            canonical = pkg / 'libp11-kit.so.0'
            versioned = pkg / 'libp11-kit.so.0.4.11'
            canonical.write_bytes(self.libc.read_bytes())
            versioned.write_bytes(self.libc.read_bytes())
            proxy = pkg / 'p11-kit-proxy.so'
            proxy.symlink_to('libp11-kit.so.0')
            tools = temp / 'bin'
            tools.mkdir()
            stub = tools / 'repackage'
            stub.write_text('#!/bin/sh\nexit 0\n')
            stub.chmod(0o755)
            env = dict(os.environ, TSWRKNG=str(temp),
                       PATH=str(tools) + os.pathsep + os.environ['PATH'])
            for _ in range(2):
                result = subprocess.run(['sh', str(script)], env=env,
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(versioned.exists())
            self.assertTrue(proxy.is_symlink())
            self.assertEqual(proxy.resolve(), canonical)
            self.assertEqual(canonical.read_bytes(), self.libc.read_bytes())
            versioned.write_bytes(b'not the same library')
            result = subprocess.run(['sh', str(script)], env=env,
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(versioned.exists())

    def test_missing_image_root_is_rejected(self):
        with self.assertRaises(m.LibraryError):
            m.Collector(self.root / 'missing-image', None, [])

    def test_failed_copy_is_reported(self):
        self.put('/usr/lib64/libc.so.6', self.libc.read_bytes(), self.source)
        with mock.patch.object(m, 'atomic_copy', side_effect=OSError('deliberate copy error')):
            ok, collector = self.collect()
        self.assertFalse(ok)
        self.assertTrue(any('deliberate copy error' in e['error'] for e in collector.errors))

    def test_verify_only_cli_fails_with_report(self):
        report = self.root / 'report.json'
        result = subprocess.run(['python3', str(HELPER), 'collect', str(self.image), '--verify-only', '--report', str(report)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertTrue(json.loads(report.read_text())['unresolved'])


class CacheTests(ClosureTests):
    def setUp(self):
        super().setUp()
        self.cache = self.root / 'cache'
        self.cache.mkdir()
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        rpm = self.bin / 'rpm'
        rpm.write_text('#!/usr/bin/env python3\nimport pathlib,sys\np=pathlib.Path(sys.argv[-1])\nprint(p.with_suffix(".header").read_text(),end="")\n')
        unpack = self.bin / 'rpm2archive'
        unpack.write_text('#!/usr/bin/env python3\nimport pathlib,sys\nassert "-n" in sys.argv\np=pathlib.Path(sys.argv[-1])\nsys.stdout.buffer.write(p.with_suffix(".tar").read_bytes())\n')
        rpm.chmod(0o755)
        unpack.chmod(0o755)
        self.env = mock.patch.dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ['PATH'])
        self.env.start()
        self.addCleanup(self.env.stop)

    def make_rpm(self, version='1', arch=None, members=None):
        archive = self.cache / ('fixture-' + version + '.rpm')
        archive.write_bytes(b'header-fixture')
        members = members or [
            ('usr/lib64/libc-real.so.6', self.libc.read_bytes(), None),
            ('usr/lib64/libc.so.6', None, '/usr/lib64/libc-real.so.6'),
            ('usr/share/licenses/fixture/COPYING', b'test license', None),
            ('usr/bin/must-not-copy', b'not a library', None),
        ]
        archive.with_suffix('.header').write_text('fixture\t' + (arch or platform.machine()) + '\t0:' + version + '-1\n' + '\n'.join('/' + member[0] for member in members) + '\n')
        with tarfile.open(archive.with_suffix('.tar'), 'w') as tar:
            for name, data, link in members:
                info = tarfile.TarInfo('./' + name)
                info.mode = 0o644
                if link:
                    info.type = tarfile.SYMTYPE
                    info.linkname = link
                    tar.addfile(info)
                else:
                    info.size = len(data)
                    tar.addfile(info, io.BytesIO(data))
        return archive

    def rpm_cache(self):
        return m.RpmCache([self.cache], self.root / 'unpacked', platform.machine())

    def test_cache_only_library_and_license(self):
        self.make_rpm()
        ok, collector = self.collect(self.rpm_cache())
        self.assertTrue(ok, collector.errors)
        self.assertEqual((self.image / 'usr/share/licenses/fixture/COPYING').read_text(), 'test license')
        self.assertFalse((self.image / 'usr/bin/must-not-copy').exists())
        self.assertFalse((self.image / 'usr/lib64/libc.so.6').is_symlink())

    def test_foreign_arch_is_rejected(self):
        self.make_rpm(arch='incompatible-test-arch')
        ok, _ = self.collect(self.rpm_cache())
        self.assertFalse(ok)

    def test_ambiguous_cache_fails(self):
        self.make_rpm(version='1')
        self.make_rpm(version='2')
        ok, collector = self.collect(self.rpm_cache())
        self.assertFalse(ok)
        self.assertTrue(any('Ambiguous' in e['error'] for e in collector.errors))

    def test_archive_parent_symlink_rejected(self):
        outside = self.root / 'outside'
        outside.mkdir()
        archive = self.make_rpm(members=[
            ('usr/lib64/evil.so', None, str(outside)),
            ('usr/lib64/evil.so/nested/libc.so.6', self.libc.read_bytes(), None),
        ])
        with self.assertRaises(m.LibraryError):
            self.rpm_cache().unpack(str(archive))
        self.assertEqual(list(outside.iterdir()), [])

    def test_absolute_rpm_link_cannot_resolve_on_host(self):
        self.make_rpm(members=[('usr/lib64/libc.so.6', None, str(self.libc))])
        ok, _ = self.collect(self.rpm_cache())
        self.assertFalse(ok)


class ShellPropagationTests(TreeCase):
    def body(self):
        return (REPO / 'ts/bin/repackage').read_text().rsplit('\nget_opts "$@"', 1)[0]

    def test_main_propagates_extraction_failure(self):
        code = self.body() + '\npackage_path() { return 0; }; extract_archive() { return 37; }; main; exit $?\n'
        result = subprocess.run(['bash', '-c', code], capture_output=True)
        self.assertEqual(result.returncode, 37)

    def test_main_propagates_reducer_failure(self):
        funcs = ['package_path', 'extract_archive', 'preserve_empty_working', 'canonicalize_usr', 'move_run', 'extra_dirs', 'extra_files', 'remove_empty']
        code = self.body() + '\n' + '\n'.join(f'{f}() {{ return 0; }}' for f in funcs) + '\nreduce_libs() { return 42; }; main; exit $?\n'
        result = subprocess.run(['bash', '-c', code], capture_output=True)
        self.assertEqual(result.returncode, 42)

    def test_env_mode_invalidates_marker_and_propagates(self):
        build = self.root / 'packages/unit/build'
        build.mkdir(parents=True)
        (build / 'installed').touch()
        code = self.body() + '\nmain() { return 53; }; get_opts -e\n'
        result = subprocess.run(['bash', '-c', code], cwd=self.root, env=dict(os.environ, TSWRKNG=str(self.root), XTRWRKNG='', PACKAGE='unit', PORTS='fixture'), capture_output=True)
        self.assertEqual(result.returncode, 53)
        self.assertFalse((build / 'installed').exists())
        self.assertEqual(list(self.root.glob('build-unit.*')), [])

    def test_stb_preserves_failure_through_tee(self):
        script = self.root / 'build'
        script.write_text('#!/bin/sh\necho deliberate-test-failure\nexit 23\n')
        script.chmod(0o755)
        text = (REPO / 'ts/bin/stb').read_text().replace('cd /build', 'cd "' + str(self.root) + '"').replace('/build.log', str(self.root / 'build.log'))
        result = subprocess.run(['bash', '-c', text], capture_output=True, text=True)
        self.assertEqual(result.returncode, 23)
        self.assertIn('deliberate-test-failure', (self.root / 'build.log').read_text())


if __name__ == '__main__':
    unittest.main()
