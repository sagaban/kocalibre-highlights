"""Access to KOReader's files on the device over SSH (KOReader's SSH server)."""

import io
import json
import os
import posixpath
import shlex
import subprocess
import tarfile
from datetime import timedelta

from . import luatable


class DeviceError(Exception):
    pass


class DeviceBook:
    '''A book on the device, with its KOReader sidecar data'''

    def __init__(self, path):
        self.path = path              # absolute path of the book on the device
        self.sidecar_path = None      # metadata.<ext>.lua
        self.sidecar = None           # parsed sidecar table (dict)
        self.sidecar_raw = None
        self.import_path = None       # <book>.annotations.lua
        self.pending_import = None    # parsed import file, if present
        self.calibre_uuid = None

    @property
    def filename(self):
        return posixpath.basename(self.path)

    @property
    def annotations(self):
        if not self.sidecar:
            return []
        return luatable.to_list(self.sidecar.get('annotations'))

    def __repr__(self):
        return f'DeviceBook({self.path!r})'


def calibre_uuid_from_identifiers(identifiers):
    for line in (identifiers or '').splitlines():
        k, sep, v = line.partition(':')
        if sep and k.strip().lower() == 'calibre':
            return v.strip()
    return None


class KOReaderSSH:

    def __init__(self, host, port=2222, user='root', key_file=None, koreader_dir='/mnt/us/koreader',
                 timeout=20, ssh_binary='ssh'):
        self.host, self.port, self.user = host, int(port), user
        self.key_file = key_file
        self.koreader_dir = koreader_dir
        self.timeout = timeout
        self.ssh_binary = ssh_binary
        self._settings = None

    def _cmd(self, remote_cmd):
        cmd = [self.ssh_binary, '-p', str(self.port), '-o', 'BatchMode=yes',
               '-o', f'ConnectTimeout={self.timeout}', '-o', 'StrictHostKeyChecking=accept-new',
               '-o', 'ServerAliveInterval=10']
        if self.key_file:
            cmd += ['-i', os.path.expanduser(self.key_file), '-o', 'IdentitiesOnly=yes']
        cmd += [f'{self.user}@{self.host}', remote_cmd]
        return cmd

    def run(self, remote_cmd, data=None, timeout=120):
        try:
            p = subprocess.run(self._cmd(remote_cmd), input=data, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, timeout=timeout)
        except FileNotFoundError:
            raise DeviceError('ssh is not installed')
        except subprocess.TimeoutExpired:
            raise DeviceError(f'Timed out talking to {self.host}')
        if p.returncode != 0:
            err = p.stderr.decode('utf-8', 'replace').strip()
            raise DeviceError(f'Command failed on device ({p.returncode}): {err}')
        return p.stdout

    def check(self):
        out = self.run('echo ok').decode().strip()
        if out != 'ok':
            raise DeviceError(f'Unexpected answer from device: {out!r}')

    def utc_offset(self):
        '''Device local time minus UTC, rounded to 15 minutes'''
        out = self.run("date '+%Y-%m-%d %H:%M:%S'; date -u '+%Y-%m-%d %H:%M:%S'").decode().split('\n')
        from datetime import datetime
        local = datetime.strptime(out[0].strip(), '%Y-%m-%d %H:%M:%S')
        utc = datetime.strptime(out[1].strip(), '%Y-%m-%d %H:%M:%S')
        minutes = round((local - utc).total_seconds() / 900) * 15
        return timedelta(minutes=minutes)

    def settings(self):
        if self._settings is None:
            raw = self.run(f'cat {shlex.quote(self.koreader_dir + "/settings.reader.lua")}')
            self._settings = luatable.loads(raw.decode('utf-8'))
        return self._settings

    def sidecar_dir(self, book_path):
        mode = self.settings().get('document_metadata_folder', 'doc')
        base = posixpath.splitext(book_path)[0] + '.sdr'
        if mode == 'dir':
            return self.koreader_dir + '/docsettings' + base
        if mode == 'hash':
            raise DeviceError('KOReader stores metadata by hash; set "Book metadata location" to '
                              '"book folder" or "koreader/docsettings" in KOReader')
        return base

    def import_file_path(self, book_path):
        folder = self.settings().get('annotations_export_folder') or self.sidecar_dir(book_path)
        return folder + '/' + posixpath.basename(book_path) + '.annotations.lua'

    def scan(self, roots):
        '''Find books with sidecars under roots. Returns {book_path: DeviceBook}'''
        mode = self.settings().get('document_metadata_folder', 'doc')
        search = list(roots)
        if mode == 'dir':
            search = [self.koreader_dir + '/docsettings' + r for r in roots]
        export_folder = self.settings().get('annotations_export_folder')
        if export_folder:
            search.append(export_folder)
        find = ' '.join(shlex.quote(r) for r in search)
        cal = ' '.join(shlex.quote(r + '/.metadata.calibre') for r in roots)
        script = (
            f"L=/tmp/kocalibre-highlights.list; : > $L; "
            f"find {find} \\( -iname 'metadata.*.lua' -o -name '*.annotations.lua' \\) -type f 2>/dev/null >> $L; "
            f"for f in {cal}; do [ -f \"$f\" ] && echo \"$f\" >> $L; done; "
            f"[ -s $L ] && tar -cf - -T $L; rm -f $L"
        )
        raw = self.run(script, timeout=300)
        files = {}
        if raw:
            with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
                for m in tf.getmembers():
                    if m.isfile():
                        files['/' + m.name.lstrip('/')] = tf.extractfile(m).read()
        return self._books_from_files(files, roots)

    def _books_from_files(self, files, roots):
        mode = self.settings().get('document_metadata_folder', 'doc')
        books = {}
        uuid_by_path = {}
        for path, data in files.items():
            if posixpath.basename(path) == '.metadata.calibre':
                root = posixpath.dirname(path)
                try:
                    for entry in json.loads(data.decode('utf-8')):
                        uuid_by_path[posixpath.join(root, entry['lpath'])] = entry.get('uuid')
                except (ValueError, KeyError, TypeError):
                    pass
        for path, data in files.items():
            name = posixpath.basename(path)
            if not (name.lower().startswith('metadata.') and name.endswith('.lua')):
                continue
            ext = name[len('metadata.'):-len('.lua')]
            sdr = posixpath.dirname(path)
            if not sdr.endswith('.sdr'):
                continue
            book_path = sdr[:-4] + '.' + ext
            if mode == 'dir':
                book_path = book_path[len(self.koreader_dir + '/docsettings'):]
            text = data.decode('utf-8', 'replace')
            try:
                table = luatable.loads(text)
            except luatable.LuaParseError:
                continue
            b = DeviceBook(table.get('doc_path') or book_path)
            b.sidecar_path, b.sidecar, b.sidecar_raw = path, table, text
            b.calibre_uuid = uuid_by_path.get(b.path) or calibre_uuid_from_identifiers(
                (table.get('doc_props') or {}).get('identifiers'))
            b.import_path = self.import_file_path(b.path)
            imp = files.get(b.import_path)
            if imp is not None:
                try:
                    b.pending_import = luatable.loads(imp.decode('utf-8'))
                except luatable.LuaParseError:
                    pass
            books[b.path] = b
        return books

    def open_books(self):
        '''Books KOReader currently has open. While a book is open, KOReader keeps
        its annotations in memory (including an import it already consumed) and
        only writes the sidecar when the book is closed, so its sidecar is stale.'''
        script = ("for p in /proc/[0-9]*; do grep -q reader.lua $p/cmdline 2>/dev/null || continue; "
                  "for f in $p/fd/*; do readlink \"$f\"; done; done 2>/dev/null; true")
        out = self.run(script).decode('utf-8', 'replace')
        return {line.strip() for line in out.splitlines() if line.startswith('/') and not line.endswith('.cr3')}

    def write_file(self, path, data):
        '''Atomically write data (bytes) to path on the device'''
        q = shlex.quote(path)
        tmp = shlex.quote(path + '.kocalibre-tmp')
        self.run(f'mkdir -p {shlex.quote(posixpath.dirname(path))} && cat > {tmp} && mv -f {tmp} {q}', data=data)


