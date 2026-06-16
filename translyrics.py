"""
translyrics.py — Extract lyrics/transcript from a YouTube URL.

Strategy:
  1. Fetch video metadata (title, declared audio language, subtitle tracks) via yt-dlp.
  2. Try to fetch existing subtitles via yt-dlp — preferring non-English tracks,
     since those are more likely the original lyrics rather than a translation.
  3. If the caption language doesn't match the declared audio language, warn and
     fall back to Whisper so you get the actual sung lyrics, not a translation.
  4. If no captions exist at all, fall back to Whisper.
  5. If the lyrics are not in English, automatically translate them to English
     and save both files inside an output folder named after the song.

Usage:
  python translyrics.py <youtube_url>
  python translyrics.py <youtube_url> --whisper          # always use Whisper
  python translyrics.py <youtube_url> --model medium     # Whisper model size
  python translyrics.py <youtube_url> --no-lang-check    # skip mismatch detection
"""

__author__ = "Millie"

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

MAX_FILENAME_LEN = 80
MAX_CHUNK = 4500
SEPARATOR = "=" * 60
PREVIEW_CHARS = 2000


def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", name)


def transcribe_with_whisper(url: str, title: str, model_size: str, audio_dir: str, cookies_args: list) -> tuple[str, str]:
    """
    Download audio via yt-dlp and transcribe with OpenAI Whisper.
    Returns (transcript_text, detected_language_code).
    MP3 is saved permanently as <audio_dir>/<title>.mp3.
    """
    try:
        import whisper
    except ImportError:
        print("[ERROR] openai-whisper is not installed.")
        print("        Run: python -m pip install openai-whisper")
        sys.exit(1)

    os.makedirs(audio_dir, exist_ok=True)
    audio_path = os.path.join(audio_dir, f"{sanitize_filename(title)[:MAX_FILENAME_LEN]}.mp3")

    print(f"[INFO] Downloading audio for: {title}")
    subprocess.run([
        sys.executable, "-m", "yt_dlp",
        "--no-playlist", "-x", "--audio-format", "mp3", "--remote-components", "ejs:github",
        "-o", audio_path, *cookies_args, url,
    ], check=True, timeout=600)
    print(f"[INFO] MP3 saved to: {audio_path}")

    print(f"[INFO] Transcribing with Whisper model '{model_size}' (this may take a moment)...")
    model = whisper.load_model(model_size)
    result = model.transcribe(audio_path, fp16=False)

    detected_lang = result.get("language", "unknown")
    segments = result.get("segments", [])
    if segments:
        transcript = "\n\n".join(seg["text"].strip() for seg in segments if seg["text"].strip())
    else:
        transcript = result["text"].strip()

    return transcript, detected_lang


