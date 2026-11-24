# DateFixer (Offline Android App — Java + XML + HTML + CSS + Python)

100% offline Android file & media date manager with a **ZArchiver-style dark file explorer** and **zero Kotlin**.

## Tech Stack
- **Java + XML** (`MainActivity.java`, `activity_main.xml`): Android host, `WebView` + `@JavascriptInterface` bridge, multi-user storage permissions (`MANAGE_EXTERNAL_STORAGE`), and `MediaScannerConnection` gallery refresh.
- **HTML + CSS + JS** (`app/src/main/assets/`): ZArchiver-style dark explorer UI, Type Permission Gate, Dry-Run Preview, Bundle Date Overwrite, File Details Editor, and Results/Undo screens.
- **Python (Chaquopy)** (`app/src/main/python/media_date_engine.py`): 100% standard-library offline engine (zero `pip` dependencies) for filename date parsing, pure-Python JPEG EXIF reading/writing, pure-Python MP4/MOV atom updates, filesystem timestamps, and JSON undo logs.

## Features
- **ZArchiver-Style Explorer:** Browse your active Android user storage dynamically (works on both primary and secondary user profiles), navigate with `..`, select individual items, or tap **Select All**.
- **2-Step Detect & Permission Gate:** Scans selected files/folders, groups them by detected filename pattern, and asks permission per type before modifying anything.
- **Rich Filename Pattern Support (`1800–2099`):**
  - Camera & burst: `IMG_20251119_112809_Burst09.jpg`, `VID_20240715_105623258.mp4`, `video_20251127_115818.mp4`, `IMG20250810142209.jpg`
  - WhatsApp: `IMG-20260924-WA0057.jpg`, `VID_20230831_WA0001.mp4`
  - Screenshots, Telegram, Signal, Month-name (`14-May-2024.jpg`), `DDMMYYYY`, ISO 8601, Unix timestamps, optional 6-digit `YYMMDD`, and custom regex.
- **Preserves Time on Date-Only Filenames:** Updates only `YYYY-MM-DD` while keeping the file's existing `HH:MM:SS`.
- **Safety Warnings:**
  - Flags **Unmatched** files to ask before changing.
  - Flags **Future Dates (`> now`)** with a warning and leaves them unchecked by default.
  - Warns and requires confirmation when **Set Date (Bundle)** includes folders alongside files/media.
- **Edit All File Details & Bundle Overwrite:** Tap any file to rename, edit date/time, or update JPEG EXIF metadata—or select any files/folders to overwrite their date/time as a bundle.
- **Undo Support:** Saves `_media_date_fixer_undo.json` before batch updates.

## Build APK via GitHub Actions (No Android Studio Required)
1. Upload all files and folders inside `MediaDateFixerJavaWeb` (including `.github/workflows/build-apk.yml`) to the root of a GitHub repository.
2. Open the **Actions** tab and wait for **Build Android APK** to finish.
3. Download **`MediaDateFixer-debug-apk`** under **Artifacts** to get `app-debug.apk`.

## Build Locally in Android Studio
1. Open the `MediaDateFixerJavaWeb` folder in **Android Studio** (use Gradle JVM 17 or 21).
2. Let Gradle sync, then click **Build > Build App Bundle(s) / APK(s) > Build APK(s)**.
