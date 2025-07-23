# gatetimes

Conwy Gate Times utilities.

## Gate time extraction

`extract_gate_times.py` parses `GateTimes2025.pdf` and writes `gate_times.csv`
using OCR.  This script is retained for reference but the API now predicts gate
times from tide height data.

```
pip install -r requirements.txt
python extract_gate_times.py
```

## MCP API

- `mcp_api.py` implements a small FastAPI service providing:

- `/tides/{YYYY-MM-DD}` - 12\u00a0months of cached tide data from
  [WorldTides](https://www.worldtides.info/apidocs) converted to local time.
- `/tide-heights` - half hour tide heights for the next 7 days refreshed once a
  week. Heights are relative to chart datum (CD).
- `/weather/{YYYY-MM-DD}` - weather forecast for a day if it is within the next
  five days using [OpenWeather](https://openweathermap.org/api/one-call-3), also
  returned in local time.
- `/sunrise-sunset?lat=LAT&lng=LON&date=YYYY-MM-DD` - sunrise and sunset times
  for a specific date from [sunrise-sunset.org](https://sunrise-sunset.org/api).
- `/moon-phase?date=YYYY-MM-DD` - moon phase data from
  [Farmsense](https://api.farmsense.net/v1/moonphases/).
- `/marine` - sea level and ocean current forecast from
  [Open-Meteo](https://open-meteo.com/).
- `/gate-times` and `/gate-times/{YYYY-MM-DD}` - predicted gate raise and lower
  times calculated from tide height forecasts. Each event includes the date and
  time, the action to take and the tide height. The gate is **lowered** as the
  tide rises to `GATE_OPEN_HEIGHT` metres (default 4&nbsp;m) and **raised** once
  it falls back below this level.


Tide, weather and gate time data are cached in memory and refreshed every
12&nbsp;hours. All timestamps returned by the API are expressed in local ISO
format for Conwy, North Wales.


Copy `.env.example` to `.env` and fill in your `WORLDTIDES_KEY`,
`OPENWEATHER_KEY`, and authentication values `BASIC_AUTH_USER`,
`BASIC_AUTH_PASS` or `MCP_API_KEY`. You can also adjust
`GATE_OPEN_HEIGHT` to change the tide height used for gate predictions.

All API endpoints require authentication using either HTTP Basic credentials or
an `X-API-KEY` header containing the value of `MCP_API_KEY`.

## Using a virtual environment

On Ubuntu you can isolate the dependencies with `venv`:

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

With the environment active you can run the API with:

```
uvicorn mcp_api:app --reload
```

## Running as a service

Assuming the repository lives at `/home/dafydd/gatetimes`, create a
`systemd` service file such as `/etc/systemd/system/gatetimes.service`:

```
[Unit]
Description=Gate Times API
After=network.target

[Service]
User=dafydd
WorkingDirectory=/home/dafydd/gatetimes
EnvironmentFile=/home/dafydd/gatetimes/.env
ExecStart=/home/dafydd/gatetimes/.venv/bin/uvicorn mcp_api:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start it with:

```
sudo systemctl daemon-reload
sudo systemctl enable gatetimes
sudo systemctl start gatetimes
```

## Keeping the code up to date

To automatically pull changes from GitHub you can use a simple cron job that
runs `git pull` periodically.  Edit the crontab with `crontab -e` and add, for
example:

```
*/30 * * * * cd /home/dafydd/gatetimes && git pull --ff-only
```

This checks for updates every 30 minutes and reloads the service if the code has
changed:

```
*/30 * * * * cd /home/dafydd/gatetimes && git pull --ff-only && sudo systemctl restart gatetimes
```
