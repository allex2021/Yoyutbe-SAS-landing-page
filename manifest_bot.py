"""
ManifestBot v1.0 — Manifest & Metadata Automation Script
=========================================================
Scans the output folder, extracts technical metadata from every
processed short via ffprobe, auto-generates viral YouTube Shorts
titles / descriptions / hashtags, and exports:

  • manifest.json   — full machine-readable record
  • manifest.csv    — spreadsheet-ready for bulk upload tools
  • output/<name>.txt — per-video upload card (copy-paste ready)
"""

import os
import json
import csv
import subprocess
import datetime
import random

# ── Configuration ──────────────────────────────────────────────
OUTPUT_FOLDER = "output"          # Folder with processed shorts
FFPROBE_BIN   = os.path.expanduser("~/bin/ffmpeg").replace("ffmpeg", "ffprobe")
MANIFEST_JSON = "manifest.json"
MANIFEST_CSV  = "manifest.csv"
GEMINI_API_KEY = ""               # Optional Gemini API Key for AI viral tags & titles

# ── Viral title templates (slot in {topic} at runtime) ─────────
TITLE_TEMPLATES = [
    "This Will SHOCK You 😱 #{topic}",
    "Nobody Talks About This... #{topic}",
    "Wait For It 🤯 #{topic}",
    "POV: You Finally Understand #{topic}",
    "The #{topic} Trick Nobody Shows You",
    "I Tried #{topic} For 30 Days — Here's What Happened",
    "#{topic} Facts That Will Break Your Brain 🧠",
    "Stop Scrolling — Watch This #{topic} Clip",
    "The #{topic} Secret They Don't Want You To Know",
    "#{topic} Explained In 30 Seconds ⚡",
]

# ── Default hashtag pools ───────────────────────────────────────
DEFAULT_HASHTAGS = [
    "#shorts", "#viral", "#trending", "#fyp", "#reels",
    "#youtubeshorts", "#explore", "#foryou", "#satisfying", "#mindblowing",
]

TOPIC = "Amazing"   # ← Change this to your niche/topic keyword


# ──────────────────────────────────────────────────────────────
#  HELPERS
# ──────────────────────────────────────────────────────────────

def run_ffprobe(filepath):
    """
    Runs ffprobe to extract stream & format metadata as JSON.
    Returns a dict, or None on failure.
    """
    ffprobe = FFPROBE_BIN if os.path.exists(FFPROBE_BIN) else "ffprobe"
    cmd = [
        ffprobe, "-v", "quiet",
        "-print_format", "json",
        "-show_streams", "-show_format",
        filepath
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return json.loads(result.stdout)
    except Exception:
        return None


def query_gemini_api(api_key: str, prompt: str, system_instruction: str = None) -> str:
    import urllib.request
    import urllib.error
    import json
    import time
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    if system_instruction:
        payload["systemInstruction"] = {
            "parts": [{"text": system_instruction}]
        }
    headers = {"Content-Type": "application/json"}
    
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=30) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                return res_data["candidates"][0]["content"]["parts"][0]["text"]
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait_time = (2 ** attempt) + 1
                print(f"[Gemini API] Rate limited (429). Retrying in {wait_time}s...")
                time.sleep(wait_time)
                continue
            else:
                print(f"[Gemini API] HTTP Error {e.code}: {e.reason}")
                break
        except Exception as e:
            print(f"[Gemini API] Error calling Gemini: {e}")
            break
    return None


def parse_video_meta(ffprobe_data, filepath):
    """
    Extracts human-readable technical metadata from ffprobe output.
    """
    meta = {
        "filename"    : os.path.basename(filepath),
        "filepath"    : os.path.abspath(filepath),
        "file_size_mb": round(os.path.getsize(filepath) / (1024 * 1024), 2),
        "created_at"  : datetime.datetime.fromtimestamp(
                            os.path.getmtime(filepath)
                        ).strftime("%Y-%m-%d %H:%M:%S"),
        "duration_sec": None,
        "width"       : None,
        "height"      : None,
        "fps"         : None,
        "video_codec" : None,
        "audio_codec" : None,
        "bitrate_kbps": None,
    }

    if not ffprobe_data:
        return meta

    fmt = ffprobe_data.get("format", {})
    meta["duration_sec"] = round(float(fmt.get("duration", 0)), 2)
    meta["bitrate_kbps"] = round(int(fmt.get("bit_rate", 0)) / 1000, 1)

    for stream in ffprobe_data.get("streams", []):
        if stream.get("codec_type") == "video" and meta["width"] is None:
            meta["width"]       = stream.get("width")
            meta["height"]      = stream.get("height")
            meta["video_codec"] = stream.get("codec_name")
            r_frame_rate        = stream.get("r_frame_rate", "0/1")
            try:
                num, den        = map(int, r_frame_rate.split("/"))
                meta["fps"]     = round(num / den, 2) if den else None
            except Exception:
                meta["fps"]     = None

        elif stream.get("codec_type") == "audio" and meta["audio_codec"] is None:
            meta["audio_codec"] = stream.get("codec_name")

    return meta


