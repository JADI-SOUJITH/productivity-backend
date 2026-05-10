from flask import Flask, request, jsonify
from flask_cors import CORS
from google import genai
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

import json
import os
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from urllib.parse import urlparse

app = Flask(__name__)

# ── CORS ──────────────────────────────────────────────────────────────────────
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://localhost:8080",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:8080",
    "https://productivity-frontend.vercel.app",
    "https://tanstack-start-app.productivity-tracker.workers.dev",
]
CORS(app, origins=ALLOWED_ORIGINS, supports_credentials=False)

IST = timezone(timedelta(hours=5, minutes=30))

GEMINI_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None

# ── MongoDB ───────────────────────────────────────────────────────────────────
MONGO_URI = os.getenv("MONGO_URI")
mongo = MongoClient(MONGO_URI, tlsAllowInvalidCertificates=True)
db        = mongo["productivity"]
col_data    = db["tracking_data"]
col_history = db["history"]

col_data.create_index(
    [("url", 1), ("start_time", 1), ("end_time", 1)],
    unique=True, background=True
)

CATEGORIES_FILE = "categories.json"


# =========================
# CATEGORIES
# =========================
def load_categories():
    default_categories = {
        "productive": [
            "leetcode.com", "geeksforgeeks.org", "github.com",
            "stackoverflow.com", "takeuforward.org", "codeforces.com",
            "hackerrank.com", "kaggle.com", "coursera.org", "udemy.com",
            "edx.org", "nptel.ac.in", "w3schools.com", "developer.mozilla.org",
            "docs.python.org", "chatgpt.com", "notion.so",
            "localhost", "127.0.0.1",
        ],
        "distracting": [
            "youtube.com", "instagram.com", "facebook.com", "twitter.com",
            "x.com", "snapchat.com", "reddit.com", "9gag.com",
            "netflix.com", "primevideo.com", "hotstar.com",
        ],
        "shopping": [
            "amazon.in", "amazon.com", "flipkart.com", "myntra.com", "ajio.com",
        ],
        "gaming": ["poki.com", "crazygames.com", "miniclip.com"],
        "communication": [
            "whatsapp.com", "web.whatsapp.com", "mail.google.com",
            "outlook.live.com", "zoom.us", "meet.google.com",
        ],
    }
    if not os.path.exists(CATEGORIES_FILE):
        return default_categories
    try:
        with open(CATEGORIES_FILE, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else default_categories
    except Exception:
        return default_categories


# =========================
# HELPERS
# =========================
def parse_ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(IST)


def get_domain(url):
    try:
        return urlparse(url).netloc.lower() or "unknown"
    except Exception:
        return "unknown"


def should_skip_url(url):
    if not url:
        return True
    skip = [
    "chrome://", "chrome-extension://", "about:", "edge://",
    "productivity-tracker.workers.dev",
    "onrender.com", "railway.app",
    "mongodb.com",
    "vercel.app",
]
    return any(s in url for s in skip)


def merge_intervals(intervals):
    if not intervals:
        return []
    intervals = sorted(intervals, key=lambda x: x[0])
    merged = [list(intervals[0])]
    for start, end in intervals[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def intervals_to_ms(intervals):
    return sum(int((e - s).total_seconds() * 1000) for s, e in merge_intervals(intervals))


def classify(domain, categories_map):
    domain = domain.lower()
    for category, sites in categories_map.items():
        for site in sites:
            if site.lower() in domain:
                return category
    if "localhost" in domain or "127.0.0.1" in domain:
        return "productive"
    return "neutral"


# =========================
# HISTORY HELPERS
# =========================
def normalize_previous(entry):
    if not entry:
        return None
    return {
        "date":       entry.get("date"),
        "total_time": entry.get("total_ms", 0),
        "sessions":   entry.get("sessions", 0),
        "score":      entry.get("score", 0),
        "categories": entry.get("category_ms", {}),
        "spikes":     entry.get("spikes", 0),
    }


def get_previous_snapshot(current_date_str):
    entry = col_history.find_one(
        {"date": {"$lt": current_date_str}},
        sort=[("date", -1)]
    )
    return normalize_previous(entry)


def save_daily_snapshot(snapshot):
    col_history.update_one(
        {"date": snapshot["date"]},
        {"$set": snapshot},
        upsert=True
    )


def compute_averages():
    history = list(col_history.find({}, {"_id": 0}))
    if not history:
        return {"total_time": 0, "sessions": 0, "score": 0, "spikes": 0}
    count = len(history)
    return {
        "total_time": sum(h.get("total_ms", 0) for h in history) / count,
        "sessions":   sum(h.get("sessions", 0) for h in history) / count,
        "score":      sum(h.get("score", 0) for h in history) / count,
        "spikes":     sum(h.get("spikes", 0) for h in history) / count,
    }


# =========================
# SAVE RAW DATA
# =========================
@app.route("/save", methods=["POST"])
def save_data():
    incoming = request.json or []
    added = 0

    for item in incoming:
        if should_skip_url(item.get("url", "")):
            continue
        try:
            col_data.insert_one({
                "url":         item.get("url"),
                "title":       item.get("title", ""),
                "duration_ms": item.get("duration_ms", 0),
                "start_time":  item.get("start_time"),
                "end_time":    item.get("end_time"),
            })
            added += 1
        except DuplicateKeyError:
            pass
        except Exception:
            pass

    total = col_data.count_documents({})
    print(f"✅ ADDED {added} | TOTAL: {total}")
    return jsonify({"status": "ok", "added": added, "total": total})


# =========================
# COACH ROUTE
# =========================
@app.route("/coach", methods=["POST"])
def coach():
    payload = request.get_json() or {}
    message = payload.get("message", "")
    data    = payload.get("data", {})

    if client is None:
        return jsonify({"reply": "⚠️ GEMINI_API_KEY not set on server."}), 400

    score       = data.get("score", 0)
    total_ms    = data.get("total_time", 0)
    total_min   = round(total_ms / 60000)
    sessions    = data.get("sessions", 0)
    spikes      = data.get("spikes", 0)
    longest_min = round(data.get("longest_focus", 0) / 60)
    focus_score = data.get("metrics", {}).get("focus_score", 0)
    switch_rate = data.get("metrics", {}).get("switch_rate", 0)
    peak_hour   = data.get("peak_hour")
    low_hour    = data.get("low_hour")

    top_sites = data.get("top_sites", [])
    if top_sites and isinstance(top_sites[0], dict):
        top_site_name = top_sites[0].get("name", "unknown")
    elif top_sites and isinstance(top_sites[0], list):
        top_site_name = top_sites[0][0]
    else:
        top_site_name = "unknown"

    categories = data.get("categories", {})
    if isinstance(categories, list):
        cat_summary = ", ".join(f"{c['name']}:{c['value']}min" for c in categories)
    else:
        cat_summary = ", ".join(f"{k}:{round(v/60000)}min" for k, v in categories.items())

    prompt = f"""You are a chill productivity buddy — like a smart friend who knows the user's work habits.

Personality:
- Casual, warm, a little witty
- Never robotic or corporate
- Short replies unless asked for more
- Sound like a real human texting, not an AI report

STRICT rules:
- ONLY respond to what the user actually said
- If they greet you (hey / hi / hooo / sup / hello etc.) — just greet back in 1 casual line, nothing else, no stats
- If they ask a vague question — answer briefly, only pull in stats if truly relevant
- If they ask about their productivity/data — then use the stats below
- NEVER dump all the stats unprompted
- No markdown, no bold, no bullet points unless they ask
- Max 2-3 sentences for casual messages, max 5-6 lines for data questions

User's message: "{message}"

Their stats today (only use if relevant):
- Total time: {total_min} min
- Score: {score}%
- Top site: {top_site_name}
- Focus score: {focus_score}/100
- Switch rate: {switch_rate}/hr
- Distractions: {spikes}
- Longest focus: {longest_min} min
- Sessions: {sessions}
- Peak hour: {peak_hour}
- Low hour: {low_hour}
- Categories: {cat_summary}
"""

    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt,
        )
        return jsonify({"reply": response.text})
    except Exception as e:
        return jsonify({"reply": f"AI Error: {str(e)}"}), 500


# =========================
# MAIN DATA ROUTE
# =========================
@app.route("/data")
def get_data():
    categories_map = load_categories()
    averages       = compute_averages()
    now_ist        = datetime.now(IST)
    today_str      = now_ist.date().isoformat()
    previous       = get_previous_snapshot(today_str)
    today_start    = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)

    empty_response = {
        "total_time": 0, "sessions": 0, "score": 0,
        "top_sites": [], "categories": {},
        "metrics": {"avg_session": 0, "switch_rate": 0, "focus_score": 0},
        "averages": averages, "spikes": 0, "longest_focus": 0,
        "peak_hour": None, "low_hour": None,
        "hourly": {}, "hourly_score": {}, "previous": previous,
    }

    raw = list(col_data.find(
        {"start_time": {"$gte": today_start.isoformat()}},
        {"_id": 0}
    ))

    today_records = []
    for item in raw:
        try:
            duration = int(item.get("duration_ms", 0))
            if duration < 2000:
                continue
            if should_skip_url(item.get("url", "")):
                continue
            start = parse_ts(item["start_time"])
            end   = parse_ts(item["end_time"]) if item.get("end_time") else start + timedelta(milliseconds=duration)
            if end < today_start:
                continue
            start = max(start, today_start)
            end   = min(end, now_ist)
            if end > start:
                today_records.append((start, end, item.get("url", "")))
        except Exception:
            continue

    if not today_records:
        return jsonify(empty_response)

    global_intervals = [(s, e) for s, e, _ in today_records]
    merged_global    = merge_intervals(global_intervals)
    total_time       = intervals_to_ms(global_intervals)
    sessions         = len(merged_global)

    site_map = defaultdict(list)
    for s, e, url in today_records:
        site_map[get_domain(url)].append((s, e))
    site_time = {site: intervals_to_ms(v) for site, v in site_map.items()}
    top_sites = [[site, ms] for site, ms in
                 sorted(site_time.items(), key=lambda x: x[1], reverse=True)[:5]]

    category_map = defaultdict(list)
    for s, e, url in today_records:
        cat = classify(get_domain(url), categories_map)
        category_map[cat].append((s, e))
    category_time = {cat: intervals_to_ms(v) for cat, v in category_map.items()}

    weights = {
        "productive": 1.0, "neutral": 0.5, "communication": 0.6,
        "shopping": 0.2, "gaming": 0.0, "distracting": 0.0,
    }
    weighted_time = sum(category_time.get(cat, 0) * w for cat, w in weights.items())
    score = round(min((weighted_time / total_time * 100) if total_time else 0, 100), 2)

    avg_session   = int(total_time / sessions) if sessions else 0
    total_hours   = total_time / (1000 * 60 * 60)
    switch_rate   = round(sessions / total_hours, 1) if total_hours else 0
    longest_focus = max((int((e - s).total_seconds()) for s, e in merged_global), default=0)
    focus_score   = round(min(100, (longest_focus / 3600) * 100), 1)

    hourly_total_ms      = defaultdict(int)
    hourly_productive_ms = defaultdict(int)
    for s, e, url in today_records:
        cat     = classify(get_domain(url), categories_map)
        current = s
        while current < e:
            next_hour = current.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            slice_end = min(e, next_hour)
            slice_ms  = int((slice_end - current).total_seconds() * 1000)
            hourly_total_ms[current.hour] += slice_ms
            if cat == "productive":
                hourly_productive_ms[current.hour] += slice_ms
            current = slice_end

    hourly_score = {
        str(h): round((hourly_productive_ms[h] / hourly_total_ms[h]) * 100, 1)
        if hourly_total_ms[h] else 0
        for h in range(24)
    }

    active_hours  = [h for h in range(24) if hourly_total_ms[h] > 0]
    peak_hour = max(active_hours, key=lambda h: hourly_score[str(h)]) if active_hours else None
    low_hour  = min(active_hours, key=lambda h: hourly_score[str(h)]) if active_hours else None

    spikes = sum(
        1 for i in range(1, len(today_records))
        if 0 < (today_records[i][0] - today_records[i-1][1]).total_seconds() < 5
    )

    snapshot = {
        "date":          today_str,
        "total_ms":      int(total_time),
        "productive_ms": int(category_time.get("productive", 0)),
        "sessions":      sessions,
        "score":         score,
        "spikes":        spikes,
        "category_ms":   {k: int(v) for k, v in category_time.items()},
        "top_sites":     top_sites,
        "hourly_score":  hourly_score,
        "longest_focus": int(longest_focus),
    }
    save_daily_snapshot(snapshot)

    return jsonify({
        "total_time":    total_time,
        "sessions":      sessions,
        "score":         score,
        "top_sites":     top_sites,
        "categories":    category_time,
        "metrics": {
            "avg_session": avg_session,
            "switch_rate": switch_rate,
            "focus_score": focus_score,
        },
        "averages":      averages,
        "spikes":        spikes,
        "longest_focus": longest_focus,
        "peak_hour":     peak_hour,
        "low_hour":      low_hour,
        "hourly":        {str(h): int(hourly_total_ms[h]) for h in range(24)},
        "hourly_score":  hourly_score,
        "previous":      previous,
    })


# =========================
# HOME
# =========================
@app.route("/")
def home():
    return "✅ Productivity Tracker API running"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port)