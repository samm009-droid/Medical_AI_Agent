import os, re, json, math, time, random, asyncio, subprocess, urllib.parse
import requests, feedparser, edge_tts, numpy as np
from PIL import Image, ImageDraw, ImageFont
import PIL.Image

setattr(PIL.Image, "ANTIALIAS", getattr(PIL.Image, "LANCZOS", PIL.Image.BICUBIC))

import google.generativeai as genai
from moviepy.editor import (
    VideoFileClip, AudioFileClip, ImageClip, ColorClip,
    CompositeVideoClip, CompositeAudioClip, concatenate_videoclips
)
from moviepy.audio.AudioClip import AudioArrayClip, concatenate_audioclips

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "").strip()

W, H = 1280, 720
SHORT_W, SHORT_H = 720, 1280
FPS = 24

VOICE_NAME = "en-US-ChristopherNeural"
VOICE_RATE = "-5%"
VOICE_PITCH = "-2Hz"

USED_VIDEOS_FILE = "used_videos.txt"
USED_NEWS_FILE = "used_news.txt"
LOGO_PATH = "\u062a\u0646\u0632\u064a\u0644.jpeg"

os.makedirs("temp", exist_ok=True)
os.makedirs("output", exist_ok=True)

LIVE_TREND_FEEDS = [
    "https://trends.google.com/trending/rss?geo=US",
    "https://trends.google.com/trending/rss?geo=GB",
    "https://news.google.com/rss/search?q=symptoms+OR+deficiency+OR+remedy+OR+vitamin+health+when:1d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=fatty+liver+OR+insulin+resistance+OR+blood+sugar+OR+cortisol+when:1d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=magnesium+OR+vitamin+D+OR+omega+3+OR+gut+bloating+when:1d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=blood+pressure+OR+cholesterol+OR+arteries+OR+kidney+health+when:1d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=sleep+insomnia+OR+chronic+fatigue+OR+inflammation+diet+when:1d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=new+study+health+nutrition+metabolism+longevity+when:1d&hl=en-US&gl=US&ceid=US:en",
    "https://www.health.harvard.edu/blog/feed",
    "https://health.clevelandclinic.org/feed/",
    "https://www.medicalnewstoday.com/rss",
    "https://www.healthline.com/rss/health-news",
    "https://www.drugs.com/feeds/medical_news.xml",
    "https://www.sciencedaily.com/rss/health_medicine/nutrition.xml"
]

GOOGLE_AUTOCOMPLETE_SEEDS = [
    "why does my body ",
    "symptoms of low vitamin ",
    "what happens if you eat ",
    "what happens if you drink ",
    "best natural remedy for ",
    "how to reverse fatty ",
    "hidden signs of high ",
    "why do i wake up ",
    "best supplement for ",
    "foods that destroy your "
]

HIGH_DEMAND_HEALTH_TERMS = {
    "vitamin": 8, "magnesium": 9, "deficiency": 9, "symptom": 8, "symptoms": 8,
    "liver": 9, "fatty liver": 10, "kidney": 8, "insulin": 9, "blood sugar": 10,
    "diabetes": 8, "cholesterol": 8, "blood pressure": 9, "artery": 8, "heart": 7,
    "sleep": 8, "cortisol": 9, "bloating": 9, "gut": 8, "stomach": 7, "acid": 7,
    "inflammation": 9, "joint": 7, "nerve": 8, "tingling": 9, "numbness": 9,
    "fatigue": 8, "tired": 8, "thyroid": 8, "metabolism": 8, "fasting": 8,
    "clove": 8, "turmeric": 8, "vinegar": 8, "lemon": 7, "ginger": 7, "garlic": 7,
    "omega": 8, "collagen": 7, "potassium": 8, "zinc": 7, "iron": 7, "b12": 9
}

SAFE_LANDSCAPE_QUERIES = [
    "doctor explaining medical chart to patient in bright clinic",
    "healthy fresh vegetables herbs and natural nutrition on table",
    "close up vitamin supplement capsules and glass of water",
    "scientist examining blood sample tube in medical laboratory",
    "doctor checking patient blood pressure in modern hospital",
    "healthy Mediterranean diet fresh food preparation in kitchen",
    "close up natural spices turmeric ginger lemon herbal tea",
    "pharmacist organizing prescription bottles in pharmacy",
    "medical researcher looking through microscope in lab",
    "active person walking outdoors in morning sunlight health",
    "person sleeping peacefully in bedroom night rest recovery",
    "nutritionist consulting patient with healthy foodon desk"
]

SAFE_PORTRAIT_QUERIES = [
    "healthy fresh food nutrition vertical",
    "doctor medical clinic consultation vertical",
    "fitness healthy lifestyle morning routine",
    "vitamin capsules glass of water health",
    "fresh lemon herbal tea healthy drink",
    "laboratory scientist medical research"
]

KEYWORD_VISUAL_MAP = [
    (["liver", "bile", "detox", "abdomen", "visceral"], "doctor examining abdominal ultrasound scan in clinic"),
    (["kidney", "urine", "uric", "stone", "filtration", "water"], "fresh lemon water hydration glass on table"),
    (["heart", "artery", "plaque", "cholesterol", "blood pressure", "pulse"], "cardiologist checking patient blood pressure monitor"),
    (["sugar", "glucose", "insulin", "diabetes", "pancreas", "carb"], "patient checking blood sugar meter with doctor"),
    (["vitamin", "supplement", "magnesium", "zinc", "b12", "capsule", "pill"], "close up golden vitamin supplement capsules on table"),
    (["gut", "stomach", "bloat", "acid", "digestion", "intestine", "microbiome"], "healthy fresh vegetables fiber rich nutrition food"),
    (["herb", "spice", "clove", "turmeric", "ginger", "garlic", "tea", "vinegar"], "natural herbs spices and warm herbal tea in kitchen"),
    (["sleep", "wake", "night", "insomnia", "cortisol", "stress", "tired", "fatigue"], "person sleeping peacefully in dark bedroom night"),
    (["nerve", "tingling", "numb", "hand", "foot", "cramp", "muscle", "joint"], "physical therapist doctor examining patient hand and leg"),
    (["cell", "blood", "hormone", "enzyme", "receptor", "inflammation", "immune"], "scientist analyzing blood sample under microscope lab")
]

