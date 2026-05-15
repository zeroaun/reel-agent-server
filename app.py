from flask import Flask, request, jsonify
import os, requests, subprocess, tempfile, threading, shutil, json, re

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
ELEVENLABS_KEY = os.environ.get("ELEVENLABS_KEY", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_KEY", "")
PEXELS_KEY = os.environ.get("PEXELS_KEY", "")

def telegram_send_message(chat_id, text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10
        )
    except Exception as e:
        print(f"Telegram msg error: {e}")

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

def claude_generate_script(prompt):
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": ANTHROPIC_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    system = (
        "Tu es expert en réels viraux Instagram TikTok YouTube Shorts. "
        "Réponds UNIQUEMENT avec un JSON valide sans markdown ni backticks ni commentaires."
    )
    user = (
        f"Demande: {prompt}\n\n"
        'JSON attendu: {"brief":"résumé","duration":60,"langue":"fr","style":"business","ton":"educatif",'
        '"voice_id":"pNInz6obpgDQGcFmaJgB","voice_name":"Adam","script":"texte voix-off complet adapté à la durée",'
        '"title":"Titre accrocheur max 8 mots","keywords_pexels":["en1","en2","en3","en4","en5"],'
        '"hashtags":["#tag1","#tag2","#tag3","#tag4","#tag5","#tag6","#tag7","#tag8"]}\n\n'
        "Règles: duration extraire (30/60/90/120) défaut 60, langue détecter défaut fr, "
        "style cinematic/urban/nature/business/lifestyle, ton motivant/educatif/storytelling/direct/emotionnel, "
        "voices pNInz6obpgDQGcFmaJgB=Adam EXAVITQu4vr4xnSDxMaL=Bella VR6AewLTigWG4xSOukaG=Arnold jBpfuIE2acCO8z3wKNLl=Freya, "
        "script 130 mots/min, keywords EN ANGLAIS obligatoirement."
    )
    body = {
        "model": "claude-haiku-4-5",
        "max_tokens": 2000,
        "system": system,
        "messages": [{"role": "user", "content": user}]
    }
    r = requests.post(url, json=body, headers=headers, timeout=30)
    r.raise_for_status()
    raw = r.json()["content"][0]["text"]
    raw = re.sub(r'```json|```', '', raw).strip()
    return json.loads(raw)

def pexels_search(keywords, style):
    style_map = {"cinematic": "cinematic", "urban": "urban street", "nature": "nature outdoor", "business": "business professional", "lifestyle": "lifestyle"}
    query = f"{style_map.get(style, 'cinematic')} {keywords[0]} {keywords[1] if len(keywords) > 1 else ''}"
    r = requests.get(
        f"https://api.pexels.com/videos/search?query={requests.utils.quote(query)}&per_page=8&min_duration=5&max_duration=30&orientation=portrait",
        headers={"Authorization": PEXELS_KEY},
        timeout=30
    )
    r.raise_for_status()
    videos = r.json().get("videos", [])
    clips = []
    for v in videos[:6]:
        hd = next((f for f in v.get("video_files", []) if f.get("quality") == "hd" and f.get("width", 0) >= 720), None)
        sd = next((f for f in v.get("video_files", []) if f.get("quality") == "sd"), None)
        file = hd or sd or (v.get("video_files", [{}])[0] if v.get("video_files") else None)
        if file and file.get("link"):
            clips.append(file["link"])
    return clips

def generate_voice(script, voice_id, dest_path):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {"xi-api-key": ELEVENLABS_KEY, "Content-Type": "application/json"}
    body = {"text": script, "model_id": "eleven_multilingual_v2", "voice_settings": {"stability": 0.5, "similarity_boost": 0.8, "style": 0.3, "use_speaker_boost": True}}
    r = requests.post(url, json=body, headers=headers, timeout=60)
    r.raise_for_status()
    with open(dest_path, "wb") as f:
        f.write(r.content)

