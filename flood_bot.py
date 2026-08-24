"""
FloodBot v3.0 — Full Feature Engine
=====================================
New in v3.0:
  • Transcript Cache — same video never re-transcribed (file-based JSON)
  • Multi-clip mode — extract top N hooks from one video automatically
  • Background Music — royalty-free beat auto-mixed via FFmpeg
  • CapCut-style captions — one big word at a time, centered on screen
  • Virality Score — each detected moment shows its score in logs
  • Clip Duration Slider — 15/30/45/60s configurable from UI

Previous (v2.0):
  • YouTube URL download (yt-dlp)
  • Hook Detection — AI finds the best viral hook moment
  • Caption Translation (50+ languages via deep-translator)
  • Caption Style Picker (color, size, position, font)
  • Watermark / Logo burn-in
  • Custom Intro / Outro clip prepend/append
  • Multiple export quality presets (720p, 1080p, 4K)
"""

import os
import sys
import re
import json
import hashlib
import subprocess
from typing import Optional, Tuple, List
import numpy as np
import urllib.parse
import requests

# ── Profanity Check & Censoring ─────────────────────────────────
SWEAR_WORDS = {
    "fuck", "shit", "bitch", "asshole", "bastard", "crap", "damn", "motherfucker", "hell", "piss", "dick", "cunt",
    "bal", "bokachoda", "khanki", "magi", "chudirbhai", "shala", "shuarerbaccha", "gandu", "bainchod", "harami", "choda"
}

def detect_profanity_intervals(segments: list) -> list:
    """Scan Whisper segments for swear words and return list of (start, end) intervals."""
    intervals = []
    for seg in segments:
        if "words" in seg:
            for w in seg["words"]:
                word_clean = "".join(c for c in w["word"].lower() if c.isalnum())
                if word_clean in SWEAR_WORDS:
                    intervals.append((w["start"], w["end"]))
    return intervals

