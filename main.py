import os, re, json, time, math, wave, random, asyncio, hashlib, warnings, subprocess
warnings.filterwarnings("ignore")
from urllib.parse import quote_plus
import requests, feedparser, edge_tts
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import google.generativeai as genai
from moviepy.editor import VideoFileClip, ImageClip, CompositeVideoClip, concatenate_videoclips

if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.Resampling.LANCZOS

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
PEXELS_KEY = os.environ.get("PEXELS_API_KEY", "").strip()
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)

W, H = 1280, 720
SW, SH = 1080, 1920
FPS = 24
SR = 44100
VOICE_NAME = "en-US-ChristopherNeural"
VOICE_RATE = "-4%"
SHORT_RATE = "+4%"
VOICE_PITCH = "-2Hz"
MIN_LONG_SEC = 560.0
LOGO_PATH = "\u062a\u0646\u0632\u064a\u0644.jpeg"
USED_NEWS_FILE = "used_news.txt"
USED_VIDEOS_FILE = "used_videos.txt"

os.makedirs("output", exist_ok=True)
os.makedirs("temp", exist_ok=True)

LIVE_FEEDS = [
    ("Google Daily Search Trends US", "https://trends.google.com/trending/rss?geo=US"),
    ("Google Daily Search Trends UK", "https://trends.google.com/trending/rss?geo=GB"),
    ("Google Daily Search Trends CA", "https://trends.google.com/trending/rss?geo=CA"),
    ("Google News Health Symptoms (24h)", "https://news.google.com/rss/search?q=health+symptom+OR+deficiency+OR+warning+sign+when:1d&hl=en-US&gl=US&ceid=US:en"),
    ("Google News Nutrition & Vitamins (24h)", "https://news.google.com/rss/search?q=vitamin+OR+magnesium+OR+nutrition+OR+supplement+health+when:1d&hl=en-US&gl=US&ceid=US:en"),
    ("Google News Organs & Digestion (24h)", "https://news.google.com/rss/search?q=liver+OR+kidney+OR+gut+health+OR+digestion+OR+bloating+when:1d&hl=en-US&gl=US&ceid=US:en"),
    ("Google News Metabolism & Blood Sugar (24h)", "https://news.google.com/rss/search?q=insulin+OR+blood+sugar+OR+metabolism+OR+inflammation+when:1d&hl=en-US&gl=US&ceid=US:en"),
    ("Google News Heart & Sleep Health (24h)", "https://news.google.com/rss/search?q=sleep+OR+heart+health+OR+blood+pressure+OR+cholesterol+when:1d&hl=en-US&gl=US&ceid=US:en"),
    ("Harvard Health Publishing", "https://www.health.harvard.edu/blog/feed"),
    ("Cleveland Clinic Health Essentials", "https://health.clevelandclinic.org/feed/"),
    ("Mayo Clinic Medical News", "https://newsnetwork.mayoclinic.org/feed/"),
    ("NIH MedlinePlus Health", "https://medlineplus.gov/feeds/news_en.xml"),
    ("Medical News Today", "https://rss.medicalnewstoday.com/featurednews.xml"),
    ("Healthline Wellness News", "https://www.healthline.com/rss/health-news"),
    ("ScienceDaily Health & Medicine", "https://www.sciencedaily.com/rss/health_medicine.xml"),
    ("Drugs.com Clinical News", "https://www.drugs.com/feeds/medical_news.xml"),
    ("BBC Health News", "https://feeds.bbci.co.uk/news/health/rss.xml"),
    ("NYT Health & Wellness", "https://rss.nytimes.com/services/xml/rss/nyt/Health.xml"),
]

SEEDS = [
    "why does my body ", "signs of low vitamin ", "what happens if you eat ",
    "early warning signs of ", "best natural food for ", "how to unclog and support "
]

TERMS = [
    "vitamin", "magnesium", "potassium", "zinc", "iron", "b12", "vitamin d", "liver", "kidney",
    "insulin", "blood sugar", "cortisol", "thyroid", "gut", "bloating", "inflammation", "sleep",
    "fatigue", "cramps", "numbness", "tingling", "cholesterol", "blood pressure", "heart", "brain",
    "electrolyte", "bile", "autophagy", "fasting", "omega", "collagen", "uric acid", "joint",
    "symptom", "deficiency", "warning", "diet", "protein", "sugar", "arteries", "digestion"
]

BANNED = ["berg", "eric berg", "dr berg", "dr. berg", "huberman", "oz", "mercola", "fauci", "gupta"]

def load_set(p):
    if not os.path.exists(p): return set()
    with open(p, "r", encoding="utf-8") as f:
        return set(x.strip() for x in f if x.strip())

def save_item(p, v):
    with open(p, "a", encoding="utf-8") as f:
        f.write(f"{v.strip()}\n")

def fnt(sz, bold=True):
    ps = [
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    ]
    for p in ps:
        if os.path.exists(p):
            try: return ImageFont.truetype(p, sz)
            except Exception: pass
    return ImageFont.load_default()

def clean_txt(t):
    if not t: return ""
    t = re.sub(r"https?://\S+", "", str(t))
    for b in BANNED:
        t = re.sub(rf"\b{re.escape(b)}\b", "", t, flags=re.I)
    t = re.sub(r"\bDr\.?\s+[A-Z][a-z]+\b", "medical researchers", t)
    t = re.sub(r"\bProfessor\s+[A-Z][a-z]+\b", "health specialists", t)
    t = re.sub(r"[\*\#\_\~\`\>\|]", " ", t)
    return re.sub(r"\s+", " ", t).strip()

