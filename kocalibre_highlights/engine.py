"""Runs a highlights sync for a calibre library. No GUI code here."""

import json
import os
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

from . import luatable
from .column import annotations_from_column
from .device import DeviceError, KOReaderSSH
from .metadata import FIELDS, changes_for_book, check_columns, koreader_values
from .positions import Book
from .sync import (IMPORT_DEVICE_ID, BookSync, apply_koreader_import, state_from_json,
                   state_to_json, utc_to_ko)

try:
    load_translations()
except NameError:
    pass  # not running as a calibre plugin (tests); calibre-debug provides _()

FORMAT = 'EPUB'


def action_name(action):
    return {'add': _('added'), 'update': _('updated'), 'delete': _('deleted')}[action]


def side_name(side):
    return {'calibre': 'calibre', 'koreader': 'KOReader'}[side]


class StateStore:
    '''Per library sync state, by book uuid: the highlight keys synced last time
    and the KOReader book data (status, rating, review) seen last time.'''

    def __init__(self, base_dir, library_id):
        self.dir = os.path.join(base_dir, 'state')
        os.makedirs(self.dir, exist_ok=True)
        self.path = os.path.join(self.dir, f'{library_id}.json')
        try:
            with open(self.path, encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        if data and 'version' not in data:
            data = {'highlights': data}  # version 1 only had highlights, at the top level
        self.data = {'version': 2, 'highlights': data.get('highlights', {}), 'metadata': data.get('metadata', {})}

    def get(self, book_uuid):
        return state_from_json(self.data['highlights'].get(book_uuid))

    def set(self, book_uuid, state):
        self.data['highlights'][book_uuid] = state_to_json(state)

    def get_metadata(self, book_uuid):
        return self.data['metadata'].get(book_uuid)

    def set_metadata(self, book_uuid, values):
        self.data['metadata'][book_uuid] = values

    def save(self):
        tmp = self.path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(tmp, self.path)


class Backup:

    def __init__(self, base_dir, keep=20):
        self.root = os.path.join(base_dir, 'backups')
        self.dir = os.path.join(self.root, time.strftime('%Y%m%d-%H%M%S'))
        self.keep = keep
        self.used = False

    def write(self, name, data):
        os.makedirs(self.dir, exist_ok=True)
        self.used = True
        safe = ''.join(c if c.isalnum() or c in ' ._()-' else '_' for c in name)[:180]
        mode = 'wb' if isinstance(data, bytes) else 'w'
        with open(os.path.join(self.dir, safe), mode, **({} if mode == 'wb' else {'encoding': 'utf-8'})) as f:
            f.write(data)

    def prune(self):
        try:
            entries = sorted(os.listdir(self.root))
        except OSError:
            return
        import shutil
        for old in entries[:-self.keep]:
            shutil.rmtree(os.path.join(self.root, old), ignore_errors=True)


class Report:

    def __init__(self):
        self.books = []    # (title, source, Counter of (action, side))
        self.errors = []   # (title, message)
        self.skipped = []  # (title, reason)
        self.metadata = []  # (title, {column: new value})
        self.device = None

    def totals(self):
        c = Counter()
        for _, _, counts in self.books:
            c.update(counts)
        return c

    def summary(self):
        t = self.totals()
        lines = []
        if self.device:
            lines.append(_('Device: {}').format(self.device))
        lines.append(_('Books synced: {}').format(len(self.books)))
        for side in ('calibre', 'koreader'):
            parts = [f'{t[(a, side)]} {action_name(a)}' for a in ('add', 'update', 'delete') if t[(a, side)]]
            if parts:
                lines.append(f'  {side_name(side)}: ' + ', '.join(parts))
        if not any(t.values()):
            lines.append('  ' + _('Everything was already in sync'))
        if self.metadata:
            lines.append(_('Read / rating / review: {} books updated in calibre').format(len(self.metadata)))
        if self.skipped:
            lines.append(_('Skipped: {} books').format(len(self.skipped)))
        if self.errors:
            lines.append(_('Errors: {}').format(len(self.errors)))
        return '\n'.join(lines)

    def details(self):
        out = []
        for title, source, counts in self.books:
            if any(counts.values()):
                out.append(f'{title} [{source}]: ' + ', '.join(
                    _('{0} {1} in {2}').format(n, action_name(a), side_name(s))
                    for (a, s), n in sorted(counts.items())))
        for title, changes in self.metadata:
            out.append(f'{title}: ' + ', '.join(f'{col} = {_short(v)}' for col, v in changes.items()))
        for title, msg in self.errors:
            out.append(_('ERROR {0}: {1}').format(title, msg))
        for title, reason in self.skipped:
            out.append(_('Skipped {0}: {1}').format(title, reason))
        return '\n'.join(out)


def _short(v):
    if isinstance(v, str) and len(v) > 40:
        return repr(v[:40] + '…')
    return repr(v)


def calibre_highlights(db, book_id):
    return list(db.annotations_map_for_book(book_id, FORMAT).get('highlight', ()))


class SyncEngine:
    '''
    db: calibre new_api Cache
    prefs: dict-like with the plugin settings
    base_dir: where to keep state and backups
    '''

    def __init__(self, db, prefs, base_dir, log=None, dry_run=False):
        self.db = db
        self.prefs = prefs
        self.base_dir = base_dir
        self.log = log or (lambda *a: None)
        self.dry_run = dry_run
        self.state = StateStore(base_dir, db.library_id)
        self.backup = Backup(base_dir)
        self.report = Report()

    def device(self, host):
        p = self.prefs
        return KOReaderSSH(host, port=p.get('port', 2222), user=p.get('user', 'root'),
                           key_file=p.get('key_file') or None, koreader_dir=p.get('koreader_dir', '/mnt/us/koreader'))

    def run(self, host=None, book_ids=None, use_device=True, use_column=None):
        '''Sync all books (or only book_ids). Returns a Report.'''
        if use_column is None:
            use_column = bool(self.prefs.get('use_column_fallback', True))
        synced = set()
        if use_device and host:
            try:
                synced = self.sync_device(host, book_ids)
            except DeviceError as e:
                self.report.errors.append((_('Device'), str(e)))
        if use_column:
            self.sync_column(book_ids, exclude=synced)
        if not self.dry_run:
            self.state.save()
        self.backup.prune()
        return self.report

    # Device {{{
    def sync_device(self, host, book_ids=None):
        dev = host if isinstance(host, KOReaderSSH) else self.device(host)
        host = dev.host
        dev.check()
        offset = dev.utc_offset()
        roots = self.prefs.get('book_roots') or ['/mnt/us/books', '/mnt/us/documents']
        books = dev.scan(roots)
        open_books = dev.open_books()
        self.report.device = _('{0} ({1} books with KOReader data)').format(host, len(books))
        self.log(f'Found {len(books)} books with KOReader data on {host}')
        wanted = set(book_ids) if book_ids is not None else None
        synced = set()
        ko_now = utc_to_ko(datetime.now(timezone.utc), offset)
        meta_columns, errors = check_columns(self.db.field_metadata, self.prefs)
        self.report.errors.extend((_('Settings'), e) for e in errors)
        meta_changes = {}  # column -> {book_id: value}
        for dbook in books.values():
            book_id = self.db.lookup_by_uuid(dbook.calibre_uuid) if dbook.calibre_uuid else None
            if book_id is None:
                if wanted is None and dbook.path.lower().endswith('.epub'):
                    self.report.skipped.append((dbook.filename, _('not in this calibre library')))
                continue
            if wanted is not None and book_id not in wanted:
                continue
            title = self.db.field_for('title', book_id)
            if dbook.path in open_books:
                self.report.skipped.append((title, _('open in KOReader: close it and sync again')))
                continue
            if meta_columns:
                self.sync_book_metadata(dbook, book_id, title, meta_columns, meta_changes)
            if not dbook.path.lower().endswith('.epub'):
                continue
            try:
                if self.sync_device_book(dev, dbook, book_id, title, offset, ko_now):
                    synced.add(book_id)
            except Exception as e:
                import traceback
                self.report.errors.append((title, f'{e}\n{traceback.format_exc()}'))
        if not self.dry_run:
            for col, vals in meta_changes.items():
                self.db.set_field(col, vals)
        return synced

    def sync_book_metadata(self, dbook, book_id, title, columns, pending):
        '''Status, rating and review from the sidecar to calibre columns'''
        book_uuid = self.db.field_for('uuid', book_id)
        values = koreader_values(dbook.sidecar)
        current = {setting: self.db.field_for(col, book_id) for setting, col in columns.items()}
        changes = changes_for_book(values, self.state.get_metadata(book_uuid), current)
        if changes:
            self.report.metadata.append((title, {columns[k]: v for k, v in changes.items()}))
            if not self.dry_run:
                self.backup.write(f'{book_id}-metadata.json', json.dumps(
                    {columns[k]: v for k, v in current.items()}, ensure_ascii=False, default=str))
            for setting, v in changes.items():
                pending.setdefault(columns[setting], {})[book_id] = v
        self.state.set_metadata(book_uuid, {k: values[k] for k in FIELDS})

    def sync_device_book(self, dev, dbook, book_id, title, offset, ko_now):
        path = self.db.format_abspath(book_id, FORMAT)
        if not path:
            self.report.skipped.append((title, _('no EPUB format in calibre')))
            return False
        ko_annots = dbook.annotations
        pending = dbook.pending_import
        if pending and pending.get('device_id') == IMPORT_DEVICE_ID:
            # Our previous changes were not imported by KOReader yet
            ko_annots = apply_koreader_import(ko_annots, luatable.to_list(pending.get('annotations')),
                                              pending.get('datetime'))
        book_uuid = self.db.field_for('uuid', book_id)
        prev = self.state.get(book_uuid)
        calibre_annots = calibre_highlights(self.db, book_id)
        if not ko_annots and not calibre_annots and not prev:
            return True
        # Newer crengine DOM versions always write explicit [1] indices
        explicit = int((dbook.sidecar or {}).get('cre_dom_version') or 0) >= 20260812
        syncer = BookSync(Book(path), book_uuid, offset, explicit)
        res = syncer.sync(ko_annots, calibre_annots, prev, can_write_koreader=True)
        for e in res.errors:
            self.report.errors.append((title, e))
        self.report.books.append((title, 'device', res.counts()))
        if self.dry_run:
            return True
        if res.calibre_changes or res.koreader_changed:
            self.backup.write(f'{book_id}-calibre.json', json.dumps(calibre_annots, ensure_ascii=False, indent=1))
            if dbook.sidecar_raw:
                self.backup.write(f'{book_id}-{os.path.basename(dbook.sidecar_path)}', dbook.sidecar_raw)
        if res.koreader_changed:
            payload = {
                'annotations': res.koreader_annotations,
                'datetime': ko_now,
                'device_id': IMPORT_DEVICE_ID,
            }
            dev.write_file(dbook.import_path, luatable.dumps(payload).encode('utf-8'))
        if res.calibre_changes:
            self.db.merge_annotations_for_book(book_id, FORMAT, res.calibre_changes)
        self.state.set(book_uuid, res.state)
        return True
    # }}}

    # Column {{{
    def sync_column(self, book_ids=None, exclude=()):
        col = self.prefs.get('column') or '#ko_bookmarks'
        if col not in self.db.field_metadata.all_field_keys():
            return
        ids = book_ids if book_ids is not None else self.db.all_book_ids()
        values = self.db.all_field_for(col, ids, default_value=None)
        for book_id, html in values.items():
            if not html or book_id in exclude:
                continue
            title = self.db.field_for('title', book_id)
            ko_annots = annotations_from_column(html)
            if not any(a.get('pos0') and a.get('drawer') for a in ko_annots):
                continue
            path = self.db.format_abspath(book_id, FORMAT)
            if not path:
                self.report.skipped.append((title, _('no EPUB format in calibre')))
                continue
            try:
                book_uuid = self.db.field_for('uuid', book_id)
                syncer = BookSync(Book(path), book_uuid, local_utc_offset())
                res = syncer.sync(ko_annots, calibre_highlights(self.db, book_id),
                                  self.state.get(book_uuid), can_write_koreader=False)
            except Exception as e:
                import traceback
                self.report.errors.append((title, f'{e}\n{traceback.format_exc()}'))
                continue
            for e in res.errors:
                self.report.errors.append((title, e))
            self.report.books.append((title, 'column', res.counts()))
            if res.calibre_changes and not self.dry_run:
                self.backup.write(f'{book_id}-calibre.json', json.dumps(
                    calibre_highlights(self.db, book_id), ensure_ascii=False, indent=1))
                self.db.merge_annotations_for_book(book_id, FORMAT, res.calibre_changes)
    # }}}


def local_utc_offset():
    now = time.time()
    return timedelta(seconds=round((datetime.fromtimestamp(now) - datetime.utcfromtimestamp(now)).total_seconds()))
