'''Validate position conversion against real KOReader sidecars and calibre annotations.

Run with: calibre-debug tests/validate_real_data.py <sidecar_dir> <calibre_library>
'''
import glob
import json
import os
import re
import sqlite3
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kocalibre_highlights import luatable  # noqa
from kocalibre_highlights.positions import Book, PositionError, normalize_text  # noqa

sdr_dir, lib = sys.argv[1], sys.argv[2]
verbose = '-v' in sys.argv
stats = Counter()


def check(ok, key, detail):
    stats[key + (':ok' if ok else ':FAIL')] += 1
    if not ok and verbose:
        print('  FAIL', key, detail)


books = {}


def book_for(book_id):
    if book_id not in books:
        epubs = glob.glob(f'{lib}/*/*({book_id})/*.epub')
        books[book_id] = Book(epubs[0]) if epubs else None
    return books[book_id]


# KOReader -> calibre -> KOReader
for sdrf in sorted(glob.glob(sdr_dir + '/**/metadata.epub.lua', recursive=True)):
    m = re.search(r'\((\d+)\)\.sdr', sdrf)
    if not m:
        continue
    d = luatable.loads(open(sdrf, encoding='utf-8').read())
    anns = [a for a in luatable.to_list(d.get('annotations')) if a.get('pos0')]
    if not anns:
        continue
    book = book_for(int(m.group(1)))
    if book is None:
        stats['no_epub'] += len(anns)
        continue
    if verbose:
        print('#', os.path.basename(sdrf))
    for a in anns:
        try:
            n0, p0 = book.xpointer_to_point(a['pos0'])
            n1, p1 = book.xpointer_to_point(a['pos1'])
        except PositionError as e:
            check(False, 'resolve', (a['pos0'], e))
            continue
        want = normalize_text(a['text'])
        got = normalize_text(book.text(n0, p0, p1)) if n0 == n1 else None
        # crengine's pos1 points at the last char (inclusive) in older versions
        ok = got == want or (got is not None and want.startswith(got) and len(want) - len(got) <= 1)
        check(ok, 'text', (a['pos0'], got and got[:60], want[:60]))
        c0, c1 = book.point_to_cfi(n0, p0), book.point_to_cfi(n1, p1)
        q0, q1 = book.cfi_to_point(n0, c0), book.cfi_to_point(n1, c1)
        check(q0 == p0 and q1 == p1, 'cfi_roundtrip', (a['pos0'], c0, p0, q0))
        x0, x1 = book.point_to_xpointer(n0, q0), book.point_to_xpointer(n1, q1)
        check(x0 == a['pos0'] and x1 == a['pos1'], 'xp_roundtrip', (a['pos0'], x0, a['pos1'], x1))

# calibre -> KOReader -> calibre
db = sqlite3.connect(f'file:{lib}/metadata.db?mode=ro', uri=True)
for book_id, fmt, data in db.execute("select book, format, annot_data from annotations where annot_type='highlight'"):
    a = json.loads(data)
    if a.get('removed') or fmt != 'EPUB':
        continue
    book = book_for(book_id)
    name = a['spine_name']
    check(book.spine_index(name) == a['spine_index'], 'spine_index', (name, a['spine_index']))
    p0, p1 = book.cfi_to_point(name, a['start_cfi']), book.cfi_to_point(name, a['end_cfi'])
    got = normalize_text(book.text(name, p0, p1))
    check(got == normalize_text(a['highlighted_text']), 'calibre_text', (got[:60], a['highlighted_text'][:60]))
    check(book.point_to_cfi(name, p0) == a['start_cfi'] and book.point_to_cfi(name, p1) == a['end_cfi'],
          'calibre_cfi_roundtrip', (a['start_cfi'], book.point_to_cfi(name, p0)))
    x0 = book.point_to_xpointer(name, p0)
    n2, back = book.xpointer_to_point(x0)
    check(back == p0, 'calibre_xp_roundtrip', (a['start_cfi'], x0))

for k in sorted(stats):
    print(f'{k:28} {stats[k]}')
