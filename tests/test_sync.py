'''Unit tests. Run with: calibre-debug -e tests/test_sync.py'''
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kocalibre_highlights import luatable  # noqa
from kocalibre_highlights.column import annotations_from_column  # noqa
from kocalibre_highlights.positions import Book  # noqa
from kocalibre_highlights.styles import calibre_style_to_ko, ko_style_key, ko_to_calibre_style  # noqa
from kocalibre_highlights.sync import (BookSync, apply_koreader_import, calibre_uuid_for,  # noqa
                                       parse_calibre_ts)

OPF = '''<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="id">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>T</dc:title><dc:identifier id="id">x</dc:identifier><dc:language>es</dc:language></metadata>
<manifest>
<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>
<item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/>
<item id="c2" href="c2.xhtml" media-type="application/xhtml+xml"/>
<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
</manifest>
<spine toc="ncx"><itemref idref="cover" linear="no"/><itemref idref="c1"/><itemref idref="c2"/></spine>
</package>'''

NCX = '''<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><head/><docTitle><text>T</text></docTitle>
<navMap><navPoint id="n1" playOrder="1"><navLabel><text>Uno</text></navLabel><content src="c1.xhtml"/></navPoint></navMap></ncx>'''


def html(body):
    return f'''<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>t</title></head>
<body>{body}</body></html>'''


C1 = html('''
  <h1 id="top">Capítulo <i>uno</i></h1>
  <div>
    <p>Primer párrafo con <cite>una cita</cite> y texto
       que sigue    con espacios.</p>
    <p>Segundo <b>en negrita</b> medio <i>itálica</i> final del párrafo.</p>
    <p id="p3">Tercero 😀 emoji y más texto.</p>
  </div>
''')
C2 = html('<p>Otro archivo, un solo párrafo.</p><p>Y otro más.</p>')


def make_epub(path):
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('mimetype', 'application/epub+zip', compress_type=zipfile.ZIP_STORED)
        z.writestr('META-INF/container.xml', '''<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>''')
        z.writestr('content.opf', OPF)
        z.writestr('toc.ncx', NCX)
        z.writestr('cover.xhtml', html('<p>cover</p>'))
        z.writestr('c1.xhtml', C1)
        z.writestr('c2.xhtml', C2)


def ko_hl(pos0, pos1, text, dt='2026-01-01 10:00:00', **kw):
    a = {'chapter': 'Uno', 'color': 'gray', 'datetime': dt, 'drawer': 'lighten',
         'page': pos0, 'pageno': 3, 'pos0': pos0, 'pos1': pos1, 'text': text}
    a.update(kw)
    return a


class Base(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tdir = tempfile.mkdtemp()
        cls.epub = os.path.join(cls.tdir, 'b.epub')
        make_epub(cls.epub)
        cls.book = Book(cls.epub)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tdir)


class PositionTests(Base):

    def test_spines(self):
        self.assertEqual(self.book.cre_spine, ['cover.xhtml', 'c1.xhtml', 'c2.xhtml'])
        self.assertEqual(self.book.calibre_spine, ['c1.xhtml', 'c2.xhtml', 'cover.xhtml'])

    def roundtrip(self, xp, expected_text_start):
        name, p = self.book.xpointer_to_point(xp)
        self.assertEqual(self.book.point_to_xpointer(name, p), xp)
        cfi = self.book.point_to_cfi(name, p)
        self.assertEqual(self.book.cfi_to_point(name, cfi), p)
        root = self.book.root(name)
        from kocalibre_highlights.positions import iter_text_slots, text_between
        slots = list(iter_text_slots(root))
        rest = text_between(root, p, slots[-1]._replace(offset=len(slots[-1].raw)))
        self.assertTrue(rest.startswith(expected_text_start), (xp, rest[:30]))
        return cfi

    def test_xpointers(self):
        # DocFragment[2] is c1 (cover is DocFragment[1])
        self.roundtrip('/body/DocFragment[2]/body/div/p[1]/text()[1].0', 'Primer')
        # Second text node of p[1], after <cite>; whitespace collapsed by crengine
        cfi = self.roundtrip('/body/DocFragment[2]/body/div/p[1]/text()[2].9', 'que sigue')
        # calibre counts offsets from the first text node of the parent, skipping <cite>
        self.assertEqual(cfi, '/2/4/4/2/1:' + str(len('Primer párrafo con ') + len(' y texto\n       ')))
        self.roundtrip('/body/DocFragment[2]/body/div/p[2]/text()[3].1', 'final')
        self.roundtrip('/body/DocFragment[2]/body/div/p[2]/b/text().3', 'negrita')
        self.roundtrip('/body/DocFragment[2]/body/h1/i/text().0', 'uno')
        self.roundtrip('/body/DocFragment[3]/body/p[2]/text().2', 'otro')

    def test_id_assertions_and_utf16(self):
        name, p = self.book.xpointer_to_point('/body/DocFragment[2]/body/div/p[3]/text().10')
        cfi = self.book.point_to_cfi(name, p)
        # Emoji is 2 UTF-16 code units: "Tercero 😀 " is 10 code points, 11 units
        self.assertEqual(cfi, '/2/4/4/6[p3]/1:11')
        self.assertEqual(self.book.cfi_to_point(name, cfi), p)
        self.assertEqual(self.book.point_to_xpointer(name, p), '/body/DocFragment[2]/body/div/p[3]/text().10')

    def test_explicit_indices(self):
        name, p = self.book.xpointer_to_point('/body/DocFragment[2]/body/div/p[2]/b/text().3')
        self.assertEqual(self.book.point_to_xpointer(name, p, explicit_first_index=True),
                         '/body/DocFragment[2]/body[1]/div[1]/p[2]/b[1]/text()[1].3')
        name2, p2 = self.book.xpointer_to_point('/body/DocFragment[2]/body[1]/div[1]/p[2]/b[1]/text()[1].3')
        self.assertEqual(p2, p)


