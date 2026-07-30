"""Weather advisor — FREE Open-Meteo, no API key required.

Configuration (via environment):
    WEATHER_CITY        City name to geocode (optional WEATHER_COUNTRY hint).
    WEATHER_COUNTRY     Optional country name/code to disambiguate the city.
    WEATHER_LATITUDE    Explicit latitude (overrides city geocoding).
    WEATHER_LONGITUDE   Explicit longitude (overrides city geocoding).

With no city and no coordinates the advisor is ``skipped``. Otherwise it
geocodes the city (if needed), fetches the daily forecast and produces a
Turkish meteorologist-style summary.
"""

from __future__ import annotations

import os
from typing import Optional, Tuple

from . import Advisor, Briefing
from ..integrations._common import http_get

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather interpretation codes -> Turkish human-readable text.
WEATHER_CODES = {
    0: "açık ve güneşli",
    1: "az bulutlu",
    2: "parçalı bulutlu",
    3: "çok bulutlu / kapalı",
    45: "sisli",
    48: "kırağılı sis",
    51: "hafif çiseleme",
    53: "orta şiddette çiseleme",
    55: "yoğun çiseleme",
    56: "hafif dondurucu çiseleme",
    57: "yoğun dondurucu çiseleme",
    61: "hafif yağmurlu",
    63: "orta şiddette yağmurlu",
    65: "kuvvetli yağmurlu",
    66: "hafif dondurucu yağmur",
    67: "kuvvetli dondurucu yağmur",
    71: "hafif kar yağışlı",
    73: "orta şiddette kar yağışlı",
    75: "yoğun kar yağışlı",
    77: "kar taneli",
    80: "yer yer sağanak yağışlı",
    81: "sağanak yağışlı",
    82: "şiddetli sağanak yağışlı",
    85: "hafif kar sağanağı",
    86: "yoğun kar sağanağı",
    95: "gök gürültülü fırtına",
    96: "dolu ile gök gürültülü fırtına",
    99: "yoğun dolu ile gök gürültülü fırtına",
}


class WeatherAdvisor(Advisor):
    key = "weather"
    title = "Hava Durumu Meteoroloğu"

    def _generate(self) -> Briefing:
        lat_env = os.getenv("WEATHER_LATITUDE")
        lon_env = os.getenv("WEATHER_LONGITUDE")
        city = os.getenv("WEATHER_CITY")

        if lat_env and lon_env:
            try:
                lat, lon = float(lat_env), float(lon_env)
            except ValueError:
                return self.failed(
                    "WEATHER_LATITUDE/WEATHER_LONGITUDE sayıya çevrilemedi"
                )
            place_name = city or f"{lat:.2f}, {lon:.2f}"
        elif city:
            located = self._geocode(city)
            if located is None:
                return self.failed(f"'{city}' için konum bulunamadı")
            lat, lon, place_name = located
        else:
            return self.skipped(
                "missing env var(s): WEATHER_CITY or WEATHER_LATITUDE/WEATHER_LONGITUDE"
            )

        return self._forecast(lat, lon, place_name)

    # -- helpers ---------------------------------------------------------
    def _geocode(self, city: str) -> Optional[Tuple[float, float, str]]:
        params = {"name": city, "count": "1", "language": "tr", "format": "json"}
        country = os.getenv("WEATHER_COUNTRY")
        if country:
            params["country"] = country
        query = "&".join(f"{k}={v}" for k, v in params.items())
        resp = http_get(f"{GEOCODE_URL}?{query}")
        resp.raise_for_status()
        results = resp.json().get("results") or []
        if not results:
            return None
        top = results[0]
        name = top.get("name", city)
        admin = top.get("admin1")
        country_name = top.get("country")
        label = ", ".join(p for p in (name, admin, country_name) if p)
        return float(top["latitude"]), float(top["longitude"]), label

    def _forecast(self, lat: float, lon: float, place_name: str) -> Briefing:
        query = (
            f"latitude={lat}&longitude={lon}"
            "&current=temperature_2m,weather_code,wind_speed_10m"
            "&daily=weather_code,temperature_2m_max,temperature_2m_min,"
            "precipitation_sum,precipitation_probability_max,wind_speed_10m_max"
            "&timezone=auto&forecast_days=1"
        )
        resp = http_get(f"{FORECAST_URL}?{query}")
        resp.raise_for_status()
        data = resp.json()
        text = self._summarize(place_name, data)
        return self.ok(text)

    def _summarize(self, place_name: str, data: dict) -> str:
        current = data.get("current", {})
        daily = data.get("daily", {})

        def first(seq, default=None):
            return seq[0] if isinstance(seq, list) and seq else default

        code = first(daily.get("weather_code"), current.get("weather_code"))
        desc = WEATHER_CODES.get(code, "değişken")
        t_max = first(daily.get("temperature_2m_max"))
        t_min = first(daily.get("temperature_2m_min"))
        precip = first(daily.get("precipitation_sum"))
        precip_prob = first(daily.get("precipitation_probability_max"))
        wind_max = first(daily.get("wind_speed_10m_max"))
        cur_temp = current.get("temperature_2m")

        lines = [f"{place_name} için bugünkü hava durumu: gökyüzü {desc}."]

        if cur_temp is not None:
            lines.append(f"Şu an hava {cur_temp:.0f}°C civarında.")

        if t_max is not None and t_min is not None:
            lines.append(
                f"Gün içinde sıcaklık {t_min:.0f}°C ile {t_max:.0f}°C arasında seyredecek."
            )

        if precip is not None and precip > 0:
            prob_txt = f" (yağış olasılığı %{precip_prob:.0f})" if precip_prob is not None else ""
            lines.append(f"Beklenen yağış miktarı {precip:.1f} mm{prob_txt}.")
        elif precip_prob is not None and precip_prob > 0:
            lines.append(f"Yağış olasılığı %{precip_prob:.0f}.")

        if wind_max is not None:
            lines.append(f"En yüksek rüzgar hızı yaklaşık {wind_max:.0f} km/s.")

        # Notable events — a meteorologist's closing advice.
        notes = []
        if code in (71, 73, 75, 77, 85, 86):
            notes.append("kar yağışına karşı hazırlıklı olun")
        elif code in (61, 63, 65, 80, 81, 82, 95, 96, 99) or (precip is not None and precip >= 5):
            notes.append("yanınıza şemsiye almayı unutmayın")
        if wind_max is not None and wind_max >= 40:
            notes.append("kuvvetli rüzgara dikkat edin")
        if t_max is not None and t_max >= 32:
            notes.append("sıcak havada bol su için ve güneşten korunun")
        if t_min is not None and t_min <= 0:
            notes.append("don riskine karşı önlem alın")

        if notes:
            lines.append("Uyarı: " + ", ".join(notes) + ".")
        else:
            lines.append("Bugün için dikkat gerektiren olağandışı bir hava olayı görünmüyor.")

        return " ".join(lines)
