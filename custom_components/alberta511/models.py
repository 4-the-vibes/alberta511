"""Pure-Python parsing and geo helpers for 511 Alberta data.

Nothing in this module imports Home Assistant, so it can be unit-tested on its
own. The 511 platform (Castle Rock / IBI "CARS") is not perfectly consistent
between deployments and API versions, so every parser accepts several field
name aliases and tolerates missing or oddly formatted values.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

EARTH_RADIUS_KM = 6371.0088
ALBERTA_TZ = ZoneInfo("America/Edmonton")

CARDINALS = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]
CARDINAL_TO_DEG = {name: i * 22.5 for i, name in enumerate(CARDINALS)}
CARDINAL_TO_DEG.update(
    {"NORTH": 0.0, "EAST": 90.0, "SOUTH": 180.0, "WEST": 270.0}
)

_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


# --------------------------------------------------------------------------- #
# Generic value helpers
# --------------------------------------------------------------------------- #
def first(record: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Return the first present, non-empty value among several key aliases."""
    for key in keys:
        if key in record and record[key] not in (None, ""):
            return record[key]
    return default


def parse_float(value: Any) -> float | None:
    """Parse '12.1', '64%', '42.8 °F', 12 or None into a float."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    match = _NUMBER_RE.search(str(value))
    if not match:
        return None
    return float(match.group())


def parse_time(value: Any) -> datetime | None:
    """Parse a Unix timestamp (s or ms), ISO string or legacy 511 date string."""
    if value in (None, "", 0):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        ts = float(value)
        if ts > 1e12:  # milliseconds
            ts /= 1000
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if text.isdigit():
        return parse_time(int(text))
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=ALBERTA_TZ)
    except ValueError:
        pass
    for fmt in ("%b %d %Y, %I:%M %p", "%m/%d/%Y %I:%M:%S %p", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=ALBERTA_TZ)
        except ValueError:
            continue
    return None


def parse_wind_direction(value: Any) -> tuple[float | None, str | None]:
    """Return (degrees, cardinal) from '224', 224, 'NW' or 'North'."""
    if value in (None, ""):
        return None, None
    text = str(value).strip().upper()
    if text in CARDINAL_TO_DEG:
        deg = CARDINAL_TO_DEG[text]
        return deg, degrees_to_cardinal(deg)
    deg = parse_float(value)
    if deg is None:
        return None, None
    deg %= 360
    return deg, degrees_to_cardinal(deg)


def degrees_to_cardinal(deg: float) -> str:
    return CARDINALS[int((deg % 360) / 22.5 + 0.5) % 16]


def dew_point_c(temp_c: float | None, rh: float | None) -> float | None:
    """Magnus-formula dew point in °C."""
    if temp_c is None or rh is None or rh <= 0:
        return None
    b, c = 17.62, 243.12
    gamma = math.log(min(rh, 100.0) / 100.0) + (b * temp_c) / (c + temp_c)
    return round(c * gamma / (b - gamma), 1)


def f_to_c(value: float | None) -> float | None:
    return None if value is None else (value - 32.0) * 5.0 / 9.0


def c_to_f(value: float | None) -> float | None:
    return None if value is None else value * 9.0 / 5.0 + 32.0


# --------------------------------------------------------------------------- #
# Geo helpers
# --------------------------------------------------------------------------- #
def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def decode_polyline(encoded: str | None, precision: int = 5) -> list[tuple[float, float]]:
    """Decode a Google encoded polyline into [(lat, lon), ...]."""
    if not encoded or not isinstance(encoded, str):
        return []
    coords: list[tuple[float, float]] = []
    index = lat = lon = 0
    factor = 10**precision
    length = len(encoded)
    try:
        while index < length:
            deltas = []
            for _ in range(2):
                shift = result = 0
                while True:
                    byte = ord(encoded[index]) - 63
                    index += 1
                    result |= (byte & 0x1F) << shift
                    shift += 5
                    if byte < 0x20:
                        break
                deltas.append(~(result >> 1) if result & 1 else result >> 1)
            lat += deltas[0]
            lon += deltas[1]
            coords.append((lat / factor, lon / factor))
    except IndexError:
        # Truncated polyline: keep whatever decoded cleanly.
        pass
    return coords


def distance_to_path_km(
    lat: float, lon: float, path: list[tuple[float, float]]
) -> float | None:
    """Shortest distance (km) from a point to a polyline (segments, not just vertices)."""
    if not path:
        return None
    if len(path) == 1:
        return haversine_km(lat, lon, *path[0])
    # Local equirectangular projection centred on the point: accurate to well
    # under 1% at the tens-of-km scale this is used for.
    kx = math.radians(1) * EARTH_RADIUS_KM * math.cos(math.radians(lat))
    ky = math.radians(1) * EARTH_RADIUS_KM
    best = math.inf
    prev = None
    for plat, plon in path:
        cur = ((plon - lon) * kx, (plat - lat) * ky)
        if prev is not None:
            best = min(best, _point_segment_origin(prev, cur))
        prev = cur
    return best


def _point_segment_origin(a: tuple[float, float], b: tuple[float, float]) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    t = 0.0 if seg2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / seg2))
    px, py = ax + t * dx, ay + t * dy
    return math.hypot(px, py)


# --------------------------------------------------------------------------- #
# Data models
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CameraView:
    """One selectable image feed (a camera can have several views)."""

    key: str
    camera_id: str
    view_id: str
    url: str
    status: str | None
    description: str | None
    source: str | None
    source_id: str | None
    roadway: str | None
    direction: str | None
    location: str | None
    latitude: float | None
    longitude: float | None
    view_count: int = 1
    embedded_weather: dict[str, Any] | None = None

    @property
    def enabled(self) -> bool:
        if not self.status:
            return True
        return self.status.strip().lower() in ("enabled", "active", "online", "true")

    @property
    def has_location(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    def base_label(self) -> str:
        location = self.location or f"Camera {self.camera_id}"
        if self.roadway and self.roadway.lower() not in location.lower():
            label = f"{self.roadway} – {location}"
        else:
            label = location
        extras = []
        if self.view_count > 1 and self.description:
            extras.append(self.description)
        if self.direction and self.direction.lower() not in ("unknown", "none", ""):
            extras.append(self.direction)
        if extras:
            label += f" ({', '.join(extras)})"
        return label


@dataclass(frozen=True)
class WeatherReading:
    station_id: str
    latitude: float | None
    longitude: float | None
    last_updated: datetime | None
    camera_source: str | None
    camera_source_id: str | None
    air_temperature: float | None
    pavement_temperature: float | None
    wind_speed: float | None
    wind_direction_deg: float | None
    wind_direction_cardinal: str | None
    relative_humidity: float | None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RoadEvent:
    event_id: str
    roadway: str | None
    direction: str | None
    description: str | None
    event_type: str | None
    event_subtype: str | None
    severity: str | None
    is_full_closure: bool
    lanes_affected: str | None
    start: datetime | None
    planned_end: datetime | None
    last_updated: datetime | None
    latitude: float | None
    longitude: float | None
    latitude2: float | None
    longitude2: float | None
    path: tuple[tuple[float, float], ...] = ()
    details: str | None = None

    def distance_km(self, lat: float, lon: float) -> float | None:
        candidates: list[float] = []
        if self.latitude is not None and self.longitude is not None:
            candidates.append(haversine_km(lat, lon, self.latitude, self.longitude))
        if self.latitude2 is not None and self.longitude2 is not None:
            candidates.append(haversine_km(lat, lon, self.latitude2, self.longitude2))
        if self.path:
            d = distance_to_path_km(lat, lon, list(self.path))
            if d is not None:
                candidates.append(d)
        return min(candidates) if candidates else None

    def as_attribute(self, distance: float | None) -> dict[str, Any]:
        return {
            "description": self.description,
            "type": self.event_type,
            "subtype": self.event_subtype,
            "roadway": self.roadway,
            "direction": self.direction,
            "severity": self.severity,
            "full_closure": self.is_full_closure,
            "lanes_affected": self.lanes_affected,
            "distance_km": None if distance is None else round(distance, 1),
            "start": self.start.isoformat() if self.start else None,
            "planned_end": self.planned_end.isoformat() if self.planned_end else None,
        }


@dataclass(frozen=True)
class RoadCondition:
    condition_id: str
    roadway: str | None
    location: str | None
    condition: str | None
    visibility: str | None
    last_updated: datetime | None
    path: tuple[tuple[float, float], ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Alert:
    alert_id: str
    message: str | None
    notes: str | None
    start: datetime | None
    end: datetime | None
    regions: list[str]
    high_importance: bool


# --------------------------------------------------------------------------- #
# Parsers
# --------------------------------------------------------------------------- #
_WEATHER_KEYS = ("AirTemperature", "PavementTemperature", "WindSpeed", "RelativeHumidity")


def _as_list(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [r for r in raw if isinstance(r, dict)]
    if isinstance(raw, dict):
        # Some deployments wrap the array, e.g. {"Cameras": [...]}.
        for value in raw.values():
            if isinstance(value, list):
                return [r for r in value if isinstance(r, dict)]
    return []


def parse_cameras(raw: Any) -> list[CameraView]:
    views: list[CameraView] = []
    for rec in _as_list(raw):
        cam_id = str(first(rec, "Id", "ID", "id", default=""))
        if not cam_id:
            continue
        raw_views = rec.get("Views") or rec.get("views") or []
        if not raw_views:
            url = first(rec, "Url", "ImageUrl", "Image")
            if url:
                raw_views = [{"Id": cam_id, "Url": url, "Status": rec.get("Status")}]
        raw_views = [v for v in raw_views if isinstance(v, dict) and first(v, "Url", "url")]
        embedded = (
            {k: rec[k] for k in rec if k in _WEATHER_KEYS or k.startswith("Wind") or k == "WeatherUpdated"}
            if any(k in rec for k in _WEATHER_KEYS)
            else None
        )
        for view in raw_views:
            view_id = str(first(view, "Id", "ID", default=cam_id))
            views.append(
                CameraView(
                    key=f"{cam_id}:{view_id}",
                    camera_id=cam_id,
                    view_id=view_id,
                    url=str(first(view, "Url", "url")),
                    status=first(view, "Status", "status"),
                    description=first(view, "Description", "description"),
                    source=first(rec, "Source", "Organization"),
                    source_id=first(rec, "SourceId", "SourceID"),
                    roadway=first(rec, "Roadway", "RoadwayName"),
                    direction=first(rec, "Direction", "DirectionOfTravel"),
                    location=first(rec, "Location", "Name", "Description"),
                    latitude=parse_float(first(rec, "Latitude", "Lat")),
                    longitude=parse_float(first(rec, "Longitude", "Lon", "Lng")),
                    view_count=len(raw_views),
                    embedded_weather=embedded,
                )
            )
    return views


def parse_weather_record(rec: dict[str, Any], station_id: str = "") -> WeatherReading:
    deg, cardinal = parse_wind_direction(first(rec, "WindDirection", "WindDirectionDeg"))
    known = {
        "Id", "ID", "Latitude", "Longitude", "LastUpdated", "WeatherUpdated",
        "CameraSource", "CameraSourceId", "AirTemperature", "PavementTemperature",
        "WindSpeed", "WindDirection", "RelativeHumidity",
    }
    return WeatherReading(
        station_id=str(first(rec, "Id", "ID", default=station_id)),
        latitude=parse_float(rec.get("Latitude")),
        longitude=parse_float(rec.get("Longitude")),
        last_updated=parse_time(first(rec, "LastUpdated", "WeatherUpdated")),
        camera_source=first(rec, "CameraSource"),
        camera_source_id=first(rec, "CameraSourceId"),
        air_temperature=parse_float(rec.get("AirTemperature")),
        pavement_temperature=parse_float(rec.get("PavementTemperature")),
        wind_speed=parse_float(rec.get("WindSpeed")),
        wind_direction_deg=deg,
        wind_direction_cardinal=cardinal,
        relative_humidity=parse_float(rec.get("RelativeHumidity")),
        extra={k: v for k, v in rec.items() if k not in known and not isinstance(v, (list, dict))},
    )


def parse_weather(raw: Any) -> list[WeatherReading]:
    return [parse_weather_record(rec) for rec in _as_list(raw)]


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "yes", "1")


def parse_events(raw: Any) -> list[RoadEvent]:
    events: list[RoadEvent] = []
    for rec in _as_list(raw):
        events.append(
            RoadEvent(
                event_id=str(first(rec, "ID", "Id", "id", default="")),
                roadway=first(rec, "RoadwayName", "Roadway"),
                direction=first(rec, "DirectionOfTravel", "Direction"),
                description=first(rec, "Description"),
                event_type=first(rec, "EventType"),
                event_subtype=first(rec, "EventSubType"),
                severity=first(rec, "Severity"),
                is_full_closure=_bool(rec.get("IsFullClosure", False)),
                lanes_affected=first(rec, "LanesAffected"),
                start=parse_time(rec.get("StartDate")),
                planned_end=parse_time(rec.get("PlannedEndDate")),
                last_updated=parse_time(rec.get("LastUpdated")),
                latitude=parse_float(rec.get("Latitude")),
                longitude=parse_float(rec.get("Longitude")),
                latitude2=parse_float(rec.get("LatitudeSecondary")),
                longitude2=parse_float(rec.get("LongitudeSecondary")),
                path=tuple(decode_polyline(rec.get("EncodedPolyline"))),
                details=first(rec, "Details"),
            )
        )
    return events


def _join(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, list):
        parts = [str(v).strip() for v in value if v not in (None, "")]
        return ", ".join(parts) or None
    return str(value).strip() or None


def parse_road_conditions(raw: Any) -> list[RoadCondition]:
    roads: list[RoadCondition] = []
    for i, rec in enumerate(_as_list(raw)):
        condition = _join(
            first(rec, "Condition", "Conditions", "PrimaryCondition", "RoadCondition", "SurfaceCondition")
        )
        secondary = _join(first(rec, "SecondaryConditions", "SecondaryCondition"))
        if secondary and condition and secondary not in condition:
            condition = f"{condition}, {secondary}"
        roads.append(
            RoadCondition(
                condition_id=str(first(rec, "Id", "ID", default=i)),
                roadway=first(rec, "RoadwayName", "Roadway"),
                location=first(rec, "LocationDescription", "Location", "AreaName", "Description"),
                condition=condition or secondary,
                visibility=_join(first(rec, "Visibility")),
                last_updated=parse_time(first(rec, "LastUpdated", "Updated")),
                path=tuple(decode_polyline(first(rec, "EncodedPolyline", "Polyline"))),
                extra={
                    k: v
                    for k, v in rec.items()
                    if not isinstance(v, (list, dict))
                    and k not in ("EncodedPolyline", "Polyline")
                },
            )
        )
    return roads


def parse_alerts(raw: Any) -> list[Alert]:
    alerts: list[Alert] = []
    for i, rec in enumerate(_as_list(raw)):
        regions = rec.get("Regions") or rec.get("AreaNames") or []
        if isinstance(regions, str):
            regions = [regions]
        alerts.append(
            Alert(
                alert_id=str(first(rec, "Id", "ID", default=i)),
                message=_join(first(rec, "Message", "Title", "Description")),
                notes=_join(first(rec, "Notes", "Details")),
                start=parse_time(first(rec, "StartTime", "StartDate")),
                end=parse_time(first(rec, "EndTime", "EndDate")),
                regions=[str(r) for r in regions],
                high_importance=_bool(rec.get("HighImportance", False)),
            )
        )
    return alerts


# --------------------------------------------------------------------------- #
# Matching
# --------------------------------------------------------------------------- #
def build_labels(views: Iterable[CameraView]) -> dict[str, str]:
    """Return {unique human label: view key}, sorted by label."""
    by_label: dict[str, list[CameraView]] = {}
    for view in views:
        by_label.setdefault(view.base_label(), []).append(view)
    labels: dict[str, str] = {}
    for label, group in by_label.items():
        if len(group) == 1:
            labels[label] = group[0].key
        else:
            for view in group:
                labels[f"{label} #{view.view_id}"] = view.key
    return dict(sorted(labels.items(), key=lambda kv: kv[0].lower()))


def match_weather(
    view: CameraView, stations: list[WeatherReading], max_km: float
) -> tuple[WeatherReading | None, float | None]:
    """Find the weather station for a camera.

    Prefers the station that names this camera as its CameraSourceId, then
    falls back to the nearest station within ``max_km``. If the camera record
    itself carries weather (older API format), that is used last.
    """
    if view.source_id:
        sid = view.source_id.strip().lower()
        exact = [s for s in stations if s.camera_source_id and s.camera_source_id.strip().lower() == sid]
        if len(exact) > 1 and view.source:
            same_src = [s for s in exact if (s.camera_source or "").lower() == view.source.lower()]
            exact = same_src or exact
        if exact:
            station = exact[0]
            dist = (
                haversine_km(view.latitude, view.longitude, station.latitude, station.longitude)
                if view.has_location and station.latitude is not None and station.longitude is not None
                else None
            )
            return station, dist
    best: tuple[WeatherReading | None, float | None] = (None, None)
    if view.has_location:
        for station in stations:
            if station.latitude is None or station.longitude is None:
                continue
            d = haversine_km(view.latitude, view.longitude, station.latitude, station.longitude)
            if d <= max_km and (best[1] is None or d < best[1]):
                best = (station, d)
    if best[0] is None and view.embedded_weather:
        return parse_weather_record(view.embedded_weather, station_id=f"camera-{view.camera_id}"), 0.0
    return best


def nearby_events(
    view: CameraView, events: list[RoadEvent], radius_km: float
) -> list[tuple[float, RoadEvent]]:
    if not view.has_location:
        return []
    found: list[tuple[float, RoadEvent]] = []
    for event in events:
        d = event.distance_km(view.latitude, view.longitude)
        if d is not None and d <= radius_km:
            found.append((d, event))
    found.sort(key=lambda item: item[0])
    return found


def nearest_road_condition(
    view: CameraView, roads: list[RoadCondition], max_km: float
) -> tuple[RoadCondition | None, float | None]:
    if not view.has_location:
        return None, None
    best: tuple[RoadCondition | None, float | None] = (None, None)
    want_road = _norm_road(view.roadway)
    for road in roads:
        d = distance_to_path_km(view.latitude, view.longitude, list(road.path))
        if d is None or d > max_km:
            continue
        # Small bonus for segments on the same highway the camera watches,
        # so an overpass camera doesn't latch onto the crossing road.
        score = d - (0.5 if want_road and _norm_road(road.roadway) == want_road else 0.0)
        if best[1] is None or score < best[1]:
            best = (road, score)
    if best[0] is None:
        return None, None
    true_d = distance_to_path_km(view.latitude, view.longitude, list(best[0].path))
    return best[0], true_d


def _norm_road(name: str | None) -> str | None:
    if not name:
        return None
    digits = re.findall(r"\d+[a-zA-Z]?", name)
    return digits[0].upper() if digits else name.strip().lower()
