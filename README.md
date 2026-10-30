# ShowPatch · MCP Tools

Puente entre un LLM y tres consolas de iluminación: **grandMA3**, **ChamSys MagicQ** y
**Wolfmix**. El modelo no escribe DMX: escribe comandos de consola y la consola renderiza.

## Qué resuelve

- **Patch con solapes**: detecta dos aparatos en la misma dirección antes del bolo.
- **Geometría**: herradura y matriz afín idempotentes, conservando alturas y rotación física.
- **Clones sin manual**: índice de 14 221 fixtures con modo y número de canales.
- **Color exacto**: RGB, CMY, HSV, RGBW y HEX con porcentajes, más simulación de daltonismo.
- **Repetición**: grabador de comandos con velocidad y bucle.
- **Monitor DMX**: escucha Art-Net y sACN para ver si la consola emite (no emite nada).

## Estado

Contrato `unified_show-1.0.0` congelado. Puerta única:

```bash
python bridge.py verify
```

Debe imprimir contrato 6/6, la suite completa en verde, esquema válido y roundtrip correcto.
Estado del plan: `python bridge.py orchestrate status`.

## Quickstart

```bash
python bridge.py web        # app local: panel, fixtures, DMX, color   (127.0.0.1:8787)
python bridge.py landing    # landing con registro y descargas         (127.0.0.1:8790)
python bridge.py mcp        # servidor MCP por stdio, para el LLM
```

Sin dependencias: sólo Python 3.10+ y biblioteca estándar.

## Estructura

```
spec/            contrato congelado, ejemplo, mapeo e índice de fixtures
core/            parsers, geometría, comandos, OSC, MIDI, monitor y captura DMX
bridges/         emisores por consola (grandMA3/ChamSys) y Wolfmix por MIDI
mcp_server/      11 herramientas JSON-RPC por stdio
web/             app local (panel.html) + API
landing/         landing de venta, registro y panel de admin
orchestrator/    DAG de work packages, gates y evidencia
agents/          roles del equipo y lecciones acumuladas
docs/            arquitectura, release, entorno y datos de fixtures
```

## Reglas de diseño

1. **Sin DMX crudo desde la IA.** Se mandan comandos; el render lo hace la consola.
2. **Dry-run por defecto.** Todo envío es simulado salvo orden explícita (`--live`).
3. **Allowlist de verbos** y rutas confinadas al repositorio.
4. **El contrato no se toca** para poner verde un test.

## Datos de terceros

El índice de fixtures proviene de ChamSys Fixture Finder. Atribución, límites de uso y
marcas en [NOTICE.md](NOTICE.md).

## Licencia

MIT. Ver [LICENSE](LICENSE).
