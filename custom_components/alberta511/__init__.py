"""Alberta 511 traffic cameras, road weather and road conditions for Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONF_SHOW_SELECTOR
from .coordinator import (
    Alberta511Coordinator,
    FeedViewer,
    async_get_coordinator,
    async_release_coordinator,
)

BASE_PLATFORMS = [Platform.CAMERA, Platform.SENSOR, Platform.BINARY_SENSOR]


@dataclass
class Alberta511Runtime:
    coordinator: Alberta511Coordinator
    viewer: FeedViewer


type Alberta511ConfigEntry = ConfigEntry[Alberta511Runtime]


def _platforms(entry: ConfigEntry) -> list[Platform]:
    if entry.data.get(CONF_SHOW_SELECTOR, True):
        return [Platform.SELECT, *BASE_PLATFORMS]
    return list(BASE_PLATFORMS)


async def async_setup_entry(hass: HomeAssistant, entry: Alberta511ConfigEntry) -> bool:
    try:
        coordinator = await async_get_coordinator(hass, entry)
    except Exception:
        await async_release_coordinator(hass, entry)
        raise
    if coordinator.data is None:
        err = coordinator.last_exception
        await async_release_coordinator(hass, entry)
        raise ConfigEntryNotReady(f"511 Alberta not reachable: {err}")

    entry.runtime_data = Alberta511Runtime(coordinator, FeedViewer(entry, coordinator))
    await hass.config_entries.async_forward_entry_setups(entry, _platforms(entry))
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: Alberta511ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, _platforms(entry))
    if unloaded:
        await async_release_coordinator(hass, entry)
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
