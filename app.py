"""
FloodBot UI — Flask Backend v2.0 (app.py)
"""

import os, sys, json, time, queue, threading, subprocess
from flask import Flask, render_template, request, jsonify, Response, send_from_directory

if getattr(sys, 'frozen', False):
    # Running inside PyInstaller bundle
    BASE_DIR = sys._MEIPASS
    # For writing outputs, use the folder where the executable resides
    EXE_DIR = os.path.dirname(sys.executable)
    OUTPUT_FOLDER = os.path.join(EXE_DIR, "output")
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    OUTPUT_FOLDER = os.path.join(BASE_DIR, "output")

template_dir = os.path.join(BASE_DIR, "templates")
app = Flask(__name__, template_folder=template_dir)

# Silence Flask's default Werkzeug request log prints (prevents flooding log lines)
import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

CURRENT_VERSION = "3.0"
def find_ffmpeg() -> str:
    ext = ".exe" if sys.platform == "win32" else ""
    local_bin = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin")
    
    if getattr(sys, 'frozen', False):
        meipass_ffmpeg = os.path.join(sys._MEIPASS, f"ffmpeg{ext}")
        if os.path.exists(meipass_ffmpeg):
            return meipass_ffmpeg

    for p in [
        os.path.join(local_bin, f"ffmpeg{ext}"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), f"ffmpeg{ext}"),
        os.path.expanduser(f"~/bin/ffmpeg{ext}"),
    ]:
        if os.path.exists(p):
            return p
            
    import shutil
    path_bin = shutil.which("ffmpeg")
    if path_bin:
        return path_bin
        
    return f"ffmpeg{ext}"

FFMPEG_BIN = find_ffmpeg()

log_queue : queue.Queue = queue.Queue()
is_running = {"floodbot": False, "manifestbot": False}


def push_log(msg, level="info"):
    log_queue.put({"msg": msg, "level": level, "ts": time.strftime("%H:%M:%S")})


def sanitize_output_folder(custom_folder=None):
    """Sanitizes output folder path and falls back to server default if path is invalid/incompatible."""
    if not custom_folder or not str(custom_folder).strip():
        return OUTPUT_FOLDER
    folder = str(custom_folder).strip()
    # If running on Linux/Railway, ignore Windows/Mac drive paths like C:\ or /Users/ if they don't exist
    if sys.platform != "win32" and (folder.startswith(("C:", "D:", "c:", "d:", "\\")) or (folder.startswith("/Users/") and not os.path.exists(folder))):
        return OUTPUT_FOLDER
    try:
        folder = os.path.expanduser(folder)
        os.makedirs(folder, exist_ok=True)
        return folder
    except Exception:
        return OUTPUT_FOLDER


def get_output_files(custom_folder=None):
    folder = sanitize_output_folder(custom_folder)
    files = []
    try:
        for f in sorted(os.listdir(folder)):
            if not f.lower().endswith(".mp4"): continue
            path    = os.path.join(folder, f)
            size_mb = round(os.path.getsize(path) / (1024**2), 2)
            card    = f.replace(".mp4", "_upload_card.txt")
            card_p  = os.path.join(folder, card)
            card_tx = open(card_p, encoding="utf-8").read() if os.path.exists(card_p) else ""
            files.append({"name": f, "size_mb": size_mb, "has_card": os.path.exists(card_p), "card_text": card_tx})
    except Exception:
        pass
    return files


@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/status")
def status():
    folder = request.args.get("output_folder", "").strip() or None
    return jsonify({
        "floodbot_running"   : is_running["floodbot"],
        "manifestbot_running": is_running["manifestbot"],
        "output_files"       : get_output_files(folder),
        "ffmpeg_ok"          : os.path.exists(FFMPEG_BIN),
    })

@app.route("/api/output-files")
def output_files_api():
    folder = request.args.get("output_folder", "").strip() or None
    return jsonify(get_output_files(folder))

@app.route("/api/clear-history", methods=["POST"])
def clear_history():
    """Deletes all output MP4 files and metadata cards in the output folder."""
    try:
        data = request.get_json() or {}
        folder = data.get("output_folder", "").strip() or OUTPUT_FOLDER
        folder = os.path.expanduser(folder)
        if not os.path.exists(folder):
            return jsonify({"ok": True, "message": "Folder does not exist"})
        
        count = 0
        for f in os.listdir(folder):
            ext = os.path.splitext(f)[1].lower()
            if ext in [".mp4", ".txt"]:
                # Only delete if it's a short video or an upload card to be safe
                if ext == ".mp4" or f.endswith("_upload_card.txt"):
                    file_path = os.path.join(folder, f)
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                        count += 1
        return jsonify({"ok": True, "deleted": count})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/output/<path:filename>")
def serve_output(filename):
    folder = request.args.get("output_folder", "").strip() or OUTPUT_FOLDER
    folder = os.path.expanduser(folder)
    return send_from_directory(folder, filename)


# ── Serve any local video for browser preview ─────────────────────────────────
@app.route("/api/serve-video")
def serve_video():
    """Stream a local video file for in-browser preview."""
    path = request.args.get("path", "").strip()
    path = os.path.expanduser(path)
    if not path or not os.path.exists(path):
        return jsonify({"error": "File not found"}), 404
    folder  = os.path.dirname(path)
    fname   = os.path.basename(path)
    return send_from_directory(folder, fname, conditional=True)


