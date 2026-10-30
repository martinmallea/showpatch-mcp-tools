"""Offsets de Pan por modelo de fixture con calibración in-situ."""

PAN_OFFSETS = {
    "Robe_Pointe": 0.0, "Robe_Robin_Pointe": 0.0,
    "Robe_MegaPointe": 0.0, "Robe_LEDBeam_12": 90.0,
    "Robe_Spikie": 0.0, "ClayPaky_Sharpy": 0.0,
    "ClayPaky_Sharpy_Wash": 0.0, "Martin_Mac_Aura": 0.0,
    "Martin_Mac_Viper": 0.0, "Beam_230W": 90.0,
    "Beam_7R": 90.0, "Moving_Head_Wash_19x15": 0.0,
    "Moving_Head_Beam_380": 90.0, "__default__": 0.0,
}

PAN_INVERT = {"Robe_LEDBeam_12": False, "__default__": False}


def normalize_fixture_key(manufacturer: str, model: str) -> str:
    raw = f"{manufacturer}_{model}".replace(" ", "_").replace("-", "_")
    return raw if raw in PAN_OFFSETS else "__default__"


def get_pan_offset(fixture_key: str) -> float:
    return PAN_OFFSETS.get(fixture_key, PAN_OFFSETS["__default__"])


def apply_pan_offset(bearing_deg: float, fixture_key: str) -> float:
    offset = get_pan_offset(fixture_key)
    pan = bearing_deg + offset
    if PAN_INVERT.get(fixture_key, PAN_INVERT["__default__"]):
        pan = -pan
    while pan > 270.0: pan -= 540.0
    while pan < -270.0: pan += 540.0
    return round(pan, 2)


def calibrate_with_offset_keyword(fixture_id: str, observed_pan: float, target_bearing: float) -> str:
    correction = round(target_bearing - observed_pan, 2)
    return (
        f'Set Fixture {fixture_id} Attribute "PAN" At {observed_pan}; '
        f'User name[Fixture {fixture_id}]> Store Offset'
        f'  # corrección sugerida: {correction}°'
    )
