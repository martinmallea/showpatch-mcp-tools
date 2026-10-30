# Datos de fixtures — qué se obtuvo y de dónde

Dos fuentes analizadas: **ChamSys Fixture Finder** (catálogo real, integrado) y
**gdtf-build.com** (herramienta de conversión a GDTF, analizada como vía futura).

## 1. ChamSys Fixture Finder — integrado

`https://fixturefinder.chamsys.co.uk/` es una SPA (Vue + Vite) sobre Laravel. El
bundle `spa/assets/index-*.js` contiene las rutas reales de la API; no hay
autenticación para consultar metadatos.

### Endpoints descubiertos

| Método | Ruta | Devuelve |
|---|---|---|
| GET | `/api/v1/meta` | `{version:"29-10-2026", head_count:70225, manufacturer_count:874}` |
| GET | `/api/v1/manufacturers` | 874 fabricantes con `head_count` |
| GET | `/api/v1/library/all?page=N` | 300 filas/página, 235 páginas |
| GET | `/api/v1/fixtures/{id}` | detalle: `all_chans`, `channels`, `elements` |
| GET | `/api/v1/fixtures/{id}/modes` | modos alternativos con su conteo |
| GET | `/api/v1/fixtures/{id}/download` | archivo `.hed` (binario, **no** lo usamos) |
| POST | `/api/v1/search` | búsqueda por canal o por fabricante+nombre |
| GET | `https://api.chamsys.co.uk/api/fixtures/heads/download` | `Heads.all` completo |

Forma de una fila del índice:

```json
{"id": 2961, "m": "Acme", "n": "LEDStrobe50", "o": "10ch", "c": 10, "f": "Acme_LEDStrobe50_10ch.hed"}
```

`m` fabricante · `n` modelo · `o` modo · `c` canales · `f` archivo. Es,
literalmente, la tupla que le falta al parser cuando el patch no declara canales.

Detalle por fixture (útil para el futuro, no ingerido):

```json
{"id": 2961, "manufacturer": "Acme", "fixture_name": "LEDStrobe50",
 "mode": "10ch", "channel_count": 10,
 "all_chans": "Dimmer,Dimmer,Dimmer,...", "elements": {"duplicate": true, "count": 10}}
```

`all_chans` da la **función de cada canal en orden**, que es justo lo que el
finder intenta inferir. Queda como mejora pendiente: enriquecer
`spec/channel_functions.json` con layouts reales.

### Qué se ha ingerido

`spec/fixture_library.json` — **14 221 fixtures**, 17 fabricantes, 2,15 MB,
librería `29-10-2026`.

Criterio: los fabricantes que de verdad llegan a bolo. Touring (Robe 1 000,
Clay Paky, Martin 751) y el grueso de gamas de entrada y clones (ADJ 1 741,
Elation 1 651, Showtec 1 397, Cameo 1 330, Eurolite 1 328, Acme 1 257, BeamZ
1 032, Stairville, Shehds, Varytec, Ayra, JB Systems, Ignition, Generic…).

### Cómo se usa

```bash
python bridge.py fixtures --search pointe --manufacturer robe
# Robe  GigaPointe  Mode1  39 ch
# Robe  iPointe     Mode2  34 ch
# Robe  MegaPointe  Mode2  34 ch

python bridge.py fixtures --sync          # regenera (235 páginas, ~3 min)
python bridge.py fixtures --sync --all    # catálogo completo (~70k)
```

En el parser funciona como **último recurso**, después de regex y diccionarios:

```
"Robe Pointe 24ch Mode 1"  -> 24 ch  (regex)
"Robe Robin Pointe"        -> 31 ch  (model_dict)
"ADJ Mega Tripar"          -> 24 ch  (library)   <- antes quedaba en None
```

`channel_count_source="library"` deja el origen auditable. Si hay varios modos y
ninguno se pidió, `resolve()` devuelve el más frecuente con `ambiguous=true` y la
lista de opciones: es una hipótesis, no un dato.

### Límites encontrados (y cómo se rodearon)

1. **`q` sólo busca por nombre de modelo.** Buscar "claypaky" devuelve 0 porque
   ninguna cabeza se llama así; "robe" devuelve 2 284 resultados porque coincide
   con "st**robe**". No hay filtro por fabricante en la API: el filtrado se hace
   en cliente, y por eso el sync recorre el catálogo entero (235 páginas).
2. **Rate limit explícito** ("Too many requests just now"). El sincronizador va a
   0,4–0,6 s por página y reintenta con backoff en HTTP 429.
3. **Sin paginación total en la respuesta**, pero `meta` trae `total` y
   `last_page` por consulta, así que la iteración termina sola.
4. **`.hed` es binario.** No se descarga: no aporta al contrato y multiplicaría
   el repo. El nombre de archivo sí se guarda como referencia.

### Cumplimiento

`robots.txt` declara `User-agent: * / Allow: /` con
`Content-Signal: search=yes, ai-train=no, use=reference` y bloquea crawlers de
entrenamiento. En consecuencia:

- ❌ no se usa para entrenar modelos ni se construye corpus;
- ✅ se guardan **metadatos factuales** (fabricante, modelo, modo, canales) para
  interoperabilidad, con atribución y URL de origen en el JSON;
- ✅ no se redistribuyen binarios ni definiciones propietarias;
- ✅ tráfico moderado (0,4 s/página) y regenerable con un comando.

## 2. gdtf-build.com — analizado, no integrado

Herramienta gratuita de LMNR que convierte un **patch de MA3 (`.xmlp`)**, una
personalidad de **Avolites (`.d4`)** o un **head file de ChamSys (`.hed`)** en un
perfil **GDTF 1.2** listo para grandMA3. Sin cuenta y sin coste.

Lo relevante para el proyecto:

1. **Confirma el flujo** que ya tenemos: patch de consola → perfil → consola.
2. **GDTF describe tipos, no instancias.** Nuestro `unified_show-1.0.0` describe
   el rig parcheado (posiciones, patch, semántica); GDTF describe el *fixture
   type* (modos, canales con atributos, geometría 3D con ejes de pan/tilt). Son
   capas complementarias, no competidoras.
3. **Ruta natural para el offset de Pan.** La geometría GDTF incluye los ejes
   del yugo; de ahí podría salir `pan_offset_deg` medido en vez de calibrado a
   ojo, que es hoy la parte más frágil de `core/pan_offsets.py`.
4. **Fuente local futura:** MA3 instala sus perfiles en
   `C:\ProgramData\MALightingTechnology\gma3_library\fixturetypes`. En esta
   máquina esa carpeta está **vacía** (no hay grandMA3 onPC instalado). Cuando lo
   haya, leer los `.gdtf` de ahí es más autoritativo que cualquier API web.
5. **Sin API pública.** La conversión ocurre en la web; no hay endpoint que
   reutilizar. No se automatiza.

Decisión: no se integra ahora. Se documenta como vía para (a) leer GDTF locales
cuando exista MA3 y (b) generar GDTF desde nuestro catálogo de canales. Añadirlo
sin un `.gdtf` real que validar sería código muerto.