@app.route("/api/browse-files", methods=["POST"])
def browse_files():
    """
    List video files in a given directory.
    Also supports a system file-picker dialog (macOS/Windows/Linux) when dir='__dialog__'.
    """
    data = request.get_json() or {}
    directory = data.get("directory", "").strip()
    exts = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".flv"}

    if directory == "__dialog__":
        # Open OS file picker via osascript (macOS) or zenity (Linux)
        try:
            if sys.platform == "darwin":
                result = subprocess.run(
                    ["osascript", "-e",
                     'POSIX path of (choose file of type {"mp4","mov","avi","mkv","webm","m4v"}'
                     ' with prompt "Select a video file")'],
                    capture_output=True, text=True, timeout=60
                )
                picked = result.stdout.strip()
                if picked:
                    return jsonify({"files": [{"path": picked, "name": os.path.basename(picked),
                                               "size_mb": round(os.path.getsize(picked)/(1024**2),2)}]})
            elif sys.platform == "win32":
                result = subprocess.run(
                    ["powershell", "-Command",
                     "Add-Type -AssemblyName System.Windows.Forms;"
                     "$f=New-Object System.Windows.Forms.OpenFileDialog;"
                     "$f.Filter='Video Files|*.mp4;*.mov;*.avi;*.mkv;*.webm';"
                     "if($f.ShowDialog() -eq 'OK'){$f.FileName}"],
                    capture_output=True, text=True, timeout=60
                )
                picked = result.stdout.strip()
                if picked:
                    return jsonify({"files": [{"path": picked, "name": os.path.basename(picked),
                                               "size_mb": round(os.path.getsize(picked)/(1024**2),2)}]})
        except Exception as e:
            return jsonify({"error": f"Dialog failed: {e}"}), 500
        return jsonify({"files": []})

    # List all videos in a directory
    directory = os.path.expanduser(directory or BASE_DIR)
    if not os.path.isdir(directory):
        return jsonify({"error": f"Not a directory: {directory}"}), 400

    files = []
    try:
        for f in sorted(os.listdir(directory)):
            if os.path.splitext(f)[1].lower() in exts:
                full = os.path.join(directory, f)
                files.append({
                    "path": full,
                    "name": f,
                    "size_mb": round(os.path.getsize(full)/(1024**2), 2),
                })
    except PermissionError:
        return jsonify({"error": "Permission denied"}), 403
    return jsonify({"files": files})


@app.route("/api/video-info", methods=["POST"])
def video_info():
    """Return duration, resolution, fps of a local video using FFprobe."""
    data = request.get_json() or {}
    path = os.path.expanduser(data.get("path", "").strip())
    if not path or not os.path.exists(path):
        return jsonify({"error": "File not found"}), 404

    ffprobe = os.path.expanduser("~/bin/ffprobe")
    if not os.path.exists(ffprobe):
        ffprobe = "ffprobe"

    cmd = [ffprobe, "-v", "quiet", "-print_format", "json",
           "-show_streams", "-show_format", path]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if r.returncode == 0 and r.stdout.strip():
            info = json.loads(r.stdout)
            duration = float(info.get("format", {}).get("duration", 0))
            width = height = fps = None
            for s in info.get("streams", []):
                if s.get("codec_type") == "video":
                    width  = s.get("width")
                    height = s.get("height")
                    fr = s.get("avg_frame_rate", "0/1")
                    try:
                        n, d = fr.split("/")
                        fps = round(float(n)/float(d), 2) if float(d) else 0
                    except Exception:
                        fps = 0
                    break
            return jsonify({"duration": duration, "width": width, "height": height, "fps": fps,
                            "size_mb": round(os.path.getsize(path)/(1024**2), 2),
                            "name": os.path.basename(path), "path": path})
    except Exception:
        pass

    # Fallback to ffmpeg -i parsing if ffprobe fails or is missing
    ffmpeg_bin = os.path.expanduser("~/bin/ffmpeg")
    if not os.path.exists(ffmpeg_bin):
        ffmpeg_bin = "ffmpeg"
    try:
        r = subprocess.run([ffmpeg_bin, "-i", path], capture_output=True, text=True, timeout=15)
        duration = 0.0
        width = height = fps = None
        
        import re
        for line in r.stderr.splitlines():
            if "Duration:" in line:
                m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", line)
                if m:
                    h, m_val, s = m.groups()
                    duration = float(h)*3600 + float(m_val)*60 + float(s)
            if "Video:" in line:
                res_match = re.search(r"\b(\d{3,4})x(\d{3,4})\b", line)
                if res_match:
                    width = int(res_match.group(1))
                    height = int(res_match.group(2))
                fps_match = re.search(r"\b(\d+(\.\d+)?)\s*fps\b", line)
                if fps_match:
                    fps = float(fps_match.group(1))
                    
        return jsonify({"duration": duration, "width": width, "height": height, "fps": fps,
                        "size_mb": round(os.path.getsize(path)/(1024**2), 2),
                        "name": os.path.basename(path), "path": path})
    except Exception as e:
        return jsonify({"error": f"Metadata extraction failed: {str(e)}"}), 500


@app.route("/api/generate-thumbnail", methods=["POST"])
def generate_thumbnail():
    """Extract a thumbnail frame from a video at a given timestamp."""
    data = request.get_json() or {}
    path  = os.path.expanduser(data.get("path", "").strip())
    ts    = float(data.get("timestamp", 0))
    if not path or not os.path.exists(path):
        return jsonify({"error": "File not found"}), 404

    thumb_name = f"_thumb_{os.getpid()}_{int(ts)}.jpg"
    thumb_path = os.path.join(BASE_DIR, thumb_name)
    cmd = [os.path.expanduser("~/bin/ffmpeg"), "-y",
           "-ss", str(ts), "-i", path,
           "-frames:v", "1", "-q:v", "2", thumb_path]
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
    if r.returncode == 0 and os.path.exists(thumb_path):
        return send_from_directory(BASE_DIR, thumb_name)
    return jsonify({"error": "Thumbnail generation failed"}), 500