class LuaTests(unittest.TestCase):

    def test_roundtrip(self):
        d = {'annotations': [{'text': 'a "b"\nc\\d', 'pageno': 3, 'x': 0.25, 'ok': True}], 'n': {}}
        s = luatable.dumps(d)
        self.assertEqual(luatable.loads(s)['annotations'][1]['text'], 'a "b"\nc\\d')
        self.assertIn('[1] = {', s)
        self.assertEqual(luatable.dumps(luatable.loads(s)), s)


class StyleTests(unittest.TestCase):

    def test_roundtrip(self):
        for c in ('red', 'orange', 'yellow', 'green', 'olive', 'cyan', 'blue', 'purple', 'gray'):
            for d in ('lighten', 'underscore', 'strikeout'):
                self.assertEqual(ko_style_key(*calibre_style_to_ko(ko_to_calibre_style(c, d))), (c, d))


class ColumnTests(unittest.TestCase):

    def test_formats(self):
        old = "<p>x</p><!-- 1: {'chapter': '1', 'datetime': '2025-05-14 21:02:12', 'drawer': 'lighten', 'pos0': 'a', 'pos1': 'b', 'text': 'T, u'} -->"
        new = '<p>x</p> <!-- chapter: Ocho, color: gray, datetime: 2026-07-28 00:35:20, drawer: lighten, page: /p, pageno: 452, pos0: /a, pos1: /b, text: Uno, dos: tres -->'
        self.assertEqual(annotations_from_column(old)[0]['text'], 'T, u')
        a = annotations_from_column(new)[0]
        self.assertEqual((a['text'], a['pageno'], a['pos1']), ('Uno, dos: tres', 452, '/b'))


P1 = ('/body/DocFragment[2]/body/div/p[1]/text()[1].0', '/body/DocFragment[2]/body/div/p[1]/text()[1].14')
P2 = ('/body/DocFragment[2]/body/div/p[2]/b/text().3', '/body/DocFragment[2]/body/div/p[2]/b/text().10')


