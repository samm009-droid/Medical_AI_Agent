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
VOICE_NAME = "en-US-ChristopherNeural"
VOICE_RATE = "-4%"
VOICE_PITCH = "-2Hz"
MIN_LONG_SEC = 560.0
LOGO_CANDIDATES = ["logo.jpeg", "logo.jpg", "logo.png", "\u062a\u0646\u0632\u064a\u0644.jpeg"]
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

def get_logo_path():
    for p in LOGO_CANDIDATES:
        if os.path.exists(p):
            return p
    return LOGO_CANDIDATES[0]

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
        "You are an elite medical educator and viral documentary scriptwriter for MedPulse Daily.",
        "Today's Live Trending Health Topic: " + tr["title"],
        "Context: " + tr["summary"],
        "STRICT RULES:",
        "1. NEVER mention any doctor's name or person's name anywhere.",
        "2. NEVER include website links or URLs in spoken text or subtitles.",
        "3. Use SIMPLE everyday English with vivid real-life analogies (car dashboard warning light, clogged kitchen filter, dish soap dissolving grease, rusted lock and key) and clear daily food/symptom examples.",
        "4. Write 6 sequential points with 4 paragraphs per point (24 body paragraphs total, 52-65 words each).",
        "5. Score each paragraph with thrill_score from 1 to 100 based on how shocking, suspenseful, and curiosity-inducing it is so our automated editor can extract the most thrilling clips for a viral Short.",
        "Return ONLY valid JSON with this exact structure:",
        "{",
        '  "video_title": "Viral title (no person names)",',
        '  "short_title": "Viral Short title under 65 chars",',
        '  "thumbnail_hook": "3 TO 4 UPPERCASE WORDS",',
        '  "intro_hook": "55-word shocking opening warning hook with a real-life symptom example",',
        '  "intro_sub": "12-word gripping subtitle for intro",',
        '  "intro_query": "human body medical scan",',
        '  "points": [',
        "    {",
        '      "point_number": 1,',
        '      "point_title": "Short 4-word title",',
        '      "paragraphs": [',
        '        {"text": "55-word shocking hidden symptom reveal...", "sub": "12-word subtitle", "q1": "tired person headache", "q2": "human cells microscope", "thrill_score": 98},',
        '        {"text": "55-word simple everyday analogy...", "sub": "12-word subtitle", "q1": "blood flow arteries", "q2": "heart beating medical", "thrill_score": 75},',
        '        {"text": "55-word shocking daily mistake people make...", "sub": "12-word subtitle", "q1": "sugar soda drink", "q2": "liver digestion medical", "thrill_score": 95},',
        '        {"text": "55-word practical food fix...", "sub": "12-word subtitle", "q1": "fresh green vegetables", "q2": "lemon water glass", "thrill_score": 82}',
        "      ]",
        "    }",
        "  ],",
        '  "outro": "45-word warm conclusion asking viewers to like, subscribe to MedPulse Daily, and share their experience in the comments.",',
        '  "outro_sub": "Like, subscribe to MedPulse Daily, and comment below!",',
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
    for i in range(1, 7):
        pts.append({
            "point_number": i,
            "point_title": f"Hidden Body Signal {i}",
            "paragraphs": [
                {"text": f"Here is shocking warning sign number {i} linked to {tr['title']}. Just like a red check-engine light flashing on your car dashboard, your cells send out urgent distress signals through sudden afternoon exhaustion, brain fog, or muscle tightness long before standard tests spot the danger.", "sub": f"Warning sign {i} flashes like a car dashboard alert.", "q1": "tired person rubbing eyes", "q2": "medical nerve signal", "thrill_score": 97},
                {"text": "Inside your bloodstream, microscopic cellular pumps work nonstop to balance fluids and minerals. Think of this system like a kitchen water filter: when excess sugar and stress hormones accumulate, the filter clogs up and energy delivery drops.", "sub": "Cellular pumps clog up like an overworked water filter.", "q1": "blood cells flowing", "q2": "science laboratory", "thrill_score": 74},
                {"text": "The biggest hidden mistake millions make every morning is consuming refined sugar or dehydrating drinks on an empty stomach. That single habit acts like pouring sticky syrup onto delicate clockwork gears, forcing your liver and pancreas into emergency overdrive.", "sub": "Morning sugar habits overload your organs like sticky syrup.", "q1": "pouring sugary soda", "q2": "doctor checking patient", "thrill_score": 94},
                {"text": "You can start reversing this internal stress tonight with a simple kitchen swap. Add mineral-rich leafy greens, pumpkin seeds, avocado, and clean water with a pinch of sea salt to your meal so your cells recharge naturally.", "sub": "Mineral-rich whole foods recharge cellular energy naturally.", "q1": "fresh spinach avocado", "q2": "happy healthy person", "thrill_score": 80}
            ]
        })
    return {
        "video_title": clean_txt(tr["title"]) + " - 6 Early Warning Signs & Natural Fixes",
        "short_title": "Never Ignore These Shocking Body Warning Signs!",
        "thumbnail_hook": "SILENT BODY ALARM",
        "intro_hook": f"Stop and check how your body feels right now! Could your everyday fatigue, sudden cravings, or restless sleep actually be a silent alarm? Today on MedPulse Daily we uncover the science behind {clean_txt(tr['title'])} with simple examples.",
        "intro_sub": "Your daily fatigue or cravings could be a silent body alarm!",
        "intro_query": "human body scan medical",
        "points": pts,
        "outro": "Thank you for watching MedPulse Daily! If these simple examples helped you understand your body better, please hit the like button, subscribe to our channel, and tell us in the comments which warning sign surprised you most!",
        "outro_sub": "Hit like, subscribe to MedPulse Daily, and comment below!",
        "seo_description": f"Discover the science and everyday examples behind {clean_txt(tr['title'])}. Learn the 6 warning signs and natural food habits to protect your health.",
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

def paste_logo(img, sz=68, cx=W - 92, top_y=14, f_sz=13):
    lp = get_logo_path()
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
    pad_x, pad_y = 10, 4
    bx1 = cx - (tw // 2) - pad_x
    bx2 = cx + (tw // 2) + pad_x
    by1 = top_y + sz + 5
    by2 = by1 + th + (pad_y * 2) + 2
    dr.rounded_rectangle([(bx1, by1), (bx2, by2)], radius=6, fill=(8, 16, 34, 240), outline=(255, 205, 0, 230), width=2)
    dr.text((cx - (tw // 2), by1 + pad_y - 1), CHANNEL_NAME, font=fn, fill=(255, 215, 0, 255))

def make_overlay(p_num, p_title, sub_txt, dur):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    dr.rectangle([(0, H - 175), (W, H)], fill=(8, 14, 26, 205))
    dr.rectangle([(0, H - 175), (W, H - 171)], fill=(220, 38, 38, 255))
    badge = f"POINT {p_num}" if p_num else "DAILY HEALTH TREND"
    f_b, f_t, f_s = get_font(20, True), get_font(22, True), get_font(27, True)
    dr.rounded_rectangle([(36, 24), (245, 64)], radius=8, fill=(200, 30, 30, 235))
    dr.text((50, 32), badge, font=f_b, fill=(255, 255, 255, 255))
    if p_title:
        dr.rounded_rectangle([(255, 24), (790, 64)], radius=8, fill=(15, 23, 42, 210))
        dr.text((270, 31), clean_txt(p_title).upper()[:38], font=f_t, fill=(255, 215, 0, 255))
    paste_logo(img, sz=66, cx=W - 92, top_y=12, f_sz=13)
    y = H - 150
    for ln in wrap_lines(sub_txt, f_s, W - 110, dr)[:3]:
        bb = dr.textbbox((0, 0), ln, font=f_s)
        x = (W - (bb[2] - bb[0])) // 2
        dr.text((x + 2, y + 2), ln, font=f_s, fill=(0, 0, 0, 240))
        dr.text((x, y), ln, font=f_s, fill=(255, 255, 255, 255))
        y += 40
    return ImageClip(np.array(img)).set_duration(dur)

def make_card(p_num, p_title, dur=2.8):
    img = Image.new("RGBA", (W, H), (10, 18, 34, 255))
    dr = ImageDraw.Draw(img)
    dr.rectangle([(70, 60), (W - 70, H - 60)], outline=(255, 200, 0, 220), width=4)
    f1, f2 = get_font(34, True), get_font(52, True)
    tag = f"POINT {p_num} OF 6"
    b1 = dr.textbbox((0, 0), tag, font=f1)
    dr.rounded_rectangle([((W - (b1[2] - b1[0]) - 60) // 2, 195), ((W + (b1[2] - b1[0]) + 60) // 2, 255)], radius=12, fill=(210, 35, 35, 255))
    dr.text(((W - (b1[2] - b1[0])) // 2, 207), tag, font=f1, fill=(255, 255, 255, 255))
    y = 320
    for ln in wrap_lines(clean_txt(p_title).upper(), f2, W - 220, dr)[:2]:
        b2 = dr.textbbox((0, 0), ln, font=f2)
        dr.text(((W - (b2[2] - b2[0])) // 2, y), ln, font=f2, fill=(255, 215, 0, 255))
        y += 68
    paste_logo(img, sz=76, cx=W - 155, top_y=76, f_sz=14)
    return ImageClip(np.array(img)).set_duration(dur)

def calc_excitement(rec):
    txt = rec["text"].lower()
    val = int(rec.get("ai_thrill", 80)) * 2
    hot_words = [
        "shocking", "warning", "danger", "silent", "mistake", "secret", "hidden",
        "never", "stop", "instantly", "emergency", "alarm", "damage", "toxic",
        "clogged", "dashboard", "check-engine", "overnight", "sudden", "urgent", "trap"
    ]
    for hw in hot_words:
        if hw in txt:
            val += 15
    if rec.get("para_idx") in (1, 3):
        val += 25
    if 6.5 <= rec.get("dur", 10.0) <= 15.0:
        val += 18
    return val

def save_short_ov_png(badge_txt, sub_txt, out_png):
    img = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    dr.rectangle([(0, 0), (SW, 220)], fill=(6, 12, 24, 180))
    dr.rectangle([(0, SH - 560), (SW, SH)], fill=(6, 12, 24, 220))
    dr.rectangle([(0, SH - 560), (SW, SH - 554)], fill=(255, 205, 0, 255))
    f_b, f_s = get_font(30, True), get_font(44, True)
    dr.rounded_rectangle([(42, 58), (690, 128)], radius=14, fill=(215, 30, 30, 245))
    dr.text((66, 75), clean_txt(badge_txt).upper()[:28], font=f_b, fill=(255, 255, 255, 255))
    paste_logo(img, sz=94, cx=SW - 115, top_y=24, f_sz=18)
    y = SH - 500
    for ln in wrap_lines(sub_txt, f_s, SW - 110, dr)[:4]:
        bb = dr.textbbox((0, 0), ln, font=f_s)
        x = (SW - (bb[2] - bb[0])) // 2
        dr.text((x + 3, y + 3), ln, font=f_s, fill=(0, 0, 0, 255))
        dr.text((x, y), ln, font=f_s, fill=(255, 230, 0, 255))
        y += 62
    img.save(out_png)

def build_short_from_long(hook_rec, body_records):
    ranked = sorted(body_records, key=calc_excitement, reverse=True)
    chosen, used_pts = [], set()
    cur_sec = hook_rec["dur"]
    for r in ranked:
        if r["point_num"] in used_pts and len(chosen) < 3:
            continue
        if cur_sec + r["dur"] <= 51.0 or len(chosen) < 2:
            chosen.append(r)
            used_pts.add(r["point_num"])
            cur_sec += r["dur"]
        if len(chosen) >= 4 or cur_sec >= 46.0:
            break
    chosen.sort(key=lambda x: calc_excitement(x))
    cta_wav = "temp/sh_cta.wav"
    cta_dur = gen_wav("Don't miss the other warning signs and natural fixes! Watch the full video on MedPulse Daily right now and subscribe!", cta_wav, rate="+2%")
    seq = [hook_rec]
    for c in chosen:
        seq.append({"badge": "SHOCKING REVEAL " + str(c["point_num"]), "sub": c["sub"], "vpath": c["vpath"], "apath": c["apath"], "dur": c["dur"]})
    seq.append({"badge": "WATCH FULL VIDEO", "sub": "Watch the full video on MedPulse Daily for all 6 steps!", "vpath": hook_rec["vpath"], "apath": cta_wav, "dur": cta_dur})
    v_parts, w_parts = [], []
    vf = f"[0:v]scale=-2:{SH}:flags=lanczos,crop={SW}:{SH}:(iw-{SW})/2:0,setsar=1:1,fps={FPS}[bg];[bg][1:v]overlay=0:0,setsar=1:1,setdar=9/16[v]"
    for i, it in enumerate(seq):
        ov_p, sc_mp4 = f"temp/sh_ov_{i}.png", f"temp/sh_part_{i}.mp4"
        save_short_ov_png(it["badge"], it["sub"], ov_p)
        subprocess.run([FFMPEG_EXE, "-y", "-stream_loop", "-1", "-i", it["vpath"], "-loop", "1", "-i", ov_p, "-t", f"{it['dur']:.3f}", "-filter_complex", vf, "-map", "[v]", "-an", "-aspect", "9:16", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", sc_mp4], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(sc_mp4) and os.path.getsize(sc_mp4) > 15000:
            v_parts.append(os.path.abspath(sc_mp4))
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
    thumb_hook = clean_txt(sc.get("thumbnail_hook", "BODY WARNING SIGNS")).upper()
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
    dur = gen_wav(sc.get("intro_hook", tr["title"]), aw)
    v1 = dl_pexels(sc.get("intro_query", "medical health"), f"{idx}_a")
    v2 = dl_pexels("human body anatomy", f"{idx}_b")
    vp = prep_two(v1, v2, dur, f"temp/prep_{idx}.mp4")
    clips.append(CompositeVideoClip([VideoFileClip(vp).subclip(0, dur), make_overlay(0, "TODAY'S TOP HEALTH TREND", sc.get("intro_sub", tr["title"]), dur)]))
    wavs.append(aw)
    hook_rec = {"badge": "URGENT HEALTH ALERT", "sub": sc.get("intro_sub", tr["title"]), "vpath": vp, "apath": aw, "dur": dur}
    cur_t += dur
    idx += 1

    chime_p = "temp/chime.wav"
    make_chime_wav(chime_p, 2.8)

    for pt in sc.get("points", [])[:6]:
        pnum = pt.get("point_number", 1)
        ptitle = pt.get("point_title", f"Key Signal {pnum}")
        clips.append(make_card(pnum, ptitle, 2.8))
        wavs.append(chime_p)
        cur_t += 2.8
        for p_i, para in enumerate(pt.get("paragraphs", [])[:4], 1):
            aw = f"temp/a_{idx}.wav"
            p_txt = para.get("text", "")
            p_sub = para.get("sub", p_txt[:85])
            dur = gen_wav(p_txt, aw)
            v1 = dl_pexels(para.get("q1", "medical health"), f"{idx}_a")
            v2 = dl_pexels(para.get("q2", "healthy nutrition"), f"{idx}_b")
            vp = prep_two(v1, v2, dur, f"temp/prep_{idx}.mp4")
            clips.append(CompositeVideoClip([VideoFileClip(vp).subclip(0, dur), make_overlay(pnum, ptitle, p_sub, dur)]))
            wavs.append(aw)
            body_records.append({"idx": idx, "point_num": pnum, "para_idx": p_i, "text": p_txt, "sub": p_sub, "vpath": vp, "apath": aw, "dur": dur, "ai_thrill": para.get("thrill_score", 85)})
            cur_t += dur
            idx += 1

    bonus_list = [
        ("Let us look at a practical kitchen example you can apply today. When you pair healthy fats like extra-virgin olive oil or avocado with colorful vegetables, your digestive tract absorbs fat-soluble vitamins up to four times more effectively than eating plain salads alone.", "Healthy fats boost vitamin absorption up to four times.", "olive oil salad", "fresh avocado vegetables"),
        ("Another everyday example happens during the last two hours before bedtime. Replacing bright phone screens and late-night snacks with a warm cup of chamomile tea or magnesium-rich almonds signals your nervous system to lower stress hormones and begin deep cellular repair.", "Evening habits lower stress hormones and trigger cellular repair.", "chamomile tea cup", "almonds nuts healthy"),
        ("Think of hydration like oil inside a car engine. Drinking plain water without trace electrolytes can leave your cells thirsty, whereas adding a squeeze of fresh lemon and a tiny pinch of mineral salt helps water enter your cells smoothly all morning.", "Electrolytes help water hydrate your cells like engine oil.", "lemon water glass", "pouring clean water")
    ]
    b_i = 0
    while cur_t < MIN_LONG_SEC:
        b_txt, b_sub, q1, q2 = bonus_list[b_i % len(bonus_list)]
        aw = f"temp/a_{idx}.wav"
        dur = gen_wav(b_txt, aw)
        v1 = dl_pexels(q1, f"{idx}_a")
        v2 = dl_pexels(q2, f"{idx}_b")
        vp = prep_two(v1, v2, dur, f"temp/prep_{idx}.mp4")
        clips.append(CompositeVideoClip([VideoFileClip(vp).subclip(0, dur), make_overlay(6, "PRACTICAL DAILY EXAMPLE", b_sub, dur)]))
        wavs.append(aw)
        cur_t += dur
        idx += 1
        b_i += 1

    aw = f"temp/a_{idx}.wav"
    dur = gen_wav(sc.get("outro", "Thank you for watching MedPulse Daily! Please like, subscribe, and comment below!"), aw)
    v1 = dl_pexels("happy healthy lifestyle", f"{idx}_a")
    v2 = dl_pexels("fresh fruits vegetables", f"{idx}_b")
    vp = prep_two(v1, v2, dur, f"temp/prep_{idx}.mp4")
    clips.append(CompositeVideoClip([VideoFileClip(vp).subclip(0, dur), make_overlay(0, "SUBSCRIBE & SHARE YOUR THOUGHTS", sc.get("outro_sub", "Like, subscribe, and comment below!"), dur)]))
    wavs.append(aw)

    fin = concatenate_videoclips(clips, method="compose")
    export_final_mp4(fin, wavs, "output/final_video.mp4")
    fin.close()

    build_short_from_long(hook_rec, body_records)
    write_details(tr, sc)

if __name__ == "__main__":
    main()