THUMBNAIL_PALETTES = [
    {"glow": "emerald green and golden yellow", "accent": "bright yellow"},
    {"glow": "crimson red and icy cyan", "accent": "crisp white"},
    {"glow": "warm amber and deep cobalt blue", "accent": "neon yellow"},
    {"glow": "clinical teal and fiery orange", "accent": "warm gold"}
]

STOP_WORDS = {
    "about", "after", "again", "against", "because", "before", "between", "could",
    "during", "every", "found", "health", "human", "large", "level", "levels",
    "medical", "might", "other", "people", "patients", "research", "results",
    "shows", "study", "studies", "their", "there", "these", "those", "through",
    "treatment", "under", "using", "while", "without", "would", "years"
}

def load_circular_logo(path, size=64):
    if not os.path.exists(path):
        return None
    try:
        img = Image.open(path).convert("RGBA").resize((size, size), PIL.Image.LANCZOS)
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
        out = Image.new("RGBA", (size + 8, size + 8), (0, 0, 0, 0))
        ImageDraw.Draw(out).ellipse((0, 0, size + 7, size + 7), fill=(0, 210, 255, 240), outline=(255, 255, 255, 240), width=2)
        out.paste(img, (4, 4), mask)
        return out
    except Exception:
        return None

LOGO_PIL = load_circular_logo(LOGO_PATH, size=64)
LOGO_SHORT_PIL = load_circular_logo(LOGO_PATH, size=54)

def load_font(size, bold=True):
    candidates = [
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()

def load_used_items(filepath, max_keep=600):
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()][-max_keep:]

def save_used_items(filepath, items, max_keep=600):
    with open(filepath, "w", encoding="utf-8") as f:
        for item in items[-max_keep:]:
            f.write(f"{item}\n")

def clean_text_for_tts(text):
    text = re.sub(r"[*_#`~>]", " ", str(text))
    return re.sub(r"\s+", " ", text).strip()

def fetch_live_google_autocomplete_trends():
    suggestions = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    for seed in random.sample(GOOGLE_AUTOCOMPLETE_SEEDS, min(6, len(GOOGLE_AUTOCOMPLETE_SEEDS))):
        try:
            url = f"https://suggestqueries.google.com/complete/search?client=firefox&hl=en&gl=us&q={urllib.parse.quote(seed)}"
            r = requests.get(url, headers=headers, timeout=8)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and len(data) > 1 and isinstance(data[1], list):
                    for s in data[1][:5]:
                        if isinstance(s, str) and len(s) > 18:
                            suggestions.append(s.strip())
        except Exception:
            continue
    return suggestions

def fetch_live_google_trend_topic():
    print("Scanning Real-Time Google Search Trends, Autocomplete & 24h Health Feeds...")
    used_news = set(load_used_items(USED_NEWS_FILE))
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    candidates = []
    word_freq = {}

    live_queries = fetch_live_google_autocomplete_trends()
    for q in live_queries:
        for w in re.findall(r"[a-z]{4,}", q.lower()):
            if w not in STOP_WORDS:
                word_freq[w] = word_freq.get(w, 0) + 2

    for url in LIVE_TREND_FEEDS:
        try:
            r = requests.get(url, headers=headers, timeout=12)
            if r.status_code != 200:
                continue
            feed = feedparser.parse(r.content)
            for entry in feed.entries[:20]:
                title = re.sub(r"<[^>]+>", "", entry.get("title", "")).strip()
                if " - " in title and len(title.split(" - ")[0]) > 24:
                    title = " - ".join(title.split(" - ")[:-1]).strip()
                summary = re.sub(r"<[^>]+>", " ", entry.get("summary", entry.get("description", ""))).strip()
                summary = re.sub(r"\s+", " ", summary)[:500]
                link = entry.get("link", "").strip()
                if not title or len(title) < 18:
                    continue
                norm_key = re.sub(r"[^a-z0-9]", "", title.lower())[:60]
                if norm_key in used_news or (link and link in used_news):
                    continue

                combined = f"{title} {summary}".lower()
                if any(bad in combined for bad in ["politics", "senate", "election", "lawsuit", "stock market", "murder", "crash"]):
                    continue

                base_score = 0
                for term, weight in HIGH_DEMAND_HEALTH_TERMS.items():
                    if term in combined:
                        base_score += weight
                if base_score == 0 and "trends.google.com" in url:
                    continue

                words = set(re.findall(r"[a-z]{4,}", title.lower())) - STOP_WORDS
                for w in words:
                    word_freq[w] = word_freq.get(w, 0) + 1

                candidates.append({
                    "title": title,
                    "summary": summary or title,
                    "link": link or "https://news.google.com",
                    "norm_key": norm_key,
                    "words": words,
                    "base_score": base_score
                })
        except Exception:
            continue

    for q in live_queries:
        norm_key = re.sub(r"[^a-z0-9]", "", q.lower())[:60]
        if norm_key in used_news:
            continue
        q_low = q.lower()
        b_score = sum(wt for tm, wt in HIGH_DEMAND_HEALTH_TERMS.items() if tm in q_low) + 12
        words = set(re.findall(r"[a-z]{4,}", q_low)) - STOP_WORDS
        candidates.append({
            "title": q.title(),
            "summary": f"High-volume live Google search query trending today: {q}",
            "link": "https://trends.google.com",
            "norm_key": norm_key,
            "words": words,
            "base_score": b_score
        })

    if not candidates:
        fallback_q = "Why Magnesium, Vitamin D3, and Insulin Resistance Control Your Daily Energy and Organ Repair"
        return {
            "title": fallback_q,
            "summary": "Trending patient search on how mineral deficiencies and elevated insulin trigger fatigue, fatty liver, and nighttime waking.",
            "link": "https://trends.google.com",
            "norm_key": f"live_{int(time.time())}",
            "related_searches": live_queries[:4]
        }

    for c in candidates:
        velocity_bonus = sum(min(word_freq.get(w, 0), 8) * 3 for w in c["words"] if word_freq.get(w, 0) >= 2)
        c["total_score"] = c["base_score"] + velocity_bonus

    candidates.sort(key=lambda x: x["total_score"], reverse=True)
    winner = candidates[0]
    related = []
    for other in candidates[1:30]:
        if len(winner["words"] & other["words"]) >= 1 and other["title"] != winner["title"]:
            related.append(other["title"])
            if len(related) >= 4:
                break
    winner["related_searches"] = related or live_queries[:4]
    print(f"Selected #1 Live Google Search Trend (Score {winner['total_score']}): {winner['title']}")
    return winner

