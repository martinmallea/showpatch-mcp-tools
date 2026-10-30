# ShowPatch — Visión general del proyecto

## 1. Problema

El cuello de botella en iluminación profesional no es la consola, sino
el trabajo offline y la fricción en bolo:

- Adaptar un show de gira a un festival con escenario 30% más pequeño.
- Parchear robótica china sin manuales.
- Traducir de MA3 a ChamSys cuando cambian la mesa a última hora.

## 2. Solución

ShowPatch expone herramientas MCP consumibles por un LLM (Claude
Desktop, Llama 3 vía Ollama) que razona sobre el rig y aplica cambios
en caliente sobre el hardware, vía OSC/UDP y generación de Lua.

## 3. Arquitectura en 4 fases

- **Fase 1**: Parsers. Extrae show de MA3 (XML) y ChamSys (HTTP) a
  `unified_show-1.0.0` (JSON agnóstico).
- **Fase 2**: Finder. Fingerprinting de canales DMX de robótica
  desconocida.
- **Fase 3**: Intelligence. Matrices afines, herraduras, cálculo de Pan
  teórico.
- **Fase 4**: MCP Server. JSON-RPC + inyección OSC + generación Lua.

## 4. Principios de diseño

1. Agnóstico por defecto (sin terminología nativa MA/ChamSys).
2. Anidamiento semántico (position / optics / capabilities / semantic).
3. Versionado explícito (schema_version en raíz).
4. Extensible sin breaking (metadata.extensions.<namespace>).
5. Idempotencia geométrica (rotation física ≠ bearing semántico).

## 5. Seguridad y límites

- La IA nunca envía DMX crudo (jitter y latencia rompen el ritmo).
- La IA interactúa con el Command Line de la consola.
- UDP no tiene ACK: la sincronización bidireccional se valida con
  hooks Lua residentes + polling a 500ms como red de seguridad.
- El 2-Port Node no "libera" parámetros: onPC + Node desbloquean hasta
  2048/4096 según producto.

## 6. Gobernanza

- Repositorio personal (no organización) hasta que el proyecto crezca.
- Una rama `main` protegida con required status checks de CI.
- PRs requieren 6/6 PASS del contract test.
- Cambios de schema requieren PR separada con bump semver.

## 7. Roadmap

1. Validar contrato local (6/6 PASS)
2. Publicar repo en GitHub
3. Portar `bridges/ma_bridge/` con implementación MA3 real
4. Validar contra grandMA3 onPC + Node 2-Port físico
5. Añadir `bridges/chamsys_bridge/`
6. Empaquetar como librería Python y plugin MA3
