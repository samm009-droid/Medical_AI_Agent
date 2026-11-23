import os, re, json, time, random, asyncio, subprocess, urllib.parse
import requests, feedparser, edge_tts
import numpy as np
import PIL.Image, PIL.ImageDraw, PIL.ImageFont
import google.generativeai as genai

setattr(PIL.Image, "ANTIALIAS", getattr(PIL.Image, "LANCZOS", PIL.Image.BICUBIC))
from moviepy.editor import (
    VideoFileClip, AudioFileClip, ImageClip,
    CompositeVideoClip, CompositeAudioClip, concatenate_videoclips
)
from moviepy.audio.AudioClip import AudioArrayClip

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "").strip()
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

W, H = 1280, 720
SW, SH = 1080, 1920
FPS = 24
MIN_LONG_SEC = 560.0
VOICE_NAME = "en-US-ChristopherNeural"
VOICE_RATE = "-4%"
VOICE_PITCH = "-2Hz"
SHORT_RATE = "+4%"
USED_NEWS_FILE = "used_news.txt"
USED_VIDEOS_FILE = "used_videos.txt"
LOGO_PATH = "\u062a\u0646\u0632\u064a\u0644.jpeg"

os.makedirs("output", exist_ok=True)
os.makedirs("temp", exist_ok=True)

GN = "https://news.google.com/rss/search?q="
GT = "+when:1d&hl=en-US&gl=US&ceid=US:en"

FEEDS = [
    ("Google Trends US", "https://trends.google.com/trending/rss?geo=US"),
    ("Google Trends UK", "https://trends.google.com/trending/rss?geo=GB"),
    ("Google Trends CA", "https://trends.google.com/trending/rss?geo=CA"),
    ("Google News Symptoms", GN + "health+symptom+OR+deficiency+OR+remedy" + GT),
    ("Google News Vitamins", GN + "vitamin+OR+magnesium+OR+potassium+OR+zinc" + GT),
    ("Google News Organs", GN + "fatty+liver+OR+gut+health+OR+kidneys+OR+nerves" + GT),
    ("Google News Metabolism", GN + "insulin+OR+cortisol+OR+blood+sugar" + GT),
    ("Google News Heart", GN + "blood+pressure+OR+cholesterol+OR+insomnia" + GT),
    ("Harvard Health", "https://www.health.harvard.edu/blog/feed"),
    ("Cleveland Clinic", "https://health.clevelandclinic.org/feed/"),
    ("Mayo Clinic", "https://newsnetwork.mayoclinic.org/feed/"),
    ("NIH MedlinePlus", "https://medlineplus.gov/feeds/news_en.xml"),
    ("Medical News Today", "https://rss.medicalnewstoday.com/featurednews.xml"),
    ("Healthline Wellness", "https://www.healthline.com/rss/health-news"),
    ("ScienceDaily Health", "https://www.sciencedaily.com/rss/health_medicine.xml"),
    ("Drugs.com Clinical", "https://www.drugs.com/feeds/medical_news.xml"),
    ("BBC Health", "http://feeds.bbci.co.uk/news/health/rss.xml"),
    ("NYT Health", "https://rss.nytimes.com/services/xml/rss/nyt/Health.xml"),
]

SEEDS = [
    "why do i wake up with ", "early warning signs of deficiency in ",
    "what happens when you stop eating ", "best natural remedy for high ",
    "hidden signs of fatty ", "how to lower cortisol and "
]

TERMS = [
    "vitamin", "magnesium", "potassium", "zinc", "iron", "b12", "insulin",
    "cortisol", "liver", "kidney", "thyroid", "gut", "bloating", "nerve",
    "sleep", "fatigue", "inflammation", "blood sugar", "diabetes", "cholesterol",
    "arteries", "blood pressure", "heart", "brain", "joint", "uric acid",
    "cramp", "electrolyte", "fasting", "omega", "bile", "stomach acid"
]

BANNED = ["in conclusion", "to summarize", "delve into", "berg", "dr. berg", "eric berg"]

def load_set(fp):
    if not os.path.exists(fp):
        return set()
    with open(fp, "r", encoding="utf-8") as f:
        return set(x.strip() for x in f if x.strip())

def save_set(fp, item):
    with open(fp, "a", encoding="utf-8") as f:
        f.write(f"{item.strip()}\n")

