#!/bin/sh
# Re-extract the translatable strings and merge them into every translation.
# After running it, translate the new/fuzzy entries in kocalibre_highlights/translations/*.po
set -e
cd "$(dirname "$0")/kocalibre_highlights"
xgettext --language=Python --keyword=_ --from-code=UTF-8 --no-wrap --add-comments=TRANSLATORS \
    --package-name="KOReader Highlights Sync" -o translations/messages.pot \
    action.py config.py engine.py metadata.py sync.py
for po in translations/*.po; do
    msgmerge --quiet --update --backup=none --no-wrap "$po" translations/messages.pot
    printf '%s: ' "$po"; msgfmt --check --statistics -o /dev/null "$po"
done
