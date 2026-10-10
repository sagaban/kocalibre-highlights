"""Two-way highlight synchronization between KOReader and calibre for one book.

The engine is pure: it receives the current state of both sides plus the
state recorded at the end of the previous sync, and returns the changes to
apply to each side.

Highlights are identified by their KOReader position key (pos0, pos1). For
calibre highlights the key is computed by converting their CFIs. The state of
the previous sync (the set of keys that existed on both sides) lets us tell a
deletion on one side apart from a creation on the other.
"""

import base64
import hashlib
from datetime import datetime, timedelta, timezone

from .positions import PositionError
from .styles import calibre_style_to_ko, ko_style_key, ko_to_calibre_style

try:
    load_translations()
except NameError:
    pass  # not running as a calibre plugin (tests); calibre-debug provides _()

KO_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'
IMPORT_DEVICE_ID = 'calibre-kocalibre-highlights'


# Time helpers {{{

def ko_to_utc(s, utc_offset):
    '''KOReader datetimes are naive strings in the device's local time'''
    if not s:
        return None
    try:
        dt = datetime.strptime(s, KO_DATE_FORMAT)
    except ValueError:
        return None
    return (dt - utc_offset).replace(tzinfo=timezone.utc)


def utc_to_ko(dt, utc_offset):
    return (dt.astimezone(timezone.utc).replace(tzinfo=None) + utc_offset).strftime(KO_DATE_FORMAT)


