# Runtime library payloads

`ts/bin/ts-library-deps` is a build-host utility, not an image package. It
implements the common library-path policy for `repackage` and the image builder.

## SONAME reduction

`repackage` resolves complete relative and absolute link chains within its
staged package root. It understands the old `/lib`, `/lib64`, and `/usr/lib`
aliases after directory canonicalization. It never resolves package-absolute
links against the running build host. Cycles, root escapes, and conflicting
payloads for one SONAME fail. Every selected regular ELF is staged before the
deletion ledger is applied. The final top-level file is named by its SONAME.
Linker scripts and cross-directory aliases are preserved; versioned targets
referenced by an alias outside the ledger are retained rather than broken.

## Dependency closure

The image builder reads DT_NEEDED, RPATH/RUNPATH, and loader search configuration.
It recursively copies missing compatible ELF libraries as regular files from
installed build-chroot libraries or cached native/noarch RPM payloads. If a
provider is not cached, the normal configured DNF repositories may supply an
exact native provider using download-only commands. Target RPMs are never
installed, and RPM scriptlets are never executed by the collector. RPM license
payloads accompany libraries sourced from those archives. Foreign ELF classes
and machines do not satisfy a dependency. Ambiguous RPM versions/providers fail
rather than selecting an arbitrary archive.

The initial closure runs before image finalization. A separate verify-only pass
checks the final image without adding files. Unresolved DT_NEEDED entries, copy
failures, and resolver errors make the build fail. There are no default broad
SONAME exceptions. Explicit `--allow-missing SONAME` exceptions are supported by
the standalone tool and are recorded; the stock builder does not pass any.
This is ELF link dependency validation, not proof that every optional dlopen
plugin or application data file is available. A boot test remains required.

`repackage` propagates errors, invalidates its installed marker at the beginning
of an environment-mode operation, and writes a new marker only after success.
The builder requires that marker after a recipe using repackage. `stb` uses
pipefail so `tee` cannot hide build failures.

## Diagnostics and tests

The stock CI job requires `test-library-payloads` to pass first. Its after-script
preserves `/build.log` and `ts/build/library-reports/*.json` outside the build
scratch mount before cleanup, with artifacts retained on success or failure.

Run from the repository root:

```sh
bash -n ts/bin/repackage ts/bin/stb ts/build/build
python3 -m unittest discover -s tests/library_payloads -p 'test_*.py' -v
python3 -m unittest discover -s ts/build/packages/lightdm/build/tests -p 'test_*.py' -v
```

Tests use existing ELF files and isolated RPM/archive fixtures, not compilation
or target-package installation. On 2026-10-12, additional manual verification
resolved all four desktop libraries missing from ISO 2204 directly from Fedora
44 RPMs: libxfce4windowing-0.so.0, libxfce4windowingui-0.so.0,
libgtk-layer-shell.so.0, and libwnck-3.so.0. That check also verified retained
license files. No stock build.conf or thinstation.conf.buildtime changes are
part of this repair.
