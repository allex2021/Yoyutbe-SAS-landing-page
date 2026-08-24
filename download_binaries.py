import os
import sys
import urllib.request
import zipfile
import shutil
import platform

def download_file(url, dest):
    print(f"Downloading: {url} -> {dest}...")
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as response, open(dest, 'wb') as out_file:
        shutil.copyfileobj(response, out_file)
    print("Download finished.")

def extract_zip(zip_path, extract_to):
    print(f"Extracting: {zip_path} -> {extract_to}...")
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_to)

def main():
    bin_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin")
    os.makedirs(bin_dir, exist_ok=True)
    
    sys_plat = platform.system().lower() # windows, darwin, linux
    print(f"Platform detected: {sys_plat}")
    
    # 1. Download yt-dlp
    yt_url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp"
    if sys_plat == "windows":
        yt_url += ".exe"
    yt_dest = os.path.join(bin_dir, "yt-dlp.exe" if sys_plat == "windows" else "yt-dlp")
    
    if not os.path.exists(yt_dest):
        try:
            download_file(yt_url, yt_dest)
            if sys_plat != "windows":
                os.chmod(yt_dest, 0o755)
            print("✅ yt-dlp is ready.")
        except Exception as e:
            print(f"❌ Failed to download yt-dlp: {e}")
    else:
        print("✅ yt-dlp already exists, skipping.")
            
    # 2. Download ffmpeg
    ff_dest = os.path.join(bin_dir, "ffmpeg.exe" if sys_plat == "windows" else "ffmpeg")
    if not os.path.exists(ff_dest):
        tmp_zip = os.path.join(bin_dir, "ffmpeg.zip")
        try:
            if sys_plat == "windows":
                # Direct static link to a small zip containing ffmpeg.exe
                ff_url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
                download_file(ff_url, tmp_zip)
                extract_dir = os.path.join(bin_dir, "ffmpeg_extracted")
                extract_zip(tmp_zip, extract_dir)
                # Find ffmpeg.exe inside extracted files
                for root, dirs, files in os.walk(extract_dir):
                    if "ffmpeg.exe" in files:
                        shutil.move(os.path.join(root, "ffmpeg.exe"), ff_dest)
                    if "ffprobe.exe" in files:
                        shutil.move(os.path.join(root, "ffprobe.exe"), os.path.join(bin_dir, "ffprobe.exe"))
                shutil.rmtree(extract_dir)
                os.remove(tmp_zip)
                print("✅ FFmpeg is ready (Windows).")
            elif sys_plat == "darwin":
                # Static Mac ffmpeg zip from evermeet.cx
                ff_url = "https://evermeet.cx/ffmpeg/getrelease/zip"
                download_file(ff_url, tmp_zip)
                extract_zip(tmp_zip, bin_dir)
                os.remove(tmp_zip)
                # Ensure it is named correctly and executable
                for f in os.listdir(bin_dir):
                    if f.startswith("ffmpeg-") and f.endswith(".zip"):
                        os.remove(os.path.join(bin_dir, f))
                if os.path.exists(ff_dest):
                    os.chmod(ff_dest, 0o755)
                print("✅ FFmpeg is ready (macOS).")
        except Exception as e:
            if os.path.exists(tmp_zip):
                os.remove(tmp_zip)
            print(f"❌ Failed to download FFmpeg: {e}")
    else:
        print("✅ FFmpeg already exists, skipping.")
            
    print("\n🎉 Binary setup complete! All dependencies are localized inside the 'bin/' directory.")

if __name__ == "__main__":
    main()
