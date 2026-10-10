import os

from calibre.constants import config_dir
from calibre.utils.config import JSONConfig
from qt.core import (QCheckBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QSpinBox, QVBoxLayout,
                     QWidget)

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
        l.addWidget(QLabel(
            '<p>Los highlights se leen y escriben por el servidor SSH de KOReader '
            '(<i>Herramientas → Más herramientas → Servidor SSH</i>; activá el inicio de sesión sin '
            'contraseña o agregá tu clave pública). Si el dispositivo está conectado a calibre por wifi, '
            'su dirección se detecta sola.</p>'
            '<p>KOReader aplica los cambios la próxima vez que abrís el libro en el dispositivo.</p>'))
        l.itemAt(0).widget().setWordWrap(True)
        f = QFormLayout()
        l.addLayout(f)
        self.host = QLineEdit(prefs['host'])
        self.host.setPlaceholderText(f'automática (última: {prefs["last_host"] or "ninguna"})')
        f.addRow('&Dirección del dispositivo:', self.host)
        h = QHBoxLayout()
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(int(prefs['port']))
        self.user = QLineEdit(prefs['user'])
        h.addWidget(self.port), h.addWidget(QLabel('Usuario:')), h.addWidget(self.user)
        f.addRow('&Puerto SSH:', h)
        self.key_file = QLineEdit(prefs['key_file'])
        self.key_file.setPlaceholderText('claves SSH por defecto (~/.ssh)')
        f.addRow('Archivo de &clave SSH:', self.key_file)
        self.koreader_dir = QLineEdit(prefs['koreader_dir'])
        f.addRow('Carpeta de &KOReader:', self.koreader_dir)
        self.book_roots = QLineEdit(', '.join(prefs['book_roots']))
        f.addRow('Carpetas de &libros:', self.book_roots)
        self.auto = QCheckBox('Sincronizar automáticamente cuando el dispositivo se conecta a calibre')
        self.auto.setChecked(prefs['auto_sync_on_connect'])
        l.addWidget(self.auto)
        self.notify = QCheckBox('Mostrar un resumen después de las sincronizaciones automáticas')
        self.notify.setChecked(prefs['notify_auto_sync'])
        l.addWidget(self.notify)
        self.use_column = QCheckBox('Importar también desde la columna del plugin KOReader Sync '
                                    '(para libros que no están en el dispositivo)')
        self.use_column.setChecked(prefs['use_column_fallback'])
        l.addWidget(self.use_column)
        f2 = QFormLayout()
        self.column = QLineEdit(prefs['column'])
        f2.addRow('C&olumna:', self.column)
        l.addLayout(f2)
        l.addWidget(QLabel('<p><b>Datos del libro</b> (de KOReader a calibre; vacío = no sincronizar). '
                           'Solo se escriben cuando cambian en KOReader, así que lo que edites a mano en '
                           'calibre se mantiene.</p>'))
        l.itemAt(l.count() - 1).widget().setWordWrap(True)
        f3 = QFormLayout()
        self.read_column = QLineEdit(prefs['read_column'])
        self.read_column.setPlaceholderText('ej. #leido (columna Sí/No)')
        f3.addRow('Columna de l&eído:', self.read_column)
        self.rating_column = QLineEdit(prefs['rating_column'])
        self.rating_column.setPlaceholderText('ej. rating')
        f3.addRow('Columna de c&alificación:', self.rating_column)
        self.review_column = QLineEdit(prefs['review_column'])
        self.review_column.setPlaceholderText('ej. #ko_review (texto largo)')
        f3.addRow('Columna de &reseña:', self.review_column)
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
