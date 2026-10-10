# KOReader Highlights Sync (plugin de calibre)

Sincroniza en las dos direcciones los highlights y las notas entre **KOReader** y el **visor de
calibre** (EPUB). Los highlights de KOReader aparecen como highlights reales al abrir el libro en
calibre, y los que hacés en calibre aparecen en KOReader.

## Instalación

```sh
./build.sh
```

Después, en calibre: *Preferencias → Complementos → Cargar complemento desde archivo* →
`KOReader Highlights Sync.zip`, y reiniciar calibre. Agregá el botón **KOReader Highlights** a la
barra de herramientas si no aparece (*Preferencias → Barras de herramientas y menús*).

En KOReader: *Herramientas → Más herramientas → Servidor SSH*, activado y con login sin contraseña
o tu clave pública en `koreader/settings/SSH/authorized_keys`.

## Uso

- **Al conectar el Kindle a calibre por wifi** la sync corre sola (configurable).
- Botón / menú: *Sincronizar todos*, *Sincronizar seleccionados*, *Vista previa* (no cambia nada),
  *Importar solo desde la columna* (libros que ya no están en el Kindle).

KOReader aplica los cambios **la próxima vez que abrís el libro** en el Kindle.

## Cómo funciona

| | KOReader | calibre |
|---|---|---|
| Dónde | `libro.sdr/metadata.epub.lua` | tabla `annotations` de `metadata.db` |
| Posición | XPointer `/body/DocFragment[15]/body/p[72]/text().120` | `spine_index` + CFI `/2/4/144/1:120` |

- `positions.py` convierte XPointer ↔ CFI leyendo el HTML del EPUB, emulando a crengine (índices
  por nombre de tag, espacios colapsados, DocFragment = ítem XHTML del spine en orden OPF) y al
  `cfi.pyj` de calibre (offsets desde el primer nodo de texto del padre, spine con los ítems no
  lineales al final, aserciones `[id]`, UTF-16).
- Para escribir en KOReader no se toca el sidecar: se deja `libro.sdr/libro.epub.annotations.lua`,
  el mecanismo de importación propio de KOReader (`ReaderAnnotation:importAnnotations`), que lo
  fusiona al abrir el libro. Así no hay riesgo de que KOReader pise los cambios si el libro está
  abierto.
- En calibre se usa `merge_annotations_for_book`; los borrados son lápidas (`removed: true`), igual
  que hace el visor.
- **Borrados:** el estado de la última sync (`state/<library_id>.json` en la carpeta de datos del
  plugin) distingue "lo borré en un lado" de "lo creé en el otro".
- **Ediciones** (nota, color): gana la más reciente.
- Antes de cada cambio se guarda un backup (sidecar + anotaciones de calibre) en
  `~/Library/Preferences/calibre/plugins/KOReader Highlights Sync data/backups`.

Colores: amarillo/verde/azul/rojo/morado ↔ estilos nativos de calibre; gris/naranja/oliva/cian ↔
estilos personalizados `KOReader <color>`; subrayado y tachado ↔ decoraciones.

## Limitaciones

- Solo EPUB (el visor de calibre no muestra highlights de PDF).
- Highlights que cruzan dos archivos del EPUB no se pasan a calibre.
- Los libros se emparejan por el `uuid` de calibre: tienen que haberse enviado desde calibre.
- Los highlights nuevos de calibre no se escriben en libros que nunca se abrieron en KOReader.

## Tests

```sh
calibre-debug -e tests/test_sync.py
calibre-debug -e tests/validate_real_data.py -- <carpeta con sidecars> <biblioteca calibre>
```
