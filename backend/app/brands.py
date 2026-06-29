"""Normalisation of АЗС brand names from messy OSM tags."""
import re

# canonical brand -> list of lowercase substrings that identify it
BRAND_PATTERNS = {
    "Лукойл": ["лукойл", "lukoil"],
    "Газпромнефть": ["газпромнефть", "газпром нефть", "gazpromneft", "gazprom neft"],
    "Газпром": ["газпром", "gazprom"],
    "Роснефть": ["роснефть", "rosneft"],
    "Татнефть": ["татнефть", "tatneft"],
    "Башнефть": ["башнефть", "bashneft"],
    "Сургутнефтегаз": ["сургутнефтегаз", "surgutneftegas", "снг"],
    "Шелл": ["shell", "шелл"],
    "ЕКА": ["ека", "eka"],
    "Нефтьмагистраль": ["нефтьмагистраль", "нефтемагистраль"],
    "Трасса": ["трасса"],
    "Iрбис": ["ирбис", "irbis"],
    "Калина Ойл": ["калина"],
    "Магнит": ["магнит"],
    "Нефтегазхолдинг": ["нефтегазхолдинг", "ннк", "nnk"],
    "Teboil": ["teboil", "тебойл"],
    "Газпромнефть-Аэро": ["аэро"],
    "Иркутскнефтепродукт": ["иркутскнефтепродукт"],
    "КарелияНефтепродукт": ["карелиянефтепродукт"],
    "Фаэтон": ["фаэтон"],
    "Прайм": ["prime", "прайм"],
}


def normalize_brand(*candidates):
    """Return a canonical brand name or None from a set of tag values."""
    for raw in candidates:
        if not raw:
            continue
        low = str(raw).strip().lower()
        for canonical, pats in BRAND_PATTERNS.items():
            for p in pats:
                if p in low:
                    return canonical
    # fall back to a cleaned-up version of the first non-empty candidate
    for raw in candidates:
        if raw and str(raw).strip():
            s = re.sub(r"\s+", " ", str(raw).strip())
            return s[:60]
    return None


# fuel tag (OSM) -> our fuel key
OSM_FUEL_MAP = {
    "fuel:octane_92": "ai92",
    "fuel:octane_95": "ai95",
    "fuel:octane_98": "ai98",
    "fuel:octane_100": "ai98",
    "fuel:diesel": "dt",
    "fuel:diesel:class3": "dt",
    "fuel:gtl_diesel": "dt",
    "fuel:biodiesel": "dt",
    "fuel:lpg": "gas",
    "fuel:cng": "gas",
    "fuel:lng": "gas",
    "fuel:propane": "gas",
}


def fuels_from_tags(tags: dict):
    found = set()
    for k, v in tags.items():
        if k in OSM_FUEL_MAP and str(v).lower() in ("yes", "true", "1"):
            found.add(OSM_FUEL_MAP[k])
    # ordering matches config.FUEL_TYPES
    order = ["ai92", "ai95", "ai98", "dt", "gas"]
    return [f for f in order if f in found]
