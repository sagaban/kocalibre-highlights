import os

from calibre.gui2 import error_dialog, info_dialog, open_local_file
from calibre.gui2.actions import InterfaceAction
from calibre.gui2.device import device_signals
from qt.core import QMenu, QThread, pyqtSignal

from calibre_plugins.kocalibre_highlights.config import DATA_DIR, prefs


class SyncWorker(QThread):

    done = pyqtSignal(object, object)  # report, exception text

    def __init__(self, parent, db, host, book_ids, use_device, use_column, dry_run):
        QThread.__init__(self, parent)
        self.db, self.host, self.book_ids = db, host, book_ids
        self.use_device, self.use_column, self.dry_run = use_device, use_column, dry_run

    def run(self):
        try:
            from calibre_plugins.kocalibre_highlights.engine import SyncEngine
            eng = SyncEngine(self.db, prefs, DATA_DIR, dry_run=self.dry_run)
            report = eng.run(host=self.host, book_ids=self.book_ids, use_device=self.use_device,
                             use_column=self.use_column)
            self.done.emit(report, None)
        except Exception:
            import traceback
            self.done.emit(None, traceback.format_exc())


class HighlightsSyncAction(InterfaceAction):

    name = 'KOReader Highlights Sync'
    action_spec = ('KOReader Highlights', 'highlight.png',
                   'Sincronizar highlights entre KOReader y el visor de calibre', None)
    action_type = 'current'
    dont_add_to = frozenset(('context-menu-device',))

    def genesis(self):
        self.worker = None
        self.menu = QMenu(self.gui)
        self.qaction.setMenu(self.menu)
        self.qaction.triggered.connect(self.sync_all)
        self.create_menu_action(self.menu, 'kch-sync-all', 'Sincronizar todos los libros', icon='highlight.png',
                                triggered=self.sync_all)
        self.create_menu_action(self.menu, 'kch-sync-selected', 'Sincronizar libros seleccionados', icon='sync.png',
                                triggered=self.sync_selected)
        self.create_menu_action(self.menu, 'kch-preview', 'Vista previa (no cambia nada)', icon='search.png',
                                triggered=self.preview)
        self.create_menu_action(self.menu, 'kch-column', 'Importar solo desde la columna de KOReader Sync',
                                icon='column.png', triggered=self.import_column)
        self.menu.addSeparator()
        self.create_menu_action(self.menu, 'kch-backups', 'Abrir carpeta de backups', icon='document_open.png',
                                triggered=self.open_backups)
        self.create_menu_action(self.menu, 'kch-config', 'Configurar', icon='config.png',
                                triggered=self.show_config)
        device_signals.device_metadata_available.connect(self.on_device_ready)

    def apply_settings(self):
        pass

    def show_config(self):
        self.interface_action_base_plugin.do_user_config(self.gui)

    def open_backups(self):
        path = os.path.join(DATA_DIR, 'backups')
        os.makedirs(path, exist_ok=True)
        open_local_file(path)

    # Device {{{
    def connected_host(self):
        dev = self.gui.device_manager.connected_device
        sock = getattr(dev, 'device_socket', None)
        if sock is not None:
            try:
                return sock.getpeername()[0]
            except OSError:
                pass
        return None

    def host(self):
        h = self.connected_host()
        if h:
            if prefs['last_host'] != h:
                prefs['last_host'] = h
            if not prefs['host']:
                return h
        return prefs['host'] or h or prefs['last_host'] or None

    def on_device_ready(self):
        if prefs['auto_sync_on_connect'] and self.connected_host():
            self.start(silent=not prefs['notify_auto_sync'])
    # }}}

    def sync_all(self):
        self.start()

    def sync_selected(self):
        ids = self.gui.library_view.get_selected_ids()
        if not ids:
            return error_dialog(self.gui, 'No hay libros seleccionados', 'Seleccioná primero los libros a sincronizar', show=True)
        self.start(book_ids=ids)

    def preview(self):
        self.start(dry_run=True)

    def import_column(self):
        self.start(use_device=False, use_column=True)

    def start(self, book_ids=None, silent=False, dry_run=False, use_device=True, use_column=None):
        if self.worker is not None and self.worker.isRunning():
            if not silent:
                info_dialog(self.gui, 'Sincronización en curso', 'Ya hay una sincronización de highlights en curso', show=True)
            return
        host = self.host() if use_device else None
        if use_device and not host:
            if prefs['use_column_fallback'] and use_column is not False:
                use_device = False  # nothing to talk to, only import from the column
            elif silent:
                return
            else:
                return error_dialog(self.gui, 'Sin dispositivo', 'No se conoce la dirección del dispositivo con '
                                    'KOReader. Conectalo a calibre por wifi o configurá su dirección en el plugin.',
                                    show=True)
        self.silent, self.dry_run = silent, dry_run
        self.worker = SyncWorker(self.gui, self.gui.current_db.new_api, host, book_ids, use_device,
                                 use_column, dry_run)
        self.worker.done.connect(self.finished)
        self.gui.status_bar.show_message('Sincronizando highlights de KOReader...', 3000)
        self.worker.start()

    def finished(self, report, exc):
        self.worker = None
        if exc:
            return error_dialog(self.gui, 'Falló la sincronización', 'Falló la sincronización de highlights',
                                det_msg=exc, show=True)
        summary = report.summary()
        if self.dry_run:
            summary = 'Vista previa: no se cambió nada.\n\n' + summary
        self.gui.status_bar.show_message('KOReader highlights: ' + summary.replace('\n', ' ').strip(), 8000)
        if report.errors or not self.silent:
            info_dialog(self.gui, 'KOReader highlights', summary.replace('\n', '<br>'),
                        det_msg=report.details(), show=True)