def fetch_live_trend():
    used = load_set(USED_NEWS_FILE)
    items, auto = [], []
    hdr = {"User-Agent": "Mozilla/5.0"}
    for s in SEEDS:
        try:
            u = f"https://suggestqueries.google.com/complete/search?client=firefox&hl=en&gl=us&q={quote_plus(s)}"
            r = requests.get(u, headers=hdr, timeout=8)
            if r.status_code == 200:
                for q in r.json()[1][:5]:
                    qc = clean_txt(q)
                    if len(qc) > 12: auto.append(qc)
        except Exception: pass
    for sname, url in LIVE_FEEDS:
        try:
            r = requests.get(url, headers=hdr, timeout=12)
            if r.status_code != 200: continue
            d = feedparser.parse(r.content)
            for e in d.entries[:12]:
                t = clean_txt(getattr(e, "title", ""))
                t = re.sub(r"\s+-\s+[^-]+$", "", t).strip()
                s = clean_txt(re.sub(r"<[^>]+>", " ", getattr(e, "summary", "")))[:350]
                lk = getattr(e, "link", "").strip()
                if not t or len(t) < 15: continue
                h = hashlib.md5(t.lower().encode("utf-8")).hexdigest()[:12]
                if h in used: continue
                low = f"{t} {s}".lower()
                hits = [k for k in TERMS if k in low]
                if not hits and "Google Daily" in sname: continue
                sc = len(hits) * 4 + (5 if "24h" in sname or "Trends" in sname else 2)
                for aq in auto:
                    if any(w in low for w in aq.lower().split() if len(w) > 4): sc += 3
                items.append({"id": h, "title": t, "summary": s or t, "source": sname, "url": lk, "score": sc, "kw": hits})
        except Exception: pass
    if not items:
        return {
            "id": hashlib.md5(str(time.time()).encode()).hexdigest()[:12],
            "title": "Hidden Signs of Magnesium and Vitamin D Deficiency on Sleep, Nerves, and Energy",
            "summary": "Clinical nutrition observations on how cellular electrolytes regulate nerve calm, muscle recovery, and deep sleep.",
            "auto": auto[:5],
            "sources": [
                {"name": "NIH MedlinePlus Health", "title": "Electrolytes and Cellular Nerve Signaling", "url": "https://medlineplus.gov/fluidandelectrolytebalance.html"},
                {"name": "Harvard Health Publishing", "title": "Vitamins, Minerals, and Cellular Metabolism", "url": "https://www.health.harvard.edu/nutrition"},
                {"name": "Cleveland Clinic Health Essentials", "title": "Signs of Micronutrient Imbalance", "url": "https://health.clevelandclinic.org/"}
            ]
        }
    wf = {}
    for it in items:
        for w in re.findall(r"[a-zA-Z]{5,}", it["title"].lower()):
            if w not in ("health", "study", "shows", "could", "about", "their", "after", "first"):
                wf[w] = wf.get(w, 0) + 1
    for it in items:
        for w in set(re.findall(r"[a-zA-Z]{5,}", it["title"].lower())):
            it["score"] += wf.get(w, 0) * 2
    items.sort(key=lambda x: x["score"], reverse=True)
    best = items[0]
    srcs, seen = [{"name": best["source"], "title": best["title"], "url": best["url"]}], {best["source"]}
    bw = set(re.findall(r"[a-zA-Z]{5,}", best["title"].lower()))
    for it in items[1:]:
        if it["source"] in seen: continue
        iw = set(re.findall(r"[a-zA-Z]{5,}", it["title"].lower()))
        if (bw & iw) or (set(best["kw"]) & set(it["kw"])):
            srcs.append({"name": it["source"], "title": it["title"], "url": it["url"]})
            seen.add(it["source"])
        if len(srcs) >= 5: break
    for it in items[1:]:
        if len(srcs) >= 4: break
        if it["source"] not in seen:
            srcs.append({"name": it["source"], "title": it["title"], "url": it["url"]})
            seen.add(it["source"])
    best["sources"] = srcs
    best["auto"] = auto[:6]
    return best

