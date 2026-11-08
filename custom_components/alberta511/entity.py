"""Base entity for Alberta 511."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, CCTV_PAGE_URL, DOMAIN
from .coordinator import Alberta511Coordinator, FeedViewer, Snapshot


class Alberta511Entity(CoordinatorEntity[Alberta511Coordinator]):
    """Entity that follows the entry's currently selected feed."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(self, entry, key: str) -> None:
        runtime = entry.runtime_data
        super().__init__(runtime.coordinator)
        self._entry = entry
        self._viewer: FeedViewer = runtime.viewer
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Government of Alberta",
            model="511 Alberta camera feed",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=CCTV_PAGE_URL,
        )

    @property
    def snapshot(self) -> Snapshot:
        return self._viewer.snapshot()

    @property
    def available(self) -> bool:
        return super().available and self._viewer.view is not None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._viewer.add_listener(self._handle_feed_change))

    @callback
    def _handle_feed_change(self) -> None:
        self.async_write_ha_state()
