from flask import Flask, request, jsonify
import os, requests, subprocess, tempfile, threading, uuid

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
GROUP_ID = os.environ.get("GROUP_ID", "-5213698485")

def download_file(url, dest):
    r = requests.get(url, stream=True, timeout=60)
    with open(dest, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)

def send_telegram_message(text):
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": GROUP_ID, "text": text}
    )

def send_telegram_video(video_path, caption):
    with open(video_path, "rb") as f:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo",
            data={"chat_id": GROUP_ID, "caption": caption, "supports_streaming": True},
            files={"video": f}
        )

def process_reel(data):
    job_id = str(uuid.uuid4())[:8]
    tmpdir = tempfile.mkdtemp()

    try:
        clips_urls = data.get("clips_urls", [])
        audio_url = data.get("audio_url", "")
        srt_content = data.get("srt_content", "")
        title = data.get("title", "Réel")
        duration = int(data.get("duration", 60))
        voice_name = data.get("voice_name", "Adam")
        first_name = data.get("first_name", "")

        send_telegram_message(f"🎬 Montage en cours...\n\n📌 {title}\n⏱ {duration}s\n\nÉtape 1/4: Téléchargement des clips...")

        # Télécharge les clips
        clip_paths = []
        for i, url in enumerate(clips_urls[:6]):
            if not url:
                continue
            clip_path = os.path.join(tmpdir, f"clip_{i}.mp4")
            try:
                download_file(url, clip_path)
                clip_paths.append(clip_path)
            except Exception as e:
                print(f"Erreur clip {i}: {e}")

        if not clip_paths:
            send_telegram_message("❌ Erreur: Impossible de télécharger les clips Pexels.")
            return

        send_telegram_message(f"✅ {len(clip_paths)} clips téléchargés\n\nÉtape 2/4: Téléchargement audio...")

        # Télécharge l'audio
        audio_path = os.path.join(tmpdir, "voix.mp3")
        if audio_url:
            download_file(audio_url, audio_path)
        
        # Fichier SRT
        srt_path = os.path.join(tmpdir, "subtitles.srt")
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt_content)

        send_telegram_message("✅ Audio téléchargé\n\nÉtape 3/4: Assemblage et montage...")

        # Prépare chaque clip: resize en 9:16 + durée égale
        clip_duration = duration / len(clip_paths)
        processed_clips = []

        for i, clip_path in enumerate(clip_paths):
            out = os.path.join(tmpdir, f"proc_{i}.mp4")
            cmd = [
                "ffmpeg", "-y",
                "-i", clip_path,
                "-t", str(clip_duration),
                "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1",
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-an",
                "-r", "30",
                out
            ]
            subprocess.run(cmd, capture_output=True)
            if os.path.exists(out):
                processed_clips.append(out)

        # Concatène tous les clips
        concat_list = os.path.join(tmpdir, "concat.txt")
        with open(concat_list, "w") as f:
            for p in processed_clips:
                f.write(f"file '{p}'\n")

        concat_output = os.path.join(tmpdir, "concat.mp4")
        subprocess.run([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", concat_list,
            "-c", "copy",
            concat_output
        ], capture_output=True)

        # Ajoute l'audio + sous-titres
        final_output = os.path.join(tmpdir, f"reel_final_{job_id}.mp4")

        if audio_url and os.path.exists(audio_path):
            cmd = [
                "ffmpeg", "-y",
                "-i", concat_output,
                "-i", audio_path,
                "-vf", f"subtitles={srt_path}:force_style='FontSize=14,PrimaryColour=&HFFFFFF,OutlineColour=&H80000000,BorderStyle=4,Outline=1,Shadow=0,Alignment=2,MarginV=50'",
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                "-movflags", "+faststart",
                final_output
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-i", concat_output,
                "-vf", f"subtitles={srt_path}:force_style='FontSize=14,PrimaryColour=&HFFFFFF,OutlineColour=&H80000000,BorderStyle=4,Outline=1,Shadow=0,Alignment=2,MarginV=50'",
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-movflags", "+faststart",
                final_output
            ]

        result = subprocess.run(cmd, capture_output=True)

        if not os.path.exists(final_output):
            send_telegram_message(f"❌ Erreur montage FFmpeg:\n{result.stderr.decode()[:500]}")
            return

        size_mb = os.path.getsize(final_output) / (1024 * 1024)
        send_telegram_message(f"✅ Vidéo montée ({size_mb:.1f} MB)\n\nÉtape 4/4: Envoi sur Telegram...")

        caption = f"🎬 {title}\n⏱ {duration}s | 🎙 {voice_name}"
        if first_name:
            caption += f"\n👤 Par: {first_name}"

        send_telegram_video(final_output, caption)
        send_telegram_message("✅ Réel prêt ! Envoie un nouveau sujet pour un autre réel 🚀")

    except Exception as e:
        send_telegram_message(f"❌ Erreur inattendue: {str(e)}")
    finally:
        # Nettoyage
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "Reel Agent Server"})

@app.route("/render", methods=["POST"])
def render():
    data = request.json
    if not data:
        return jsonify({"error": "No data"}), 400
    
    # Lance le montage en arrière-plan
    thread = threading.Thread(target=process_reel, args=(data,))
    thread.daemon = True
    thread.start()

    return jsonify({
        "status": "processing",
        "message": "Montage démarré en arrière-plan"
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
