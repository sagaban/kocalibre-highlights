"""Conversion between KOReader (crengine) XPointers and calibre viewer CFIs.

Both formats address a position inside one spine item (HTML file) of an EPUB:

* KOReader: ``/body/DocFragment[12]/body/div/p[3]/text()[2].42``
  DocFragment[N] is the Nth XHTML item of the OPF spine (in OPF order). Element
  steps count same-name siblings, text() steps count text nodes and the final
  offset counts code points in crengine's text, where (outside of <pre>) runs
  of ASCII whitespace are collapsed into a single space and whitespace-only
  text that is the first child of a block element is dropped.

* calibre: ``spine_index`` (index into the container spine, linear items first),
  plus a CFI such as ``/2/4/344/1:278``: even steps are elements, odd steps are
  runs of text between elements and offsets count UTF-16 code units from the
  start of the run. Elements with a unique id get an ``[id]`` assertion.

Positions are converted through a common representation, a ``Point``: a text
slot of the lxml tree (an element's ``.text`` or ``.tail``) plus an offset in
code points into that raw string.
"""

import re
from collections import namedtuple

from lxml import etree

XHTML_NS = 'http://www.w3.org/1999/xhtml'

# Elements crengine treats as blocks by default (it drops whitespace-only text
# when it is the first child of a block element)
BLOCK_TAGS = frozenset('''
address article aside blockquote body center dd details dialog dir div dl dt
fieldset figcaption figure footer form h1 h2 h3 h4 h5 h6 header hgroup hr html
li main menu nav ol p pre section summary table tbody td tfoot th thead tr ul
caption colgroup col legend optgroup option
'''.split())

PRE_TAGS = frozenset(('pre', 'textarea', 'listing', 'plaintext', 'xmp'))

_WS_COLLAPSE = re.compile(r'[ \t\r\n]+')


class PositionError(ValueError):
    pass


class Point(namedtuple('Point', 'owner kind offset')):
    '''owner: lxml element; kind: 'text' (owner.text) or 'tail' (owner.tail);
    offset: code point offset into that raw string. kind may also be 'elem' for
    a position at the start of an element that has no text.'''

    @property
    def raw(self):
        if self.kind == 'elem':
            return ''
        return (self.owner.text if self.kind == 'text' else self.owner.tail) or ''

    @property
    def parent(self):
        return self.owner if self.kind in ('text', 'elem') else self.owner.getparent()


def local_name(el):
    tag = el.tag
    if not isinstance(tag, str):
        return None
    return tag.rpartition('}')[2].lower()


def is_element(node):
    return isinstance(node.tag, str)


def utf16_len(s):
    return len(s) + sum(1 for c in s if ord(c) > 0xffff)


def utf16_to_cp(s, n):
    '''Convert a UTF-16 offset into s to a code point offset'''
    units = 0
    for i, c in enumerate(s):
        if units >= n:
            return i
        units += 2 if ord(c) > 0xffff else 1
    return len(s)


def utf16_offset(s, cp):
    return utf16_len(s[:cp])


def find_body(root):
    for el in root.iterchildren():
        if local_name(el) == 'body':
            return el
    raise PositionError('Document has no body')


def in_pre(el):
    while el is not None:
        if local_name(el) in PRE_TAGS:
            return True
        el = el.getparent()
    return False


# crengine model {{{

def cre_children(el):
    '''Yield the children crengine has in its DOM for el, as tuples
    ('elem', element) or ('text', Point at offset 0).'''
    pre = in_pre(el)
    block = local_name(el) in BLOCK_TAGS
    seen_any = False

    def text_node(owner, kind, raw):
        nonlocal seen_any
        if not raw:
            return None
        if not pre and block and not seen_any and not raw.strip(' \t\r\n'):
            return None  # first empty space of a non-pre block is ignored
        seen_any = True
        return ('text', Point(owner, kind, 0))

    t = text_node(el, 'text', el.text)
    if t:
        yield t
    for child in el.iterchildren():
        if is_element(child):
            seen_any = True
            yield ('elem', child)
        t = text_node(child, 'tail', child.tail)
        if t:
            yield t


def cre_text(raw, pre):
    if pre:
        return raw.replace('\r\n', '\n').replace('\r', '\n')
    return _WS_COLLAPSE.sub(lambda m: ' ', raw) if raw else raw


def raw_to_cre_offset(raw, offset, pre):
    return len(cre_text(raw[:offset], pre))