def fallback_script(tr):
    t = clean_txt(tr["title"])
    pts = [
        {
            "title": "Point 1: The Subtle Daily Clues People Brush Off",
            "subtitle": "How your body whispers before it ever shouts",
            "badge": "EARLY BODY CLUES",
            "paragraphs": [
                {"text": f"Today people all over the world are searching for answers about {t}. Most of the time, your body does not suddenly break down overnight. Instead, it sends small, polite signals during your normal routine, much like a tiny warning light flickering on a car dashboard long before the engine overheats.", "queries": ["tired person rubbing eyes morning", "woman holding stomach kitchen"]},
                {"text": "For example, think about waking up after eight full hours in bed yet feeling as if your battery is still at twenty percent. Or notice what happens at three in the afternoon when your brain feels foggy, your eyelids feel heavy after lunch, and you suddenly crave something salty or sweet just to keep going.", "queries": ["exhausted office worker afternoon", "person looking at sugary snack"]},
                {"text": "Many people blame age, busy schedules, or stress for these tiny annoyances. They drink another cup of coffee, ignore the mild bloating or occasional eyelid twitch, and push through the afternoon without realizing those exact moments are direct messages from their cells.", "queries": ["pouring black coffee cup morning", "stressed man massaging temples"]},
                {"text": "When we connect these everyday dots together, a clear picture emerges. Your body is not malfunctioning randomly; it is prioritizing survival and asking for specific raw materials that have quietly run low over months of modern eating and stress.", "queries": ["doctor showing medical chart", "healthy cells animation microscopic"]}
            ]
        },
        {
            "title": "Point 2: The Simple Kitchen Analogy Inside Your Cells",
            "subtitle": "Understanding the root cause without confusing jargon",
            "badge": "ROOT MECHANISM",
            "paragraphs": [
                {"text": "To understand what is actually happening inside your body, skip the complicated textbook terms and picture a busy restaurant kitchen. Even if you deliver boxes of fresh food to the back door, nothing gets cooked if the spark plugs on the stove are wet or the sink drain is clogged.", "queries": ["busy home kitchen cooking", "fresh vegetables on wooden table"]},
                {"text": "Inside your body, your cells work the exact same way. Nutrients like magnesium, potassium, B vitamins, and healthy fats act like tiny spark plugs for your cellular engines, while bile from your liver works just like warm dish soap that dissolves stubborn grease on a dinner plate.", "queries": ["olive oil pouring into spoon", "green leafy vegetables closeup"]},
                {"text": "When your digestive system lacks that natural soap or your cells lack those mineral spark plugs, food sits heavy in your stomach, fat-soluble vitamins wash right past your gut wall, and your energy factories slow down to a crawl.", "queries": ["person feeling bloated after meal", "anatomy digestion illustration"]},
                {"text": "Even more fascinating, when blood sugar spikes and crashes from refined snacks, insulin acts like a rusted lock on your cell doors. Fuel stays trapped in your bloodstream making you feel tired and hungry at the exact same time.", "queries": ["blood sugar test meter", "tired woman sitting on sofa"]}
            ]
        },
        {
            "title": "Point 3: Why Common Habits Accidentally Drain Your Reserves",
            "subtitle": "Everyday foods and routines that quietly block recovery",
            "badge": "HIDDEN DRAINERS",
            "paragraphs": [
                {"text": "You might wonder how someone who eats three meals a day could ever run low on essential nutrients. The secret lies in invisible drainers built right into modern life that flush minerals out faster than your fork can replace them.", "queries": ["supermarket aisle processed food", "person eating fast food lunch"]},
                {"text": "Take refined flour, sugary drinks, and ultra-processed seed oils as a first example. Every single time your body processes a high-sugar snack, it has to spend its own stored magnesium and B vitamins just to metabolize that sugar, leaving your nerves and muscles shortchanged.", "queries": ["soda pouring into glass ice", "white bread pastries bakery"]},
                {"text": "Second, think about chronic mental stress and late-night screen time. When your stress hormone cortisol stays high all evening, it acts like a leaky faucet in your kidneys, causing you to excrete precious electrolytes that were supposed to keep your heartbeat steady and your muscles relaxed at night.", "queries": ["person scrolling phone in dark bed", "insomnia awake at night clock"]},
                {"text": "Third, sipping large amounts of liquid right on top of heavy meals or relying on constant antacids can dilute your natural stomach acid. Without strong stomach acid, you cannot unlock iron, zinc, or vitamin B12 from your food, even if you eat a pricey meal.", "queries": ["drinking water during meal", "stomach pain indigestion closeup"]}
            ]
        },
        {
            "title": "Point 4: Real-Life Examples of What Happens When You Fix It",
            "subtitle": "How your nerves, gut, and energy respond to the right fuel",
            "badge": "REAL EXAMPLES",
            "paragraphs": [
                {"text": "Look at what changes when you stop masking the symptom and start refilling the exact tank that ran dry. Imagine a car that has been sputtering on cheap fuel suddenly getting a clean oil filter and premium gas.", "queries": ["happy energetic person walking park", "sunrise morning stretching window"]},
                {"text": "For instance, when someone replaces their afternoon sugary pastry with mineral-rich pumpkin seeds, avocado, and clean protein, that dramatic three-o-clock brain fog begins to lift within days because blood sugar stays level instead of riding a roller coaster.", "queries": ["avocado and seeds healthy bowl", "focused person working smiling"]},
                {"text": "Or consider night-time calf cramps and restless tossing in bed. When your cells finally receive bioavailable magnesium alongside potassium from leafy greens, muscle fibers that were stuck in a tight contraction can finally unhook and relax into deep sleep.", "queries": ["peaceful sleeping woman night", "fresh spinach and greens salad"]},
                {"text": "Similarly, adding bitter greens, lemon water before meals, or fermented vegetables supports natural stomach acid and bile flow. Suddenly, that heavy brick-like feeling after dinner fades away because your digestive tract has its natural dish soap back.", "queries": ["squeezing fresh lemon into water", "healthy salad bowl fork"]}
            ]
        },
        {
            "title": "Point 5: The Best Whole Foods and Timing That Work Together",
            "subtitle": "Practical grocery swaps you can use at your very next meal",
            "badge": "FOOD SYNERGY",
            "paragraphs": [
                {"text": "Nature never packages nutrients in isolation, and your body absorbs them best when they arrive as a team. Think of vitamins and minerals like construction workers who each need a partner to lift a heavy beam into place.", "queries": ["colorful fresh market vegetables", "cooking healthy meal skillet"]},
                {"text": "A classic example is pairing fat-soluble nutrients with natural healthy fats. If you eat steamed greens or eggs with extra-virgin olive oil, grass-fed butter, or avocado, your liver releases bile and pulls those protective nutrients straight into your circulation.", "queries": ["eggs cooking in pan", "drizzling olive oil over salad"]},
                {"text": "Another powerful habit is giving your digestive tract a twelve to fourteen hour overnight rest between dinner and breakfast. Just like a grocery store cleaning crew can only mop the floors after the shoppers go home, your gut repairs its lining best when you stop late-night snacking.", "queries": ["kitchen clock evening time", "herbal tea cup evening relax"]},
                {"text": "Focus your plate around clean proteins like wild fish or pasture-raised eggs, sulfur-rich vegetables like broccoli and garlic that help your liver detoxify, and mineral-rich foods like berries, nuts, and sea salt in your morning water.", "queries": ["salmon fillet with broccoli plate", "berries and nuts in bowl"]}
            ]
        },
        {
            "title": "Point 6: Your Simple Step-by-Step Daily Action Plan",
            "subtitle": "Three easy habits to test starting tonight and tomorrow morning",
            "badge": "DAILY ACTION PLAN",
            "paragraphs": [
                {"text": "You do not need an expensive cabinet full of complicated pills to start feeling a real difference. The smartest approach is to test three simple, zero-cost adjustments over the next seven days and pay attention to how your body responds.", "queries": ["person writing health journal notes", "walking outdoors sunny morning"]},
                {"text": "Step one starts tomorrow morning: before reaching for caffeine, drink a tall glass of water with a tiny pinch of natural mineral salt or fresh lemon juice, and build your first meal around protein and healthy fat rather than sweet cereal or toast.", "queries": ["glass of lemon water morning", "healthy protein breakfast plate"]},
                {"text": "Step two happens at lunch and dinner: slow down, chew your food thoroughly, include one cup of bitter or cruciferous greens, and take a gentle ten-minute walk after eating. That short walk acts like a sponge that pulls excess glucose straight into your muscles without needing extra insulin.", "queries": ["couple walking in park afternoon", "healthy dinner plate vegetables"]},
                {"text": "Step three begins two hours before bed: stop all snacks, dim bright overhead lights, and include magnesium-rich foods at dinner so your nervous system can shift smoothly into repair mode. Always talk with your qualified healthcare professional if you take prescription medications or have severe symptoms.", "queries": ["calm bedroom warm lamp night", "doctor talking with patient friendly"]}
            ]
        }
    ]
    return {
        "youtube_title": f"{t[:68]} - Simple Examples & Daily Fix",
        "thumbnail_hook": "WARNING SIGNS EXPLAINED",
        "thumbnail_prompt": "High-contrast 16:9 medical illustration of a glowing human body with a magnifying glass highlighting cellular energy and fresh whole foods, cinematic lighting, 8k, no text",
        "intro_hook": f"Have you ever noticed how a tiny rattle in your car is easy to ignore until you are suddenly stranded on the highway? Right now, one of the most searched health questions today is all about {t}. In the next few minutes, we are going to break this down in plain, everyday English using simple real-life examples, so you can spot the early clues, understand what is happening inside your cells, and use practical food steps starting today.",
        "points": pts,
        "outro": "When you understand the simple language of your body, small daily choices create massive results over time. If today's breakdown gave you a clear lightbulb moment, please hit the like button, share in the comments which sign or food example stood out to you most, and subscribe to MedPulse 5 so you never miss our daily health guides. Take care of your body, and see you in the next video.",
        "short": {
            "hook_banner": "DON'T IGNORE THIS CLUE",
            "scenes": [
                {"narration": f"Did you know one of today's top searched health clues is directly linked to {t[:55]}?", "caption": "TODAY'S #1 HEALTH CLUE", "query": "doctor looking at medical scan vertical"},
                {"narration": "Most people brush off afternoon brain fog, low morning energy, or tight muscles as normal stress.", "caption": "NOT JUST NORMAL STRESS", "query": "tired person rubbing eyes vertical"},
                {"narration": "Think of your cells like a kitchen stove: without mineral spark plugs, your energy cannot ignite.", "caption": "CELLULAR SPARK PLUGS", "query": "fresh green vegetables closeup vertical"},
                {"narration": "Every sugary snack and stressful late night quietly drains magnesium, potassium, and B vitamins.", "caption": "HIDDEN MINERAL DRAINERS", "query": "person scrolling phone night vertical"},
                {"narration": "When you refill those missing raw materials with whole foods, your nerves and digestion finally relax.", "caption": "REFILL YOUR CELLULAR TANK", "query": "avocado and healthy food vertical"},
                {"narration": "Start tomorrow with mineral water, protein at breakfast, and a ten-minute walk after meals.", "caption": "SIMPLE DAILY FIX", "query": "person walking outdoors morning vertical"},
                {"narration": "Watch our full step-by-step guide on MedPulse 5 and subscribe for daily simplified health answers.", "caption": "SUBSCRIBE TO MEDPULSE 5", "query": "happy healthy person smiling vertical"}
            ]
        }
    }