@app.route("/api/youtube-metadata", methods=["POST"])
def youtube_metadata():
    data = request.get_json()
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    ytdlp = os.path.abspath(os.path.join(BASE_DIR, ".venv", "bin", "yt-dlp"))
    if not os.path.exists(ytdlp):
        ytdlp = os.path.expanduser("~/Library/Python/3.9/bin/yt-dlp")
    if not os.path.exists(ytdlp):
        ytdlp = "yt-dlp"

    # Setup environment with ~/bin in PATH for ffmpeg
    env = os.environ.copy()
    ffmpeg_dir = os.path.expanduser("~/bin")
    if os.path.exists(ffmpeg_dir):
        env["PATH"] = ffmpeg_dir + os.pathsep + env.get("PATH", "")

    cookies_path = os.path.join(BASE_DIR, "cookies.txt")
    cookie_fallback = []
    if os.path.exists(cookies_path):
        cookie_fallback.append(["--cookies", cookies_path])
        
    cookie_fallback.extend([
        ["--cookies-from-browser", "chrome"],
        ["--cookies-from-browser", "safari"],
        ["--cookies-from-browser", "firefox"],
        []
    ])

    for opt in cookie_fallback:
        cmd = [
            ytdlp,
            "--skip-download",
            "--dump-json",
            "--no-playlist",
            "--extractor-args", "youtube:player-client=ios,android,web_creator",
            "--user-agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "--referer", "https://www.youtube.com/",
            "--no-cache-dir"
        ] + opt + [url]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=20, env=env)
            if result.returncode == 0:
                info = json.loads(result.stdout)
                thumb = info.get("thumbnail")
                if not thumb and info.get("thumbnails"):
                    thumb = info.get("thumbnails")[-1]["url"]
                return jsonify({
                    "title": info.get("title"),
                    "duration": info.get("duration"),
                    "thumbnail": thumb,
                    "description": info.get("description", "")[:200] + "...",
                })
        except Exception:
            continue

    # Fallback: Extract video ID and build raw placeholders to avoid blocking the user
    video_id = None
    import re
    patterns = [
        r"v=([^#\&\?]+)",
        r"youtu\.be\/([^#\&\?]+)",
        r"shorts\/([^#\&\?]+)",
        r"embed\/([^#\&\?]+)"
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            video_id = match.group(1)
            break
            
    if video_id:
        fallback_thumb = f"https://img.youtube.com/vi/{video_id}/0.jpg"
        return jsonify({
            "title": f"YouTube Video ({video_id})",
            "duration": 180,  # 3 minutes default
            "thumbnail": fallback_thumb,
            "description": "YouTube Video Imported (Fallback Mode)"
        })

    return jsonify({"error": "Failed to extract YouTube metadata (YouTube bot block). Try opening the link in Chrome/Safari browser first to refresh session."}), 500


@app.route("/api/find-viral-videos", methods=["POST"])
def find_viral_videos():
    data = request.get_json()
    keyword = data.get("keyword", "").strip()
    timeframe = data.get("timeframe", "24h") # "24h", "7d", "all"
    if not keyword:
        keyword = "shorts viral"

    ytdlp = os.path.abspath(os.path.join(BASE_DIR, ".venv", "bin", "yt-dlp"))
    if not os.path.exists(ytdlp):
        ytdlp = os.path.expanduser("~/Library/Python/3.9/bin/yt-dlp")
    if not os.path.exists(ytdlp):
        ytdlp = "yt-dlp"

    # Setup environment with ~/bin in PATH for ffmpeg
    env = os.environ.copy()
    ffmpeg_dir = os.path.expanduser("~/bin")
    if os.path.exists(ffmpeg_dir):
        env["PATH"] = ffmpeg_dir + os.pathsep + env.get("PATH", "")

    cookies_path = os.path.join(BASE_DIR, "cookies.txt")
    cmd = [
        ytdlp,
        "--skip-download",
        "--dump-json",
        "--extractor-args", "youtube:player-client=ios,android,web_creator",
        "--user-agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "--referer", "https://www.youtube.com/",
        "--no-cache-dir"
    ]
    if os.path.exists(cookies_path):
        cmd.extend(["--cookies", cookies_path])
    cmd.append(f"ytsearch30:{keyword}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)
        videos = []
        import time
        now = time.time()

        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                info = json.loads(line)
                ts = info.get("timestamp")
                if not ts:
                    up_str = info.get("upload_date")
                    if up_str:
                        import datetime
                        try:
                            dt = datetime.datetime.strptime(up_str, "%Y%m%d")
                            ts = dt.timestamp()
                        except:
                            pass
                
                if ts:
                    age_sec = now - ts
                    if timeframe == "24h" and age_sec > 86400:
                        continue
                    elif timeframe == "7d" and age_sec > 7 * 86400:
                        continue

                thumb = info.get("thumbnail")
                if not thumb and info.get("thumbnails"):
                    thumb = info.get("thumbnails")[-1]["url"]

                videos.append({
                    "id": info.get("id"),
                    "title": info.get("title"),
                    "url": info.get("webpage_url"),
                    "thumbnail": thumb,
                    "view_count": info.get("view_count", 0),
                    "duration": info.get("duration", 0),
                    "uploader": info.get("uploader", "Unknown"),
                    "upload_date": info.get("upload_date"),
                })
            except Exception as e:
                continue

        videos = sorted(videos, key=lambda x: x["view_count"], reverse=True)
        return jsonify({"videos": videos[:12]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/test-gemini-key", methods=["POST"])
def test_gemini_key():
    data = request.get_json()
    key = data.get("gemini_api_key", "").strip()
    if not key:
        return jsonify({"error": "API Key is empty!"}), 400
    
    # Run a test query to Gemini API
    import urllib.request
    import urllib.error
    import json
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}"
    payload = {
        "contents": [{"parts": [{"text": "Hello, please reply with just the word 'OK'."}]}]
    }
    headers = {"Content-Type": "application/json"}
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=10) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            text = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()
            if len(text) > 0:
                return jsonify({"ok": True, "message": "API Key is valid!"})
            else:
                return jsonify({"error": f"Unexpected response: {text}"}), 400
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8")
            err_data = json.loads(err_body)
            msg = err_data.get("error", {}).get("message", err_body)
            return jsonify({"error": f"Gemini API Error ({e.code}): {msg}"}), 400
        except Exception:
            return jsonify({"error": f"Gemini API Error ({e.code}): {e.reason}"}), 400
    except Exception as e:
        return jsonify({"error": f"Failed to verify API Key: {str(e)}"}), 400


@app.route("/api/test-groq-key", methods=["POST"])
def test_groq_key():
    data = request.get_json()
    key = data.get("groq_api_key", "").strip()
    if not key:
        return jsonify({"error": "API Key is empty!"}), 400
    
    import urllib.request
    import urllib.error
    import json
    url = "https://api.groq.com/openai/v1/models"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }
    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=10) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            if "data" in res_data:
                return jsonify({"ok": True, "message": "Groq API Key is valid!"})
            else:
                return jsonify({"error": "Unexpected response format from Groq"}), 400
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8")
            err_data = json.loads(err_body)
            msg = err_data.get("error", {}).get("message", err_body)
            return jsonify({"error": f"Groq API Error ({e.code}): {msg}"}), 400
        except Exception:
            return jsonify({"error": f"Groq API Error ({e.code}): {e.reason}"}), 400
    except Exception as e:
        return jsonify({"error": f"Failed to verify Groq API Key: {str(e)}"}), 400


