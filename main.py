import os, re, json, math, time, wave, array, warnings, asyncio, subprocess
warnings.filterwarnings("ignore")
import requests, feedparser, edge_tts
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import google.generativeai as genai
import imageio_ffmpeg
from moviepy.editor import VideoFileClip, ImageClip, CompositeVideoClip, concatenate_videoclips

FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
os.environ["IMAGEIO_FFMPEG_EXE"] = FFMPEG_EXE
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
PEXELS_KEY = os.environ.get("PEXELS_API_KEY", "").strip()
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)

W, H = 1280, 720
SW, SH = 1080, 1920
FPS = 24
CHANNEL_NAME = "MEDPULSE DAILY"
LOGO_PATH = "logo.jpeg"
VOICE_NAME = "en-US-ChristopherNeural"
VOICE_RATE = "-4%"
VOICE_PITCH = "-2Hz"
MIN_LONG_SEC = 560.0
USED_NEWS_FILE = "used_news.txt"
USED_VIDEOS_FILE = "used_videos.txt"

for d in ["output", "temp"]:
    os.makedirs(d, exist_ok=True)

BANNED = [
    r"\bdr\.?\s*eric\s*berg\b", r"\bdr\.?\s*berg\b", r"\beric\s*berg\b",
    r"\bdr\.?\s*sten\s*ekberg\b", r"\bdr\.?\s*ekberg\b", r"\bdr\.?\s*mandell\b",
    r"\bdr\.?\s*mindy\b", r"\bdr\.?\s*oz\b", r"\bdr\.?\s*hyman\b", r"\bdr\.?\s*huberman\b",
    r"\bdoctor\s+[a-z]+\b", r"\bdr\.?\s+[a-z]+\b", r"\bprofessor\s+[a-z]+\b"
]

def clean_txt(t):
    if not t:
        return ""
    s = re.sub(r"https?://\S+|www\.\S+", "", str(t))
    for pat in BANNED:
        s = re.sub(pat, "medical research", s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip()

def load_set(fp):
    if not os.path.exists(fp):
        return set()
    with open(fp, "r", encoding="utf-8", errors="ignore") as f:
        return set(x.strip() for x in f if x.strip())

def save_item(fp, val):
    with open(fp, "a", encoding="utf-8") as f:
        f.write(str(val).strip() + "\n")

def get_font(sz, bold=True):
    b_p = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
    r_p = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
    d_b = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    d_r = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    for p in ([b_p, d_b] if bold else [r_p, d_r]):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, sz)
            except Exception:
                pass
    return ImageFont.load_default()

def wrap_lines(txt, font, max_w, draw):
    words = clean_txt(txt).split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        bb = draw.textbbox((0, 0), test, font=font)
        if (bb[2] - bb[0]) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines

def split_timed_subs(txt, total_dur, max_words=13):
    words = clean_txt(txt).split()
    if not words:
        return [("", total_dur)]
    chunks = []
    cur = []
    for w in words:
        cur.append(w)
        if len(cur) >= max_words or (len(cur) >= 7 and w.endswith((".", "!", "?", ",", ";", ":"))):
            chunks.append(" ".join(cur))
            cur = []
    if cur:
        if chunks and len(cur) <= 3:
            chunks[-1] = chunks[-1] + " " + " ".join(cur)
        else:
            chunks.append(" ".join(cur))
    tot_chars = max(1, sum(len(c) for c in chunks))
    out = []
    acc = 0.0
    for i, c in enumerate(chunks):
        if i == len(chunks) - 1:
            d = max(0.4, total_dur - acc)
        else:
            d = round(max(0.8, total_dur * (len(c) / float(tot_chars))), 3)
            if acc + d > total_dur - 0.4:
                d = max(0.4, total_dur - acc - 0.4)
        out.append((c, d))
        acc += d
    return out

LIVE_FEEDS = [
    ("Google Trends US", "https://trends.google.com/trending/rss?geo=US"),
    ("Google Trends UK", "https://trends.google.com/trending/rss?geo=GB"),
    ("Google Trends CA", "https://trends.google.com/trending/rss?geo=CA"),
    ("Google News Symptoms", "https://news.google.com/rss/search?q=warning+signs+symptoms+body+health+when:1d&hl=en-US&gl=US&ceid=US:en"),
    ("Google News Vitamins", "https://news.google.com/rss/search?q=vitamin+deficiency+nutrition+metabolism+when:1d&hl=en-US&gl=US&ceid=US:en"),
    ("Google News Organs", "https://news.google.com/rss/search?q=liver+kidney+gut+inflammation+blood+sugar+when:1d&hl=en-US&gl=US&ceid=US:en"),
    ("Google News Heart", "https://news.google.com/rss/search?q=sleep+heart+arteries+cholesterol+blood+pressure+when:1d&hl=en-US&gl=US&ceid=US:en"),
    ("Harvard Health", "https://www.health.harvard.edu/blog/feed"),
    ("Cleveland Clinic", "https://health.clevelandclinic.org/feed/"),
    ("Mayo Clinic", "https://newsnetwork.mayoclinic.org/feed/"),
    ("NIH MedlinePlus", "https://medlineplus.gov/feeds/whatsnew.xml"),
    ("Medical News Today", "https://www.medicalnewstoday.com/rss"),
    ("Healthline", "https://www.healthline.com/rss/health-news"),
    ("ScienceDaily", "https://www.sciencedaily.com/rss/health_medicine.xml"),
    ("Drugs.com", "https://www.drugs.com/feeds/medical_news.xml"),
    ("BBC Health", "http://feeds.bbci.co.uk/news/health/rss.xml"),
    ("NYT Health", "https://rss.nytimes.com/services/xml/rss/nyt/Health.xml")
]

