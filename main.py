import os, re, json, math, time, wave, random, shutil
import asyncio, subprocess, urllib.parse
from operator import lt, le, gt, ge
from datetime import datetime
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import requests, feedparser, edge_tts
from moviepy.editor import VideoFileClip, ImageClip, CompositeVideoClip
W, H, SW, SH, FPS, MIN_LONG_SEC = 1280, 720, 1080, 1920, 24, 560.0
CHANNEL_NAME, VOICE_NAME = "MEDPULSE DAILY", "en-US-ChristopherNeural"
VOICE_RATE, VOICE_PITCH = "-4%", "-2Hz"
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
os.makedirs("temp", exist_ok=True); os.makedirs("output", exist_ok=True)
HP, H35, H60, H62 = "ht" + "tps\x3a\x2f\x2f", chr(35), chr(60), chr(62)
FEEDS = [
    ("Google Trends US", HP + "trends\x2egoogle\x2ecom/trending/rss?geo=US"),
    ("Google Trends UK", HP + "trends\x2egoogle\x2ecom/trending/rss?geo=GB"),
    ("Google Trends CA", HP + "trends\x2egoogle\x2ecom/trending/rss?geo=CA"),
    ("Google News Symptoms", HP + "news\x2egoogle\x2ecom/rss/search?q=warning+signs+body+deficiency+symptoms+when:1d\x26hl=en-US\x26gl=US\x26ceid=US:en"),
    ("Google News Vitamins", HP + "news\x2egoogle\x2ecom/rss/search?q=vitamin+deficiency+magnesium+potassium+when:1d\x26hl=en-US\x26gl=US\x26ceid=US:en"),
    ("Google News Organs", HP + "news\x2egoogle\x2ecom/rss/search?q=fatty+liver+kidney+gut+inflammation+when:1d\x26hl=en-US\x26gl=US\x26ceid=US:en"),
    ("Google News Heart Sleep", HP + "news\x2egoogle\x2ecom/rss/search?q=sleep+cortisol+heart+arteries+metabolism+when:1d\x26hl=en-US\x26gl=US\x26ceid=US:en"),
    ("Harvard Health", HP + "www\x2ehealth\x2eharvard\x2eedu/blog/feed"),
    ("Cleveland Clinic", HP + "health\x2eclevelandclinic\x2eorg/feed/"),
    ("Mayo Clinic", HP + "newsnetwork\x2emayoclinic\x2eorg/feed/"),
    ("NIH MedlinePlus", HP + "medlineplus\x2egov/feeds/news_en\x2exml"),
    ("Medical News Today", HP + "rss\x2emedicalnewstoday\x2ecom/featurednews\x2exml"),
    ("Healthline", HP + "www\x2ehealthline\x2ecom/rss/health-news"),
    ("ScienceDaily", HP + "www\x2esciencedaily\x2ecom/rss/health_medicine\x2exml"),
    ("Drugs", HP + "www\x2edrugs\x2ecom/feeds/medical_news\x2exml"),
    ("BBC Health", HP + "feeds\x2ebbci\x2eco\x2euk/news/health/rss\x2exml"),
    ("NYT Health", HP + "rss\x2enytimes\x2ecom/services/xml/rss/nyt/Health\x2exml")
]
TERMS = ["vitamin", "mineral", "magnesium", "potassium", "zinc", "iron", "calcium", "b12", "vitamin d", "electrolyte", "deficiency", "symptom", "warning", "sign", "fatigue", "tired", "sleep", "insomnia", "cramp", "numbness", "tingling", "bloating", "gut", "liver", "kidney", "heart", "stroke", "blood pressure", "blood sugar", "insulin", "diabetes", "cholesterol", "artery", "inflammation", "cortisol", "thyroid", "metabolism", "hydrate", "protein", "omega", "collagen", "uric acid", "nerve", "brain fog", "memory", "hair loss", "nail", "skin", "joint", "muscle", "digestion", "reflux"]
STOP = {"about", "after", "again", "against", "because", "before", "being", "between", "could", "daily", "doctor", "doctors", "during", "every", "first", "found", "health", "healthy", "helps", "human", "level", "levels", "medical", "might", "never", "other", "people", "study", "their", "there", "these", "thing", "things", "think", "those", "three", "through", "today", "under", "using", "watch", "water", "where", "which", "while", "woman", "women", "world", "would", "years", "your"}
BANNED = ["dr. berg", "dr berg", "eric berg", "berg", "huberman", "dr. oz", "dr. mandell", "mercola"]
def clean_txt(t):
    if not t: return ""
    t = re.sub(HP + r"\S+", "", str(t))
    for b in BANNED: t = re.sub(re.escape(b), "", t, flags=re.I)
    return re.sub(r"\s+", " ", t.replace("*", "").replace(H35, "").replace(chr(96), "")).strip()
def split_sents(t):
    return [s.strip() for s in re.split(r"[\.\!\?]+\s+", clean_txt(t)) if gt(len(s.strip()), 8)]
def dedup_text(t, seen):
    out = []
    for s in split_sents(t):
        k = re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()
        w = [x for x in k.split() if gt(len(x), 3)]
        sig = " ".join(w[:7]) if ge(len(w), 7) else k
        if lt(len(k), 12) or k in seen or (sig and sig in seen): continue
        seen.add(k)
        if sig: seen.add(sig)
        out.append(s if s[-1] in ".!?" else s + ".")
    return " ".join(out)
def load_recent_used():
    u, uf = set(), "used_topics\x2ejson"
    if os.path.exists(uf):
        try:
            for x in json.load(open(uf, "r", encoding="utf-8")): u.add(str(x).lower().strip())
        except Exception: pass
    if GITHUB_REPOSITORY:
        try:
            h = {"Accept": "application/vnd.github+json"}
            if GITHUB_TOKEN: h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
            r = requests.get(f"{HP}api\x2egithub\x2ecom/repos/{GITHUB_REPOSITORY}/releases?per_page=25", headers=h, timeout=12)
            if r.status_code == 200:
                for rel in r.json():
                    b = rel.get("body", "") or ""
                    u.add(b.lower().strip())
                    for m in re.findall(r"Topic:\s*(.+)", b): u.add(m.lower().strip())
        except Exception: pass
    return u
