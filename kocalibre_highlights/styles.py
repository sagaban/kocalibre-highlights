"""Mapping between KOReader highlight colors/drawers and calibre highlight styles."""

# KOReader's highlight colors (frontend/apps/reader/modules/readerhighlight.lua)
KO_COLORS = {
    'red': '#FF3300',
    'orange': '#FF8800',
    'yellow': '#FFFF33',
    'green': '#00AA66',
    'olive': '#88FF77',
    'cyan': '#00FFEE',
    'blue': '#0066FF',
    'purple': '#EE00FF',
    'gray': '#808080',
}

# Colors calibre has builtin styles for
CALIBRE_BUILTIN_COLORS = ('yellow', 'green', 'blue', 'red', 'purple')

# Custom calibre styles for KOReader colors without a builtin equivalent
CUSTOM_COLORS = {
    'gray': ('#c8c8c8', '#5a5a5a'),
    'orange': ('#ffc58a', '#a35a00'),
    'olive': ('#c8f5b8', '#4f7a3a'),
    'cyan': ('#a8fff8', '#00807a'),
}

FRIENDLY_PREFIX = 'KOReader '
DEFAULT_COLOR = 'yellow'
DEFAULT_DRAWER = 'lighten'


def ko_to_calibre_style(color, drawer):
    color = (color or DEFAULT_COLOR).lower()
    drawer = drawer or DEFAULT_DRAWER
    if drawer in ('strikeout', 'underscore'):
        return {
            'kind': 'decoration', 'type': 'custom',
            'text-decoration-line': 'line-through' if drawer == 'strikeout' else 'underline',
            'text-decoration-style': 'solid', 'text-decoration-color': KO_COLORS.get(color, KO_COLORS['gray']),
            'friendly_name': FRIENDLY_PREFIX + color,
        }
    if color in CALIBRE_BUILTIN_COLORS:
        return {'kind': 'color', 'type': 'builtin', 'which': color}
    light, dark = CUSTOM_COLORS.get(color, CUSTOM_COLORS['gray'])
    return {'kind': 'color', 'type': 'custom', 'light': light, 'dark': dark,
            'friendly_name': FRIENDLY_PREFIX + color}


def _hex_to_rgb(h):
    h = (h or '').lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def nearest_ko_color(hex_color):
    rgb = _hex_to_rgb(hex_color)
    if rgb is None:
        return DEFAULT_COLOR
    palette = dict(KO_COLORS)
    # Also compare with the light variants we use for custom colors
    for name, (light, dark) in CUSTOM_COLORS.items():
        palette[name + ':light'] = light

    def dist(item):
        c = _hex_to_rgb(item[1])
        return sum((a - b) ** 2 for a, b in zip(rgb, c))

    best = min(palette.items(), key=dist)[0]
    return best.partition(':')[0]


def _ko_name_from_friendly(style):
    name = style.get('friendly_name') or ''
    if name.startswith(FRIENDLY_PREFIX):
        c = name[len(FRIENDLY_PREFIX):]
        if c in KO_COLORS:
            return c
    return None


def calibre_style_to_ko(style):
    '''Return (color, drawer) for a calibre highlight style'''
    if not style:
        return DEFAULT_COLOR, DEFAULT_DRAWER
    kind, typ = style.get('kind'), style.get('type')
    if kind == 'decoration':
        if typ == 'builtin':
            if style.get('which') == 'strikeout':
                return 'red', 'strikeout'
            return 'red', 'underscore'  # wavy
        color = _ko_name_from_friendly(style) or nearest_ko_color(style.get('text-decoration-color'))
        line = style.get('text-decoration-line') or ''
        return color, ('strikeout' if 'line-through' in line else 'underscore')
    if typ == 'builtin':
        which = style.get('which')
        return (which if which in KO_COLORS else DEFAULT_COLOR), DEFAULT_DRAWER
    return (_ko_name_from_friendly(style) or nearest_ko_color(style.get('light'))), DEFAULT_DRAWER


def ko_style_key(color, drawer):
    '''Normalized style used to compare both sides'''
    color = (color or DEFAULT_COLOR).lower()
    drawer = drawer or DEFAULT_DRAWER
    if drawer == 'invert':
        drawer = DEFAULT_DRAWER
    return color, drawer