TERMS = [
    "vitamin", "magnesium", "potassium", "zinc", "iron", "calcium", "b12", "liver", "kidney",
    "heart", "gut", "brain", "pancreas", "thyroid", "arteries", "nerve", "blood sugar", "insulin",
    "glucose", "cholesterol", "triglycerides", "blood pressure", "inflammation", "cortisol",
    "metabolism", "belly fat", "fatty liver", "uric acid", "electrolytes", "fasting", "collagen",
    "symptom", "warning", "deficiency", "sign", "fatigue", "sleep", "cramps", "bloating", "digestion"
]

def fetch_live_trend():
    used = load_set(USED_NEWS_FILE)
    hdr = {"User-Agent": "Mozilla/5.0"}
    raw = []
    seeds = ["why does my body ", "early warning signs of ", "symptoms of low ", "best foods to clean "]
    for q in seeds:
        try:
            r = requests.get("https://suggestqueries.google.com/complete/search", params={"client": "firefox", "hl": "en", "gl": "us", "q": q}, headers=hdr, timeout=7)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and len(data) > 1:
                    for s in data[1][:4]:
                        raw.append({"title": clean_txt(s).title(), "summary": clean_txt(s), "url": "https://trends.google.com/trends/", "source": "Google Live Search"})
        except Exception:
            pass
    for s_name, url in LIVE_FEEDS:
        try:
            r = requests.get(url, headers=hdr, timeout=9)
            if r.status_code != 200:
                continue
            for e in feedparser.parse(r.content).entries[:10]:
                t = clean_txt(getattr(e, "title", ""))
                sm = clean_txt(re.sub(r"<[^>]+>", " ", getattr(e, "summary", "")))
                lk = getattr(e, "link", url)
                pub = s_name
                if " - " in t and "Google News" in s_name:
                    t, pub = [x.strip() for x in t.rsplit(" - ", 1)]
                if len(t) >= 18 and t.lower() not in used:
                    raw.append({"title": t, "summary": sm[:320], "url": lk, "source": pub})
        except Exception:
            pass
    wf = {}
    for it in raw:
        for w in re.findall(r"[a-z]{4,}", (it["title"] + " " + it["summary"]).lower()):
            if w not in ["this", "that", "with", "from", "your", "have", "what", "when", "health", "news", "study"]:
                wf[w] = wf.get(w, 0) + 1
    scored = []
    for it in raw:
        blob = (it["title"] + " " + it["summary"]).lower()
        hits = sum(4 for k in TERMS if k in blob)
        if hits == 0 and "Trends" in it["source"]:
            continue
        vel = sum(min(wf.get(w, 0), 8) for w in set(re.findall(r"[a-z]{4,}", it["title"].lower())))
        scored.append((hits * 10 + vel, it))
    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        fb = {"title": "Silent Warning Signs Of Magnesium And Vitamin D Deficiency", "summary": "How hidden micronutrient shortages trigger fatigue, muscle cramps, and poor sleep.", "url": "https://medlineplus.gov/nutrition.html", "source": "NIH MedlinePlus"}
        return {"title": fb["title"], "summary": fb["summary"], "sources": [fb]}
    best = scored[0][1]
    save_item(USED_NEWS_FILE, best["title"].lower())
    b_words = set(re.findall(r"[a-z]{4,}", best["title"].lower()))
    sources = [{"title": best["title"], "source": best["source"], "url": best["url"]}]
    seen = {best["source"].lower()}
    for _, cand in scored[1:]:
        cs = cand["source"].lower()
        if cs in seen:
            continue
        cw = set(re.findall(r"[a-z]{4,}", (cand["title"] + " " + cand["summary"]).lower()))
        if len(b_words.intersection(cw)) >= 1 or len(sources) < 4:
            sources.append({"title": cand["title"], "source": cand["source"], "url": cand["url"]})
            seen.add(cs)
        if len(sources) >= 5:
            break
    return {"title": best["title"], "summary": best["summary"], "sources": sources}