def get_thumbnail_spec(topic_title):
    t = topic_title.lower()
    if any(w in t for w in ["vitamin", "magnesium", "supplement", "b12", "zinc", "omega"]):
        return "HIDDEN DEFICIENCY", "glowing golden vitamin capsules beside a high-contrast clinical blood analysis display"
    if any(w in t for w in ["liver", "kidney", "detox", "bile"]):
        return "ORGAN WARNING SIGNS", "an anatomical 3D glowing human liver and kidney model with fresh lemon and clinical markers"
    if any(w in t for w in ["sugar", "insulin", "diabetes", "fasting", "metabolism", "weight"]):
        return "BLOOD SUGAR TRUTH", "a digital glucose monitor showing a sharp drop beside natural metabolism-boosting foods"
    if any(w in t for w in ["heart", "pressure", "cholesterol", "artery"]):
        return "CHECK THIS NOW", "a cinematic macro cross-section of a clean glowing artery and a blood pressure cuff"
    if any(w in t for w in ["sleep", "wake", "cortisol", "tired", "fatigue"]):
        return "STOP IGNORING THIS", "a glowing bedside clock at 3:00 AM with a calm cellular energy restoration wave"
    return "THE ROOT CAUSE", "a dramatic high-contrast medical illustration of cellular repair, natural herbs, and clinical diagnostics"

def pick_visual_queries_for_text(text, count=3):
    t_low = text.lower()
    picked = []
    for kw_list, q in KEYWORD_VISUAL_MAP:
        if any(k in t_low for k in kw_list) and q not in picked:
            picked.append(q)
            if len(picked) >= count:
                return picked
    pool = SAFE_LANDSCAPE_QUERIES[:]
    random.shuffle(pool)
    for pq in pool:
        if pq not in picked:
            picked.append(pq)
            if len(picked) >= count:
                break
    return picked

def generate_dr_berg_masterclass_script(topic):
    related_str = "\n".join(f"- {r}" for r in topic.get("related_searches", []))
    prompt = f"""
You are a world-class medical educator speaking in the exact teaching style of Dr. Eric Berg ('Dr. Berg').
Today's video is about the #1 LIVE TRENDING HEALTH SEARCH on Google right now:

TRENDING TOPIC / SEARCH: {topic['title']}
CONTEXT & DETAILS: {topic['summary']}
RELATED LIVE GOOGLE SEARCHES TODAY:
{related_str}

YOUR MISSION:
Transform this #1 trending topic into a deep, comprehensive, example-packed Dr. Berg style masterclass video.
Do NOT write like a dry academic report or a news anchor. Speak warmly, clearly, and directly to the viewer ('you') like Dr. Berg teaching a patient.

MANDATORY DR. BERG ELEMENTS:
1. THRILLING, FAST-PACED INTRO HOOK ('intro_hook', 45 to 60 words):
   - Grab the viewer in the very first second with a surprising question, a hidden symptom they might be feeling right now, or a common myth about this topic, then promise the exact root cause and step-by-step fix.
2. 6 DEEP, COMPREHENSIVE POINTS ('points', list of 6 objects):
   - Point 1: The Hidden Symptom & What Most People Get Wrong
   - Point 2: The Real Root Cause Inside Your Body (Use a vivid everyday analogy like dish soap, a clogged filter, or a rusted lock)
   - Point 3: Concrete Real-Life Examples & Warning Signs on Your Body
   - Point 4: How It Affects Your Hormones, Organs & Cellular Energy Step-by-Step
   - Point 5: The Worst Daily Mistakes, Foods, or Habits That Make It Worse
   - Point 6: The Complete Step-by-Step Natural Action Plan (Exact foods, herbs, vitamin forms, dosages, and daily timing)
3. RICH EXPLANATION & EXAMPLES (NO ARTIFICIAL SHORTENING):
   - Each of the 6 points MUST have `paragraphs`: a list of 3 detailed, engaging paragraphs (each paragraph 75 to 95 words).
   - Every point MUST include concrete real-world examples (e.g., what happens after a specific meal, why a certain symptom appears at night, specific food/mineral pairings).
4. WARM, POLITE OUTRO ('outro', 50 to 65 words):
   - Summarize the #1 takeaway in one sentence, then politely and warmly ask the viewer to subscribe (follow) the channel, leave a comment sharing which symptom or step resonated with them, and hit the like button so this information can help more people.
5. COMPANION YOUTUBE SHORT ('short_script'):
   - 4 punchy, exciting scenes (`scenes`: list of 4 objects, 22 to 28 words each) for a 9:16 vertical YouTube Short on the exact same trending topic.

Return ONLY valid JSON with this structure:
{{
  "title_options": [
    "High-CTR Dr. Berg Style Title #1 (under 70 chars)",
    "High-CTR Title #2",
    "High-CTR Title #3"
  ],
  "intro_hook": "45-60 words thrilling hook...",
  "points": [
    {{
      "point_num": 1,
      "point_title": "Short Clear Title (under 48 chars)",
      "point_subtitle": "One-line key takeaway (under 65 chars)",
      "paragraphs": [
        "Detailed paragraph 1 (75-95 words with real-life example)...",
        "Detailed paragraph 2 (75-95 words with simple analogy)...",
        "Detailed paragraph 3 (75-95 words with practical insight)..."
      ]
    }}
  ],
  "outro": "50-65 words warm polite request to subscribe, comment, and like...",
  "short_script": {{
    "short_title": "Viral Short Title #Shorts",
    "hook_badge": "3-WORD HOOK",
    "scenes": [
      {{"narration": "22-28 words thrilling hook...", "portrait_query": "healthy nutrition food"}},
      {{"narration": "22-28 words hidden root cause...", "portrait_query": "doctor medical clinic"}},
      {{"narration": "22-28 words real-life example or warning sign...", "portrait_query": "vitamin supplement capsules"}},
      {{"narration": "22-28 words quick tip + polite invite to watch full video & subscribe...", "portrait_query": "fresh herbal tea lemon"}}
    ]
  }},
  "description": "Comprehensive SEO YouTube description...",
  "tags": "comma, separated, high, search, tags"
}}
"""
    genai.configure(api_key=GEMINI_API_KEY)
    raw_data = {}
    for model_name in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
        for attempt in range(2):
            try:
                print(f"Generating Deep Dr. Berg Script via {model_name} (attempt {attempt + 1})...")
                model = genai.GenerativeModel(model_name)
                res = model.generate_content(prompt, generation_config={"temperature": 0.65})
                txt = (res.text or "").strip()
                txt = re.sub(r"^```(?:json)?", "", txt).strip()
                txt = re.sub(r"```$", "", txt).strip()
                s_i, e_i = txt.find("{"), txt.rfind("}")
                if s_i != -1 and e_i != -1:
                    txt = txt[s_i:e_i + 1]
                raw_data = json.loads(txt)
                break
            except Exception as e:
                print(f"Model {model_name} warning: {e}")
                time.sleep(2)
        if raw_data:
            break

    return validate_script_data(raw_data, topic)

