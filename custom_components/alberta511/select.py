"""Feed selector (dropdown of every 511 Alberta camera view)."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .entity import Alberta511Entity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([Alberta511FeedSelect(entry)])


class Alberta511FeedSelect(Alberta511Entity, SelectEntity, RestoreEntity):
    _attr_name = "Feed"
    _attr_icon = "mdi:cctv"

    def __init__(self, entry) -> None:
        super().__init__(entry, "feed_select")

    @property
    def available(self) -> bool:
        # Stay usable even if the current feed vanished, so the user can pick another.
        return self.coordinator.data is not None and bool(self.coordinator.data.labels)

    @property
    def options(self) -> list[str]:
        return list(self.coordinator.data.labels) if self.coordinator.data else []

    @property
    def current_option(self) -> str | None:
        return self._viewer.label

    async def async_select_option(self, option: str) -> None:
        key = self.coordinator.data.labels.get(option) if self.coordinator.data else None
        if key is None:
            raise ValueError(f"Unknown 511 Alberta feed: {option}")
        self._viewer.select(key)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        data = self.coordinator.data
        if last and data and last.state in data.labels:
            self._viewer.select(data.labels[last.state])