def generate_script(tr):
    prompt = "\n".join([
        "You are an elite viral medical documentary writer for MedPulse Daily.",
        "Today's Live Trending Health Topic: " + tr["title"],
        "Context: " + tr["summary"],
        "STYLE: Suspenseful Countdown from Rank 6 down to Rank 1 (The #1 Most Shocking Warning/Mistake).",
        "STRICT RULES:",
        "1. NEVER mention any doctor's name or person's name anywhere.",
        "2. NEVER include website links or URLs in spoken text.",
        "3. Use SIMPLE everyday English, vivid real-life analogies (car dashboard warning light, clogged kitchen filter, dish soap dissolving grease), and clear food/symptom examples.",
        "4. Create 6 countdown ranks ordered from rank 6 down to rank 1. Each rank MUST have 4 dramatic paragraphs (24 body paragraphs total, 52-65 words each):",
        "   - Paragraph 1: The shocking everyday symptom or silent body alarm.",
        "   - Paragraph 2: Minute-by-minute journey inside the organs using a simple analogy.",
        "   - Paragraph 3: The hidden daily mistake or food trap people think is harmless.",
        "   - Paragraph 4: The 24-hour natural kitchen rescue fix.",
        "5. Every single paragraph MUST have its own unique changing 'headline' (4 to 6 uppercase words) for the top-left live news ticker.",
        "6. Score each paragraph with thrill_score (1 to 100) so the editor can clip the most thrilling moments for the Short.",
        "Return ONLY valid JSON with this exact structure:",
        "{",
        '  "video_title": "Viral Countdown Title (no person names)",',
        '  "short_title": "Viral Short title under 65 chars",',
        '  "thumbnail_hook": "3 TO 4 UPPERCASE WORDS",',
        '  "intro_headline": "BREAKING BODY COUNTDOWN",',
        '  "intro_hook": "55-word high-suspense opening hook teasing the countdown from #6 to the shocking #1 body signal...",',
        '  "intro_query": "human body medical scan",',
        '  "points": [',
        "    {",
        '      "rank": 6,',
        '      "point_title": "Short 4-word title",',
        '      "paragraphs": [',
        '        {"headline": "SILENT MORNING ALARM", "text": "55-word shocking symptom reveal...", "q1": "tired person waking up", "q2": "human nerve cells", "thrill_score": 96},',
        '        {"headline": "INSIDE YOUR BLOODSTREAM", "text": "55-word organ journey with simple analogy...", "q1": "blood flow arteries", "q2": "heart beating medical", "thrill_score": 80},',
        '        {"headline": "THE HIDDEN DAILY TRAP", "text": "55-word shocking daily mistake...", "q1": "sugar coffee cup", "q2": "liver digestion medical", "thrill_score": 94},',
        '        {"headline": "24-HOUR NATURAL RESET", "text": "55-word practical kitchen food fix...", "q1": "fresh green vegetables", "q2": "lemon water glass", "thrill_score": 85}',
        "      ]",
        "    }",
        "  ],",
        '  "outro_headline": "PROTECT YOUR HEALTH DAILY",',
        '  "outro": "45-word warm conclusion asking viewers to like, subscribe to MedPulse Daily, and comment which countdown sign surprised them most.",',
        '  "seo_description": "3-paragraph engaging summary (no links, no person names).",',
        '  "seo_tags": ["health", "wellness", "nutrition", "symptoms", "science"]',
        "}"
    ])
    for m_name in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
        try:
            resp = genai.GenerativeModel(m_name).generate_content(prompt)
            raw = re.sub(r"^" + "\x60\x60\x60" + r"(?:json)?|" + "\x60\x60\x60" + r"$", "", resp.text.strip()).strip()
            m = re.search(r"\{.*\}", raw, flags=re.S)
            if m:
                data = json.loads(m.group(0))
                if len(data.get("points", [])) >= 6:
                    return data
        except Exception:
            time.sleep(2)
    pts = []
    ranks = [6, 5, 4, 3, 2, 1]
    for rnk in ranks:
        pts.append({
            "rank": rnk,
            "point_title": f"Critical Body Signal #{rnk}",
            "paragraphs": [
                {"headline": f"SILENT WARNING SIGNAL #{rnk}", "text": f"Coming in at number {rnk} on our countdown of {tr['title']} is a silent distress signal millions ignore. Just like a red check-engine light flashing on your car dashboard, sudden afternoon exhaustion, stubborn brain fog, or nighttime muscle tightness warns you that your cells are running dangerously low on key nutrients.", "q1": "tired person rubbing eyes", "q2": "medical nerve signal", "thrill_score": 97},
                {"headline": f"INSIDE YOUR CELLS AT #{rnk}", "text": "Within minutes of this imbalance, microscopic pumps inside your organs struggle to move fluids and electrolytes. Picture a kitchen water filter clogged with sediment: when stress hormones and excess glucose build up, oxygen and energy delivery to your brain and heart slows down.", "q1": "blood cells flowing", "q2": "science laboratory", "thrill_score": 78},
                {"headline": f"HIDDEN DAILY MISTAKE #{rnk}", "text": "The biggest hidden trap that accelerates this damage is starting your morning with refined sugar or dehydrating drinks on an empty stomach. That everyday habit acts like pouring sticky syrup onto delicate clockwork gears, forcing your liver into emergency overdrive.", "q1": "pouring sugary soda", "q2": "doctor checking patient", "thrill_score": 95},
                {"headline": f"24-HOUR KITCHEN RESCUE #{rnk}", "text": "Here is how you reverse this within twenty-four hours using your kitchen. Pair mineral-rich leafy greens, pumpkin seeds, and avocado with clean water and a pinch of sea salt so your cells absorb nutrients smoothly and restore natural energy.", "q1": "fresh spinach avocado", "q2": "happy healthy person", "thrill_score": 84}
            ]
        })
    return {
        "video_title": clean_txt(tr["title"]) + " - Countdown From #6 To The #1 Shocking Sign",
        "short_title": "Wait Until You See The #1 Body Warning Sign!",
        "thumbnail_hook": "#1 SILENT BODY ALARM",
        "intro_headline": "URGENT HEALTH COUNTDOWN",
        "intro_hook": f"Stop and check how your body feels right now! We are counting down the six most shocking warning signs behind {clean_txt(tr['title'])}, starting at number six and building up to the number one silent mistake that catches ninety percent of people off guard.",
        "intro_query": "human body scan medical",
        "points": pts,
        "outro_headline": "JOIN MEDPULSE DAILY",
        "outro": "Thank you for watching MedPulse Daily! If this countdown helped you spot what your body is telling you, hit the like button, subscribe to our channel, and tell us in the comments if number one surprised you!",
        "seo_description": f"We count down the 6 most important warning signs and natural fixes for {clean_txt(tr['title'])} using simple real-life examples.",
        "seo_tags": ["health", "nutrition", "symptoms", "wellness", "medicalscience"]
    }