def generate_title(topic=TOPIC):
    """Picks a random viral title template and fills in the topic."""
    template = random.choice(TITLE_TEMPLATES)
    return template.replace("{topic}", topic).replace("#{topic}", f"#{topic}")


def generate_description(title, hashtags=None):
    """Builds a YouTube Shorts description block."""
    tags = hashtags or DEFAULT_HASHTAGS
    tag_line = " ".join(tags)
    return (
        f"{title}\n\n"
        f"🔔 Subscribe for more!\n"
        f"👍 Like if this helped you!\n"
        f"💬 Comment your thoughts below!\n\n"
        f"{tag_line}"
    )


def write_upload_card(meta, title, description, output_path):
    """Writes a per-video .txt upload card."""
    lines = [
        "=" * 60,
        f"  UPLOAD CARD — {meta['filename']}",
        "=" * 60,
        "",
        "[ TITLE ]",
        title,
        "",
        "[ DESCRIPTION ]",
        description,
        "",
        "[ TECHNICAL INFO ]",
        f"  Duration  : {meta['duration_sec']}s",
        f"  Resolution: {meta['width']}x{meta['height']}",
        f"  FPS       : {meta['fps']}",
        f"  Size      : {meta['file_size_mb']} MB",
        f"  Codecs    : {meta['video_codec']} / {meta['audio_codec']}",
        f"  Bitrate   : {meta['bitrate_kbps']} kbps",
        f"  Created   : {meta['created_at']}",
        "",
        "=" * 60,
    ]
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ──────────────────────────────────────────────────────────────
#  MAIN ENGINE
# ──────────────────────────────────────────────────────────────

