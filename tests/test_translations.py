"""Every translation has exactly the keys and placeholders of the English one."""

from __future__ import annotations

import json
import re
import string
from pathlib import Path

import pytest

TRANSLATIONS = Path(__file__).parent.parent / "custom_components" / "hp" / "translations"
LANGUAGES = [
    "bg",
    "cs",
    "da",
    "de",
    "el",
    "es",
    "fr",
    "hu",
    "it",
    "lv",
    "nl",
    "pl",
    "pt",
    "pt-BR",
    "ro",
    "ru",
    "sk",
    "sl",
    "sr",
    "sr-Latn",
    "sv",
    "uk",
]


def _flatten(data: dict, prefix: str = "") -> dict[str, str]:
    flat: dict[str, str] = {}
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(_flatten(value, path))
        else:
            flat[path] = value
    return flat


def _load(language: str) -> dict[str, str]:
    return _flatten(json.loads((TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8")))


def _placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name is not None}


def test_all_languages_are_tested():
    """A new translations/*.json file is added to LANGUAGES."""
    assert sorted(p.stem for p in TRANSLATIONS.glob("*.json")) == sorted(["en", *LANGUAGES])


@pytest.mark.parametrize("language", LANGUAGES)
def test_translation_parity(language: str):
    """Same keys as en.json (but entity names), same placeholders in each string, nothing empty."""
    english, other = _load("en"), _load(language)
    english = {key: text for key, text in english.items() if not key.startswith("entity.")}
    assert sorted(other) == sorted(english)
    for key, text in english.items():
        assert other[key].strip(), key
        assert _placeholders(other[key]) == _placeholders(text), key


# Serbian: brands, placeholders and identifiers stay in Latin script in the Cyrillic translation.
_SR_LATIN_ALLOWED = re.compile(r"HTTPS|HP|IP|PDF|JPEG|PNG|eSCL|AirScan|allowlist_external_dirs|scan_|A4|\bhp\b|\{\w+\}")


@pytest.mark.parametrize(
    ("language", "forbidden"),
    [("sr", r"[A-Za-z\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u024f]"), ("sr-Latn", r"[\u0400-\u04ff]")],
)
def test_serbian_script(language: str, forbidden: str):
    """No Latin letter in sr (but brands and placeholders), no Cyrillic letter in sr-Latn."""
    for key, text in _load(language).items():
        assert not re.search(forbidden, _SR_LATIN_ALLOWED.sub("", text)), key


@pytest.mark.parametrize("language", LANGUAGES)
def test_entity_names_not_translated(language: str):
    """Entity names (and their states) stay in English in every language: same names, same entity IDs."""
    data = json.loads((TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8"))
    assert "entity" not in data


def test_every_translation_key_is_used() -> None:
    """Each entity translation key of en.json belongs to an entity, and the other way round."""
    from custom_components.hp import binary_sensor, button, image, select, sensor

    english = json.loads((TRANSLATIONS / "en.json").read_text(encoding="utf-8"))["entity"]
    used = {
        "button": {button.SCAN.translation_key, button.ADD_PAGE.translation_key},
        "image": {image.LAST_IMAGE.translation_key},
        "select": {d.translation_key for d in select.SCAN_SELECTS},
        "binary_sensor": {binary_sensor.ONLINE.translation_key}
        | {d.translation_key for d in binary_sensor.CONNECTIVITY},
        "sensor": {sensor.STATUS.translation_key, sensor.LAST_SEEN.translation_key, sensor.LAST_SCAN.translation_key}
        | {d.translation_key for d in sensor.COUNTERS}
        | {f"{color}_{d.key}" for color in sensor.COLORS for d in sensor.CONSUMABLE_SENSORS},
    }
    assert {platform: set(keys) for platform, keys in english.items()} == used


def test_icons_match_translations() -> None:
    """Every entity has an icon, and every icon an entity."""
    icons = json.loads((TRANSLATIONS.parent / "icons.json").read_text(encoding="utf-8"))["entity"]
    english = json.loads((TRANSLATIONS / "en.json").read_text(encoding="utf-8"))["entity"]
    assert {p: set(k) for p, k in icons.items()} == {p: set(k) for p, k in english.items()}


def test_service_fields_translated() -> None:
    """Every field of services.yaml has a name in en.json, and every selector translation key exists."""
    import yaml

    services = yaml.safe_load((TRANSLATIONS.parent / "services.yaml").read_text(encoding="utf-8"))
    english = json.loads((TRANSLATIONS / "en.json").read_text(encoding="utf-8"))
    for service, spec in services.items():
        assert set(spec["fields"]) == set(english["services"][service]["fields"])
        for field in spec["fields"].values():
            if key := field["selector"].get("select", {}).get("translation_key"):
                options = set(field["selector"]["select"]["options"])
                assert set(english["selector"][key]["options"]) == options
