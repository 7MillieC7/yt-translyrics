# TransLyrics

Extract lyrics or transcripts from any YouTube video and translate them to any language.

Two scripts, no API keys required — everything runs locally on your machine.

---

## What it does

**`translyrics.py`** — give it a YouTube URL, get a `.txt` file with the lyrics and an `.mp3` of the audio, saved together in a folder named after the video.

It tries YouTube's own captions first (fast, no audio download needed). If captions are missing or in the wrong language, it falls back to Whisper — an offline transcription model that downloads the audio and transcribes it locally.

**`translation.py`** — give it the `.txt` from the first script and a language name, get a translated `.txt` saved in the same folder.

Ukrainian output is special: it includes both Cyrillic and a Latin transliteration in the same file.

---

## Setup (one time)

**1. Install Python dependencies:**
```
python -m pip install yt-dlp openai-whisper deep-translator
```

**2. Install ffmpeg** (needed for audio processing):
- Download from https://ffmpeg.org/download.html
- On Windows: extract the zip, add the `bin\` folder to your system PATH.

---

## Usage

**Extract lyrics:**
```
python translyrics.py "YOUR_YOUTUBE_URL"
```

Output: a folder named after the video, containing `Song Title.txt` and `Song Title.mp3`.

Optional flags:
```
--whisper            skip captions, always use Whisper
--model medium       use a more accurate (but slower) Whisper model
--no-lang-check      use captions without language verification
```

**Translate lyrics:**
```
python translation.py "Song Title\Song Title.txt" french
```

Supported languages include: `french`, `spanish`, `romanian`, `latin`, `japanese`, `german`, `ukrainian`, and [many more](https://py-googletrans.readthedocs.io/en/latest/#googletrans-languages).

---

## Notes

- No API keys needed — Google Translate is called for free via `deep-translator`.
- Whisper runs fully offline after the model downloads the first time (~75 MB for `base`).
- If a video has no captions and Whisper can't access it (age-restricted, private), extraction will fail.
- Wrap file paths containing spaces or special characters in quotes.