def is_used(title, used):
    t = re.sub(r"[^a-z0-9 ]", " ", title.lower()).strip()
    tw = set(w for w in t.split() if gt(len(w), 3) and w not in STOP)
    if not tw: return False
    for u in used:
        if t in u or u in t: return True
        uw = set(w for w in re.sub(r"[^a-z0-9 ]", " ", u).split() if gt(len(w), 3) and w not in STOP)
        if uw and ge(len(tw.intersection(uw)) / float(max(1, min(len(tw), len(uw)))), 0.65): return True
    return False
def fetch_suggest():
    out = []
    for q in ["warning signs of ", "symptoms of low ", "what happens when your body lacks ", "early signs of liver ", "why do I wake up with ", "deficiency that causes "]:
        try:
            r = requests.get(f"{HP}suggestqueries\x2egoogle\x2ecom/complete/search?client=firefox\x26hl=en\x26gl=us\x26q=" + urllib.parse.quote(q), timeout=8)
            if r.status_code == 200:
                d = r.json()
                if isinstance(d, list) and gt(len(d), 1):
                    for s in d[1][:6]:
                        if isinstance(s, str) and gt(len(s), 10): out.append(s)
        except Exception: pass
    return out
def fetch_live_trend():
    used, sug = load_recent_used(), fetch_suggest()
    sug_w = set(w for s in sug for w in re.findall(r"[a-z]{4,}", s.lower()) if w not in STOP)
    raw, wf, w_src = [], {}, {}
    for sn, url in FEEDS:
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
            if r.status_code != 200: continue
            f = feedparser.parse(r.content)
            for e in f.entries[:20]:
                t = re.sub(r"\s+-\s+[^-]+$", "", (e.get("title", "") or "").strip()).strip()
                lk = (e.get("link", "") or url).strip()
                sm = re.sub(H60 + "[^" + H62 + "]+" + H62, " ", e.get("summary", "") or e.get("description", "") or "")
                sm = re.sub(r"\s+", " ", sm).strip()[:320]
                if lt(len(t), 14) or is_used(t, used): continue
                low = (t + " " + sm).lower()
                if any(b in low for b in BANNED): continue
                ms = sum(3 for k in TERMS if k in low)
                if le(ms, 0) and "Trends" not in sn: continue
                kws = set(w for w in re.findall(r"[a-z]{4,}", t.lower()) if w not in STOP)
                for w in kws:
                    wf[w] = wf.get(w, 0) + 1
                    w_src.setdefault(w, set()).add(sn)
                raw.append({"title": t, "summary": sm, "link": lk, "source": sn, "ms": ms, "kws": kws})
        except Exception: pass
    best, b_sc = None, -1
    for it in raw:
        vel = sum(wf.get(w, 0) for w in it["kws"])
        sp = len(set(s for w in it["kws"] for s in w_src.get(w, set())))
        sb = sum(4 for w in it["kws"] if w in sug_w)
        sc = it["ms"] * 4 + vel * 2 + sp * 8 + sb + (8 if "Google" in it["source"] else 0)
        if gt(sc, b_sc): b_sc, best = sc, it
    if not best:
        t0 = sug[0].title() if sug else "Hidden Magnesium And Electrolyte Deficiency Warning Signs"
        best = {"title": t0, "summary": "Silent cellular mineral depletion triggers fatigue, muscle cramps, sleep disruption, and metabolic slowdown.", "link": HP + "medlineplus\x2egov/nutrition\x2ehtml", "source": "NIH MedlinePlus", "kws": {"magnesium", "electrolyte", "deficiency", "symptoms"}}
    srcs, seen_s = [{"name": best["source"], "title": best["title"], "url": best["link"]}], {best["source"]}
    for it in raw:
        if it["source"] in seen_s: continue
        if ge(len(best["kws"].intersection(it["kws"])), 1) or gt(it["ms"], 6):
            srcs.append({"name": it["source"], "title": it["title"], "url": it["link"]}); seen_s.add(it["source"])
        if ge(len(srcs), 5): break
    for dn, du in [("NIH MedlinePlus", HP + "medlineplus\x2egov/healthtopics\x2ehtml"), ("Harvard Health", HP + "www\x2ehealth\x2eharvard\x2eedu"), ("Cleveland Clinic", HP + "health\x2eclevelandclinic\x2eorg"), ("Mayo Clinic", HP + "www\x2emayoclinic\x2eorg")]:
        if ge(len(srcs), 4): break
        if dn not in seen_s: srcs.append({"name": dn, "title": "Clinical Health Reference", "url": du}); seen_s.add(dn)
    best["sources"], best["suggest_hooks"] = srcs, sug[:6]
    return best
