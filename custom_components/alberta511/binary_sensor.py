"""Binary sensors for the selected 511 Alberta feed."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_TEMP_UNIT, DEFAULT_TEMP_UNIT
from .coordinator import Snapshot
from .entity import Alberta511Entity
from .models import f_to_c


@dataclass(frozen=True, kw_only=True)
class A511BinaryDescription(BinarySensorEntityDescription):
    value_fn: Callable[[Snapshot, dict[str, Any]], bool | None]


def _pavement_c(s: Snapshot, opts: dict[str, Any]) -> float | None:
    if not s.weather or s.weather.pavement_temperature is None:
        return None
    t = s.weather.pavement_temperature
    return f_to_c(t) if opts.get(CONF_TEMP_UNIT, DEFAULT_TEMP_UNIT) == "fahrenheit" else t


def _freezing(s: Snapshot, opts: dict[str, Any]) -> bool | None:
    t = _pavement_c(s, opts)
    return None if t is None else t <= 0.0


BINARY_SENSORS: tuple[A511BinaryDescription, ...] = (
    A511BinaryDescription(
        key="closure_nearby",
        name="Road closure nearby",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:road-variant",
        value_fn=lambda s, _o: any(e.is_full_closure for _, e in s.events) if s.view else None,
    ),
    A511BinaryDescription(
        key="pavement_freezing",
        name="Pavement at or below freezing",
        device_class=BinarySensorDeviceClass.COLD,
        value_fn=_freezing,
    ),
    A511BinaryDescription(
        key="camera_online",
        name="Camera online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s, _o: s.view.enabled if s.view else None,
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities(Alberta511BinarySensor(entry, d) for d in BINARY_SENSORS)


class Alberta511BinarySensor(Alberta511Entity, BinarySensorEntity):
    entity_description: A511BinaryDescription

    def __init__(self, entry, description: A511BinaryDescription) -> None:
        super().__init__(entry, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.snapshot, self._entry.options)