@app.route("/api/generate-tts", methods=["POST"])
def generate_tts_api():
    """Generates voiceover using Microsoft Edge-TTS."""
    data = request.get_json() or {}
    text = data.get("text", "").strip()
    voice = data.get("voice", "en-US-GuyNeural").strip()
    output_filename = data.get("filename", "voiceover.mp3").strip()
    
    if not text:
        return jsonify({"error": "Text is required to generate speech!"}), 400
        
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    if not output_filename.endswith((".mp3", ".wav", ".m4a", ".ogg")):
        output_filename += ".mp3"
        
    output_path = os.path.join(OUTPUT_FOLDER, os.path.basename(output_filename))
    
    import asyncio
    import edge_tts
    
    async def run_tts():
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_path)
        
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_tts())
        loop.close()
        
        return jsonify({
            "ok": True,
            "message": "Successfully generated voiceover!",
            "path": output_path,
            "filename": os.path.basename(output_path)
        })
    except Exception as e:
        return jsonify({"error": f"TTS Generation failed: {str(e)}"}), 500


@app.route("/api/open-output-folder", methods=["POST"])
def open_output_folder():
    try:
        data = request.get_json() or {}
        folder = data.get("output_folder", "").strip() or OUTPUT_FOLDER
        folder = os.path.expanduser(folder)
        os.makedirs(folder, exist_ok=True)
        if sys.platform == "darwin":
            subprocess.run(["open", folder])
        elif sys.platform == "win32":
            os.startfile(folder)
        else:
            subprocess.run(["xdg-open", folder])
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/run-floodbot", methods=["POST"])
def run_floodbot():
    if is_running["floodbot"]:
        return jsonify({"error": "FloodBot is already running!"}), 400

    data = request.get_json()
    jobs = data.get("jobs", [])
    gemini_api_key = data.get("gemini_api_key", "").strip()
    groq_api_key = data.get("groq_api_key", "").strip()
    output_folder = sanitize_output_folder(data.get("output_folder", ""))
    push_log(f"📁 Output directory: {output_folder}", "info")

    def worker():
        is_running["floodbot"] = True
        try:
            sys.path.insert(0, BASE_DIR)
            import flood_bot as fb

            os.makedirs(output_folder, exist_ok=True)
            total = len(jobs)

            for i, job in enumerate(jobs, 1):
                push_log(f"{'═'*50}", "info")
                push_log(f"  JOB {i}/{total}", "info")

                video_path   = job.get("video_path", "input.mp4")
                youtube_url  = job.get("youtube_url", "").strip() or None
                use_hook     = job.get("use_hook", False)
                hook_duration= int(job.get("hook_duration", 30))
                start_time   = float(job.get("start", 0)) if not use_hook else None
                end_time     = float(job.get("end", 30))  if not use_hook else None
                caption_lang = job.get("caption_lang", "en")
                watermark    = job.get("watermark", "").strip() or None
                quality      = job.get("quality", "1080p")
                intro_path   = job.get("intro_path", "").strip() or None
                outro_path   = job.get("outro_path", "").strip() or None
                add_music    = job.get("add_music", False)
                music_volume = float(job.get("music_volume", 0.12))
                music_path   = job.get("music_path", "").strip() or None
                auto_bleep   = job.get("auto_bleep", False)
                sensor_blur  = job.get("sensor_blur", False)
                beat_sync    = job.get("beat_sync", False)
                dub_lang     = job.get("dub_lang", "").strip() or None
                top_n        = int(job.get("top_n", 5))
                audio_speed  = float(job.get("audio_speed", 1.03))
                audio_pitch  = float(job.get("audio_pitch", 1.1))
                copyright_free = bool(job.get("copyright_free", False))
                style        = {
                    "color"   : job.get("caption_color",    "yellow"),
                    "size"    : int(job.get("caption_size",  24)),
                    "position": job.get("caption_position", "bottom"),
                    "outline" : job.get("caption_outline",  "black"),
                }
                aspect_ratio = job.get("aspect_ratio", "9:16")
                burn_captions = job.get("burn_captions", True)
                out_name = os.path.join(output_folder, job.get("output", f"short_{i:02d}.mp4"))

                # Redirect print → log queue
                import builtins
                original_print = builtins.print
                def log_print(*args, **kwargs):
                    msg = " ".join(str(a) for a in args)
                    lvl = "error" if "[Error]" in msg else "success" if "[Done]" in msg or "✅" in msg else "info"
                    push_log(msg, lvl)
                builtins.print = log_print

                try:
                    # Download YouTube url once per job
                    local_video_path = video_path
                    if youtube_url:
                        push_log(f"[YT-DLP] Downloading: {youtube_url}", "info")
                        dl = fb.download_youtube(youtube_url, out_dir=".")
                        if dl:
                            local_video_path = dl
                        else:
                            push_log("[Error] Download failed — skipping job.", "error")
                            continue

                    if not os.path.exists(local_video_path):
                        push_log(f"[Error] File not found: {local_video_path}", "error")
                        continue

                    # If multi-clip mode is selected (top_n > 1) and use_hook is True
                    if use_hook and top_n > 1:
                        push_log(f"[Hook] Detecting top {top_n} viral hook moments...", "info")
                        hooks = fb.detect_top_hooks(local_video_path, clip_duration=hook_duration, top_n=top_n, gemini_api_key=gemini_api_key, groq_api_key=groq_api_key)
                        if not hooks:
                            hooks = [(0.0, float(hook_duration), 50.0)]
                        
                        base_out, ext = os.path.splitext(out_name)
                        
                        for h_idx, (s, e, sc) in enumerate(hooks, 1):
                            clip_out_name = f"{base_out}_clip{h_idx}{ext}"
                            push_log(f"🎬 Processing clip {h_idx}/{len(hooks)} ({s:.1f}s → {e:.1f}s) score={sc:.1f}...", "info")
                            
                            ok = fb.process_job(
                                video_path    = local_video_path,
                                start_time    = s,
                                end_time      = e,
                                output_name   = clip_out_name,
                                job_idx       = h_idx,
                                total_jobs    = len(hooks),
                                use_hook      = False,
                                hook_duration = hook_duration,
                                caption_lang  = caption_lang,
                                style         = style,
                                watermark     = watermark,
                                intro_path    = intro_path,
                                outro_path    = outro_path,
                                quality       = quality,
                                youtube_url   = None, # already downloaded
                                aspect_ratio  = aspect_ratio,
                                burn_captions = burn_captions,
                                gemini_api_key= gemini_api_key,
                                add_music     = add_music,
                                music_volume  = music_volume,
                                music_path    = music_path,
                                auto_bleep    = auto_bleep,
                                sensor_blur   = sensor_blur,
                                beat_sync     = beat_sync,
                                dub_lang      = dub_lang,
                                audio_speed   = audio_speed,
                                audio_pitch   = audio_pitch,
                                copyright_free= copyright_free,
                                groq_api_key  = groq_api_key,
                            )
                            push_log(f"✅ Clip {h_idx} {'done' if ok else 'failed'} → {os.path.basename(clip_out_name)}", "success" if ok else "error")
                    else:
                        # Normal single clip execution
                        ok = fb.process_job(
                            video_path    = local_video_path,
                            start_time    = start_time,
                            end_time      = end_time,
                            output_name   = out_name,
                            job_idx       = i,
                            total_jobs    = total,
                            use_hook      = use_hook,
                            hook_duration = hook_duration,
                            caption_lang  = caption_lang,
                            style         = style,
                            watermark     = watermark,
                            intro_path    = intro_path,
                            outro_path    = outro_path,
                            quality       = quality,
                            youtube_url   = None, # already downloaded if needed
                            aspect_ratio  = aspect_ratio,
                            burn_captions = burn_captions,
                            gemini_api_key= gemini_api_key,
                            add_music     = add_music,
                            music_volume  = music_volume,
                            music_path    = music_path,
                            auto_bleep    = auto_bleep,
                            sensor_blur   = sensor_blur,
                            beat_sync     = beat_sync,
                            dub_lang      = dub_lang,
                            audio_speed   = audio_speed,
                            audio_pitch   = audio_pitch,
                            copyright_free= copyright_free,
                            groq_api_key  = groq_api_key,
                        )
                        push_log(f"✅ Job {i} {'done' if ok else 'failed'} → {os.path.basename(out_name)}", "success" if ok else "error")
                finally:
                    builtins.print = original_print

            # Run ManifestBot automatically to generate title/description/tags
            try:
                push_log("📋 Automatically generating upload metadata cards...", "info")
                import manifest_bot as mb
                mb.GEMINI_API_KEY = gemini_api_key
                mb.OUTPUT_FOLDER = output_folder
                mb.run_manifest_bot()
                push_log("✅ Generated titles, descriptions, and hashtags successfully!", "success")
            except Exception as e_mb:
                push_log(f"⚠️ Warning: Auto-metadata generation failed: {e_mb}", "warn")

            push_log("🏁 All jobs complete!", "success")
        except Exception as e:
            push_log(f"❌ Exception: {e}", "error")
        finally:
            is_running["floodbot"] = False

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/evaluate-virality", methods=["POST"])
def evaluate_virality_route():
    """Evaluate virality of a video using Gemini."""
    data = request.get_json() or {}
    video_path   = data.get("video_path", "").strip()
    youtube_url  = data.get("youtube_url", "").strip() or None
    gemini_key   = data.get("gemini_api_key", "").strip()
    groq_api_key = data.get("groq_api_key", "").strip()
    
    if not gemini_key:
        return jsonify({"error": "Gemini API key is required for virality evaluation!"}), 400
        
    try:
        sys.path.insert(0, BASE_DIR)
        import flood_bot as fb
        
        # Handle YouTube download if URL is provided
        if youtube_url:
            push_log(f"[YT-DLP] Downloading video to evaluate virality: {youtube_url}", "info")
            dl = fb.download_youtube(youtube_url, out_dir=".")
            if dl:
                video_path_local = dl
            else:
                return jsonify({"error": "Failed to download YouTube video"}), 500
        else:
            video_path_local = video_path
            
        if not video_path_local or not os.path.exists(video_path_local):
            return jsonify({"error": f"Video file not found at: {video_path_local}"}), 404
            
        push_log(f"[Virality] Evaluating virality for: {os.path.basename(video_path_local)}...", "info")
        evaluation = fb.evaluate_virality(video_path_local, gemini_key, groq_api_key=groq_api_key)
        return jsonify(evaluation)
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


