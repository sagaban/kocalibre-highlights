#!/bin/sh
# Build the calibre plugin zip. Install with: calibre-customize -a "KOReader Highlights Sync.zip"
# Needs msgfmt (GNU gettext) to compile the translations.
set -e
cd "$(dirname "$0")"
OUT="$PWD/KOReader Highlights Sync.zip"
STAGE="$(mktemp -d)"
trap '/bin/rm -r "$STAGE"' EXIT
cp -R kocalibre_highlights/. "$STAGE"
/bin/rm -r "$STAGE/translations"
mkdir "$STAGE/translations"
for po in kocalibre_highlights/translations/*.po; do
    lang="$(basename "$po" .po)"
    msgfmt --check -o "$STAGE/translations/$lang.mo" "$po"
done
/bin/rm -f "$OUT"
cd "$STAGE"
zip -q -r "$OUT" . -x '__pycache__/*' '*/__pycache__/*' '*.pyc'
echo "Built $OUT"
