import os
import json
import aiohttp
from config import API_URL

async def fetch_f1_data(endpoint: str, params: dict = None) -> dict:
    cache_key = endpoint.replace('/', '_')
    if params:
        cache_key += "_" + "_".join([f"{k}_{v}" for k, v in params.items()])
    cache_file = f"cache_{cache_key}.json"

    try:
        timeout = aiohttp.ClientTimeout(total=15)
        headers = {"User-Agent": "F1TelegramBot/1.0"}
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(f"{API_URL}/{endpoint}.json", params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    with open(cache_file, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False)
                    return data
    except Exception as e:
        print(f"API Error ({endpoint}): {e}")

    try:
        if os.path.exists(cache_file):
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"Cache Read Error ({endpoint}): {e}")

    return None

def get_weather_emoji(code):
    if code in [0, 1]: return "☀️"
    if code in [2, 3]: return "☁️"
    if code in [45, 48]: return "🌫"
    if code in [51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82]: return "🌧"
    if code in [95, 96, 99]: return "⛈"
    return "🌡"

async def fetch_weather(lat: float, lon: float, target_date_str: str = None) -> dict:
    url = "https://api.open-meteo.com/v1/forecast"
    try:
        if not target_date_str:
            params = {"latitude": lat, "longitude": lon, "current_weather": "true"}
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("current_weather")
        else:
            params = {
                "latitude": lat, "longitude": lon,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode",
                "timezone": "auto",
                "start_date": target_date_str,
                "end_date": target_date_str
            }
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if "daily" in data and len(data["daily"]["time"]) > 0:
                            return {
                                "t_max": data["daily"]["temperature_2m_max"][0],
                                "t_min": data["daily"]["temperature_2m_min"][0],
                                "rain": data["daily"]["precipitation_sum"][0],
                                "code": data["daily"]["weathercode"][0]
                            }
    except Exception as e:
        print(f"Weather fetch error: {e}")
    return None