def cre_to_raw_offset(raw, cre_offset, pre):
    if pre:
        # only \r\n -> \n changes lengths
        count = 0
        i = 0
        while i < len(raw) and count < cre_offset:
            i += 2 if raw.startswith('\r\n', i) else 1
            count += 1
        return i
    count = 0
    i = 0
    n = len(raw)
    while i < n and count < cre_offset:
        if raw[i] in ' \t\r\n':
            while i < n and raw[i] in ' \t\r\n':
                i += 1
        else:
            i += 1
        count += 1
    return i


_STEP_RE = re.compile(r'^([^\[\]/]+?)(?:\[(\d+)\])?$')


def parse_xpointer(xp):
    '''Return (docfragment_index (1-based), steps, offset) for an XPointer'''
    m = re.match(r'^/body/DocFragment(?:\[(\d+)\])?(/.*)?$', xp)
    if not m:
        raise PositionError(f'Unsupported XPointer: {xp}')
    frag = int(m.group(1) or 1)
    rest = m.group(2) or ''
    offset = None
    m2 = re.search(r'\.(\d+)$', rest)
    if m2:
        offset = int(m2.group(1))
        rest = rest[:m2.start()]
    steps = []
    for part in rest.split('/'):
        if not part:
            continue
        ms = _STEP_RE.match(part)
        if not ms:
            raise PositionError(f'Bad XPointer step {part!r} in {xp}')
        steps.append((ms.group(1).lower(), int(ms.group(2) or 1)))
    return frag, steps, offset


def resolve_xpointer_steps(root, steps, offset):
    '''Resolve the steps (starting with body) of an XPointer to a Point'''
    if not steps or steps[0][0] != 'body':
        raise PositionError('XPointer does not start with body')
    el = find_body(root)
    for i, (name, idx) in enumerate(steps[1:], 1):
        if name == 'text()':
            texts = [p for kind, p in cre_children(el) if kind == 'text']
            if idx > len(texts):
                raise PositionError(f'text()[{idx}] not found')
            p = texts[idx - 1]
            if i != len(steps) - 1:
                raise PositionError('text() step is not last')
            raw = p.raw
            cp = cre_to_raw_offset(raw, offset or 0, in_pre(p.parent))
            return Point(p.owner, p.kind, cp)
        matches = [c for kind, c in cre_children(el) if kind == 'elem' and local_name(c) == name]
        if idx > len(matches):
            raise PositionError(f'{name}[{idx}] not found')
        el = matches[idx - 1]
    # Points to an element (offset is then a child index, if any)
    if offset:
        kids = list(cre_children(el))
        if offset < len(kids):
            kind, x = kids[offset]
            return x if kind == 'text' else first_point_in(x)
        return last_point_in(el)
    return first_point_in(el)


def first_point_in(el):
    '''First text position inside el, or el itself'''
    for kind, x in cre_children(el):
        if kind == 'text':
            return x
        p = first_point_in(x)
        if p.kind != 'elem':
            return p
    return Point(el, 'elem', 0)


def last_point_in(el):
    kids = list(cre_children(el))
    for kind, x in reversed(kids):
        if kind == 'text':
            return Point(x.owner, x.kind, len(x.raw))
        p = last_point_in(x)
        if p.kind != 'elem':
            return p
    return Point(el, 'elem', 0)


def point_to_xpointer_path(root, point, explicit_first_index=False):
    '''XPointer path (after DocFragment) for point'''
    pre = in_pre(point.parent)
    parent = point.parent
    if point.kind == 'elem':
        path = ''
        node = point.owner
    else:
        texts = [p for kind, p in cre_children(parent) if kind == 'text']
        idx = None
        for i, p in enumerate(texts):
            if p.owner is point.owner and p.kind == point.kind:
                idx = i + 1
                break
        if idx is None:
            # Text dropped by crengine (leading whitespace), point at parent
            path = ''
            node = parent
        else:
            off = raw_to_cre_offset(point.raw, point.offset, pre)
            step = 'text()' if (len(texts) == 1 and not explicit_first_index) else f'text()[{idx}]'
            path = f'/{step}.{off}'
            node = parent
    body = find_body(root)
    while node is not body:
        p = node.getparent()
        if p is None:
            raise PositionError('Node is not inside body')
        name = local_name(node)
        same = [c for kind, c in cre_children(p) if kind == 'elem' and local_name(c) == name]
        idx = next(i for i, c in enumerate(same) if c is node) + 1
        step = name if (len(same) == 1 and not explicit_first_index) else f'{name}[{idx}]'
        path = f'/{step}' + path
        node = p
    return ('/body[1]' if explicit_first_index else '/body') + path
