"""Read KOReader annotations from the HTML column written by the KOReader Sync plugin.

That plugin renders the annotations as HTML for display, and embeds the raw
data inside HTML comments, in one of two formats depending on its version:

* one comment with a Python dict repr of all annotations:
  ``<!-- 1: {'chapter': ..., 'pos0': ..., 'text': ...}, 2: {...} -->``
* one comment per annotation with unquoted, alphabetically sorted fields:
  ``<!-- chapter: Ocho, color: gray, ..., pos0: ..., text: Puede que... -->``
"""

import ast
import re

_COMMENT_RE = re.compile(r'<!--(.*?)-->', re.DOTALL)
KNOWN_KEYS = ('chapter', 'color', 'datetime', 'datetime_updated', 'drawer', 'note', 'note_format',
              'page', 'pageno', 'pageref', 'pos0', 'pos1', 'text', 'text_edited')
_FIELD_RE = re.compile(r'(?:^|, )(' + '|'.join(KNOWN_KEYS) + r'): ')


def _parse_fields(body):
    matches = list(_FIELD_RE.finditer(body))
    if not matches or matches[0].start() != 0:
        return None
    ans = {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        val = body[m.end():end]
        if m.group(1) in ('pageno', 'pageref') and val.isdigit():
            val = int(val)
        elif val in ('True', 'False'):
            val = val == 'True'
        ans[m.group(1)] = val
    return ans


def annotations_from_column(html):
    if not html:
        return []
    found = {}
    seq = 0
    for m in _COMMENT_RE.finditer(html):
        body = m.group(1).strip()
        if not body:
            continue
        if not re.match(r'^\d+\s*:', body):
            fields = _parse_fields(body)
            if fields:
                seq += 1
                found[seq] = fields
            continue
        try:
            data = ast.literal_eval('{' + body + '}')
        except (ValueError, SyntaxError):
            continue
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, dict):
                    found[k] = v
    return [found[k] for k in sorted(found)]
