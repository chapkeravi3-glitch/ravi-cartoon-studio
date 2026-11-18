import asyncio, hashlib, io, json, os, random, re, shutil, subprocess, urllib.parse
import requests, streamlit as st
from PIL import Image, ImageDraw

try:
    import edge_tts
except ImportError:
    edge_tts = None

W, H, FPS = 1280, 720, 25
ROOT = "cartoon_projects"
STYLES = {
    "3D Pixar जैसा कार्टून": "3D animated Pixar style cartoon, vibrant colors, soft lighting, cute big eyes",
    "2D फ़्लैट कार्टून": "2D flat vector cartoon illustration, bold outlines, bright colors",
    "एनिमे स्टाइल": "anime style illustration, detailed background, vivid colors",
    "बच्चों की स्टोरीबुक": "children's storybook watercolor illustration, warm and friendly",
}
VOICES = {
    "हिंदी महिला (Swara)": "hi-IN-SwaraNeural",
    "हिंदी पुरुष (Madhur)": "hi-IN-MadhurNeural",
}

st.set_page_config(page_title="Ravi Cartoon Studio", page_icon="🎬", layout="centered")
st.title("🎬 Ravi Cartoon Studio")
st.caption("कहानी डालो → कार्टून कैरेक्टर वाला एनिमेटेड वीडियो")


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-800:])
    return r.stdout


def audio_len(path):
    out = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration",
              "-of", "default=nw=1:nk=1", path])
    return float(out.strip())