class SyncTests(Base):

    def syncer(self):
        return BookSync(self.book, 'book-uuid', timedelta(hours=2))

    def first_sync(self):
        s = self.syncer()
        ko = [ko_hl(*P1, 'Primer párrafo'), {'page': '/x', 'datetime': '2026-01-01 09:00:00', 'text': 'in Uno'}]
        res = s.sync(ko, [], None)
        return s, ko, res

    def test_ko_to_calibre(self):
        s, ko, res = self.first_sync()
        self.assertEqual(len(res.calibre_changes), 1)
        c = res.calibre_changes[0]
        self.assertEqual(c['uuid'], calibre_uuid_for('book-uuid', P1))
        self.assertEqual((c['spine_name'], c['spine_index']), ('c1.xhtml', 0))
        self.assertEqual(c['timestamp'], '2026-01-01T08:00:00.000Z')
        self.assertEqual(c['style']['friendly_name'], 'KOReader gray')
        self.assertFalse(res.koreader_changed)
        self.assertEqual(set(res.state), {P1})
        # Second sync is a no-op
        res2 = s.sync(ko, res.calibre_changes, res.state)
        self.assertEqual((res2.calibre_changes, res2.koreader_changed), ([], False))

    def test_calibre_to_ko(self):
        s, ko, res = self.first_sync()
        calibre = list(res.calibre_changes)
        name, p0 = self.book.xpointer_to_point(P2[0])
        _, p1 = self.book.xpointer_to_point(P2[1])
        calibre.append({'type': 'highlight', 'uuid': 'newone', 'spine_name': name, 'spine_index': 0,
                        'start_cfi': self.book.point_to_cfi(name, p0), 'end_cfi': self.book.point_to_cfi(name, p1),
                        'highlighted_text': 'negrita', 'notes': 'nota',
                        'style': {'kind': 'color', 'type': 'builtin', 'which': 'blue'},
                        'timestamp': '2026-02-01T12:00:00.000Z', 'toc_family_titles': ['Uno']})
        res2 = s.sync(ko, calibre, res.state)
        self.assertTrue(res2.koreader_changed)
        new = [a for a in res2.koreader_annotations if a.get('pos0') == P2[0]][0]
        self.assertEqual((new['pos1'], new['color'], new['note'], new['datetime']),
                         (P2[1], 'blue', 'nota', '2026-02-01 14:00:00'))
        # page bookmark is preserved
        self.assertTrue(any(a.get('text') == 'in Uno' for a in res2.koreader_annotations))
        self.assertEqual(set(res2.state), {P1, P2})
        # Next sync with KOReader having imported it: no-op
        res3 = s.sync(res2.koreader_annotations, calibre, res2.state)
        self.assertEqual((res3.calibre_changes, res3.koreader_changed), ([], False))

    def test_delete_in_calibre(self):
        s, ko, res = self.first_sync()
        tomb = [dict(BookSync.tombstone(res.calibre_changes[0]))]
        res2 = s.sync(ko, tomb, res.state)
        self.assertTrue(res2.koreader_changed)
        self.assertFalse(any(a.get('pos0') == P1[0] for a in res2.koreader_annotations))
        self.assertEqual(len(res2.koreader_annotations), 1)  # bookmark stays
        self.assertEqual(res2.state, {})

    def test_delete_in_koreader(self):
        s, ko, res = self.first_sync()
        res2 = s.sync([ko[1]], res.calibre_changes, res.state)
        self.assertEqual(len(res2.calibre_changes), 1)
        self.assertTrue(res2.calibre_changes[0]['removed'])
        self.assertFalse(res2.koreader_changed)

    def test_edits_newest_wins(self):
        s, ko, res = self.first_sync()
        calibre = [dict(res.calibre_changes[0], notes='desde calibre', timestamp='2026-03-01T00:00:00.000Z')]
        res2 = s.sync(ko, calibre, res.state)
        k = [a for a in res2.koreader_annotations if a.get('pos0') == P1[0]][0]
        self.assertEqual((k['note'], k['datetime_updated']), ('desde calibre', '2026-03-01 02:00:00'))
        # Then edited again in KOReader, later
        ko2 = [dict(k, note='desde ko', color='green', datetime_updated='2026-04-01 10:00:00')]
        res3 = s.sync(ko2, calibre, res2.state)
        c = res3.calibre_changes[0]
        self.assertEqual((c['notes'], c['style']['which'], c['timestamp']),
                         ('desde ko', 'green', '2026-04-01T08:00:00.000Z'))
        self.assertFalse(res3.koreader_changed)

    def test_readonly_source(self):
        s, ko, res = self.first_sync()
        # Deleted in calibre: a stale column copy must not resurrect it, even without state
        tomb = [BookSync.tombstone(res.calibre_changes[0])]
        res2 = s.sync(ko, tomb, None, can_write_koreader=False)
        self.assertEqual(res2.calibre_changes, [])
        # Calibre only highlights are never deleted from a read-only source
        res3 = s.sync([], res.calibre_changes, res.state, can_write_koreader=False)
        self.assertEqual(res3.calibre_changes, [])
        self.assertEqual(res3.state, {})

    def test_import_emulation(self):
        a = ko_hl(*P1, 'x', dt='2026-01-01 10:00:00')
        b = ko_hl(*P2, 'y', dt='2026-01-02 10:00:00')
        late = ko_hl('/l0', '/l1', 'late', dt='2026-05-01 00:00:00')
        # Import removes b (older than import, not in it), keeps late, updates a
        a2 = dict(a, note='n', datetime_updated='2026-02-01 00:00:00')
        out = apply_koreader_import([a, b, late], [a2], '2026-03-01 00:00:00')
        self.assertEqual([x['text'] for x in out], ['late', 'x'])
        self.assertEqual(out[1]['note'], 'n')

    def test_times(self):
        self.assertEqual(parse_calibre_ts('2025-09-29T14:52:40.784Z').microsecond, 784000)


def run():
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c)
                               for c in (PositionTests, LuaTests, StyleTests, ColumnTests, SyncTests))
    r = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if r.wasSuccessful() else 1)


run()