def clean_txt(t):
    t = re.sub(r"<[^>]+>", " ", str(t or ""))
    t = re.sub(r"\b(dr\.?\s*eric\s*berg|dr\.?\s*berg|eric\s*berg)\b", "", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip()

def sanitize(t):
    t = clean_txt(t)
    for b in BANNED:
        t = re.sub(rf"\b{re.escape(b)}\b", "", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip()
    return (t + ".") if (t and t[-1] not in ".!?") else t

def load_logo(sz=66):
    if not os.path.exists(LOGO_PATH):
        return None
    try:
        im = PIL.Image.open(LOGO_PATH).convert("RGBA").resize((sz, sz), PIL.Image.LANCZOS)
        msk = PIL.Image.new("L", (sz, sz), 0)
        PIL.ImageDraw.Draw(msk).ellipse((0, 0, sz, sz), fill=255)
        bd = PIL.Image.new("RGBA", (sz + 6, sz + 6), (0, 0, 0, 0))
        PIL.ImageDraw.Draw(bd).ellipse((0, 0, sz + 5, sz + 5), fill=(56, 189, 248, 230))
        bd.paste(im, (3, 3), msk)
        return bd
    except Exception:
        return None

LOGO_PIL = load_logo(66)
LOGO_SH = load_logo(84)

def get_font(sz, bold=True):
    sfx = "Bold.ttf" if bold else "Regular.ttf"
    for p in [
        f"/usr/share/fonts/truetype/liberation/LiberationSans-{sfx}",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    ]:
        if os.path.exists(p):
            try:
                return PIL.ImageFont.truetype(p, sz)
            except Exception:
                pass
    return PIL.ImageFont.load_default()

def fetch_live_trend(used_n):
    cands, hdr = [], {"User-Agent": "Mozilla/5.0"}
    for s in random.sample(SEEDS, 4):
        try:
            u = "https://suggestqueries.google.com/complete/search?client=firefox&hl=en&gl=us&q=" + urllib.parse.quote(s)
            r = requests.get(u, headers=hdr, timeout=8)
            if r.status_code == 200:
                d = r.json()
                for x in (d[1][:4] if isinstance(d, list) and len(d) > 1 else []):
                    q = clean_txt(x)
                    nm = re.sub(r"[^a-z0-9]", "", q.lower())[:45]
                    if len(q) > 15 and nm and nm not in used_n:
                        sc = sum(5 for k in TERMS if k in q.lower()) + 9
                        cands.append({
                            "title": q.title(), "summary": f"Live trend: {q}.",
                            "source_name": "Google Search Trends",
                            "source_url": "https://trends.google.com/trends/explore?geo=US&q=" + urllib.parse.quote(q),
                            "norm": nm, "score": sc
                        })
        except Exception:
            pass
    for sn, fu in FEEDS:
        try:
            r = requests.get(fu, headers=hdr, timeout=10)
            if r.status_code != 200:
                continue
            for e in feedparser.parse(r.content).entries[:12]:
                t = clean_txt(getattr(e, "title", ""))
                sm = clean_txt(getattr(e, "summary", getattr(e, "description", "")))[:280]
                lk = clean_txt(getattr(e, "link", "")) or fu
                nm = re.sub(r"[^a-z0-9]", "", t.lower())[:45]
                if len(t) < 15 or not nm or nm in used_n:
                    continue
                ht = sum(5 for k in TERMS if k in f"{t} {sm}".lower())
                if "trends.google.com" in fu and ht == 0:
                    continue
                bn = 7 if ("when:1d" in fu or "trends.google.com" in fu) else 3
                cands.append({"title": t, "summary": sm or t, "source_name": sn, "source_url": lk, "norm": nm, "score": ht + bn})
        except Exception:
            pass
    if not cands:
        fb = "Hidden Signs Of Magnesium And Vitamin D3 Deficiency On Sleep And Liver"
        cands.append({"title": fb, "summary": fb, "source_name": "NIH MedlinePlus", "source_url": "https://medlineplus.gov/", "norm": "magnesiumvitd3", "score": 20})
    wf = {}
    for c in cands:
        for w in re.findall(r"[a-z]{4,}", c["title"].lower()):
            if w in TERMS:
                wf[w] = wf.get(w, 0) + 1
    for c in cands:
        for w in re.findall(r"[a-z]{4,}", c["title"].lower()):
            c["score"] += wf.get(w, 0) * 3
    cands.sort(key=lambda x: x["score"], reverse=True)
    best = cands[0]
    bw = set(re.findall(r"[a-z]{4,}", best["title"].lower()))
    srcs, seen = [], set()
    for c in cands:
        cw = set(re.findall(r"[a-z]{4,}", c["title"].lower()))
        sn = c["source_name"]
        if (c is best or len(bw.intersection(cw)) >= 1) and sn not in seen:
            seen.add(sn)
            srcs.append({"name": sn, "title": c["title"], "url": c["source_url"]})
            if len(srcs) >= 5:
                break
    for br in [
        {"name": "NIH / PubMed", "title": f"Clinical Overview: {best['title']}", "url": "https://pubmed.ncbi.nlm.nih.gov/"},
        {"name": "Cleveland Clinic", "title": "Root Causes and Nutrition Guide", "url": "https://my.clevelandclinic.org/"},
        {"name": "Harvard Health", "title": "Metabolic and Preventive Review", "url": "https://www.health.harvard.edu/"},
        {"name": "Mayo Clinic", "title": "Symptoms and Lifestyle Protocol", "url": "https://www.mayoclinic.org/"}
    ]:
        if len(srcs) < 5 and br["name"] not in seen:
            seen.add(br["name"])
            srcs.append(br)
    best["sources"] = srcs[:5]
    return best

def call_gemini(prompt):
    if not GEMINI_API_KEY:
        return None
    fn = "\x60\x60\x60"
    for m in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
        try:
            r = genai.GenerativeModel(m).generate_content(prompt, generation_config={"temperature": 0.45})
            txt = r.text.strip().replace(fn + "json", "").replace(fn, "").strip()
            mt = re.search(r"\{.*\}", txt, re.S)
            if mt:
                return json.loads(mt.group(0))
        except Exception:
            pass
    return None

def build_fallback(tr):
    t = tr["title"]
    heads = [
        "1. THE SILENT EARLY WARNING SIGN",
        "2. THE ROOT CAUSE INSIDE YOUR CELLS",
        "3. EVERYDAY FOODS THAT TRIGGER IT",
        "4. HOW LIVER, GUT & NERVES REACT",
        "5. THE SIMPLE DAILY NUTRIENT FIX",
        "6. YOUR 7-DAY ACTION PLAN"
    ]
    vqs = [
        "doctor medical scan", "red blood cells artery", "human liver animation",
        "digestive gut health", "avocado leafy greens", "lemon water morning",
        "walking morning sun", "peaceful sleep night"
    ]
    ps = [
        f"Today's top health search centers on {t}. Most people ignore subtle daily signals like waking up exhausted at three in the morning, feeling stiffness in the shoulders, or craving sweet snacks after dinner. Think of these signals like the check engine light flashing on your car dashboard long before the engine overheats on the highway.",
        "When you cover up that dashboard light with black tape, the mechanical problem underneath keeps growing quietly every single day. Someone who drinks three cups of strong coffee just to push through afternoon brain fog is not fixing a caffeine shortage; their cells are struggling to convert food into clean electrical energy.",
        "Imagine trying to charge your mobile phone with a frayed, loose cable that disconnects every few seconds. Even if the phone stays plugged into the wall all night, you still wake up to a battery sitting at twenty percent. That is the exact biological frustration happening inside millions of people who feel drained every morning.",
        "By learning how to read these early body whispers, you can address the real cellular bottleneck before it turns into a chronic struggle. Think of insulin, bile, and electrolytes like a key turning a lock on your front door, or warm dish soap dissolving stubborn grease on a dinner plate so your organs can repair naturally."
    ]
    pts = [{"point_number": i + 1, "point_title": h, "visual_queries": vqs, "paragraphs": list(ps)} for i, h in enumerate(heads)]
    return {
        "video_title": f"{t}: 6 Warning Signs & The Simple Daily Fix!",
        "thumbnail_hook": "FIX THE ROOT CAUSE!",
        "intro_hook": f"Have you ever wondered why {t.lower()} is suddenly one of the most searched health topics today, and could your body already be showing the early warning signs right now? Stay with me as we uncover the hidden cellular root cause using simple everyday examples and walk through the natural home solution step by step.",
        "points": pts,
        "outro": "If you found today's breakdown helpful, please take a second to hit the like button and subscribe to the channel so you never miss our daily health guides. Also, share in the comments which symptom or tip stood out to you the most, we love reading your thoughts and wish you vibrant health.",
        "short_script": {
            "hook": f"If you want to understand {t.lower()}, watch what happens inside your cells every single day.",
            "body": "Most people treat the surface symptom while ignoring the cellular doorway. When excess sugar and stress hormones jam your mineral locks, fuel stays trapped in the blood while your nerves and liver starve for energy. By cutting late-night snacks, adding potassium-rich greens, and taking a ten-minute walk after meals, you reopen that cellular doorway naturally.",
            "cta": "Watch our full step-by-step guide on the channel, and please hit like, comment, and subscribe for daily health solutions!",
            "visual_queries": [q + " vertical" for q in vqs]
        }
    }

def generate_script(tr):
    fb = build_fallback(tr)
    pr = (
        f"You are the educator for MedPulse 5. Today's #1 trending health search is: {tr['title']} ({tr['summary']}).\n"
        "Create a single-topic script explaining physiology in simple language using everyday analogies (car dashboard light, dish soap dissolving grease, clogged filter, lock and key) and daily food/symptom examples.\n"
        "RULES: 1. NEVER mention Dr. Berg or any person name. Do NOT read URLs aloud. 2. 6 SEQUENTIAL POINTS, each with 4 spoken paragraphs (70-85 words each, 24 paragraphs total) for a 9.5+ minute video. 3. 8 visual_queries per point. 4. Thrilling intro_hook (45-60 words) and polite outro (50-65 words) asking to subscribe, comment, and like. 5. short_script with hook, body, cta, and 8 vertical visual_queries.\n"
        "Return ONLY valid JSON with keys: video_title, thumbnail_hook, intro_hook, points, outro, short_script."
    )
    d = call_gemini(pr)
    if not d or not isinstance(d.get("points"), list) or len(d["points"]) < 6:
        return fb
    for i in range(6):
        fp, pt = fb["points"][i], d["points"][i]
        pt["point_number"] = i + 1
        pt["point_title"] = clean_txt(pt.get("point_title") or fp["point_title"]).upper()[:56]
        ps = [sanitize(p) for p in (pt.get("paragraphs") or []) if len(clean_txt(p).split()) >= 25]
        while len(ps) < 4:
            ps.append(fp["paragraphs"][len(ps)])
        pt["paragraphs"] = ps[:4]
        vq = [clean_txt(q) for q in (pt.get("visual_queries") or []) if clean_txt(q)]
        while len(vq) < 8:
            vq.append(fp["visual_queries"][len(vq) % 8])
        pt["visual_queries"] = vq[:8]
    d["video_title"] = clean_txt(d.get("video_title") or fb["video_title"])[:90]
    d["thumbnail_hook"] = clean_txt(d.get("thumbnail_hook") or fb["thumbnail_hook"]).upper()[:28]
    d["intro_hook"] = sanitize(d.get("intro_hook") or fb["intro_hook"])
    d["outro"] = sanitize(d.get("outro") or fb["outro"])
    if not isinstance(d.get("short_script"), dict):
        d["short_script"] = fb["short_script"]
    else:
        for k in ["hook", "body", "cta"]:
            d["short_script"][k] = sanitize(d["short_script"].get(k) or fb["short_script"][k])
        svq = [clean_txt(q) for q in (d["short_script"].get("visual_queries") or []) if clean_txt(q)]
        while len(svq) < 8:
            svq.append(fb["short_script"]["visual_queries"][len(svq) % 8])
        d["short_script"]["visual_queries"] = svq[:8]
    return d

async def _tts(txt, mp3_p, rt, pt):
    await edge_tts.Communicate(txt, VOICE_NAME, rate=rt, pitch=pt).save(mp3_p)

def gen_wav(txt, out_w, rt=VOICE_RATE, pt=VOICE_PITCH, pad=0.38):
    mp3 = out_w.replace(".wav", "_r.mp3")
    for _ in range(3):
        try:
            asyncio.run(_tts(txt, mp3, rt, pt))
            if os.path.exists(mp3) and os.path.getsize(mp3) > 400:
                cmd = ["ffmpeg", "-y", "-i", mp3, "-af", f"apad=pad_dur={pad:.2f}", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2", out_w]
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if os.path.exists(mp3):
                    os.remove(mp3)
                if os.path.exists(out_w) and os.path.getsize(out_w) > 1000:
                    return True
        except Exception:
            time.sleep(1)
    AudioArrayClip(np.zeros((88200, 2), dtype=np.float32), fps=44100).write_audiofile(out_w, fps=44100, verbose=False, logger=None)
    return False

def gen_bgm(dur):
    sr, tot = 44100, int(dur * 44100)
    data = np.zeros((tot, 2), dtype=np.float32)
    for s in range(0, tot, sr * 10):
        e = min(tot, s + sr * 10)
        t = np.linspace(s / sr, e / sr, e - s, endpoint=False, dtype=np.float32)
        w = sum(0.25 * np.sin(2 * np.pi * f * t) for f in [130.81, 196.0, 246.94, 293.66])
        data[s:e, 0] = data[s:e, 1] = (w * (0.65 + 0.35 * np.sin(2 * np.pi * 0.07 * t)) * 0.032).astype(np.float32)
    return AudioArrayClip(data, fps=sr)

def make_chime(dur=2.8):
    sr = 44100
    t = np.linspace(0, dur, int(sr * dur), endpoint=False, dtype=np.float32)
    s = (0.45 * np.sin(2 * np.pi * 528.0 * t) + 0.3 * np.sin(2 * np.pi * 660.0 * t)) * np.exp(-2.0 * t) * 0.1
    return AudioArrayClip(np.column_stack([s, s]).astype(np.float32), fps=sr)

def dl_pexels(q, used_v, out_r, port=False):
    if not PEXELS_API_KEY:
        return False
    hdr, ori = {"Authorization": PEXELS_API_KEY}, ("portrait" if port else "landscape")
    for qr in [q, "medical animation", "doctor hospital", "healthy food"]:
        try:
            u = f"https://api.pexels.com/videos/search?query={urllib.parse.quote(qr)}&per_page=15&orientation={ori}"
            r = requests.get(u, headers=hdr, timeout=12)
            if r.status_code != 200:
                continue
            vids = r.json().get("videos", [])
            random.shuffle(vids)
            for v in vids:
                vid, vw, vh = str(v.get("id", "")), v.get("width", 0), v.get("height", 0)
                if not vid or vid in used_v or (port and vh <= vw) or (not port and vw <= vh):
                    continue
                val = []
                for vf in v.get("video_files", []):
                    fw, fh = vf.get("width", 0), vf.get("height", 0)
                    if (port and fh > fw and fw >= 540) or (not port and fw > fh and fh >= 540):
                        val.append(vf)
                if not val:
                    continue
                val.sort(key=lambda x: abs(x.get("width", 0) - (1080 if port else 1280)))
                vr = requests.get(val[0].get("link", ""), timeout=25)
                if vr.status_code == 200 and len(vr.content) > 50000:
                    with open(out_r, "wb") as f:
                        f.write(vr.content)
                    used_v.add(vid)
                    save_set(USED_VIDEOS_FILE, vid)
                    return True
        except Exception:
            pass
    return False

def norm_clip(raw_p, out_p, dur, tw, th):
    vf = f"scale={tw}:{th}:force_original_aspect_ratio=increase,crop={tw}:{th},setsar=1:1,fps={FPS},format=yuv420p"
    cmd = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", raw_p, "-t", f"{dur:.2f}", "-vf", vf, "-an", "-metadata:s:v:0", "rotate=0", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "21", "-threads", "4", out_p]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return os.path.exists(out_p) and os.path.getsize(out_p) > 10000

def prep_two(q1, q2, used_v, out_p, dur):
    h1, h2 = max(2.0, round(dur * 0.5, 2)), max(2.0, round(dur * 0.5 + 0.15, 2))
    r1, r2, p1, p2 = out_p + "_r1.mp4", out_p + "_r2.mp4", out_p + "_p1.mp4", out_p + "_p2.mp4"
    ok1 = dl_pexels(q1, used_v, r1, False) and norm_clip(r1, p1, h1, W, H)
    ok2 = dl_pexels(q2, used_v, r2, False) and norm_clip(r2, p2, h2, W, H)
    for f in [r1, r2]:
        if os.path.exists(f):
            os.remove(f)
    if ok1 and ok2:
        lf = out_p + "_l.txt"
        with open(lf, "w", encoding="utf-8") as f:
            f.write(f"file '{os.path.abspath(p1)}'\nfile '{os.path.abspath(p2)}'\n")
        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lf, "-c", "copy", out_p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for f in [p1, p2, lf]:
            if os.path.exists(f):
                os.remove(f)
        if os.path.exists(out_p) and os.path.getsize(out_p) > 15000:
            return True
    for f in [p1, p2]:
        if os.path.exists(f):
            os.replace(f, out_p)
            return True
    ImageClip(np.array(PIL.Image.new("RGB", (W, H), (14, 24, 42)))).set_duration(dur).write_videofile(out_p, fps=FPS, codec="libx264", audio=False, verbose=False, logger=None)
    return True

def split_subs(txt, mw=8):
    w = txt.split()
    return [" ".join(w[i:i + mw]) for i in range(0, len(w), mw)] if w else ["..."]

def make_ov(lbl, sub):
    im = PIL.Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dr = PIL.ImageDraw.Draw(im)
    if LOGO_PIL is not None:
        im.paste(LOGO_PIL, (W - 90, 20), LOGO_PIL)
    if sub:
        fn, w = get_font(28, True), sub.split()
        lns = [" ".join(w[:len(w)//2]), " ".join(w[len(w)//2:])] if len(w) > 5 else [sub]
        bh = 44 * len(lns) + 20
        by = H - 80 - bh
        dr.rounded_rectangle((130, by, W - 130, by + bh), radius=12, fill=(8, 14, 26, 215), outline=(56, 189, 248, 150), width=2)
        for i, ln in enumerate(lns):
            bb = dr.textbbox((0, 0), ln, font=fn)
            tx, ty = (W - (bb[2] - bb[0])) // 2, by + 10 + i * 42
            dr.text((tx + 2, ty + 2), ln, font=fn, fill=(0, 0, 0, 240))
            dr.text((tx, ty), ln, font=fn, fill=(255, 255, 255, 255))
    dr.rectangle((0, H - 62, W, H), fill=(10, 18, 34, 235))
    dr.rectangle((0, H - 65, W, H - 62), fill=(56, 189, 248, 255))
    dr.rectangle((24, H - 52, 168, H - 12), fill=(14, 116, 144, 255))
    dr.text((38, H - 44), "MEDPULSE 5", font=get_font(19, True), fill=(255, 255, 255, 255))
    dr.text((186, H - 45), lbl[:66], font=get_font(22, True), fill=(240, 249, 255, 255))
    return np.array(im)

def make_card(pn, ptitle, top, dur=2.8):
    im = PIL.Image.new("RGB", (W, H), (10, 18, 34))
    dr = PIL.ImageDraw.Draw(im)
    dr.rectangle((0, 0, W, 10), fill=(56, 189, 248))
    dr.rectangle((0, H - 10, W, H), fill=(56, 189, 248))
    dr.rounded_rectangle((110, 150, W - 110, H - 150), radius=22, fill=(17, 28, 52), outline=(56, 189, 248), width=3)
    dr.rounded_rectangle((150, 195, 380, 248), radius=10, fill=(14, 116, 144))
    dr.text((172, 208), f"KEY POINT 0{pn} OF 06", font=get_font(22, True), fill=(255, 255, 255))
    dr.text((150, 285), ptitle[:48], font=get_font(40, True), fill=(255, 255, 255))
    dr.rectangle((150, 355, W - 150, 358), fill=(56, 189, 248))
    dr.text((150, 385), f"TODAY'S TREND: {top[:68]}", font=get_font(23, False), fill=(186, 230, 253))
    dr.text((150, 445), "MEDPULSE 5  |  EVIDENCE-BASED HEALTH EXPLAINED SIMPLY", font=get_font(19, True), fill=(125, 211, 252))
    if LOGO_PIL is not None:
        im.paste(LOGO_PIL.convert("RGB"), (W - 190, 185))
    return ImageClip(np.array(im)).set_duration(dur).set_audio(make_chime(dur))

def build_para(vp, wp, lbl, txt):
    ra = AudioFileClip(wp)
    sd = max(0.4, ra.duration - 0.08)
    ac, vc = ra.subclip(0, sd), VideoFileClip(vp)
    vc = vc.loop(duration=sd) if vc.duration < sd else vc.subclip(0, sd)
    chs = split_subs(txt, 8)
    wcs = [max(1, len(c.split())) for c in chs]
    tw, ovs, tc = sum(wcs), [], 0.0
    for i, ch in enumerate(chs):
        cd = max(0.2, (sd - tc) if i == len(chs) - 1 else round(sd * (wcs[i] / tw), 3))
        ovs.append(ImageClip(make_ov(lbl, ch)).set_start(tc).set_duration(cd))
        tc += cd
    return CompositeVideoClip([vc] + ovs, size=(W, H)).set_duration(sd).set_audio(ac), vc, ra

def make_sh_ov(bdg, cap):
    im = PIL.Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    dr = PIL.ImageDraw.Draw(im)
    dr.rounded_rectangle((48, 78, SW - 165, 162), radius=22, fill=(10, 18, 34, 225), outline=(56, 189, 248, 220), width=3)
    dr.text((76, 103), f"MEDPULSE 5  |  {bdg[:28].upper()}", font=get_font(28, True), fill=(255, 255, 255, 255))
    if LOGO_SH is not None:
        im.paste(LOGO_SH, (SW - 132, 74), LOGO_SH)
    if cap:
        fn, w = get_font(56, True), cap.upper().split()
        lns = [" ".join(w[:len(w)//2]), " ".join(w[len(w)//2:])] if len(w) > 3 else [" ".join(w)]
        bh, by = 78 * len(lns) + 44, 1120
        dr.rounded_rectangle((64, by, SW - 64, by + bh), radius=28, fill=(8, 14, 28, 230), outline=(250, 204, 21, 240), width=4)
        for i, ln in enumerate(lns):
            bb = dr.textbbox((0, 0), ln, font=fn)
            tx, ty = (SW - (bb[2] - bb[0])) // 2, by + 22 + i * 76
            for dx, dy in [(-3, -3), (3, -3), (-3, 3), (3, 3), (0, 4)]:
                dr.text((tx + dx, ty + dy), ln, font=fn, fill=(0, 0, 0, 255))
            dr.text((tx, ty), ln, font=fn, fill=(250, 204, 21, 255) if i == 0 else (255, 255, 255, 255))
    dr.rounded_rectangle((180, SH - 170, SW - 180, SH - 96), radius=36, fill=(14, 116, 144, 235), outline=(255, 255, 255, 200), width=2)
    dr.text((255, SH - 148), "LIKE, COMMENT & SUBSCRIBE", font=get_font(32, True), fill=(255, 255, 255, 255))
    return np.array(im)

def build_short(d, used_v):
    sh = d.get("short_script", {})
    ft = f"{sh.get('hook', '')} {sh.get('body', '')} {sh.get('cta', '')}".strip()
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", ft) if len(s.strip()) > 8]
    if len(sents) < 6:
        w = ft.split()
        st = max(10, len(w) // 7)
        sents = [" ".join(w[i:i + st]) for i in range(0, len(w), st)]
    sents, vqs, bdg = sents[:8], (sh.get("visual_queries") or ["doctor vertical"]), d.get("thumbnail_hook", "HEALTH FIX")
    clips, res = [], []
    for i, s in enumerate(sents):
        wp, rv, nv = f"temp/sh_{i}.wav", f"temp/shr_{i}.mp4", f"temp/shn_{i}.mp4"
        gen_wav(s, wp, rt=SHORT_RATE, pt=VOICE_PITCH, pad=0.22)
        ra = AudioFileClip(wp)
        sd = max(0.4, ra.duration - 0.06)
        ac = ra.subclip(0, sd)
        ok = dl_pexels(vqs[i % len(vqs)], used_v, rv, True) and norm_clip(rv, nv, sd + 0.2, SW, SH)
        if os.path.exists(rv):
            os.remove(rv)
        if not ok:
            ImageClip(np.array(PIL.Image.new("RGB", (SW, SH), (12, 22, 40)))).set_duration(sd + 0.2).write_videofile(nv, fps=FPS, codec="libx264", audio=False, verbose=False, logger=None)
        vc, chs = VideoFileClip(nv).subclip(0, sd), split_subs(s, 4)
        wcs = [max(1, len(c.split())) for c in chs]
        tw, ovs, tc = sum(wcs), [], 0.0
        for ci, ch in enumerate(chs):
            cd = max(0.18, (sd - tc) if ci == len(chs) - 1 else round(sd * (wcs[ci] / tw), 3))
            ovs.append(ImageClip(make_sh_ov(bdg, ch)).set_start(tc).set_duration(cd))
            tc += cd
        clips.append(CompositeVideoClip([vc] + ovs, size=(SW, SH)).set_duration(sd).set_audio(ac))
        res.extend([vc, ra])
    fin = concatenate_videoclips(clips, method="compose")
    fin = fin.set_audio(CompositeAudioClip([fin.audio, gen_bgm(fin.duration)]))
    fin.write_videofile("output/short_video.mp4", fps=FPS, codec="libx264", audio_codec="aac", bitrate="5000k", preset="ultrafast", threads=4, ffmpeg_params=["-pix_fmt", "yuv420p", "-movflags", "+faststart"])
    for r in res:
        try:
            r.close()
        except Exception:
            pass

def write_details(d, tr, ts):
    sp, tg, t, hk = "=" * 60, "\x23", d["video_title"], d["thumbnail_hook"]
    srcs = tr.get("sources", [])
    sl = [f"{i}. {s.get('name', 'Source')} - {s.get('title', t)}\n   Link: {s.get('url', '')}" for i, s in enumerate(srcs, 1)]
    tp = f"Ultra-detailed 16:9 medical thumbnail, clinical visualization of {tr['title']}, glowing cellular highlight, bold 3D text '{hk}', 8k."
    out = [
        sp, "1. LONG VIDEO TITLE:", sp, t, "",
        sp, "2. DESCRIPTION (TIMESTAMPS & DIVERSE SOURCES ONLY HERE):", sp, t, "",
        f"In today's deep dive on MedPulse 5, we break down today's top health trend ({tr['title']}) using simple everyday examples and a step-by-step daily plan.",
        "", "CHAPTER TIMESTAMPS:", "\n".join(ts), "",
        "SCIENTIFIC & MEDICAL SOURCES FOR THIS VIDEO:", "\n".join(sl), "",
        "Please hit LIKE, leave a COMMENT, and SUBSCRIBE to MedPulse 5!",
        "Disclaimer: Educational purposes only, not medical advice.",
        f"{tg}MedPulse5 {tg}HealthTips {tg}NaturalRemedies {tg}NutritionScience",
        "", sp, "3. YOUTUBE TAGS:", sp,
        f"MedPulse 5, {tr['title']}, root cause health, natural remedies, nutrition, vitamin deficiency, daily health tips",
        "", sp, "4. YOUTUBE SHORT TITLE & DESCRIPTION:", sp,
        f"Short Title: {tr['title'][:55]} - Watch What Happens! {tg}Shorts {tg}Health",
        f"Short Description: Quick guide on {tr['title']}. Sources: {', '.join(s.get('name', '') for s in srcs[:3])}",
        "", sp, "5. AI THUMBNAIL PROMPT (PERCHANCE 16:9):", sp, tp
    ]
    with open("output/youtube_details.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")

def main():
    used_n, used_v = load_set(USED_NEWS_FILE), load_set(USED_VIDEOS_FILE)
    tr = fetch_live_trend(used_n)
    d = generate_script(tr)
    clips, res, ts, cur_t = [], [], ["00:00 Introduction: Today's Top Health Search"], 0.0

    iw, iv = "temp/intro.wav", "temp/intro.mp4"
    gen_wav(d["intro_hook"], iw)
    ra = AudioFileClip(iw)
    prep_two("medical scan anatomy", "doctor explaining clinic", used_v, iv, ra.duration + 0.3)
    ra.close()
    ci, vi, ai = build_para(iv, iw, f"TODAY'S TREND: {tr['title'].upper()}", d["intro_hook"])
    clips.append(ci); res.extend([vi, ai]); cur_t += ci.duration

    for pt in d["points"]:
        pn, ptl, vqs = pt["point_number"], pt["point_title"], pt["visual_queries"]
        ts.append(f"{int(cur_t // 60):02d}:{int(cur_t % 60):02d} {ptl.title()}")
        cd = make_card(pn, ptl, tr["title"], 2.8)
        clips.append(cd); cur_t += cd.duration
        for pi, ptxt in enumerate(pt["paragraphs"]):
            wp, vp = f"temp/p_{pn}_{pi}.wav", f"temp/p_{pn}_{pi}.mp4"
            gen_wav(ptxt, wp)
            ta = AudioFileClip(wp); pd = ta.duration + 0.3; ta.close()
            prep_two(vqs[(pi * 2) % len(vqs)], vqs[(pi * 2 + 1) % len(vqs)], used_v, vp, pd)
            cp, vcp, acp = build_para(vp, wp, ptl, ptxt)
            clips.append(cp); res.extend([vcp, acp]); cur_t += cp.duration

    bns = [
        "Let us also look at a common real-life mistake people make when trying to fix this overnight. Many people buy random supplements without fixing their evening meal timing or hydration first. Think of supplements like putting premium tires on a car that still has no motor oil inside the engine. When you combine clean hydration, natural electrolytes, and whole foods first, every nutrient works twice as well.",
        "Another practical example you can test this week is tracking how your body feels ninety minutes after lunch. If you feel a sudden wave of yawning, heavy eyelids, or a craving for something sweet, that is your body telling you that your lunch had too many fast carbohydrates for your current insulin sensitivity. Replacing half of those starches with leafy greens and olive oil steadies your focus immediately."
    ]
    bi = 0
    while cur_t < MIN_LONG_SEC and bi < len(bns):
        wb, vb = f"temp/b_{bi}.wav", f"temp/b_{bi}.mp4"
        gen_wav(bns[bi], wb)
        ta = AudioFileClip(wb); bd = ta.duration + 0.3; ta.close()
        prep_two("healthy kitchen nutrition", "peaceful sleep recovery", used_v, vb, bd)
        cb, vcb, acb = build_para(vb, wb, "PRACTICAL DAILY APPLICATION", bns[bi])
        clips.append(cb); res.extend([vcb, acb]); cur_t += cb.duration; bi += 1

    ts.append(f"{int(cur_t // 60):02d}:{int(cur_t % 60):02d} Final Summary & Daily Takeaway")
    ow, ov = "temp/outro.wav", "temp/outro.mp4"
    gen_wav(d["outro"], ow)
    to = AudioFileClip(ow)
    prep_two("happy healthy outdoors", "medical wellness nature", used_v, ov, to.duration + 0.3)
    to.close()
    co, vo, ao = build_para(ov, ow, "SUBSCRIBE, COMMENT & LIKE  |  MEDPULSE 5", d["outro"])
    clips.append(co); res.extend([vo, ao])

    fin = concatenate_videoclips(clips, method="compose")
    fin = fin.set_audio(CompositeAudioClip([fin.audio, gen_bgm(fin.duration)]))
    fin.write_videofile("output/final_video.mp4", fps=FPS, codec="libx264", audio_codec="aac", bitrate="3500k", preset="ultrafast", threads=4, ffmpeg_params=["-pix_fmt", "yuv420p", "-movflags", "+faststart"])
    for r in res:
        try:
            r.close()
        except Exception:
            pass

    build_short(d, used_v)
    write_details(d, tr, ts)
    save_set(USED_NEWS_FILE, tr["norm"])

if __name__ == "__main__":
    main()
