"""Isolated installed-RPM and collision-fallback tests. No host RPM changes."""
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

REPACKAGE = Path(__file__).resolve().parents[2] / "ts/bin/repackage"

HARNESS = r"""
source <(sed '/^get_opts "\$@"$/,$d' "$1")
package=foo
pkgpath="$TEST_ROOT/output"
mkdir -p "$pkgpath"
extract_scripts() { :; }
apply_caps() { :; }
rpm() {
    if [ "$1" = --eval ]; then printf '%s\n' x86_64; return; fi
    if [ "$1" = -q ]; then
        if [ "$2" = --scripts ]; then return 0; fi
        if [ "$2" = --qf ]; then
            case "$3" in
                *FILENAMES*) printf '%s\n' "$TEST_ROOT/installed" "$TEST_ROOT/installed/payload"; return 0 ;;
                *filenames*) printf '%s\n' '/usr/bin/foo (none)'; return 0 ;;
            esac
            return 9
        fi
        [ "$2" = foo.x86_64 ] && [ -e "$TEST_STATE" ]
        return
    fi
    if [ "$1" = -qp ]; then
        if [ "$2" = --qf ]; then
            case "$3" in
                '%{NAME} %{ARCH}')
                    case "$4" in *foo-extra-*) printf 'foo-extra x86_64' ;;
                        *.i686.rpm) printf 'foo i686' ;;
                        *) printf 'foo x86_64' ;;
                    esac ;;
                *) printf '/usr/bin/foo (none)\n' ;;
            esac
            return 0
        fi
        if [ "$2" = --scripts ]; then return 0; fi
    fi
    return 9
}
dnf() {
    printf 'DNF:%s\n' "$*" >> "$TEST_LOG"
    if [ "$1" = install ]; then
        [ "$TEST_COLLISION" != 1 ] || return 1
        touch "$TEST_STATE"
        return 0
    fi
    if [ "$1" = download ]; then
        local a dest=''
        for a in "$@"; do case "$a" in --destdir=*) dest="$(printf '%s' "$a" | cut -d= -f2-)" ;; esac; done
        [ -n "$dest" ] || return 1
        cp "$TEST_ARCHIVE" "$dest/foo-1.0-1.x86_64.rpm"
        return 0
    fi
    return 99
}
rpm2archive() { echo "RPM2ARCHIVE:$1" >> "$TEST_LOG"; cat "$TEST_ARCHIVE"; }
extract_archive
"""

class HybridRepackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hybrid-rpm-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cache = self.root / "cache"
        self.cache.mkdir()
        installed = self.root / "installed"
        installed.mkdir()
        (installed / "payload").write_text("installed payload\n")
        self.state = self.root / "state"
        self.log = self.root / "commands.log"
        self.archive = self.root / "archive.rpm"
        staged = self.root / "stage"
        (staged / "usr/bin").mkdir(parents=True)
        (staged / "usr/bin/foo").write_text("RPM archive payload\n")
        with tarfile.open(self.archive, "w:gz") as tar:
            tar.add(staged / "usr", arcname="usr")
        self.env = dict(os.environ,
                        TEST_ROOT=str(self.root), TEST_STATE=str(self.state),
                        TEST_LOG=str(self.log), TEST_ARCHIVE=str(self.archive),
                        TEST_COLLISION="0", TS_REPACKAGE_DNF_CACHE=str(self.cache))

    def run_case(self, collision=False):
        env = dict(self.env, TEST_COLLISION="1" if collision else "0")
        result = subprocess.run(["bash", "-c", HARNESS, "test", str(REPACKAGE)],
                                env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return self.log.read_text() if self.log.exists() else ""

    def test_installed_package_skips_dnf_and_archive(self):
        self.state.touch()
        log = self.run_case()
        self.assertNotIn("DNF:", log)
        self.assertNotIn("RPM2ARCHIVE", log)
        copy = self.root / "output" / str(self.root).lstrip("/") / "installed/payload"
        self.assertEqual(copy.read_text(), "installed payload\n")

    def test_install_then_reuse_without_unwind(self):
        first = self.run_case()
        self.assertIn("DNF:install ", first)
        self.assertNotIn("RPM2ARCHIVE", first)
        self.log.unlink()
        second = self.run_case()
        self.assertNotIn("DNF:", second)
        self.assertNotIn("RPM2ARCHIVE", second)

    def test_collision_cached_archive_without_erasing(self):
        dest = self.cache / "repo/packages"
        dest.mkdir(parents=True)
        (dest / "foo-1.0-1.x86_64.rpm").write_bytes(self.archive.read_bytes())
        log = self.run_case(collision=True)
        self.assertIn("DNF:install ", log)
        self.assertNotIn("--allowerasing", log)
        self.assertIn("RPM2ARCHIVE:", log)
        self.assertNotIn("DNF:download ", log)
        self.assertEqual((self.root / "output/usr/bin/foo").read_text(),
                         "RPM archive payload\n")

    def test_uncached_collision_downloads_single_rpm(self):
        log = self.run_case(collision=True)
        self.assertIn("DNF:download --arch=x86_64 ", log)
        self.assertIn("DNF:install --setopt=keepcache=1 --setopt=install_weak_deps=False -y foo.x86_64", log)
        self.assertNotIn("--arch=x86_64,noarch", log)
        self.assertNotIn("--resolve", log)
        self.assertIn("RPM2ARCHIVE:", log)
        self.assertTrue((self.root / "output/usr/bin/foo").exists())

    def test_prefix_and_foreign_arch_not_selected(self):
        dest = self.cache / "repo/packages"
        dest.mkdir(parents=True)
        (dest / "foo-extra-9.0-1.x86_64.rpm").touch()
        (dest / "foo-9.0-1.i686.rpm").touch()
        log = self.run_case(collision=True)
        self.assertIn("DNF:download --arch=x86_64 ", log)
        self.assertIn("RPM2ARCHIVE:", log)

    def test_source_does_not_use_allowerasing(self):
        src = REPACKAGE.read_text()
        self.assertNotIn("dnf install --downloadonly", src)
        self.assertNotIn("dnf repoquery --available", src)
        self.assertNotIn("dnf install --allowerasing", src)

if __name__ == "__main__":
    unittest.main()
