"""Book level data from KOReader's sidecar (read status, rating, review) to calibre columns.

One way, KOReader -> calibre. A value is written to calibre only when it changed
in KOReader since the last sync (or on the first sync), so edits made by hand in
calibre are kept until the value is changed again on the device.
"""

# setting name -> (sidecar summary key, accepted calibre datatypes)
FIELDS = {
    'read_column': ('status', ('bool',)),
    'rating_column': ('rating', ('rating', 'int', 'float')),
    'review_column': ('note', ('comments', 'text')),
}


def koreader_values(sidecar):
    '''Values for each field from a parsed sidecar; None means "no value"'''
    summary = (sidecar or {}).get('summary') or {}
    status = summary.get('status')
    rating = summary.get('rating')
    note = summary.get('note')
    return {
        'read_column': (status == 'complete') if status else None,
        'rating_column': int(rating) * 2 if isinstance(rating, (int, float)) and rating > 0 else None,
        'review_column': (note.strip() or None) if isinstance(note, str) else None,
    }


def check_columns(field_metadata, prefs):
    '''Return ({setting: column}, [errors]) for the configured, valid columns'''
    columns, errors = {}, []
    for setting, (key, datatypes) in FIELDS.items():
        col = (prefs.get(setting) or '').strip()
        if not col:
            continue
        fm = field_metadata.get(col)
        if fm is None:
            errors.append(f'La columna {col} no existe')
        elif fm.get('datatype') not in datatypes:
            errors.append(f'La columna {col} es de tipo {fm.get("datatype")}, se esperaba {"/".join(datatypes)}')
        else:
            columns[setting] = col
    return columns, errors


def changes_for_book(values, last_seen, current):
    '''
    values: koreader_values() now
    last_seen: values recorded at the last sync, or None
    current: {setting: current calibre value}
    Returns {setting: new calibre value}
    '''
    ans = {}
    for setting, current_value in current.items():
        v = values.get(setting)
        prev = None if last_seen is None else last_seen.get(setting)
        if last_seen is not None and v == prev:
            continue  # unchanged in KOReader: keep whatever calibre has
        if v is None and prev is None:
            continue
        if _normalize(current_value) != _normalize(v):
            ans[setting] = v
    return ans


def _normalize(v):
    # calibre stores an empty rating as 0 or None and an empty comment as ''
    if v is None or v == '' or (v == 0 and not isinstance(v, bool)):
        return None
    return v
