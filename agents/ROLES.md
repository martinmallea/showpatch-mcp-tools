# Equipo de agentes — ShowPatch

Seis roles, un solo contrato y una sola puerta de verdad: los gates. El
orquestador no ejecuta ingeniería; los subagentes no se autoproclaman
terminados. Si un gate no pasa, el work package no está hecho, diga lo que diga
el informe.

## Reparto

| Rol | Agente en la plataforma | Work packages | Rutas que posee |
|---|---|---|---|
| **ORQ** | ORQ · ShowPatch | WP-07 + despacho | `orchestrator/`, `orchestration/`, `agents/`, `bridge.py` |
| **SUB-QA** | Contrato y QA | WP-01, WP-08, WP-09 | `tools/contract_test.py`, `tools/verify_all.py`, `tools/env_audit.py`, `docs/ENVIRONMENT.md` |
| **SUB-PARSER** | Parsers | WP-02, WP-04 | `core/ma3_xml.py`, `core/finder.py`, `bridges/chamsys_bridge/csv_import.py` |
| **SUB-GEOMETRY** | Geometría | WP-03 | `core/intelligence.py` |
| **SUB-PROTOCOL** | Protocolo | WP-05, WP-06 | `mcp_server/`, `core/osc_codec.py`, `core/commands.py`, `bridges/ma_bridge/` |
| **SUB-DOCS** | Documentación | WP-10 | `docs/ARCHITECTURE.md`, `docs/RELEASE.md`, `CHANGELOG.md` |

El reparto es por **rutas exclusivas**: dos subagentes nunca escriben el mismo
archivo. Eso elimina el conflicto de fusión, que es el fallo típico de un equipo
de agentes trabajando en paralelo.

## Protocolo de un work package

```
ORQ: python bridge.py orchestrate next
     → lista de WP listos (dependencias en done)

ORQ: python bridge.py orchestrate brief WP-03
     → brief autocontenido: objetivo, rutas, criterio de done, gates

SUB: ejecuta el brief y responde con rutas escritas + salida literal de tests

ORQ: python bridge.py orchestrate gate WP-03
     → ejecuta los gates y escribe orchestration/evidence/WP-03_<ts>.json
```

Estados posibles: `pending → in_progress → done | failed | blocked`. `blocked`
es un estado legítimo: significa "no se puede demostrar aquí" (por ejemplo,
validar `/gma3/cmd` sin grandMA3 onPC instalado).

## Reglas duras

1. **Contrato congelado.** `spec/unified_show.schema.json` v1.0.0 y los 6 tests de
   `tools/contract_test.py` no se tocan para poner verde. Un cambio de esquema
   necesita su propio WP y bump semver.
2. **Un dueño por ruta.** Si un subagente necesita cambiar una ruta ajena,
   devuelve el WP al orquestador en vez de editarla.
3. **Parsers no calculan Pan.** `bearing_deg` y `calculated_pan` los escribe sólo
   el motor de geometría; los parsers emiten `null`.
4. **Validadores no mutan input.** La coherencia de `mount_type` la inyecta el
   parser, no el validador.
5. **Sin DMX crudo.** La IA habla el Command Line de la consola. Los valores de
   canal son del renderizador, no del LLM.
6. **Dry-run por defecto.** `osc.send` sólo envía con `dry_run=False` explícito.
7. **Nada de hardware imaginario.** Lo que no se ha probado en una consola se
   documenta como no probado.

## Experiencia acumulada (lecciones)

Cada error no obvio se registra y **se inyecta en los briefs siguientes del mismo
rol**. Ese es el mecanismo de "coger experiencia": no hay memoria implícita, hay
un log que se lee antes de cada encargo.

```bash
python bridge.py lessons                                   # últimas 5
python bridge.py lessons --role SUB-PARSER --limit 10
python bridge.py lessons --add --role SUB-QA --wp WP-01 \
    --title "Un vector de oro puede estar mal" \
    --detail "Audita el número esperado antes de tocar producción."
```

Fichero: `agents/lessons.jsonl` (JSONL, append-only, una lección por línea).
`render_brief()` añade al brief las 5 últimas del rol, incluidas las globales
(`role="ALL"`). Si una lección deja de aplicar, se borra la línea: es memoria
operativa, no un archivo histórico.

## Portar el equipo a otro proyecto

El kit no depende de ShowPatch. Para arrancar otro proyecto:

```bash
cd showpatch
python tools/scaffold_project.py --dest C:\proyectos\mi-app --name mi-app
cd C:\proyectos\mi-app
python orchestrate.py status
```

Genera `orchestrator/` (DAG, gates, estado y evidencia), `tools/lessons.py`
(experiencia), `orchestrate.py` (CLI), un plan de 3 work packages con gates
reales y `agents/` con roles y lecciones vacías.

El gate por defecto ejecuta los tests del proyecto: si no hay tests, **falla**.
No hay verde de mentira; el primer trabajo real es convertir esa puerta en verde.

Cada proyecto tiene su propio `work_packages.json` y sus propias lecciones. Los
roles se reutilizan; la experiencia se separa por proyecto para no contaminar
dominios distintos.

## Despacho masivo

Para una pasada completa sin intervención:

```bash
python bridge.py orchestrate run            # respeta dependencias, para al primer fallo
python bridge.py orchestrate run --keep-going
python bridge.py orchestrate status --json  # para consumir desde otro proceso
```

`run` es idempotente: los WP ya en `done` se saltan salvo `--force`.

## Cuándo escalar al humano

- El gate falla por algo que no está en el repo (hardware, licencia, red).
- Hay que cambiar el esquema congelado.
- Hay que instalar software en la máquina (`gh`, `pandoc`, `lua`, Docker).
- Hay que enviar OSC real a una consola.
