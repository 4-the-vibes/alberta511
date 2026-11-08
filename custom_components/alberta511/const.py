"""Constants for the Alberta 511 integration."""

from __future__ import annotations

DOMAIN = "alberta511"

BASE_URL = "https://511.alberta.ca/api/v2/get"
CCTV_PAGE_URL = "https://511.alberta.ca/cctv"
ATTRIBUTION = "Data provided by 511 Alberta (Government of Alberta)"

# API collections
COLLECTION_CAMERAS = "cameras"
COLLECTION_WEATHER = "weatherstations"
COLLECTION_EVENTS = "event"
COLLECTION_ROADS = "roadconditions"
COLLECTION_ALERTS = "alerts"

# 511 Alberta throttles to ten calls every 60 seconds.
API_CALLS_PER_WINDOW = 10
API_WINDOW_SECONDS = 60

# Config entry data
CONF_API_KEY = "api_key"
CONF_CAMERA = "camera"
CONF_FILTER = "filter"
CONF_SHOW_SELECTOR = "show_feed_selector"

# Options
CONF_IMAGE_INTERVAL = "image_refresh_seconds"
CONF_DATA_INTERVAL = "data_refresh_minutes"
CONF_EVENT_RADIUS = "event_radius_km"
CONF_WEATHER_RADIUS = "weather_match_km"
CONF_TEMP_UNIT = "api_temperature_unit"
CONF_WIND_UNIT = "api_wind_speed_unit"

DEFAULT_IMAGE_INTERVAL = 120
DEFAULT_DATA_INTERVAL = 5
DEFAULT_EVENT_RADIUS = 15.0
DEFAULT_WEATHER_RADIUS = 5.0
DEFAULT_TEMP_UNIT = "celsius"
DEFAULT_WIND_UNIT = "km/h"
ROAD_CONDITION_MAX_KM = 3.0

# How often the (large, slow-changing) camera list itself is re-downloaded.
CAMERA_LIST_REFRESH_HOURS = 6

MAX_EVENTS_IN_ATTRIBUTES = 10