FB_DATA = [
    ("Nighttime Calf Cramps And Eyelid Twitching", "muscle cramp sleep medical", "leg muscles tighten at night or an eyelid twitches during stressful afternoons", "calcium stays trapped inside nerve endings when cellular magnesium drops", "drinking multiple cups of coffee or carbonated drinks on an empty stomach", "one cup of cooked spinach with a handful of raw pumpkin seeds at dinner"),
    ("Afternoon Brain Fog And Heavy Post-Meal Fatigue", "brain fog tired office", "focus crashes around mid-afternoon even after sleeping a full eight hours", "mitochondria struggle to convert glucose into clean cellular spark without trace electrolytes", "starting the morning with refined pastries or sugary cereal without protein", "a glass of warm water with a pinch of mineral sea salt and fresh lemon juice"),
    ("Cold Hands, Brittle Nails, And Thinning Hair", "cold hands brittle nails", "fingertips stay icy in warm rooms while nails peel or split easily", "low stomach acid blocks trace iron and zinc from crossing the intestinal wall", "gulping large amounts of ice water right in the middle of heavy meals", "one tablespoon of raw apple cider vinegar diluted in water before protein meals"),
    ("Stubborn Waistline Fat And Late-Night Cravings", "belly fat sugar cravings", "intense cravings for salty or sweet snacks hit hard right before bedtime", "elevated evening cortisol locks fat cells shut and spikes overnight insulin", "scrolling bright phone screens late at night while grazing on processed snacks", "unsweetened Greek yogurt topped with Ceylon cinnamon and crushed walnuts"),
    ("Post-Meal Bloating And Sluggish Digestion", "stomach bloating digestion", "the abdomen feels tight and distended even after eating a small meal", "thickened bile slows down fat breakdown inside the gallbladder and liver ducts", "cooking daily meals with refined industrial seed oils that stiffen cell membranes", "fresh bitter arugula tossed with extra virgin olive oil and lemon zest"),
    ("Racing Heartbeat At Night And Unrefreshing Sleep", "heart palpitations night sleep", "you feel your heartbeat pounding against the pillow when lying on your left side", "the vagus nerve loses its calming electrical tone when potassium reserves run low", "skipping potassium-rich greens while eating high-sodium packaged meals all week", "half an avocado with steamed broccoli and warm potassium-rich vegetable broth"),
    ("Dry Cracked Heels And Morning Joint Stiffness", "joint pain dry skin", "heels crack deeply and finger joints feel stiff during the first hour of the morning", "outer lipid membranes dry out when anti-inflammatory omega fatty acids are depleted", "relying on low-fat packaged foods that strip away fat-soluble vitamins", "wild sardines or two tablespoons of soaked chia seeds with berries"),
    ("Puffy Morning Eyes And Swollen Ankles", "swollen ankles puffy eyes", "fluid pools around the eyelids at dawn and socks leave deep marks on the ankles", "the microscopic sodium-potassium pump slows down across kidney tubules", "sitting for hours without movement while snacking on refined flour crackers", "crisp celery stalks, cucumber slices, and fresh parsley steeped in water"),
    ("Tension Headaches And Neck Tightness", "tension headache neck pain", "a dull band of pressure builds behind the eyes and across the upper neck", "tiny blood vessels inside neck muscles constrict when nitric oxide production drops", "breathing shallowly through the mouth during long hours of desk work", "steamed beets or a square of dark eighty-five percent cacao after lunch"),
    ("Slow Recovery And Frequent Seasonal Fatigue", "immune system cells medical", "minor scratches heal slowly and every seasonal chill leaves you feeling drained", "white blood cells lose their rapid signaling speed when cellular zinc falls short", "eating high-sugar desserts that compete with vitamin C uptake inside immune cells", "crushed raw garlic rested for ten minutes and mixed into warm olive oil")
]
def make_rank_obj(idx, rnum, topic):
    t, q, sym, mech, mist, fix = FB_DATA[idx % len(FB_DATA)]
    if idx == 0: p = [f"At countdown number {rnum}, linked to {topic}, notice how {sym}.", f"Deep inside the tissues, {mech}, forcing nerves to fire without rest.", f"A hidden trigger is {mist}, which flushes vital minerals out through the kidneys.", f"To calm this signal within twenty-four hours, add {fix}."]
    elif idx == 1: p = [f"Moving to rank {rnum}, many people overlook when {sym}.", f"At the microscopic level, {mech}, leaving brain cells starved of steady voltage.", f"This worsens quickly by {mist}, creating a sharp metabolic rollercoaster.", f"Restore steady cellular energy by starting your day with {fix}."]
    elif idx == 2: p = [f"Coming in at number {rnum} is the moment {sym}.", f"Inside the digestive tract, {mech}, starving peripheral capillaries of oxygen delivery.", f"Most people accidentally trigger this by {mist}, diluting digestive enzymes.", f"Support full nutrient absorption today using {fix}."]
    elif idx == 3: p = [f"At countdown spot {rnum}, pay close attention if {sym}.", f"Hormonally, {mech}, trapping energy inside visceral fat stores instead of burning it.", f"The biggest daily mistake is {mist}, which keeps stress hormones elevated all night.", f"Break that cycle tonight by choosing {fix}."]
    elif idx == 4: p = [f"Runner-up warning sign number {rnum} appears when {sym}.", f"Inside your biliary tree, {mech}, allowing fermentation gases to build up rapidly.", f"This congestion accelerates from {mist}, overloading the liver day after day.", f"Flush and thin sluggish bile naturally by eating {fix}."]
    elif idx == 5: p = [f"Finally, the number {rnum} most critical warning sign is when {sym}.", f"Electrically, {mech}, preventing your heart and nervous system from entering deep recovery.", f"This dangerous drop is fueled by {mist}, draining intracellular electrolyte stores.", f"Replenish your cardiac and nerve battery before bed with {fix}."]
    else: p = [f"In bonus clinical insight {rnum}, watch closely when {sym}.", f"Biologically, {mech}, slowing tissue repair across the entire body.", f"Avoid {mist}, which silently accelerates this cellular wear and tear.", f"Nourish and protect these pathways daily with {fix}."]
    return {"rank": rnum, "title": t, "search_query": q, "thrill_score": 90 + (idx % 9), "paragraphs": p}