def generate_script(tr):
    fb = fallback_script(tr)
    if not GEMINI_KEY: return fb
    s_txt = "\n".join([f"- {s['name']}: {s['title']}" for s in tr.get("sources", [])])
    a_txt = ", ".join(tr.get("auto", []))
    prompt = f"""You are the lead medical educator for the YouTube channel 'MedPulse 5'.
Today's #1 live trending health topic is:
Headline: {tr['title']}
Context: {tr['summary']}
Related Live Searches Today: {a_txt}
Diverse Reference Outlets:
{s_txt}

STRICT RULES:
1. NEVER mention any doctor's name, celebrity name, or 'Dr. Berg' anywhere. Zero person names.
2. NEVER read URLs or website links in the spoken script.
3. Explain ONE unified topic in crystal-clear everyday English using vivid analogies (like a car dashboard light, dish soap cutting grease, a clogged kitchen filter, or a lock and key) and concrete real-life examples (specific symptoms at specific times of day, exact foods in the kitchen).
4. Structure the long video into 6 sequential points (`points` list). Each point MUST contain 4 detailed paragraphs (`paragraphs` list). Each paragraph MUST be 60 to 80 words of natural spoken English, with 2 distinct Pexels visual search queries (`queries`: list of 2 strings). Total spoken words across intro_hook + 24 paragraphs + outro must be 1550 to 1800 words so the video is at least 9.5 minutes long.
5. Also create `short` for a high-retention 45-55 second YouTube Short with 7 fast-paced scenes (`scenes` list), where each scene has 1 punchy sentence (`narration`), a 3-to-4 word uppercase `caption`, and a portrait Pexels search `query`.

Return ONLY valid JSON matching this structure:
{{
  "youtube_title": "Catchy clear title (max 85 chars, no person names)",
  "thumbnail_hook": "3 TO 4 UPPERCASE WORDS",
  "thumbnail_prompt": "Detailed 16:9 image generation prompt, no text in image",
  "intro_hook": "4-sentence thrilling analogy-driven opening hook",
  "points": [
    {{
      "title": "Point 1: ...",
      "subtitle": "Short clear subtitle",
      "badge": "2-3 WORD UPPERCASE BADGE",
      "paragraphs": [
        {{"text": "60-80 words with simple everyday example...", "queries": ["visual query 1", "visual query 2"]}},
        {{"text": "60-80 words...", "queries": ["visual query 1", "visual query 2"]}},
        {{"text": "60-80 words...", "queries": ["visual query 1", "visual query 2"]}},
        {{"text": "60-80 words...", "queries": ["visual query 1", "visual query 2"]}}
      ]
    }}
  ],
  "outro": "Warm closing summary asking viewers to like, comment which example helped them, and subscribe to MedPulse 5",
  "short": {{
    "hook_banner": "3 TO 4 WORD HOOK",
    "scenes": [
      {{"narration": "One punchy sentence", "caption": "3-4 WORD CAPTION", "query": "vertical visual query"}}
    ]
  }}
}}"""
    for m_name in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
        try:
            m = genai.GenerativeModel(m_name)
            r = m.generate_content(prompt)
            raw = (r.text or "").strip()
            raw = re.sub(r"^" + "\x60\x60\x60" + r"(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*" + "\x60\x60\x60" + r"$", "", raw)
            j0, j1 = raw.find("{"), raw.rfind("}")
            if j0 != -1 and j1 != -1: raw = raw[j0:j1+1]
            data = json.loads(raw)
            pts = data.get("points", [])
            if len(pts) < 6: continue
            for idx, p in enumerate(pts[:6]):
                p["title"] = clean_txt(p.get("title", fb["points"][idx]["title"]))
                p["subtitle"] = clean_txt(p.get("subtitle", fb["points"][idx]["subtitle"]))
                p["badge"] = clean_txt(p.get("badge", fb["points"][idx]["badge"])).upper()[:24]
                prs = p.get("paragraphs", [])
                while len(prs) < 4:
                    prs.append(fb["points"][idx]["paragraphs"][len(prs) % 4])
                for k, pr in enumerate(prs[:4]):
                    tx = clean_txt(pr.get("text", ""))
                    if len(tx.split()) < 38:
                        tx = tx + " " + fb["points"][idx]["paragraphs"][k]["text"]
                    pr["text"] = clean_txt(tx)
                    qs = pr.get("queries", [])
                    if not isinstance(qs, list) or len(qs) < 2:
                        qs = fb["points"][idx]["paragraphs"][k]["queries"]
                    pr["queries"] = [clean_txt(qs[0]), clean_txt(qs[1])]
                p["paragraphs"] = prs[:4]
            data["points"] = pts[:6]
            data["youtube_title"] = clean_txt(data.get("youtube_title", fb["youtube_title"]))
            data["thumbnail_hook"] = clean_txt(data.get("thumbnail_hook", fb["thumbnail_hook"])).upper()
            data["intro_hook"] = clean_txt(data.get("intro_hook", fb["intro_hook"]))
            data["outro"] = clean_txt(data.get("outro", fb["outro"]))
            if not data.get("short") or len(data["short"].get("scenes", [])) < 5:
                data["short"] = fb["short"]
            return data
        except Exception as e:
            print("Gemini retry:", e)
    return fb