# ── Beat Detection ──────────────────────────────────────────────
def detect_beats(music_path: str) -> list:
    """Extract mono audio transient energy peaks using FFmpeg raw PCM pipe."""
    if not music_path or not os.path.exists(music_path):
        return []
    try:
        ffmpeg_bin = os.path.expanduser("~/bin/ffmpeg")
        if not os.path.exists(ffmpeg_bin):
            ffmpeg_bin = "ffmpeg"
        cmd = [
            ffmpeg_bin, "-y", "-i", music_path,
            "-f", "s16le", "-ac", "1", "-ar", "8000", "-"
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        chunk_size = 1600
        energies = []
        timestamps = []
        t = 0.0
        while True:
            data = proc.stdout.read(chunk_size)
            if not data:
                break
            if len(data) < chunk_size:
                data += b"\x00" * (chunk_size - len(data))
            samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
            energy = np.mean(samples ** 2)
            energies.append(energy)
            timestamps.append(t)
            t += 0.1
        proc.wait()
        
        beats = []
        if len(energies) > 2:
            diffs = np.diff(energies)
            mean_diff = np.mean(diffs)
            std_diff = np.std(diffs)
            threshold = mean_diff + 1.2 * std_diff
            for i in range(1, len(diffs) - 1):
                if diffs[i] > threshold and diffs[i] > diffs[i-1] and diffs[i] > diffs[i+1]:
                    beats.append(timestamps[i])
        return beats
    except Exception as e:
        print(f"[Beat-Sync] Warning: Beat detection failed: {e}")
        return []

# ── Voice Dubbing ───────────────────────────────────────────────
def translate_and_dub(video_path: str, segments: list, target_lang: str, output_audio_path: str) -> bool:
    """Translates transcript segments, generates Google TTS dubs, adjusts speed to match, and merges."""
    try:
        from deep_translator import GoogleTranslator
        translator = GoogleTranslator(source="auto", target=target_lang)
    except Exception as e:
        print(f"[Dubbing] GoogleTranslator failed: {e}")
        return False
        
    print(f"[Dubbing] Dubbing video into language: {target_lang}...")
    temp_files = []
    ffmpeg_inputs = []
    filter_parts = []
    
    # Process up to 30 segments to keep it fast
    for idx, seg in enumerate(segments[:30]):
        text = seg["text"].strip()
        if not text:
            continue
        try:
            translated = translator.translate(text)
            enc_text = urllib.parse.quote(translated[:200])
            tts_url = f"https://translate.google.com/translate_tts?ie=UTF-8&tl={target_lang}&client=tw-ob&q={enc_text}"
            
            temp_tts = f"_tmp_tts_{idx}_{os.getpid()}.mp3"
            r = requests.get(tts_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            if r.status_code == 200:
                with open(temp_tts, "wb") as f:
                    f.write(r.content)
                temp_files.append(temp_tts)
            else:
                continue
                
            orig_dur = max(0.5, seg["end"] - seg["start"])
            tts_dur = None
            
            # Try using ffprobe
            ffprobe = os.path.expanduser("~/bin/ffprobe")
            if not os.path.exists(ffprobe):
                ffprobe = "ffprobe"
            try:
                dur_cmd = [ffprobe, "-v", "quiet", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", temp_tts]
                res = subprocess.run(dur_cmd, capture_output=True, text=True)
                if res.returncode == 0 and res.stdout.strip():
                    tts_dur = float(res.stdout.strip())
            except Exception:
                pass
                
            # Fallback to ffmpeg -i if ffprobe fails or is missing
            if tts_dur is None:
                ffmpeg_bin = os.path.expanduser("~/bin/ffmpeg")
                if not os.path.exists(ffmpeg_bin):
                    ffmpeg_bin = "ffmpeg"
                try:
                    res = subprocess.run([ffmpeg_bin, "-i", temp_tts], capture_output=True, text=True)
                    for line in res.stderr.splitlines():
                        if "Duration:" in line:
                            parts = line.split("Duration:")[1].split(",")[0].strip().split(":")
                            hours = float(parts[0])
                            mins = float(parts[1])
                            secs = float(parts[2])
                            tts_dur = hours * 3600 + mins * 60 + secs
                            break
                except Exception:
                    pass
                    
            if tts_dur is None:
                tts_dur = orig_dur

            
            speed = max(0.5, min(2.0, tts_dur / orig_dur))
            temp_stretched = f"_tmp_stretched_{idx}_{os.getpid()}.wav"
            
            ffmpeg_bin = os.path.expanduser("~/bin/ffmpeg")
            if not os.path.exists(ffmpeg_bin):
                ffmpeg_bin = "ffmpeg"
                
            speed_cmd = [
                ffmpeg_bin, "-y", "-i", temp_tts,
                "-af", f"atempo={speed}",
                temp_stretched
            ]
            subprocess.run(speed_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            temp_files.append(temp_stretched)
            
            delay_ms = int(seg["start"] * 1000)
            ffmpeg_inputs.extend(["-i", temp_stretched])
            input_idx = len(ffmpeg_inputs) // 2 - 1
            filter_parts.append(f"[{input_idx}:a]adelay={delay_ms}|{delay_ms}[a{idx}]")
        except Exception as ex:
            print(f"[Dubbing] Warning: Failed segment {idx}: {ex}")
            
    if not filter_parts:
        return False
        
    mix_labels = "".join(f"[a{i}]" for i in range(len(filter_parts)))
    mix_filter = ";".join(filter_parts) + f";{mix_labels}amix=inputs={len(filter_parts)}:normalize=0[aout]"
    
    ffmpeg_bin = os.path.expanduser("~/bin/ffmpeg")
    if not os.path.exists(ffmpeg_bin):
        ffmpeg_bin = "ffmpeg"
        
    mix_cmd = [ffmpeg_bin, "-y"] + ffmpeg_inputs + ["-filter_complex", mix_filter, "-map", "[aout]", output_audio_path]
    r = subprocess.run(mix_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    
    for f in temp_files:
        if os.path.exists(f):
            os.remove(f)
            
    return r.returncode == 0

# ── Virality Analysis ───────────────────────────────────────────
def evaluate_virality(video_path: str, gemini_api_key: str, groq_api_key: str = "") -> dict:
    """Queries Gemini to grade the hook and transcript virality."""
    if not gemini_api_key:
        return {"error": "API Key is required!"}
    try:
        model = get_model()
        result = _fw_transcribe(model, video_path, language="en", groq_api_key=groq_api_key)
        segments_list = []
        for seg in result["segments"]:
            segments_list.append(f"[{seg['start']:.1f}s - {seg['end']:.1f}s]: {seg['text'].strip()}")
        transcript_text = "\n".join(segments_list)
        
        prompt = (
            f"Analyze this short-form video transcript:\n\n{transcript_text}\n\n"
            f"Provide a JSON response with keys:\n"
            f"- 'virality_score' (0-100)\n"
            f"- 'hook_grade' (e.g. A, B, C, F for first 3 seconds)\n"
            f"- 'positives' (list of strings)\n"
            f"- 'negatives' (list of strings)\n"
            f"- 'actionable_tips' (list of strings)\n"
            f"Return ONLY valid raw JSON."
        )
        res = query_gemini_api(gemini_api_key, prompt, "You are an elite short-form content analyst.")
        if res:
            match = re.search(r"\{.*\}", res, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        return {"error": "Invalid JSON response from Gemini"}
    except Exception as e:
        return {"error": str(e)}


# ── Transcript Cache ───────────────────────────────────────────
_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".transcript_cache")
os.makedirs(_CACHE_DIR, exist_ok=True)

def _cache_key(video_path: str) -> str:
    """SHA256 of file path + mtime + size → unique cache key."""
    stat = os.stat(video_path)
    raw  = f"{os.path.abspath(video_path)}|{stat.st_mtime}|{stat.st_size}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]

def _load_cached_transcript(video_path: str) -> Optional[dict]:
    key  = _cache_key(video_path)
    path = os.path.join(_CACHE_DIR, f"{key}.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            print(f"[Cache] Loaded cached transcript ({key[:8]}...)")
            return data
        except Exception:
            pass
    return None

def _save_cached_transcript(video_path: str, result: dict) -> None:
    key  = _cache_key(video_path)
    path = os.path.join(_CACHE_DIR, f"{key}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
        print(f"[Cache] Saved transcript to cache ({key[:8]}...)")
    except Exception as e:
        print(f"[Cache] Warning: could not save cache: {e}")

# Make sure ~/bin is at the front of PATH so subprocesses can find static ffmpeg
ffmpeg_dir = os.path.expanduser("~/bin")
if os.path.exists(ffmpeg_dir):
    os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")

# faster-whisper: 4-8x faster than openai-whisper, works offline, no API key needed
from faster_whisper import WhisperModel as _FasterWhisperModel

def extract_audio_for_api(video_path: str) -> Optional[str]:
    """Extracts audio channel from video as a highly compressed mono MP3 for API upload."""
    import tempfile
    temp_audio = os.path.join(tempfile.gettempdir(), f"temp_audio_{os.path.basename(video_path)}.mp3")
    if os.path.exists(temp_audio):
        try:
            os.remove(temp_audio)
        except Exception:
            pass
            
    cmd = [
        FFMPEG_BIN, "-y",
        "-i", video_path,
        "-vn",                  # disable video
        "-acodec", "libmp3lame",
        "-ac", "1",             # mono
        "-ar", "16000",         # 16kHz
        "-ab", "32k",           # 32kbps (extremely light!)
        temp_audio
    ]
    try:
        r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=30)
        if r.returncode == 0 and os.path.exists(temp_audio):
            return temp_audio
    except Exception as e:
        print(f"[ExtractAudio Error] {e}")
    return None

def _groq_transcribe(audio_path: str, api_key: str, language: str = "en") -> Optional[dict]:
    """Transcribes audio using Groq Cloud Whisper API with verbose_json response."""
    import requests
    url = "https://api.groq.com/openai/v1/audio/transcriptions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }
    
    # Extract audio if it is a video file or if it's too heavy
    api_audio = audio_path
    is_temp = False
    if not audio_path.lower().endswith((".mp3", ".wav", ".m4a", ".ogg")):
        extracted = extract_audio_for_api(audio_path)
        if extracted:
            api_audio = extracted
            is_temp = True
            
    try:
        with open(api_audio, "rb") as f:
            files = {
                "file": (os.path.basename(api_audio), f, "audio/mp3")
            }
            data = {
                "model": "whisper-large-v3-turbo",
                "response_format": "verbose_json"
            }
            if language:
                data["language"] = language
                
            print(f"[Groq API] Uploading audio channel ({os.path.basename(api_audio)})...")
            r = requests.post(url, headers=headers, files=files, data=data, timeout=60)
            
        if r.status_code == 200:
            res_data = r.json()
            out_segments = []
            
            for idx, seg in enumerate(res_data.get("segments", [])):
                words = seg.get("words", [])
                if not words:
                    seg_text = seg.get("text", "").strip()
                    words_list = seg_text.split()
                    if words_list:
                        seg_dur = seg["end"] - seg["start"]
                        word_dur = seg_dur / len(words_list)
                        for w_idx, w in enumerate(words_list):
                            words.append({
                                "word": w,
                                "start": seg["start"] + w_idx * word_dur,
                                "end": seg["start"] + (w_idx + 1) * word_dur,
                                "probability": 1.0
                            })
                            
                out_segments.append({
                    "id": seg.get("id", idx),
                    "start": seg["start"],
                    "end": seg["end"],
                    "text": seg.get("text", "").strip(),
                    "words": words
                })
                
            print(f"[Groq API] Transcription successful ({len(out_segments)} segments).")
            return {"segments": out_segments}
        else:
            print(f"[Groq API Error] HTTP {r.status_code}: {r.text}")
            return None
    except Exception as e:
        print(f"[Groq API Exception] {e}")
        return None
    finally:
        if is_temp and os.path.exists(api_audio):
            try:
                os.remove(api_audio)
            except Exception:
                pass

def _fw_transcribe(model, audio_path: str, language: str = "en", use_cache: bool = True, groq_api_key: Optional[str] = None) -> dict:
    """Transcribe with Groq API (if key available) or fallback to faster-whisper."""
    if use_cache:
        cached = _load_cached_transcript(audio_path)
        if cached:
            return cached

    if groq_api_key:
        print("[Whisper] Using Groq Cloud API for ultra-fast transcription...")
        result = _groq_transcribe(audio_path, groq_api_key, language)
        if result:
            if use_cache:
                _save_cached_transcript(audio_path, result)
            return result
        print("[Whisper] Groq API transcription failed, falling back to local model...")

    print("[Whisper] Running local faster-whisper transcription on CPU (fast mode)...")
    segments_iter, _info = model.transcribe(
        audio_path, language=language, word_timestamps=True, beam_size=1, condition_on_previous_text=False
    )
    out_segments = []
    for seg in segments_iter:
        words = [{"word": w.word, "start": w.start, "end": w.end, "probability": w.probability}
                 for w in (seg.words or [])]
        out_segments.append({
            "id": seg.id,
            "start": seg.start,
            "end": seg.end,
            "text": seg.text.strip(),
            "words": words,
        })
    result = {"segments": out_segments}
    if use_cache:
        _save_cached_transcript(audio_path, result)
    return result
try:
    from moviepy import VideoFileClip, concatenate_videoclips   # moviepy 2.x
except ImportError:
    from moviepy.editor import VideoFileClip, concatenate_videoclips  # moviepy 1.x

def safe_subclip(clip, start, end):
    if hasattr(clip, "subclipped"):
        return clip.subclipped(start, end)
    return clip.subclip(start, end)

def safe_crop(clip, **kwargs):
    if hasattr(clip, "cropped"):
        return clip.cropped(**kwargs)
    return clip.crop(**kwargs)

def track_and_crop(clip, video_path, start_time, end_time, target_aspect_ratio="9:16"):
    """
    Auto-reframe: tracks faces in the video segment and applies dynamic panning crop.
    """
    import cv2
    print("[AutoReframe] Initialising AI face tracking reframe...")
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    if face_cascade.empty():
        print("[AutoReframe] Warning: Haar cascade XML not loaded! Using center crop.")
        w, h = clip.size
        tw = int(h * 9 / 16) if target_aspect_ratio == "9:16" else min(w, h)
        return safe_crop(clip, x1=(w - tw) // 2, y1=0, width=tw, height=h)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        w, h = clip.size
        tw = int(h * 9 / 16) if target_aspect_ratio == "9:16" else min(w, h)
        return safe_crop(clip, x1=(w - tw) // 2, y1=0, width=tw, height=h)

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920.0
    
    start_frame = int(start_time * fps)
    end_frame = int(end_time * fps)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    # Sample every 0.5 seconds to make it very fast
    step_frames = int(0.5 * fps)
    if step_frames < 1:
        step_frames = 1

    tracks = []
    last_known_ratio_1 = 0.35 # default left-ish for Speaker 1
    last_known_ratio_2 = 0.65 # default right-ish for Speaker 2
    
    for f_idx in range(start_frame, min(end_frame, total_frames), step_frames):
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
        ret, frame = cap.read()
        if not ret:
            break
        
        t = (f_idx - start_frame) / fps
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Scale gray image down to make detection extremely fast
        scale = 300.0 / gray.shape[1] if gray.shape[1] > 300 else 1.0
        if scale < 1.0:
            gray = cv2.resize(gray, (0, 0), fx=scale, fy=scale)
            
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=4, minSize=(30, 30))
        
        if len(faces) >= 2:
            # Sort by horizontal position x so Speaker 1 is left and Speaker 2 is right
            faces_sorted = sorted(faces[:2], key=lambda f: f[0])
            ratio_1 = (((faces_sorted[0][0] + faces_sorted[0][2]/2) / scale) / width)
            ratio_2 = (((faces_sorted[1][0] + faces_sorted[1][2]/2) / scale) / width)
            last_known_ratio_1 = ratio_1
            last_known_ratio_2 = ratio_2
            tracks.append((t, ratio_1, ratio_2))
        elif len(faces) == 1:
            ratio_1 = (((faces[0][0] + faces[0][2]/2) / scale) / width)
            last_known_ratio_1 = ratio_1
            # Keep speaker 2 at opposite side relative to speaker 1, or their last known position
            tracks.append((t, ratio_1, last_known_ratio_2))
        else:
            # Feature 1: Keep last known face coordinates instead of jumping to 0.5 center!
            tracks.append((t, last_known_ratio_1, last_known_ratio_2))

    cap.release()

    if not tracks:
        w, h = clip.size
        if target_aspect_ratio == "podcast_split":
            tw = int(h * 9 / 16)
            x1_1 = 0
            x1_2 = w - tw if w > tw else 0
            y1 = h // 4
            def fallback_filter(get_frame, t):
                frame = get_frame(t)
                top_half = frame[y1:y1+h//2, x1_1:x1_1+tw]
                bottom_half = frame[y1:y1+h//2, x1_2:x1_2+tw]
                import numpy as np
                return np.vstack((top_half, bottom_half))
            if hasattr(clip, "transform"):
                return clip.transform(fallback_filter)
            return clip.fl(fallback_filter)
        else:
            tw = int(h * 9 / 16) if target_aspect_ratio == "9:16" else min(w, h)
            return safe_crop(clip, x1=(w - tw) // 2, y1=0, width=tw, height=h)

    # Smooth coordinates using rolling average (window size of 5 points ~ 2.5 seconds)
    times = [pt[0] for pt in tracks]
    ratios_1 = [pt[1] for pt in tracks]
    ratios_2 = [pt[2] for pt in tracks]
    
    smoothed_ratios_1 = []
    smoothed_ratios_2 = []
    window = 5
    for i in range(len(tracks)):
        start_idx = max(0, i - window // 2)
        end_idx = min(len(tracks), i + window // 2 + 1)
        sub1 = ratios_1[start_idx:end_idx]
        sub2 = ratios_2[start_idx:end_idx]
        smoothed_ratios_1.append(sum(sub1) / len(sub1))
        smoothed_ratios_2.append(sum(sub2) / len(sub2))

    def get_ratios_at(t):
        if t <= times[0]:
            return smoothed_ratios_1[0], smoothed_ratios_2[0]
        if t >= times[-1]:
            return smoothed_ratios_1[-1], smoothed_ratios_2[-1]
        for i in range(len(times) - 1):
            if times[i] <= t <= times[i+1]:
                t0, t1 = times[i], times[i+1]
                r1_0, r1_1 = smoothed_ratios_1[i], smoothed_ratios_1[i+1]
                r2_0, r2_1 = smoothed_ratios_2[i], smoothed_ratios_2[i+1]
                ratio1 = r1_0 + (r1_1 - r1_0) * (t - t0) / (t1 - t0)
                ratio2 = r2_0 + (r2_1 - r2_0) * (t - t0) / (t1 - t0)
                return ratio1, ratio2
        return 0.5, 0.5

    w, h = clip.size

    def frame_filter(get_frame, t):
        frame = get_frame(t)
        ratio_1, ratio_2 = get_ratios_at(t)
        
        if target_aspect_ratio == "9:16":
            tw = int(h * 9 / 16)
            center_x = int(ratio_1 * w)
            x1 = center_x - tw // 2
            if x1 < 0: x1 = 0
            if x1 + tw > w: x1 = w - tw
            return frame[:, x1:x1+tw]
        elif target_aspect_ratio == "1:1":
            tw = min(w, h)
            center_x = int(ratio_1 * w)
            x1 = center_x - tw // 2
            if x1 < 0: x1 = 0
            if x1 + tw > w: x1 = w - tw
            y1 = (h - tw) // 2
            return frame[y1:y1+tw, x1:x1+tw]
        elif target_aspect_ratio == "podcast_split":
            target_w = int(h * 9 / 16)
            
            # Crop Speaker 1 (Top half)
            center_x_1 = int(ratio_1 * w)
            x1_1 = center_x_1 - target_w // 2
            if x1_1 < 0: x1_1 = 0
            if x1_1 + target_w > w: x1_1 = w - target_w
            
            # Crop Speaker 2 (Bottom half)
            center_x_2 = int(ratio_2 * w)
            x1_2 = center_x_2 - target_w // 2
            if x1_2 < 0: x1_2 = 0
            if x1_2 + target_w > w: x1_2 = w - target_w
            
            y1 = h // 4
            y2 = y1 + h // 2
            top_half = frame[y1:y2, x1_1:x1_1+target_w]
            bottom_half = frame[y1:y2, x1_2:x1_2+target_w]
            
            import numpy as np
            return np.vstack((top_half, bottom_half))
            
        return frame

    if hasattr(clip, "transform"):
        return clip.transform(frame_filter)
    return clip.fl(frame_filter)

from deep_translator import GoogleTranslator

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

def find_ffprobe() -> str:
    ext = ".exe" if sys.platform == "win32" else ""
    local_bin = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin")
    
    if getattr(sys, 'frozen', False):
        meipass_ffprobe = os.path.join(sys._MEIPASS, f"ffprobe{ext}")
        if os.path.exists(meipass_ffprobe):
            return meipass_ffprobe

    for p in [
        os.path.join(local_bin, f"ffprobe{ext}"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), f"ffprobe{ext}"),
        os.path.expanduser(f"~/bin/ffprobe{ext}"),
    ]:
        if os.path.exists(p):
            return p
            
    import shutil
    path_bin = shutil.which("ffprobe")
    if path_bin:
        return path_bin
        
    return f"ffprobe{ext}"

FFMPEG_BIN  = find_ffmpeg()
FFPROBE_BIN = find_ffprobe()
OUTPUT_FOLDER = "output"

# ── Hook keywords that signal a viral opening ──────────────────
HOOK_KEYWORDS = [
    "never", "secret", "shocking", "wait", "watch this", "you won't believe",
    "truth", "mistake", "warning", "stop", "listen", "actually", "nobody",
    "everyone", "always", "hack", "trick", "why", "how", "what if",
    "imagine", "fact", "crazy", "insane", "real", "honest", "exposed",
    "reveal", "finally", "broke", "change", "wrong", "right", "biggest",
    "worst", "best", "only", "first", "last", "ever", "never seen",
    "most people", "this is why", "here's why", "the reason",
]

# ── Shared faster-whisper model ───────────────────────────────
_whisper_model = None

def get_model():
    global _whisper_model
    if _whisper_model is None:
        print("[faster-whisper] Loading 'base' model (int8, CPU)...")
        _whisper_model = _FasterWhisperModel("base", device="cpu", compute_type="int8")
        print("[faster-whisper] Model ready.")
    return _whisper_model


# ══════════════════════════════════════════════════════════════
#  FEATURE 1 — YouTube URL Download
# ══════════════════════════════════════════════════════════════

def download_youtube(url: str, out_dir: str = ".") -> Optional[str]:
    """
    Downloads a YouTube video using yt-dlp.
    Returns the local file path, or None on failure.
    """
    # Prefer local bin/yt-dlp, local venv yt-dlp, fallback to Windows scripts, user locations, then PATH
    ext = ".exe" if sys.platform == "win32" else ""
    local_bin = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin")
    
    ytdlp = os.path.abspath(os.path.join(local_bin, f"yt-dlp{ext}"))
    if not os.path.exists(ytdlp):
        ytdlp = os.path.abspath(os.path.join(os.path.dirname(__file__), ".venv", "bin", "yt-dlp"))
    if not os.path.exists(ytdlp):
        ytdlp = os.path.abspath(os.path.join(os.path.dirname(__file__), ".venv", "Scripts", "yt-dlp.exe"))
    if not os.path.exists(ytdlp):
        ytdlp = os.path.expanduser("~/Library/Python/3.9/bin/yt-dlp")
    if not os.path.exists(ytdlp):
        ytdlp = f"yt-dlp{ext}"

    # Setup environment with ~/bin and common Mac binary paths in PATH
    env = os.environ.copy()
    paths = [
        os.path.expanduser("~/bin"),
        "/usr/local/bin",
        "/opt/homebrew/bin", # Homebrew on Apple Silicon
    ]
    path_addons = [p for p in paths if os.path.exists(p)]
    if path_addons:
        env["PATH"] = os.pathsep.join(path_addons) + os.pathsep + env.get("PATH", "")

    out_template = os.path.join(out_dir, "%(title).60s.%(ext)s")
    cmd_base = [
        ytdlp,
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "-o", out_template,
        "--print", "after_move:filepath",
        "--no-playlist",
    ]

    # Explicitly configure Node.js runtime if available to prevent warning messages
    node_exe = None
    for p in ["/usr/local/bin/node", "/opt/homebrew/bin/node"]:
        if os.path.exists(p):
            node_exe = p
            break
    if node_exe:
        cmd_base.extend(["--js-runtimes", f"node:{node_exe}"])

    # Anti-bot bypass configurations (resolves HTTP 403 Forbidden)
    cmd_base.extend([
        "--extractor-args", "youtube:player-client=ios,android,web_creator",
        "--user-agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "--referer", "https://www.youtube.com/",
        "--no-cache-dir",
    ])
    
    cookies_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")
    if os.path.exists(cookies_path):
        cmd_base.extend(["--cookies", cookies_path])
        print(f"[YT-DLP] Prioritising cookies.txt session file: {cookies_path}")

    cookie_fallback = [
        ["--cookies-from-browser", "chrome"],
        ["--cookies-from-browser", "safari"],
        ["--cookies-from-browser", "firefox"],
        [] # raw download fallback
    ]

    for opt in cookie_fallback:
        cmd = cmd_base + opt + [url]
        browser_label = f" (using cookies from {opt[1]})" if opt else ""
        print(f"[YT-DLP] Trying download{browser_label}...")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, env=env)
            if result.returncode == 0:
                lines = [l.strip() for l in result.stdout.splitlines() if l.strip().endswith(".mp4")]
                if lines:
                    raw_path = lines[-1]
                    d_dir = os.path.dirname(raw_path) or out_dir
                    b_name = os.path.basename(raw_path)
                    safe_name = re.sub(r'[^a-zA-Z0-9_\-.]', '_', b_name)
                    safe_path = os.path.join(d_dir, safe_name)
                    if raw_path != safe_path and os.path.exists(raw_path):
                        try:
                            os.replace(raw_path, safe_path)
                            return safe_path
                        except Exception:
                            return raw_path
                    return raw_path
            else:
                # Log stderr warning to help diagnose if needed
                print(f"[YT-DLP Warning] Attempt failed: {result.stderr.strip()[:180]}...")
        except Exception as e:
            print(f"[YT-DLP Exception] {e}")

    print("[YT-DLP Error] All YouTube download attempts failed. YouTube bot detection may have blocked this IP. Please upload your video directly or provide cookies.txt.")
    return None


# ══════════════════════════════════════════════════════════════
#  FEATURE 2 — Hook Detection
# ══════════════════════════════════════════════════════════════

def _score_segment(text: str, start: float, audio_rms: float) -> float:
    """
    Scores a transcript segment for 'hookiness'.
    Higher = more likely to be a viral hook.
    """
    score = 0.0
    low   = text.lower()

    # Keyword hits
    for kw in HOOK_KEYWORDS:
        if kw in low:
            score += 2.0

    # Questions and exclamations
    if "?" in text:  score += 3.0
    if "!" in text:  score += 1.5

    # Short punchy sentences (< 10 words)
    words = low.split()
    if len(words) < 10: score += 1.5
    if len(words) < 6:  score += 1.0

    # Numbers signal data/facts
    if re.search(r'\b\d+\b', text): score += 1.5

    # Audio energy boost
    score += audio_rms * 5.0

    # Prefer earlier in video (first 30%)
    if start < 60:   score += 2.0
    elif start < 120: score += 1.0

    return score


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

def detect_hook(video_path: str, clip_duration: int = 30, gemini_api_key: str = "", groq_api_key: str = "") -> Tuple[float, float]:
    """Analyses the video audio + transcript to find the best viral hook moment.
    Returns (hook_start, hook_end) in seconds. Falls back to (0, clip_duration) if detection fails."""
    try:
        print("[Hook] Analysing video for viral hook moment...")
        clip = VideoFileClip(video_path)
        total_dur = clip.duration
        audio = clip.audio

        # Sample RMS per second
        rms_per_sec: list[float] = []
        step = 1.0
        t = 0.0
        while t < min(total_dur, 300):  # analyse first 5 min max
            try:
                chunk = safe_subclip(audio, t, min(t + step, total_dur))
                arr = chunk.to_soundarray(fps=8000).astype(np.float32)
                rms = float(np.sqrt(np.mean(arr ** 2)))
            except Exception:
                rms = 0.0
            rms_per_sec.append(rms)
            t += step
        clip.close()

        # Transcribe with faster-whisper
        model = get_model()
        result = _fw_transcribe(model, video_path, language="en", groq_api_key=groq_api_key)

        # Gemini-based hook detection
        ENABLE_GEMINI = True  # Set to False to skip Gemini and use heuristic only

        if ENABLE_GEMINI and gemini_api_key:
            print("[Hook] Sending transcript to Gemini for viral hook detection...")
            segments_list = []
            for seg in result["segments"]:
                segments_list.append(f"[{seg['start']:.1f}s - {seg['end']:.1f}s]: {seg['text'].strip()}")
            transcript_text = "\n".join(segments_list)

            prompt = (
                f"You are an elite YouTube Shorts growth specialist. Analyze this transcript to locate the single most viral "
                f"segment of approximately {clip_duration} seconds. "
                f"Prioritize: \n"
                f"- High-retention hooks: shocking claims, deep curiosity loops, emotional peaks, or strong statements.\n"
                f"- Accurate word boundaries: the start_time and end_time MUST align with the exact start of a sentence and must not cut off mid-word.\n"
                f"- Ideal length: try to capture a full coherent point or story beat close to {clip_duration} seconds.\n\n"
                f"Output strictly a JSON object with keys \"start_time\" (float), \"end_time\" (float), and \"reason\" (string).\n\n"
                f"Transcript:\n{transcript_text}"
            )
            gemini_response = query_gemini_api(gemini_api_key, prompt, "You are a professional AI video editor specializing in YouTube Shorts.")
            if gemini_response:
                import re, json as _json
                match = re.search(r"\{.*\}", gemini_response, re.DOTALL)
                if match:
                    try:
                        data = _json.loads(match.group(0))
                        g_start = float(data["start_time"])
                        g_end = float(data["end_time"])
                        print(f"[Hook] Gemini detected best hook at {g_start:.1f}s → {g_end:.1f}s because: {data.get('reason')}")
                        return g_start, min(g_end, total_dur)
                    except Exception as e_parse:
                        print(f"[Hook] Failed to parse Gemini response: {e_parse}. Falling back to heuristic.")
                else:
                    print("[Hook] Gemini response had no JSON. Falling back to heuristic.")
            else:
                print("[Hook] Gemini API returned no response or failed. Falling back to heuristic.")
        elif not gemini_api_key:
            print("[Hook] Gemini API key not provided. Skipping Gemini call.")
        else:
            print("[Hook] Gemini usage disabled via ENABLE_GEMINI flag. Using heuristic fallback.")

        # Heuristic-based fallback
        best_score = -1.0
        best_start = 0.0
        best_end   = float(clip_duration)

        # Scan the video using a rolling window of clip_duration
        step_scan = 1.0
        max_scan_time = max(0.0, total_dur - clip_duration)

        t_scan = 0.0
        while t_scan <= max_scan_time:
            window_start = t_scan
            window_end = t_scan + clip_duration

            window_score = 0.0
            for seg in result["segments"]:
                seg_start = seg["start"]
                if window_start <= seg_start <= window_end:
                    seg_text = seg["text"]
                    idx = int(seg_start)
                    rms = rms_per_sec[idx] if idx < len(rms_per_sec) else 0.0

                    # Score segment using keywords, length, questions
                    seg_score = _score_segment(seg_text, seg_start, rms)
                    window_score += seg_score

                    # Bonus if the window starts exactly near the beginning of this segment (within 2 seconds)
                    if abs(seg_start - window_start) <= 2.0:
                        window_score += seg_score * 0.5

            # Penalize silence within the window
            idx_start = int(window_start)
            idx_end = int(window_end)
            window_rms = rms_per_sec[idx_start:idx_end]
            if window_rms:
                avg_rms = sum(window_rms) / len(window_rms)
                if avg_rms < 0.01:
                    window_score -= 10.0

            if window_score > best_score:
                best_score = window_score
                best_start = window_start
                best_end   = window_end

            t_scan += step_scan

        best_end = min(best_end, total_dur)
        print(f"[Hook] Best hook detected at {best_start:.1f}s → {best_end:.1f}s  (score={best_score:.1f})")
        return best_start, best_end

    except Exception as e:
        print(f"[Hook] Detection failed ({e}), using start of video.")
        return 0.0, float(clip_duration)


def detect_top_hooks(
    video_path: str,
    clip_duration: int = 30,
    top_n: int = 3,
    gemini_api_key: str = "",
    groq_api_key: str = "",
) -> List[Tuple[float, float, float]]:
    """
    Detects the top N non-overlapping viral hook moments.
    Returns list of (start, end, score) sorted by score descending.
    """
    try:
        print(f"[Hook] Scanning for top {top_n} hook moments...")
        clip = VideoFileClip(video_path)
        total_dur = clip.duration
        audio = clip.audio

        rms_per_sec: list[float] = []
        step = 1.0
        t = 0.0
        while t < min(total_dur, 300):
            try:
                chunk = safe_subclip(audio, t, min(t + step, total_dur))
                arr = chunk.to_soundarray(fps=8000).astype(np.float32)
                rms = float(np.sqrt(np.mean(arr ** 2)))
            except Exception:
                rms = 0.0
            rms_per_sec.append(rms)
            t += step
        clip.close()

        model = get_model()
        result = _fw_transcribe(model, video_path, language="en", groq_api_key=groq_api_key)

        # Score every window
        all_windows: List[Tuple[float, float, float]] = []
        max_scan = max(0.0, total_dur - clip_duration)
        t_scan = 0.0
        while t_scan <= max_scan:
            ws, we = t_scan, t_scan + clip_duration
            score = 0.0
            for seg in result["segments"]:
                if ws <= seg["start"] <= we:
                    idx = int(seg["start"])
                    rms = rms_per_sec[idx] if idx < len(rms_per_sec) else 0.0
                    score += _score_segment(seg["text"], seg["start"], rms)
            idx_s, idx_e = int(ws), int(we)
            wr = rms_per_sec[idx_s:idx_e]
            if wr and (sum(wr)/len(wr)) < 0.01:
                score -= 10.0
            all_windows.append((ws, min(we, total_dur), score))
            t_scan += 1.0

        # Pick top N non-overlapping windows with minimum gap and score filter
        all_windows.sort(key=lambda x: x[2], reverse=True)
        selected: List[Tuple[float, float, float]] = []
        MIN_GAP = 15.0  # at least 15s between clips
        for ws, we, sc in all_windows:
            if sc < 0:  # skip low-quality / silent windows
                continue
            # Check no overlap AND enforce minimum gap between clips
            too_close = any(
                not (we + MIN_GAP <= s or ws >= e + MIN_GAP)
                for s, e, _ in selected
            )
            if not too_close:
                selected.append((ws, we, sc))
                print(f"[Hook] #{len(selected)} → {ws:.1f}s–{we:.1f}s  score={sc:.1f}")
            if len(selected) >= top_n:
                break

        # If we don't have enough clips, fill up evenly spaced from remaining video
        if len(selected) < top_n and total_dur >= clip_duration:
            print(f"[Hook] Only {len(selected)}/{top_n} hooks found — filling with evenly-spaced clips...")
            step_fill = max(clip_duration, (total_dur - clip_duration) / max(top_n, 1))
            t_fill = 0.0
            while len(selected) < top_n and t_fill + clip_duration <= total_dur:
                ws_f, we_f = t_fill, t_fill + clip_duration
                too_close = any(
                    not (we_f + MIN_GAP <= s or ws_f >= e + MIN_GAP)
                    for s, e, _ in selected
                )
                if not too_close:
                    selected.append((ws_f, min(we_f, total_dur), 0.0))
                    print(f"[Hook] #{len(selected)} (fallback) → {ws_f:.1f}s–{we_f:.1f}s")
                t_fill += step_fill

        if not selected:
            selected = [(0.0, float(clip_duration), 0.0)]
        return selected

    except Exception as ex:
        print(f"[Hook] Multi-hook detection failed ({ex}), returning single clip.")
        return [(0.0, float(clip_duration), 0.0)]


def format_float(val: float) -> str:
    """Format float with dot decimal separator regardless of system locale."""
    return f"{val:.6f}".replace(",", ".")


def format_time(secs: float) -> str:
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    s = int(secs % 60)
    ms = int((secs % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# Emojis mapping for kinetic styling
EMOJI_MAP = {
    "SECRET": "🤫", "NEVER": "🚫", "SHOCK": "😱", "SHOCKING": "😱", "WAR": "⚔️",
    "MONEY": "💰", "CASH": "💵", "RICH": "🤑", "ROCKET": "🚀", "FIRE": "🔥",
    "MIND": "🧠", "BRAIN": "🧠", "TRUTH": "👁️", "WARNING": "⚠️", "STOP": "🛑",
    "LOVE": "❤️", "HEART": "❤️", "BABY": "👶", "KING": "👑", "QUEEN": "👑",
    "GOLD": "🪙", "STAR": "⭐", "CRAZY": "🤪", "INSANE": "🤯", "ALERT": "🚨",
    "POLICE": "🚨", "PHONE": "📱", "MOBILE": "📱", "TIME": "⏱️", "WATCH": "⌚",
    "SUCCESS": "🏆", "WIN": "🏆", "LOSE": "❌", "WRONG": "❌", "RIGHT": "✅",
    "OK": "👌", "YES": "👍", "NO": "👎", "DEATH": "💀", "DEAD": "💀",
    "SCAM": "💸", "LIE": "🤥", "FAKE": "🤥", "TRICK": "🎭", "MAGIC": "🪄",
}


def generate_srt(
    video_path: str,
    srt_path: Optional[str] = None,
    transcript_path: Optional[str] = None,
    lang: str = "en",
    style: Optional[dict] = None,
    beat_times: Optional[List[float]] = None,
    groq_api_key: str = "",
) -> None:
    """Transcribes and writes a kinetic SRT file with karaoke word highlights and optional beat-sync snapping."""
    model  = get_model()
    result = _fw_transcribe(model, video_path, language="en", groq_api_key=groq_api_key)

    translator = None
    if lang != "en" and srt_path:
        try:
            translator = GoogleTranslator(source="en", target=lang)
            print(f"[Translate] Translation enabled → {lang}")
        except Exception as e:
            print(f"[Translate] Warning: {e}")

    if srt_path:
        words_list = []
        for seg in result["segments"]:
            if "words" in seg:
                words_list.extend(seg["words"])

        # Group words list into chunks of 3 words for high readability and retention
        chunk_size = 3
        chunks = [words_list[i : i + chunk_size] for i in range(0, len(words_list), chunk_size)]

        with open(srt_path, "w", encoding="utf-8") as f:
            idx = 1
            for chunk in chunks:
                for current_idx, current_word in enumerate(chunk):
                    start_time_val = current_word["start"]
                    
                    # Beat-sync snapping: align caption word highlights directly to the background music's beats
                    if beat_times:
                        closest_beat = min(beat_times, key=lambda b: abs(b - start_time_val))
                        if abs(closest_beat - start_time_val) < 0.35:
                            start_time_val = closest_beat
                    
                    # Stay on screen until next word starts, or end of current word if last in chunk
                    if current_idx < len(chunk) - 1:
                        end_time_val = chunk[current_idx + 1]["start"]
                    else:
                        end_time_val = current_word["end"]

                    if end_time_val <= start_time_val:
                        end_time_val = start_time_val + 0.3

                    # Build phrase text with current word highlighted in style color
                    parts = []
                    for i, w in enumerate(chunk):
                        raw_text = w["word"].upper().strip()
                        clean_w = "".join(c for c in raw_text if c.isalnum())
                        emoji = EMOJI_MAP.get(clean_w, "")
                        if emoji:
                            raw_text = f"{emoji} {raw_text}"

                        if i == current_idx:
                            # Highlight color from style (default: yellow)
                            color_hex = "#FFFF00"
                            if style and "color" in style:
                                color_map = {
                                    "yellow": "#FFFF00", "white": "#FFFFFF", "red": "#FF0000",
                                    "green": "#00FF00", "blue": "#0000FF", "pink": "#FF69B4",
                                    "orange": "#FFA500"
                                }
                                color_hex = color_map.get(style["color"].lower(), "#FFFF00")
                            parts.append(f"<font color=\"{color_hex}\"><b>{raw_text}</b></font>")
                        else:
                            parts.append(raw_text)

                    text_line = " ".join(parts)
                    if translator:
                        try:
                            text_line = translator.translate(text_line).upper()
                        except Exception:
                            pass

                    f.write(f"{idx}\n{format_time(start_time_val)} --> {format_time(end_time_val)}\n{text_line}\n\n")
                    idx += 1

    if transcript_path:
        with open(transcript_path, "w", encoding="utf-8") as f:
            for seg in result["segments"]:
                f.write(f"[{seg['start']:.1f} - {seg['end']:.1f}]: {seg['text'].strip()}\n")


# ══════════════════════════════════════════════════════════════
#  FEATURE 4 — FFmpeg Final Render (style + watermark + quality)
# ══════════════════════════════════════════════════════════════

QUALITY_PRESETS = {
    "720p" : {"scale": "406:720",  "crf": "23"},
    "1080p": {"scale": "608:1080", "crf": "20"},
    "4K"   : {"scale": "1216:2160","crf": "18"},
    "original": {"scale": None,    "crf": "20"},
}

CAPTION_COLORS = {
    "yellow": "&H00FFFF",
    "white" : "&H00FFFFFF",
    "red"   : "&H0000FF",
    "green" : "&H0000FF00",
    "blue"  : "&H00FF0000",
    "pink"  : "&H00FF69B4",
    "orange": "&H000080FF",
}

CAPTION_POSITIONS = {
    "bottom": "2",
    "middle": "10",
    "top"   : "6",
}


# ── Background Music ──────────────────────────────────────────────────────────
BUILTIN_BEATS = [
    # Royalty-free lofi/trap style notes (sine wave generated on-the-fly if no file given)
]

def ffmpeg_add_music(
    video_path: str,
    output_path: str,
    music_path: Optional[str] = None,
    music_volume: float = 0.12,
    original_volume: float = 1.0,
) -> bool:
    if not music_path or not os.path.exists(music_path):
        dur_cmd = [FFMPEG_BIN, "-i", video_path]
        r = subprocess.run(dur_cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True)
        dur = 30.0
        for line in r.stderr.splitlines():
            if "Duration" in line:
                try:
                    t = line.split("Duration:")[1].split(",")[0].strip()
                    h, m, s = t.split(":")
                    dur = float(h)*3600 + float(m)*60 + float(s)
                except Exception:
                    pass

        tmp_beat = f"_tmp_beat_{os.getpid()}.wav"
        beat_cmd = [
            FFMPEG_BIN, "-y",
            "-f", "lavfi",
            "-i", f"sine=frequency=432:duration={dur}",
            "-af", f"volume=0.05",
            tmp_beat,
        ]
        subprocess.run(beat_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        music_path = tmp_beat
        cleanup_beat = True
    else:
        cleanup_beat = False

    tmp_out = output_path + "_music_tmp.mp4"
    cmd = [
        FFMPEG_BIN, "-y",
        "-i", video_path,
        "-stream_loop", "-1", "-i", music_path,
        "-filter_complex",
        f"[0:a]volume={original_volume}[orig];[1:a]volume={music_volume}[music];[orig][music]amix=inputs=2:duration=first[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        tmp_out,
    ]
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if cleanup_beat and os.path.exists(music_path):
        os.remove(music_path)

    if r.returncode == 0:
        os.replace(tmp_out, output_path)
        return True
    else:
        print(f"[Music] Warning: FFmpeg music mix failed: {r.stderr[-300:]}")
        if os.path.exists(tmp_out):
            os.remove(tmp_out)
        return False


def ffmpeg_render(
    input_mp4   : str,
    srt_path    : Optional[str],
    output_name : str,
    style       : dict,
    watermark   : Optional[str] = None,
    intro_path  : Optional[str] = None,
    outro_path  : Optional[str] = None,
    quality     : str = "1080p",
    censored_intervals: Optional[List[Tuple[float, float]]] = None,
    audio_speed : float = 1.03,
    audio_pitch : float = 1.1,
    copyright_free: bool = False,
) -> bool:
    """
    Final FFmpeg render with:
     - hflip + color grade
     - Subtitle burn (custom style)
     - Optional watermark text
     - Optional scale to quality preset
     - Optional mouth censorship bar and text
     - Optional profanity audio muting (bleeping)
     - Audio fingerprint shift + metadata wipe
     - Optional copyright-free transforms (hue, zoom, speed, audio EQ)
    """
    color     = CAPTION_COLORS.get(style.get("color","yellow"), "&H00FFFF")
    size      = style.get("size", 24)
    position  = CAPTION_POSITIONS.get(style.get("position","bottom"), "2")
    outline   = style.get("outline", "black")
    out_col   = "&H00FFFFFF" if outline == "white" else "&H000000"
    border    = "0" if outline == "none" else "1"

    vf_parts = [
        "hflip",
        "vibrance=intensity=0.1",
        "eq=brightness=0.02:contrast=1.03",
    ]

    # ── Copyright-Free extra video transforms ──
    if copyright_free:
        vf_parts.extend([
            "hue=h=3",                                    # slight hue rotation
            "crop=iw*0.98:ih*0.98:(iw-iw*0.98)/2:(ih-ih*0.98)/2,scale=iw/0.98:ih/0.98",  # 2% zoom crop
            "setpts=1.01*PTS",                            # 1% speed reduction
        ])

    # Swear word censoring bar
    if censored_intervals:
        for start, end in censored_intervals:
            vf_parts.append(
                f"drawbox=x=iw*0.2:y=ih*0.53:w=iw*0.6:h=ih*0.07:color=black:t=fill:enable='between(t,{start},{end})'"
            )
            vf_parts.append(
                f"drawtext=text='CENSORED':fontcolor=red:fontsize=20:x=(w-tw)/2:y=ih*0.54:enable='between(t,{start},{end})'"
            )

    if srt_path and os.path.exists(srt_path):
        abs_srt = os.path.abspath(srt_path).replace("\\", "/").replace(":", "\\:")
        sub_filter = (
            f"subtitles='{abs_srt}':force_style='"
            f"Alignment={position},"
            f"FontSize={size},"
            f"PrimaryColour={color},"
            f"OutlineColour={out_col},"
            f"BorderStyle={border},"
            f"Outline=2'"
        )
        vf_parts.append(sub_filter)

    # Watermark text
    if watermark:
        safe_wm  = watermark.replace("'", "\\'")
        wm_filter = (
            f"drawtext=text='{safe_wm}':"
            f"fontcolor=white@0.6:fontsize=18:"
            f"x=w-tw-20:y=20"
        )
        vf_parts.append(wm_filter)

    # Quality scale
    preset = QUALITY_PRESETS.get(quality, QUALITY_PRESETS["1080p"])
    if preset["scale"]:
        vf_parts.append(f"scale={preset['scale']}")

    vf_string = ",".join(vf_parts)

    rate = int(44100 * audio_pitch)
    tempo = audio_speed / audio_pitch
    af_parts = [
        f"asetrate={rate}",
        f"atempo={format_float(tempo)}",
        "highpass=f=200",
        "lowpass=f=3000"
    ]

    # ── Copyright-Free extra audio transforms ──
    if copyright_free:
        af_parts.extend([
            "equalizer=f=100:t=o:w=200:g=2",   # boost low-end slightly
            "equalizer=f=8000:t=o:w=3000:g=-1", # cut high-end slightly
        ])

    if censored_intervals:
        for start, end in censored_intervals:
            af_parts.append(f"volume=enable='between(t,{format_float(start)},{format_float(end)})':volume=0")
    af_string = ",".join(af_parts)

    cmd = [
        FFMPEG_BIN, "-y", "-i", input_mp4,
        "-vf",  vf_string,
        "-af",  af_string,
        "-c:v", "libx264", "-preset", "veryfast",
        "-crf", preset["crf"],
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-map_metadata", "-1",
        output_name,
    ]

    if copyright_free:
        print("[Copyright-Free] Applying hue shift, zoom crop, speed variation, audio EQ...")

    print("[FFmpeg] Encoding video with filters and captions...")
    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        print(f"[FFmpeg Warning] Primary render failed (code {result.returncode}): {result.stderr[-350:]}")
        # Retry without subtitles if subtitles filter failed (common on minimal Linux containers)
        vf_parts_no_sub = [p for p in vf_parts if not p.startswith("subtitles=")]
        vf_string_no_sub = ",".join(vf_parts_no_sub) if vf_parts_no_sub else "null"
        cmd_fallback = [
            FFMPEG_BIN, "-y", "-i", input_mp4,
            "-vf",  vf_string_no_sub,
            "-af",  af_string,
            "-c:v", "libx264", "-preset", "veryfast",
            "-crf", preset["crf"],
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-map_metadata", "-1",
            output_name,
        ]
        result = subprocess.run(cmd_fallback, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0:
            print("[FFmpeg] ✅ Video encoding complete (fallback mode without burn-in subs)!")
        else:
            print(f"[Error] FFmpeg retry also failed with code {result.returncode}: {result.stderr[-350:]}")
    else:
        print("[FFmpeg] ✅ Video encoding complete!")

    # Intro / Outro concat via FFmpeg
    if result.returncode == 0 and (intro_path or outro_path):
        parts       = []
        concat_txt  = "_concat_list.txt"
        if intro_path and os.path.exists(intro_path):
            parts.append(f"file '{os.path.abspath(intro_path)}'")
        parts.append(f"file '{os.path.abspath(output_name)}'")
        if outro_path and os.path.exists(outro_path):
            parts.append(f"file '{os.path.abspath(outro_path)}'")

        with open(concat_txt, "w") as f:
            f.write("\n".join(parts))

        tmp_concat = "_concat_out.mp4"
        concat_cmd = [
            FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0",
            "-i", concat_txt, "-c", "copy", tmp_concat
        ]
        r2 = subprocess.run(concat_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if r2.returncode == 0:
            os.replace(tmp_concat, output_name)
        for f2 in [concat_txt, tmp_concat]:
            if os.path.exists(f2): os.remove(f2)

    return result.returncode == 0
    """
    Final FFmpeg render with:
     - hflip + color grade
     - Subtitle burn (custom style)
     - Optional watermark text
     - Optional scale to quality preset
     - Optional mouth censorship bar and text
     - Optional profanity audio muting (bleeping)
     - Audio fingerprint shift + metadata wipe
    """
    color     = CAPTION_COLORS.get(style.get("color","yellow"), "&H00FFFF")
    size      = style.get("size", 24)
    position  = CAPTION_POSITIONS.get(style.get("position","bottom"), "2")
    outline   = style.get("outline", "black")
    out_col   = "&H00FFFFFF" if outline == "white" else "&H000000"
    border    = "0" if outline == "none" else "1"

    vf_parts = [
        "hflip",
        "vibrance=intensity=0.1",
        "eq=brightness=0.02:contrast=1.03",
    ]

    # Swear word censoring bar
    if censored_intervals:
        for start, end in censored_intervals:
            vf_parts.append(
                f"drawbox=x=iw*0.2:y=ih*0.53:w=iw*0.6:h=ih*0.07:color=black:t=fill:enable='between(t,{start},{end})'"
            )
            vf_parts.append(
                f"drawtext=text='CENSORED':fontcolor=red:fontsize=20:x=(w-tw)/2:y=ih*0.54:enable='between(t,{start},{end})'"
            )

    if srt_path and os.path.exists(srt_path):
        abs_srt = os.path.abspath(srt_path).replace("\\", "/").replace(":", "\\:")
        sub_filter = (
            f"subtitles='{abs_srt}':force_style='"
            f"Alignment={position},"
            f"FontSize={size},"
            f"PrimaryColour={color},"
            f"OutlineColour={out_col},"
            f"BorderStyle={border},"
            f"Outline=2'"
        )
        vf_parts.append(sub_filter)

    # Watermark text
    if watermark:
        safe_wm  = watermark.replace("'", "\\'")
        wm_filter = (
            f"drawtext=text='{safe_wm}':"
            f"fontcolor=white@0.6:fontsize=18:"
            f"x=w-tw-20:y=20"
        )
        vf_parts.append(wm_filter)

    # Quality scale
    preset = QUALITY_PRESETS.get(quality, QUALITY_PRESETS["1080p"])
    if preset["scale"]:
        vf_parts.append(f"scale={preset['scale']}")

    vf_string = ",".join(vf_parts)

    rate = int(44100 * audio_pitch)
    tempo = audio_speed / audio_pitch
    af_parts = [
        f"asetrate={rate}",
        f"atempo={format_float(tempo)}",
        "highpass=f=200",
        "lowpass=f=3000"
    ]
    if censored_intervals:
        for start, end in censored_intervals:
            af_parts.append(f"volume=enable='between(t,{format_float(start)},{format_float(end)})':volume=0")
    af_string = ",".join(af_parts)

    cmd = [
        FFMPEG_BIN, "-y", "-i", input_mp4,
        "-vf",  vf_string,
        "-af",  af_string,
        "-crf", preset["crf"],
        "-map_metadata", "-1",
        output_name,
    ]

    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        print(f"[Error] FFmpeg execution failed with code {result.returncode}")
        print("[FFmpeg Stderr Output]:")
        print(result.stderr)

    # Intro / Outro concat via FFmpeg
    if result.returncode == 0 and (intro_path or outro_path):
        parts       = []
        concat_txt  = "_concat_list.txt"
        if intro_path and os.path.exists(intro_path):
            parts.append(f"file '{os.path.abspath(intro_path)}'")
        parts.append(f"file '{os.path.abspath(output_name)}'")
        if outro_path and os.path.exists(outro_path):
            parts.append(f"file '{os.path.abspath(outro_path)}'")

        with open(concat_txt, "w") as f:
            f.write("\n".join(parts))

        tmp_concat = "_concat_out.mp4"
        concat_cmd = [
            FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0",
            "-i", concat_txt, "-c", "copy", tmp_concat
        ]
        r2 = subprocess.run(concat_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if r2.returncode == 0:
            os.replace(tmp_concat, output_name)
        for f2 in [concat_txt, tmp_concat]:
            if os.path.exists(f2): os.remove(f2)

    return result.returncode == 0


def ffmpeg_trim_crop(
    input_path: str,
    output_path: str,
    start_time: float,
    end_time: float,
    crop_x: int = 0,
    crop_y: int = 0,
    crop_w: int = 0,
    crop_h: int = 0,
    target_w: int = 1080,
    target_h: int = 1920,
) -> bool:
    """
    Pure FFmpeg: fast-seek trim → crop → scale to target size.
    ~3-5x faster than moviepy write_videofile.
    crop_w=0 means no crop (use full frame).
    """
    duration = max(0.5, end_time - start_time)

    # Ensure all dimensions and coordinates are even numbers (required by libx264 yuv420p)
    tw = int(target_w) - (int(target_w) % 2)
    th = int(target_h) - (int(target_h) % 2)

    vf_parts = []
    if crop_w > 0 and crop_h > 0:
        cw = int(crop_w) - (int(crop_w) % 2)
        ch = int(crop_h) - (int(crop_h) % 2)
        cx = int(crop_x) - (int(crop_x) % 2)
        cy = int(crop_y) - (int(crop_y) % 2)
        vf_parts.append(f"crop={cw}:{ch}:{cx}:{cy}")
    vf_parts.append(f"scale={tw}:{th}:force_original_aspect_ratio=decrease")
    vf_parts.append(f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2")
    vf_string = ",".join(vf_parts)

    cmd = [
        FFMPEG_BIN, "-y",
        "-ss", str(start_time),          # fast seek BEFORE -i
        "-i", input_path,
        "-t", str(duration),
        "-vf", vf_string,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        output_path,
    ]
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        print(f"[FFmpeg Trim Error] Primary trim failed with code {r.returncode}:\n{r.stderr[-600:]}")
        # Robust fallback without custom crop in case crop box exceeded frame bounds
        cmd_fb = [
            FFMPEG_BIN, "-y",
            "-ss", str(start_time),
            "-i", input_path,
            "-t", str(duration),
            "-vf", f"scale={tw}:{th}:force_original_aspect_ratio=decrease,pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            output_path,
        ]
        r_fb = subprocess.run(cmd_fb, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if r_fb.returncode == 0:
            print("[Render] ✅ 9:16 Trim & Reframe complete (fallback scale)!")
            return True
        print(f"[Error] FFmpeg trim fallback also failed: {r_fb.stderr[-600:]}")
        return False
    else:
        print("[Render] ✅ 9:16 Trim & Reframe complete!")
    return True


def process_job(
    video_path   : str,
    start_time   : Optional[float],
    end_time     : Optional[float],
    output_name  : str,
    job_idx      : int = 1,
    total_jobs   : int = 1,
    use_hook     : bool = False,
    hook_duration: int = 30,
    caption_lang : str = "en",
    style        : Optional[dict] = None,
    watermark    : Optional[str] = None,
    intro_path   : Optional[str] = None,
    outro_path   : Optional[str] = None,
    quality      : str = "1080p",
    youtube_url  : Optional[str] = None,
    aspect_ratio : str = "9:16",
    burn_captions: bool = True,
    gemini_api_key: Optional[str] = None,
    music_path   : Optional[str] = None,
    music_volume : float = 0.12,
    add_music    : bool = False,
    auto_bleep   : bool = False,
    sensor_blur  : bool = False,
    beat_sync    : bool = False,
    dub_lang     : Optional[str] = None,
    audio_speed  : float = 1.03,
    audio_pitch  : float = 1.1,
    copyright_free: bool = False,
    groq_api_key: str = "",
) -> bool:
    """Processes a single video editing job."""
    if style is None:
        style = {"color": "yellow", "size": 24, "position": "bottom", "outline": "black"}

    print(f"\n{'═'*60}")
    print(f"  JOB {job_idx}/{total_jobs}  |  {os.path.basename(video_path)}")
    print(f"{'═'*60}")

    # ── Step 0: Download from YouTube if URL given ─────────────
    if youtube_url:
        print(f"[YT-DLP] Downloading: {youtube_url}")
        dl = download_youtube(youtube_url, out_dir=".")
        if not dl:
            print("[YT-DLP] Download failed — skipping job.")
            return False
        video_path = dl
        print(f"[YT-DLP] Saved → {video_path}")

    if not os.path.exists(video_path):
        print(f"[Error] File not found: {video_path}")
        return False

    # ── Step 1: Hook detection or manual timestamps ────────────
    if use_hook:
        print("[Hook] Finding best viral moment...")
        start_time, end_time = detect_hook(video_path, clip_duration=hook_duration, gemini_api_key=gemini_api_key, groq_api_key=groq_api_key)
    else:
        start_time = start_time or 0.0
        end_time   = end_time   or hook_duration

    print(f"[Trim] {start_time:.1f}s → {end_time:.1f}s")

    tmp_mp4 = f"_tmp_{job_idx}.mp4"
    tmp_srt = f"_tmp_{job_idx}.srt" if burn_captions else None

    # ── Step 2: Trim + Crop (pure FFmpeg — fast) ───────────────
    if aspect_ratio in ["9:16", "1:1"]:
        print(f"[AutoReframe] Detecting crop region (ratio={aspect_ratio})...")
        try:
            clip = safe_subclip(VideoFileClip(video_path), start_time, end_time)
            w, h = clip.size

            if aspect_ratio == "9:16":
                target_w, target_h = 1080, 1920
                crop_h_val = h
                crop_w_val = int(h * 9 / 16)
            else:  # 1:1
                target_w, target_h = 1080, 1080
                crop_h_val = min(w, h)
                crop_w_val = crop_h_val

            crop_x_val = max(0, (w - crop_w_val) // 2)  # default: center
            try:
                import cv2
                face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
                cap = cv2.VideoCapture(video_path)
                cap.set(cv2.CAP_PROP_POS_MSEC, (start_time + (end_time - start_time) * 0.3) * 1000)
                ret, frame = cap.read()
                cap.release()
                if ret:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    faces = face_cascade.detectMultiScale(gray, 1.1, 4)
                    if len(faces) > 0:
                        fx, fy, fw, fh = sorted(faces, key=lambda f: f[2]*f[3], reverse=True)[0]
                        face_cx = fx + fw // 2
                        crop_x_val = max(0, min(face_cx - crop_w_val // 2, w - crop_w_val))
                        print(f"[AutoReframe] Face at x={face_cx}, crop from x={crop_x_val}")
            except Exception as fe:
                print(f"[AutoReframe] Face detection skipped: {fe}")
            clip.close()

            print(f"[Render] FFmpeg trim+crop → {tmp_mp4} ...")
            ok_trim = ffmpeg_trim_crop(
                video_path, tmp_mp4,
                start_time, end_time,
                crop_x=crop_x_val, crop_y=0,
                crop_w=crop_w_val, crop_h=crop_h_val,
                target_w=target_w, target_h=target_h,
            )
        except Exception as ex:
            print(f"[AutoReframe] Error: {ex}. Falling back to simple trim.")
            ok_trim = ffmpeg_trim_crop(
                video_path, tmp_mp4,
                start_time, end_time,
                target_w=1080, target_h=1920,
            )
    else:
        print(f"[Render] FFmpeg trim → {tmp_mp4} ...")
        ok_trim = ffmpeg_trim_crop(
            video_path, tmp_mp4,
            start_time, end_time,
            target_w=1920, target_h=1080,
        )

    if not ok_trim:
        print("[Error] FFmpeg trim/crop failed — skipping job.")
        return False

    # ── Step 2.5: Optional Global Dubbing ─────────────────────
    if dub_lang:
        print(f"[Dubbing] Generating target voiceover for: {dub_lang}...")
        tmp_dub = f"_tmp_dub_{job_idx}.wav"
        model = get_model()
        result = _fw_transcribe(model, tmp_mp4, language="en", groq_api_key=groq_api_key)
        dub_ok = translate_and_dub(tmp_mp4, result["segments"], dub_lang, tmp_dub)
        if dub_ok and os.path.exists(tmp_dub):
            tmp_dubbed_mp4 = f"_tmp_dubbed_{job_idx}.mp4"
            replace_cmd = [
                FFMPEG_BIN, "-y",
                "-i", tmp_mp4, "-i", tmp_dub,
                "-map", "0:v", "-map", "1:a",
                "-c:v", "copy", "-c:a", "aac",
                tmp_dubbed_mp4
            ]
            r_rep = subprocess.run(replace_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if r_rep.returncode == 0:
                os.replace(tmp_dubbed_mp4, tmp_mp4)
                print("[Dubbing] ✅ Video audio replaced with translated voice!")
            if os.path.exists(tmp_dub):
                os.remove(tmp_dub)

    # ── Step 2.7: Optional Profanity Detection ────────────────
    censored_intervals = []
    if auto_bleep or sensor_blur:
        print("[Profanity] Scanning transcript for swear words...")
        model = get_model()
        result = _fw_transcribe(model, tmp_mp4, language="en", groq_api_key=groq_api_key)
        censored_intervals = detect_profanity_intervals(result["segments"])
        if censored_intervals:
            print(f"[Profanity] ⚠️ Detected {len(censored_intervals)} swear word(s). Censorship active.")
        else:
            print("[Profanity] ✅ Clean transcript. No censorship needed.")

    # ── Step 2.8: Optional Beat-Sync Detection ────────────────
    beat_times = []
    if beat_sync and add_music and music_path and os.path.exists(music_path):
        print("[Beat-Sync] Analyzing background music beats...")
        beat_times = detect_beats(music_path)
        if beat_times:
            print(f"[Beat-Sync] Syncing captions to {len(beat_times)} detected beats!")

    # ── Step 3: Subtitle generation + translation ──────────────
    transcript_path = output_name.replace(".mp4", "_transcript.txt")
    if burn_captions or gemini_api_key:
        print(f"[Captions] Transcribing {'+ translating to ' + caption_lang if (burn_captions and caption_lang != 'en') else ''}...")
        generate_srt(tmp_mp4, srt_path=tmp_srt, transcript_path=transcript_path, lang=caption_lang, style=style, beat_times=beat_times, groq_api_key=groq_api_key)

    # ── Step 4: FFmpeg render (style + watermark + quality + censorship + copyright bypass)
    print(f"[4/5] FFmpeg final render at {quality}...")
    ok = ffmpeg_render(
        input_mp4   = tmp_mp4,
        srt_path    = tmp_srt,
        output_name = output_name,
        style       = style,
        watermark   = watermark,
        intro_path  = intro_path,
        outro_path  = outro_path,
        quality     = quality,
        censored_intervals = censored_intervals,
        audio_speed = audio_speed,
        audio_pitch = audio_pitch,
        copyright_free = copyright_free,
    )

    # ── Step 5: Background Music ───────────────────────────────
    if ok and add_music:
        print(f"[5/5] Mixing background music (volume={music_volume})...")
        music_ok = ffmpeg_add_music(
            video_path   = output_name,
            output_path  = output_name,
            music_path   = music_path,
            music_volume = music_volume,
        )
        if music_ok:
            print("[Music] ✅ Background music added!")
        else:
            print("[Music] ⚠️ Music mix failed, video saved without music.")

    # ── Cleanup ────────────────────────────────────────────────
    for f in [tmp_mp4, tmp_srt]:
        if f and os.path.exists(f): os.remove(f)

    if ok:
        if os.path.exists(output_name):
            print("[Metadata] Stripping metadata to avoid algorithmic footprint...")
            strip_tmp = output_name + ".tmp_strip.mp4"
            strip_cmd = [
                FFMPEG_BIN, "-y",
                "-i", output_name,
                "-map_metadata", "-1",
                "-c:v", "copy",
                "-c:a", "copy",
                strip_tmp
            ]
            try:
                r_strip = subprocess.run(strip_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if r_strip.returncode == 0 and os.path.exists(strip_tmp):
                    os.replace(strip_tmp, output_name)
                    print("[Metadata] ✅ Metadata stripped successfully!")
                else:
                    if os.path.exists(strip_tmp): os.remove(strip_tmp)
                    print("[Metadata] ⚠️ Metadata stripping failed, using original render.")
            except Exception as e_strip:
                if os.path.exists(strip_tmp): os.remove(strip_tmp)
                print(f"[Metadata] ⚠️ Metadata strip exception: {e_strip}")

        print(f"[Done] ✅ → {output_name}")
    else:
        print(f"[Error] FFmpeg render failed for job {job_idx}")
    return ok


def process_copyright_free_video(
    video_path: str,
    output_name: str,
    quality: str = "1080p",
    audio_speed: float = 1.02,
    audio_pitch: float = 1.05,
) -> bool:
    """
    Process an entire full-length / long video to bypass YouTube copyright detection algorithms:
      • Horizontal Flip (hflip)
      • Color grading (vibrance + brightness + contrast + subtle hue rotation)
      • Subtle Zoom Crop (2%) to break pixel-match hashing
      • Video speed shift (1%)
      • Audio pitch + tempo shift + acoustic frequency equalization
      • Complete metadata wipe (-map_metadata -1)
    """
    if not os.path.exists(video_path):
        print(f"[Copyright-Free] Error: File not found {video_path}")
        return False

    os.makedirs(os.path.dirname(os.path.abspath(output_name)), exist_ok=True)
    preset = QUALITY_PRESETS.get(quality, QUALITY_PRESETS["1080p"])

    vf_parts = [
        "hflip",
        "vibrance=intensity=0.12",
        "eq=brightness=0.02:contrast=1.03",
        "hue=h=3",
        "crop=iw*0.98:ih*0.98:(iw-iw*0.98)/2:(ih-ih*0.98)/2,scale=iw/0.98:ih/0.98",
        "setpts=1.01*PTS",
    ]
    if preset["scale"]:
        vf_parts.append(f"scale={preset['scale']}")
    vf_string = ",".join(vf_parts)

    rate = int(44100 * audio_pitch)
    tempo = audio_speed / audio_pitch
    af_parts = [
        f"asetrate={rate}",
        f"atempo={format_float(tempo)}",
        "highpass=f=200",
        "lowpass=f=3200",
        "equalizer=f=120:t=o:w=200:g=2",
        "equalizer=f=7500:t=o:w=3000:g=-1",
    ]
    af_string = ",".join(af_parts)

    cmd = [
        FFMPEG_BIN, "-y",
        "-i", video_path,
        "-vf", vf_string,
        "-af", af_string,
        "-c:v", "libx264", "-preset", "fast", "-crf", preset["crf"],
        "-c:a", "aac", "-b:a", "192k",
        "-map_metadata", "-1",
        "-movflags", "+faststart",
        output_name,
    ]

    print(f"[Copyright-Free] Processing long video: {video_path} → {output_name}")
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        print(f"[Copyright-Free] Warning: Primary render failed ({r.stderr[-300:]}), retrying...")
        r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)

    if r.returncode == 0 and os.path.exists(output_name):
        print(f"[Copyright-Free] ✅ Successfully generated copyright-free video: {output_name}")
        return True
    else:
        print(f"[Copyright-Free] ❌ Failed to generate copyright-free video.")
        return False


def run_bulk(jobs: list[dict], gemini_api_key: str = "", groq_api_key: str = "") -> None:
    """Run a list of job dicts. Each dict mirrors process_job kwargs."""
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    total = len(jobs)
    ok_n, fail_n = 0, 0

    for i, job in enumerate(jobs, 1):
        job.setdefault("job_idx",    i)
        job.setdefault("total_jobs", total)
        job.setdefault("output_name", os.path.join(OUTPUT_FOLDER, f"short_{i:02d}.mp4"))
        if gemini_api_key:
            job["gemini_api_key"] = gemini_api_key
        if groq_api_key:
            job["groq_api_key"] = groq_api_key
        result = process_job(**job)
        if result: ok_n += 1
        else:      fail_n += 1

    print(f"\n{'═'*60}")
    print(f"  DONE — ✅ {ok_n}/{total} succeeded   ❌ {fail_n}/{total} failed")
    print(f"{'═'*60}\n")


# ══════════════════════════════════════════════════════════════
#  DEMO  (edit and run directly if you like)
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("🔥" + "=" * 54 + "🔥")
    print("          FLOODBOT v2.0 — FULL FEATURE ENGINE         ")
    print("🔥" + "=" * 54 + "🔥\n")

    DEMO_JOBS = [
        {
            "video_path"   : "input.mp4",
            "start_time"   : None,         # ignored when use_hook=True
            "end_time"     : None,
            "output_name"  : "output/hook_short.mp4",
            "use_hook"     : True,          # ← AI finds the best moment
            "hook_duration": 30,
            "caption_lang" : "en",          # "en","bn","hi","es","fr","ko"...
            "style"        : {
                "color"   : "yellow",       # yellow/white/red/pink/blue/green
                "size"    : 28,
                "position": "bottom",       # bottom/middle/top
                "outline" : "black",        # black/white/none
            },
            "watermark"    : "@YourChannel",# None to disable
            "intro_path"   : None,          # "intro.mp4" or None
            "outro_path"   : None,          # "outro.mp4" or None
            "quality"      : "1080p",       # 720p/1080p/4K/original
            "youtube_url"  : None,          # paste a YT URL to auto-download
        },
    ]

    run_bulk(DEMO_JOBS)