class KOReaderFolder(KOReaderSSH):
    '''A device mounted as a local folder (USB mass storage), or a copy of one.

    mount: local path that corresponds to device_root (e.g. /Volumes/Kindle for /mnt/us)
    '''

    def __init__(self, mount, device_root='/mnt/us', koreader_dir='/mnt/us/koreader', utc_offset=None):
        KOReaderSSH.__init__(self, host=mount, koreader_dir=koreader_dir)
        self.mount = mount.rstrip('/')
        self.device_root = device_root.rstrip('/')
        self._offset = utc_offset

    def local(self, device_path):
        if not device_path.startswith(self.device_root + '/'):
            raise DeviceError(f'{device_path} is not on the device')
        return self.mount + device_path[len(self.device_root):]

    def run(self, remote_cmd, data=None, timeout=120):
        raise DeviceError('Shell commands are not available on a folder device')

    def open_books(self):
        return set()  # KOReader is not running while the device is mounted

    def check(self):
        if not os.path.isdir(self.mount):
            raise DeviceError(f'{self.mount} is not mounted')

    def utc_offset(self):
        if self._offset is not None:
            return self._offset
        from .engine import local_utc_offset
        return local_utc_offset()

    def settings(self):
        if self._settings is None:
            try:
                with open(self.local(self.koreader_dir + '/settings.reader.lua'), encoding='utf-8') as f:
                    self._settings = luatable.loads(f.read())
            except OSError:
                self._settings = {}
        return self._settings

    def scan(self, roots):
        files = {}
        mode = self.settings().get('document_metadata_folder', 'doc')
        search = [self.koreader_dir + '/docsettings' + r for r in roots] if mode == 'dir' else list(roots)
        if self.settings().get('annotations_export_folder'):
            search.append(self.settings()['annotations_export_folder'])
        for root in search:
            base = self.local(root)
            for dirpath, dirnames, filenames in os.walk(base):
                for name in filenames:
                    if (name.lower().startswith('metadata.') and name.endswith('.lua')) or name.endswith('.annotations.lua'):
                        local = os.path.join(dirpath, name)
                        with open(local, 'rb') as f:
                            files[self.device_root + local[len(self.mount):]] = f.read()
        for root in roots:
            try:
                with open(self.local(root + '/.metadata.calibre'), 'rb') as f:
                    files[root + '/.metadata.calibre'] = f.read()
            except OSError:
                pass
        return self._books_from_files(files, roots)

    def write_file(self, path, data):
        local = self.local(path)
        os.makedirs(os.path.dirname(local), exist_ok=True)
        tmp = local + '.kocalibre-tmp'
        with open(tmp, 'wb') as f:
            f.write(data)
        os.replace(tmp, local)
