import streamlit as st
import json
import os
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from urllib.parse import urlparse
from google import genai

# ================= CONFIG =================
st.set_page_config(page_title="AI Productivity Analyzer", layout="centered")
st.title("🧠 AI Productivity Analyzer")

API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=API_KEY) if API_KEY else None

IST = timezone(timedelta(hours=5, minutes=30))
now_ist = datetime.now(IST)
today_start = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)

# ================= LOAD =================
def read_json(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except:
        return []

data = read_json("data.json")
categories = read_json("categories.json")

# ================= HELPERS =================
def format_time(ms):
    seconds = int(ms / 1000)

    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60

    parts = []
    if h > 0:
        parts.append(f"{h} hr")
    if m > 0:
        parts.append(f"{m} min")
    if s > 0:
        parts.append(f"{s} sec")

    return " ".join(parts)

def parse_ts(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(IST)

def get_domain(url):
    try:
        return urlparse(url).netloc.lower()
    except:
        return "unknown"

def classify(domain):
    for cat, sites in categories.items():
        for site in sites:
            if site in domain:
                return cat
    if "localhost" in domain:
        return "productive"
    return "neutral"

# ================= FILTER TODAY =================
today_records = []

for x in data:
    try:
        duration = int(x["duration_ms"])
        if duration < 2000:
            continue

        start = parse_ts(x["start_time"])
        end = start + timedelta(milliseconds=duration)

        if end < today_start:
            continue

        start = max(start, today_start)
        end = min(end, now_ist)

        today_records.append((start, end, x["url"]))
    except:
        continue

# ================= MERGE =================
def merge_intervals(intervals):
    intervals = sorted(intervals, key=lambda x: x[0])
    merged = []

    for s, e in intervals:
        if not merged:
            merged.append([s, e])
            continue

        last_s, last_e = merged[-1]

        if s <= last_e:
            merged[-1][1] = max(last_e, e)
        else:
            merged.append([s, e])

    return merged
def behavior_metrics(merged_intervals, total_time):
    if not merged_intervals or total_time == 0:
        return {}

    # avg session
    avg_session_ms = total_time / len(merged_intervals)

    # sessions per hour
    total_hours = total_time / (1000 * 60 * 60)
    switch_rate = len(merged_intervals) / total_hours if total_hours else 0

    # longest session
    longest = max((e - s).total_seconds() for s, e in merged_intervals)

    # focus score (simple formula)
    focus_score = min(100, (longest / 3600) * 100)

    return {
        "avg_session": avg_session_ms,
        "switch_rate": switch_rate,
        "longest_session": longest,
        "focus_score": focus_score
    }
def hourly_analysis(records):
    hourly_map = defaultdict(int)

    for start, end, _ in records:
        current = start

        while current < end:
            next_hour = (current.replace(minute=0, second=0, microsecond=0)
                         + timedelta(hours=1))

            slice_end = min(end, next_hour)
            duration = (slice_end - current).total_seconds() * 1000

            hour = current.hour
            hourly_map[hour] += duration

            current = slice_end

    return hourly_map
def detect_spikes(records):
    spikes = 0

    for i in range(1, len(records)):
        prev_end = records[i-1][1]
        curr_start = records[i][0]

        gap = (curr_start - prev_end).total_seconds()

        # very quick switch (less than 5 sec gap)
        if 0 < gap < 5:
            spikes += 1

    return spikes
def focus_streak(merged_intervals):
    if not merged_intervals:
        return 0

    longest = 0

    for start, end in merged_intervals:
        duration = (end - start).total_seconds()
        longest = max(longest, duration)

    return longest
# ================= GLOBAL =================
global_intervals = [(s, e) for s, e, _ in today_records]
merged_global = merge_intervals(global_intervals)

total_time = sum((e - s).total_seconds()*1000 for s, e in merged_global)
session_count = len(merged_global)
metrics = behavior_metrics(merged_global, total_time)

hourly_data = hourly_analysis(today_records)
current_hour = now_ist.hour
spikes = detect_spikes(today_records)
longest_focus = focus_streak(merged_global)
filtered_hours = {
    h: t for h, t in hourly_data.items()
    if h < current_hour   # only completed hours
}

if len(filtered_hours) > 1:
    peak_hour = max(filtered_hours, key=filtered_hours.get)
    low_hour = min(filtered_hours, key=filtered_hours.get)
else:
    peak_hour = None
    low_hour = None
# ================= SITE =================
site_map = defaultdict(list)
for s, e, url in today_records:
    site = get_domain(url)
    site_map[site].append((s, e))

site_time = {
    site: sum((e - s).total_seconds()*1000 for s, e in merge_intervals(v))
    for site, v in site_map.items()
}

top_sites = sorted(site_time.items(), key=lambda x: x[1], reverse=True)[:5]

# ================= CATEGORY =================
category_map = defaultdict(list)

for s, e, url in today_records:
    cat = classify(get_domain(url))
    category_map[cat].append((s, e))

category_time = {
    cat: sum((e - s).total_seconds()*1000 for s, e in merge_intervals(v))
    for cat, v in category_map.items()
}

# ================= SCORE =================
WEIGHTS = {
    "productive": 1.0,
    "neutral": 0.5,
    "communication": 0.6,
    "shopping": 0.2,
    "gaming": 0.0,
    "distracting": 0.0
}

weighted_time = sum(category_time.get(cat, 0)*w for cat, w in WEIGHTS.items())
score = (weighted_time / total_time * 100) if total_time else 0
score = min(score, 100)

# ================= DEEP =================
deep_sessions = [1 for s, e in merged_global if (e - s).total_seconds() >= 20*60]

# ================= HISTORY SAVE =================
def save_history():
    history_file = "history.json"
    today_str = str(now_ist.date())

    try:
        with open(history_file, "r") as f:
            history = json.load(f)
    except:
        history = []

    # skip if already saved today
    for h in history:
        if h["date"] == today_str:
            return

    # build top sites (already computed in your app)
    top_sites_data = [
        {"site": s, "ms": int(t)}
        for s, t in top_sites
    ]

    history.append({
        "date": today_str,
        "total_ms": int(total_time),
        "productive_ms": int(category_time.get("productive", 0)),
        "sessions": session_count,
        
        "category_ms": {k: int(v) for k, v in category_time.items()},
        "top_sites": top_sites_data,
        
        "hourly": {str(h): int(t) for h, t in hourly_data.items()}
    })

    with open(history_file, "w") as f:
        json.dump(history, f, indent=2)
def load_history():
    try:
        with open("history.json", "r") as f:
            return json.load(f)
    except:
        return []
history = load_history()

today_data = None
yesterday_data = None

for i in range(len(history)-1, -1, -1):
    if history[i]["date"] == str(now_ist.date()):
        today_data = history[i]
        if i > 0:
            yesterday_data = history[i-1]
        break
def compare_days(today, yesterday):
    if not today or not yesterday:
        return "Not enough data to compare yet."

    def pct_change(a, b):
        if b == 0:
            return 0
        return ((a - b) / b) * 100

    total_change = pct_change(today["total_ms"], yesterday["total_ms"])
    prod_change = pct_change(today["productive_ms"], yesterday["productive_ms"])
    session_change = pct_change(today["sessions"], yesterday["sessions"])

    summary = []

    # total time
    if total_change > 10:
        summary.append("⬆️ You worked more than yesterday")
    elif total_change < -10:
        summary.append("⬇️ You worked less than yesterday")

    # productivity
    if prod_change > 10:
        summary.append("🔥 Productivity improved")
    elif prod_change < -10:
        summary.append("⚠️ Productivity dropped")

    # sessions
    if session_change > 20:
        summary.append("⚠️ More tab switching today")
    elif session_change < -20:
        summary.append("✅ Better focus (less switching)")

    return summary

# CALL SAVE
if total_time > 0:
    save_history()

# ================= UI =================
# ================= SUMMARY =================
st.header("📊 Summary")
st.write("Total:", format_time(total_time))
st.write("Sessions:", session_count)
st.write("⚡ Productivity Score:", f"{score:.2f}%")

# ================= TOP SITES =================
st.header("🌐 Top Sites")
for s, t in top_sites:
    st.write(f"{s} → {format_time(t)}")

# ================= CATEGORIES =================
st.header("📈 Categories")
for k, v in category_time.items():
    st.write(f"{k} → {format_time(v)}")

# ================= DEEP WORK =================
st.header("🧘 Deep Work")
st.write("Deep sessions:", len(deep_sessions))


# ================= TIME INSIGHTS =================
st.header("⏰ Time Insights")

if peak_hour is not None:
    st.write(f"🔥 Peak hour: {peak_hour}:00 - {(peak_hour+1)%24}:00")
    st.write(f"😴 Lowest activity: {low_hour}:00 - {(low_hour+1)%24}:00")
else:
    st.write("⏳ Not enough data yet")


# ================= BEHAVIOR INSIGHTS =================
st.header("🧠 Behavior Insights")

if metrics:
    st.write(f"Avg session: {format_time(metrics['avg_session'])}")
    st.write(f"Switch rate: {metrics['switch_rate']:.1f} sessions/hour")
    st.write(f"Longest focus: {int(metrics['longest_session']//60)} min")
    st.write(f"Focus score: {metrics['focus_score']:.1f}/100 (moderate)")
    st.write(f"🔥 Longest focus streak: {int(longest_focus//60)} min")

st.write(f"⚠️ Distraction spikes: {spikes}")


# ================= COMPARISON =================
st.header("📅 Comparison (vs Yesterday)")

comparison = compare_days(today_data, yesterday_data)

if isinstance(comparison, list):
    for line in comparison:
        st.write(line)
else:
    st.write(comparison)
# ================= AI =================
st.header("🤖 AI Coach")

def ai_analysis():
    if not client:
        return "API key not set"

    prompt = f"""
You are a friendly productivity coach.
actaully bro i am building something like system detects the behaviour of user in chrome (i mean switching tabs )
...so user lossed time whitout knowing them bro .And detecting the behaviour of user ..
bro.... i am giving you data from that data you should tell user like very freindly.... simple ..interactive bro .
like where did you actually spent more of time ..
so in data some websites are not categerized .. all you have to do is serach the web and caterized yourself.
finally you guide like this 
Talk like a smart friend.
Use very simple English.
Keep it short and clear.
No long paragraphs.
No complex words.

Use simple English.
Keep it short.

User data:

Total time: {format_time(total_time)}
Sessions: {session_count}
Productivity score: {score:.1f}%

Top sites:
{top_sites}

Categories:
{category_time}

Behavior:
- Avg session: {format_time(metrics['avg_session'])}
- Switch rate: {metrics['switch_rate']:.1f}
- Longest focus: {int(longest_focus//60)} min
- Spikes: {spikes}

Time:
- Peak hour: {peak_hour}
- Low hour: {low_hour}

Give:

1. Quick summary (2 lines)
2. 3 problems
3. 3 simple improvements

Keep it crisp. No essay.
"""

    res = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )

    return res.text

if st.button("Get AI Insights"):
    with st.spinner("Thinking..."):
        st.write(ai_analysis())