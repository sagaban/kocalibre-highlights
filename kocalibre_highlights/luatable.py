"""Minimal reader/writer for KOReader sidecar files (metadata.*.lua).

Sidecars are produced by KOReader's `dump()` and only contain a single
`return { ... }` table literal with strings, numbers, booleans and nested
tables, so a small recursive-descent parser is enough.
"""

import re

_NUM_RE = re.compile(r'-?(?:0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)')
_IDENT_RE = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
_ESCAPES = {'n': '\n', 't': '\t', 'r': '\r', 'a': '\a', 'b': '\b', 'f': '\f',
            'v': '\v', '\\': '\\', '"': '"', "'": "'", '\n': '\n'}


class LuaParseError(ValueError):
    pass


class _Parser:

    def __init__(self, src):
        self.s = src
        self.i = 0

    def error(self, msg):
        line = self.s.count('\n', 0, self.i) + 1
        raise LuaParseError(f'{msg} at line {line}')

    def skip(self):
        s, n = self.s, len(self.s)
        while self.i < n:
            c = s[self.i]
            if c in ' \t\r\n':
                self.i += 1
            elif s.startswith('--', self.i):
                if s.startswith('--[[', self.i):
                    end = s.find(']]', self.i)
                    self.i = n if end < 0 else end + 2
                else:
                    end = s.find('\n', self.i)
                    self.i = n if end < 0 else end + 1
            else:
                break

    def peek(self):
        self.skip()
        return self.s[self.i] if self.i < len(self.s) else ''

    def expect(self, ch):
        if self.peek() != ch:
            self.error(f'Expected {ch!r}')
        self.i += 1

    def value(self):
        c = self.peek()
        if c == '{':
            return self.table()
        if c in '"\'':
            return self.string()
        if c == '[' and self.s.startswith(('[[', '[=['), self.i):
            return self.long_string()
        m = _NUM_RE.match(self.s, self.i)
        if m:
            self.i = m.end()
            t = m.group()
            if t.lower().lstrip('-').startswith('0x'):
                return int(t, 16)
            if any(x in t for x in '.eE'):
                return float(t)
            return int(t)
        m = _IDENT_RE.match(self.s, self.i)
        if m:
            self.i = m.end()
            word = m.group()
            if word == 'true':
                return True
            if word == 'false':
                return False
            if word == 'nil':
                return None
            self.error(f'Unexpected identifier {word!r}')
        self.error('Unexpected character')

    def string(self):
        q = self.s[self.i]
        self.i += 1
        out = []
        s = self.s
        while True:
            if self.i >= len(s):
                self.error('Unterminated string')
            c = s[self.i]
            if c == q:
                self.i += 1
                break
            if c == '\\':
                self.i += 1
                e = s[self.i]
                if e in _ESCAPES:
                    out.append(_ESCAPES[e])
                    self.i += 1
                elif e.isdigit():
                    m = re.match(r'\d{1,3}', s[self.i:])
                    out.append(chr(int(m.group())))
                    self.i += len(m.group())
                elif e == 'x':
                    out.append(chr(int(s[self.i + 1:self.i + 3], 16)))
                    self.i += 3
                elif e == 'u':
                    end = s.index('}', self.i)
                    out.append(chr(int(s[self.i + 2:end], 16)))
                    self.i = end + 1
                elif e == 'z':
                    self.i += 1
                    while self.i < len(s) and s[self.i] in ' \t\r\n':
                        self.i += 1
                else:
                    self.error(f'Bad escape \\{e}')
            else:
                out.append(c)
                self.i += 1
        raw = ''.join(out)
        # Decimal escapes produce bytes, re-decode them as UTF-8 if needed
        if any(0x80 <= ord(ch) <= 0xff for ch in raw):
            try:
                raw = raw.encode('latin-1').decode('utf-8')
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass
        return raw

    def long_string(self):
        m = re.match(r'\[(=*)\[', self.s[self.i:])
        close = ']' + m.group(1) + ']'
        start = self.i + len(m.group())
        end = self.s.find(close, start)
        if end < 0:
            self.error('Unterminated long string')
        self.i = end + len(close)
        text = self.s[start:end]
        return text[1:] if text.startswith('\n') else text

    def table(self):
        self.expect('{')
        result = {}
        auto = 1
        while True:
            c = self.peek()
            if c == '}':
                self.i += 1
                break
            if c == '[' and not self.s.startswith(('[[', '[=['), self.i):
                self.i += 1
                key = self.value()
                self.expect(']')
                self.expect('=')
                result[key] = self.value()
            else:
                m = _IDENT_RE.match(self.s, self.i)
                save = self.i
                if m and m.group() not in ('true', 'false', 'nil'):
                    self.i = m.end()
                    if self.peek() == '=':
                        self.i += 1
                        result[m.group()] = self.value()
                    else:
                        self.i = save
                        result[auto] = self.value()
                        auto += 1
                else:
                    result[auto] = self.value()
                    auto += 1
            c = self.peek()
            if c in ',;':
                self.i += 1
            elif c != '}':
                self.error('Expected , or }')
        return result