@app.route("/api/detect-hooks", methods=["POST"])
def detect_hooks_api():
    """Detect top N viral hook moments from a video and return timestamps + scores."""
    data = request.get_json() or {}
    video_path   = data.get("video_path", "").strip()
    youtube_url  = data.get("youtube_url", "").strip() or None
    clip_duration= int(data.get("clip_duration", 30))
    top_n        = int(data.get("top_n", 5))
    gemini_key   = data.get("gemini_api_key", "").strip()
    groq_api_key = data.get("groq_api_key", "").strip()

    def worker():
        is_running["floodbot"] = True
        try:
            sys.path.insert(0, BASE_DIR)
            import flood_bot as fb
            import builtins
            orig = builtins.print
            def lp(*a, **k): push_log(" ".join(str(x) for x in a), "info")
            builtins.print = lp
            try:
                if youtube_url:
                    push_log(f"[YT-DLP] Downloading for hook preview: {youtube_url}", "info")
                    dl = fb.download_youtube(youtube_url, out_dir=".")
                    if dl: video_path_local = dl
                    else:
                        push_log("[Error] Download failed", "error"); return
                else:
                    video_path_local = video_path

                hooks = fb.detect_top_hooks(video_path_local, clip_duration=clip_duration, top_n=top_n, gemini_api_key=gemini_key, groq_api_key=groq_api_key)
                for idx, (s, e, sc) in enumerate(hooks, 1):
                    push_log(f"🎯 Hook #{idx}: {s:.1f}s → {e:.1f}s  |  Virality Score: {sc:.1f}", "success")
                push_log(f"✅ Found {len(hooks)} hook moment(s)!", "success")
            finally:
                builtins.print = orig
        except Exception as ex:
            push_log(f"❌ Hook detection error: {ex}", "error")
        finally:
            is_running["floodbot"] = False

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/process-long-video", methods=["POST"])
def process_long_video_api():
    """Process an entire long video with YouTube copyright bypass filters."""
    if is_running["floodbot"]:
        return jsonify({"error": "FloodBot is already running a job!"}), 409

    data = request.get_json() or {}
    video_path    = data.get("video_path", "").strip()
    youtube_url   = data.get("youtube_url", "").strip() or None
    quality       = data.get("quality", "1080p")
    audio_speed   = float(data.get("audio_speed", 1.02))
    audio_pitch   = float(data.get("audio_pitch", 1.05))
    output_folder = sanitize_output_folder(data.get("output_folder", ""))

    def worker():
        is_running["floodbot"] = True
        try:
            sys.path.insert(0, BASE_DIR)
            import flood_bot as fb
            import builtins
            orig = builtins.print
            def lp(*a, **k):
                msg = " ".join(str(x) for x in a)
                lvl = "error" if "[Error]" in msg else "success" if "[Done]" in msg or "✅" in msg else "info"
                push_log(msg, lvl)
            builtins.print = lp
            try:
                local_path = video_path
                if youtube_url:
                    push_log(f"[YT-DLP] Downloading long video: {youtube_url}", "info")
                    dl = fb.download_youtube(youtube_url, out_dir=".")
                    if dl:
                        local_path = dl
                    else:
                        push_log("[Error] YouTube download failed", "error")
                        return

                if not os.path.exists(local_path):
                    push_log(f"[Error] File not found: {local_path}", "error")
                    return

                base_name = os.path.splitext(os.path.basename(local_path))[0]
                out_path = os.path.join(output_folder, f"{base_name}_copyright_free.mp4")
                push_log(f"🛡️ Starting Long Video Copyright-Free Processing → {os.path.basename(out_path)}...", "info")

                ok = fb.process_copyright_free_video(
                    video_path  = local_path,
                    output_name = out_path,
                    quality     = quality,
                    audio_speed = audio_speed,
                    audio_pitch = audio_pitch,
                )
                if ok:
                    push_log(f"✅ Long video copyright-free conversion complete! Saved: {os.path.basename(out_path)}", "success")
                else:
                    push_log("❌ Failed to convert long video.", "error")
            finally:
                builtins.print = orig
        except Exception as ex:
            push_log(f"❌ Long video exception: {ex}", "error")
        finally:
            is_running["floodbot"] = False

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"ok": True})