def validate_script_data(data, topic):
    if not isinstance(data, dict):
        data = {}
    hook_badge, visual_subj = get_thumbnail_spec(topic["title"])
    palette = random.choice(THUMBNAIL_PALETTES)

    titles = data.get("title_options", [])
    if not isinstance(titles, list) or len(titles) < 3:
        titles = [
            f"{topic['title'][:55]}: The Hidden Root Cause & Natural Fix",
            f"What Happens to Your Body When You Fix {topic['title'][:42]}",
            f"6 Warning Signs and Natural Solutions for {topic['title'][:42]}"
        ]
    data["title_options"] = [str(t).strip()[:90] for t in titles[:3]]

    data["thumbnail_prompt"] = (
        f"Hyper-realistic 8K medical YouTube thumbnail in Dr. Eric Berg style, 16:9 landscape. "
        f"Subject: {visual_subj}, razor-sharp focus, dramatic lighting in {palette['glow']}. "
        f"Strictly NO brains or skulls. "
        f"Bold 3D typography on the left reading '{hook_badge}' in {palette['accent']} with deep black shadow, high contrast."
    )

    intro = clean_text_for_tts(data.get("intro_hook", ""))
    if len(intro.split()) < 25:
        intro = (
            f"Have you ever wondered why so many people are suddenly searching for {topic['title']}? "
            f"What if the symptom you have been brushing off as normal tiredness or aging is actually your body sending a flare signal? "
            f"In the next few minutes, we are going to uncover the exact root cause inside your cells and the simple daily steps to fix it."
        )
    data["intro_hook"] = intro

    default_roles = [
        "The Hidden Symptom & Common Myth",
        "The Real Root Cause Inside Your Body",
        "Real-Life Examples & Body Warning Signs",
        "How Your Organs & Hormones React",
        "Daily Mistakes That Make It Worse",
        "The Step-by-Step Natural Action Plan"
    ]
    raw_points = data.get("points", [])
    if not isinstance(raw_points, list):
        raw_points = []
    repaired_points = []
    for idx in range(6):
        pt = raw_points[idx] if idx < len(raw_points) and isinstance(raw_points[idx], dict) else {}
        p_title = str(pt.get("point_title") or default_roles[idx]).strip()[:52]
        p_sub = str(pt.get("point_subtitle") or f"Understanding step {idx + 1} of {topic['title'][:36]}").strip()[:68]
        paras = pt.get("paragraphs", [])
        if not isinstance(paras, list) or len(paras) < 3:
            paras = [
                f"When we examine part {idx + 1} of {topic['title']}, let us start with a real-life example you can immediately recognize. Imagine waking up after a full night of rest, yet feeling as if your cellular battery is still stuck at twenty percent because {topic['summary'][:120]}.",
                f"To understand why this happens inside your body, think of your cellular receptors like a simple kitchen sink filter. When metabolic waste or excess insulin builds up day after day, nutrients cannot flow smoothly into the tissue, creating a backup that shows up as stubborn daily discomfort.",
                f"The encouraging news is that your body responds remarkably fast once you remove the trigger and supply the right cofactor. By paying attention to meal timing, hydration, and targeted whole-food minerals, you give your organs the exact signal they need to repair."
            ]
        clean_paras = []
        for p_i in range(3):
            txt = clean_text_for_tts(paras[p_i] if p_i < len(paras) else paras[-1])
            if len(txt.split()) < 35:
                txt += f" For example, patients who address this specific mechanism consistently notice a clear difference in their daily energy, digestion, and recovery within the first two weeks."
            clean_paras.append(txt)

        repaired_points.append({
            "point_num": idx + 1,
            "point_title": p_title,
            "point_subtitle": p_sub,
            "paragraphs": clean_paras
        })
    data["points"] = repaired_points

    outro = clean_text_for_tts(data.get("outro", ""))
    if len(outro.split()) < 25:
        outro = (
            "Remember, small consistent changes to your daily routine always beat complicated temporary fixes when it comes to healing your body at the root level. "
            "If you found today's explanation helpful, please take a moment to subscribe to MedPulse 5, hit the like button, and leave a comment below sharing your experience or any question you would like us to cover next."
        )
    data["outro"] = outro

    sc = data.get("short_script", {})
    if not isinstance(sc, dict):
        sc = {}
    raw_scenes = sc.get("scenes", [])
    if not isinstance(raw_scenes, list) or len(raw_scenes) < 4:
        raw_scenes = [
            {"narration": f"Stop ignoring this sign! Right now, {topic['title']} is trending for a huge reason that directly affects your daily energy.", "portrait_query": SAFE_PORTRAIT_QUERIES[0]},
            {"narration": "Most people treat the surface symptom, but the real root cause starts deep inside your cells when key minerals and hormones fall out of balance.", "portrait_query": SAFE_PORTRAIT_QUERIES[1]},
            {"narration": "Think of it like a clogged filter in your body—until you clear the root trigger, temporary quick fixes will never give you lasting relief.", "portrait_query": SAFE_PORTRAIT_QUERIES[2]},
            {"narration": "Watch our full step-by-step guide linked right below on MedPulse 5, and please subscribe, like, and leave a comment!", "portrait_query": SAFE_PORTRAIT_QUERIES[3]}
        ]
    clean_scenes = []
    for s_i, s_obj in enumerate(raw_scenes[:4]):
        if not isinstance(s_obj, dict):
            s_obj = {}
        s_txt = clean_text_for_tts(s_obj.get("narration", ""))
        if len(s_txt.split()) < 12:
            s_txt = f"Here is the hidden truth about {topic['title']} and how you can support your body naturally starting today."
        s_q = str(s_obj.get("portrait_query") or SAFE_PORTRAIT_QUERIES[s_i % len(SAFE_PORTRAIT_QUERIES)]).strip()
        clean_scenes.append({"narration": s_txt, "portrait_query": s_q})

    data["short_script"] = {
        "short_title": str(sc.get("short_title") or f"{hook_badge}: {data['title_options'][0][:45]} #Shorts").strip(),
        "hook_badge": str(sc.get("hook_badge") or hook_badge).strip().upper()[:22],
        "scenes": clean_scenes
    }

    if not data.get("description"):
        data["description"] = f"In this comprehensive Dr. Berg style breakdown on MedPulse 5, we explore {topic['title']} with real-life examples, simple physiology, and a natural action plan."
    if not data.get("tags"):
        data["tags"] = "Dr Berg style, health trends, root cause medicine, natural remedies, vitamin deficiency, nutrition examples, MedPulse 5"
    return data