def gemini_scenes(story, key, model, n, style):
    prompt = f"""तुम एक कार्टून एनिमेशन डायरेक्टर हो। नीचे की कहानी को ठीक {n} सीन में बाँटो।
सिर्फ़ JSON लौटाओ, इस रूप में:
{{"characters": {{"नाम": "English में कैरेक्टर का पूरा फ़िक्स्ड वर्णन: उम्र, कपड़े के रंग, बाल, चेहरा, खास निशानी"}},
 "scenes": [{{"narration": "इस सीन की हिंदी नैरेशन (2-3 छोटे वाक्य, बोलने लायक)",
              "image_prompt": "English में इस सीन की तस्वीर का वर्णन: कौन सा कैरेक्टर क्या कर रहा है, जगह, मूड। कैरेक्टर का पूरा वर्णन हर बार दोहराओ ताकि सब सीन में एक जैसा दिखे"}}]}}
कहानी:
{story}"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.7}}
    last = None
    for _ in range(3):
        try:
            r = requests.post(url, json=body, timeout=120)
            r.raise_for_status()
            txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            txt = re.sub(r"^```(?:json)?|```$", "", txt.strip()).strip()
            data = json.loads(txt)
            if data.get("scenes"):
                return data
        except Exception as e:
            last = e
    raise RuntimeError(f"Gemini से सीन नहीं बने: {last}")


def fallback_image(seed):
    rnd = random.Random(seed)
    img = Image.new("RGB", (1920, 1080))
    d = ImageDraw.Draw(img)
    top, bot = (rnd.randint(90, 180), rnd.randint(150, 220), 255), (255, 235, 180)
    for y in range(1080):
        t = y / 1080
        d.line([(0, y), (1920, y)], fill=tuple(int(top[i] * (1 - t) + bot[i] * t) for i in range(3)))
    d.ellipse([1500, 100, 1700, 300], fill=(255, 220, 60))
    for i in range(3):
        c = (rnd.randint(40, 110), rnd.randint(150, 200), rnd.randint(60, 110))
        x = i * 700 - 200
        d.ellipse([x, 700, x + 1100, 1500], fill=c)
    return img


def make_image(prompt, path, seed, style_txt):
    full = f"{prompt}, {style_txt}, no text, no watermark, high quality"
    url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(full)
           + f"?width=1280&height=720&seed={seed}&nologo=true&model=flux")
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=120)
            if r.ok and r.headers.get("content-type", "").startswith("image"):
                img = Image.open(io.BytesIO(r.content)).convert("RGB")
                img.resize((1920, 1080)).save(path, quality=92)
                return True
        except Exception:
            pass
        seed += 7
    fallback_image(seed).save(path, quality=92)
    return False


def make_voice(text, path, voice):
    if edge_tts is None:
        raise RuntimeError("edge-tts इंस्टॉल नहीं है (requirements.txt देखो)")
    asyncio.run(edge_tts.Communicate(text, voice, rate="-8%").save(path))


def make_clip(img, aud, out, idx):
    dur = audio_len(aud) + 0.4
    n = int(dur * FPS)
    mode = idx % 4
    if mode == 0:
        z = f"z='min(zoom+0.0010,1.30)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    elif mode == 1:
        z = f"z='if(eq(on,0),1.30,max(zoom-0.0010,1.0))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    elif mode == 2:
        z = f"z=1.25:x='(iw-iw/zoom)*on/{n}':y='ih/2-(ih/zoom/2)'"
    else:
        z = f"z=1.25:x='(iw-iw/zoom)*(1-on/{n})':y='(ih-ih/zoom)*on/{n}'"
    vf = (f"scale=1920:1080,zoompan={z}:d={n}:s={W}x{H}:fps={FPS},"
          f"fade=t=in:st=0:d=0.4,fade=t=out:st={dur-0.4:.2f}:d=0.4,format=yuv420p")
    sh(["ffmpeg", "-y", "-loop", "1", "-i", img, "-i", aud, "-vf", vf, "-af", "apad",
        "-t", f"{dur:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-r", str(FPS),
        "-c:a", "aac", "-ar", "44100", "-ac", "2", out])


def join_clips(clips, out, music=None, vol=0.12):
    lst = out + ".txt"
    with open(lst, "w") as f:
        for c in clips:
            f.write(f"file '{os.path.abspath(c)}'\n")
    tmp = out + ".tmp.mp4"
    sh(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", tmp])
    if music:
        sh(["ffmpeg", "-y", "-i", tmp, "-stream_loop", "-1", "-i", music, "-filter_complex",
            f"[1:a]volume={vol}[m];[0:a][m]amix=inputs=2:duration=first[a]",
            "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", out])
        os.remove(tmp)
    else:
        os.replace(tmp, out)


# ---------------- UI ----------------
key_default = st.secrets.get("GEMINI_API_KEY", "") if hasattr(st, "secrets") else ""
with st.sidebar:
    st.header("सेटिंग")
    gkey = st.text_input("Gemini API Key", value=key_default, type="password")
    gmodel = st.text_input("Gemini मॉडल", value="gemini-2.5-flash")
    style_name = st.selectbox("कार्टून स्टाइल", list(STYLES))
    voice_name = st.selectbox("आवाज़", list(VOICES))
    n_scenes = st.slider("कितने सीन", 4, 20, 10)
    music = st.file_uploader("बैकग्राउंड म्यूज़िक (वैकल्पिक)", type=["mp3", "wav", "m4a"])
    if st.button("🗑️ सब कैश साफ़ करो"):
        shutil.rmtree(ROOT, ignore_errors=True)
        st.session_state.clear()
        st.rerun()

story = st.text_area("अपनी कहानी यहाँ डालो", height=220,
                     placeholder="एक बार की बात है, एक छोटा सा शेर जंगल में खो गया...")
pid = hashlib.md5((story + style_name + str(n_scenes)).encode()).hexdigest()[:10]
pdir = os.path.join(ROOT, pid)
os.makedirs(pdir, exist_ok=True)
scene_file = os.path.join(pdir, "scenes.json")

c1, c2 = st.columns(2)
if c1.button("1️⃣ सीन बनाओ", use_container_width=True):
    if not (story.strip() and gkey):
        st.error("कहानी और Gemini key दोनों चाहिए।")
    else:
        with st.spinner("कहानी को सीन में बाँट रहा हूँ..."):
            try:
                data = gemini_scenes(story, gkey, gmodel, n_scenes, style_name)
                json.dump(data, open(scene_file, "w"), ensure_ascii=False)
                st.session_state["pid"] = pid
            except Exception as e:
                st.error(str(e))

if os.path.exists(scene_file):
    data = json.load(open(scene_file))
    scenes = data["scenes"]
    st.subheader("सीन (चाहो तो बदलो)")
    with st.expander("कैरेक्टर"):
        for k, v in data.get("characters", {}).items():
            st.write(f"**{k}**: {v}")
    for i, s in enumerate(scenes):
        with st.expander(f"सीन {i+1}", expanded=False):
            s["narration"] = st.text_area("नैरेशन", s["narration"], key=f"n{pid}{i}")
            s["image_prompt"] = st.text_area("तस्वीर का वर्णन", s["image_prompt"], key=f"p{pid}{i}")
            ip = os.path.join(pdir, f"img_{i}.jpg")
            if os.path.exists(ip):
                st.image(ip)
            if st.button("🔄 इस सीन को दोबारा बनाओ", key=f"r{pid}{i}"):
                for f in (f"img_{i}.jpg", f"aud_{i}.mp3", f"clip_{i}.mp4", "final.mp4"):
                    p = os.path.join(pdir, f)
                    if os.path.exists(p):
                        os.remove(p)
                st.rerun()
    json.dump(data, open(scene_file, "w"), ensure_ascii=False)

    if c2.button("2️⃣ वीडियो बनाओ", use_container_width=True):
        bar, msg = st.progress(0.0), st.empty()
        try:
            clips = []
            for i, s in enumerate(scenes):
                ip = os.path.join(pdir, f"img_{i}.jpg")
                ap = os.path.join(pdir, f"aud_{i}.mp3")
                cp = os.path.join(pdir, f"clip_{i}.mp4")
                if os.path.exists(cp):  # बन चुका क्लिप दोबारा नहीं बनेगा
                    clips.append(cp)
                    bar.progress((i + 1) / len(scenes))
                    continue
                if not os.path.exists(ip):
                    msg.info(f"सीन {i+1}: कार्टून तस्वीर बन रही है...")
                    make_image(s["image_prompt"], ip, 1000 + i * 13, STYLES[style_name])
                if not os.path.exists(ap):
                    msg.info(f"सीन {i+1}: आवाज़ बन रही है...")
                    make_voice(s["narration"], ap, VOICES[voice_name])
                msg.info(f"सीन {i+1}: एनिमेशन क्लिप बन रहा है...")
                make_clip(ip, ap, cp, i)
                clips.append(cp)
                bar.progress((i + 1) / len(scenes))
            msg.info("सब क्लिप जोड़ रहा हूँ...")
            mp = None
            if music:
                mp = os.path.join(pdir, "music.mp3")
                open(mp, "wb").write(music.getvalue())
            join_clips(clips, os.path.join(pdir, "final.mp4"), mp)
            msg.success("वीडियो तैयार! ✅")
        except Exception as e:
            msg.error(f"रुक गया: {e}\nदोबारा दबाओ - बन चुके क्लिप वहीं से आगे चलेंगे।")

    final = os.path.join(pdir, "final.mp4")
    if os.path.exists(final):
        st.video(final)
        st.download_button("⬇️ वीडियो डाउनलोड करो", open(final, "rb"), "cartoon_story.mp4", "video/mp4")
