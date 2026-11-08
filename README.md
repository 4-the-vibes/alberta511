# Alberta 511 for Home Assistant

Custom integration that brings the [511 Alberta](https://511.alberta.ca/cctv) highway cameras into Home Assistant, along with the road-weather station, road condition and traffic events near each camera.

## What you get

Each config entry is one device. It can be either:

- **a 511 Viewer** (the default): a `select` dropdown listing every 511 Alberta feed, plus a camera and sensors that follow whichever feed is selected. Switch feeds from a dashboard, or with `select.select_option` in automations ("show me Hwy 1 Canmore when I leave for the ski hill").
- **a fixed camera**: turn off "Add a feed selector dropdown" during setup. The device stays on one feed.

You can add as many of either as you like. All entries with the same key share one poller, so adding cameras doesn't add API calls.

| Entity | What it shows |
|---|---|
| `select.<name>_feed` | Dropdown of every feed (one option per camera view) |
| `camera.<name>` | Still image for the selected feed (refreshes every 120 s by default). It has latitude/longitude attributes, so it shows up on the map card |
| Air temperature, Pavement temperature, Humidity, Wind speed, Wind direction | From the road-weather (RWIS) station paired with the camera |
| Dew point | Worked out from air temperature and humidity |
| Road condition | 511's reported surface condition for the highway segment at the camera, e.g. "Partly Snow Covered, Icy Sections", with visibility as an attribute |
| Nearby events / Nearest event / Nearest event distance | Collisions, construction and closures within the radius you set (15 km by default). The attributes list the 10 closest events |
| Road closure nearby | On if any full closure is inside the radius |
| Pavement at or below freezing | On when pavement temperature is ≤ 0 °C |
| Provincial 511 alerts | Count of active province-wide alerts, with their messages as attributes |
| Camera online, Camera status, Weather station distance, Road weather updated | Diagnostics |

### How a camera is matched to weather and road data

- **Weather station:** the station whose `CameraSourceId` names this camera. If no station does, the nearest station within 5 km is used (you can change the distance). The match is shown in the sensor's attributes.
- **Road condition:** the road-condition segment closest to the camera, within 3 km. Segments on the same highway as the camera win, so a camera on an overpass doesn't pick up the road crossing under it.
- **Events:** distance is measured to the event's whole line, not just its start point, so a long closure counts if any part of it is near the camera.

## Install

1. Copy `custom_components/alberta511` into `/config/custom_components/`. Or push this repo to GitHub and add it to HACS as a custom repository (category: Integration).
2. Restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration → Alberta 511**.
4. Enter your developer key (see below). You can also type a filter like `canmore` or `hwy 93` to shorten the list.
5. Pick a feed from the dropdown and choose whether to add the feed selector.

### Developer key

511 Alberta's API docs say a free developer key is needed: create an account at 511.alberta.ca, sign in, and request a key on the Developers page. Setup also accepts a blank key. If the API rejects requests without one, setup will say so.

The API allows 10 calls per 60 seconds. A full refresh uses 4 calls, plus 1 more every 6 h to re-download the camera list. The client also limits itself to stay under the cap.

## Options

Open **Configure** on the entry to change:

- image refresh (30–3600 s)
- data refresh (2–60 min)
- event radius
- weather-station fallback distance
- the units 511 reports in

The docs list temperature as °F, but their sample values look like °C, so the default is °C. If temperatures look wrong, switch this option. Home Assistant then converts to your display units.

## Dashboard

See `examples/dashboard.yaml` for a stacked card with the dropdown, the image, the weather readings and the event list.

## Notes and limits

- 511 Alberta publishes still images, not video streams. The camera entity refreshes the still on a timer.
- The road-condition and alert field names follow the 511/CARS platform docs. The parser accepts several field-name variants. If 511 doesn't publish a collection, those sensors stay `unknown`, and a note is written to the log once.
- Data © Government of Alberta / 511 Alberta.

## Development

`models.py` doesn't import Home Assistant, so you can test it without HA installed:

```
pytest tests
```