def parse_calibre_ts(ts):
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def calibre_ts(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f'{dt.microsecond // 1000:03d}Z'


def to_second(dt):
    return dt.replace(microsecond=0) if dt else dt


def utcnow():
    return datetime.now(timezone.utc)
# }}}


def is_ko_highlight(a):
    '''Page bookmarks have no drawer and no pos0/pos1'''
    return bool(a.get('drawer') and a.get('pos0') and a.get('pos1'))


def ko_key(a):
    return a['pos0'], a['pos1']


def ko_updated(a, utc_offset):
    return ko_to_utc(a.get('datetime_updated') or a.get('datetime'), utc_offset)


def calibre_uuid_for(book_uuid, key):
    '''Deterministic calibre uuid for a highlight created from KOReader'''
    h = hashlib.sha1(f'{book_uuid}\0{key[0]}\0{key[1]}'.encode('utf-8')).digest()
    return base64.urlsafe_b64encode(h).decode('ascii')[:22]


def apply_koreader_import(annotations, imported, import_datetime):
    '''Python port of ReaderAnnotation:importAnnotations() for rolling (EPUB)
    documents, used to know the effective KOReader state while an import file we
    wrote earlier has not been consumed yet.'''
    annotations = [dict(a) for a in annotations]
    new = [dict(a) for a in imported]
    if not annotations:
        return new

    def does_match(a, b):
        return (not a.get('drawer')) == (not b.get('drawer')) and a.get('page') == b.get('page') and a.get('pos1') == b.get('pos1')

    for i in range(len(annotations) - 1, -1, -1):
        item = annotations[i]
        item_dt = item.get('datetime_updated') or item.get('datetime') or ''
        found = False
        for j in range(len(new) - 1, -1, -1):
            n = new[j]
            if does_match(item, n):
                if item_dt < (n.get('datetime_updated') or n.get('datetime') or ''):
                    del annotations[i]
                else:
                    del new[j]
                found = True
                break
        if not found and item_dt < (import_datetime or ''):
            del annotations[i]
    annotations.extend(new)
    return annotations


class SyncResult:

    def __init__(self):
        self.calibre_changes = []      # annotations to merge into calibre (incl. tombstones)
        self.koreader_annotations = None  # full list to write to KOReader, None if unchanged
        self.state = {}                # key -> {'uuid': ...}
        self.log = []                  # (action, side, text)
        self.errors = []

    @property
    def koreader_changed(self):
        return self.koreader_annotations is not None

    def note(self, action, side, text):
        self.log.append((action, side, (text or '').strip()[:80]))

    def counts(self):
        from collections import Counter
        return Counter((a, s) for a, s, t in self.log)


class BookSync:
    '''Sync the highlights of one EPUB book.

    book: positions.Book for the calibre copy of the EPUB
    book_uuid: calibre uuid of the book
    utc_offset: timedelta, KOReader device local time minus UTC
    '''

    def __init__(self, book, book_uuid, utc_offset=timedelta(0), explicit_first_index=False):
        self.book = book
        self.book_uuid = book_uuid
        self.utc_offset = utc_offset
        self.explicit_first_index = explicit_first_index

    # Conversions {{{
    def ko_to_calibre(self, a, uuid=None):
        name, p0 = self.book.xpointer_to_point(a['pos0'])
        name1, p1 = self.book.xpointer_to_point(a['pos1'])
        if name != name1:
            # Highlight spans two spine items: calibre needs both ends in one file
            raise PositionError('Highlight spans multiple files')
        updated = ko_updated(a, self.utc_offset) or utcnow()
        annot = {
            'type': 'highlight',
            'uuid': uuid or calibre_uuid_for(self.book_uuid, ko_key(a)),
            'start_cfi': self.book.point_to_cfi(name, p0),
            'end_cfi': self.book.point_to_cfi(name, p1),
            'spine_name': name,
            'spine_index': self.book.spine_index(name),
            'highlighted_text': a.get('text') or self.book.text(name, p0, p1),
            'style': ko_to_calibre_style(a.get('color'), a.get('drawer')),
            'timestamp': calibre_ts(updated),
        }
        if a.get('note'):
            annot['notes'] = a['note']
        if a.get('chapter'):
            annot['toc_family_titles'] = [a['chapter']]
        return annot

    def calibre_key(self, c):
        name = c['spine_name']
        p0 = self.book.cfi_to_point(name, c['start_cfi'])
        p1 = self.book.cfi_to_point(name, c['end_cfi'])
        return (self.book.point_to_xpointer(name, p0, self.explicit_first_index),
                self.book.point_to_xpointer(name, p1, self.explicit_first_index))

    def calibre_to_ko(self, c, key):
        ts = parse_calibre_ts(c.get('timestamp')) or utcnow()
        color, drawer = calibre_style_to_ko(c.get('style'))
        a = {
            'datetime': utc_to_ko(ts, self.utc_offset),
            'drawer': drawer,
            'color': color,
            'text': c.get('highlighted_text') or '',
            'page': key[0],
            'pos0': key[0],
            'pos1': key[1],
            'pageno': 0,  # recomputed by KOReader when it imports the file
        }
        titles = c.get('toc_family_titles')
        if titles:
            a['chapter'] = titles[-1]
        if c.get('notes'):
            a['note'] = c['notes']
        return a
    # }}}

    def sync(self, ko_annotations, calibre_annots, prev_state, can_write_koreader=True):
        '''
        ko_annotations: KOReader annotations (list of dicts, highlights and bookmarks)
        calibre_annots: calibre highlight annotations for the book (incl. removed ones)
        prev_state: dict key -> {'uuid': ...} from the last sync, or None if never synced
        can_write_koreader: False when KOReader data comes from a read-only source
          (e.g. the calibre column); then nothing is deleted anywhere.
        '''
        res = SyncResult()
        prev_state = prev_state or {}
        prev_keys = set(prev_state) if can_write_koreader else set()

        kmap = {}
        for a in ko_annotations:
            if is_ko_highlight(a):
                kmap.setdefault(ko_key(a), a)

        tombstones = {c.get('uuid') for c in calibre_annots if c.get('removed')}

        def deleted_in_calibre(key):
            uuids = {calibre_uuid_for(self.book_uuid, key), prev_state.get(key, {}).get('uuid')}
            return bool(uuids & tombstones)

        cmap = {}
        for c in calibre_annots:
            if c.get('type') != 'highlight' or c.get('removed'):
                continue
            try:
                key = self.calibre_key(c)
            except (PositionError, ValueError, KeyError) as e:
                res.errors.append(_('calibre highlight {0!r}: {1}').format(c.get('highlighted_text', '')[:40], e))
                continue
            if key in cmap:
                # Duplicate of an existing calibre highlight, keep the newest
                if (c.get('timestamp') or '') <= (cmap[key].get('timestamp') or ''):
                    continue
            cmap[key] = c

        new_ko = [dict(a) for a in ko_annotations]
        ko_index = {ko_key(a): i for i, a in enumerate(new_ko) if is_ko_highlight(a)}
        ko_removed = set()
        ko_changed = False

        for key in sorted(set(kmap) | set(cmap) | prev_keys):
            k, c = kmap.get(key), cmap.get(key)
            synced_before = key in prev_keys
            if k and c:
                changed = self._reconcile(k, c, key, new_ko[ko_index[key]], res, can_write_koreader)
                ko_changed = ko_changed or changed
                res.state[key] = {'uuid': c['uuid']}
            elif k:
                if not can_write_koreader and (key in prev_state or deleted_in_calibre(key)):
                    # Managed by device syncs, or deleted in calibre: a stale
                    # read-only copy must not bring it back
                    continue
                if synced_before or deleted_in_calibre(key):
                    # Was on both sides and removed in calibre
                    ko_removed.add(key)
                    ko_changed = True
                    res.note('delete', 'koreader', k.get('text'))
                else:
                    try:
                        annot = self.ko_to_calibre(k, uuid=prev_state.get(key, {}).get('uuid'))
                    except (PositionError, ValueError) as e:
                        res.errors.append(_('KOReader highlight {0!r}: {1}').format(k.get('text', '')[:40], e))
                        continue
                    res.calibre_changes.append(annot)
                    res.state[key] = {'uuid': annot['uuid']}
                    res.note('add', 'calibre', k.get('text'))
            elif c:
                if synced_before:
                    # Was on both sides and removed in KOReader
                    res.calibre_changes.append(self.tombstone(c))
                    res.note('delete', 'calibre', c.get('highlighted_text'))
                elif can_write_koreader:
                    a = self.calibre_to_ko(c, key)
                    new_ko.append(a)
                    ko_changed = True
                    res.state[key] = {'uuid': c['uuid']}
                    res.note('add', 'koreader', c.get('highlighted_text'))
            # else: deleted on both sides, forget it

        # A calibre highlight whose range was edited gets a new key, so it is
        # handled above as deleted (old key) plus created (new key).
        if ko_changed and can_write_koreader:
            res.koreader_annotations = [a for a in new_ko if not (is_ko_highlight(a) and ko_key(a) in ko_removed)]
        if not can_write_koreader:
            res.state = {}
        return res

    def _reconcile(self, k, c, key, k_out, res, can_write_koreader):
        '''Both sides have the highlight: propagate note/style edits, newest wins.
        Returns True if the KOReader annotation was modified.'''
        k_style = ko_style_key(k.get('color'), k.get('drawer'))
        c_style = ko_style_key(*calibre_style_to_ko(c.get('style')))
        k_note = (k.get('note') or '').strip()
        c_note = (c.get('notes') or '').strip()
        if k_style == c_style and k_note == c_note:
            return False
        k_time = to_second(ko_updated(k, self.utc_offset))
        c_time = to_second(parse_calibre_ts(c.get('timestamp')))
        if k_time and c_time and c_time > k_time:
            # Edited last in calibre
            if not can_write_koreader:
                return False
            if k_style != c_style:
                k_out['color'], k_out['drawer'] = calibre_style_to_ko(c.get('style'))
            if c_note:
                k_out['note'] = c['notes']
            else:
                k_out.pop('note', None)
            k_out['datetime_updated'] = utc_to_ko(c_time, self.utc_offset)
            res.note('update', 'koreader', k.get('text'))
            return True
        # Edited last in KOReader
        updated = dict(c)
        if k_style != c_style:
            updated['style'] = ko_to_calibre_style(k.get('color'), k.get('drawer'))
        if k_note:
            updated['notes'] = k['note']
        else:
            updated.pop('notes', None)
        updated['timestamp'] = calibre_ts(k_time or utcnow())
        res.calibre_changes.append(updated)
        res.note('update', 'calibre', c.get('highlighted_text'))
        return False

    @staticmethod
    def tombstone(c):
        return {'type': 'highlight', 'uuid': c['uuid'], 'removed': True, 'timestamp': calibre_ts(utcnow())}


def state_to_json(state):
    return [{'pos0': k[0], 'pos1': k[1], **v} for k, v in sorted(state.items())]


def state_from_json(data):
    if data is None:
        return None
    return {(x['pos0'], x['pos1']): {k: v for k, v in x.items() if k not in ('pos0', 'pos1')} for x in data}