def dl_pexels(q, tag):
    out_p = f"temp/vid_{tag}.mp4"
    if os.path.exists(out_p) and os.path.getsize(out_p) > 60000:
        return out_p
    used = load_set(USED_VIDEOS_FILE)
    hdr = {"Authorization": PEXELS_KEY}
    for qr in [q, "medical health lifestyle", "healthy food nutrition", "human body science"]:
        if not PEXELS_KEY:
            break
        try:
            r = requests.get("https://api.pexels.com/videos/search", headers=hdr, params={"query": qr, "per_page": 15, "orientation": "landscape"}, timeout=12)
            if r.status_code != 200:
                continue
            for v in r.json().get("videos", []):
                vid = str(v.get("id"))
                if vid in used:
                    continue
                best_u = None
                for vf in v.get("video_files", []):
                    if vf.get("width", 0) >= 1280 and vf.get("height", 0) >= 720 and vf.get("width", 0) > vf.get("height", 0):
                        best_u = vf.get("link")
                        break
                if not best_u and v.get("video_files"):
                    best_u = v["video_files"][0].get("link")
                if best_u:
                    vr = requests.get(best_u, timeout=25)
                    if vr.status_code == 200 and len(vr.content) > 80000:
                        with open(out_p, "wb") as f:
                            f.write(vr.content)
                        save_item(USED_VIDEOS_FILE, vid)
                        return out_p
        except Exception:
            pass
    subprocess.run([FFMPEG_EXE, "-y", "-f", "lavfi", "-i", "color=c=0x101c2e:s=1280x720:d=8:r=24", "-c:v", "libx264", "-pix_fmt", "yuv420p", out_p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out_p

def prep_two(p1, p2, dur, out_p):
    half = max(2.2, (dur + 0.4) / 2.0)
    c1, c2 = out_p + "_1.mp4", out_p + "_2.mp4"
    vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1:1,fps={FPS}"
    for src, dst in [(p1, c1), (p2, c2)]:
        subprocess.run([FFMPEG_EXE, "-y", "-stream_loop", "-1", "-i", src, "-t", f"{half:.2f}", "-vf", vf, "-an", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", dst], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    lst = out_p + "_list.txt"
    with open(lst, "w", encoding="utf-8") as f:
        f.write(f"file '{os.path.abspath(c1)}'\nfile '{os.path.abspath(c2)}'\n")
    subprocess.run([FFMPEG_EXE, "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", out_p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out_p if (os.path.exists(out_p) and os.path.getsize(out_p) > 30000) else p1

async def _edge_save(txt, out_mp3, rate):
    await edge_tts.Communicate(clean_txt(txt), VOICE_NAME, rate=rate, pitch=VOICE_PITCH).save(out_mp3)

def gen_wav(txt, out_wav, rate=VOICE_RATE):
    tmp_mp3, raw_wav = out_wav + ".mp3", out_wav + "_raw.wav"
    for _ in range(3):
        try:
            asyncio.run(_edge_save(txt, tmp_mp3, rate))
            if os.path.exists(tmp_mp3) and os.path.getsize(tmp_mp3) > 1000:
                break
        except Exception:
            time.sleep(1)
    subprocess.run([FFMPEG_EXE, "-y", "-i", tmp_mp3, "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", raw_wav], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not os.path.exists(raw_wav):
        with wave.open(out_wav, "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(44100)
            wf.writeframes(b"\x00" * (44100 * 4 * 4))
        return 4.0
    with wave.open(raw_wav, "rb") as rf:
        sr, ch, sw, nf = rf.getframerate(), rf.getnchannels(), rf.getsampwidth(), rf.getnframes()
        pcm = rf.readframes(max(1, nf - int(sr * 0.06)))
    full_pcm = pcm + (b"\x00" * (int(sr * 0.30) * ch * sw))
    with wave.open(out_wav, "wb") as wf:
        wf.setnchannels(ch)
        wf.setsampwidth(sw)
        wf.setframerate(sr)
        wf.writeframes(full_pcm)
    return float(len(full_pcm) // (ch * sw)) / float(sr)

def make_chime_wav(out_wav, dur=2.8):
    sr = 44100
    buf = array.array("h")
    for i in range(int(sr * dur)):
        t = i / float(sr)
        v = 0.22 * math.exp(-t * 2.2) * min(1.0, t / 0.04) * (math.sin(2 * math.pi * 528.0 * t) + 0.5 * math.sin(2 * math.pi * 792.0 * t))
        s = int(max(-32767, min(32767, v * 32767)))
        buf.extend([s, s])
    with wave.open(out_wav, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(buf.tobytes())

def build_master_wav(wav_list, out_wav, bg_vol=0.032):
    chunks = []
    for wp in wav_list:
        if os.path.exists(wp):
            with wave.open(wp, "rb") as rf:
                chunks.append(rf.readframes(rf.getnframes()))
    voice_arr = np.frombuffer(b"".join(chunks), dtype=np.int16).astype(np.float32)
    n_pairs = len(voice_arr) // 2
    t = np.arange(n_pairs, dtype=np.float32) / 44100.0
    bg = bg_vol * 32767.0 * (0.5 * np.sin(2 * math.pi * 136.1 * t) + 0.3 * np.sin(2 * math.pi * 204.15 * t) + 0.2 * np.sin(2 * math.pi * 272.2 * t))
    bg_st = np.empty(n_pairs * 2, dtype=np.float32)
    bg_st[0::2] = bg
    bg_st[1::2] = bg
    mixed = np.clip(voice_arr + bg_st, -32767, 32767).astype(np.int16)
    with wave.open(out_wav, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        wf.writeframes(mixed.tobytes())

def export_final_mp4(clip_obj, wav_list, out_mp4):
    tmp_v, tmp_a = out_mp4 + "_silent.mp4", out_mp4 + "_master.wav"
    build_master_wav(wav_list, tmp_a)
    clip_obj.write_videofile(tmp_v, fps=FPS, codec="libx264", audio=False, preset="ultrafast", threads=4, logger=None)
    subprocess.run([FFMPEG_EXE, "-y", "-i", tmp_v, "-i", tmp_a, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", out_mp4], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def paste_logo(img, sz=64, cx=W - 90, top_y=12, f_sz=13):
    lp = LOGO_PATH if os.path.exists(LOGO_PATH) else "\u062a\u0646\u0632\u064a\u0644.jpeg"
    lx = cx - (sz // 2)
    if os.path.exists(lp):
        try:
            lg = Image.open(lp).convert("RGBA").resize((sz, sz), Image.LANCZOS)
            mask = Image.new("L", (sz, sz), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, sz, sz), fill=255)
            ring = Image.new("RGBA", (sz + 6, sz + 6), (0, 0, 0, 0))
            ImageDraw.Draw(ring).ellipse((0, 0, sz + 5, sz + 5), outline=(255, 205, 0, 245), width=3)
            img.paste(ring, (lx - 3, top_y - 3), ring)
            img.paste(lg, (lx, top_y), mask)
        except Exception:
            pass
    dr = ImageDraw.Draw(img)
    fn = get_font(f_sz, True)
    bb = dr.textbbox((0, 0), CHANNEL_NAME, font=fn)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    bx1, bx2 = cx - (tw // 2) - 9, cx + (tw // 2) + 9
    by1, by2 = top_y + sz + 5, top_y + sz + th + 15
    dr.rounded_rectangle([(bx1, by1), (bx2, by2)], radius=6, fill=(8, 16, 34, 240), outline=(255, 205, 0, 230), width=2)
    dr.text((cx - (tw // 2), by1 + 3), CHANNEL_NAME, font=fn, fill=(255, 215, 0, 255))

def make_frame_img(badge_txt, headline_txt, sub_chunk):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    f_b, f_h, f_s = get_font(19, True), get_font(20, True), get_font(25, True)
    b_str = clean_txt(badge_txt).upper()
    h_str = clean_txt(headline_txt).upper()[:42]
    bb_b = dr.textbbox((0, 0), b_str, font=f_b)
    bw = (bb_b[2] - bb_b[0]) + 28
    dr.rounded_rectangle([(24, 16), (24 + bw, 54)], radius=8, fill=(210, 28, 28, 240), outline=(255, 205, 0, 220), width=2)
    dr.text((38, 24), b_str, font=f_b, fill=(255, 255, 255, 255))
    if h_str:
        bb_h = dr.textbbox((0, 0), h_str, font=f_h)
        hw = min(W - bw - 230, (bb_h[2] - bb_h[0]) + 30)
        hx1 = 32 + bw
        dr.rounded_rectangle([(hx1, 16), (hx1 + hw, 54)], radius=8, fill=(8, 16, 34, 225), outline=(255, 205, 0, 190), width=2)
        dr.text((hx1 + 14, 24), h_str, font=f_h, fill=(255, 215, 0, 255))
    paste_logo(img, sz=64, cx=W - 90, top_y=12, f_sz=13)
    if sub_chunk:
        lines = wrap_lines(sub_chunk, f_s, W - 220, dr)[:2]
        bar_h = 44 if len(lines) == 1 else 78
        by1 = H - bar_h - 12
        by2 = H - 12
        dr.rounded_rectangle([(74, by1), (W - 74, by2)], radius=12, fill=(6, 12, 24, 195), outline=(255, 205, 0, 180), width=2)
        y = by1 + 9
        for ln in lines:
            bb = dr.textbbox((0, 0), ln, font=f_s)
            x = (W - (bb[2] - bb[0])) // 2
            dr.text((x + 2, y + 2), ln, font=f_s, fill=(0, 0, 0, 245))
            dr.text((x, y), ln, font=f_s, fill=(255, 255, 255, 255))
            y += 33
    return np.array(img)

def build_synced_scene(vc, badge_txt, headline_txt, spoken_txt, dur):
    chunks = split_timed_subs(spoken_txt, dur, max_words=13)
    ov_clips = []
    for sub_c, c_dur in chunks:
        arr = make_frame_img(badge_txt, headline_txt, sub_c)
        ov_clips.append(ImageClip(arr).set_duration(c_dur))
    ov_track = concatenate_videoclips(ov_clips, method="chain").set_duration(dur)
    return CompositeVideoClip([vc, ov_track])

def make_card(rank_num, p_title, dur=2.8):
    img = Image.new("RGBA", (W, H), (10, 18, 34, 255))
    dr = ImageDraw.Draw(img)
    dr.rectangle([(70, 60), (W - 70, H - 60)], outline=(255, 200, 0, 220), width=4)
    f1, f2 = get_font(34, True), get_font(50, True)
    tag = f"COUNTDOWN #{rank_num}" if rank_num > 1 else "NUMBER #1: THE BIGGEST SHOCK"
    b1 = dr.textbbox((0, 0), tag, font=f1)
    dr.rounded_rectangle([((W - (b1[2] - b1[0]) - 60) // 2, 195), ((W + (b1[2] - b1[0]) + 60) // 2, 255)], radius=12, fill=(210, 35, 35, 255))
    dr.text(((W - (b1[2] - b1[0])) // 2, 207), tag, font=f1, fill=(255, 255, 255, 255))
    y = 320
    for ln in wrap_lines(clean_txt(p_title).upper(), f2, W - 220, dr)[:2]:
        b2 = dr.textbbox((0, 0), ln, font=f2)
        dr.text(((W - (b2[2] - b2[0])) // 2, y), ln, font=f2, fill=(255, 215, 0, 255))
        y += 66
    paste_logo(img, sz=76, cx=W - 155, top_y=76, f_sz=14)
    return ImageClip(np.array(img)).set_duration(dur)

def calc_excitement(rec):
    txt = rec["text"].lower()
    val = int(rec.get("ai_thrill", 85)) * 2
    for hw in ["shocking", "warning", "danger", "silent", "mistake", "secret", "hidden", "never", "stop", "instantly", "emergency", "alarm", "damage", "toxic", "clogged", "dashboard", "check-engine", "overnight", "sudden", "urgent", "trap"]:
        if hw in txt:
            val += 15
    if rec.get("rank") in (1, 2):
        val += 22
    if rec.get("para_idx") in (1, 3):
        val += 25
    if 6.5 <= rec.get("dur", 10.0) <= 15.0:
        val += 18
    return val

def save_short_ov_png(badge_txt, headline_txt, sub_chunk, out_png):
    img = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    f_b, f_h, f_s = get_font(27, True), get_font(28, True), get_font(38, True)
    b_str = clean_txt(badge_txt).upper()[:24]
    h_str = clean_txt(headline_txt).upper()[:30]
    bb_b = dr.textbbox((0, 0), b_str, font=f_b)
    bw = (bb_b[2] - bb_b[0]) + 36
    dr.rounded_rectangle([(34, 42), (34 + bw, 96)], radius=12, fill=(215, 28, 28, 245), outline=(255, 205, 0, 230), width=2)
    dr.text((52, 54), b_str, font=f_b, fill=(255, 255, 255, 255))
    if h_str:
        bb_h = dr.textbbox((0, 0), h_str, font=f_h)
        hw = min(SW - 270, (bb_h[2] - bb_h[0]) + 36)
        dr.rounded_rectangle([(34, 104), (34 + hw, 158)], radius=12, fill=(8, 16, 34, 230), outline=(255, 205, 0, 210), width=2)
        dr.text((52, 116), h_str, font=f_h, fill=(255, 215, 0, 255))
    paste_logo(img, sz=90, cx=SW - 112, top_y=30, f_sz=17)
    if sub_chunk:
        lines = wrap_lines(sub_chunk, f_s, SW - 120, dr)[:2]
        bar_h = 84 if len(lines) == 1 else 142
        by1 = SH - bar_h - 140
        by2 = SH - 140
        dr.rounded_rectangle([(42, by1), (SW - 42, by2)], radius=18, fill=(6, 12, 24, 205), outline=(255, 205, 0, 210), width=3)
        y = by1 + 16
        for ln in lines:
            bb = dr.textbbox((0, 0), ln, font=f_s)
            x = (SW - (bb[2] - bb[0])) // 2
            dr.text((x + 3, y + 3), ln, font=f_s, fill=(0, 0, 0, 255))
            dr.text((x, y), ln, font=f_s, fill=(255, 230, 0, 255))
            y += 54
    img.save(out_png)

def render_short_synced_item(it, item_idx):
    chunks = split_timed_subs(it["text"], it["dur"], max_words=9)
    sub_mp4s = []
    cur_t = 0.0
    vf = f"[0:v]scale=-2:{SH}:flags=lanczos,crop={SW}:{SH}:(iw-{SW})/2:0,setsar=1:1,fps={FPS}[bg];[bg][1:v]overlay=0:0,setsar=1:1,setdar=9/16[v]"
    for c_i, (sub_c, c_dur) in enumerate(chunks):
        ov_p = f"temp/sh_ov_{item_idx}_{c_i}.png"
        part_p = f"temp/sh_sub_{item_idx}_{c_i}.mp4"
        save_short_ov_png(it["badge"], it["headline"], sub_c, ov_p)
        subprocess.run([FFMPEG_EXE, "-y", "-stream_loop", "-1", "-ss", f"{cur_t:.3f}", "-i", it["vpath"], "-loop", "1", "-i", ov_p, "-t", f"{c_dur:.3f}", "-filter_complex", vf, "-map", "[v]", "-an", "-aspect", "9:16", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", part_p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(part_p) and os.path.getsize(part_p) > 8000:
            sub_mp4s.append(os.path.abspath(part_p))
        cur_t += c_dur
    return sub_mp4s

def build_short_from_long(hook_rec, body_records):
    ranked = sorted(body_records, key=calc_excitement, reverse=True)
    chosen, used_rnks = [], set()
    cur_sec = hook_rec["dur"]
    for r in ranked:
        if r["rank"] in used_rnks and len(chosen) < 3:
            continue
        if cur_sec + r["dur"] <= 51.0 or len(chosen) < 2:
            chosen.append(r)
            used_rnks.add(r["rank"])
            cur_sec += r["dur"]
        if len(chosen) >= 4 or cur_sec >= 46.0:
            break
    chosen.sort(key=lambda x: calc_excitement(x))
    cta_wav = "temp/sh_cta.wav"
    cta_txt = "Want to see the number one shocking sign and all natural fixes? Watch the full countdown on MedPulse Daily right now and subscribe!"
    cta_dur = gen_wav(cta_txt, cta_wav, rate="+2%")
    seq = [hook_rec]
    for c in chosen:
        seq.append({"badge": f"COUNTDOWN #{c['rank']}", "headline": c["headline"], "text": c["text"], "vpath": c["vpath"], "apath": c["apath"], "dur": c["dur"]})
    seq.append({"badge": "FULL COUNTDOWN", "headline": "WATCH #1 ON MEDPULSE DAILY", "text": cta_txt, "vpath": hook_rec["vpath"], "apath": cta_wav, "dur": cta_dur})
    v_parts, w_parts = [], []
    for i, it in enumerate(seq):
        subs = render_short_synced_item(it, i)
        if subs:
            v_parts.extend(subs)
            w_parts.append(it["apath"])
    lst_p, silent_sh, master_w = "temp/sh_concat.txt", "temp/sh_silent.mp4", "temp/sh_master.wav"
    with open(lst_p, "w", encoding="utf-8") as f:
        for vp in v_parts:
            f.write(f"file '{vp}'\n")
    build_master_wav(w_parts, master_w, bg_vol=0.035)
    subprocess.run([FFMPEG_EXE, "-y", "-f", "concat", "-safe", "0", "-i", lst_p, "-c", "copy", silent_sh], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run([FFMPEG_EXE, "-y", "-i", silent_sh, "-i", master_w, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-aspect", "9:16", "-shortest", "output/short_video.mp4"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def write_details(tr, sc):
    src_lines = []
    for idx, s in enumerate(tr.get("sources", []), 1):
        src_lines.append(f"{idx}. {clean_txt(s.get('source', 'Medical Source'))} - {clean_txt(s.get('title', ''))}")
        src_lines.append(f"   Link: {s.get('url', '')}")
    tags = [clean_txt(t).replace(" ", "") for t in sc.get("seo_tags", ["health", "wellness", "nutrition"]) if clean_txt(t)]
    hash_str = " ".join(["\x23" + t for t in tags[:12]])
    v_title = clean_txt(sc.get("video_title", tr["title"]))
    s_title = clean_txt(sc.get("short_title", v_title))
    thumb_hook = clean_txt(sc.get("thumbnail_hook", "#1 BODY WARNING")).upper()
    body = "\n".join([
        "==========================================",
        "1. LONG VIDEO TITLE (COPY & PASTE):",
        "==========================================",
        v_title, "",
        "==========================================",
        "2. SHORT VIDEO TITLE (COPY & PASTE):",
        "==========================================",
        s_title + " \x23Shorts \x23Health \x23Wellness", "",
        "==========================================",
        "3. YOUTUBE DESCRIPTION (WITH TODAY'S SOURCES):",
        "==========================================",
        "Welcome to MedPulse Daily! " + clean_txt(sc.get("seo_description", "")), "",
        "SCIENTIFIC & MEDICAL SOURCES FOR THIS VIDEO:",
        "\n".join(src_lines), "",
        "MEDICAL DISCLAIMER:",
        "This video is for educational purposes only and is not a substitute for professional medical advice.", "",
        hash_str, "",
        "==========================================",
        "4. YOUTUBE TAGS (COMMA SEPARATED):",
        "==========================================",
        ", ".join(tags[:20]), "",
        "==========================================",
        "5. THUMBNAIL IMAGE PROMPT (LANDSCAPE 16:9):",
        "==========================================",
        f"Ultra-detailed cinematic 3D medical illustration representing {v_title}, glowing anatomical highlight, deep dark navy and golden accents, dramatic studio lighting, high contrast, 8k resolution, bold text overlay '{thumb_hook}', no people names, aspect ratio 16:9."
    ])
    with open("output/youtube_details.txt", "w", encoding="utf-8") as f:
        f.write(body)

def main():
    tr = fetch_live_trend()
    sc = generate_script(tr)
    clips, wavs, body_records = [], [], []
    cur_t, idx = 0.0, 0

    aw = f"temp/a_{idx}.wav"
    i_txt = sc.get("intro_hook", tr["title"])
    i_head = sc.get("intro_headline", "BREAKING HEALTH COUNTDOWN")
    dur = gen_wav(i_txt, aw)
    v1 = dl_pexels(sc.get("intro_query", "medical health"), f"{idx}_a")
    v2 = dl_pexels("human body anatomy", f"{idx}_b")
    vp = prep_two(v1, v2, dur, f"temp/prep_{idx}.mp4")
    clips.append(build_synced_scene(VideoFileClip(vp).subclip(0, dur), "LIVE ALERT", i_head, i_txt, dur))
    wavs.append(aw)
    hook_rec = {"badge": "URGENT ALERT", "headline": i_head, "text": i_txt, "vpath": vp, "apath": aw, "dur": dur}
    cur_t += dur
    idx += 1

    chime_p = "temp/chime.wav"
    make_chime_wav(chime_p, 2.8)

    default_Ranks = [6, 5, 4, 3, 2, 1]
    for pt_i, pt in enumerate(sc.get("points", [])[:6]):
        rnk = pt.get("rank", default_Ranks[pt_i])
        ptitle = pt.get("point_title", f"Critical Body Signal #{rnk}")
        clips.append(make_card(rnk, ptitle, 2.8))
        wavs.append(chime_p)
        cur_t += 2.8
        for p_i, para in enumerate(pt.get("paragraphs", [])[:4], 1):
            aw = f"temp/a_{idx}.wav"
            p_txt = para.get("text", "")
            p_head = para.get("headline", ptitle)
            dur = gen_wav(p_txt, aw)
            v1 = dl_pexels(para.get("q1", "medical health"), f"{idx}_a")
            v2 = dl_pexels(para.get("q2", "healthy nutrition"), f"{idx}_b")
            vp = prep_two(v1, v2, dur, f"temp/prep_{idx}.mp4")
            clips.append(build_synced_scene(VideoFileClip(vp).subclip(0, dur), f"COUNTDOWN #{rnk}", p_head, p_txt, dur))
            wavs.append(aw)
            body_records.append({"idx": idx, "rank": rnk, "para_idx": p_i, "headline": p_head, "text": p_txt, "vpath": vp, "apath": aw, "dur": dur, "ai_thrill": para.get("thrill_score", 88)})
            cur_t += dur
            idx += 1

    bonus_list = [
        ("NUTRIENT ABSORPTION SECRET", "Here is a critical bonus tip to multiply your results. When you pair healthy fats like extra-virgin olive oil or avocado with colorful vegetables, your digestive tract absorbs fat-soluble vitamins up to four times faster than eating plain salads alone.", "olive oil salad", "fresh avocado vegetables"),
        ("DEEP CELLULAR NIGHT REPAIR", "Another powerful habit happens during the last two hours before sleep. Swapping bright phone screens and late-night snacks for warm chamomile tea or magnesium-rich almonds lowers stress hormones and activates deep overnight cellular repair.", "chamomile tea cup", "almonds nuts healthy"),
        ("ELECTROLYTE HYDRATION FORMULA", "Think of cellular hydration like oil inside a car engine. Drinking plain water without trace minerals can leave your cells thirsty, whereas adding fresh lemon juice and a tiny pinch of sea salt helps water energize your organs all morning.", "lemon water glass", "pouring clean water")
    ]
    b_i = 0
    while cur_t < MIN_LONG_SEC:
        b_head, b_txt, q1, q2 = bonus_list[b_i % len(bonus_list)]
        aw = f"temp/a_{idx}.wav"
        dur = gen_wav(b_txt, aw)
        v1 = dl_pexels(q1, f"{idx}_a")
        v2 = dl_pexels(q2, f"{idx}_b")
        vp = prep_two(v1, v2, dur, f"temp/prep_{idx}.mp4")
        clips.append(build_synced_scene(VideoFileClip(vp).subclip(0, dur), "BONUS INSIGHT", b_head, b_txt, dur))
        wavs.append(aw)
        cur_t += dur
        idx += 1
        b_i += 1

    aw = f"temp/a_{idx}.wav"
    o_txt = sc.get("outro", "Thank you for watching MedPulse Daily! Please like, subscribe, and comment below!")
    o_head = sc.get("outro_headline", "SUBSCRIBE TO MEDPULSE DAILY")
    dur = gen_wav(o_txt, aw)
    v1 = dl_pexels("happy healthy lifestyle", f"{idx}_a")
    v2 = dl_pexels("fresh fruits vegetables", f"{idx}_b")
    vp = prep_two(v1, v2, dur, f"temp/prep_{idx}.mp4")
    clips.append(build_synced_scene(VideoFileClip(vp).subclip(0, dur), "MEDPULSE DAILY", o_head, o_txt, dur))
    wavs.append(aw)

    fin = concatenate_videoclips(clips, method="compose")
    export_final_mp4(fin, wavs, "output/final_video.mp4")
    fin.close()

    build_short_from_long(hook_rec, body_records)
    write_details(tr, sc)

if __name__ == "__main__":
    main()
