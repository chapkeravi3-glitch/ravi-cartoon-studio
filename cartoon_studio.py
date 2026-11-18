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


def pick_model(key, wanted):
    """Google के पास जो मॉडल अभी चालू हैं, उनमें से सही वाला अपने-आप चुनो।"""
    try:
        r = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                         params={"key": key, "pageSize": 200}, timeout=30)
        r.raise_for_status()
        names = [m["name"].split("/")[-1] for m in r.json().get("models", [])
                 if "generateContent" in m.get("supportedGenerationMethods", [])]
    except Exception:
        return wanted
    if wanted in names:
        return wanted
    bad = ("lite", "image", "tts", "live", "audio", "embed", "vision", "robotics", "computer")
    flash = sorted([n for n in names if "flash" in n and not any(b in n for b in bad)], reverse=True)
    stable = [n for n in flash if "preview" not in n and "exp" not in n]
    pool = stable or flash or names
    return pool[0] if pool else wanted


def gemini_scenes(story, key, model, n, style, genre="अपने-आप पहचानो"):
    story = re.sub(r"^\s*सीन\s*\d+\s*[:：.\-]\s*", "", story, flags=re.M)  # "सीन 1:" जैसे लेबल हटाओ
    prompt = f"""तुम एक कार्टून एनिमेशन डायरेक्टर हो। नीचे की स्क्रिप्ट (कहानी, खबर, क्रिकेट, तथ्य - कुछ भी) को ठीक {n} सीन में बाँटो।
स्क्रिप्ट का प्रकार: {genre}
सख़्त नियम:
- हर सीन की तस्वीर में कम से कम एक कार्टून कैरेक्टर साफ़ दिखे जो उस सीन का काम कर रहा हो। खाली मैदान, सिर्फ़ फूल या सिर्फ़ नज़ारा बिल्कुल नहीं।
- स्क्रिप्ट किसी भी तरह की हो, विषय के हिसाब से कैरेक्टर बनाओ:
  * कहानी: कहानी के पात्र (इंसान, जानवर, राजा आदि)।
  * फ़िल्मी: फ़िल्म के हीरो, हीरोइन, विलेन जैसे अलग दिखने वाले कार्टून पात्र, उनके रोल और कपड़ों से।
  * ऐतिहासिक: उस दौर के कपड़ों वाले राजा, सैनिक, आम लोग, दरबार, किला, युद्ध का माहौल।
  * फैक्ट/जानकारी: एक कार्टून होस्ट (प्रोफ़ेसर या गाइड जैसा) जो चीज़ें दिखाकर समझा रहा हो, और विषय की चीज़ें (जैसे ग्रह, जानवर, मशीन) कार्टून रूप में।
  * खेल/खबर: खिलाड़ी, भीड़, कमेंटेटर या एंकर।
- असली या मशहूर लोगों और फ़िल्मी किरदारों के नाम तस्वीर के वर्णन में मत लिखो। उनकी जगह भूमिका, उम्र, कपड़े और रंग लिखो (जैसे "cartoon Mughal emperor in white robe and jeweled turban")।
- हर सीन में विषय की चीज़ें दिखें और कैरेक्टर का हावभाव/एक्शन साफ़ लिखो।
- narration में स्क्रिप्ट की बात ही रखो, अपनी तरफ़ से बातें मत जोड़ो।
सिर्फ़ JSON लौटाओ, इस रूप में:
{{"characters": {{"नाम/भूमिका": "English में कैरेक्टर का पूरा फ़िक्स्ड वर्णन: कपड़े के रंग, चेहरा, बाल, खास निशानी"}},
 "scenes": [{{"narration": "इस सीन की हिंदी नैरेशन (2-3 छोटे वाक्य, बोलने लायक)",
              "image_prompt": "English में: कौन-से कार्टून कैरेक्टर (पूरा वर्णन हर बार दोहराओ) क्या एक्शन कर रहे हैं, जगह, चीज़ें, मूड। शुरुआत कैरेक्टर से करो"}}]}}
स्क्रिप्ट:
{story}"""
    cands = []
    for m in [pick_model(key, model), model, "gemini-flash-latest", "gemini-2.5-flash", "gemini-2.0-flash"]:
        if m and m not in cands:
            cands.append(m)
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.7}}
    last = None
    # दो रास्ते: सामान्य Gemini API (AIza key) और Vertex express (AQ. key)
    routes = [("https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent", "AI Studio"),
              ("https://aiplatform.googleapis.com/v1/publishers/google/models/{m}:generateContent", "Vertex")]
    for m in cands:
        for base, rname in routes:
            url = base.format(m=m)
            for _ in range(2):
                try:
                    r = requests.post(url, params={"key": key}, json=body, timeout=120)
                    if r.status_code in (400, 401, 403, 404):
                        last = f"{rname}/{m}: {r.status_code} {r.text[:160]}"
                        break
                    if not r.ok:
                        last = f"{rname}/{m}: {r.status_code} {r.text[:160]}"
                        continue
                    txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                    txt = re.sub(r"^```(?:json)?|```$", "", txt.strip()).strip()
                    data = json.loads(txt)
                    if data.get("scenes"):
                        st.session_state["used_model"] = f"{m} ({rname})"
                        return data
                except Exception as e:
                    last = f"{rname}/{m}: {e}"
    # आख़िरी रास्ता: बिना key और बिना बिलिंग वाला मुफ़्त टेक्स्ट AI (Pollinations)
    try:
        r = requests.post("https://text.pollinations.ai/openai",
                          json={"model": "openai", "response_format": {"type": "json_object"},
                                "messages": [{"role": "user", "content": prompt}]}, timeout=180)
        if r.ok:
            txt = r.json()["choices"][0]["message"]["content"]
            txt = re.sub(r"^```(?:json)?|```$", "", txt.strip()).strip()
            data = json.loads(txt)
            if data.get("scenes"):
                st.session_state["used_model"] = "मुफ़्त Pollinations AI"
                return data
        last = f"{last} | Pollinations: {r.status_code} {r.text[:120]}"
    except Exception as e:
        last = f"{last} | Pollinations: {e}"
    raise RuntimeError(f"सीन नहीं बने: {last}")


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


