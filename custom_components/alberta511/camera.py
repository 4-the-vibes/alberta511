"""Camera entity showing the selected 511 Alberta still-image feed."""

from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.components.camera import Camera
from homeassistant.const import ATTR_LATITUDE, ATTR_LONGITUDE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import Alberta511Error
from .const import CONF_IMAGE_INTERVAL, DEFAULT_IMAGE_INTERVAL
from .entity import Alberta511Entity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([Alberta511Camera(entry)])


class Alberta511Camera(Alberta511Entity, Camera):
    _attr_name = None  # use the device name
    _attr_icon = "mdi:cctv"

    def __init__(self, entry) -> None:
        Alberta511Entity.__init__(self, entry, "camera")
        Camera.__init__(self)
        self._interval = int(entry.options.get(CONF_IMAGE_INTERVAL, DEFAULT_IMAGE_INTERVAL))
        self._attr_frame_interval = float(self._interval)
        self._image: bytes | None = None
        self._image_key: str | None = None
        self._fetched_at = 0.0

    @property
    def available(self) -> bool:
        view = self._viewer.view
        return super().available and view is not None and view.enabled

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        view = self._viewer.view
        if view is None:
            return {}
        attrs: dict[str, Any] = {
            "feed": self._viewer.label,
            "roadway": view.roadway,
            "location": view.location,
            "direction": view.direction,
            "view": view.description,
            "view_status": view.status,
            "camera_id": view.camera_id,
            "view_id": view.view_id,
            "image_url": view.url,
        }
        if view.has_location:
            attrs[ATTR_LATITUDE] = view.latitude
            attrs[ATTR_LONGITUDE] = view.longitude
        return attrs

    @callback
    def _handle_feed_change(self) -> None:
        # New feed selected: force a fresh image and bump the access token so
        # dashboards drop the cached picture immediately.
        self._fetched_at = 0.0
        self.async_update_token()
        super()._handle_feed_change()

    async def async_camera_image(self, width: int | None = None, height: int | None = None) -> bytes | None:
        view = self._viewer.view
        if view is None:
            return None
        now = time.monotonic()
        if self._image is not None and self._image_key == view.key and now - self._fetched_at < self._interval:
            return self._image
        client = self.coordinator.client
        try:
            self._image = await client.async_fetch_image(view.url)
            self._image_key = view.key
            self._fetched_at = now
        except Alberta511Error as err:
            _LOGGER.debug("Image fetch failed for %s: %s", view.key, err)
            if self._image_key != view.key:
                return None
        return self._image