def run_manifest_bot():
    print("📋" + "=" * 54 + "📋")
    print("        MANIFESTBOT v1.0 — Metadata Automation         ")
    print("📋" + "=" * 54 + "📋\n")

    if not os.path.isdir(OUTPUT_FOLDER):
        print(f"❌  Output folder '{OUTPUT_FOLDER}' not found.")
        print("    Run flood_bot.py first to generate processed shorts.\n")
        return

    mp4_files = sorted([
        os.path.join(OUTPUT_FOLDER, f)
        for f in os.listdir(OUTPUT_FOLDER)
        if f.lower().endswith(".mp4")
    ])

    if not mp4_files:
        print(f"⚠️   No .mp4 files found in '{OUTPUT_FOLDER}/'.")
        return

    print(f"🔍  Found {len(mp4_files)} video(s) in '{OUTPUT_FOLDER}/'\n")

    all_records = []

    for i, filepath in enumerate(mp4_files, start=1):
        fname = os.path.basename(filepath)
        print(f"  [{i}/{len(mp4_files)}] Processing: {fname}")

        # ── Extract technical metadata ──────────────────────
        ffprobe_data = run_ffprobe(filepath)
        meta         = parse_video_meta(ffprobe_data, filepath)

        # ── Generate YouTube content ────────────────────────
        transcript_text = ""
        trans_file = filepath.replace(".mp4", "_transcript.txt")
        if os.path.exists(trans_file):
            try:
                with open(trans_file, encoding="utf-8") as tf:
                    transcript_text = tf.read().strip()
            except Exception:
                pass

        title = None
        description = None
        hashtags = None

        if GEMINI_API_KEY and transcript_text:
            print(f"           ✨  Generating AI metadata via Gemini...")
            prompt = (
                f"Analyze the following video transcript segments and generate extremely viral YouTube Shorts metadata:\n"
                f"1. A highly catchy, clickable YouTube Short Title (under 60 chars) with 1-2 emojis.\n"
                f"2. A short engaging description (1-2 sentences) encouraging views and subscription.\n"
                f"3. 3-5 relevant trending hashtags (first one must be the main niche keyword).\n\n"
                f"Output strictly a JSON object with keys \"title\" (string), \"description\" (string), and \"hashtags\" (list of strings). "
                f"Do not output any markdown code blocks or extra text, just the raw JSON.\n\n"
                f"Transcript:\n{transcript_text}"
            )
            g_res = query_gemini_api(GEMINI_API_KEY, prompt, "You are a professional social media manager and SEO expert.")
            if g_res:
                import re
                match = re.search(r"\{.*\}", g_res, re.DOTALL)
                if match:
                    try:
                        data = json.loads(match.group(0))
                        title = data.get("title")
                        description = data.get("description")
                        hashtags = data.get("hashtags", [])
                        hashtags = [h.strip() if h.startswith("#") else f"#{h.strip()}" for h in hashtags]
                        if hashtags:
                            description += "\n\n" + " ".join(hashtags)
                    except Exception as e_json:
                        print(f"           ⚠️  Gemini JSON parse failed: {e_json}")

        if not title or not description:
            base = os.path.splitext(fname)[0]
            for prefix in ["yt_short_", "short_"]:
                if base.startswith(prefix):
                    base = base[len(prefix):]
            cleaned = base.replace("_", " ").replace("-", " ").replace("|", " ").replace("｜", " ")
            words = [w.capitalize() for w in cleaned.split() if w.lower() not in ["and", "or", "the", "a", "to", "for", "in", "on", "of", "with"]]
            guessed_topic = words[0] if words else TOPIC
            
            topic_tag = f"#{guessed_topic.replace(' ', '').replace('_', '')}"
            hashtags = [topic_tag.lower()] + [h for h in DEFAULT_HASHTAGS if h.lower() != topic_tag.lower()][:4]

            title        = generate_title(guessed_topic)
            description  = generate_description(title, hashtags)

        # ── Write per-video upload card (.txt) ─────────────
        card_path    = filepath.replace(".mp4", "_upload_card.txt")
        write_upload_card(meta, title, description, card_path)
        print(f"           ✅  Upload card → {os.path.basename(card_path)}")

        # ── Build full record ───────────────────────────────
        record = {
            **meta,
            "youtube_title"      : title,
            "youtube_description": description,
            "hashtags"           : hashtags,
            "upload_card"        : card_path,
            "status"             : "ready_to_upload",
        }
        all_records.append(record)

    # ── Export manifest.json ────────────────────────────────
    with open(MANIFEST_JSON, "w", encoding="utf-8") as f:
        json.dump(all_records, f, indent=2, ensure_ascii=False)
    print(f"\n  💾  manifest.json  → {MANIFEST_JSON}")

    # ── Export manifest.csv ─────────────────────────────────
    csv_fields = [
        "filename", "duration_sec", "width", "height", "fps",
        "file_size_mb", "video_codec", "audio_codec", "bitrate_kbps",
        "created_at", "youtube_title", "status",
    ]
    with open(MANIFEST_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_records)
    print(f"  📊  manifest.csv   → {MANIFEST_CSV}")

    # ── Summary ─────────────────────────────────────────────
    print("\n" + "═" * 60)
    print("📊  MANIFEST SUMMARY")
    print("═" * 60)
    total_dur  = sum(r["duration_sec"] or 0 for r in all_records)
    total_size = sum(r["file_size_mb"] for r in all_records)
    print(f"   Videos processed : {len(all_records)}")
    print(f"   Total duration   : {round(total_dur, 1)}s  ({round(total_dur/60, 1)} min)")
    print(f"   Total size       : {round(total_size, 2)} MB")
    print(f"   Output folder    : {os.path.abspath(OUTPUT_FOLDER)}/")
    print(f"   Manifest JSON    : {os.path.abspath(MANIFEST_JSON)}")
    print(f"   Manifest CSV     : {os.path.abspath(MANIFEST_CSV)}")
    print("═" * 60)
    print("🏁  All metadata generated — ready to upload!\n")


if __name__ == "__main__":
    run_manifest_bot()
