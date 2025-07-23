from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import os
import asyncio
import secrets
import requests
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Depends, Security
from fastapi.security import HTTPBasic, HTTPBasicCredentials, APIKeyHeader
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

WORLDTIDES_KEY = os.getenv("WORLDTIDES_KEY")
OPENWEATHER_KEY = os.getenv("OPENWEATHER_KEY")
BASIC_AUTH_USER = os.getenv("BASIC_AUTH_USER")
BASIC_AUTH_PASS = os.getenv("BASIC_AUTH_PASS")
MCP_API_KEY = os.getenv("MCP_API_KEY")
GATE_OPEN_HEIGHT = float(os.getenv("GATE_OPEN_HEIGHT", "4"))
LAT = 53.28
LON = -3.83
TZ = ZoneInfo("Europe/London")

app = FastAPI()

# In-memory caches
app.state.tide_cache = []
app.state.weather_cache = {}
app.state.gate_times = {}
app.state.tide_heights_cache = []
app.state.tide_heights_last_load = datetime.min
app.state.sun_cache = {}
app.state.moon_cache = {}
app.state.marine_cache = {}

security_basic = HTTPBasic(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-KEY", auto_error=False)


def verify_auth(
    credentials: Optional[HTTPBasicCredentials] = Depends(security_basic),
    api_key: Optional[str] = Security(api_key_header),
):
    if MCP_API_KEY and api_key and secrets.compare_digest(api_key, MCP_API_KEY):
        return
    if (
        credentials
        and BASIC_AUTH_USER
        and BASIC_AUTH_PASS
        and secrets.compare_digest(credentials.username, BASIC_AUTH_USER)
        and secrets.compare_digest(credentials.password, BASIC_AUTH_PASS)
    ):
        return
    raise HTTPException(
        status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Basic"}
    )


def beaufort(speed: float) -> int:
    """Convert meters/second wind speed to Beaufort scale."""
    thresholds = [
        0.5,
        1.5,
        3.3,
        5.5,
        7.9,
        10.7,
        13.8,
        17.1,
        20.7,
        24.4,
        28.4,
        32.6,
    ]
    for i, t in enumerate(thresholds):
        if speed < t:
            return i
    return 12


class Temp(BaseModel):
    day: float
    min: float
    max: float
    night: float
    eve: float
    morn: float


class FeelsLike(BaseModel):
    day: float
    night: float
    eve: float
    morn: float


class WeatherDesc(BaseModel):
    id: int
    main: str
    description: str
    icon: str


class WeatherDay(BaseModel):
    dt: str
    sunrise: Optional[str] = None
    sunset: Optional[str] = None
    moonrise: Optional[str] = None
    moonset: Optional[str] = None
    moon_phase: Optional[float] = None
    summary: Optional[str] = None
    temp: Temp
    feels_like: FeelsLike
    pressure: int
    humidity: int
    dew_point: float
    wind_speed: float
    wind_speed_beaufort: int
    wind_gust: Optional[float] = None
    wind_gust_beaufort: Optional[int] = None
    wind_deg: int
    weather: List[WeatherDesc]
    clouds: int
    pop: float
    uvi: float


class TideEvent(BaseModel):
    dt: str
    date: str
    height: float
    type: str


class TideHeight(BaseModel):
    dt: str
    date: str
    height: float


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


def fetch_sunrise_sunset(date: str, lat: float, lng: float):
    url = "https://api.sunrise-sunset.org/json"
    params = {"lat": lat, "lng": lng, "date": date, "formatted": 0}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    data["tzid"] = TZ.key
    return data


def fetch_moon_phase(ts: int):
    url = "https://api.farmsense.net/v1/moonphases/"
    params = {"d": ts}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def fetch_marine_forecast(
    lat: float,
    lon: float,
    hourly: str,
    timeformat: str = "unixtime",
    forecast_hours: int = 48,
):
    url = "https://api.open-meteo.com/v1/marine"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": hourly,
        "timeformat": timeformat,
        "forecast_hours": forecast_hours,
    }
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


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
            dt_local = to_local(e["dt"])
            e["dt"] = dt_local.isoformat()
            e["date"] = dt_local.strftime("%Y-%m-%d")

        app.state.tide_cache.extend(chunk)
        current += timedelta(days=chunk_days)


def load_tide_heights():
    """Load half-hour tide heights for the next six months."""
    if not WORLDTIDES_KEY:
        print("WORLDTIDES_KEY not set; skipping tide heights fetch")
        return

    start = datetime.utcnow()
    # Roughly six months of data (about 180 days)
    heights = fetch_tide_heights(start, 180)
    for h in heights:
        dt_local = to_local(h["dt"])
        h["dt"] = dt_local.isoformat()
        h["date"] = dt_local.strftime("%Y-%m-%d")

    app.state.tide_heights_cache = heights
    app.state.tide_heights_last_load = datetime.utcnow()


def fetch_tide_heights(start_date: datetime, days: int):
    url = "https://www.worldtides.info/api/v3"
    params = {
        "heights": "",
        "lat": LAT,
        "lon": LON,
        "date": start_date.strftime("%Y-%m-%d"),
        "days": days,
        "datum": "CD",
        "key": WORLDTIDES_KEY,
    }
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    return r.json().get("heights", [])


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

        day["wind_speed_beaufort"] = beaufort(day.get("wind_speed", 0))
        if "wind_gust" in day:
            day["wind_gust_beaufort"] = beaufort(day["wind_gust"])

        app.state.weather_cache[date_str] = day