async def _tts(txt, mp3_p, rate):
    c = edge_tts.Communicate(txt, VOICE_NAME, rate=rate, pitch=VOICE_PITCH)
    await c.save(mp3_p)

def gen_wav(txt, base_p, rate=VOICE_RATE):
    txt = clean_txt(txt)
    mp3_p = base_p + ".mp3"
    raw_w = base_p + "_raw.wav"
    wav_p = base_p + ".wav"
    for _ in range(3):
        try:
            asyncio.run(_tts(txt, mp3_p, rate))
            if os.path.exists(mp3_p) and os.path.getsize(mp3_p) > 300: break
        except Exception: time.sleep(1)
    subprocess.run(["ffmpeg", "-y", "-i", mp3_p, "-acodec", "pcm_s16le", "-ar", str(SR), "-ac", "2", raw_w], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.path.exists(raw_w) and os.path.getsize(raw_w) > 1000:
        with wave.open(raw_w, "rb") as rf:
            nf = rf.getnframes()
            keep = max(int(SR * 0.4), nf - int(SR * 0.06))
            frames = rf.readframes(keep)
        pad = b"\x00" * (int(SR * 0.30) * 4)
        total_bytes = frames + pad
        tot_samples = len(total_bytes) // 4
        with wave.open(wav_p, "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(SR)
            wf.writeframes(total_bytes)
        try: os.remove(raw_w)
        except Exception: pass
        return wav_p, float(tot_samples) / SR
    tot_samples = SR * 3
    with wave.open(wav_p, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(b"\x00" * (tot_samples * 4))
    return wav_p, 3.0

def gen_chime_wav(idx, dur=2.8):
    wav_p = f"temp/chime_{idx}.wav"
    n = int(SR * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    env = np.exp(-2.2 * t) * np.minimum(1.0, t / 0.04)
    w = (0.5 * np.sin(2 * math.pi * 528.0 * t) + 0.35 * np.sin(2 * math.pi * 660.0 * t)) * env * 0.14
    pcm = np.clip(np.column_stack([w, w]) * 32767.0, -32768, 32767).astype(np.int16)
    with wave.open(wav_p, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(pcm.tobytes())
    return wav_p, float(n) / SR

def build_master_wav(wav_list, out_wav):
    cur_sample = 0
    with wave.open(out_wav, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        for wp in wav_list:
            if not wp or not os.path.exists(wp): continue
            with wave.open(wp, "rb") as rf:
                raw = rf.readframes(rf.getnframes())
            arr = np.frombuffer(raw, dtype=np.int16).reshape(-1, 2).astype(np.float32)
            n = len(arr)
            t = (np.arange(n, dtype=np.float32) + cur_sample) / float(SR)
            cur_sample += n
            bgm = (np.sin(2 * math.pi * 110.0 * t) * 0.4 + np.sin(2 * math.pi * 164.8 * t) * 0.3 + np.sin(2 * math.pi * 220.0 * t) * 0.2) * (0.020 * 32767.0)
            arr[:, 0] = np.clip(arr[:, 0] + bgm, -32768, 32767)
            arr[:, 1] = np.clip(arr[:, 1] + bgm, -32768, 32767)
            wf.writeframes(arr.astype(np.int16).tobytes())

def export_final_mp4(clips, wav_list, out_mp4, tw, th, br):
    master_wav = out_mp4.replace(".mp4", "_master.wav")
    silent_mp4 = out_mp4.replace(".mp4", "_silent.mp4")
    build_master_wav(wav_list, master_wav)
    tot_d = float(sum(c.duration for c in clips))
    fin = concatenate_videoclips(clips, method="chain").set_duration(tot_d)
    fin.duration = tot_d
    fin.end = tot_d
    fin.write_videofile(silent_mp4, fps=FPS, codec="libx264", audio=False, bitrate=br, preset="ultrafast", threads=4, ffmpeg_params=["-pix_fmt", "yuv420p"])
    fin.close()
    cmd = ["ffmpeg", "-y", "-i", silent_mp4, "-i", master_wav, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out_mp4]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for p in (silent_mp4, master_wav):
        if os.path.exists(p):
            try: os.remove(p)
            except Exception: pass

def dl_pexels(q, dest, used_v, portrait=False):
    if not PEXELS_KEY: return None
    hdr = {"Authorization": PEXELS_KEY}
    ori = "portrait" if portrait else "landscape"
    qs = [q, "medical doctor health", "healthy nutrition vegetables", "human body anatomy wellness"]
    for sq in qs:
        try:
            u = f"https://api.pexels.com/videos/search?query={quote_plus(sq)}&per_page=15&orientation={ori}"
            r = requests.get(u, headers=hdr, timeout=15)
            if r.status_code != 200: continue
            for v in r.json().get("videos", []):
                vid = str(v.get("id", ""))
                if not vid or vid in used_v: continue
                best, bsc = None, 999999
                for vf in v.get("video_files", []):
                    if vf.get("file_type") != "video/mp4": continue
                    fw, fh = vf.get("width", 0), vf.get("height", 0)
                    if portrait and (fh <= fw or fw < 540): continue
                    if not portrait and (fw < fh or fw < 960): continue
                    sc = abs(fw - (1080 if portrait else 1280))
                    if sc < bsc:
                        bsc, best = sc, vf.get("link")
                if best:
                    vr = requests.get(best, timeout=25)
                    if vr.status_code == 200 and len(vr.content) > 50000:
                        with open(dest, "wb") as f: f.write(vr.content)
                        used_v.add(vid)
                        save_item(USED_VIDEOS_FILE, vid)
                        return dest
        except Exception: pass
    return None

def norm_one(raw_p, out_p, dur, tw=W, th=H):
    vf = f"scale={tw}:{th}:force_original_aspect_ratio=increase,crop={tw}:{th},setsar=1:1,fps={FPS},format=yuv420p"
    if raw_p and os.path.exists(raw_p):
        cmd = [
            "ffmpeg", "-y", "-stream_loop", "-1", "-i", raw_p,
            "-t", f"{dur + 0.35:.2f}", "-vf", vf, "-metadata:s:v:0", "rotate=0",
            "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", out_p
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(out_p) and os.path.getsize(out_p) > 8000: return out_p
    cmd_fb = [
        "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=0x101c2e:s={tw}x{th}:r={FPS}",
        "-t", f"{dur + 0.35:.2f}", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", out_p
    ]
    subprocess.run(cmd_fb, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out_p

def prep_two(q1, q2, tag, dur, used_v):
    d1 = max(2.2, dur * 0.5)
    d2 = max(2.2, dur - d1 + 0.35)
    r1 = dl_pexels(q1, f"temp/r1_{tag}.mp4", used_v, False)
    r2 = dl_pexels(q2, f"temp/r2_{tag}.mp4", used_v, False)
    n1 = norm_one(r1, f"temp/n1_{tag}.mp4", d1, W, H)
    n2 = norm_one(r2, f"temp/n2_{tag}.mp4", d2, W, H)
    lst = f"temp/lst_{tag}.txt"
    with open(lst, "w", encoding="utf-8") as f:
        f.write(f"file '{os.path.abspath(n1)}'\nfile '{os.path.abspath(n2)}'\n")
    out = f"temp/m_{tag}.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", out], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for p in (r1, r2, n1, n2, lst):
        if p and os.path.exists(p):
            try: os.remove(p)
            except Exception: pass
    return out if (os.path.exists(out) and os.path.getsize(out) > 8000) else norm_one(None, out, dur, W, H)

def draw_logo(img, x, y, sz=78):
    if not os.path.exists(LOGO_PATH): return
    try:
        lg = Image.open(LOGO_PATH).convert("RGBA").resize((sz, sz), Image.Resampling.LANCZOS)
        msk = Image.new("L", (sz, sz), 0)
        ImageDraw.Draw(msk).ellipse((0, 0, sz, sz), fill=255)
        bdr = Image.new("RGBA", (sz+6, sz+6), (0, 0, 0, 0))
        ImageDraw.Draw(bdr).ellipse((0, 0, sz+5, sz+5), fill=(0, 215, 255, 230))
        img.paste(bdr, (x-3, y-3), bdr)
        img.paste(lg, (x, y), msk)
    except Exception: pass

def make_ov(idx, tot, badge, title, sub, cap, prog):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    dr.rectangle([28, 22, 265, 62], fill=(10, 22, 42, 225), outline=(0, 210, 255, 220), width=2)
    dr.text((42, 31), f"MEDPULSE 5  |  POINT {idx}/{tot}", font=fnt(17, True), fill=(255, 255, 255, 255))
    bx = 280
    bw = max(160, len(badge) * 11 + 30)
    dr.rectangle([bx, 22, bx + bw, 62], fill=(0, 145, 195, 225))
    dr.text((bx + 14, 31), badge[:24], font=fnt(17, True), fill=(255, 255, 255, 255))
    draw_logo(img, W - 108, 18, 76)
    if cap:
        words = cap.split()
        lines, cur = [], ""
        for w in words:
            if len(cur + " " + w) <= 58: cur = (cur + " " + w).strip()
            else:
                lines.append(cur)
                cur = w
        if cur: lines.append(cur)
        lines = lines[:2]
        dr.rectangle([130, 505, W - 130, 588], fill=(6, 12, 24, 215), outline=(255, 210, 0, 175), width=2)
        y0 = 515 if len(lines) == 2 else 532
        for ln in lines:
            dr.text((152, y0), ln, font=fnt(25, True), fill=(255, 245, 145, 255))
            y0 += 32
    dr.rectangle([0, 600, W, H], fill=(8, 16, 32, 242))
    dr.rectangle([0, 600, W, 605], fill=(0, 210, 255, 255))
    dr.rectangle([26, 616, 36, 696], fill=(255, 195, 0, 255))
    dr.text((50, 614), title[:66], font=fnt(27, True), fill=(255, 255, 255, 255))
    dr.text((50, 654), sub[:88], font=fnt(20, False), fill=(185, 220, 245, 255))
    pw = int(W * max(0.02, min(1.0, prog)))
    dr.rectangle([0, H - 7, pw, H], fill=(255, 200, 0, 255))
    return np.array(img)

def make_card(idx, tot, title, sub, badge):
    wp, dur = gen_chime_wav(idx, 2.8)
    img = Image.new("RGBA", (W, H), (10, 20, 38, 255))
    dr = ImageDraw.Draw(img)
    dr.rectangle([55, 55, W - 55, H - 55], outline=(0, 210, 255, 220), width=3)
    dr.rectangle([95, 160, 390, 212], fill=(0, 175, 230, 255))
    dr.text((112, 173), f"POINT {idx} OF {tot}  |  {badge[:14]}", font=fnt(21, True), fill=(255, 255, 255, 255))
    dr.text((95, 255), title[:54], font=fnt(38, True), fill=(255, 255, 255, 255))
    dr.text((95, 325), sub[:78], font=fnt(24, False), fill=(190, 225, 250, 255))
    dr.rectangle([95, 415, W - 260, 421], fill=(255, 200, 0, 255))
    dr.text((95, 450), "MEDPULSE 5  -  SIMPLIFIED HEALTH & REAL EXAMPLES", font=fnt(20, True), fill=(0, 215, 255, 255))
    draw_logo(img, W - 175, 85, 96)
    c = ImageClip(np.array(img)[:, :, :3]).set_duration(dur)
    c.duration = dur
    c.end = dur
    return c, wp, dur

def build_scene(vp, dur, idx, tot, badge, title, sub, txt, p0, p1):
    vc = VideoFileClip(vp).without_audio()
    vc = vc.subclip(0, min(dur, vc.duration)).set_duration(dur)
    words = txt.split()
    ch = [" ".join(words[i:i+13]) for i in range(0, len(words), 13)] or [txt]
    cd = dur / len(ch)
    ovs = []
    for i, c_txt in enumerate(ch):
        pr = p0 + (p1 - p0) * ((i + 1) / len(ch))
        arr = make_ov(idx, tot, badge, title, sub, c_txt, pr)
        ovs.append(ImageClip(arr).set_start(i * cd).set_duration(cd))
    comp = CompositeVideoClip([vc] + ovs, size=(W, H)).set_duration(dur)
    comp.duration = dur
    comp.end = dur
    return comp

def make_sh_ov(banner, cap, main_txt, prog):
    img = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    dr.rectangle([45, 75, 420, 140], fill=(10, 22, 44, 230), outline=(0, 215, 255, 240), width=3)
    dr.text((68, 92), "MEDPULSE 5 DAILY", font=fnt(30, True), fill=(255, 255, 255, 255))
    draw_logo(img, SW - 165, 62, 105)
    dr.rectangle([45, 165, SW - 45, 250], fill=(215, 25, 45, 238), outline=(255, 255, 255, 210), width=2)
    dr.text((70, 185), banner[:30].upper(), font=fnt(38, True), fill=(255, 255, 255, 255))
    if main_txt:
        ws = main_txt.upper().split()
        lns, c = [], ""
        for w in ws:
            if len(c + " " + w) <= 18: c = (c + " " + w).strip()
            else:
                lns.append(c)
                c = w
        if c: lns.append(c)
        lns = lns[:3]
        bh = len(lns) * 74 + 44
        by = 1120 - bh // 2
        dr.rectangle([55, by, SW - 55, by + bh], fill=(8, 14, 28, 228), outline=(255, 215, 0, 245), width=4)
        ty = by + 20
        for j, ln in enumerate(lns):
            col = (255, 230, 0, 255) if j % 2 == 0 else (255, 255, 255, 255)
            dr.text((92, ty+3), ln, font=fnt(54, True), fill=(0, 0, 0, 255))
            dr.text((88, ty), ln, font=fnt(54, True), fill=(0, 0, 0, 255))
            dr.text((90, ty), ln, font=fnt(54, True), fill=col)
            ty += 72
    dr.rectangle([0, SH - 250, SW, SH], fill=(8, 16, 34, 242))
    dr.rectangle([0, SH - 250, SW, SH - 242], fill=(0, 215, 255, 255))
    dr.text((60, SH - 210), cap[:32].upper(), font=fnt(40, True), fill=(255, 215, 0, 255))
    dr.text((60, SH - 140), "LIKE & SUBSCRIBE FOR DAILY HEALTH GUIDES", font=fnt(28, True), fill=(255, 255, 255, 255))
    pw = int(SW * max(0.03, min(1.0, prog)))
    dr.rectangle([0, SH - 14, pw, SH], fill=(255, 210, 0, 255))
    return np.array(img)

def build_short(data, used_v):
    sh = data.get("short", {})
    scs = sh.get("scenes", [])[:8]
    banner = clean_txt(sh.get("hook_banner", data.get("thumbnail_hook", "DAILY HEALTH CLUE")))
    clips, wavs = [], []
    for i, sc in enumerate(scs):
        nar = clean_txt(sc.get("narration", ""))
        cap = clean_txt(sc.get("caption", "KEY HEALTH TIP"))
        q = clean_txt(sc.get("query", "healthy lifestyle vertical"))
        if not nar: continue
        wp, dur = gen_wav(nar, f"temp/sh_a_{i}", rate=SHORT_RATE)
        rp = dl_pexels(q, f"temp/sh_r_{i}.mp4", used_v, True)
        np_p = norm_one(rp, f"temp/sh_n_{i}.mp4", dur, SW, SH)
        if rp and os.path.exists(rp):
            try: os.remove(rp)
            except Exception: pass
        vc = VideoFileClip(np_p).without_audio()
        vc = vc.subclip(0, min(dur, vc.duration)).set_duration(dur)
        ws = nar.split()
        ch = [" ".join(ws[k:k+5]) for k in range(0, len(ws), 5)] or [nar]
        cd = dur / len(ch)
        ovs = []
        for k, c_txt in enumerate(ch):
            pr = (i + (k + 1) / len(ch)) / max(1, len(scs))
            arr = make_sh_ov(banner, cap, c_txt, pr)
            ovs.append(ImageClip(arr).set_start(k * cd).set_duration(cd))
        comp = CompositeVideoClip([vc] + ovs, size=(SW, SH)).set_duration(dur)
        comp.duration = dur
        comp.end = dur
        clips.append(comp)
        wavs.append(wp)
    if not clips: return
    export_final_mp4(clips, wavs, "output/short_video.mp4", SW, SH, "5000k")

def write_details(tr, data, stamps):
    yt_t = clean_txt(data.get("youtube_title", tr["title"]))
    th_h = clean_txt(data.get("thumbnail_hook", "WARNING SIGNS"))
    th_p = clean_txt(data.get("thumbnail_prompt", "High-contrast 16:9 medical illustration, cinematic 8k, no text"))
    ts_block = "\n".join(stamps)
    src_lines = []
    for idx, s in enumerate(tr.get("sources", []), 1):
        u = s.get("url", "").strip()
        if u: src_lines.append(f"{idx}. {s['name']} - {s['title']}\n   {u}")
        else: src_lines.append(f"{idx}. {s['name']} - {s['title']}")
    src_block = "\n".join(src_lines)
    tags = ["MedPulse 5", "health education", "symptoms explained", "nutrition tips", "cellular health", "natural remedies", "daily health", "vitamins and minerals", "digestive health", "preventive health"]
    ht = "\x23MedPulse5 \x23HealthTips \x23Nutrition \x23WarningSigns \x23Wellness"
    sh_ht = "\x23Shorts \x23YouTubeShorts \x23HealthShorts \x23MedPulse5 \x23DailyHealth"
    txt = f"""====================================================================
1) LONG VIDEO - YOUTUBE TITLE (COPY & PASTE):
====================================================================
{yt_t}

====================================================================
2) LONG VIDEO - YOUTUBE DESCRIPTION (SOURCES CITED IN DESCRIPTION ONLY):
====================================================================
{yt_t}

In today's episode on MedPulse 5, we break down one of today's top-searched health topics into simple, everyday language with real-life examples and practical kitchen habits you can test right away.

TIMESTAMPS & CHAPTERS:
{ts_block}

TODAY'S DIVERSE MEDICAL & HEALTH SOURCES:
{src_block}

MEDICAL DISCLAIMER:
This video on MedPulse 5 is for general educational and informational purposes only and is not a substitute for professional medical advice, diagnosis, or treatment. Always consult a qualified healthcare provider with any questions regarding a medical condition.

{ht}

====================================================================
3) YOUTUBE TAGS (COMMA-SEPARATED):
====================================================================
{", ".join(tags)}

====================================================================
4) THUMBNAIL GENERATION PROMPT & TEXT HOOK:
====================================================================
Thumbnail Text Hook (3-4 Words):
{th_h}

AI Image Generator Prompt (Choose Landscape 16:9):
{th_p}

====================================================================
5) YOUTUBE SHORT - TITLE, DESCRIPTION & HASHTAGS:
====================================================================
Short Title:
{yt_t[:55]} {sh_ht}

Short Description:
Watch the full 9+ minute step-by-step guide on our channel MedPulse 5!
Sources & references are listed in our full video description.
{sh_ht}
"""
    with open("output/youtube_details.txt", "w", encoding="utf-8") as f:
        f.write(txt)

def main():
    used_v = load_set(USED_VIDEOS_FILE)
    tr = fetch_live_trend()
    print("Selected Same-Day Trend:", tr["title"])
    data = generate_script(tr)
    pts = data["points"]
    tot_p = len(pts)
    timeline, wavs, stamps = [], [], ["00:00 Introduction & Real-Life Analogy"]
    cur_t = 0.0

    iw, idur = gen_wav(data["intro_hook"], "temp/intro_a")
    iv = prep_two(pts[0]["paragraphs"][0]["queries"][0], pts[0]["paragraphs"][0]["queries"][1], "intro", idur, used_v)
    timeline.append(build_scene(iv, idur, 1, tot_p, "TODAY'S TOP TREND", data["youtube_title"], "Simple everyday examples & step-by-step guide", data["intro_hook"], 0.0, 0.04))
    wavs.append(iw)
    cur_t += idur

    tot_paras = tot_p * 4
    p_cnt = 0
    for idx, pt in enumerate(pts, 1):
        card, cw, cdur = make_card(idx, tot_p, pt["title"], pt["subtitle"], pt["badge"])
        timeline.append(card)
        wavs.append(cw)
        cur_t += cdur
        mm, ss = int(cur_t // 60), int(cur_t % 60)
        stamps.append(f"{mm:02d}:{ss:02d} {pt['title']}")
        for k, pr in enumerate(pt["paragraphs"], 1):
            p_cnt += 1
            pw, pdur = gen_wav(pr["text"], f"temp/p_{idx}_{k}")
            pv = prep_two(pr["queries"][0], pr["queries"][1], f"{idx}_{k}", pdur, used_v)
            pr0 = 0.04 + 0.90 * ((p_cnt - 1) / tot_paras)
            pr1 = 0.04 + 0.90 * (p_cnt / tot_paras)
            sc = build_scene(pv, pdur, idx, tot_p, pt["badge"], pt["title"], pt["subtitle"], pr["text"], pr0, pr1)
            timeline.append(sc)
            wavs.append(pw)
            cur_t += pdur

    bonus_i = 0
    bonus_pool = [
        "Let us look at one more practical everyday example so you can spot this easily at home. Notice how your energy and digestion feel sixty minutes after eating a freshly cooked whole-food meal compared to a packaged convenience meal. When your meal contains natural fiber, clean protein, and healthy fats, your stomach empties at a steady pace and your brain receives a smooth stream of fuel for hours without jittery crashes.",
        "Another simple self-check you can do this week takes less than ten seconds each morning. Pay attention to how rested your eyes and calf muscles feel when you first stand up out of bed, and notice how steady your focus stays between lunch and dinner when you hydrate with water and natural electrolytes before drinking coffee."
    ]
    while cur_t < MIN_LONG_SEC and bonus_i < len(bonus_pool):
        btxt = bonus_pool[bonus_i]
        bonus_i += 1
        bw, bdur = gen_wav(btxt, f"temp/bonus_{bonus_i}")
        bv = prep_two("healthy meal preparation kitchen", "energetic person outdoors morning", f"b_{bonus_i}", bdur, used_v)
        timeline.append(build_scene(bv, bdur, tot_p, tot_p, "PRACTICAL RECAP", "Real-Life Daily Self-Check", "Putting today's examples into practice", btxt, 0.94, 0.97))
        wavs.append(bw)
        cur_t += bdur

    ow, odur = gen_wav(data["outro"], "temp/outro_a")
    ov = prep_two("happy healthy people outdoors", "doctor smiling clinic", "outro", odur, used_v)
    timeline.append(build_scene(ov, odur, tot_p, tot_p, "MEDPULSE 5 SUMMARY", "Like, Comment & Subscribe to MedPulse 5", "Share which example stood out to you in the comments!", data["outro"], 0.97, 1.0))
    wavs.append(ow)
    cur_t += odur

    export_final_mp4(timeline, wavs, "output/final_video.mp4", W, H, "3500k")
    build_short(data, used_v)
    write_details(tr, data, stamps)
    save_item(USED_NEWS_FILE, tr["id"])
    print("All outputs generated successfully!")

if __name__ == "__main__":
    main()
