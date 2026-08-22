import os
import sys
import subprocess
import shutil

def run_cmd(cmd):
    print(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)

def main():
    print("🚀 YouTube Shorts Automation Suite — Desktop Build Script")
    print("=========================================================")

    # 1. Install pyinstaller
    print("\n📦 Step 1: Installing PyInstaller...")
    try:
        run_cmd(["uv", "pip", "install", "pyinstaller"])
    except Exception:
        try:
            run_cmd([sys.executable, "-m", "pip", "install", "pyinstaller"])
        except Exception:
            run_cmd(["pip", "install", "pyinstaller"])

    # 2. Setup build options
    print("\n🏗️ Step 2: Compiling with PyInstaller...")
    # Add templates directory to compilation data
    # format is: source_path;dest_path (Windows) or source_path:dest_path (macOS/Linux)
    separator = ";" if sys.platform == "win32" else ":"
    data_arg = f"templates{separator}templates"

    pyinstaller_bin = "pyinstaller"
    venv_bin = os.path.join(os.getcwd(), ".venv", "Scripts" if sys.platform == "win32" else "bin", "pyinstaller")
    if os.path.exists(venv_bin):
        pyinstaller_bin = venv_bin
    elif os.path.exists(venv_bin + ".exe"):
        pyinstaller_bin = venv_bin + ".exe"

    cmd = [
        pyinstaller_bin,
        "--clean",
        "--onefile",
        "--add-data", data_arg,
        "--name", "ShortsAutomationSuite",
        "app.py"
    ]

    try:
        run_cmd(cmd)
        print("\n✅ Step 3: Package complete!")
        
        dist_dir = os.path.join(os.getcwd(), "dist")
        exe_name = "ShortsAutomationSuite.exe" if sys.platform == "win32" else "ShortsAutomationSuite"
        out_path = os.path.join(dist_dir, exe_name)
        
        print(f"\n🎉 Standalone executable created successfully at:")
        print(f"   👉 {out_path}")
        print("\nYou can now share this single file with anyone! When they open it, it will automatically launch the server.")
        
    except Exception as e:
        print(f"\n❌ Build failed: {e}")
        print("Please check that your Python, PyInstaller, and virtualenv paths are configured correctly.")

if __name__ == "__main__":
    main()
