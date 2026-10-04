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

1. Put portable, non-secret defaults in `thinstation.conf.buildtime`.
2. Let runtime expose the normal ThinStation configuration chain through `/etc/thinstation.global`.
3. Use `/etc/thinstation.custom` for persistent site/machine overrides.
4. Add a package-owned `/etc/init.d/<writer>` or equivalent package-owned setup hook.
5. Let the writer translate ThinStation variables into the application's native runtime config.
6. Call the writer from the relevant systemd unit with `ExecStartPre`, or immediately before the application stack is started.

The web UI should edit the persistent override or source variables, then invoke the same writer used at boot.

Do not replace `/etc/thinstation.custom` wholesale from a generic setup tool. Upsert only variables owned by that tool so unrelated package/site settings survive.

### Package variable documentation

If a package consumes a new ThinStation variable, add or update a package-owned file under:

```text
ts/build/packages/<package>/build/conf/
```

Document the variable where the implementation lives, not only in a README or external skill. Include its purpose, valid values/form, default behavior, and important security constraints.

Treat this as part of the package contract: code that introduces a new init/runtime variable is incomplete until its `build/conf` documentation is present.

### Secrets vs. site configuration

Do not use the ThinStation config chain as a generic secret store.

Buildtime/custom configuration is appropriate for non-secret deployment behavior such as listener address, port, public URL, feature flags, DNS/search behavior, or other site policy.

Application encryption keys, authentication secrets, database/cache passwords, bootstrap tokens, and comparable credentials should be generated at first run or provisioned through a dedicated protected mechanism, then persisted in application-owned storage with restrictive permissions.

For a Docker appliance, a package-owned stack `setup.sh` executed before Compose is a good place to:

- source only documented non-secret ThinStation settings;
- load existing persistent secrets;
- generate missing first-run secrets;
- materialize the application's native config;
- verify file/directory modes before service start.

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
