import json
from datetime import datetime
from collections import defaultdict

# ================= LOAD DATA =================
def read_data():
    try:
        with open("data.json", "r") as f:
            return json.load(f)
    except:
        return []

# ================= LOAD CATEGORIES =================
def load_categories():
    with open("categories.json", "r") as f:
        return json.load(f)

# ================= CLASSIFY =================
def classify(url, categories):
    url = url.lower()

    for category, sites in categories.items():
        for site in sites:
            if site in url:
                return category

    if "localhost" in url or "127.0.0.1" in url:
        return "productive"

    return "neutral"

# ================= CLEAN DATA =================
def clean_data(data):
    cleaned = []
    for item in data:
        if item["duration_ms"] < 2000:  # remove noise
            continue
        cleaned.append(item)
    return cleaned

# ================= MERGE SESSIONS =================
def merge_sessions(data):
    data = sorted(data, key=lambda x: x["start_time"])
    merged = []

    for item in data:
        if not merged:
            merged.append(item)
            continue

        prev = merged[-1]

        prev_end = datetime.fromisoformat(prev["end_time"].replace("Z", ""))
        curr_start = datetime.fromisoformat(item["start_time"].replace("Z", ""))

        gap = (curr_start - prev_end).total_seconds()

        if prev["url"] == item["url"] and gap < 60:
            prev["duration_ms"] += item["duration_ms"]
            prev["end_time"] = item["end_time"]
        else:
            merged.append(item)

    return merged

# ================= SPLIT TODAY =================
from datetime import datetime, timedelta

def split_today(data):
    IST_OFFSET = timedelta(hours=5, minutes=30)
    today = (datetime.utcnow() + IST_OFFSET).date()

    today_data = []

    for item in data:
        dt = datetime.fromisoformat(item["start_time"].replace("Z", ""))
        dt = dt + IST_OFFSET   # convert to IST

        if dt.date() == today:
            today_data.append(item)

    return today_data, data

# ================= CATEGORY TIME =================
def category_breakdown(data, categories):
    result = defaultdict(int)

    for item in data:
        cat = classify(item["url"], categories)
        result[cat] += item["duration_ms"]

    return dict(result)

# ================= PRODUCTIVITY SCORE =================
WEIGHTS = {
    "productive": 1.0,
    "neutral": 0.5,
    "communication": 0.6,
    "shopping": 0.2,
    "gaming": 0.0,
    "distracting": 0.0
}

def compute_score(data, categories):
    total = 0
    weighted = 0

    for item in data:
        duration = item["duration_ms"]
        cat = classify(item["url"], categories)

        total += duration
        weighted += duration * WEIGHTS.get(cat, 0.5)

    if total == 0:
        return 0

    return (weighted / total) * 100

# ================= DEEP WORK =================
def deep_work_sessions(data):
    sessions = []

    for item in data:
        if item["duration_ms"] >= 20 * 60 * 1000:
            sessions.append(item)

    return sessions

# ================= FORMAT TIME =================
def format_time(ms):
    seconds = int(ms / 1000)
    mins = seconds // 60
    secs = seconds % 60
    return f"{mins} min {secs} sec"

# ================= INSIGHTS =================
def generate_insights(data, categories):
    msgs = []

    score = compute_score(data, categories)
    deep = deep_work_sessions(data)

    if score < 40:
        msgs.append("⚠️ Low productivity detected")
    elif score > 70:
        msgs.append("🔥 Strong productive focus")

    if len(deep) == 0:
        msgs.append("🧠 No deep work sessions found")
    else:
        msgs.append(f"🚀 {len(deep)} deep work sessions detected")

    if len(data) > 80:
        msgs.append("⚠️ Too many context switches")

    return msgs

# ================= MAIN =================
if __name__ == "__main__":
    data = read_data()
    categories = load_categories()

    data = clean_data(data)
    data = merge_sessions(data)

    today_data, overall_data = split_today(data)

    print("\n===== TODAY =====")

    total_today = sum(x["duration_ms"] for x in today_data)
    print("Total Time:", format_time(total_today))
    print("Sessions:", len(today_data))

    score = compute_score(today_data, categories)
    print("Productivity Score:", f"{score:.2f}%")

    breakdown = category_breakdown(today_data, categories)
    print("\n--- Category Breakdown ---")
    for k, v in breakdown.items():
        print(k, "→", format_time(v))

    print("\n--- Insights ---")
    for msg in generate_insights(today_data, categories):
        print("-", msg)

    print("\n===== OVERALL =====")

    total_all = sum(x["duration_ms"] for x in overall_data)
    print("Total Time:", format_time(total_all))
    print("Sessions:", len(overall_data))