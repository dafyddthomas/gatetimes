from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import os
import csv
import asyncio
import requests
from fastapi import FastAPI, HTTPException
from dotenv import load_dotenv

load_dotenv()

WORLDTIDES_KEY = os.getenv("WORLDTIDES_KEY")
OPENWEATHER_KEY = os.getenv("OPENWEATHER_KEY")
LAT = 53.28
LON = -3.83
TZ = ZoneInfo("Europe/London")

app = FastAPI()

# In-memory caches
app.state.tide_cache = []
app.state.weather_cache = {}
app.state.gate_times = {}


def fetch_tide_chunk(start_date: datetime, days: int):
    url = "https://www.worldtides.info/api/v3"
    params = {
        "extremes": "",
        "lat": LAT,
        "lon": LON,
        "date": start_date.strftime("%Y-%m-%d"),
        "days": days,
        "key": WORLDTIDES_KEY,
    }
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    return r.json().get("extremes", [])


def to_local(dt: int) -> datetime:
    return datetime.fromtimestamp(dt, tz=timezone.utc).astimezone(TZ)


def iso_local(dt: int) -> str:
    """Return ISO formatted string for a UTC timestamp in local time."""
    return to_local(dt).isoformat()


def load_tide_data():
    if not WORLDTIDES_KEY:
        print("WORLDTIDES_KEY not set; skipping tide fetch")
        return
    app.state.tide_cache = []
    start = datetime.utcnow()
    end = start + timedelta(days=365)
    current = start
    while current < end:
        chunk_days = min(7, (end - current).days)
        chunk = fetch_tide_chunk(current, chunk_days)
        for e in chunk:
            dt_iso = iso_local(e["dt"])
            e["dt"] = dt_iso
            e["date"] = dt_iso
        app.state.tide_cache.extend(chunk)
        current += timedelta(days=chunk_days)


def load_weather_data():
    if not OPENWEATHER_KEY:
        print("OPENWEATHER_KEY not set; skipping weather fetch")
        return
    url = "https://api.openweathermap.org/data/3.0/onecall"
    params = {
        "lat": LAT,
        "lon": LON,
        "exclude": "minutely,hourly,alerts,current",
        "units": "metric",
        "appid": OPENWEATHER_KEY,
    }
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    app.state.weather_cache = {}
    for day in data.get("daily", []):
        dt_local = to_local(day["dt"])
        date_str = dt_local.strftime("%Y-%m-%d")
        for key in ("dt", "sunrise", "sunset", "moonrise", "moonset"):
            if key in day:
                day[key] = iso_local(day[key])
        app.state.weather_cache[date_str] = day


def load_gate_times():
    path = "gate_times.csv"
    if not os.path.exists(path):
        print("gate_times.csv not found; skipping gate time load")
        return
    app.state.gate_times = {}
    months = [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ]
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            month = months.index(row["month"]) + 1
            day = int(row["day"])
            hour, minute = map(int, row["time"].split(":"))
            dt = datetime(2025, month, day, hour, minute, tzinfo=TZ)
            key = dt.strftime("%Y-%m-%d")
            event = {"datetime": dt.isoformat(), "action": row["action"]}
            app.state.gate_times.setdefault(key, []).append(event)


async def refresh_loop():
    """Background task to refresh caches every 12 hours."""
    while True:
        await asyncio.to_thread(load_tide_data)
        await asyncio.to_thread(load_weather_data)
        await asyncio.to_thread(load_gate_times)
        await asyncio.sleep(60 * 60 * 12)


@app.on_event("startup")
async def startup_event():
    await asyncio.to_thread(load_tide_data)
    await asyncio.to_thread(load_weather_data)
    await asyncio.to_thread(load_gate_times)
    asyncio.create_task(refresh_loop())


@app.get("/tides")
def all_tides():
    return app.state.tide_cache


@app.get("/tides/{date}")
def tides_for_date(date: str):
    try:
        target = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")
    results = [e for e in app.state.tide_cache
               if datetime.fromisoformat(e["dt"]).astimezone(TZ).date() == target]
    if not results:
        raise HTTPException(status_code=404, detail="No tide data for this date")
    return results


@app.get("/weather/{date}")
def weather(date: str):
    try:
        target = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")
    today = datetime.now(TZ).date()
    if target < today or target > today + timedelta(days=5):
        raise HTTPException(status_code=404, detail="Weather available only for the next 5 days")
    if date not in app.state.weather_cache:
        load_weather_data()
    if date not in app.state.weather_cache:
        raise HTTPException(status_code=404, detail="Weather data not found")
    return app.state.weather_cache[date]


@app.get("/gate-times")
def gate_times_all():
    return app.state.gate_times


@app.get("/gate-times/{date}")
def gate_times_date(date: str):
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")
    if date not in app.state.gate_times:
        raise HTTPException(status_code=404, detail="No gate times for this date")
    return app.state.gate_times[date]
