# Native ThinStation Appliance Patterns

## Configuration precedence

Use ThinStation's own configuration model for appliance defaults:

1. immutable defaults in thinstation.conf.buildtime;
2. values exported through /etc/thinstation.global;
3. optional persistent site/local override under /var/prstnt/<appliance>/config/;
4. package config writer under /etc/init.d/;
5. generated native runtime config under /etc/<appliance>/;
6. service startup after ExecStartPre runs the writer.

The web UI should edit the persistent override and invoke the same writer, not maintain a second configuration system.

## Immutable recovery and persistent generations

For mutable runtimes such as MCP, keep a small immutable recovery implementation in the base image and ordinary generations on persistent storage.

Persistent layout:

    generations/<name>/
    active -> generations/<name>
    previous -> generations/<name>

Each generation should contain a manifest with identity, entrypoint, working directory, hashes, and optional self-test.

Selection order:
1. valid active;
2. valid previous;
3. immutable recovery.

Quarantine runtime-failed generations instead of repeatedly crash-looping them.

## Bootstrap policy

Provide a fast path away from immutable recovery.

Useful modes:
- auto: distribution channel first, recovery seed as fallback;
- channel: require configured channel;
- recovery: create a replaceable persistent generation from immutable recovery;
- off: remain on immutable recovery until configured.

Store these defaults in thinstation.conf.buildtime and materialize runtime policy with a ThinStation config writer.

A recovery-seeded generation is useful for proving persistent switching, but it is still the small recovery runtime. The distribution channel is the normal path to the full MCP.

## Distribution channel

Keep the distribution point static and portable. A minimal channel document needs generation, archive URL, and SHA-256.

The appliance should:
1. fetch the channel document;
2. validate generation and URL;
3. download to persistent scratch;
4. verify checksum before extraction;
5. reject archive path traversal;
6. install atomically into a new generation;
7. validate manifest/self-test;
8. activate only after validation.

Do not hard-code a private distribution hostname in reusable source. Supply it through build-time or persistent policy.

## Service ordering

Recommended chain:

    persistent storage/init
      -> appliance config writer
      -> optional bootstrap/update helper
      -> runtime selector
      -> runtime supervisor

Bootstrap/update failure must not prevent selector/recovery startup.

## Registration and console UX

For first-run appliances:
- keep registration/login minimal;
- show configurable issue/acceptable-use text on console and web login;
- show one-time token/QR only until registration succeeds;
- make the UI mobile-friendly and responsive in portrait/landscape;
- retire bootstrap credentials after administrator creation;
- refresh getty after registration so token/QR disappear.

Let agetty be the single console renderer. Generate /run/issue.d content atomically.

Do not retain ThinStation tsuser console autologin on a management appliance. Explicitly enable normal getty/login behavior.

## Appliance web UI

Favor an appliance console:
- persistent navigation on desktop and drawer on mobile;
- compact status/user header;
- plain login/registration;
- focused pages such as Overview, Network, Credentials, Runtime, System, Settings;
- list/table first and detail drill-down second;
- dangerous actions behind deliberate administration affordances.

Network configuration should expose live state separately from intended configuration and use NetworkManager profiles as source of truth.

For remote network changes, save separately from apply. Before applying, create a rollback profile/timer and cancel it only after the browser reconnects and confirms the new configuration.

## Credentials

Treat credentials as inventory objects.

List:
- name;
- type;
- scopes/capabilities;
- allowed hosts/targets;
- protection metadata.

Open a credential for detailed administration. Keep secrets write-only. Support rotation, scope/host updates, rename/delete, and public-key copy without revealing private material.

## Hot-deploy loop

Do not rebuild the ISO for every web/API iteration.

Use:

    edit source
      -> copy web/backend files into running guest
      -> restart only affected service
      -> refresh browser

SSH is convenient after setup. QEMU Guest Agent is preferred early because it does not depend on guest networking or SSH credentials.

Hot deploy does not validate package inclusion, boot ordering, persistence restore, autologin/getty policy, or unit enablement. Those still require a real build.