def calculate_gate_times():
    """Calculate approximate gate raise/lower times from tide heights.

    The terms "raise" and "lower" in the returned events correspond to the
    physical movement of the gate in Conwy. The gate is **lowered** when the
    tide rises above ``GATE_OPEN_HEIGHT`` and **raised** again once it falls
    back below this level.
    """
    if not app.state.tide_heights_cache:
        load_tide_heights()

    threshold = GATE_OPEN_HEIGHT
    events: dict[str, list] = {}

    prev_dt: Optional[datetime] = None
    prev_height: Optional[float] = None

    for entry in app.state.tide_heights_cache:
        dt = datetime.fromisoformat(entry["dt"]).astimezone(TZ)
        height = entry["height"]
        if prev_dt is not None and prev_height is not None:
            if prev_height < threshold <= height:
                ratio = (threshold - prev_height) / (height - prev_height)
                crossing = prev_dt + (dt - prev_dt) * ratio
                date_key = crossing.strftime("%Y-%m-%d")
                event = {
                    "datetime": crossing.isoformat(),
                    "action": "lower",
                    "height": threshold,
                }
                events.setdefault(date_key, []).append(event)
            elif prev_height > threshold >= height:
                ratio = (prev_height - threshold) / (prev_height - height)
                crossing = prev_dt + (dt - prev_dt) * ratio
                date_key = crossing.strftime("%Y-%m-%d")
                event = {
                    "datetime": crossing.isoformat(),
                    "action": "raise",
                    "height": threshold,
                }
                events.setdefault(date_key, []).append(event)

        prev_dt = dt
        prev_height = height

    app.state.gate_times = events


async def refresh_loop():
    """Background task to refresh caches every 12 hours."""
    while True:
        await asyncio.to_thread(load_tide_data)
        await asyncio.to_thread(load_weather_data)
        if (
            not app.state.tide_heights_cache
            or datetime.utcnow() - app.state.tide_heights_last_load > timedelta(days=7)
        ):
            await asyncio.to_thread(load_tide_heights)
        await asyncio.to_thread(calculate_gate_times)
        await asyncio.sleep(60 * 60 * 12)


@app.on_event("startup")
async def startup_event():
    await asyncio.to_thread(load_tide_data)
    await asyncio.to_thread(load_weather_data)
    await asyncio.to_thread(load_tide_heights)
    await asyncio.to_thread(calculate_gate_times)
    asyncio.create_task(refresh_loop())


@app.get("/tides/{date}", response_model=List[TideEvent])
def tides_for_date(date: str, auth: None = Depends(verify_auth)):
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")

    results = [e for e in app.state.tide_cache if e["date"] == date]

    if not results:
        raise HTTPException(status_code=404, detail="No tide data for this date")
    return results


@app.get("/tide-heights", response_model=List[TideHeight])
def tide_heights(offset: int = 0, limit: int = 100, auth: None = Depends(verify_auth)):
    if (
        not app.state.tide_heights_cache
        or datetime.utcnow() - app.state.tide_heights_last_load > timedelta(days=7)
    ):
        load_tide_heights()
    return app.state.tide_heights_cache[offset : offset + limit]


@app.get("/weather/{date}", response_model=WeatherDay)
def weather(date: str, auth: None = Depends(verify_auth)):
    try:
        target = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")
    today = datetime.now(TZ).date()
    if target < today or target > today + timedelta(days=5):
        raise HTTPException(
            status_code=404, detail="Weather available only for the next 5 days"
        )
    if date not in app.state.weather_cache:
        load_weather_data()
    if date not in app.state.weather_cache:
        raise HTTPException(status_code=404, detail="Weather data not found")
    return app.state.weather_cache[date]


@app.get("/sunrise-sunset")
def sunrise_sunset(
    date: str,
    lat: float = LAT,
    lng: float = LON,
    auth: None = Depends(verify_auth),
):
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")
    key = f"{lat}:{lng}:{date}"
    if key not in app.state.sun_cache:
        app.state.sun_cache[key] = fetch_sunrise_sunset(date, lat, lng)
    return app.state.sun_cache[key]


@app.get("/moon-phase")
def moon_phase(date: str, auth: None = Depends(verify_auth)):
    try:
        dt = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")
    ts = int(dt.replace(tzinfo=timezone.utc).timestamp())
    if ts not in app.state.moon_cache:
        data = fetch_moon_phase(ts)
        if isinstance(data, list) and data:
            data = data[0]
        app.state.moon_cache[ts] = data
    return app.state.moon_cache[ts]


@app.get("/marine")
def marine(
    forecast_hours: int = 48,
    timeformat: str = "unixtime",
    hourly: str = "sea_level_height_msl,ocean_current_velocity,ocean_current_direction",
    lat: float = LAT,
    lon: float = LON,
    auth: None = Depends(verify_auth),
):
    key = f"{lat}:{lon}:{hourly}:{timeformat}:{forecast_hours}"
    if key not in app.state.marine_cache:
        app.state.marine_cache[key] = fetch_marine_forecast(
            lat, lon, hourly, timeformat, forecast_hours
        )
    return app.state.marine_cache[key]


@app.get("/gate-times")
def gate_times_all(auth: None = Depends(verify_auth)):
    return app.state.gate_times


@app.get("/gate-times/{date}")
def gate_times_date(date: str, auth: None = Depends(verify_auth)):
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")
    if date not in app.state.gate_times:
        raise HTTPException(status_code=404, detail="No gate times for this date")
    return app.state.gate_times[date]
