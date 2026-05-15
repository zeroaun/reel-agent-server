from flask import Flask, request, jsonify
import os, requests, subprocess, tempfile, threading, shutil

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
ELEVENLABS_KEY = os.environ.get("ELEVENLABS_KEY", "")

def telegram_send_message(chat_id, text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10
        )
    except Exception as e:
        print(f"Telegram message error: {e}")

def telegram_send_video(chat_id, video_path, caption=""):
    try:
        with open(video_path, "rb") as f:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo",
                data={"chat_id": chat_id, "caption": caption, "supports_streaming": True, "width": 1080, "height": 1920},
                files={"video": ("reel.mp4", f, "video/mp4")},
                timeout=300
            )
    except Exception as e:
        print(f"Telegram video error: {e}")

def download_file(url, dest):
    r = requests.get(url, stream=True, timeout=60)
    r.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)

def generate_voice(script, voice_id, dest_path):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {"xi-api-key": ELEVENLABS_KEY, "Content-Type": "application/json"}
    body = {
        "text": script,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.8, "style": 0.3, "use_speaker_boost": True}
    }
    r = requests.post(url, json=body, headers=headers, timeout=60)
    r.raise_for_status()
    with open(dest_path, "wb") as f:
        f.write(r.content)

def process_reel(data, chat_id):
    tmpdir = tempfile.mkdtemp()
    try:
        clips_urls = data.get("clips_urls", [])
        script = data.get("script", "")
        voice_id = data.get("voice_id", "pNInz6obpgDQGcFmaJgB")
        srt_content = data.get("srt_content", "")
        title = data.get("title", "Réel")
        duration = int(data.get("duration", 60))
        voice_name = data.get("voice_name", "Adam")
        first_name = data.get("first_name", "")
        hashtags = data.get("hashtags", "")

        telegram_send_message(chat_id, f"🎬 Montage en cours...\n\n📌 {title}\n⏱ {duration}s\n\n⬇️ Téléchargement des clips...")

        # Télécharge les clips
        clip_paths = []
        for i, url in enumerate(clips_urls[:6]):
            if not url:
                continue
            clip_path = os.path.join(tmpdir, f"clip_{i}.mp4")
            try:
                download_file(url, clip_path)
                if os.path.exists(clip_path) and os.path.getsize(clip_path) > 1000:
                    clip_paths.append(clip_path)
            except Exception as e:
                print(f"Clip {i} error: {e}")

        if not clip_paths:
            telegram_send_message(chat_id, "❌ Erreur: impossible de télécharger les clips.")
            return

        telegram_send_message(chat_id, f"✅ {len(clip_paths)} clips téléchargés\n\n🎙 Génération voix-off ElevenLabs...")

        # Génère la voix avec ElevenLabs
        audio_path = os.path.join(tmpdir, "voix.mp3")
        try:
            generate_voice(script, voice_id, audio_path)
        except Exception as e:
            print(f"ElevenLabs error: {e}")
            audio_path = None

        # Écrit le fichier SRT
        srt_path = os.path.join(tmpdir, "subtitles.srt")
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt_content)

        telegram_send_message(chat_id, "✅ Voix générée\n\n🎞 Assemblage et montage FFmpeg...")

        # Traite chaque clip: resize 9:16
        clip_duration = duration / len(clip_paths)
        processed_clips = []
        for i, clip_path in enumerate(clip_paths):
            out = os.path.join(tmpdir, f"proc_{i}.mp4")
            cmd = [
                "ffmpeg", "-y", "-i", clip_path,
                "-t", str(clip_duration),
                "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-an", "-r", "30", out
            ]
            subprocess.run(cmd, capture_output=True, timeout=120)
            if os.path.exists(out) and os.path.getsize(out) > 1000:
                processed_clips.append(out)

        if not processed_clips:
            telegram_send_message(chat_id, "❌ Erreur lors du traitement des clips.")
            return

        # Concatène les clips
        concat_list = os.path.join(tmpdir, "concat.txt")
        with open(concat_list, "w") as f:
            for p in processed_clips:
                f.write(f"file '{p}'\n")

        concat_output = os.path.join(tmpdir, "concat.mp4")
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", concat_list, "-c", "copy", concat_output
        ], capture_output=True, timeout=120)

        # Montage final: vidéo + audio + sous-titres
        final_output = os.path.join(tmpdir, "reel_final.mp4")
        vf = f"subtitles='{srt_path}':force_style='FontSize=16,PrimaryColour=&HFFFFFF,OutlineColour=&H80000000,BorderStyle=4,Outline=1,Shadow=0,Alignment=2,MarginV=60'"

        if audio_path and os.path.exists(audio_path):
            cmd = [
                "ffmpeg", "-y", "-i", concat_output, "-i", audio_path,
                "-vf", vf, "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                "-c:a", "aac", "-b:a", "192k", "-shortest",
                "-movflags", "+faststart", final_output
            ]
        else:
            cmd = [
                "ffmpeg", "-y", "-i", concat_output,
                "-vf", vf, "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                "-movflags", "+faststart", final_output
            ]

        result = subprocess.run(cmd, capture_output=True, timeout=300)

        if not os.path.exists(final_output) or os.path.getsize(final_output) < 1000:
            telegram_send_message(chat_id, f"❌ Erreur montage: {result.stderr.decode()[:200]}")
            return

        size_mb = os.path.getsize(final_output) / (1024 * 1024)
        telegram_send_message(chat_id, f"✅ Vidéo montée ({size_mb:.1f} MB)\n\n📤 Envoi sur Telegram...")

        caption = f"🎬 {title}\n⏱ {duration}s | 🎙 {voice_name}"
        if first_name:
            caption += f"\n👤 Par: {first_name}"
        if hashtags:
            caption += f"\n\n{hashtags}"

        telegram_send_video(chat_id, final_output, caption)

    except Exception as e:
        print(f"Global error: {e}")
        telegram_send_message(chat_id, f"❌ Erreur inattendue: {str(e)[:200]}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "Reel Agent Server"})

@app.route("/render", methods=["POST"])
def render():
    data = request.json
    if not data:
        return jsonify({"error": "No data"}), 400
    chat_id = data.get("chat_id", "-5213698485")
    thread = threading.Thread(target=process_reel, args=(data, chat_id))
    thread.daemon = True
    thread.start()
    return jsonify({"status": "processing"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
