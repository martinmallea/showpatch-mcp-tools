# Release 1.0.0 — ShowPatch

**Fecha:** 2026-10-30
**Contrato:** `unified_show-1.0.0` (congelado)
**Estado:** verde en software; **sin validar en hardware**

## Qué entra en esta versión

| Área | Entregable | Verificación |
|---|---|---|
| Contrato | `spec/unified_show.schema.json` + 6 contract tests | 6/6 PASS |
| Ingesta | Parser XML grandMA3, import CSV ChamSys | 2 suites |
| Geometría | Herradura, matriz afín, Pan con offset de modelo | 1 suite |
| Diagnóstico | Fingerprinting DMX sin manual | 1 suite |
| Traducción | Comandos MA3/ChamSys + Lua escapado | 1 suite |
| Protocolo | Codec OSC 1.0 + servidor MCP (11 herramientas) | 2 suites |
| Orquestación | DAG de 10 work packages, gates y evidencia | 2 gates |
| Documentación | Arquitectura, entorno, este release, changelog | gates de fichero |

Puerta única:

```bash
python bridge.py verify
# ✅ contrato: 6/6 PASS
# ✅ módulos: 123 tests OK
# ✅ esquema: ejemplo válido
# ✅ roundtrip: herradura 6/6 + comandos OK
```

## Cómo se usa

```bash
python bridge.py mcp                  # servidor MCP por stdio
python bridge.py orchestrate status   # estado del plan
python bridge.py orchestrate run      # ejecuta y verifica todo
python bridge.py audit                # inventario del entorno
```

Herramientas MCP expuestas: `show.parse_ma3`, `show.parse_ma3_text`,
`show.parse_chamsys`, `show.validate`, `show.translate`, `layout.horseshoe`,
`geometry.adapt`, `fixture.fingerprint`, `rig.style_profile`, `osc.send`,
`lua.generate`.

## Checklist de publicación

- [x] Contrato 6/6 y módulos en verde
- [x] Repositorio listo para `git init` (el paquete se entregó sin `.git`)
- [ ] **`gh` instalado** — no está: sin él no hay remoto, ni PRs, ni protección de rama
- [ ] Remoto creado y `main` protegida con required status checks
- [ ] CI ejecutándose en GitHub Actions (workflow ya versionado)
- [ ] Tag `v1.0.0` firmado y publicado
- [ ] Validación en consola real (bloqueada, ver abajo)

Comandos exactos cuando `gh` esté instalado:

```bash
winget install --id GitHub.cli -e
gh auth login
git init -b main && git add . && git commit -m "chore: freeze unified_show-1.0.0"
gh repo create showpatch --public --source=. --push
git tag -a v1.0.0 -m "Contrato congelado 1.0.0" && git push origin v1.0.0
```

## Bloqueos conocidos (no son deuda técnica: son del entorno)

1. **No hay grandMA3 onPC instalado.** Hay grandMA2 onPC 3.9.60.63 y ChamSys
   MagicQ PC. Todo lo que dependa de `/gma3/cmd`, del plugin Lua de MA3 o del
   estado OSC de MA3 **no se puede validar aquí**. El paquete oficial es
   `grandMA3 onPC Software for Windows 2.5.1.1`; la web de MA bloquea la descarga
   automática (403 a clientes que no sean navegador), así que la descarga es un
   paso humano. Después: `tools/install_gma3_onpc.ps1`.
2. **Falta `gh`.** Bloquea la publicación, no el código.
3. **Falta `lua`/`luac`.** No se puede comprobar la sintaxis del plugin antes de
   cargarlo en consola.
4. **Falta `pandoc`.** La documentación no se exporta a PDF desde la CLI.

Detalle completo y remediación por herramienta: [`docs/ENVIRONMENT.md`](ENVIRONMENT.md).

## Limitaciones funcionales declaradas

- ChamSys: sólo import CSV, sin cliente HTTP vivo.
- Sin salida DMX (Art-Net/sACN): el puente manda comandos, la consola renderiza.
- grandMA2: el esquema lo admite como origen, los emisores no lo soportan como
  destino.
- Estado OSC en memoria, sin histórico.
- Offsets de Pan por modelo son hipótesis calibradas en mesa, no medidas en
  cada fixture físico.

## Añadido después de 1.0.0

**1.3.0** renombra el proyecto a **ShowPatch** (antes MA AI Bridge): el nombre
antiguo nombraba una consola y el puente habla con tres. Ver `CHANGELOG.md`.

**1.1.0** incorpora el índice de fixtures de ChamSys Fixture Finder (14 221
fixtures) y la CLI `python bridge.py fixtures`. No cambia el contrato
`unified_show-1.0.0` ni los 6 tests congelados. Detalle en
[`CHANGELOG.md`](../CHANGELOG.md) y [`FIXTURE_DATA.md`](FIXTURE_DATA.md).

## Reversión

El contrato está congelado y etiquetado. Para volver atrás:

```bash
git checkout v1.0.0        # o el commit anterior a un cambio de esquema
```

Un cambio de esquema exige work package propio, bump semver y PR separada. Nunca
se cambia el esquema para que pase un test.
