# AGENTS.md

Context for AI coding agents working on this repository. See README.md for the user-facing docs.

## What this is

A calibre plugin (`kocalibre_highlights/`) that syncs highlights and notes both ways between
KOReader (crengine, EPUB) and the calibre e-book viewer, plus one-way KOReader → calibre sync of
read status, rating and review. It talks to the device over KOReader's SSH server.

## Commands

All Python runs inside calibre's bundled interpreter (it provides lxml, Qt and `calibre.*`):

```sh
calibre-debug -e tests/test_sync.py                    # unit tests (synthetic EPUB, no device)
calibre-debug -e tests/validate_real_data.py -- <sidecar dir> <calibre library>   # real-data check
./build.sh                                             # build "KOReader Highlights Sync.zip"
./i18n.sh                                              # re-extract strings, merge into .po files
```

On macOS `calibre-debug` is `/Applications/calibre.app/Contents/MacOS/calibre-debug`. Note
`calibre-debug -e script.py -- args`: script arguments go after `--`.
Under `calibre-debug -e`, `__name__` is not `"__main__"`, so the test file calls `run()` directly.

## Layout

| Module | Role |
|---|---|
| `positions.py` | XPointer ↔ CFI conversion through a common `Point` (lxml text slot + code point offset) |
| `sync.py` | Pure per-book sync engine (`BookSync.sync`), KOReader import emulation, time helpers |
| `engine.py` | Orchestration: device scan, calibre db, state file, backups, report. No Qt |
| `device.py` | `KOReaderSSH` (ssh + BusyBox tar) and `KOReaderFolder` (mounted/copied device) |
| `metadata.py` | Status/rating/review mapping and "only write when changed in KOReader" logic |
| `luatable.py` | Parser/serializer for KOReader `.lua` sidecars, byte-exact with KOReader's `dump()` |
| `styles.py` | KOReader color/drawer ↔ calibre highlight style |
| `column.py` | Parses the HTML column written by the KOReader Sync plugin (two formats) |
| `action.py`, `config.py`, `__init__.py` | calibre GUI action, settings widget, plugin entry point |

Core modules use relative imports so they work both as `calibre_plugins.kocalibre_highlights.*`
and as a plain package in tests. Only `action.py`/`config.py`/`__init__.py` may import Qt/GUI code.

## Invariants that are easy to break

These were verified against real devices and books. Re-run `validate_real_data.py` after touching
`positions.py`.

- **crengine DocFragment[N]** = Nth spine itemref whose manifest media-type is exactly
  `application/xhtml+xml`, in OPF order, *including* non-linear items.
- **calibre's spine** (`container.spine_names`) puts non-linear items *last*; `spine_index` is an
  index into that list. Map between the two by file name, never by index.
- **crengine text**: outside `<pre>`, runs of `[ \t\r\n]` collapse to one space (nbsp is not
  whitespace); a whitespace-only text node that is the first child of a block element is dropped.
  XPointer offsets count code points in that collapsed text. Element steps count same-name
  siblings; the `[1]` index is omitted when unique, except with `cre_dom_version >= 20260812`
  (explicit indices everywhere, including `body[1]`).
- **calibre CFI text offsets** (`read_book/cfi.pyj`): the last step is the parent's *first child*,
  and the offset is the sum of the lengths of all *direct* text nodes before the point, skipping
  inline elements' contents. Offsets are UTF-16 code units. Unique ids add `[id]` assertions.
  Decoding an odd step counts text nodes only.
- `pos1`/`end_cfi` are exclusive on both sides.
- **Writing to KOReader**: never edit `metadata.*.lua`. Write `<book>.sdr/<book>.epub.annotations.lua`
  (`device_id` = `calibre-kocalibre-highlights`, `datetime` in device local time, and *no* `paging`
  key, or KOReader discards it). KOReader merges it on the next book open and deletes it; while it
  is pending, `apply_koreader_import` predicts the merged state.
- **Books open in KOReader must be skipped** (`KOReaderSSH.open_books()` reads `/proc/*/fd`): after
  consuming an import, KOReader keeps annotations in memory and the on-disk sidecar is stale, which
  otherwise looks like deletions.
- **Deletions** are inferred from the last-sync state (`StateStore`, v2 format with `highlights` and
  `metadata` sections). Read-only sources (the column) must never delete or resurrect anything.
- calibre deletions are tombstones (`{type, uuid, timestamp, removed: True}`) written with
  `merge_annotations_for_book`; newest `timestamp` wins per `uuid`.
- KOReader datetimes are naive device-local strings; convert with the offset from
  `KOReaderSSH.utc_offset()`.

## Safety when testing

- Never write to a real calibre library from a script while the calibre GUI is running. Test
  against a copy: `sqlite3 metadata.db ".backup copy/metadata.db"` plus symlinks to the author
  folders.
- Prefer `SyncEngine(..., dry_run=True)` and `KOReaderFolder` on a local copy of the device's
  sidecars over writing to a real device.
- To try the plugin without touching the user's calibre setup, point `CALIBRE_CONFIG_DIRECTORY` to
  a temporary folder before `calibre-customize -a`. `CALIBRE_OVERRIDE_LANG=es` tests translations.

## Conventions

- Code, comments and source strings in English. Every user-visible string goes through `_()`
  using `str.format` (not f-strings) so `xgettext` can extract it; run `./i18n.sh` and update
  `translations/*.po` after changing strings. Modules that can run outside the plugin wrap
  `load_translations()` in `try/except NameError`.
- Match the existing style: small functions, `'single quotes'`, docstrings only where behavior is
  non-obvious, `# {{{` / `# }}}` folds like calibre's code.
- Keep the engine pure and testable; add a unit test in `tests/test_sync.py` for new sync rules.
- Commit messages: imperative summary line, body explaining why.