async def _edge_tts_save(text, filename, rate=VOICE_RATE):
    communicate = edge_tts.Communicate(text, VOICE_NAME, rate=rate, pitch=VOICE_PITCH)
    await communicate.save(filename)

def generate_tts(text, filename, rate=VOICE_RATE):
    clean = clean_text_for_tts(text)
    for attempt in range(4):
        try:
            asyncio.run(_edge_tts_save(clean, filename, rate=rate))
            if os.path.exists(filename) and os.path.getsize(filename) > 800:
                return True
        except Exception:
            time.sleep(2)
    return False

def make_silence_audio(duration=0.35, sr=44100):
    arr = np.zeros((int(sr * duration), 2), dtype=np.float32)
    return AudioArrayClip(arr, fps=sr).set_duration(duration)

def download_and_prepare_clip(query, norm_out_path, used_ids, orientation="landscape", target_w=W, target_h=H, target_dur=28):
    headers = {"Authorization": PEXELS_API_KEY}
    clean_q = " ".join(re.findall(r"[a-zA-Z]+", str(query))[:5])
    fallback_pool = SAFE_LANDSCAPE_QUERIES if orientation == "landscape" else SAFE_PORTRAIT_QUERIES
    candidates = [clean_q] + random.sample(fallback_pool, min(4, len(fallback_pool)))

    raw_tmp = f"{norm_out_path}_raw.mp4"
    for q in candidates:
        if not q:
            continue
        try:
            url = f"https://api.pexels.com/videos/search?query={urllib.parse.quote(q)}&per_page=18&orientation={orientation}"
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                continue
            videos = r.json().get("videos", [])
            random.shuffle(videos)
            for v in videos:
                vid_id = str(v.get("id", ""))
                dur = v.get("duration", 0)
                if not vid_id or vid_id in used_ids or dur < 5 or dur > 95:
                    continue
                v_w, v_h = v.get("width", 0) or 0, v.get("height", 0) or 0
                if orientation == "portrait" and v_w > v_h:
                    continue
                if orientation == "landscape" and v_h > v_w:
                    continue

                files = v.get("video_files", [])
                best = None
                for vf in files:
                    if vf.get("file_type") != "video/mp4":
                        continue
                    fw, fh = vf.get("width", 0) or 0, vf.get("height", 0) or 0
                    if orientation == "portrait" and fh > fw and fw >= 540:
                        best = vf
                        break
                    if orientation == "landscape" and fw > fh and fh >= 540:
                        best = vf
                        break
                if not best:
                    continue

                vr = requests.get(best["link"], stream=True, timeout=25)
                if vr.status_code == 200:
                    with open(raw_tmp, "wb") as f:
                        for chunk in vr.iter_content(chunk_size=65536):
                            if chunk:
                                f.write(chunk)
                    if os.path.exists(raw_tmp) and os.path.getsize(raw_tmp) > 50000:
                        vf_filter = (
                            f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
                            f"crop={target_w}:{target_h},"
                            f"setsar=1:1,fps={FPS},format=yuv420p"
                        )
                        cmd = [
                            "ffmpeg", "-y", "-stream_loop", "-1", "-i", raw_tmp,
                            "-t", str(int(target_dur)),
                            "-vf", vf_filter, "-an",
                            "-metadata:s:v:0", "rotate=0",
                            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
                            "-threads", "4", norm_out_path
                        ]
                        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=50)
                        if os.path.exists(raw_tmp):
                            os.remove(raw_tmp)
                        if os.path.exists(norm_out_path) and os.path.getsize(norm_out_path) > 40000:
                            used_ids.append(vid_id)
                            return True
        except Exception:
            if os.path.exists(raw_tmp):
                try:
                    os.remove(raw_tmp)
                except Exception:
                    pass
            continue
    return False

