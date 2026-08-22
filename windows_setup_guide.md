# Windows Setup Guide — +FloodBot by cyber2

Windows 10/11-এ FloodBot সেটআপ করার সবচেয়ে সহজ এবং সঠিক গাইড নিচে দেওয়া হলো:

---

## 🛠️ Prerequisites (পূর্বপ্রস্তুতি)

### ১. Python ইনস্টল করুন
1. [python.org](https://www.python.org/downloads/) থেকে Python 3.10 বা 3.11 ইনস্টল ফাইলটি ডাউনলোড করুন।
2. ইনস্টলার রান করার সময় অবশ্যই নিচে দেওয়া **"Add Python to PATH"** বক্সে টিক (Check) দিন। (এটি অত্যন্ত গুরুত্বপূর্ণ!)
3. "Install Now"-এ ক্লিক করে ইনস্টলেশন শেষ করুন।

### ২. FFmpeg সেটআপ করুন (সবচেয়ে সহজ পদ্ধতি)
যেহেতু উইন্ডোজে ডিফল্টভাবে FFmpeg থাকে না, তাই:
1. [gyan.dev FFmpeg Builds](https://www.gyan.dev/ffmpeg/builds/ffmpeg-git-essentials.7z) থেকে জিপ ফাইলটি ডাউনলোড করে আনজিপ করুন।
2. আনজিপ করা ফোল্ডারের `bin` ফোল্ডার থেকে `ffmpeg.exe` এবং `ffprobe.exe` কপি করুন।
3. আপনার উইন্ডোজের ইউজার ডিরেক্টরিতে (যেমন: `C:\Users\YOUR_USERNAME\`) একটি নতুন ফোল্ডার তৈরি করুন যার নাম দিন `bin` (ফোল্ডার পাথ হবে: `C:\Users\YOUR_USERNAME\bin\`)।
4. কপি করা `ffmpeg.exe` এবং `ffprobe.exe` ফাইল দুটি এই `bin` ফোল্ডারে পেস্ট করে দিন। 
*(ব্যস! ম্যাকের মতোই উইন্ডোজেও এটি অটোমেটিক কাজ করবে।)*

---

## 🚀 Installation & Running (ইনস্টলেশন ও রান করা)

আপনার প্রোজেক্ট ফোল্ডারে (যেমন: `YOUTUBE SHORTS`) গিয়ে Command Prompt (cmd) ওপেন করুন এবং নিচের কমান্ডগুলো একে একে রান করুন:

### ১. Virtual Environment (venv) তৈরি ও অ্যাক্টিভেট করুন
```cmd
# venv তৈরি করুন
python -m venv .venv

# venv অ্যাক্টিভেট করুন
.venv\Scripts\activate
```

### ২. Dependencies ইনস্টল করুন
```cmd
pip install -r requirements.txt
```

### ৩. Flask Server রান করুন
```cmd
python app.py
```

সার্ভার স্টার্ট হলে কমান্ড লাইনে `http://127.0.0.1:8080` মেসেজটি দেখতে পাবেন। আপনার ব্রাউজার ওপেন করে এই লিংকে চলে গেলেই প্রিমিয়াম নিয়ন সাইবারপাংক ড্যাশবোর্ডটি পেয়ে যাবেন!