PRESETS_FILE = os.path.join(BASE_DIR, "branding_presets.json")

@app.route("/api/save-preset", methods=["POST"])
def save_preset():
    """Save a named branding/style preset."""
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Preset name required"}), 400
    presets = {}
    if os.path.exists(PRESETS_FILE):
        try: presets = json.load(open(PRESETS_FILE))
        except: pass
    presets[name] = {k: v for k, v in data.items() if k != "name"}
    json.dump(presets, open(PRESETS_FILE, "w"), indent=2)
    return jsonify({"ok": True, "saved": name})

@app.route("/api/load-presets", methods=["GET"])
def load_presets():
    """Return all saved branding presets."""
    if not os.path.exists(PRESETS_FILE):
        return jsonify({"presets": {}})
    try:
        return jsonify({"presets": json.load(open(PRESETS_FILE))})
    except:
        return jsonify({"presets": {}})

@app.route("/api/delete-preset", methods=["POST"])
def delete_preset():
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    if os.path.exists(PRESETS_FILE):
        try:
            presets = json.load(open(PRESETS_FILE))
            presets.pop(name, None)
            json.dump(presets, open(PRESETS_FILE, "w"), indent=2)
        except: pass
    return jsonify({"ok": True})


@app.route("/api/run-manifestbot", methods=["POST"])
def run_manifestbot():
    if is_running["manifestbot"]:
        return jsonify({"error": "ManifestBot is already running!"}), 400

    data  = request.get_json()
    topic = data.get("topic", "Amazing")
    gemini_api_key = data.get("gemini_api_key", "").strip()
    output_folder = data.get("output_folder", "").strip() or OUTPUT_FOLDER
    output_folder = os.path.expanduser(output_folder)

    def worker():
        is_running["manifestbot"] = True
        try:
            push_log("📋 ManifestBot starting...", "info")
            import manifest_bot as mb
            mb.TOPIC = topic
            mb.OUTPUT_FOLDER = output_folder
            mb.GEMINI_API_KEY = gemini_api_key

            import builtins
            original_print = builtins.print
            def log_print(*args, **kwargs):
                msg = " ".join(str(a) for a in args)
                lvl = "success" if "✅" in msg or "💾" in msg or "📊" in msg or "🏁" in msg else "error" if "❌" in msg else "info"
                push_log(msg, lvl)
            builtins.print = log_print

            try:
                mb.run_manifest_bot()
            finally:
                builtins.print = original_print

            push_log("✅ ManifestBot finished!", "success")
        except Exception as e:
            push_log(f"❌ Exception: {e}", "error")
        finally:
            is_running["manifestbot"] = False

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/upload-video", methods=["POST"])
def upload_video():
    data = request.get_json() or {}
    filename = data.get("filename", "").strip()
    caption = data.get("caption", "").strip()
    token = data.get("token", "").strip()
    platforms = data.get("platforms", [])
    output_folder = data.get("output_folder", "").strip() or OUTPUT_FOLDER
    output_folder = os.path.expanduser(output_folder)
    
    if not filename:
        return jsonify({"error": "No video file specified!"}), 400
    
    video_path = os.path.join(output_folder, filename)
    if not os.path.exists(video_path):
        return jsonify({"error": f"Video file not found at: {video_path}"}), 404

    def worker():
        try:
            push_log(f"🎬 Initializing direct auto-uploader for: {filename}", "info")
            import uploader_bot as ub
            ub.run_uploader(
                video_path = video_path,
                caption = caption,
                token = token,
                platforms = platforms,
                logger_func = push_log
            )
        except Exception as e:
            push_log(f"❌ Auto-Uploader exception: {str(e)}", "error")
            
    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/logs")