def gemini_image(prompt, key):
    """Pollinations न चले तो Gemini की इमेज से तस्वीर बनाओ (दोनों रास्ते)।"""
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}}
    routes = ["https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent",
              "https://aiplatform.googleapis.com/v1/publishers/google/models/{m}:generateContent"]
    for m in ["gemini-2.5-flash-image", "gemini-2.0-flash-preview-image-generation"]:
        for base in routes:
            try:
                r = requests.post(base.format(m=m), params={"key": key}, json=body, timeout=120)
                if not r.ok:
                    continue
                for p in r.json()["candidates"][0]["content"]["parts"]:
                    d = p.get("inlineData") or p.get("inline_data")
                    if d:
                        import base64
                        return Image.open(io.BytesIO(base64.b64decode(d["data"]))).convert("RGB")
            except Exception:
                continue
    return None


def make_image(prompt, path, seed, style_txt, key="", allow_blank=False, msg=None):
    import time
    full = (f"{prompt}, {style_txt}, cartoon characters clearly visible in the foreground, "
            "no text, no watermark, high quality")
    url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(full)
           + f"?width=1280&height=720&seed={seed}&nologo=true&model=flux")
    for attempt in range(4):
        # मुफ़्त सर्विस में दो तस्वीरों के बीच ~16 सेकंड का अंतर चाहिए
        wait = 16 - (time.time() - st.session_state.get("last_img", 0))
        if wait > 0:
            if msg:
                msg.info(f"मुफ़्त सर्विस के नियम से {int(wait)+1} सेकंड रुक रहा हूँ...")
            time.sleep(wait)
        st.session_state["last_img"] = time.time()
        try:
            r = requests.get(url, timeout=150)
            if r.ok and r.headers.get("content-type", "").startswith("image"):
                img = Image.open(io.BytesIO(r.content)).convert("RGB")
                img.resize((1920, 1080)).save(path, quality=92)
                return
        except Exception:
            pass
        seed += 7
    if key:
        img = gemini_image(full, key)
        if img is not None:
            img.resize((1920, 1080)).save(path, quality=92)
            return
    if allow_blank:
        fallback_image(seed).save(path, quality=92)
        return
    raise RuntimeError("कार्टून तस्वीर नहीं बन पाई (इमेज सर्विस अभी व्यस्त है)। "
                       "दोबारा दबाओ - जो सीन बन चुके हैं वे दोबारा नहीं बनेंगे।")


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
    gmodel = st.text_input("Gemini मॉडल (न चले तो अपने-आप बदल जाएगा)", value="gemini-2.5-flash")
    gkey = gkey.strip().strip('"').strip("'")
    style_name = st.selectbox("कार्टून स्टाइल", list(STYLES))
    genre = st.selectbox("स्क्रिप्ट किस तरह की है", ["अपने-आप पहचानो", "कहानी", "फ़िल्मी", "ऐतिहासिक", "फैक्ट/जानकारी", "खेल/खबर"])
    voice_name = st.selectbox("आवाज़", list(VOICES))
    n_scenes = st.slider("कितने सीन", 4, 20, 10)
    allow_blank = st.checkbox("तस्वीर न बने तो सादा बैकग्राउंड लगाओ", value=False)
    music = st.file_uploader("बैकग्राउंड म्यूज़िक (वैकल्पिक)", type=["mp3", "wav", "m4a"])
    if st.button("🗑️ सब कैश साफ़ करो"):
        shutil.rmtree(ROOT, ignore_errors=True)
        st.session_state.clear()
        st.rerun()

story = st.text_area("अपनी कहानी यहाँ डालो", height=220,
                     placeholder="एक बार की बात है, एक छोटा सा शेर जंगल में खो गया...")
pid = hashlib.md5((story + style_name + str(n_scenes) + genre + "v3").encode()).hexdigest()[:10]
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
                data = gemini_scenes(story, gkey, gmodel, n_scenes, style_name, genre)
                json.dump(data, open(scene_file, "w"), ensure_ascii=False)
                st.session_state["pid"] = pid
                st.success(f"सीन बन गए (मॉडल: {st.session_state.get('used_model')})")
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
                    make_image(s["image_prompt"], ip, 1000 + i * 13, STYLES[style_name], gkey, allow_blank, msg)
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
