#!/usr/bin/env python3
"""
Simple terminal Information Assistantṇ
Features:
 - Weather (OpenWeatherMap)
 - News headlines (NewsAPI)
 - Quick Wikipedia summaries
 - Local search history (SQLite)
 - Uses .env for API keys
"""

import os
import sys
import logging
import requests
import sqlite3
import time
from datetime import datetime
from typing import Optional

try:
    import wikipedia
except Exception:
    print("Missing dependency 'wikipedia'. Run: pip install wikipedia")
    sys.exit(1)

# ---------------------------
# Configuration & Logging
# ---------------------------
from dotenv import load_dotenv
load_dotenv()  # loads .env from current dir

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "c9f38a5706fef5439c90c6656ef26be1")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "83f55727dd5645d0874013ee371467b0")

LOGFILE = "assistant.log"
logging.basicConfig(
    filename=LOGFILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
console = logging.StreamHandler()
console.setLevel(logging.WARNING)
logging.getLogger("").addHandler(console)


# ---------------------------
# Simple local history DB
# ---------------------------
DB_PATH = "assistant_history.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            command TEXT,
            query TEXT,
            result_summary TEXT
        )
        """
    )
    conn.commit()
    conn.close()

def save_history(command: str, query: str, result_summary: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO history (timestamp, command, query, result_summary) VALUES (?, ?, ?, ?)",
        (datetime.utcnow().isoformat(), command, query[:200], result_summary[:400]),
    )
    conn.commit()
    conn.close()


# ---------------------------
# Utilities
# ---------------------------
def safe_get(d, *keys, default=None):
    for k in keys:
        if isinstance(d, dict) and k in d:
            d = d[k]
        else:
            return default
    return d

# ---------------------------
# Weather
# ---------------------------
def get_weather(city: str) -> str:
    city = city.strip()
    if not OPENWEATHER_API_KEY:
        msg = "OpenWeather API key not set. Put OPENWEATHER_API_KEY in .env"
        logging.error(msg)
        return msg
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {"q": city, "appid": OPENWEATHER_API_KEY, "units": "metric"}
    try:
        r = requests.get(url, params=params, timeout=8)
        r.raise_for_status()
        data = r.json()
        temp = safe_get(data, "main", "temp")
        desc = safe_get(data, "weather", 0, "description")
        feels = safe_get(data, "main", "feels_like")
        humidity = safe_get(data, "main", "humidity")
        name = safe_get(data, "name") or city
        res = f"{name}: {temp}°C (feels {feels}°C), {desc}. Humidity: {humidity}%."
        logging.info(f"weather {city} -> {res}")
        save_history("weather", city, res)
        return res
    except requests.HTTPError as e:
        logging.exception("Weather API error")
        return f"Weather API error: {e} - check city name or API key."
    except Exception as e:
        logging.exception("Unexpected error in get_weather")
        return "Could not fetch weather at this time."

# ---------------------------
# News (top headlines)
# ---------------------------
def get_news(country: str = "us", page_size: int = 5) -> str:
    if not NEWSAPI_KEY:
        msg = "NewsAPI key not set. Put NEWSAPI_KEY in .env"
        logging.error(msg)
        return msg
    url = "https://newsapi.org/v2/top-headlines"
    params = {"apiKey": NEWSAPI_KEY, "country": country, "pageSize": page_size}
    try:
        r = requests.get(url, params=params, timeout=8)
        r.raise_for_status()
        data = r.json()
        if data.get("status") != "ok":
            logging.error("News API returned non-ok status")
            return "News API error: " + str(data)
        articles = data.get("articles", [])
        if not articles:
            return "No headlines found."
        lines = []
        for i, a in enumerate(articles, start=1):
            title = a.get("title") or "No title"
            source = safe_get(a, "source", "name") or "unknown"
            lines.append(f"{i}. {title} ({source})")
        res = "\n".join(lines)
        logging.info("news fetched")
        save_history("news", country, res)
        return res
    except requests.HTTPError as e:
        logging.exception("News API error")
        return f"News API error: {e}"
    except Exception:
        logging.exception("Unexpected error in get_news")
        return "Could not fetch news at this time."

# ---------------------------
# Wikipedia quick summary
# ---------------------------
def wiki_summary(query: str, sentences: int = 2) -> str:
    try:
        summary = wikipedia.summary(query, sentences=sentences, auto_suggest=True, redirect=True)
        save_history("wikipedia", query, summary)
        logging.info(f"wikipedia: {query}")
        return summary
    except wikipedia.exceptions.DisambiguationError as e:
        options = e.options[:6]
        logging.warning("wikipedia disambiguation")
        return f"Disambiguation — possible matches: {', '.join(options)}"
    except wikipedia.exceptions.PageError:
        logging.warning("wikipedia page not found")
        return "No Wikipedia page found for that query."
    except Exception:
        logging.exception("Unexpected error in wiki_summary")
        return "Wikipedia lookup failed."

# ---------------------------
# History viewer
# ---------------------------
def show_history(limit: int = 10):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT timestamp, command, query, result_summary FROM history ORDER BY id DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return "No history yet."
    res_lines = []
    for ts, cmd, q, r in rows:
        t = ts.split("T")[0] + " " + ts.split("T")[1][:8] if "T" in ts else ts
        res_lines.append(f"[{t}] {cmd} '{q}' -> {r[:120]}{'...' if len(r) > 120 else ''}")
    return "\n".join(res_lines)

# ---------------------------
# Command parser & CLI
# ---------------------------
def help_text() -> str:
    return (
        "Commands:\n"
        "  weather <city>         - show current weather for city\n"
        "  news [country_code]    - top headlines (default 'us')\n"
        "  wiki <topic>           - short Wikipedia summary\n"
        "  history [n]            - show last n queries (default 10)\n"
        "  keys                   - show which API keys are configured\n"
        "  help                   - show this help\n"
        "  exit / quit            - exit the assistant\n"
    )

def show_keys():
    return (
        f"OPENWEATHER_API_KEY set: {'yes' if OPENWEATHER_API_KEY else 'no'}\n"
        f"NEWSAPI_KEY set: {'yes' if NEWSAPI_KEY else 'no'}"
    )

def parse_and_run(command_line: str) -> str:
    if not command_line.strip():
        return ""
    parts = command_line.strip().split()
    cmd = parts[0].lower()
    args = parts[1:]

    if cmd in ("exit", "quit"):
        print("Goodbye 👋")
        sys.exit(0)

    if cmd == "help":
        return help_text()

    if cmd == "keys":
        return show_keys()

    if cmd == "weather":
        if not args:
            return "Usage: weather <city>"
        city = " ".join(args)
        return get_weather(city)

    if cmd == "news":
        country = args[0] if args else "us"
        return get_news(country=country)

    if cmd == "wiki":
        if not args:
            return "Usage: wiki <topic>"
        topic = " ".join(args)
        return wiki_summary(topic, sentences=3)

    if cmd == "history":
        n = 10
        if args and args[0].isdigit():
            n = int(args[0])
        return show_history(limit=n)

    return "Unknown command. Type 'help' to see available commands."

def main_loop():
    print("Python Info Assistant — type 'help' for commands. Ctrl+C to quit.")
    while True:
        try:
            line = input("\n> ")
            start = time.time()
            out = parse_and_run(line)
            elapsed = time.time() - start
            if out:
                print("\n" + out)
            logging.info(f"command: {line} took {elapsed:.2f}s")
        except KeyboardInterrupt:
            print("\nInterrupted. Bye.")
            break
        except SystemExit:
            break
        except Exception as e:
            logging.exception("Main loop exception")
            print("An error occurred. Check the log for details.")

if __name__ == "__main__":
    init_db()
    main_loop()
