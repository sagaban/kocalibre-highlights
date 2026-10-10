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