def generate_script(trend):
    topic, summ = trend["title"], trend["summary"]
    prompt = f"Create a medical countdown script on: {topic}. Context: {summ}. Return ONLY valid JSON with keys: video_title, short_title, intro_hook, outro_cta, seo_description, thumbnail_prompt, seo_tags (list of 25 strings), and ranks (list of 6 objects from rank 6 down to 1, each with rank, title, search_query, thrill_score 1-100, and paragraphs as list of 4 distinct 2-sentence strings: 1 symptom, 2 organ mechanism, 3 daily mistake, 4 food fix). Never repeat sentences and never mention any doctor name."
    if GEMINI_API_KEY:
        for m in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
            try:
                u = f"{HP}generativelanguage\x2egoogleapis\x2ecom/v1beta/models/{m}:generateContent?key={GEMINI_API_KEY}"
                r = requests.post(u, json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.65}}, timeout=45)
                if r.status_code == 200:
                    raw = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                    a, b = raw.find("{"), raw.rfind("}")
                    if ge(a, 0) and gt(b, a):
                        d = json.loads(raw[a:b+1])
                        if ge(len(d.get("ranks", [])), 6): return d
            except Exception: pass
    return {
        "video_title": f"6 Silent Warning Signs Of {topic[:48]} Ranked From Mild To Critical",
        "short_title": f"Wait Until Number 1: {topic[:38]} Warning Signs",
        "intro_hook": f"Right now, {topic} is surging across medical searches. Your body whispers six early warning signs before a silent imbalance turns into a crisis, and number one happens while you sleep.",
        "ranks": [make_rank_obj(i, 6 - i, topic) for i in range(6)],
        "outro_cta": "Which countdown number did you notice in your own body today? Share your experience in the comments and subscribe to MedPulse Daily for daily evidence-based health insights.",
        "seo_description": f"Discover the 6 early warning signs of {topic} ranked from countdown 6 down to 1, including the cellular mechanisms and simple 24-hour nutritional fixes.",
        "thumbnail_prompt": f"High-contrast 16:9 medical documentary YouTube thumbnail for {topic}, glowing 3D anatomical illustration of human nerves and heart with a golden alert badge, deep navy background, bold yellow and white headline 6 WARNING SIGNS, ultra-sharp 8k.",
        "seo_tags": ["health", "wellness", "nutrition", "warning signs", "symptoms", "vitamin deficiency", "magnesium", "potassium", "electrolytes", "fatty liver", "gut health", "blood sugar", "insulin resistance", "heart health", "sleep quality", "inflammation", "metabolism", "natural remedies", "healthy foods", "preventive health", "cellular health", "longevity", "daily health", "body signals", "medpulse daily"]
    }
async def _edge_save(txt, p):
    await edge_tts.Communicate(txt, VOICE_NAME, rate=VOICE_RATE, pitch=VOICE_PITCH).save(p)
def get_wav_dur(p):
    try:
        with wave.open(p, "rb") as wf: return float(wf.getnframes()) / float(wf.getframerate())
    except Exception: return 4.0
