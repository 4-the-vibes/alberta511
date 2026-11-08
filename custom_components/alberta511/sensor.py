"""Sensors for the selected 511 Alberta feed: road weather, conditions, events."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfLength,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_TEMP_UNIT,
    CONF_WIND_UNIT,
    DEFAULT_TEMP_UNIT,
    DEFAULT_WIND_UNIT,
    MAX_EVENTS_IN_ATTRIBUTES,
)
from .coordinator import Snapshot
from .entity import Alberta511Entity
from .models import c_to_f, dew_point_c, f_to_c

WIND_UNITS = {
    "km/h": UnitOfSpeed.KILOMETERS_PER_HOUR,
    "mph": UnitOfSpeed.MILES_PER_HOUR,
    "m/s": UnitOfSpeed.METERS_PER_SECOND,
}


@dataclass(frozen=True, kw_only=True)
class A511SensorDescription(SensorEntityDescription):
    value_fn: Callable[[Snapshot, dict[str, Any]], Any]
    attrs_fn: Callable[[Snapshot], dict[str, Any]] | None = None
    unit_kind: str | None = None  # "temp" | "wind" -> resolved from options


def _w(attr: str) -> Callable[[Snapshot, dict[str, Any]], Any]:
    return lambda s, _o: getattr(s.weather, attr) if s.weather else None


def _dew_point(s: Snapshot, opts: dict[str, Any]) -> float | None:
    if not s.weather:
        return None
    temp = s.weather.air_temperature
    fahrenheit = opts.get(CONF_TEMP_UNIT, DEFAULT_TEMP_UNIT) == "fahrenheit"
    dp = dew_point_c(f_to_c(temp) if fahrenheit else temp, s.weather.relative_humidity)
    return round(c_to_f(dp), 1) if fahrenheit and dp is not None else dp


def _weather_attrs(s: Snapshot) -> dict[str, Any]:
    if not s.weather:
        return {}
    w = s.weather
    return {
        "station_id": w.station_id,
        "station_camera": f"{w.camera_source or ''} {w.camera_source_id or ''}".strip() or None,
        "station_distance_km": None if s.weather_distance is None else round(s.weather_distance, 2),
        "last_updated": w.last_updated.isoformat() if w.last_updated else None,
    }


def _road_attrs(s: Snapshot) -> dict[str, Any]:
    if not s.road:
        return {"source_available": "roadconditions" not in s.unavailable}
    r = s.road
    attrs = {
        "roadway": r.roadway,
        "segment": r.location,
        "visibility": r.visibility,
        "last_updated": r.last_updated.isoformat() if r.last_updated else None,
        "distance_km": None if s.road_distance is None else round(s.road_distance, 2),
    }
    # Pass through any extra scalar fields 511 adds (e.g. AreaName, Region).
    for k, v in r.extra.items():
        attrs.setdefault(k[:1].lower() + k[1:], v)
    return attrs


def _event_attrs(s: Snapshot) -> dict[str, Any]:
    return {
        "closures": sum(1 for _, e in s.events if e.is_full_closure),
        "events": [e.as_attribute(d) for d, e in s.events[:MAX_EVENTS_IN_ATTRIBUTES]],
    }


def _nearest_event_attrs(s: Snapshot) -> dict[str, Any]:
    return s.events[0][1].as_attribute(s.events[0][0]) if s.events else {}


def _alert_attrs(s: Snapshot) -> dict[str, Any]:
    return {
        "alerts": [
            {
                "message": a.message,
                "notes": a.notes,
                "regions": a.regions,
                "high_importance": a.high_importance,
                "start": a.start.isoformat() if a.start else None,
                "end": a.end.isoformat() if a.end else None,
            }
            for a in s.alerts[:MAX_EVENTS_IN_ATTRIBUTES]
        ]
    }


SENSORS: tuple[A511SensorDescription, ...] = (
    A511SensorDescription(
        key="air_temperature",
        name="Air temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        unit_kind="temp",
        value_fn=_w("air_temperature"),
        attrs_fn=_weather_attrs,
    ),
    A511SensorDescription(
        key="pavement_temperature",
        name="Pavement temperature",
        icon="mdi:road-variant",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        unit_kind="temp",
        value_fn=_w("pavement_temperature"),
    ),
    A511SensorDescription(
        key="dew_point",
        name="Dew point",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        unit_kind="temp",
        value_fn=_dew_point,
    ),
    A511SensorDescription(
        key="relative_humidity",
        name="Humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=_w("relative_humidity"),
    ),
    A511SensorDescription(
        key="wind_speed",
        name="Wind speed",
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        unit_kind="wind",
        value_fn=_w("wind_speed"),
    ),
    A511SensorDescription(
        key="wind_direction",
        name="Wind direction",
        icon="mdi:compass-outline",
        native_unit_of_measurement="°",
        value_fn=_w("wind_direction_deg"),
        attrs_fn=lambda s: {"cardinal": s.weather.wind_direction_cardinal} if s.weather else {},
    ),
    A511SensorDescription(
        key="weather_updated",
        name="Road weather updated",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_w("last_updated"),
    ),
    A511SensorDescription(
        key="weather_station_distance",
        name="Weather station distance",
        icon="mdi:map-marker-distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s, _o: None if s.weather_distance is None else round(s.weather_distance, 2),
    ),
    A511SensorDescription(
        key="road_condition",
        name="Road condition",
        icon="mdi:snowflake-alert",
        value_fn=lambda s, _o: (s.road.condition[:255] if s.road and s.road.condition else None),
        attrs_fn=_road_attrs,
    ),
    A511SensorDescription(
        key="nearby_events",
        name="Nearby events",
        icon="mdi:traffic-cone",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="events",
        value_fn=lambda s, _o: len(s.events) if s.view else None,
        attrs_fn=_event_attrs,
    ),
    A511SensorDescription(
        key="nearest_event_distance",
        name="Nearest event distance",
        icon="mdi:map-marker-alert",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        suggested_display_precision=1,
        value_fn=lambda s, _o: round(s.events[0][0], 2) if s.events else None,
        attrs_fn=_nearest_event_attrs,
    ),
    A511SensorDescription(
        key="nearest_event",
        name="Nearest event",
        icon="mdi:alert-outline",
        value_fn=lambda s, _o: (s.events[0][1].description or s.events[0][1].event_type or "")[:255]
        if s.events
        else "None",
    ),
    A511SensorDescription(
        key="provincial_alerts",
        name="Provincial 511 alerts",
        icon="mdi:bullhorn-outline",
        native_unit_of_measurement="alerts",
        value_fn=lambda s, _o: len(s.alerts),
        attrs_fn=_alert_attrs,
    ),
    A511SensorDescription(
        key="camera_status",
        name="Camera status",
        icon="mdi:cctv",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s, _o: s.view.status if s.view else None,
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities(Alberta511Sensor(entry, desc) for desc in SENSORS)


class Alberta511Sensor(Alberta511Entity, SensorEntity):
    entity_description: A511SensorDescription

    def __init__(self, entry, description: A511SensorDescription) -> None:
        super().__init__(entry, description.key)
        self.entity_description = description
        opts = entry.options
        if description.unit_kind == "temp":
            self._attr_native_unit_of_measurement = (
                UnitOfTemperature.FAHRENHEIT
                if opts.get(CONF_TEMP_UNIT, DEFAULT_TEMP_UNIT) == "fahrenheit"
                else UnitOfTemperature.CELSIUS
            )
        elif description.unit_kind == "wind":
            self._attr_native_unit_of_measurement = WIND_UNITS.get(
                opts.get(CONF_WIND_UNIT, DEFAULT_WIND_UNIT), UnitOfSpeed.KILOMETERS_PER_HOUR
            )

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.snapshot, self._entry.options)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        fn = self.entity_description.attrs_fn
        return fn(self.snapshot) if fn else None
