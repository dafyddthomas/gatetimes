# gatetimes

Conwy Gate Times utilities.

## Gate time extraction

`extract_gate_times.py` parses `GateTimes2025.pdf` and writes `gate_times.csv`
using OCR.  The CSV is used by the API below.

```
pip install -r requirements.txt
python extract_gate_times.py
```

## MCP API

`mcp_api.py` implements a small FastAPI service providing:

- `/tides` and `/tides/{YYYY-MM-DD}` - 12&nbsp;months of cached tide data from
  [WorldTides](https://www.worldtides.info/apidocs) converted to local time.
- `/weather/{YYYY-MM-DD}` - weather forecast for a day if it is within the next
  five days using [OpenWeather](https://openweathermap.org/api/one-call-3), also
  returned in local time.
- `/gate-times` and `/gate-times/{YYYY-MM-DD}` - gate raise and lower times
  extracted from `GateTimes2025.pdf`.

Copy `.env.example` to `.env` and fill in your `WORLDTIDES_KEY` and
`OPENWEATHER_KEY`, then run:

```
pip install -r requirements.txt
uvicorn mcp_api:app --reload
```