def build_srt(script, duration):
    words = script.split()
    if not words:
        return ""
    wps = max(3, len(words) // max(1, int(duration / 3)))
    subs = []
    for i in range(0, len(words), wps):
        chunk = " ".join(words[i:i+wps])
        t_start = (i / len(words)) * duration
        t_end = min(((i + wps) / len(words)) * duration, duration)
        def fmt(t):
            ms = int(t * 1000)
            h, ms = divmod(ms, 3600000)
            m, ms = divmod(ms, 60000)
            s, ms = divmod(ms, 1000)
            return f"{h:02}:{m:02}:{s:02},{ms:03}"
        subs.append(f"{len(subs)+1}\n{fmt(t_start)} --> {fmt(t_end)}\n{chunk}\n")
    return "\n".join(subs)

def process_reel(prompt, chat_id, first_name):
    tmpdir = tempfile.mkdtemp()
    try:
        telegram_send_message(chat_id, f"⏳ Génération en cours pour {first_name}...\n\n1️⃣ Script Claude AI\n2️⃣ Clips Pexels\n3️⃣ Voix ElevenLabs\n4️⃣ Montage FFmpeg\n\nEnviron 2-3 minutes...")

        # 1. Script avec Claude
        try:
            data = claude_generate_script(prompt)
        except Exception as e:
            telegram_send_message(chat_id, f"❌ Erreur Claude: {str(e)[:200]}")
            return

        title = data.get("title", "Réel")
        duration = int(data.get("duration", 60))
        script = data.get("script", "")
        voice_id = data.get("voice_id", "pNInz6obpgDQGcFmaJgB")
        voice_name = data.get("voice_name", "Adam")
        keywords = data.get("keywords_pexels", ["business"])
        style = data.get("style", "cinematic")
        hashtags = " ".join(data.get("hashtags", []))

        telegram_send_message(chat_id, f"✅ Script: {title}\n\n⬇️ Clips Pexels...")

        # 2. Clips Pexels
        try:
            clips_urls = pexels_search(keywords, style)
        except Exception as e:
            telegram_send_message(chat_id, f"❌ Erreur Pexels: {str(e)[:200]}")
            return

        if not clips_urls:
            telegram_send_message(chat_id, "❌ Aucun clip Pexels trouvé.")
            return

        # 3. Télécharge clips
        clip_paths = []
        for i, url in enumerate(clips_urls[:6]):
            path = os.path.join(tmpdir, f"clip_{i}.mp4")
            try:
                download_file(url, path)
                if os.path.exists(path) and os.path.getsize(path) > 1000:
                    clip_paths.append(path)
            except Exception as e:
                print(f"Clip {i} error: {e}")

        if not clip_paths:
            telegram_send_message(chat_id, "❌ Impossible de télécharger les clips.")
            return

        telegram_send_message(chat_id, f"✅ {len(clip_paths)} clips téléchargés\n\n🎙 Voix ElevenLabs...")

        # 4. Voix ElevenLabs
        audio_path = os.path.join(tmpdir, "voix.mp3")
        try:
            generate_voice(script, voice_id, audio_path)
        except Exception as e:
            print(f"ElevenLabs error: {e}")
            audio_path = None

        # 5. SRT
        srt_content = build_srt(script, duration)
        srt_path = os.path.join(tmpdir, "subtitles.srt")
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt_content)

        telegram_send_message(chat_id, "✅ Voix générée\n\n🎞 Montage FFmpeg...")

        # 6. Traite clips 9:16
        clip_duration = duration / len(clip_paths)
        processed = []
        for i, cp in enumerate(clip_paths):
            out = os.path.join(tmpdir, f"proc_{i}.mp4")
            subprocess.run([
                "ffmpeg", "-y", "-i", cp, "-t", str(clip_duration),
                "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-an", "-r", "30", out
            ], capture_output=True, timeout=120)
            if os.path.exists(out) and os.path.getsize(out) > 1000:
                processed.append(out)

        if not processed:
            telegram_send_message(chat_id, "❌ Erreur traitement clips.")
            return

        # 7. Concat
        concat_list = os.path.join(tmpdir, "concat.txt")
        with open(concat_list, "w") as f:
            for p in processed:
                f.write(f"file '{p}'\n")
        concat_out = os.path.join(tmpdir, "concat.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", concat_out], capture_output=True, timeout=120)

        # 8. Montage final
        final = os.path.join(tmpdir, "reel_final.mp4")
        vf = f"subtitles='{srt_path}':force_style='FontSize=16,PrimaryColour=&HFFFFFF,OutlineColour=&H80000000,BorderStyle=4,Outline=1,Shadow=0,Alignment=2,MarginV=60'"
        if audio_path and os.path.exists(audio_path):
            cmd = ["ffmpeg", "-y", "-i", concat_out, "-i", audio_path, "-vf", vf, "-c:v", "libx264", "-preset", "fast", "-crf", "22", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", final]
        else:
            cmd = ["ffmpeg", "-y", "-i", concat_out, "-vf", vf, "-c:v", "libx264", "-preset", "fast", "-crf", "22", "-movflags", "+faststart", final]

        result = subprocess.run(cmd, capture_output=True, timeout=300)

        if not os.path.exists(final) or os.path.getsize(final) < 1000:
            telegram_send_message(chat_id, f"❌ Erreur montage: {result.stderr.decode()[:200]}")
            return

        size_mb = os.path.getsize(final) / (1024 * 1024)
        telegram_send_message(chat_id, f"✅ Vidéo prête ({size_mb:.1f} MB)\n\n📤 Envoi Telegram...")

        caption = f"🎬 {title}\n⏱ {duration}s | 🎙 {voice_name}\n👤 Par: {first_name}"
        if hashtags:
            caption += f"\n\n{hashtags}"
        telegram_send_video(chat_id, final, caption)

    except Exception as e:
        print(f"Global error: {e}")
        telegram_send_message(chat_id, f"❌ Erreur: {str(e)[:200]}")
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
    prompt = data.get("prompt", "")
    chat_id = data.get("chat_id", "")
    first_name = data.get("first_name", "Utilisateur")
    if not prompt or not chat_id:
        return jsonify({"error": "prompt and chat_id required"}), 400
    thread = threading.Thread(target=process_reel, args=(prompt, chat_id, first_name))
    thread.daemon = True
    thread.start()
    return jsonify({"status": "processing"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
