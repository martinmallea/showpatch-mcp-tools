# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).
Versionado semántico: un cambio de esquema obliga a bump de major.

## [1.9.1] — 2026-10-30

### Added

- Roles previstos **Diseño**, **Marketing y redes** y **Ventas** en `agents/roster.json` y
  `agents/ROLES.md`, con su alcance y el criterio para crearlos.
- Referencia a **Archify** (https://github.com/tt-a1i/archify) en el orquestador: diagramas
  de arquitectura y páginas explicativas a partir del repo.

### Notas

- Los agentes de la plataforma se renombraron a Orquestador, Contrato y QA, Parsers,
  Geometría, Protocolo y Documentación, y se les cargaron las instrucciones nuevas.

## [1.9.0] — 2026-10-30

### Added

- **Monitor DMX en vivo** (`core/dmx_monitor.py` + pestaña «DMX live»): visualiza 512 canales
  por universo con fps, fuente, canales activos, pico y antigüedad del último paquete.
- Parseo de **Art-Net** (ArtDmx, UDP 6454) y **sACN/E1.31** (UDP 5568), sólo escucha.
- **Grabación de tramas** en memoria desde la app: sirve para comprobar que llega tráfico y
  cuánto, antes de plantear reproducción.
- Aviso explícito de firewall en la interfaz.

### Notas

- Escucha pasiva: no emite DMX, no interfiere y no necesita interponerse en la línea.
- Windows bloquea UDP entrante entre procesos incluso en loopback; sin permiso de firewall el
  monitor ve cero y parece roto. Verificado en esta máquina: mismo proceso funciona, proceso
  distinto no.
- El multicast de sACN requiere unirse al grupo; por ahora sólo se une si se piden universos.

## [1.8.0] — 2026-10-30

### Changed

- **Nombre definitivo: ShowPatch · MCP Tools.** Sustituye a ShowBridge, que colisiona con un
  producto de control láser del mismo sector (Truwave): mismos compradores y mismo canal.
- Renombrados carpeta, código, tests, documentación, plan, landing y agentes.
- El descriptor **MCP Tools** aparece junto al logo en la landing, la app y el README.

### Por qué ShowPatch

- "Patch" es la palabra que usa el técnico para lo que más duele cuando falla.
- No promete DMX: el puente manda comandos, no tramas.
- "MCP Tools" queda como subtítulo, no como marca: describe la integración con IA sin
  pretender ser un nombre registrable.

## [1.7.0] — 2026-10-30

### Added

- **Estructura en Notion** (`tools/notion_sync.py`): bundle Markdown + CSV para importar
  sin token, y sincronización por API (página + tres bases de datos + volcado).
- Modelo de datos: Roadmap (15 work packages con gate y evidencia), Lecciones por rol,
  Releases y Decisiones de arquitectura.
- `--dry-run` escribe los payloads en `exports/notion_payloads.json` para revisarlos
  antes de enviar nada.

### Decisiones

- **El repo manda; Notion es un espejo.** Sync de ida, nunca de vuelta.
- Sin token no hay sync: el bundle resuelve el caso sin pedir credenciales.

## [1.6.0] — 2026-10-30

### Added

- **Landing de captación** (`python bridge.py landing`): página de venta con gancho, sección
  explícita de lo que NO hace y registro por correo.
- Entrega de descargas tras el registro: ZIP de Windows, HTML completo de la interfaz y
  enlace al repositorio (marcado "público en preparación").
- `landing/server.py`: captura los registros en JSONL (correo, rol, consola y aceptación del
  aviso de PC; sin IP ni user-agent) y sirve los ficheros sólo con el alta hecha.

### Notas de producto

- El aviso "el móvil es el mando, el motor va en el PC" aparece **antes** del alta, no después.
- Sin binario publicado, la descarga responde 404 con mensaje en vez de un enlace roto.

## [1.5.0] — 2026-10-30

### Added

- **Grabador de comandos** (`core/recorder.py`): guarda cada mensaje enviado con su
  instante en JSONL, sobrevive a líneas corruptas y a un corte a mitad de sesión.
- **Autoplay** (`python bridge.py rec --play … --speed 2 --loops 3`): reproduce la
  grabación con velocidad y bucle. Dry-run por defecto; `--live` para enviar.
- `python bridge.py rec --new|--list|--show` para crear, listar y resumir tomas.
- Integración con `osc.send`: si `SHOWPATCH_RECORD` apunta a un fichero, toda
  llamada del servidor MCP queda grabada sin envolver nada.

### Notas de diseño

- El calendario de reproducción se calcula separado del envío, así que velocidad y
  bucles se prueban sin esperar en tiempo real.
- No se graban tramas DMX: eso sería otro producto y otro modelo de seguridad.

## [1.4.0] — 2026-10-30

### Added

- **App local** (`python bridge.py web`): servidor HTTP con la librería estándar y una
  página única con panel, buscador de fixtures, calculadora DMX y calculadora de color.
- **Buscador de fixtures dentro de la app**: consulta el índice de 14 221 fixtures con
  filtro por modelo y fabricante; devuelve modo y canales.
- **Calculadora DMX** (`core/dmx_calc.py`): rango, DIP switches, capacidad por universo,
  siguiente dirección libre, detección de solapes y resumen de ocupación.
- **Calculadora de color** (`core/color_calc.py`): RGB, CMY, HSV, RGBW, HEX, DMX y
  porcentajes exactos, con convenios documentados.
- **Daltonismo** (`core/colorblind.py`): simulación en luz lineal de protanopía,
  deuteranopía y tritanopía, nombre del color y detección de pares confundibles.

### Changed

- `osc.send` acepta el prefijo `/grandMA3/` además de `/gma3/`: el prefijo OSC de MA3 es
  configurable y herramientas del mercado usan `grandMA3` con puerto 8081.

### Security

- La app escucha en loopback por defecto; exponerla en red exige `--token`.
- Sin CORS abierto, sin DMX crudo y con validación de rangos en la API.

## [1.3.0] — 2026-10-30

### Changed

- **Rebranding**: el proyecto deja de llamarse MA AI Bridge y pasa a **ShowPatch**.
  El motivo es de fondo: el nombre antiguo nombraba una sola consola (MA) cuando el
  puente habla con tres (grandMA3, ChamSys MagicQ y Wolfmix). El contrato
  `unified_show-1.0.0`, el esquema y los 6 tests no cambian: son agnósticos.
- Renombrados: carpeta del repositorio, título y textos, plan de trabajo, roster y
  agentes de la plataforma.

### Added

- `tools/check_branding.py` y **WP-12**: un gate permanente que falla si el nombre
  antiguo reaparece en archivos versionados. La evidencia histórica se excluye a
  propósito: es un registro, no documentación.

## [1.2.0] — 2026-10-30

### Added

- **Registro de experiencia** (`agents/lessons.jsonl` + `tools/lessons.py`): cada
  error no obvio se guarda con rol, WP y contexto. `render_brief()` inyecta las
  5 últimas lecciones del rol en cada encargo, así que el siguiente agente no
  repite el tropiezo.
- CLI `python bridge.py lessons [--add|--list] [--role] [--wp]`.
- **Kit portable**: `tools/scaffold_project.py` lleva orquestador, lecciones y
  plantillas de equipo a cualquier proyecto nuevo, con gates reales (sin tests el
  gate falla).
- Seis lecciones sembradas con los errores reales de esta iteración.

### Changed

- Los seis agentes de la plataforma se reescriben sin rutas clavadas a MA AI
  Bridge: el oficio se mantiene (contrato, ingesta, geometría, protocolo, docs) y
  el proyecto se recibe por brief.

## [1.1.0] — 2026-10-30

### Added

- **Índice de fixtures** desde la API pública de ChamSys Fixture Finder:
  `spec/fixture_library.json` con **14 221 fixtures** de 17 fabricantes
  (librería `29-10-2026`), generado por `tools/sync_fixture_library.py`.
- `core/fixture_library.py`: resolución fabricante+modelo(+modo) → canales, con
  detección de ambigüedad y lista de opciones.
- CLI `python bridge.py fixtures --search … | --sync [--all]`.
- `docs/FIXTURE_DATA.md`: endpoints descubiertos, formato, límites, cumplimiento
  de `robots.txt` y análisis de gdtf-build.com / GDTF.
- Work package WP-11 con sus gates, para que el plan refleje la capacidad real.

### Changed

- `split_fixture_type_string` usa el índice **como último recurso**, después de
  regex y diccionarios, y marca `channel_count_source="library"`. El contrato
  congelado no se toca: sus casos siguen resolviéndose antes.

## [1.0.0] — 2026-10-30

Primera versión con contrato congelado y verificación reproducible.

### Added

- Contrato `unified_show-1.0.0` con validación de reglas de negocio
  (`core/schema_validator.py`).
- Parser de export XML de grandMA3 tolerante a variantes (`core/ma3_xml.py`).
- Import de CSV de ChamSys MagicQ (`bridges/chamsys_bridge/csv_import.py`).
- Motor geométrico: herradura, matriz afín y Pan con offset por modelo
  (`core/intelligence.py`).
- Fingerprinting DMX de robótica sin manual, con evidencia por rol
  (`core/finder.py`).
- Traducción a comandos nativos MA3/ChamSys con allowlist de verbos
  (`core/commands.py`, `bridges/ma_bridge/emitter.py`).
- Codec OSC 1.0 propio y servidor MCP con 11 herramientas
  (`core/osc_codec.py`, `mcp_server/`).
- Orquestador determinista con DAG de 10 work packages, gates ejecutables,
  estado persistente y briefs por paquete (`orchestrator/`, `orchestration/`).
- Equipo de agentes con reparto por rutas exclusivas (`agents/`).
- Auditoría de entorno regenerable (`tools/env_audit.py`) y documentación de
  arquitectura y release.
- Instalador asistido de grandMA3 onPC (`tools/install_gma3_onpc.ps1`).
- CLI única `python bridge.py` que funciona con `safe_path`.

### Fixed

- **Vector de oro OSC incorrecto.** El test 3 esperaba 61 bytes (cuatro NUL donde
  van tres). El paquete correcto mide 60 = 12 (address) + 4 (type tag) + 44
  (argumento). Se corrigió el vector, no el encoder.
- **Pérdida de casing en el splitter.** `Martin MAC Aura XB Extended` devolvía
  `mode="extended"` porque el modelo se extraía de la cadena en minúsculas. Ahora
  el match se proyecta sobre el texto original.
- **Terminador NUL ausente en cadenas de longitud múltiplo de 4.** El type tag
  `,sif` viajaba sin NUL y el decodificador se comía el argumento siguiente;
  detectado por un test propio antes de llegar a hardware.
- `mount_type` se inyectaba en el validador (que no debe mutar el input); ahora
  lo marca el parser con `mount_type_source`.
- `pos_z` se perdía al recolocar en herradura; ahora se conserva.
- Nombres de comando inválidos del prototipo (`Create Fixture`, `LoadPlugin`,
  `CallPlugin`) eliminados: se emite sólo sintaxis verificada contra el contrato.

### Changed

- Estructura `bridges/` en lugar de `contributions/`.
- `bearing_deg` (geometría) y `calculated_pan` (geometría + calibración) son
  campos distintos y se documentan como tales.
- Los parsers emiten `semantic` vacío; sólo la geometría lo escribe.
- El CI cubre PRs contra `integration`, además de `main`.

### Security

- `osc.send` rechaza `/dmx` y verbos fuera de allowlist; `dry_run=True` por
  defecto.
- Rutas confinadas al repo; `lua.generate` escribe sólo en `generated/`.
- Escapado de `\` y `"` en la generación de Lua.
- Sockets cerrados con contexto (`with`), también en error.

### Known limitations

- Sin validación en hardware: no hay grandMA3 onPC en la máquina de desarrollo.
- ChamSys sin cliente HTTP vivo (sólo CSV).
- Sin salida DMX propia (Art-Net/sACN).
- `gh`, `lua`, `pandoc` y Docker no instalados: publicación, lint de Lua, PDF y
  paridad de CI quedan pendientes.
