# KOReader Highlights Sync (calibre plugin)

*[Leer en español](README.es.md)*

Two-way sync of highlights and notes between **KOReader** and the **calibre e-book viewer**
(EPUB). KOReader highlights show up as real highlights when you open the book in calibre, and the
ones you make in calibre show up in KOReader.

It also copies each book's **read status**, **rating** and **review** from KOReader to calibre, so
it can replace the KOReader Sync plugin for that.

## Installation

```sh
./build.sh   # needs msgfmt (GNU gettext) to compile the translations
```

Then in calibre: *Preferences → Plugins → Load plugin from file* → `KOReader Highlights Sync.zip`,
and restart calibre. Add the **KOReader Highlights** button to a toolbar if it doesn't show up
(*Preferences → Toolbars & menus*).

In KOReader: *Tools → More tools → SSH server*, enabled, with login without password or your public
key in `koreader/settings/SSH/authorized_keys`.

The defaults (`/mnt/us/books`, `/mnt/us/documents`, `/mnt/us/koreader`) are for a Kindle; change
them in the plugin settings for other devices.

## Usage

- **When the device connects to calibre wirelessly** the sync runs automatically (configurable).
  The device's address is taken from that connection, or can be set in the settings.
- Button / menu: *sync all books*, *sync selected books*, *preview* (changes nothing), *import from
  the KOReader Sync column only* (for books no longer on the device).

KOReader applies changes **the next time you open the book** on the device.

Books that are **open in KOReader** during a sync are skipped: while a book is open KOReader keeps
its annotations in memory and the sidecar on disk is out of date. Close it (go back to the file
browser) and sync again.

### Read status, rating and review

The target columns are set in the plugin settings (by default, the ones configured in KOReader
Sync):

| KOReader (sidecar `summary`) | calibre |
|---|---|
| status `complete` / other | Yes/No column (e.g. `#read`) |
| rating, 1–5 stars | rating column (e.g. `rating`) |
| review | long text column (e.g. `#ko_review`) |

This goes only from KOReader to calibre, and a value is written only when it **changed in
KOReader** since the last sync, so edits you make by hand in calibre are kept until you change the
value on the device.

## How it works

| | KOReader | calibre |
|---|---|---|
| Where | `book.sdr/metadata.epub.lua` | `annotations` table in `metadata.db` |
| Position | XPointer `/body/DocFragment[15]/body/p[72]/text().120` | `spine_index` + CFI `/2/4/144/1:120` |

- `positions.py` converts XPointer ↔ CFI by reading the EPUB's HTML. It emulates crengine
  (element indices by tag name, collapsed whitespace, DocFragment = XHTML spine item in OPF order)
  and calibre's `cfi.pyj` (text offsets from the parent's first text node, spine with non-linear
  items last, `[id]` assertions, UTF-16 offsets).
- Writes to KOReader never touch the sidecar. The plugin leaves a
  `book.sdr/book.epub.annotations.lua` file, KOReader's own import mechanism
  (`ReaderAnnotation:importAnnotations`), which merges it when the book is opened.
- calibre is updated with `merge_annotations_for_book`. Deletions are tombstones
  (`removed: true`), the same way the viewer does it.
- **Deletions:** the state saved at the end of the last sync (`state/<library_id>.json` in the
  plugin's data folder) tells "deleted on one side" apart from "created on the other".
- **Edits** (note, color): the most recent one wins.
- Before any change, a backup (sidecar + calibre annotations) is saved in the plugin's data folder,
  under `backups` (on macOS: `~/Library/Preferences/calibre/plugins/KOReader Highlights Sync data`).

Colors: yellow/green/blue/red/purple ↔ calibre's builtin styles; gray/orange/olive/cyan ↔ custom
styles named `KOReader <color>`; underline and strikeout ↔ decorations.

## Limitations

- EPUB only (the calibre viewer doesn't show highlights for PDFs).
- Highlights that span two files of the EPUB are not copied to calibre.
- Books are matched by their calibre `uuid`, so they must have been sent from calibre.
- New calibre highlights are not written for books that were never opened in KOReader.
- Only KOReader's "book folder" and "koreader/docsettings" metadata locations are supported (not
  "hash").

## Tests

```sh
calibre-debug -e tests/test_sync.py
calibre-debug -e tests/validate_real_data.py -- <folder with sidecars> <calibre library>
```

## Translations

The interface is in English, with a Spanish translation; calibre picks the one matching its own
language. Translations live in `kocalibre_highlights/translations/<lang>.po`. After changing
user-visible strings, run `./i18n.sh` to update the template and merge it into every `.po`; to add a
language, copy `messages.pot` to `<lang>.po` and translate it.

## License

[GPL v3](LICENSE)