# }}}


# CFI model {{{

def _cfi_children(el):
    '''The DOM children calibre's viewer has: elements and text (lxml text/tail)'''
    out = []
    if el.text:
        out.append(('text', Point(el, 'text', 0)))
    for child in el.iterchildren():
        out.append(('elem' if is_element(child) else 'other', child))
        if child.tail:
            out.append(('text', Point(child, 'tail', 0)))
    return out


def _unique_ids(root):
    counts = {}
    for el in root.iter():
        if is_element(el):
            i = el.get('id')
            if i:
                counts[i] = counts.get(i, 0) + 1
    return {k for k, v in counts.items() if v == 1}


def _escape_cfi(raw):
    return re.sub(r'([\[\],^();~@!])', r'^\1', raw)


def _unescape_cfi(raw):
    return re.sub(r'\^(.)', r'\1', raw)


def point_to_cfi(root, point, unique_ids=None):
    '''Encode point the way calibre's read_book/cfi.pyj encode() does.

    For text, calibre walks back over *all* previous siblings to the first
    child of the parent, summing the lengths of the direct text nodes it
    passes (element contents are not counted). The final step is the first
    child of the parent and the offset is that sum plus the offset in the
    text node.'''
    if unique_ids is None:
        unique_ids = _unique_ids(root)
    parent = point.parent
    if point.kind == 'elem':
        return _cfi_path(point.owner, unique_ids)
    children = _cfi_children(parent)
    offset = 0
    for kind, x in children:
        if kind == 'text':
            if _same_slot(x, point):
                offset += utf16_offset(x.raw, point.offset)
                break
            offset += utf16_len(x.raw)
    first_kind, first = children[0]
    if first_kind == 'text':
        path = _cfi_path(parent, unique_ids) + '/1'
    elif first_kind == 'elem':
        path = _cfi_path(first, unique_ids)
    else:
        path = _cfi_path(parent, unique_ids) + '/1'
    return f'{path}:{offset}'


def _cfi_path(node, unique_ids):
    path = ''
    while True:
        p = node.getparent()
        if p is None:
            return '/2' + _id_spec(node, unique_ids) + path  # html element
        index = 0
        for kind, x in _cfi_children(p):
            if kind == 'elem':
                index = (index | 1) + 1
                if x is node:
                    break
            else:
                index |= 1
        path = f'/{index}' + _id_spec(node, unique_ids) + path
        node = p


def _id_spec(node, unique_ids):
    i = node.get('id')
    if i and i in unique_ids:
        return '[' + _escape_cfi(i) + ']'
    return ''


_CFI_STEP = re.compile(r'^/(\d+)(\[((?:\^.|[^\]])*)\])?')


def cfi_to_point(root, cfi):
    '''Decode a CFI the way calibre's read_book/cfi.pyj decode() does'''
    unique_ids = None
    s = cfi
    if s.startswith('epubcfi('):
        s = s[8:-1]
    if '!' in s:
        s = s.split('!', 1)[1]
    node = None  # the document
    parent = None
    while True:
        m = _CFI_STEP.match(s)
        if not m:
            break
        target = int(m.group(1))
        assertion = _unescape_cfi(m.group(3)) if m.group(3) else None
        s = s[m.end():]
        if node is None:
            if target != 2:
                raise PositionError(f'Unexpected root step in CFI {cfi}')
            node = root
            continue
        if assertion:
            if unique_ids is None:
                unique_ids = _unique_ids(root)
            if assertion in unique_ids:
                q = root.xpath('//*[@id=$i]', i=assertion)
                if q:
                    parent, node = q[0].getparent(), q[0]
                    continue
        if isinstance(node, Point):
            raise PositionError(f'CFI step after a text node: {cfi}')
        children = _cfi_children(node)
        if target % 2 == 0:
            cands = [(k, x) for k, x in children if k == 'elem']
            idx = target // 2 - 1
        else:
            cands = [(k, x) for k, x in children if k == 'text']
            idx = target // 2
        if idx < 0 or idx >= len(cands):
            raise PositionError(f'No matching child for step {target} in CFI {cfi}')
        parent, node = node, cands[idx][1]
    m = re.match(r'^:(\d+)', s)
    if m is None:
        if isinstance(node, Point):
            return node
        return first_point_in(node)
    if parent is None:
        raise PositionError(f'Offset on root in CFI {cfi}')
    return _point_for_text_offset(parent, node, int(m.group(1)))


