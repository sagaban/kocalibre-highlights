import os

from calibre.constants import config_dir
from calibre.utils.config import JSONConfig
from qt.core import (QCheckBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QSpinBox, QVBoxLayout,
                     QWidget)

load_translations()

prefs = JSONConfig('plugins/KOReader Highlights Sync')
prefs.defaults['host'] = ''
prefs.defaults['last_host'] = ''
prefs.defaults['port'] = 2222
prefs.defaults['user'] = 'root'
prefs.defaults['key_file'] = ''
prefs.defaults['koreader_dir'] = '/mnt/us/koreader'
prefs.defaults['book_roots'] = ['/mnt/us/books', '/mnt/us/documents']
prefs.defaults['auto_sync_on_connect'] = True
prefs.defaults['notify_auto_sync'] = True
prefs.defaults['use_column_fallback'] = True
prefs.defaults['column'] = '#ko_bookmarks'


def _koreader_sync_columns():
    '''Columns configured in the KOReader Sync plugin, used as defaults'''
    import json
    try:
        with open(os.path.join(config_dir, 'plugins', 'KOReader Sync.json'), encoding='utf-8') as f:
            c = json.load(f)
    except (OSError, ValueError):
        return {}
    return {'read_column': c.get('column_status_bool', ''), 'rating_column': c.get('column_rating', ''),
            'review_column': c.get('column_review', '')}


_ks = _koreader_sync_columns()
prefs.defaults['read_column'] = _ks.get('read_column', '')
prefs.defaults['rating_column'] = _ks.get('rating_column', '')
prefs.defaults['review_column'] = _ks.get('review_column', '')

DATA_DIR = os.path.join(config_dir, 'plugins', 'KOReader Highlights Sync data')


class ConfigWidget(QWidget):

    def __init__(self):
        QWidget.__init__(self)
        l = QVBoxLayout(self)
        l.addWidget(QLabel('<p>' + _(
            'Highlights are read and written over KOReader\'s SSH server '
            '(<i>Tools → More tools → SSH server</i>; enable login without password or add your '
            'public key). When the device is connected to calibre wirelessly, its address is '
            'detected automatically.') + '</p><p>' + _(
            'KOReader applies the changes the next time the book is opened on the device.') + '</p>'))
        l.itemAt(0).widget().setWordWrap(True)
        f = QFormLayout()
        l.addLayout(f)
        self.host = QLineEdit(prefs['host'])
        self.host.setPlaceholderText(_('automatic (last: {})').format(prefs['last_host'] or _('none')))
        f.addRow(_('Device &address:'), self.host)
        h = QHBoxLayout()
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(int(prefs['port']))
        self.user = QLineEdit(prefs['user'])
        h.addWidget(self.port), h.addWidget(QLabel(_('User:'))), h.addWidget(self.user)
        f.addRow(_('SSH &port:'), h)
        self.key_file = QLineEdit(prefs['key_file'])
        self.key_file.setPlaceholderText(_('default SSH keys (~/.ssh)'))
        f.addRow(_('SSH &key file:'), self.key_file)
        self.koreader_dir = QLineEdit(prefs['koreader_dir'])
        f.addRow(_('&KOReader folder:'), self.koreader_dir)
        self.book_roots = QLineEdit(', '.join(prefs['book_roots']))
        f.addRow(_('&Book folders:'), self.book_roots)
        self.auto = QCheckBox(_('Sync automatically when the device connects to calibre'))
        self.auto.setChecked(prefs['auto_sync_on_connect'])
        l.addWidget(self.auto)
        self.notify = QCheckBox(_('Show a summary after automatic syncs'))
        self.notify.setChecked(prefs['notify_auto_sync'])
        l.addWidget(self.notify)
        self.use_column = QCheckBox(_('Also import from the KOReader Sync plugin column '
                                      '(for books that are not on the device)'))
        self.use_column.setChecked(prefs['use_column_fallback'])
        l.addWidget(self.use_column)
        f2 = QFormLayout()
        self.column = QLineEdit(prefs['column'])
        f2.addRow(_('C&olumn:'), self.column)
        l.addLayout(f2)
        l.addWidget(QLabel('<p><b>' + _('Book data') + '</b> ' + _(
            '(from KOReader to calibre; empty = do not sync). Values are only written when they change '
            'in KOReader, so what you edit by hand in calibre is kept.') + '</p>'))
        l.itemAt(l.count() - 1).widget().setWordWrap(True)
        f3 = QFormLayout()
        self.read_column = QLineEdit(prefs['read_column'])
        self.read_column.setPlaceholderText(_('e.g. #read (Yes/No column)'))
        f3.addRow(_('R&ead column:'), self.read_column)
        self.rating_column = QLineEdit(prefs['rating_column'])
        self.rating_column.setPlaceholderText(_('e.g. rating'))
        f3.addRow(_('R&ating column:'), self.rating_column)
        self.review_column = QLineEdit(prefs['review_column'])
        self.review_column.setPlaceholderText(_('e.g. #ko_review (long text)'))
        f3.addRow(_('&Review column:'), self.review_column)
        l.addLayout(f3)
        l.addStretch(1)

    def save_settings(self):
        prefs['host'] = self.host.text().strip()
        prefs['port'] = self.port.value()
        prefs['user'] = self.user.text().strip() or 'root'
        prefs['key_file'] = self.key_file.text().strip()
        prefs['koreader_dir'] = self.koreader_dir.text().strip().rstrip('/') or '/mnt/us/koreader'
        prefs['book_roots'] = [x.strip().rstrip('/') for x in self.book_roots.text().split(',') if x.strip()]
        prefs['auto_sync_on_connect'] = self.auto.isChecked()
        prefs['notify_auto_sync'] = self.notify.isChecked()
        prefs['use_column_fallback'] = self.use_column.isChecked()
        prefs['column'] = self.column.text().strip()
        prefs['read_column'] = self.read_column.text().strip()
        prefs['rating_column'] = self.rating_column.text().strip()
        prefs['review_column'] = self.review_column.text().strip()
