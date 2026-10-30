# Arquitectura — ShowPatch 1.0.0

## Qué es y qué no es

Es un puente entre un LLM y una consola de iluminación. El LLM **no** escribe
DMX: escribe comandos de consola y el renderizador los aplica. Ese límite es de
diseño, no una limitación pendiente: el DMX crudo desde un modelo de lenguaje
produce jitter y latencia, y un show no tolera ninguno de los dos.

```
                    ┌──────────────────────────────┐
   show de consola  │  parsers (XML MA3 / CSV MQ)  │
   ────────────────▶│  core/ma3_xml.py             │
                    │  bridges/chamsys_bridge/     │
                    └──────────────┬───────────────┘
                                   │ unified_show-1.0.0 (JSON)
                                   ▼
                    ┌──────────────────────────────┐
                    │  contrato + validación       │
                    │  spec/*.schema.json          │
                    │  core/schema_validator.py    │
                    └──────────────┬───────────────┘
                                   │ documento válido
                                   ▼
                    ┌──────────────────────────────┐
                    │  geometría (Fase 3)          │
                    │  core/intelligence.py        │
                    │  bearing · herradura · afín  │
                    └──────────────┬───────────────┘
                                   │ show recolocado
                                   ▼
                    ┌──────────────────────────────┐
                    │  traducción nativa (Fase 4)  │
                    │  core/commands.py            │
                    │  bridges/*/emitter.py        │
                    └──────────────┬───────────────┘
                          comandos │ + payload OSC
                                   ▼
                    ┌──────────────────────────────┐
                    │  transporte                  │
                    │  core/osc_codec.py (UDP)     │
                    │  mcp_server/ (JSON-RPC stdio)│
                    └──────────────┬───────────────┘
                                   ▼
                        consola / onPC / nodo
```

## Capas y responsabilidades

| Capa | Módulos | Responsabilidad | No hace |
|---|---|---|---|
| Ingesta | `core/ma3_xml.py`, `bridges/chamsys_bridge/csv_import.py`, `core/fixture_library.py` | Convertir exports irregulares al contrato y resolver tipos | No calcula Pan ni valida reglas de negocio |
| Contrato | `spec/`, `core/schema_validator.py` | Definir forma y coherencia del documento | No muta el input |
| Geometría | `core/intelligence.py`, `core/pan_offsets.py` | Recolocar el rig y calcular Pan con offset de modelo | No escribe en disco ni envía red |
| Traducción | `core/commands.py`, `bridges/*/emitter.py` | Comandos nativos y Lua escapado | No inventa sintaxis: allowlist de verbos |
| Transporte | `core/osc_codec.py`, `mcp_server/` | Framing OSC y API para el LLM | No emite DMX crudo; dry-run por defecto |
| Diagnóstico | `core/finder.py`, `core/osc_listener.py` | Fingerprinting DMX y estado de consola | No decide: propone con evidencia |
| Datos | `core/fixture_library.py`, `tools/sync_fixture_library.py` | Resolver tipo de fixture → canales desde un índice local | No es verdad revelada: marca ambigüedad y origen |
| Orquestación | `orchestrator/`, `orchestration/`, `agents/` | Repartir trabajo, aceptar sólo evidencia y acumular lecciones | No implementa features |

## Invariantes del contrato

1. **`schema_version` en la raíz.** Sin versión no hay compatibilidad posible.
2. **Agnóstico por defecto.** Nada de terminología nativa en el documento; los
   nombres de consola viven en los emisores.
3. **`semantic` es del motor, no del parser.** Los parsers emiten
   `bearing_deg=None` y `calculated_pan=None`; sólo la geometría los escribe.
4. **`mount_type_source` auditable.** Si el parser no trajo el dato y hubo que
   suponerlo, queda marcado como `default`. Un dato supuesto y uno extraído no
   pueden parecer iguales.
5. **Rotación física ≠ rumbo semántico.** `position.rotation` describe cómo está
   montado el aparato; `bearing_deg` describe hacia dónde debe mirar.
6. **Idempotencia geométrica.** Repetir una transformación con los mismos
   parámetros da el mismo resultado; si no, el show no es reproducible.

## Frontera de seguridad

| Riesgo | Control | Dónde |
|---|---|---|
| Comando destructivo por error del LLM | Allowlist de verbos MA3 | `mcp_server/tools.py` |
| DMX crudo desde el modelo | Direcciones `/dmx` rechazadas; sólo `/gma3/`, `/chamsys/`, `/mcp/` | `core/osc_codec.py` |
| Envío accidental a hardware real | `dry_run=True` por defecto | `core/osc_codec.send_message` |
| Path traversal / escritura fuera del repo | `_resolve()` confina al repo | `mcp_server/tools.py` |
| Inyección Lua vía nombre de fixture | Escapado de `\` y `"` | `bridges/ma_bridge/emitter.py` |
| Ejecución silenciosa de Lua | Se escribe en `generated/`, nunca en el runtime de MA3 | `mcp_server/tools.py` |

UDP no tiene ACK. `sent=True` significa "el datagrama salió de la interfaz", no
"la consola lo aplicó". La confirmación real es el listener de estado o el
plugin Lua residente; el resto es fe.

## Estrategia de pruebas

| Nivel | Comando | Qué demuestra |
|---|---|---|
| Contrato (congelado) | `python tools/contract_test.py` | 6 invariantes: esquema, offsets, framing OSC, traducción, calibración, splitter |
| Módulos | `python -m unittest discover -s tests -p "test_*.py"` | 123 tests: geometría, parsers, finder, MCP, orchestrator, seguridad |
| Puerta única | `python bridge.py verify` | Contrato + módulos + ejemplo de esquema + roundtrip de 6 fixtures |
| Plan | `python bridge.py orchestrate run` | Cada work package con su gate y su evidencia |

## Fuente de datos de fixtures

El texto de un patch rara vez declara canales. El parser resuelve en cascada:
regex (`24ch`) → diccionarios curados → **índice local** de 14 221 fixtures
(`spec/fixture_library.json`, metadatos de ChamSys Fixture Finder). El origen
queda en `channel_count_source`, y si el modelo tiene varios modos sin
especificar se devuelve el más frecuente marcado como ambiguo.

El índice no se versiona como verdad: es una referencia de terceros, se regenera
con `python bridge.py fixtures --sync` y se documenta en
[`FIXTURE_DATA.md`](FIXTURE_DATA.md).

## Lo que NO está implementado (y se dice)

- **Conexión HTTP viva a ChamSys.** Sólo hay import CSV; no hay cliente de la
  API web de MagicQ.
- **Salida DMX propia.** No se emite Art-Net/sACN. El puente manda comandos; la
  consola renderiza.
- **grandMA2 como destino de comandos.** El esquema admite
  `source.system="grandMA2"`, pero los emisores y el plugin son MA3. MA2 usa otra
  sintaxis OSC y otro modelo de plugin.
- **Validación en hardware.** No se ha probado contra una consola física ni
  contra un nodo. En esta máquina hay grandMA2 onPC 3.9.60.63 y MagicQ PC, pero
  **no** grandMA3 onPC.
- **Rutas de plugin y nombres de comando de carga.** `LoadPlugin`/`CallPlugin`
  del prototipo no son comandos MA3 válidos; el repo no los usa, pero la
  secuencia de carga real debe confirmarse en consola.
- **Persistencia del estado OSC.** El listener guarda en memoria; no hay
  almacenamiento histórico.
