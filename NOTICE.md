# Avisos y atribuciones

## Datos de terceros incluidos en el repositorio

**`spec/fixture_library.json`** contiene metadatos de fixtures —fabricante, modelo, modo,
número de canales y nombre del archivo `.hed`— obtenidos de la API pública de
[ChamSys Fixture Finder](https://fixturefinder.chamsys.co.uk/) el 29 de octubre de 2026
(14 221 registros de 17 fabricantes).

- Uso: interoperabilidad, para resolver el número de canales de un tipo de fixture cuando
  el patch no lo declara.
- No se distribuyen los archivos `.hed` ni definiciones propietarias de canal.
- No se usó para entrenar modelos.
- © ChamSys; las marcas citadas pertenecen a sus titulares.

El archivo se regenera con `python bridge.py fixtures --sync`, que respeta el `robots.txt`
del sitio (`ai-train=no`, `use=reference`) y limita el ritmo de peticiones.

## Código de terceros

El proyecto **no tiene dependencias de ejecución**: todo el código usa la biblioteca estándar
de Python. No hay paquetes vendorizados ni binarios de terceros.

## Marcas

`grandMA3` y `MA Lighting`, `ChamSys` y `MagicQ`, `Wolfmix` son marcas de sus respectivos
titulares. Este proyecto no está afiliado, patrocinado ni respaldado por ninguno de ellos.

## Herramientas usadas en desarrollo (no se distribuyen)

- **Archify** (MIT, https://github.com/tt-a1i/archify): diagramas y páginas explicativas.
  Se instala aparte con `npx skills add tt-a1i/archify -g`; su salida es HTML propio.
- **Chrome** y **Python** del sistema, para pruebas locales.

## Datos personales

La landing guarda los correos de registro en `landing/data/signups.jsonl`, que está fuera del
repositorio y del ZIP. No se recogen IP ni user-agent. No se incluyen datos personales en el
código ni en la documentación.