def split_into_subtitle_chunks(text, max_words=7):
    words = clean_text_for_tts(text).split()
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= max_words or (len(cur) >= 4 and w.endswith((".", "?", "!", ",", ";", ":"))):
            chunks.append(" ".join(cur))
            cur = []
    if cur:
        chunks.append(" ".join(cur))
    return chunks

def create_classic_transition_card(point_num, point_title, point_subtitle, duration=2.8):
    img = Image.new("RGB", (W, H), (10, 18, 32))
    draw = ImageDraw.Draw(img)
    for y in range(H):
        shade = int(18 + (y / H) * 18)
        draw.line([(0, y), (W, y)], fill=(10, shade, shade + 16))

    draw.rounded_rectangle([110, 185, W - 110, H - 185], radius=16, fill=(14, 26, 46), outline=(0, 205, 250), width=3)
    draw.rectangle([110, 185, 128, H - 185], fill=(0, 205, 250))

    draw.text((165, 235), f"KEY POINT 0{point_num} OF 06", font=load_font(26, True), fill=(0, 215, 255))
    draw.text((165, 295), point_title[:46], font=load_font(44, True), fill=(255, 255, 255))
    draw.text((165, 385), point_subtitle[:64], font=load_font(24, False), fill=(200, 220, 240))

    if LOGO_PIL is not None:
        img.paste(LOGO_PIL, (W - 110 - 90, 210), LOGO_PIL)

    clip = ImageClip(np.array(img)).set_duration(duration)
    sr = 44100
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    wave = (0.11 * np.sin(2 * np.pi * 528.0 * t) + 0.07 * np.sin(2 * np.pi * 660.0 * t)) * np.exp(-2.6 * t)
    chime = AudioArrayClip(np.column_stack([wave, wave]).astype(np.float32), fps=sr)
    return clip.set_audio(chime)