def _point_for_text_offset(parent, first_node, offset):
    last = None
    seen_first = False
    for kind, x in _cfi_children(parent):
        if not seen_first:
            if x is first_node or (kind == 'text' and isinstance(first_node, Point) and _same_slot(x, first_node)):
                seen_first = True
            else:
                continue
        if kind == 'text':
            l16 = utf16_len(x.raw)
            if offset <= l16:
                return Point(x.owner, x.kind, utf16_to_cp(x.raw, offset))
            offset -= l16
            last = x
    if last is not None:
        return Point(last.owner, last.kind, len(last.raw))
    if isinstance(first_node, Point):
        return first_node
    return first_point_in(first_node)
# }}}


# Text extraction {{{

def iter_text_slots(root):
    '''Yield all text slots of body in document order as Points at offset 0'''
    body = find_body(root)

    def walk(el):
        if el.text:
            yield Point(el, 'text', 0)
        for child in el.iterchildren():
            if is_element(child):
                yield from walk(child)
            if child.tail:
                yield Point(child, 'tail', 0)

    yield from walk(body)


def _same_slot(a, b):
    return a.owner is b.owner and a.kind == b.kind


def text_between(root, start, end):
    '''Raw text between two Points (in document order)'''
    start, end = _to_text_point(root, start), _to_text_point(root, end)
    out = []
    started = False
    for slot in iter_text_slots(root):
        raw = slot.raw
        s = 0
        if not started:
            if not _same_slot(slot, start):
                continue
            started = True
            s = start.offset
        if _same_slot(slot, end):
            out.append(raw[s:end.offset])
            break
        out.append(raw[s:])
    return ''.join(out)


def _to_text_point(root, p):
    if p.kind != 'elem':
        return p
    # First text slot at or after the element
    el = p.owner
    for slot in iter_text_slots(root):
        if slot.owner is el or el in slot.owner.iterancestors() or (
                slot.kind == 'tail' and el in slot.owner.itersiblings(preceding=True)):
            return slot
    return p


def normalize_text(t):
    return _WS_COLLAPSE.sub(' ', t or '').strip()
# }}}


# Spine handling {{{

def opf_xhtml_spine(container):
    '''Names of the spine items in the order crengine numbers DocFragments'''
    media_types = {item.get('id'): item.get('media-type')
                   for item in container.opf_xpath('//opf:manifest/opf:item[@id]')}
    id_map = container.manifest_id_map
    ans = []
    for item in container.opf_xpath('//opf:spine/opf:itemref[@idref]'):
        idref = item.get('idref')
        name = id_map.get(idref)
        if name is not None and media_types.get(idref) == 'application/xhtml+xml':
            ans.append(name)
    return ans


class Book:
    '''Wraps a calibre container for an EPUB and converts positions'''

    def __init__(self, path_to_epub):
        from calibre.ebooks.oeb.polish.container import get_container
        self.container = get_container(path_to_epub, tweak_mode=True)
        self.cre_spine = opf_xhtml_spine(self.container)
        self.calibre_spine = [name for name, linear in self.container.spine_names]
        self._parsed = {}
        self._ids = {}

    def root(self, name):
        if name not in self._parsed:
            self._parsed[name] = self.container.parsed(name)
        return self._parsed[name]

    def unique_ids(self, name):
        if name not in self._ids:
            self._ids[name] = _unique_ids(self.root(name))
        return self._ids[name]

    # KOReader -> point
    def xpointer_to_point(self, xp):
        frag, steps, offset = parse_xpointer(xp)
        if frag < 1 or frag > len(self.cre_spine):
            raise PositionError(f'DocFragment[{frag}] out of range')
        name = self.cre_spine[frag - 1]
        return name, resolve_xpointer_steps(self.root(name), steps, offset)

    def point_to_xpointer(self, name, point, explicit_first_index=False):
        frag = self.cre_spine.index(name) + 1
        path = point_to_xpointer_path(self.root(name), point, explicit_first_index)
        return f'/body/DocFragment[{frag}]' + path

    # calibre -> point
    def cfi_to_point(self, spine_name, cfi):
        return cfi_to_point(self.root(spine_name), cfi)

    def point_to_cfi(self, name, point):
        return point_to_cfi(self.root(name), point, self.unique_ids(name))

    def spine_index(self, name):
        return self.calibre_spine.index(name)

    def text(self, name, start, end):
        return text_between(self.root(name), start, end)
# }}}
