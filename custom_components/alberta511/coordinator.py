"""Shared data hub and per-entry feed viewer for Alberta 511."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import Alberta511AuthError, Alberta511Client, Alberta511Error, Alberta511NotFound
from .const import (
    CAMERA_LIST_REFRESH_HOURS,
    COLLECTION_ALERTS,
    COLLECTION_CAMERAS,
    COLLECTION_EVENTS,
    COLLECTION_ROADS,
    COLLECTION_WEATHER,
    CONF_API_KEY,
    CONF_CAMERA,
    CONF_DATA_INTERVAL,
    CONF_EVENT_RADIUS,
    CONF_WEATHER_RADIUS,
    DEFAULT_DATA_INTERVAL,
    DEFAULT_EVENT_RADIUS,
    DEFAULT_WEATHER_RADIUS,
    DOMAIN,
    ROAD_CONDITION_MAX_KM,
)
from .models import (
    Alert,
    CameraView,
    RoadCondition,
    RoadEvent,
    WeatherReading,
    build_labels,
    match_weather,
    nearby_events,
    nearest_road_condition,
    parse_alerts,
    parse_cameras,
    parse_events,
    parse_road_conditions,
    parse_weather,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class HubData:
    views: dict[str, CameraView] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)  # label -> key
    key_to_label: dict[str, str] = field(default_factory=dict)
    weather: list[WeatherReading] = field(default_factory=list)
    events: list[RoadEvent] = field(default_factory=list)
    roads: list[RoadCondition] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)
    cameras_fetched: datetime | None = None
    unavailable: set[str] = field(default_factory=set)
    generation: int = 0


class Alberta511Coordinator(DataUpdateCoordinator[HubData]):
    """Polls every collection once per interval for all configured feeds."""

    def __init__(self, hass: HomeAssistant, client: Alberta511Client) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=None,  # shared by several entries
            name=DOMAIN,
            update_interval=timedelta(minutes=DEFAULT_DATA_INTERVAL),
        )
        self.client = client
        self._entry_intervals: dict[str, int] = {}
        self._missing_logged: set[str] = set()

    # -- interval management ------------------------------------------------ #
    def register(self, entry_id: str, minutes: int) -> None:
        self._entry_intervals[entry_id] = minutes
        self._recalc_interval()

    def unregister(self, entry_id: str) -> bool:
        """Return True when no entries remain."""
        self._entry_intervals.pop(entry_id, None)
        self._recalc_interval()
        return not self._entry_intervals

    def _recalc_interval(self) -> None:
        if self._entry_intervals:
            self.update_interval = timedelta(minutes=min(self._entry_intervals.values()))

    # -- polling -------------------------------------------------------------- #
    async def _fetch_optional(self, collection: str, parser: Callable[[Any], list], previous: list, unavailable: set[str]) -> list:
        try:
            return parser(await self.client.async_get(collection))
        except Alberta511NotFound:
            unavailable.add(collection)
            if collection not in self._missing_logged:
                self._missing_logged.add(collection)
                _LOGGER.info("511 Alberta does not publish '%s'; related sensors stay unknown", collection)
            return []
        except Alberta511AuthError:
            raise
        except Alberta511Error as err:
            _LOGGER.warning("Could not refresh 511 Alberta %s: %s", collection, err)
            return previous

    async def _async_update_data(self) -> HubData:
        old = self.data or HubData()
        new = HubData(
            views=old.views,
            labels=old.labels,
            key_to_label=old.key_to_label,
            cameras_fetched=old.cameras_fetched,
            generation=old.generation + 1,
        )
        now = dt_util.utcnow()
        try:
            stale = (
                not old.views
                or old.cameras_fetched is None
                or now - old.cameras_fetched > timedelta(hours=CAMERA_LIST_REFRESH_HOURS)
            )
            if stale:
                try:
                    views = parse_cameras(await self.client.async_get(COLLECTION_CAMERAS))
                    if views:
                        new.views = {v.key: v for v in views}
                        new.labels = build_labels(views)
                        new.key_to_label = {k: label for label, k in new.labels.items()}
                        new.cameras_fetched = now
                except Alberta511Error as err:
                    if isinstance(err, Alberta511AuthError) or not old.views:
                        raise
                    _LOGGER.warning("Keeping cached camera list: %s", err)
            if not new.views:
                raise UpdateFailed("511 Alberta returned no cameras")

            new.weather = await self._fetch_optional(COLLECTION_WEATHER, parse_weather, old.weather, new.unavailable)
            new.events = await self._fetch_optional(COLLECTION_EVENTS, parse_events, old.events, new.unavailable)
            new.roads = await self._fetch_optional(COLLECTION_ROADS, parse_road_conditions, old.roads, new.unavailable)
            new.alerts = await self._fetch_optional(COLLECTION_ALERTS, parse_alerts, old.alerts, new.unavailable)
        except Alberta511AuthError as err:
            raise ConfigEntryAuthFailed(
                "511 Alberta rejected the developer key. Re-enter it in the integration."
            ) from err
        except Alberta511Error as err:
            raise UpdateFailed(str(err)) from err
        return new


# --------------------------------------------------------------------------- #
# Hub registry (one coordinator per API key, shared across config entries)
# --------------------------------------------------------------------------- #
def _hubs(hass: HomeAssistant) -> dict[str, Alberta511Coordinator]:
    return hass.data.setdefault(DOMAIN, {})


async def async_get_coordinator(hass: HomeAssistant, entry: ConfigEntry) -> Alberta511Coordinator:
    api_key = (entry.data.get(CONF_API_KEY) or "").strip()
    hubs = _hubs(hass)
    coordinator = hubs.get(api_key)
    if coordinator is None:
        client = Alberta511Client(async_get_clientsession(hass), api_key or None)
        coordinator = Alberta511Coordinator(hass, client)
        hubs[api_key] = coordinator
    coordinator.register(entry.entry_id, int(entry.options.get(CONF_DATA_INTERVAL, DEFAULT_DATA_INTERVAL)))
    hass.data.setdefault(f"{DOMAIN}_entry_keys", {})[entry.entry_id] = api_key
    if coordinator.data is None:
        await coordinator.async_refresh()
        if not coordinator.last_update_success:
            exc = coordinator.last_exception
            if isinstance(exc, ConfigEntryAuthFailed):
                raise exc
    return coordinator


async def async_release_coordinator(hass: HomeAssistant, entry: ConfigEntry) -> None:
    # Use the key this entry registered with (it may have changed via re-auth).
    entry_keys = hass.data.setdefault(f"{DOMAIN}_entry_keys", {})
    api_key = entry_keys.pop(entry.entry_id, (entry.data.get(CONF_API_KEY) or "").strip())
    hubs = _hubs(hass)
    coordinator = hubs.get(api_key)
    if coordinator and coordinator.unregister(entry.entry_id):
        await coordinator.async_shutdown()
        hubs.pop(api_key, None)


# --------------------------------------------------------------------------- #
# Viewer: which feed an entry is showing, plus derived data for that feed
# --------------------------------------------------------------------------- #
@dataclass
class Snapshot:
    view: CameraView | None
    weather: WeatherReading | None = None
    weather_distance: float | None = None
    road: RoadCondition | None = None
    road_distance: float | None = None
    events: list[tuple[float, RoadEvent]] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)
    unavailable: set[str] = field(default_factory=set)


class FeedViewer:
    """Tracks the selected feed for one config entry and computes its context."""

    def __init__(self, entry: ConfigEntry, coordinator: Alberta511Coordinator) -> None:
        self.entry = entry
        self.coordinator = coordinator
        self.selected: str = entry.data[CONF_CAMERA]
        self._listeners: list[CALLBACK_TYPE] = []
        self._cache_key: tuple | None = None
        self._cache: Snapshot | None = None

    @property
    def view(self) -> CameraView | None:
        data = self.coordinator.data
        return data.views.get(self.selected) if data else None

    @property
    def label(self) -> str | None:
        data = self.coordinator.data
        return data.key_to_label.get(self.selected) if data else None

    @callback
    def select(self, key: str) -> None:
        if key == self.selected:
            return
        self.selected = key
        self._cache_key = None
        for listener in list(self._listeners):
            listener()

    @callback
    def add_listener(self, listener: CALLBACK_TYPE) -> CALLBACK_TYPE:
        self._listeners.append(listener)

        @callback
        def _remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _remove

    def snapshot(self) -> Snapshot:
        data = self.coordinator.data
        opts = self.entry.options
        event_radius = float(opts.get(CONF_EVENT_RADIUS, DEFAULT_EVENT_RADIUS))
        weather_radius = float(opts.get(CONF_WEATHER_RADIUS, DEFAULT_WEATHER_RADIUS))
        key = (self.selected, data.generation if data else -1, event_radius, weather_radius)
        if self._cache is not None and key == self._cache_key:
            return self._cache
        view = self.view
        snap = Snapshot(view=view)
        if data is not None:
            snap.alerts = data.alerts
            snap.unavailable = data.unavailable
        if view is not None and data is not None:
            snap.weather, snap.weather_distance = match_weather(view, data.weather, weather_radius)
            snap.road, snap.road_distance = nearest_road_condition(view, data.roads, ROAD_CONDITION_MAX_KM)
            snap.events = nearby_events(view, data.events, event_radius)
        self._cache, self._cache_key = snap, key
        return snap
