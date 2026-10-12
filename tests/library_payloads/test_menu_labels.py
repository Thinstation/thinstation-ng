"""Keep menu category names visible, with or without runtime translations."""
import ast
import configparser
import hashlib
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ROOT / 'ts/build/packages'
SOURCE = PACKAGES / 'xfwm4/build/extra/etc/xfwm4.functions'
SHELL = shutil.which('bash')
GETTEXT = shutil.which('gettext')


def write_test_catalog(path, messages):
    """Write a small GNU MO fixture without requiring a message compiler."""
    pairs = sorted((key.encode('utf-8'), value.encode('utf-8'))
                   for key, value in messages.items())
    count = len(pairs)
    original_offset = 28 + 16 * count
    original_data = b'\0'.join(key for key, _ in pairs) + b'\0'
    translation_offset = original_offset + len(original_data)
    original_table = []
    translation_table = []
    for key, value in pairs:
        original_table.extend((len(key), original_offset))
        translation_table.extend((len(value), translation_offset))
        original_offset += len(key) + 1
        translation_offset += len(value) + 1
    header = struct.pack('<7I', 0x950412de, 0, count, 28, 28 + count * 8, 0, 0)
    tables = struct.pack('<' + 'I' * (4 * count),
                         *(original_table + translation_table))
    translations = b'\0'.join(value for _, value in pairs) + b'\0'
    path.parent.mkdir(parents=True)
    path.write_bytes(header + tables + original_data + translations)


class RuntimeMenuTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.menus = self.root / 'menus'
        self.menus.mkdir()
        (self.bin / 'cat').symlink_to(shutil.which('cat'))
        text = SOURCE.read_text()
        self.helper = 'write_menu_directory()' + text.split(
            'write_menu_directory()', 1)[1].split('\nwm_menu()', 1)[0]
        self.env = dict(os.environ, PATH=str(self.bin), LC_ALL='C',
                        LANGUAGE='', TEXTDOMAIN='thinstation',
                        TEXTDOMAINDIR=str(self.root / 'locale'))

    def translator(self, body):
        path = self.bin / 'gettext'
        path.write_text('#!' + SHELL + '\n' + body + '\n')
        path.chmod(0o755)

    def label(self, key='Utilities'):
        result = subprocess.run(
            [SHELL, '-eu', '-c', self.helper +
             '\nmenudir="$1"\nwrite_menu_directory "$2"\n',
             'menu-test', str(self.menus), key],
            env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(self.menus / (key + '.directory'), encoding='utf-8')
        entry = parser['Desktop Entry']
        self.assertEqual(entry['Type'], 'Directory')
        self.assertEqual(entry['Icon'], key)
        self.assertEqual(entry['Name'], entry['Comment'])
        self.assertTrue(entry['Name'])
        return entry['Name']

    def test_missing_gettext_retains_category_name(self):
        self.assertEqual(self.label(), 'Utilities')

    def test_failed_gettext_retains_category_name(self):
        self.translator('exit 1')
        self.assertEqual(self.label(), 'Utilities')

    def test_partial_output_from_failed_gettext_is_not_used(self):
        self.translator("printf 'partial translation'; exit 1")
        self.assertEqual(self.label(), 'Utilities')

    def test_empty_successful_gettext_retains_category_name(self):
        self.translator('exit 0')
        self.assertEqual(self.label(), 'Utilities')

    def test_translation_changes_label_not_identifier(self):
        self.translator("printf '%s' 'Dienstprogramme'")
        self.assertEqual(self.label(), 'Dienstprogramme')

    def test_unknown_custom_category_is_preserved(self):
        self.translator('printf "%s" "$1"')
        self.assertEqual(self.label('Custom & Tools'), 'Custom & Tools')

    def test_existing_blank_directory_is_repaired(self):
        path = self.menus / 'Utilities.directory'
        path.write_text('[Desktop Entry]\nName=\nComment=\n')
        self.assertEqual(self.label(), 'Utilities')
        first = path.read_bytes()
        self.assertEqual(self.label(), 'Utilities')
        self.assertEqual(path.read_bytes(), first)

    @unittest.skipUnless(GETTEXT, 'GNU gettext runtime is not installed')
    def test_real_gettext_in_c_locale_needs_no_catalog(self):
        (self.bin / 'gettext').symlink_to(GETTEXT)
        self.assertEqual(self.label(), 'Utilities')

    @unittest.skipUnless(GETTEXT, 'GNU gettext runtime is not installed')
    def test_real_gettext_uses_german_and_utf8_labels(self):
        (self.bin / 'gettext').symlink_to(GETTEXT)
        source = (PACKAGES / 'base/build/locale/de.po').read_text()
        messages = {'': 'Content-Type: text/plain; charset=UTF-8\nLanguage: de\n'}
        for key in ('Utilities', 'Office', 'Network'):
            match = re.search(r'^msgid "' + key + r'"\nmsgstr (".*")$',
                              source, re.MULTILINE)
            self.assertIsNotNone(match, key)
            messages[key] = ast.literal_eval(match.group(1))
        write_test_catalog(self.root / 'locale/de/LC_MESSAGES/thinstation.mo', messages)
        # GNU gettext disables LANGUAGE in C locales, including C.UTF-8.
        locales = subprocess.run(['locale', '-a'], text=True, capture_output=True,
                                 check=True).stdout.splitlines()
        usable = [value for value in locales
                  if '.utf8' in value.lower().replace('-', '')
                  and not value.lower().startswith('c.')]
        if not usable:
            self.skipTest('A non-C UTF-8 locale is needed for GNU gettext')
        selected = 'de_DE.utf8' if 'de_DE.utf8' in usable else usable[0]
        self.env.update(LC_ALL=selected, LANGUAGE='de')
        for key in ('Utilities', 'Office', 'Network'):
            with self.subTest(category=key):
                self.assertNotEqual(messages[key], key)
                self.assertEqual(self.label(key), messages[key])


class PackagingTests(unittest.TestCase):
    def test_base_owns_gettext_not_optional_guest_login(self):
        entry = 'gettext-runtime,gettext,0,0,usr/bin,1,,,,,,,,,'
        self.assertIn(entry, (PACKAGES / 'base/.dna').read_text().splitlines())
        self.assertNotIn(entry, (PACKAGES / 'lightdm-guest/.dna').read_text().splitlines())

    def test_fast_metadata_matches_canonical_dna(self):
        for package in ('base', 'lightdm-guest'):
            dna = PACKAGES / package / '.dna'
            expected = '#' + hashlib.md5(dna.read_bytes()).hexdigest() + '  .dna'
            for cache in ('.wind', '.unwind'):
                with self.subTest(package=package, cache=cache):
                    text = (dna.parent / cache).read_text()
                    self.assertEqual(text.splitlines()[0], expected)
                    self.assertEqual('/usr/bin/gettext' in text, package == 'base')


if __name__ == '__main__':
    unittest.main()