def render_classic_clean_frame(point_num, point_title, subtitle_text):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if LOGO_PIL is not None:
        img.paste(LOGO_PIL, (W - 64 - 24, 22), LOGO_PIL)

    if subtitle_text:
        f_sub = load_font(30, True)
        bbox = draw.textbbox((0, 0), subtitle_text, font=f_sub)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        bx1 = max(28, (W - tw) // 2 - 22)
        bx2 = min(W - 28, (W + tw) // 2 + 22)
        by1, by2 = 572, 572 + th + 24
        draw.rounded_rectangle([bx1, by1, bx2, by2], radius=12, fill=(6, 12, 22, 228), outline=(0, 210, 255, 185), width=2)
        tx, ty = (W - tw) // 2, by1 + 10
        draw.text((tx + 2, ty + 2), subtitle_text, font=f_sub, fill=(0, 0, 0, 255))
        draw.text((tx, ty), subtitle_text, font=f_sub, fill=(255, 248, 145, 255))

    bar_y = 656
    draw.rectangle([0, bar_y, W, H], fill=(8, 15, 28, 225))
    draw.rectangle([0, bar_y, W, bar_y + 3], fill=(0, 210, 255, 255))
    badge_label = f"POINT 0{point_num}" if point_num > 0 else "MEDPULSE 5"
    draw.rounded_rectangle([24, bar_y + 13, 175, bar_y + 50], radius=6, fill=(0, 185, 235, 255))
    draw.text((38, bar_y + 20), badge_label, font=load_font(19, True), fill=(8, 15, 28, 255))
    draw.text((195, bar_y + 19), point_title[:58], font=load_font(23, True), fill=(245, 250, 255, 255))
    return np.array(img)

def build_classic_overlay_track(point_num, point_title, narration_text, total_duration):
    chunks = split_into_subtitle_chunks(narration_text, max_words=7)
    if not chunks:
        return ImageClip(render_classic_clean_frame(point_num, point_title, "")).set_duration(total_duration)
    char_lengths = [max(len(c), 4) for c in chunks]
    total_chars = sum(char_lengths)
    clips, elapsed = [], 0.0
    for idx, chunk in enumerate(chunks):
        dur = max(0.15, total_duration - elapsed) if idx == len(chunks) - 1 else max(0.25, total_duration * (char_lengths[idx] / total_chars))
        elapsed += dur
        clips.append(ImageClip(render_classic_clean_frame(point_num, point_title, chunk)).set_duration(dur))
    return concatenate_videoclips(clips).set_duration(total_duration)

def render_true_short_overlay_frame(hook_badge, subtitle_text):
    img = Image.new("RGBA", (SHORT_W, SHORT_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle([32, 58, SHORT_W - 110, 122], radius=14, fill=(8, 16, 30, 215), outline=(0, 215, 255, 230), width=2)
    draw.text((52, 76), f"MEDPULSE 5  |  {hook_badge[:18]}", font=load_font(22, True), fill=(0, 230, 255, 255))

    if LOGO_SHORT_PIL is not None:
        img.paste(LOGO_SHORT_PIL, (SHORT_W - 54 - 24, 58), LOGO_SHORT_PIL)

    if subtitle_text:
        f_sub = load_font(34, True)
        words = subtitle_text.split()
        mid = max(1, len(words) // 2)
        lines = [" ".join(words[:mid]), " ".join(words[mid:])] if len(words) > 4 else [subtitle_text]
        sy1 = 920
        sy2 = sy1 + len(lines) * 48 + 28
        draw.rounded_rectangle([36, sy1, SHORT_W - 36, sy2], radius=16, fill=(6, 12, 22, 225), outline=(255, 225, 70, 235), width=3)
        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=f_sub)
            tw = bbox[2] - bbox[0]
            tx, ty = (SHORT_W - tw) // 2, sy1 + 12 + i * 46
            draw.text((tx + 2, ty + 2), line, font=f_sub, fill=(0, 0, 0, 255))
            draw.text((tx, ty), line, font=f_sub, fill=(255, 248, 120, 255))

    draw.rounded_rectangle([40, SHORT_H - 110, SHORT_W - 40, SHORT_H - 48], radius=12, fill=(8, 16, 30, 225), outline=(0, 210, 255, 220), width=2)
    draw.text((68, SHORT_H - 90), "WATCH FULL VIDEO & SUBSCRIBE TO MEDPULSE 5", font=load_font(21, True), fill=(255, 255, 255, 255))
    return np.array(img)

def build_true_short_overlay_track(hook_badge, narration_text, total_duration):
    chunks = split_into_subtitle_chunks(narration_text, max_words=5)
    if not chunks:
        return ImageClip(render_true_short_overlay_frame(hook_badge, "")).set_duration(total_duration)
    char_lengths = [max(len(c), 3) for c in chunks]
    total_chars = sum(char_lengths)
    clips, elapsed = [], 0.0
    for idx, chunk in enumerate(chunks):
        dur = max(0.15, total_duration - elapsed) if idx == len(chunks) - 1 else max(0.25, total_duration * (char_lengths[idx] / total_chars))
        elapsed += dur
        clips.append(ImageClip(render_true_short_overlay_frame(hook_badge, chunk)).set_duration(dur))
    return concatenate_videoclips(clips).set_duration(total_duration)

def generate_ambient_music(duration, sr=44100):
    chunk_len = 10.0
    t = np.linspace(0, chunk_len, int(sr * chunk_len), endpoint=False)
    wave = (0.30 * np.sin(2 * np.pi * 110.0 * t) + 0.20 * np.sin(2 * np.pi * 164.81 * t) + 0.15 * np.sin(2 * np.pi * 220.0 * t))
    cycle = (wave * 0.030).astype(np.float32)
    stereo = np.column_stack([cycle, cycle])
    repeats = int(math.ceil(duration / chunk_len)) + 1
    full_arr = np.tile(stereo, (repeats, 1))[:int(sr * duration)]
    return AudioArrayClip(full_arr, fps=sr).set_duration(duration)

def build_paragraph_video_segment(point_num, point_title, p_text, v_query, seg_tag, used_videos, open_resources):
    tts_path = f"temp/{seg_tag}.mp3"
    if not generate_tts(p_text, tts_path):
        return None
    raw_a = AudioFileClip(tts_path)
    open_resources.append(raw_a)
    safe_v_dur = max(0.3, raw_a.duration - 0.06)
    paused_audio = concatenate_audioclips([raw_a.subclip(0, safe_v_dur), make_silence_audio(0.38)])
    seg_dur = paused_audio.duration

    norm_vid_path = f"temp/{seg_tag}_hd.mp4"
    target_prep_dur = int(math.ceil(seg_dur)) + 4
    ok = download_and_prepare_clip(
        v_query, norm_vid_path, used_videos,
        orientation="landscape", target_w=W, target_h=H, target_dur=target_prep_dur
    )
    if ok and os.path.exists(norm_vid_path):
        v_clip = VideoFileClip(norm_vid_path).without_audio()
        open_resources.append(v_clip)
        bg_clip = v_clip.subclip(0, min(seg_dur, v_clip.duration)).set_duration(seg_dur)
    else:
        bg_clip = ColorClip(size=(W, H), color=(12, 24, 42), duration=seg_dur)

    ov_track = build_classic_overlay_track(point_num, point_title, p_text, seg_dur)
    return CompositeVideoClip([bg_clip, ov_track], size=(W, H)).set_duration(seg_dur).set_audio(paused_audio)

def build_companion_short(script_data, used_videos):
    print("Building Full-Screen 9:16 Native Portrait YouTube Short (Zero Stretching)...")
    sc = script_data["short_script"]
    hook_badge = sc["hook_badge"]
    scenes = sc["scenes"]
    short_segments, open_res = [], []

    for idx, scene in enumerate(scenes[:4]):
        s_text = scene["narration"]
        p_query = scene["portrait_query"]
        tts_p = f"temp/short_s{idx}.mp3"
        if not generate_tts(s_text, tts_p, rate="-2%"):
            continue
        raw_a = AudioFileClip(tts_p)
        open_res.append(raw_a)
        safe_d = max(0.3, raw_a.duration - 0.06)
        voice_a = concatenate_audioclips([raw_a.subclip(0, safe_d), make_silence_audio(0.25)])
        seg_d = voice_a.duration

        norm_v = f"temp/short_v{idx}_9x16.mp4"
        ok = download_and_prepare_clip(
            p_query, norm_v, used_videos,
            orientation="portrait", target_w=SHORT_W, target_h=SHORT_H,
            target_dur=int(math.ceil(seg_d)) + 4
        )
        if ok and os.path.exists(norm_v):
            vc = VideoFileClip(norm_v).without_audio()
            open_res.append(vc)
            bg_v = vc.subclip(0, min(seg_d, vc.duration)).set_duration(seg_d)
        else:
            bg_v = ColorClip(size=(SHORT_W, SHORT_H), color=(10, 20, 36), duration=seg_d)

        ov_v = build_true_short_overlay_track(hook_badge, s_text, seg_d)
        comp = CompositeVideoClip([bg_v, ov_v], size=(SHORT_W, SHORT_H)).set_duration(seg_d).set_audio(voice_a)
        short_segments.append(comp)

    if not short_segments:
        return False
    final_short = concatenate_videoclips(short_segments, method="compose")
    if final_short.duration > 58.0:
        final_short = final_short.subclip(0, 58.0)
    bg_m = generate_ambient_music(final_short.duration)
    final_short = final_short.set_audio(CompositeAudioClip([final_short.audio, bg_m]))
    final_short.write_videofile("output/short_video.mp4", fps=FPS, codec="libx264", audio_codec="aac", preset="ultrafast", threads=4, logger=None)
    for r in open_res:
        try:
            r.close()
        except Exception:
            pass
    print(f"Native 9:16 YouTube Short Ready: output/short_video.mp4 ({final_short.duration:.1f}s)")
    return True

def main():
    if not GEMINI_API_KEY or not PEXELS_API_KEY:
        raise RuntimeError("Missing GEMINI_API_KEY or PEXELS_API_KEY!")
    used_videos = load_used_items(USED_VIDEOS_FILE)
    used_news = load_used_items(USED_NEWS_FILE)

    topic = fetch_live_google_trend_topic()
    script_data = generate_dr_berg_masterclass_script(topic)

    final_segments, open_resources = [], []
    timestamps = ["00:00 - Thrilling Introduction"]
    t_cursor = 0.0

    print("Building Thrilling Intro Hook...")
    intro_q = pick_visual_queries_for_text(script_data["intro_hook"], count=1)[0]
    intro_seg = build_paragraph_video_segment(
        0, script_data["title_options"][0], script_data["intro_hook"],
        intro_q, "intro_hook", used_videos, open_resources
    )
    if intro_seg is not None:
        final_segments.append(intro_seg)
        t_cursor += intro_seg.duration

    for pt in script_data["points"]:
        p_num = pt["point_num"]
        p_title = pt["point_title"]
        p_sub = pt["point_subtitle"]
        paras = pt["paragraphs"]

        mm, ss = int(t_cursor // 60), int(t_cursor % 60)
        timestamps.append(f"{mm:02d}:{ss:02d} - Point {p_num}: {p_title}")
        print(f"Building Point {p_num}/6: {p_title}")

        card = create_classic_transition_card(p_num, p_title, p_sub, duration=2.8)
        final_segments.append(card)
        t_cursor += card.duration

        queries = pick_visual_queries_for_text(" ".join(paras), count=3)
        for p_idx, p_text in enumerate(paras):
            v_q = queries[p_idx % len(queries)]
            seg_tag = f"pt{p_num}_p{p_idx + 1}"
            seg_clip = build_paragraph_video_segment(
                p_num, p_title, p_text, v_q, seg_tag, used_videos, open_resources
            )
            if seg_clip is not None:
                final_segments.append(seg_clip)
                t_cursor += seg_clip.duration

    print("Building Warm Polite Outro...")
    outro_seg = build_paragraph_video_segment(
        0, "SUBSCRIBE, COMMENT & LIKE  |  MEDPULSE 5", script_data["outro"],
        "doctor consulting patient in bright clinic", "outro_warm", used_videos, open_resources
    )
    if outro_seg is not None:
        final_segments.append(outro_seg)
        t_cursor += outro_seg.duration

    full_video = concatenate_videoclips(final_segments, method="compose")
    print(f"Final Natural Dr. Berg Masterclass Duration: {full_video.duration / 60.0:.2f} minutes ({full_video.duration:.1f}s)")
    ambient = generate_ambient_music(full_video.duration)
    full_video = full_video.set_audio(CompositeAudioClip([full_video.audio, ambient]))
    full_video.write_videofile("output/final_video.mp4", fps=FPS, codec="libx264", audio_codec="aac", preset="ultrafast", threads=4, logger=None)

    try:
        build_companion_short(script_data, used_videos)
    except Exception as e:
        print(f"Short generation warning: {e}")

    ar_h1 = "=== \u0627\u0644\u0639\u0646\u0627\u0648\u064a\u0646 \u0627\u0644\u0645\u0642\u062a\u0631\u062d\u0629 (\u062a\u0631\u0646\u062f \u0627\u0644\u0628\u062d\u062b \u0627\u0644\u062d\u064a \u0628\u0623\u0633\u0644\u0648\u0628 \u062f\u0643\u062a\u0648\u0631 \u0628\u064a\u0631\u062c) ==="
    ar_opt1 = "\u0627\u0644\u062e\u064a\u0627\u0631 1 (\u0645\u0648\u0635\u0649 \u0628\u0647): "
    ar_opt2 = "\u0627\u0644\u062e\u064a\u0627\u0631 2: "
    ar_opt3 = "\u0627\u0644\u062e\u064a\u0627\u0631 3: "
    ar_h2 = "=== \u0648\u0635\u0641 \u0627\u0644\u0635\u0648\u0631\u0629 \u0627\u0644\u0645\u0635\u063a\u0631\u0629 (Thumbnail Prompt - Landscape 16:9) ==="
    ar_h3 = "=== \u0639\u0646\u0648\u0627\u0646 \u0648\u0648\u0635\u0641 \u0627\u0644\u0641\u064a\u062f\u064a\u0648 \u0627\u0644\u0642\u0635\u064a\u0631 \u0627\u0644\u0645\u0631\u0641\u0642 (YouTube Short) ==="
    ar_h4 = "=== \u0635\u0646\u062f\u0648\u0642 \u0627\u0644\u0648\u0635\u0641 \u0627\u0644\u0643\u0627\u0645\u0644 \u0644\u0644\u0641\u064a\u062f\u064a\u0648 \u0627\u0644\u0637\u0648\u064a\u0644 ==="
    ar_h5 = "=== \u0627\u0644\u0643\u0644\u0645\u0627\u062a \u0627\u0644\u0645\u0641\u062a\u0627\u062d\u064a\u0629 (Tags) ==="

    details_lines = [
        ar_h1,
        f"{ar_opt1}{script_data['title_options'][0]}",
        f"{ar_opt2}{script_data['title_options'][1]}",
        f"{ar_opt3}{script_data['title_options'][2]}",
        "",
        ar_h2,
        script_data["thumbnail_prompt"],
        "",
        ar_h3,
        f"Short Title: {script_data['short_script']['short_title']}",
        f"Short Description: Watch the full deep dive on MedPulse 5: {script_data['title_options'][0]} #Shorts #Health #NaturalRemedies #Nutrition",
        "",
        ar_h4,
        script_data["description"],
        "",
        "Video Chapters:",
        *timestamps,
        "",
        f"Trending Search Reference: {topic['title']}",
        "Educational Disclaimer: This video is for informational and educational purposes only and does not substitute personal medical advice.",
        "",
        ar_h5,
        script_data["tags"]
    ]
    with open("output/youtube_details.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(details_lines))

    used_news.append(topic["norm_key"])
    save_used_items(USED_NEWS_FILE, used_news)
    save_used_items(USED_VIDEOS_FILE, used_videos)

    for r in open_resources:
        try:
            r.close()
        except Exception:
            pass
    print("ALL DONE! Live Trend Dr. Berg Video + True 9:16 Short Ready.")

if __name__ == "__main__":
    main()