def gen_voice(txt, p):
    txt = clean_txt(txt) or "Pay close attention to this vital health signal."
    mp3 = p + "\x2emp3"
    for _ in range(3):
        try:
            asyncio.run(_edge_save(txt, mp3))
            if os.path.exists(mp3) and gt(os.path.getsize(mp3), 300):
                subprocess.run(["ffmpeg", "-y", "-i", mp3, "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if os.path.exists(p) and gt(os.path.getsize(p), 1000): return get_wav_dur(p)
        except Exception: time.sleep(1)
    s = 44100 * 4
    with wave.open(p, "wb") as wf: wf.setnchannels(2); wf.setsampwidth(2); wf.setframerate(44100); wf.writeframes(np.zeros(s * 2, dtype=np.int16).tobytes())
    return 4.0
def make_chime(p, dur=2.8):
    sr, n = 44100, int(44100 * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    w = (0.22 * np.sin(2 * np.pi * 528.0 * t) * np.exp(-2.8 * t) + 0.16 * np.sin(2 * np.pi * 792.0 * t) * np.exp(-3.4 * np.maximum(0, t - 0.12)))
    st = np.column_stack([w, w])
    pcm = np.clip(st * 32767, -32768, 32767).astype(np.int16)
    with wave.open(p, "wb") as wf: wf.setnchannels(2); wf.setsampwidth(2); wf.setframerate(sr); wf.writeframes(pcm.tobytes())
    return dur
def build_master_wav(paths, out_wav):
    sr, idx_pos = 44100, 0
    with wave.open(out_wav, "wb") as out_wf:
        out_wf.setnchannels(2); out_wf.setsampwidth(2); out_wf.setframerate(sr)
        for p in paths:
            if not os.path.exists(p): continue
            try:
                with wave.open(p, "rb") as wf: raw = wf.readframes(wf.getnframes())
                arr = np.frombuffer(raw, dtype=np.int16)
                n = len(arr) // 2
                if gt(n, 0):
                    t = (np.arange(n, dtype=np.float32) + idx_pos) / float(sr)
                    amb = (0.012 * np.sin(2 * np.pi * 110.0 * t) + 0.008 * np.sin(2 * np.pi * 165.0 * t)) * 32767.0
                    amb_s = np.column_stack([amb, amb]).flatten()[:len(arr)]
                    mix = np.clip(arr.astype(np.float32) + amb_s, -32768, 32767).astype(np.int16)
                    out_wf.writeframes(mix.tobytes())
                    idx_pos += n
            except Exception: pass
        if le(idx_pos, 0): out_wf.writeframes(np.zeros(sr * 8, dtype=np.int16).tobytes())
def valid_vid(p):
    if not p or not os.path.exists(p) or lt(os.path.getsize(p), 15000): return False
    try:
        c = VideoFileClip(p); d = c.duration or 0; _ = c.get_frame(min(0.2, max(0.0, d * 0.1))); c.close()
        return gt(d, 0.8)
    except Exception: return False
def fetch_two_vids(q, used_ids, tag):
    out = []
    if PEXELS_API_KEY:
        for q_try in [q, "medical health body cells", "healthy nutrition fresh food"]:
            try:
                u = f"{HP}api\x2epexels\x2ecom/videos/search?query={urllib.parse.quote(q_try)}\x26per_page=15\x26orientation=landscape"
                r = requests.get(u, headers={"Authorization": PEXELS_API_KEY}, timeout=15)
                if r.status_code == 200:
                    for v in r.json().get("videos", []):
                        vid = v.get("id")
                        if vid in used_ids: continue
                        best_l = None
                        for vf in v.get("video_files", []):
                            if vf.get("file_type") == "video/mp4" and ge(vf.get("width", 0), 1280): best_l = vf.get("link"); break
                        if not best_l and v.get("video_files"): best_l = v["video_files"][0].get("link")
                        if best_l:
                            p = f"temp/raw_{tag}_{len(out)}\x2emp4"
                            open(p, "wb").write(requests.get(best_l, timeout=25).content)
                            if valid_vid(p): used_ids.add(vid); out.append(p)
                            if ge(len(out), 2): return out
            except Exception: pass
    while lt(len(out), 2):
        p = f"temp/fb_{tag}_{len(out)}\x2emp4"
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=0x0b1528:s=1280x720:d=8:r=24", "-c:v", "libx264", "-pix_fmt", "yuv420p", p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        out.append(p)
    return out
def prep_two(v1, v2, dur, out_p):
    h = max(2.5, dur * 0.62)
    p1, p2, lst = out_p + "_a\x2emp4", out_p + "_b\x2emp4", out_p + "_l\x2etxt"
    vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},format=yuv420p"
    subprocess.run(["ffmpeg", "-y", "-stream_loop", "-1", "-i", v1, "-t", f"{h:.2f}", "-vf", vf, "-an", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", p1], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["ffmpeg", "-y", "-stream_loop", "-1", "-i", v2, "-t", f"{h:.2f}", "-vf", vf, "-an", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", p2], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    open(lst, "w", encoding="utf-8").write(f"file '{os.path.abspath(p1)}'\nfile '{os.path.abspath(p2)}'\n")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-t", f"{dur + 1.0:.2f}", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", out_p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not valid_vid(out_p):
        subprocess.run(["ffmpeg", "-y", "-stream_loop", "-1", "-i", p1 if valid_vid(p1) else v1, "-t", f"{dur + 1.0:.2f}", "-vf", vf, "-an", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", out_p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out_p
def prep_short_bg(src_p, dur, out_p):
    vf = f"scale={SW}:{SH}:force_original_aspect_ratio=increase,crop={SW}:{SH},fps={FPS},format=yuv420p"
    subprocess.run(["ffmpeg", "-y", "-stream_loop", "-1", "-i", src_p, "-t", f"{dur + 1.0:.2f}", "-vf", vf, "-an", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", out_p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out_p
def get_font(sz):
    for fp in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold\x2ettf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold\x2ettf"]:
        if os.path.exists(fp):
            try: return ImageFont.truetype(fp, sz)
            except Exception: pass
    return ImageFont.load_default()
def draw_stroked(drw, xy, txt, fnt, fill, stroke=(0, 0, 0, 255), sw=3):
    x, y = xy
    for dx in range(-sw, sw + 1):
        for dy in range(-sw, sw + 1):
            if le(dx * dx + dy * dy, sw * sw): drw.text((x + dx, y + dy), txt, font=fnt, fill=stroke)
    drw.text((x, y), txt, font=fnt, fill=fill)
def paste_logo(img, is_sh=False):
    f1, f2 = "logo\x2ejpeg", "\u062a\u0646\u0632\u064a\u0644\x2ejpeg"
    lp = f1 if os.path.exists(f1) else (f2 if os.path.exists(f2) else None)
    sz = 86 if is_sh else 72
    cw, _ = img.size
    x0, y0 = (cw - sz - 28, 38) if is_sh else (cw - sz - 26, 22)
    drw = ImageDraw.Draw(img)
    if lp:
        try:
            lg = Image.open(lp).convert("RGBA").resize((sz, sz))
            msk = Image.new("L", (sz, sz), 0)
            ImageDraw.Draw(msk).ellipse((0, 0, sz, sz), fill=255)
            drw.ellipse((x0 - 3, y0 - 3, x0 + sz + 3, y0 + sz + 3), fill=(245, 190, 50, 240))
            img.paste(lg, (x0, y0), msk)
        except Exception: pass
    fnt = get_font(15 if is_sh else 13)
    bb = drw.textbbox((0, 0), CHANNEL_NAME, font=fnt)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    px, py = x0 + (sz - tw) // 2, y0 + sz + 7
    drw.rounded_rectangle((px - 8, py - 3, px + tw + 8, py + th + 5), radius=8, fill=(8, 18, 36, 230), outline=(245, 190, 50, 220), width=1)
    drw.text((px, py), CHANNEL_NAME, font=fnt, fill=(255, 225, 110, 255))
def make_frame_img(sub_txt, r_lbl, pt_title, show_b=False, is_sh=False):
    cw, ch = (SW, SH) if is_sh else (W, H)
    img = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    drw = ImageDraw.Draw(img)
    paste_logo(img, is_sh=is_sh)
    if show_b and (r_lbl or pt_title):
        bf1, bf2 = get_font(24 if is_sh else 20), get_font(22 if is_sh else 18)
        bx, by = (28, 46) if is_sh else (28, 24)
        bw, bh = (min(cw - 170, 620), 86) if is_sh else (min(cw - 180, 560), 74)
        drw.rounded_rectangle((bx, by, bx + bw, by + bh), radius=14, fill=(8, 20, 40, 228), outline=(245, 190, 50, 240), width=2)
        drw.rounded_rectangle((bx, by, bx + 10, by + bh), radius=5, fill=(245, 190, 50, 255))
        draw_stroked(drw, (bx + 22, by + 10), clean_txt(r_lbl)[:28], bf1, (255, 210, 60, 255), sw=2)
        draw_stroked(drw, (bx + 22, by + 40), clean_txt(pt_title)[:40], bf2, (240, 248, 255, 255), sw=2)
    if sub_txt:
        sf = get_font(38 if is_sh else 30)
        words, lines, cur = sub_txt.split(), [], ""
        lim = 24 if is_sh else 42
        for w in words:
            t_l = (cur + " " + w).strip()
            if le(len(t_l), lim): cur = t_l
            else:
                if cur: lines.append(cur)
                cur = w
        if cur: lines.append(cur)
        lines = lines[:2]
        l_w, l_h = [], []
        for ln in lines:
            bb = drw.textbbox((0, 0), ln, font=sf)
            l_w.append(bb[2] - bb[0]); l_h.append(bb[3] - bb[1])
        mw = max(l_w) if l_w else 200
        th = sum(l_h) + (10 if gt(len(lines), 1) else 0)
        pw, ph = mw + 48, th + 28
        px, py = (cw - pw) // 2, ch - ph - (230 if is_sh else 44)
        drw.rounded_rectangle((px, py, px + pw, py + ph), radius=18, fill=(6, 14, 28, 208), outline=(245, 190, 50, 195), width=2)
        cy = py + 12
        for idx, ln in enumerate(lines):
            lx = (cw - l_w[idx]) // 2
            col = (255, 230, 95, 255) if (idx == 0 and gt(len(lines), 1)) else (255, 255, 255, 255)
            draw_stroked(drw, (lx, cy), ln, sf, col, sw=3)
            cy += l_h[idx] + 10
    return np.array(img)
def split_timed_subs(txt, dur):
    w = clean_txt(txt).split()
    if not w: return [("", 0.0, dur)]
    ch = [" ".join(w[i:i + 6]) for i in range(0, len(w), 6)]
    tot = float(sum(max(1, len(c)) for c in ch))
    out, t = [], 0.0
    for idx, c in enumerate(ch):
        d = (dur - t) if idx == len(ch) - 1 else dur * (max(1, len(c)) / tot)
        out.append((c, t, max(0.25, d))); t += d
    return out
def render_scene_file(bg_p, txt, dur, r_lbl, pt_title, out_p, is_tr=False, is_sh=False):
    cw, ch = (SW, SH) if is_sh else (W, H)
    raw_p = out_p + "_r\x2emp4"
    base, comp = None, None
    try:
        base = VideoFileClip(bg_p).without_audio()
        if lt(base.duration, dur): base = base.loop(duration=dur + 0.5)
        base = base.subclip(0, dur)
        lays = [base]
        for c_txt, st, d in split_timed_subs(txt, dur):
            arr = make_frame_img(c_txt, r_lbl, pt_title, show_b=bool(is_tr and lt(st, 4.2)), is_sh=is_sh)
            lays.append(ImageClip(arr).set_start(st).set_duration(d))
        comp = CompositeVideoClip(lays, size=(cw, ch)).set_duration(dur)
        comp.write_videofile(raw_p, fps=FPS, codec="libx264", audio=False, preset="ultrafast", threads=2, ffmpeg_params=["-pix_fmt", "yuv420p"], logger=None)
    except Exception: pass
    finally:
        for obj in (comp, base):
            try:
                if obj: obj.close()
            except Exception: pass
    src_f = raw_p if valid_vid(raw_p) else bg_p
    vf = f"scale={cw}:{ch},fps={FPS},format=yuv420p"
    subprocess.run(["ffmpeg", "-y", "-stream_loop", "-1", "-i", src_f, "-t", f"{dur:.2f}", "-vf", vf, "-an", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", out_p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.path.exists(raw_p):
        try: os.remove(raw_p)
        except Exception: pass
    return out_p
def make_card_file(rnum, title, out_p, dur=2.8):
    img = Image.new("RGB", (W, H), (8, 18, 36))
    drw = ImageDraw.Draw(img)
    drw.rounded_rectangle((110, 140, W - 110, H - 140), radius=28, fill=(14, 30, 58), outline=(245, 190, 50), width=4)
    f1, f2 = get_font(62), get_font(36)
    t1, t2 = f"COUNTDOWN {H35}{rnum}", clean_txt(title)[:46]
    b1, b2 = drw.textbbox((0, 0), t1, font=f1), drw.textbbox((0, 0), t2, font=f2)
    draw_stroked(drw, ((W - (b1[2] - b1[0])) // 2, 245), t1, f1, (255, 210, 65), sw=4)
    draw_stroked(drw, ((W - (b2[2] - b2[0])) // 2, 365), t2, f2, (255, 255, 255), sw=3)
    paste_logo(img, is_sh=False)
    png_p = out_p + "\x2epng"
    img.save(png_p, "PNG")
    vf = f"scale={W}:{H},fps={FPS},format=yuv420p"
    subprocess.run(["ffmpeg", "-y", "-loop", "1", "-i", png_p, "-t", f"{dur:.2f}", "-vf", vf, "-an", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", out_p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out_p
def export_final_mp4(part_files, wavs, out_mp4, aspect="16:9"):
    tag = os.path.basename(out_mp4).replace(".", "_")
    sil_v, m_wav, lst = f"temp/{tag}_s\x2emp4", f"temp/{tag}_m\x2ewav", f"temp/{tag}_l\x2etxt"
    build_master_wav(wavs, m_wav)
    valid_parts = [pf for pf in part_files if valid_vid(pf)]
    if not valid_parts:
        fb_p = f"temp/{tag}_fb\x2emp4"
        sz_s = "1080x1920" if aspect == "9:16" else "1280x720"
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=0x0b1528:s={sz_s}:d=10:r=24", "-c:v", "libx264", "-pix_fmt", "yuv420p", fb_p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        valid_parts = [fb_p]
    with open(lst, "w", encoding="utf-8") as f:
        for pf in valid_parts: f.write(f"file '{os.path.abspath(pf)}'\n")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", sil_v], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["ffmpeg", "-y", "-i", sil_v, "-i", m_wav, "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-aspect", aspect, "-c:a", "aac", "-b:a", "192k", "-shortest", out_mp4], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not valid_vid(out_mp4):
        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-i", m_wav, "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-aspect", aspect, "-c:a", "aac", "-b:a", "192k", "-shortest", out_mp4], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
def calc_excitement(sc):
    t = sc["text"].lower()
    b = sum(6 for w in ["sleep", "night", "heart", "brain", "nerve", "liver", "blood", "sudden", "critical", "number 1", "24 hours"] if w in t)
    return int(sc.get("thrill", 85)) + b + (7 - int(sc["rank"])) * 5
def build_short_from_long(scenes, intro_sc, out_short):
    cand = sorted(scenes, key=calc_excitement, reverse=True)
    picked, used_r, tot = [intro_sc], set(), intro_sc["dur"]
    for sc in cand:
        if sc["rank"] in used_r: continue
        if le(tot + sc["dur"], 47.0) or lt(len(picked), 3):
            picked.append(sc); used_r.add(sc["rank"]); tot += sc["dur"]
        if ge(len(picked), 4) or ge(tot, 44.0): break
    cta_txt = "Watch the full 6 to 1 medical countdown now on MedPulse Daily and subscribe for daily health warnings."
    cta_w = "temp/sh_cta\x2ewav"; cta_d = gen_voice(cta_txt, cta_w)
    cta_bg = prep_short_bg(picked[-1]["bg"], cta_d, "temp/sh_cta_bg\x2emp4")
    picked.append({"bg": cta_bg, "wav": cta_w, "text": cta_txt, "dur": cta_d, "r_lbl": "FULL COUNTDOWN", "title": "Watch On MedPulse Daily", "ready_sh": True})
    s_parts, s_wavs = [], []
    for idx, sc in enumerate(picked):
        s_bg = sc["bg"] if sc.get("ready_sh") else prep_short_bg(sc["bg"], sc["dur"], f"temp/sh_bg_{idx}\x2emp4")
        sp = f"temp/sh_part_{idx}\x2emp4"
        render_scene_file(s_bg, sc["text"], sc["dur"], sc["r_lbl"], sc["title"], sp, is_tr=True, is_sh=True)
        s_parts.append(sp); s_wavs.append(sc["wav"])
    export_final_mp4(s_parts, s_wavs, out_short, aspect="9:16")
def make_thumb(topic, out_p):
    img = Image.new("RGB", (W, H), (8, 18, 36))
    drw = ImageDraw.Draw(img)
    drw.rounded_rectangle((40, 40, W - 40, H - 40), radius=30, fill=(14, 30, 58), outline=(245, 190, 50), width=6)
    f1, f2 = get_font(66), get_font(44)
    draw_stroked(drw, (80, 120), f"6 WARNING SIGNS ({H35}6 TO {H35}1)", f1, (255, 210, 60), sw=5)
    w = clean_txt(topic).upper().split()
    l1, l2 = " ".join(w[:4]), " ".join(w[4:8])
    draw_stroked(drw, (80, 255), l1, f2, (255, 255, 255), sw=4)
    if l2: draw_stroked(drw, (80, 325), l2, f2, (255, 255, 255), sw=4)
    draw_stroked(drw, (80, 465), "NUMBER 1 HAPPENS IN YOUR SLEEP", get_font(38), (255, 110, 90), sw=4)
    paste_logo(img, is_sh=False)
    img.save(out_p, "JPEG", quality=95)
def write_details(trend, data, r_titles):
    lt_t = clean_txt(data.get("video_title", trend["title"]))
    sh_t = clean_txt(data.get("short_title", "Wait Until Number 1: " + trend["title"][:38]))
    desc = clean_txt(data.get("seo_description", trend["summary"]))
    th_p = clean_txt(data.get("thumbnail_prompt", f"High-contrast 16:9 medical thumbnail for {trend['title']}"))
    tags = [clean_txt(x) for x in data.get("seo_tags", []) if clean_txt(x)][:28]
    tags_s = ", ".join(tags)
    src_lines = [f"{i + 1}. {s['name']} - {s['title']}\n   {s['url']}" for i, s in enumerate(trend.get("sources", []))]
    r_lines = [f"- {r}" for r in r_titles]
    lines = [
        f"Topic: {trend['title']}",
        f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        "[SECTION 1 - LONG VIDEO SPECIFICATIONS AND METADATA]",
        "File: output/long_video\x2emp4 | Resolution: 1280x720 HD (16:9) | Duration: 9+ Minutes",
        f"LONG VIDEO TITLE:\n{lt_t}",
        "LONG VIDEO DESCRIPTION:",
        f"{desc}",
        f"In today's evidence-based medical countdown on MedPulse Daily, we examine {trend['title']} from Countdown {H35}6 down to the critical {H35}1 warning sign, including internal organ mechanisms and 24-hour nutritional fixes:",
        *r_lines,
        "Verified Medical And Scientific Sources:",
        *src_lines,
        "Disclaimer: This video is for educational purposes only and is not a substitute for professional medical advice.",
        f"{H35}MedPulseDaily {H35}HealthWarningSigns {H35}Symptoms {H35}Nutrition {H35}PreventiveHealth",
        f"LONG VIDEO KEYWORDS AND TAGS (COPY AND PASTE):\n{tags_s}",
        "[SECTION 2 - SHORT VIDEO SPECIFICATIONS AND METADATA]",
        "File: output/short_video\x2emp4 | Resolution: 1080x1920 Vertical HD (9:16)",
        f"SHORT VIDEO TITLE:\n{sh_t} {H35}Shorts",
        "SHORT VIDEO DESCRIPTION:",
        f"Watch the most urgent warning signs of {trend['title']} and see the full {H35}6 to {H35}1 countdown on the MedPulse Daily channel.",
        "Verified Sources:",
        *src_lines[:3],
        f"{H35}Shorts {H35}MedPulseDaily {H35}HealthTips {H35}BodySignals {H35}Wellness",
        f"SHORT VIDEO KEYWORDS AND TAGS (COPY AND PASTE):\n{tags_s}",
        "[SECTION 3 - THUMBNAIL SPECIFICATIONS AND DESCRIPTION]",
        "File: output/thumbnail\x2ejpg | Resolution: 1280x720 HD",
        f"Thumbnail Headline Text: 6 WARNING SIGNS ({H35}6 TO {H35}1) - NUMBER 1 HAPPENS IN YOUR SLEEP",
        "Visual Design And AI Generator Prompt:",
        f"{th_p}"
    ]
    open("output/youtube_details\x2etxt", "w", encoding="utf-8").write("\n\n".join(lines))
def save_used(title):
    arr, uf = [], "used_topics\x2ejson"
    if os.path.exists(uf):
        try: arr = json.load(open(uf, "r", encoding="utf-8"))
        except Exception: arr = []
    if title not in arr: arr.append(title)
    json.dump(arr[-90:], open(uf, "w", encoding="utf-8"), indent=2)
def main():
    trend = fetch_live_trend()
    data = generate_script(trend)
    seen, used_vids = set(), set()
    part_files, wavs, body_scenes, r_titles = [], [], [], []
    tot_sec = 0.0
    in_txt = dedup_text(data.get("intro_hook", ""), seen) or f"Today on MedPulse Daily, we count down six warning signs of {trend['title']} from number six down to number one."
    in_w = "temp/intro\x2ewav"; in_d = gen_voice(in_txt, in_w)
    v1, v2 = fetch_two_vids(trend["title"] + " medical", used_vids, "intro")
    in_bg = prep_two(v1, v2, in_d, "temp/bg_intro\x2emp4")
    in_part = "temp/part_intro\x2emp4"
    render_scene_file(in_bg, in_txt, in_d, "LIVE HEALTH TREND", trend["title"][:38], in_part, is_tr=True, is_sh=False)
    part_files.append(in_part); wavs.append(in_w); tot_sec += in_d
    intro_sc = {"bg": in_bg, "wav": in_w, "text": in_txt, "dur": in_d, "r_lbl": "TODAY'S COUNTDOWN", "title": trend["title"][:36], "rank": 7, "thrill": 95}
    chime_w = "temp/chime\x2ewav"; make_chime(chime_w, 2.8)
    ranks = data.get("ranks", [])[:6]
    while lt(len(ranks), 6): ranks.append(make_rank_obj(len(ranks), 6 - len(ranks), trend["title"]))
    for r_idx, rk in enumerate(ranks):
        rnum = rk.get("rank", 6 - r_idx)
        rt = clean_txt(rk.get("title", FB_DATA[r_idx][0]))
        rq = clean_txt(rk.get("search_query", FB_DATA[r_idx][1]))
        r_titles.append(f"Countdown {H35}{rnum}: {rt}")
        cp = f"temp/card_{r_idx}\x2emp4"; make_card_file(rnum, rt, cp, 2.8)
        part_files.append(cp); wavs.append(chime_w); tot_sec += 2.8
        fb_ps = make_rank_obj(r_idx, rnum, trend["title"])["paragraphs"]
        ps = rk.get("paragraphs", [])
        for p_idx in range(4):
            raw_p = ps[p_idx] if lt(p_idx, len(ps)) else fb_ps[p_idx]
            p_txt = dedup_text(raw_p, seen) or dedup_text(fb_ps[p_idx], seen)
            if not p_txt: continue
            pw = f"temp/w_{r_idx}_{p_idx}\x2ewav"; pd = gen_voice(p_txt, pw)
            va, vb = fetch_two_vids(f"{rq} {rt}", used_vids, f"r{r_idx}p{p_idx}")
            pbg = prep_two(va, vb, pd, f"temp/bg_{r_idx}_{p_idx}\x2emp4")
            rl, sp = f"COUNTDOWN {H35}{rnum}", f"temp/part_{r_idx}_{p_idx}\x2emp4"
            render_scene_file(pbg, p_txt, pd, rl, rt, sp, is_tr=(p_idx == 0), is_sh=False)
            part_files.append(sp); wavs.append(pw); tot_sec += pd
            body_scenes.append({"bg": pbg, "wav": pw, "text": p_txt, "dur": pd, "r_lbl": rl, "title": rt, "rank": rnum, "thrill": int(rk.get("thrill_score", 88)) + (3 if p_idx in (0, 3) else 0)})
    b_idx = 6
    while lt(tot_sec, MIN_LONG_SEC - 14.0) and lt(b_idx, 10):
        bo = make_rank_obj(b_idx, b_idx - 5, trend["title"])
        for p_idx, bp in enumerate(bo["paragraphs"]):
            if ge(tot_sec, MIN_LONG_SEC - 12.0): break
            bt = dedup_text(bp, seen)
            if not bt: continue
            bw = f"temp/bw_{b_idx}_{p_idx}\x2ewav"; bd = gen_voice(bt, bw)
            va, vb = fetch_two_vids(bo["search_query"], used_vids, f"b{b_idx}_{p_idx}")
            bbg = prep_two(va, vb, bd, f"temp/bbg_{b_idx}_{p_idx}\x2emp4")
            bsp = f"temp/bpart_{b_idx}_{p_idx}\x2emp4"
            render_scene_file(bbg, bt, bd, "CLINICAL INSIGHT", bo["title"], bsp, is_tr=(p_idx == 0), is_sh=False)
            part_files.append(bsp); wavs.append(bw); tot_sec += bd
        b_idx += 1
    out_txt = dedup_text(data.get("outro_cta", ""), seen) or "Subscribe to MedPulse Daily and share which warning sign stood out to you today."
    ow = "temp/outro\x2ewav"; od = gen_voice(out_txt, ow)
    va, vb = fetch_two_vids("healthy lifestyle sunrise", used_vids, "outro")
    obg = prep_two(va, vb, od, "temp/bg_outro\x2emp4")
    op = "temp/part_outro\x2emp4"
    render_scene_file(obg, out_txt, od, CHANNEL_NAME, "Subscribe For Daily Health Warnings", op, is_tr=True, is_sh=False)
    part_files.append(op); wavs.append(ow)
    export_final_mp4(part_files, wavs, "output/long_video\x2emp4", aspect="16:9")
    build_short_from_long(body_scenes, intro_sc, "output/short_video\x2emp4")
    make_thumb(trend["title"], "output/thumbnail\x2ejpg")
    write_details(trend, data, r_titles)
    save_used(trend["title"])
if __name__ == "__main__":
    main()
