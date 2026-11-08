"""Unit tests for the HA-independent parsing/geo logic."""

import importlib.util
import pathlib
import sys

_PATH = pathlib.Path(__file__).parents[1] / "custom_components" / "alberta511" / "models.py"
_spec = importlib.util.spec_from_file_location("a511_models", _PATH)
m = importlib.util.module_from_spec(_spec)
sys.modules["a511_models"] = m
_spec.loader.exec_module(m)

# Samples shaped like the 511 Alberta developer docs.
CAMERAS = [
    {
        "Id": 11, "Source": "Banff", "SourceId": "banff11cam", "Roadway": "Rimrock",
        "Direction": "Unknown", "Latitude": 51.152068, "Longitude": -115.560434,
        "Location": "Rimrock-North", "SortOrder": 0,
        "Views": [{"Id": 11, "Url": "https://511.alberta.ca/map/Cctv/11", "Status": "Enabled", "Description": "Road"}],
    },
    {
        "Id": 20, "Source": "WOOD", "SourceId": "001-02", "Roadway": "Hwy 1",
        "Direction": "Eastbound", "Latitude": 51.0400, "Longitude": -115.2450,
        "Location": "Hwy 1: Dead Man's Flats",
        "Views": [
            {"Id": 201, "Url": "https://511.alberta.ca/map/Cctv/201", "Status": "Enabled", "Description": "Road"},
            {"Id": 202, "Url": "https://511.alberta.ca/map/Cctv/202", "Status": "Disabled", "Description": "Surface"},
        ],
    },
]
WEATHER = [
    {"Id": 11423, "Latitude": 51.0405, "Longitude": -115.246, "LastUpdated": 1748611380,
     "CameraSource": "WOOD", "CameraSourceId": "001-02", "AirTemperature": "12.1",
     "PavementTemperature": "14.71", "WindSpeed": "8.3", "WindDirection": "224", "RelativeHumidity": "56"},
    {"Id": 99, "Latitude": 51.153, "Longitude": -115.561, "LastUpdated": 1748611380,
     "AirTemperature": "-3", "PavementTemperature": "", "WindSpeed": "N/A", "WindDirection": "NW", "RelativeHumidity": "64%"},
]


def test_parse_cameras_views_and_labels():
    views = m.parse_cameras(CAMERAS)
    assert [v.key for v in views] == ["11:11", "20:201", "20:202"]
    assert views[2].enabled is False
    labels = m.build_labels(views)
    assert "Rimrock-North" in labels  # roadway already in location
    assert "Hwy 1: Dead Man's Flats (Road, Eastbound)" in labels
    assert labels["Hwy 1: Dead Man's Flats (Surface, Eastbound)"] == "20:202"


def test_weather_exact_match_and_fallback():
    views = {v.key: v for v in m.parse_cameras(CAMERAS)}
    stations = m.parse_weather(WEATHER)
    st, d = m.match_weather(views["20:201"], stations, 5)
    assert st.station_id == "11423" and d < 0.2
    assert st.wind_direction_cardinal == "SW" and st.air_temperature == 12.1
    st2, d2 = m.match_weather(views["11:11"], stations, 5)
    assert st2.station_id == "99" and d2 < 1
    assert st2.pavement_temperature is None and st2.wind_speed is None
    assert st2.relative_humidity == 64 and st2.wind_direction_deg == 315
    none, _ = m.match_weather(views["11:11"], stations[:1], 5)
    assert none is None


def test_legacy_embedded_weather():
    legacy = [{"Id": "ESS_AB_002", "RoadwayName": "Hwy 2", "Name": "Hwy2: West of RR 103",
               "Latitude": 55.3, "Longitude": -115.4, "Url": "https://x/img.jpg",
               "AirTemperature": "-5", "WindDirection": "NW", "RelativeHumidity": "64%",
               "WeatherUpdated": "Mar 24 2020, 1:23 PM"}]
    v = m.parse_cameras(legacy)[0]
    st, _ = m.match_weather(v, [], 5)
    assert st.air_temperature == -5 and st.last_updated.year == 2020


def test_polyline_and_events():
    # Classic Google example: (38.5,-120.2),(40.7,-120.95),(43.252,-126.453)
    assert m.decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@") == [
        (38.5, -120.2), (40.7, -120.95), (43.252, -126.453)
    ]
    cam = m.parse_cameras(CAMERAS)[1]
    events = m.parse_events([
        {"ID": 1, "Description": "Collision", "EventType": "accidentsAndIncidents",
         "IsFullClosure": True, "Latitude": 51.05, "Longitude": -115.25, "StartDate": 1697738820},
        {"ID": 2, "Description": "Far away", "Latitude": 53.5, "Longitude": -113.5},
    ])
    near = m.nearby_events(cam, events, 15)
    assert len(near) == 1 and near[0][1].is_full_closure
    assert near[0][1].as_attribute(near[0][0])["distance_km"] < 2


def test_segment_distance_beats_vertex_distance():
    # A 20 km E-W road whose vertices are both ~10 km from the point,
    # but whose segment passes ~1.1 km away.
    path = [(51.01, -115.4), (51.01, -115.1)]
    d = m.distance_to_path_km(51.0, -115.25, path)
    assert 1.0 < d < 1.3


def test_road_condition_prefers_same_highway():
    cam = m.parse_cameras(CAMERAS)[1]  # Hwy 1
    roads = m.parse_road_conditions([
        {"Id": "a", "RoadwayName": "Hwy 1A", "Condition": ["Bare Dry"],
         "EncodedPolyline": None, "LocationDescription": "x"},
        {"Id": "b", "RoadwayName": "Hwy 1", "Condition": ["Partly Snow Covered", "Icy Sections"],
         "Visibility": "Good", "LocationDescription": "Canmore to Banff",
         "EncodedPolyline": None},
    ])
    # Give both a path through the camera point (encode not needed: inject).
    roads = [m.RoadCondition(**{**r.__dict__, "path": ((51.03, -115.3), (51.05, -115.2))}) for r in roads]
    road, d = m.nearest_road_condition(cam, roads, 3)
    assert road.condition_id == "b" and road.condition == "Partly Snow Covered, Icy Sections"


def test_value_helpers():
    assert m.parse_float("42.8 °F") == 42.8
    assert m.parse_float("") is None
    assert m.dew_point_c(12.1, 56) == 3.6
    assert m.parse_time(1748611380000).year == 2025
    assert m.degrees_to_cardinal(359) == "N"