def loads(src):
    p = _Parser(src)
    p.skip()
    if p.s.startswith('return', p.i):
        p.i += len('return')
    val = p.value()
    if p.peek():
        p.error('Trailing data')
    return val


def is_array(d):
    return isinstance(d, dict) and len(d) > 0 and all(
        isinstance(k, int) and not isinstance(k, bool) for k in d) and set(d) == set(range(1, len(d) + 1))


def to_list(d):
    '''Convert a Lua array table (dict with keys 1..n) to a Python list.'''
    if isinstance(d, list):
        return d
    if not d:
        return []
    return [d[k] for k in sorted(d)]


def _quote(s):
    # Mirrors Lua's string.format("%q"), which KOReader's dump() uses
    out = ['"']
    for c in s:
        if c == '\\':
            out.append('\\\\')
        elif c == '"':
            out.append('\\"')
        elif c == '\n':
            out.append('\\\n')
        elif c == '\r':
            out.append('\\r')
        elif c == '\0':
            out.append('\\0')
        elif ord(c) < 32 or ord(c) == 127:
            out.append('\\%d' % ord(c))
        else:
            out.append(c)
    out.append('"')
    return ''.join(out)


def _key_sort(k):
    # KOReader's dump() orders numbers before strings, each group sorted
    return (0, k, '') if isinstance(k, (int, float)) and not isinstance(k, bool) else (1, 0, str(k))


def _dump(val, indent, out):
    if isinstance(val, bool):
        out.append('true' if val else 'false')
    elif isinstance(val, int):
        out.append(str(val))
    elif isinstance(val, float):
        out.append('%.14g' % val)
    elif isinstance(val, str):
        out.append(_quote(val))
    elif isinstance(val, (list, tuple)):
        _dump({i + 1: v for i, v in enumerate(val)}, indent, out)
    elif isinstance(val, dict):
        if not val:
            out.append('{}')
            return
        pad = '    ' * (indent + 1)
        out.append('{\n')
        for k in sorted(val, key=_key_sort):
            v = val[k]
            if v is None:
                continue
            kk = str(k) if isinstance(k, int) and not isinstance(k, bool) else _quote(str(k))
            out.append(f'{pad}[{kk}] = ')
            _dump(v, indent + 1, out)
            out.append(',\n')
        out.append('    ' * indent + '}')
    elif val is None:
        out.append('nil')
    else:
        raise TypeError(f'Cannot serialize {type(val)}')


def dumps(val, header=None):
    '''Serialize like KOReader's LuaSettings:flush() does.'''
    out = []
    if header:
        out.append(header.rstrip('\n') + '\n')
    out.append('return ')
    _dump(val, 0, out)
    out.append('\n')
    return ''.join(out)
