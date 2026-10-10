#!/bin/sh
# Build the calibre plugin zip. Install with: calibre-customize -a "KOReader Highlights Sync.zip"
set -e
cd "$(dirname "$0")"
OUT="$PWD/KOReader Highlights Sync.zip"
/bin/rm -f "$OUT"
cd kocalibre_highlights
zip -q -r "$OUT" . -x '__pycache__/*' '*.pyc'
echo "Built $OUT"
