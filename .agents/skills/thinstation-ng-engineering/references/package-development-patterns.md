# Package Development Patterns

## Incremental package population

When developing a package that has already been unwound/populated, avoid a full build when only package content needs refreshing.

If repackage should populate a package without rebuilding its upstream payload:

    touch ts/build/packages/<package>/build/installed
    ts/bin/update <package>

Use this only when build/installed is the intended upstream-build-complete marker. Verify the populated package root afterward.

For authored build/extra files added after an unwind, explicitly verify they reached the package root or final image. A hardlinked copy can be useful for focused development validation, but committed source remains in build/extra.

## Repackage and filesystem normalization

Treat repackage as the central normalization point for imported RPM/package payloads.

- Keep licenses and legal notices.
- Prefer /usr/bin and /usr/lib or /usr/lib64 for normalized payloads.
- Do not introduce new top-level /bin, /sbin, /lib, or /lib64 content when a /usr equivalent is correct.
- When cleaning legacy package trees for a /usr merge, inspect .dna, build/extra, finalizers, symlinks, and generated package-root files together.
- Re-run representative package population and boot tests after normalization.

## ThinStation configuration writers

Prefer ThinStation-native configuration materialization over parallel application-specific configuration frameworks.

Pattern:

1. Put portable defaults in thinstation.conf.buildtime.
2. Let runtime expose them through /etc/thinstation.global.
3. Add a package-owned /etc/init.d/<writer> that sources /etc/init.d/common.
4. Let the writer translate ThinStation variables into the application's native runtime config.
5. If needed, source a persistent site/local override after build-time defaults.
6. Call the writer from the relevant systemd unit with ExecStartPre.

The web UI should edit the persistent override or source variables, then invoke the same writer used at boot.

## Systemd integration

Use systemd ordering instead of sleeps.

- ExecStartPre for config writers.
- After for hard ordering.
- Wants for optional helpers whose failure must not block a safe fallback.
- Requires only when the service truly cannot operate without the dependency.
- Keep recovery/fallback paths startable even when network/bootstrap/update helpers fail.

For console/getty output, avoid multiple writers racing on the same TTY. Generate issue content atomically and let agetty render it.

## Network and early boot

Network availability is a boot-architecture dependency.

If ts-init, fastboot, config download, or another early consumer needs networking:
- put the selected network stack and its required libraries in the early/initrd side;
- do not defer NetworkManager into lib.squash if early boot requires it;
- avoid two runtime network stacks solely to solve bootstrap ordering;
- keep DNS/search-domain behavior in the normal NetworkManager/ThinStation config path.

## Machine profiles and hwlister

Machine profiles should contain top-level hardware module requirements, not every loaded module.

When improving hwlister:
1. collect actually loaded modules;
2. exclude filesystem modules and separately managed categories;
3. remove modules that are dependencies of other selected modules;
4. retain the minimal top-level set;
5. warn for unavailable or built-in modules.

## Localization

Separate build-time translation from runtime translation.

- Translate generated menus/groups/application metadata at build time.
- Use runtime gettext for runtime-read files.
- Keep product/session identifiers untranslated when appropriate.
- Validate at least one non-en_US locale after localization changes.
