# License: GPL v3 (see LICENSE)

from calibre.customize import InterfaceActionBase


class KOReaderHighlightsPlugin(InterfaceActionBase):
    name = 'KOReader Highlights Sync'
    description = ('Two-way sync of highlights and notes between KOReader and the calibre '
                   'e-book viewer, over KOReader\'s SSH server.')
    supported_platforms = ['windows', 'osx', 'linux']
    author = 'Santiago'
    version = (0, 2, 0)
    minimum_calibre_version = (6, 0, 0)
    actual_plugin = 'calibre_plugins.kocalibre_highlights.action:HighlightsSyncAction'

    def is_customizable(self):
        return True

    def config_widget(self):
        from calibre_plugins.kocalibre_highlights.config import ConfigWidget
        return ConfigWidget()

    def save_settings(self, config_widget):
        config_widget.save_settings()
        ac = self.actual_plugin_
        if ac is not None:
            ac.apply_settings()