def main():
    parser = argparse.ArgumentParser(description="Extract lyrics/transcript from a YouTube URL.")
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument("--whisper", action="store_true",
                        help="Skip caption extraction and always use Whisper")
    parser.add_argument("--model", default="base",
                        choices=["tiny", "base", "small", "medium", "large"],
                        help="Whisper model size (default: base). Larger = more accurate but slower.")
    parser.add_argument("--no-lang-check", action="store_true",
                        help="Skip caption language mismatch detection (use captions as-is)")
    parser.add_argument("--cookies-from-browser", metavar="BROWSER",
                        help="Pass browser cookies to yt-dlp (e.g. chrome, firefox, edge). Required for age-restricted videos.")
    args = parser.parse_args()
    cookies_args = ["--cookies-from-browser", args.cookies_from_browser] if args.cookies_from_browser else []

    print(f"[INFO] Processing: {args.url}\n")

    print("[INFO] Fetching video metadata...")
    meta_result = subprocess.run(
        [sys.executable, "-m", "yt_dlp", "--dump-json", "--no-playlist", "--remote-components", "ejs:github", *cookies_args, args.url],
        capture_output=True, text=True, timeout=30
    )
    try:
        metadata = json.loads(meta_result.stdout)
    except (json.JSONDecodeError, ValueError):
        metadata = {}

    title = metadata.get("title") or "unknown"
    audio_lang = metadata.get("language")
    output_dir = sanitize_filename(title)[:MAX_FILENAME_LEN]

    if args.whisper:
        transcript, transcript_lang = transcribe_with_whisper(args.url, title, args.model, output_dir, cookies_args)
        source = f"Whisper transcription (model: {args.model})"
    else:
        manual = list(metadata.get("subtitles", {}).keys())
        auto = list(metadata.get("automatic_captions", {}).keys())
        non_en_manual = [lang for lang in manual if not lang.startswith("en")]
        non_en_auto = [lang for lang in auto if not lang.startswith("en")]
        sub_lang = non_en_manual[0] if non_en_manual else (non_en_auto[0] if non_en_auto else "en")

        if sub_lang != "en":
            print(f"[INFO] Non-English subtitle track found: '{sub_lang}'. Trying it first.")
        print(f"[INFO] Trying to fetch captions (lang: {sub_lang})...")

        transcript = None
        cap_lang = None
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run([
                sys.executable, "-m", "yt_dlp",
                "--skip-download", "--write-auto-sub", "--write-sub",
                "--sub-lang", sub_lang, "--sub-format", "vtt",
                "--no-playlist", "--remote-components", "ejs:github",
                "-o", os.path.join(tmpdir, "%(title)s.%(ext)s"),
                *cookies_args, args.url,
            ], capture_output=True, text=True, timeout=60)

            vtt_files = [f for f in os.listdir(tmpdir) if f.endswith(".vtt")]
            if vtt_files:
                with open(os.path.join(tmpdir, vtt_files[0]), encoding="utf-8") as f:
                    raw = f.read()
                lines = []
                seen_last = None
                for line in raw.splitlines():
                    if not line.strip():
                        continue
                    if line.startswith("WEBVTT") or line.startswith("Kind:"):
                        continue
                    if line.startswith("Language:"):
                        cap_lang = line.split(":", 1)[1].strip()
                        continue
                    if re.match(r"^\d{2}:\d{2}", line):
                        continue
                    clean = re.sub(r"<[^>]+>", "", line).strip()  # strip VTT inline tags e.g. <00:00:00.000><c>word</c>
                    if not clean:
                        continue
                    if clean != seen_last:
                        lines.append(clean)
                        seen_last = clean
                transcript = "\n\n".join(lines)

        if transcript:
            print(f"[OK]   Captions found for: {title}")
            if cap_lang:
                print(f"[INFO] Caption language: {cap_lang}")

            # Captions are only trusted when the declared audio language is known AND matches.
            # An undeclared audio language means we can't verify — fall back to Whisper.
            if not args.no_lang_check:
                if audio_lang and cap_lang:
                    audio_base = audio_lang.split("-")[0].lower()
                    cap_base = cap_lang.split("-")[0].lower()
                    if audio_base != cap_base:
                        print(f"[WARN] Caption language '{cap_lang}' doesn't match "
                              f"declared audio language '{audio_lang}'.")
                        print("[WARN] Captions appear to be a translation, not the original lyrics.")
                        print("[INFO] Falling back to Whisper to transcribe the actual lyrics...")
                        transcript, transcript_lang = transcribe_with_whisper(
                            args.url, title, args.model, output_dir, cookies_args
                        )
                        source = f"Whisper transcription (model: {args.model})"
                    else:
                        transcript_lang = cap_lang
                        source = "YouTube captions (yt-dlp)"
                else:
                    print("[WARN] Video has no declared audio language — cannot verify captions.")
                    print("[INFO] Falling back to Whisper to ensure original lyrics are captured...")
                    transcript, transcript_lang = transcribe_with_whisper(
                        args.url, title, args.model, output_dir
                    )
                    source = f"Whisper transcription (model: {args.model})"
            else:
                transcript_lang = cap_lang or audio_lang
                source = "YouTube captions (yt-dlp)"
        else:
            print("[INFO] No captions available. Falling back to Whisper transcription.")
            transcript, transcript_lang = transcribe_with_whisper(
                args.url, title, args.model, output_dir, cookies_args
            )
            source = f"Whisper transcription (model: {args.model})"

    safe_title = sanitize_filename(title)[:MAX_FILENAME_LEN]
    os.makedirs(output_dir, exist_ok=True)

    orig_path = os.path.join(output_dir, f"{safe_title}.txt")
    with open(orig_path, "w", encoding="utf-8") as f:
        f.write(f"Title: {title}\n")
        f.write(f"Source: {source}\n")
        f.write(SEPARATOR + "\n\n")
        f.write(transcript)
        f.write("\n")
    print(f"\n[DONE] Saved to: {orig_path}")

    # Whisper already downloads the MP3; caption path needs a separate fetch
    mp3_path = os.path.join(output_dir, f"{safe_title}.mp3")
    if not os.path.exists(mp3_path):
        print("[INFO] Downloading MP3...")
        dl_result = subprocess.run([
            sys.executable, "-m", "yt_dlp",
            "--no-playlist", "-x", "--audio-format", "mp3", "--remote-components", "ejs:github",
            "-o", mp3_path, *cookies_args, args.url,
        ], capture_output=True, text=True, timeout=600)
        if dl_result.returncode == 0 and os.path.exists(mp3_path):
            print(f"[DONE] MP3 saved to: {mp3_path}")
        else:
            print("[WARN] MP3 download failed.")
    else:
        print(f"[INFO] MP3 already saved: {mp3_path}")

    lang_base = (transcript_lang or "").split("-")[0].lower()
    if lang_base and lang_base != "en":
        print(f"\n[INFO] Lyrics are in '{transcript_lang}' — translating to English...")
        try:
            from deep_translator import GoogleTranslator
        except ImportError:
            print("[WARN] deep-translator is not installed — skipping auto-translation.")
            print("       Run: python -m pip install deep-translator")
        else:
            paragraphs = transcript.split("\n")
            chunks = []
            current_chunk = []
            current_len = 0
            for para in paragraphs:
                if current_len + len(para) + 1 > MAX_CHUNK:
                    chunks.append("\n".join(current_chunk))
                    current_chunk = [para]
                    current_len = len(para)
                else:
                    current_chunk.append(para)
                    current_len += len(para) + 1
            if current_chunk:
                chunks.append("\n".join(current_chunk))

            translator = GoogleTranslator(source="auto", target="english")
            translated_chunks = []
            for i, chunk in enumerate(chunks):
                if len(chunks) > 1:
                    print(f"[INFO] Translating chunk {i + 1}/{len(chunks)}...")
                translated_chunks.append(translator.translate(chunk))
            translated = "\n".join(translated_chunks)

            trans_path = os.path.join(output_dir, f"{safe_title} [English].txt")
            with open(trans_path, "w", encoding="utf-8") as f:
                f.write(f"Title: {title}\n")
                f.write(f"Source: {source}\n")
                f.write("Translation: English (via Google Translate)\n")
                f.write(SEPARATOR + "\n\n")
                f.write(translated)
                f.write("\n")
            print(f"[DONE] Translation saved to: {trans_path}")

    print("\n" + SEPARATOR)
    print(transcript[:PREVIEW_CHARS])
    if len(transcript) > PREVIEW_CHARS:
        print(f"\n... [truncated — full text in {orig_path}]")


if __name__ == "__main__":
    main()