def stream_logs():
    def generate():
        yield 'data: {"msg":"🔌 Log stream connected","level":"info","ts":"--:--:--"}\n\n'
        while True:
            try:
                e = log_queue.get(timeout=25)
                yield f"data: {json.dumps(e)}\n\n"
            except queue.Empty:
                yield 'data: {"msg":"ping","level":"ping"}\n\n'
    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})


app.secret_key = "cyber2_secret_key"
_oauth_state = None

@app.route("/api/youtube-setup", methods=["POST"])
def youtube_setup():
    data = request.get_json() or {}
    client_id = data.get("client_id", "").strip()
    client_secret = data.get("client_secret", "").strip()
    if not client_id or not client_secret:
        return jsonify({"error": "Client ID and Client Secret are required!"}), 400
    
    secrets = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": ["http://localhost:8080/callback/youtube"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token"
        }
    }
    try:
        with open(os.path.join(BASE_DIR, "youtube_client_secrets.json"), "w") as f:
            json.dump(secrets, f, indent=2)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/youtube-login")
def youtube_login():
    secrets_path = os.path.join(BASE_DIR, "youtube_client_secrets.json")
    if not os.path.exists(secrets_path):
        return jsonify({"error": "Setup YouTube Client ID & Secret in settings first!"}), 400
        
    from google_auth_oauthlib.flow import Flow
    try:
        flow = Flow.from_client_secrets_file(
            secrets_path,
            scopes=["https://www.googleapis.com/auth/youtube.upload"]
        )
        flow.redirect_uri = "http://localhost:8080/callback/youtube"
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent'
        )
        global _oauth_state
        _oauth_state = state
        return jsonify({"authorization_url": authorization_url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/callback/youtube")
def callback_youtube():
    secrets_path = os.path.join(BASE_DIR, "youtube_client_secrets.json")
    from google_auth_oauthlib.flow import Flow
    try:
        flow = Flow.from_client_secrets_file(
            secrets_path,
            scopes=["https://www.googleapis.com/auth/youtube.upload"]
        )
        flow.redirect_uri = "http://localhost:8080/callback/youtube"
        flow.fetch_token(authorization_response=request.url)
        
        credentials = flow.credentials
        token_data = {
            "token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "token_uri": credentials.token_uri,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "scopes": credentials.scopes
        }
        with open(os.path.join(BASE_DIR, "youtube_token.json"), "w") as f:
            json.dump(token_data, f, indent=2)
            
        return """
        <html>
            <body style="font-family:sans-serif; text-align:center; padding-top:50px; background:#090d16; color:#00ff88;">
                <h1>🎉 YouTube Login Successful!</h1>
                <p>You can close this window now and return to the FloodBot Dashboard.</p>
                <script>
                    setTimeout(function() { window.close(); }, 3000);
                </script>
            </body>
        </html>
        """
    except Exception as e:
        return f"<h1>OAuth Callback Error:</h1><pre>{str(e)}</pre>", 500


@app.route("/api/youtube-status")
def youtube_status():
    token_path = os.path.join(BASE_DIR, "youtube_token.json")
    if not os.path.exists(token_path):
        return jsonify({"logged_in": False})
    
    try:
        with open(token_path, "r") as f:
            token_data = json.load(f)
        if "token" in token_data:
            return jsonify({"logged_in": True, "client_id": token_data.get("client_id")})
    except Exception:
        pass
    return jsonify({"logged_in": False})


@app.route("/api/youtube-upload", methods=["POST"])
def youtube_upload():
    token_path = os.path.join(BASE_DIR, "youtube_token.json")
    if not os.path.exists(token_path):
        return jsonify({"error": "Not logged in to YouTube! Please login first."}), 401
        
    data = request.get_json() or {}
    filename = data.get("filename", "").strip()
    title = data.get("title", "").strip()
    description = data.get("description", "").strip()
    tags = data.get("tags", "")
    privacy = data.get("privacy", "public").strip().lower()
    output_folder = data.get("output_folder", "").strip() or OUTPUT_FOLDER
    output_folder = os.path.expanduser(output_folder)
    
    if not filename:
        return jsonify({"error": "No video file specified!"}), 400
    video_path = os.path.join(output_folder, filename)
    if not os.path.exists(video_path):
        return jsonify({"error": f"Video file not found at: {video_path}"}), 404
        
    def upload_worker():
        try:
            push_log(f"🚀 Starting YouTube upload for: {filename}", "info")
            
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload
            
            # Load credentials
            with open(token_path, "r") as f:
                t = json.load(f)
            
            creds = Credentials(
                token=t["token"],
                refresh_token=t.get("refresh_token"),
                token_uri=t["token_uri"],
                client_id=t["client_id"],
                client_secret=t["client_secret"],
                scopes=t["scopes"]
            )
            
            youtube = build("youtube", "v3", credentials=creds)
            
            tags_list = []
            if isinstance(tags, str):
                tags_list = [tag.strip() for tag in tags.split(",") if tag.strip()]
            elif isinstance(tags, list):
                tags_list = tags
                
            body = {
                "snippet": {
                    "title": title[:100],
                    "description": description[:5000],
                    "tags": tags_list[:50],
                    "categoryId": "22"
                },
                "status": {
                    "privacyStatus": privacy if privacy in ["public", "private", "unlisted"] else "public",
                    "selfDeclaredMadeForKids": False
                }
            }
            
            push_log("[YouTube] Uploading media file...", "info")
            media = MediaFileUpload(video_path, chunksize=1024*1024, resumable=True)
            
            request_call = youtube.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media
            )
            
            response = None
            while response is None:
                status, response = request_call.next_chunk()
                if status:
                    progress = int(status.progress() * 100)
                    push_log(f"📊 YouTube Upload Progress: {progress}% completed", "info")
                    
            video_id = response.get("id")
            push_log(f"✅ Upload successful! Video ID: {video_id}", "success")
            push_log(f"🎬 Video Link: https://youtu.be/{video_id}", "success")
            
        except Exception as ex:
            push_log(f"❌ YouTube Upload failed: {str(ex)}", "error")
            
    threading.Thread(target=upload_worker, daemon=True).start()
    return jsonify({"ok": True})


VERSION_JSON_URL = "https://raw.githubusercontent.com/allex2021/Yoyutbe-SAS-landing-page/main/version.json"

@app.route("/api/check-update")
def check_update():
    """Checks the remote version.json on GitHub."""
    import urllib.request
    try:
        req = urllib.request.Request(
            VERSION_JSON_URL, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode('utf-8'))
        
        remote_ver = data.get("version", "3.0")
        changelog = data.get("changelog", "")
        download_url = data.get("download_url", "")
        
        has_update = remote_ver != CURRENT_VERSION
        return jsonify({
            "current_version": CURRENT_VERSION,
            "remote_version": remote_ver,
            "has_update": has_update,
            "changelog": changelog,
            "download_url": download_url
        })
    except Exception as e:
        return jsonify({
            "current_version": CURRENT_VERSION,
            "has_update": False,
            "error": str(e)
        })

@app.route("/api/trigger-update", methods=["POST"])
def trigger_update():
    """Downloads the latest code ZIP, unpacks it over current files, and restarts."""
    import urllib.request, zipfile, shutil
    try:
        # 1. Get latest download URL
        req = urllib.request.Request(
            VERSION_JSON_URL, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode('utf-8'))
        
        download_url = data.get("download_url")
        if not download_url:
            return jsonify({"success": False, "error": "No download URL found in remote metadata."})
        
        # 2. Download ZIP to temporary file
        temp_zip = "update_temp.zip"
        req_dl = urllib.request.Request(
            download_url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req_dl, timeout=30) as r, open(temp_zip, 'wb') as f:
            shutil.copyfileobj(r, f)
            
        # 3. Unzip files over local workspace safely
        temp_extract_dir = "update_extract_temp"
        os.makedirs(temp_extract_dir, exist_ok=True)
        with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
            zip_ref.extractall(temp_extract_dir)
            
        # Find root folder in extracted files (typically repo-main/)
        source_dir = temp_extract_dir
        for item in os.listdir(temp_extract_dir):
            item_p = os.path.join(temp_extract_dir, item)
            if os.path.isdir(item_p):
                source_dir = item_p
                break
                
        # Copy files over, except output/, .venv/, bin/, and .git/
        for root, dirs, files in os.walk(source_dir):
            rel_path = os.path.relpath(root, source_dir)
            if rel_path == ".":
                rel_path = ""
            dest_dir = os.path.abspath(os.path.join(BASE_DIR, rel_path))
            
            # Skip environment, output, and git data
            if ".venv" in rel_path or "output" in rel_path or "bin" in rel_path or ".git" in rel_path:
                continue
                
            os.makedirs(dest_dir, exist_ok=True)
            for f in files:
                src_file = os.path.join(root, f)
                dest_file = os.path.join(dest_dir, f)
                shutil.copy2(src_file, dest_file)
                
        # 4. Clean up temporary files
        shutil.rmtree(temp_extract_dir)
        if os.path.exists(temp_zip):
            os.remove(temp_zip)
        
        # 5. Automatically schedule restart of Flask app
        def restart_server():
            time.sleep(1)
            os.execv(sys.executable, [sys.executable] + sys.argv)
            
        threading.Thread(target=restart_server).start()
        
        return jsonify({"success": True, "msg": "Software updated successfully! Server is restarting."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


if __name__ == "__main__":
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    port = int(os.environ.get("PORT", 8080))
    print(f"\n🔥 FloodBot v2.0 UI → http://127.0.0.1:{port}\n")
    app.run(debug=False, host="0.0.0.0", port=port, threaded=True)
