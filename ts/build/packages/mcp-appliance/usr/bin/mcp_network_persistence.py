"""Keep NetworkManager connection files across immutable appliance boots.

Runs before NetworkManager, after the optional persistent disk mount.
An unprovisioned appliance keeps its ordinary RAM-backed bootstrap networking.
Existing persistent profiles take precedence over image defaults.
"""
import os
from pathlib import Path
import shutil
import stat
import tempfile

LIVE = Path('/etc/NetworkManager/system-connections')
STORE = Path('/var/prstnt/mcp-appliance/config/network-connections')


def directory(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise ValueError('Unsafe NetworkManager profile directory: ' + str(path))


def migrate_legacy_store_owner(store):
    """Migrate the brief unprivileged-MCP profile ownership back to root."""
    if os.geteuid() != 0 or not store.exists() or store.is_symlink():
        return
    info = store.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o022:
        return
    if info.st_uid != 0:
        os.chown(store, 0, info.st_gid)
    for source in store.iterdir():
        if not source.name.endswith('.nmconnection'):
            continue
        info = source.lstat()
        if stat.S_ISREG(info.st_mode) and not (info.st_mode & 0o077) and info.st_uid != 0:
            os.chown(source, 0, info.st_gid)


def attach(live=LIVE, store=STORE):
    live, store = Path(live), Path(store)
    for parent in (store.parent, *store.parent.parents):
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, os.geteuid()):
            raise ValueError('Unsafe persistent profile path.')
        if info.st_mode & 0o022 and not (parent == Path('/tmp') and info.st_mode & stat.S_ISVTX):
            raise ValueError('Writable persistent profile ancestor.')
    migrate_legacy_store_owner(store)
    directory(store)
    os.chmod(store, 0o700)
    if live.is_symlink():
        if live.resolve() != store.resolve():
            raise ValueError('NetworkManager profile directory points to an unexpected location.')
        return
    directory(live)
    if not any(store.iterdir()):
        for source in live.iterdir():
            if not source.name.endswith('.nmconnection'):
                continue
            info = source.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise ValueError('Unsafe network profile; refusing to migrate it.')
            fd, name = tempfile.mkstemp(prefix='.profile-', dir=store)
            try:
                with os.fdopen(fd, 'wb') as output, source.open('rb') as stream:
                    os.fchmod(output.fileno(), 0o600)
                    shutil.copyfileobj(stream, output)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(name, store / source.name)
            finally:
                if os.path.exists(name):
                    os.unlink(name)
    backup = live.with_name('system-connections.boot-defaults')
    if backup.exists() or backup.is_symlink():
        raise ValueError('Previous profile-directory backup exists; inspect before replacing it.')
    live.rename(backup)
    try:
        live.symlink_to(store, target_is_directory=True)
    except BaseException:
        backup.rename(live)
        raise


if __name__ == '__main__':
    if os.path.ismount('/var/prstnt'):
        STORE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        attach()
