# Mapeo cross-platform → unified_show-1.0.0

| Concepto | MA3 nativo | ChamSys nativo | Campo JSON |
|---|---|---|---|
| ID de fixture | `Fixture 11` | `Head 11` | `fixtures[].id` |
| Universo/Dirección | `Patch 3.1` | `Universe 3, Addr 1` | `patch.universe` + `patch.address` |
| Tipo | `FixtureType "Robe Pointe"` | `Head Type: Robe Pointe` | `type.manufacturer` + `type.model` |
| Posición | `Position X/Y/Z` | `Plot X/Y/Z` | `position.x/y/z` |
| Rotación física | `Rotation` | `Orientation` | `position.rotation.pan_deg` |
| Montaje | (implícito) | (implícito) | `position.mount_type` |
| Color | `ColorRGB` / `ColorCMY` | `Colour` | `capabilities.color_system` |
| Grupo | `Group N` | `Group N` | `semantic.group_id` |

## Notas

- `rot_z` en MA3 = rotación física del yugo → `position.rotation.pan_deg`
- `bearing_deg` y `calculated_pan` son exclusivos de `intelligence.py`
- Los parsers emiten `semantic.*` como `null`/`0.0`
