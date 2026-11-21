import os, re, json, math, time, random, asyncio, subprocess, urllib.parse
from datetime import datetime
import requests, feedparser, edge_tts, numpy as np
from PIL import Image, ImageDraw, ImageFont
import PIL.Image

if not hasattr(PIL.Image, "ANTIALIAS"):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS

from google import genai
from google.genai import types
from moviepy.editor import (
    VideoFileClip, AudioFileClip, ImageClip, ColorClip,
    CompositeVideoClip, CompositeAudioClip, concatenate_videoclips
)
from moviepy.audio.AudioClip import AudioArrayClip

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "").strip()

W, H = 1280, 720
SHORT_W, SHORT_H = 720, 1280
FPS = 24
VOICE_NAME = "en-US-ChristopherNeural"
VOICE_RATE = "+3%"
VOICE_PITCH = "-1Hz"

USED_VIDEOS_FILE = "used_videos.txt"
USED_NEWS_FILE = "used_news.txt"
LOGO_PATH = "\u062a\u0646\u0632\u064a\u0644.jpeg"

os.makedirs("temp", exist_ok=True)
os.makedirs("output", exist_ok=True)

CHAPTER_ROLE_TITLES = [
    "The Hidden Truth Behind The Headline",
    "What The New Clinical Study Shows",
    "How It Works Inside Your Body",
    "Hidden Risks & Mistakes To Avoid",
    "The Doctor's Practical Action Plan"
]

RSS_FEEDS = [
    "https://news.google.com/rss/search?q=new+medication+OR+clinical+trial+OR+FDA+approval+health+when:2d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=vitamin+OR+supplement+OR+deficiency+study+health+when:2d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=fatty+liver+OR+kidney+OR+heart+disease+breakthrough+study+when:2d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=diabetes+OR+blood+sugar+OR+insulin+OR+weight+loss+drug+study+when:2d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=blood+pressure+OR+cholesterol+OR+arteries+treatment+study+when:2d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=gut+microbiome+OR+inflammation+OR+autoimmune+clinical+study+when:2d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=sleep+apnea+OR+insomnia+OR+chronic+fatigue+medical+study+when:2d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=longevity+OR+anti+aging+OR+metabolism+clinical+trial+when:2d&hl=en-US&gl=US&ceid=US:en",
    "https://www.drugs.com/feeds/medical_news.xml",
    "https://www.drugs.com/feeds/new_drugs.xml",
    "https://www.drugs.com/feeds/fda_alerts.xml",
    "https://newsnetwork.mayoclinic.org/feed/",
    "https://www.health.harvard.edu/blog/feed",
    "https://health.clevelandclinic.org/feed/",
    "https://www.medpagetoday.com/rss/headlines.xml",
    "https://scitechdaily.com/tag/health/feed/",
    "https://scitechdaily.com/tag/medicine/feed/",
    "https://medicalxpress.com/rss-feed/",
    "https://www.news-medical.net/syndication.axd?format=rss",
    "https://www.sciencedaily.com/rss/health_medicine.xml",
    "https://www.eurekalert.org/rss/medicine_health.xml",
    "https://www.nih.gov/news-events/feed.xml",
    "https://rss.medicalnewstoday.com/featurednews.xml",
    "https://www.healthline.com/rss/health-news"
]

VIRAL_MEDICAL_KEYWORDS = [
    ("medication", 5), ("drug", 5), ("pill", 5), ("fda", 5), ("approval", 4),
    ("side effect", 5), ("warning", 4), ("recall", 4), ("vitamin", 5), ("supplement", 5),
    ("magnesium", 5), ("vitamin d", 5), ("b12", 5), ("omega", 4), ("creatine", 4),
    ("collagen", 4), ("probiotic", 4), ("ozempic", 5), ("glp-1", 5), ("semaglutide", 5),
    ("statin", 5), ("metformin", 5), ("ibuprofen", 5), ("painkiller", 5), ("antibiotic", 4),
    ("blood pressure", 5), ("hypertension", 4), ("cholesterol", 5), ("artery", 4), ("plaque", 4),
    ("heart attack", 5), ("stroke", 5), ("diabetes", 5), ("blood sugar", 5), ("insulin", 5),
    ("fatty liver", 5), ("liver", 4), ("kidney", 5), ("gut", 4), ("microbiome", 4),
    ("inflammation", 4), ("arthritis", 4), ("joint pain", 4), ("thyroid", 4), ("metabolism", 4),
    ("visceral fat", 5), ("weight loss", 4), ("longevity", 4), ("clinical trial", 4), ("study", 3),
    ("doctors", 4), ("patients", 3), ("reversal", 5), ("damage", 4), ("repair", 4)
]

SAFE_MEDICAL_QUERIES = [
    "doctor explaining medical test results to patient clinic",
    "pharmacist checking prescription medication bottles pharmacy",
    "close up medicine pills capsules on laboratory table",
    "scientist examining blood sample tube in medical lab",
    "doctor checking patient blood pressure in hospital room",
    "medical researcher looking through microscope laboratory",
    "surgeon team monitoring vital signs screen hospital",
    "senior patient taking daily vitamin pill with water",
    "cardiologist examining heart scan on computer monitor",
    "clinical trial researcher analyzing data on tablet",
    "healthy fresh food vegetables and supplements on table",
    "doctor writing prescription notes in modern clinic",
    "laboratory technician pipetting liquid into test tubes",
    "female doctor consulting patient in bright office",
    "medical animation style laboratory equipment close up",
    "hospital corridor doctors walking in scrubs"
]

KEYWORD_VISUAL_MAP = [
    (["pill", "medication", "drug", "capsule", "prescription", "dose", "tablet", "statin", "metformin"], "close up prescription medicine pills capsules pharmacy"),
    (["vitamin", "supplement", "magnesium", "omega", "nutrient", "deficiency"], "vitamin supplement capsules and healthy nutrition on table"),
    (["heart", "cardiac", "artery", "plaque", "cholesterol", "blood pressure", "hypertension", "stroke"], "cardiologist checking heart monitor and blood pressure patient"),
    (["liver", "fatty liver", "hepatic", "detox", "enzyme", "bile"], "doctor examining abdominal ultrasound scan on medical monitor"),
    (["kidney", "renal", "filtration", "urine", "creatinine", "hydration"], "medical specialist reviewing kidney scan and lab test results"),
    (["diabetes", "blood sugar", "glucose", "insulin", "pancreas", "a1c", "metabolic"], "patient checking blood sugar glucose meter with doctor"),
    (["gut", "microbiome", "digestion", "stomach", "intestine", "bloating", "probiotic"], "nutritionist doctor explaining healthy diet and digestion"),
    (["sleep", "insomnia", "circadian", "melatonin", "fatigue", "tired"], "person sleeping peacefully in bedroom night rest health"),
    (["joint", "arthritis", "inflammation", "pain", "muscle", "bone", "ache"], "physical therapist doctor examining patient knee joint pain"),
    (["blood", "cell", "immune", "antibody", "infection", "virus", "plasma"], "scientist analyzing blood sample tube in medical laboratory"),
    (["study", "trial", "research", "scientist", "data", "journal", "evidence"], "medical researcher looking through microscope in clinical lab"),
    (["warning", "risk", "mistake", "side effect", "danger", "avoid", "toxic"], "pharmacist doctor reading medication warning label carefully"),
    (["diet", "food", "eat", "meal", "vegetable", "protein", "fasting", "sugar"], "healthy fresh vegetables and whole foods on kitchen table"),
    (["exercise", "walk", "activity", "fitness", "strength", "weight"], "active adult walking outdoors healthy lifestyle exercise"),
    (["doctor", "physician", "clinic", "patient", "advice", "checkup", "test"], "doctor consulting patient and explaining medical chart")
]

THUMBNAIL_PALETTES = [
    {"name": "Cyan-Amber", "glow": "electric cyan and warm amber", "accent": "bright yellow"},
    {"name": "Emerald-Gold", "glow": "emerald green and golden yellow", "accent": "crisp white"},
    {"name": "Crimson-Ice", "glow": "deep crimson red and icy blue", "accent": "neon yellow"},
    {"name": "Cobalt-Coral", "glow": "cobalt blue and vibrant coral orange", "accent": "bright white"},
    {"name": "Teal-Ruby", "glow": "clinical teal and ruby red", "accent": "warm gold"}
]

STOP_WORDS = {
    "about", "after", "again", "against", "among", "because", "before", "being",
    "between", "both", "could", "doctors", "during", "early", "every", "found",
    "from", "health", "helps", "human", "into", "large", "level", "levels",
    "linked", "lower", "makes", "medical", "might", "more", "newly", "other",
    "people", "patients", "research", "researchers", "results", " reveals",
    "scientist", "scientists", "shows", "shown", "small", "study", "studies",
    "their", "there", "these", "those", "through", "treatment", "under",
    "using", "while", "without", "would", "years", "clinical", "trial"
}

def load_Circular_Logo(path, size=68):
    if not os.path.exists(path):
        return None
    try:
        img = Image.open(path).convert("RGBA").resize((size, size), Image.LANCZOS)
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
        out = Image.new("RGBA", (size + 8, size + 8), (0, 0, 0, 0))
        ImageDraw.Draw(out).ellipse((0, 0, size + 7, size + 7), fill=(0, 210, 255, 230), outline=(255, 255, 255, 240), width=2)
        out.paste(img, (4, 4), mask)
        return out
    except Exception:
        return None

LOGO_PIL = load_Circular_Logo(LOGO_PATH, size=68)
LOGO_SHORT_PIL = load_Circular_Logo(LOGO_PATH, size=56)

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

def load_used_items(filepath, max_keep=500):
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    return lines[-max_keep:]

def save_used_items(filepath, items, max_keep=500):
    trimmed = items[-max_keep:]
    with open(filepath, "w", encoding="utf-8") as f:
        for item in trimmed:
            f.write(f"{item}\n")

def clean_text_for_tts(text):
    text = re.sub(r"[*_#`~>]", " ", str(text))
    text = re.sub(r"\s+", " ", text).strip()
    return text

def score_viral_medical_appeal(title, summary):
    combined = f"{title} {summary}".lower()
    score = 0
    for kw, weight in VIRAL_MEDICAL_KEYWORDS:
        if kw in combined:
            score += weight
    if any(w in combined for w in ["political", "lawsuit", "senate", "stock", "market", "ceo", "insurance policy"]):
        score -= 15
    if any(w in combined for w in ["brain implant", "telepathy", "neuralink"]):
        score -= 8
    return score

def fetch_viral_trending_topic():
    print("Scanning 24 Global Health & Viral Medical Trend Feeds...")
    used_news = set(load_used_items(USED_NEWS_FILE))
    candidates = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    for url in RSS_FEEDS:
        try:
            resp = requests.get(url, headers=headers, timeout=12)
            if resp.status_code != 200:
                continue
            feed = feedparser.parse(resp.content)
            for entry in feed.entries[:18]:
                title = re.sub(r"<[^>]+>", "", entry.get("title", "")).strip()
                if " - " in title and len(title.split(" - ")[0]) > 25:
                    title = " - ".join(title.split(" - ")[:-1]).strip()
                link = entry.get("link", "").strip()
                summary = re.sub(r"<[^>]+>", " ", entry.get("summary", entry.get("description", ""))).strip()
                summary = re.sub(r"\s+", " ", summary)[:450]
                if not title or len(title) < 22:
                    continue
                norm_key = re.sub(r"[^a-z0-9]", "", title.lower())[:65]
                if norm_key in used_news or link in used_news:
                    continue
                appeal = score_viral_medical_appeal(title, summary)
                candidates.append({"title": title, "summary": summary, "link": link, "norm_key": norm_key, "appeal": appeal})
        except Exception:
            continue

    word_freq = {}
    for c in candidates:
        words = set(re.findall(r"[a-z]{5,}", c["title"].lower())) - STOP_WORDS
        for w in words:
            word_freq[w] = word_freq.get(w, 0) + 1

    for c in candidates:
        words = set(re.findall(r"[a-z]{5,}", c["title"].lower())) - STOP_WORDS
        trend_bonus = sum(min(word_freq.get(w, 0), 6) * 2 for w in words if word_freq.get(w, 0) >= 2)
        c["total_score"] = c["appeal"] + trend_bonus

    candidates.sort(key=lambda x: x["total_score"], reverse=True)
    deduped, seen_titles = [], set()
    for c in candidates:
        short_k = c["norm_key"][:40]
        if short_k not in seen_titles:
            seen_titles.add(short_k)
            deduped.append(c)

    if not deduped:
        return {
            "title": "New Clinical Findings on Daily Magnesium, Vitamin D, and Metabolic Organ Protection",
            "summary": "Researchers investigating daily supplementation and prescription metabolic therapies uncovered critical mechanisms affecting blood vessels, liver fat, and cellular energy.",
            "link": "https://www.nih.gov",
            "norm_key": f"fallback_{int(time.time())}",
            "corroborating_angles": []
        }

    top_story = deduped[0]
    top_words = set(re.findall(r"[a-z]{5,}", top_story["title"].lower())) - STOP_WORDS
    related = []
    for c in deduped[1:25]:
        c_words = set(re.findall(r"[a-z]{5,}", c["title"].lower())) - STOP_WORDS
        if len(top_words & c_words) >= 1 and len(related) < 3:
            related.append(f"{c['title']} ({c['summary'][:160]})")
    top_story["corroborating_angles"] = related
    print(f"Selected #1 Viral Medical Topic: {top_story['title']} (Score: {top_story['total_score']})")
    return top_story

def get_matched_thumbnail_hook(topic_text):
    t = topic_text.lower()
    if any(w in t for w in ["vitamin", "supplement", "magnesium", "omega", "b12", "vitamin d"]):
        return "THE VITAMIN TRUTH", "a glowing translucent vitamin capsule beside a clinical laboratory vial and heart rate monitor"
    if any(w in t for w in ["pill", "medication", "drug", "fda", "statin", "metformin", "ozempic", "glp-1", "painkiller", "ibuprofen"]):
        return "DOCTORS WARN NOW", "a high-detail prescription pill bottle spilling luminous capsules onto a sleek clinical desk next to a stethoscope"
    if any(w in t for w in ["liver", "fatty liver", "kidney", "renal", "hepatic"]):
        return "ORGAN REPAIR SHOCK", "an anatomical 3D glass-like glowing human torso highlighting the liver and kidneys in a modern diagnostics lab"
    if any(w in t for w in ["heart", "artery", "plaque", "cholesterol", "blood pressure", "hypertension", "stroke"]):
        return "CLEARS ARTERIES?", "a cinematic macro cross-section of a glowing human artery and a high-tech cardiology monitor"
    if any(w in t for w in ["diabetes", "blood sugar", "insulin", "glucose", "metabolism", "weight"]):
        return "BLOOD SUGAR TRUTH", "a futuristic digital glucose monitor displaying a sharp metabolic drop beside glowing red blood cells"
    if any(w in t for w in ["gut", "microbiome", "inflammation", "autoimmune", "arthritis"]):
        return "HIDDEN GUT LINK", "a glowing medical visualization of the human digestive tract and cellular shield in a dark clinical studio"
    return "MEDICAL BREAKTHROUGH", "a dramatic clinical close-up of a glowing medical vial, prescription capsule, and diagnostic monitor"

def build_harmonized_visual_queries(narration_text, base_query=""):
    sentences = [s.strip() for s in re.split(r"[.!?]+", narration_text) if len(s.strip()) > 10]
    queries = []
    for s in sentences:
        s_low = s.lower()
        matched_q = None
        for kw_list, pexels_q in KEYWORD_VISUAL_MAP:
            if any(k in s_low for k in kw_list):
                matched_q = pexels_q
                break
        if matched_q and matched_q not in queries:
            queries.append(matched_q)
    if base_query:
        clean_base = re.sub(r"[^a-zA-Z0-9 ]", " ", base_query).strip()
        if clean_base and clean_base not in queries:
            queries.insert(0, clean_base)
    pool = SAFE_MEDICAL_QUERIES[:]
    random.shuffle(pool)
    for pq in pool:
        if len(queries) >= 4:
            break
        if pq not in queries:
            queries.append(pq)
    return queries[:4]

def clamp_act_words(text, min_words=66, max_words=73):
    text = clean_text_for_tts(text)
    words = text.split()
    if len(words) > max_words:
        trimmed = " ".join(words[:max_words])
        last_dot = max(trimmed.rfind("."), trimmed.rfind("?"), trimmed.rfind("!"))
        if last_dot > int(len(trimmed) * 0.72):
            return trimmed[:last_dot + 1].strip()
        return trimmed.rstrip(",;:-") + "."
    pad_sentences = [
        "Clinicians emphasize that tracking these measurable biological markers early gives patients a major advantage in long-term prevention.",
        "Understanding how your body processes this at the cellular level helps you ask sharper questions during your next checkup.",
        "Researchers note that consistent daily habits and evidence-based monitoring make the biggest difference in real clinical outcomes."
    ]
    idx = 0
    while len(text.split()) < min_words:
        text = text.strip() + " " + pad_sentences[idx % len(pad_sentences)]
        idx += 1
    words = text.split()
    if len(words) > max_words:
        trimmed = " ".join(words[:max_words])
        last_dot = max(trimmed.rfind("."), trimmed.rfind("?"), trimmed.rfind("!"))
        if last_dot > int(len(trimmed) * 0.72):
            return trimmed[:last_dot + 1].strip()
        return trimmed.rstrip(",;:-") + "."
    return text

def split_into_subtitle_chunks(text, max_words=7):
    words = clean_text_for_tts(text).split()
    if not words:
        return []
    chunks, current = [], []
    for w in words:
        current.append(w)
        if len(current) >= max_words or (len(current) >= 4 and w.endswith((".", "?", "!", ",", ";", ":"))):
            chunks.append(" ".join(current))
            current = []
    if current:
        chunks.append(" ".join(current))
    return chunks

def validate_and_repair_script_data(data, topic):
    if not isinstance(data, dict):
        data = {}
    hook_text, visual_subject = get_matched_thumbnail_hook(topic["title"])
    palette = random.choice(THUMBNAIL_PALETTES)

    titles = data.get("title_options", [])
    if not isinstance(titles, list) or len(titles) < 3:
        titles = [
            f"Doctors Warn: The Hidden Truth About {topic['title'][:48]}",
            f"New Clinical Study Changes Everything About {topic['title'][:45]}",
            f"Before You Ignore This Medical Warning, Watch the Data"
        ]
    titles = [str(t).strip()[:95] for t in titles[:3]]
    data["title_options"] = titles

    data["thumbnail_prompt"] = (
        f"Hyper-realistic 8K cinematic medical YouTube thumbnail in Leonid Kim MD style, 16:9 aspect ratio. "
        f"Foreground subject: {visual_subject}, razor-sharp focus, dramatic studio rim lighting in {palette['glow']} tones. "
        f"Strictly NO human brains or glowing skulls. "
        f"Bold 3D metallic typography on the left side reading '{hook_text}' in {palette['accent']} font with heavy dark drop shadow, high contrast, ultra-clickable."
    )

    data["intro_hook"] = clamp_act_words(
        data.get("intro_hook", f"Have you seen the headlines about {topic['title']}? Millions of patients are asking whether this new medical finding is a genuine breakthrough or another misunderstood trend. Today we are looking directly at the clinical data."),
        min_words=52, max_words=62
    )
    data["outro"] = clamp_act_words(
        data.get("outro", "If you found this clinical breakdown helpful, subscribe to MedPulse 5 and share this episode with someone you care about. Always discuss new research or medication changes with your personal physician."),
        min_words=42, max_words=52
    )

    raw_chapters = data.get("chapters", [])
    repaired_chapters = []
    for idx in range(5):
        ch_raw = raw_chapters[idx] if idx < len(raw_chapters) and isinstance(raw_chapters[idx], dict) else {}
        ch_title = str(ch_raw.get("chapter_title", CHAPTER_ROLE_TITLES[idx])).strip()
        if len(ch_title) < 6 or len(ch_title) > 58:
            ch_title = CHAPTER_ROLE_TITLES[idx]
        for k in ["act1_hook", "act2_science", "act3_impact", "act4_takeaway"]:
            ch_raw[k] = clamp_act_words(
                ch_raw.get(k, f"In chapter {idx + 1}, clinical investigators examined how {topic['title']} directly influences patient outcomes and cellular health."),
                min_words=66, max_words=73
            )
        repaired_chapters.append({
            "chapter_title": ch_title,
            "act1_hook": ch_raw["act1_hook"],
            "act2_science": ch_raw["act2_science"],
            "act3_impact": ch_raw["act3_impact"],
            "act4_takeaway": ch_raw["act4_takeaway"],
            "search_query_1": str(ch_raw.get("search_query_1", SAFE_MEDICAL_QUERIES[(idx * 3) % len(SAFE_MEDICAL_QUERIES)])),
            "search_query_2": str(ch_raw.get("search_query_2", SAFE_MEDICAL_QUERIES[(idx * 3 + 1) % len(SAFE_MEDICAL_QUERIES)])),
            "search_query_3": str(ch_raw.get("search_query_3", SAFE_MEDICAL_QUERIES[(idx * 3 + 2) % len(SAFE_MEDICAL_QUERIES)])),
            "search_query_4": str(ch_raw.get("search_query_4", SAFE_MEDICAL_QUERIES[(idx * 3 + 3) % len(SAFE_MEDICAL_QUERIES)]))
        })
    data["chapters"] = repaired_chapters

    short_data = data.get("short_script", {})
    if not isinstance(short_data, dict):
        short_data = {}
    data["short_script"] = {
        "short_title": str(short_data.get("short_title", f"{hook_text}: {titles[0][:45]} #Shorts")).strip(),
        "hook_banner": hook_text,
        "part1_hook": clean_text_for_tts(short_data.get("part1_hook", f"Stop scrolling if you care about your health. A major clinical finding just exposed the truth about {topic['title']}.")),
        "part2_reveal": clean_text_for_tts(short_data.get("part2_reveal", "Researchers discovered that what happens inside your blood vessels and vital organs is very different from what most headlines claim.")),
        "part3_cta": clean_text_for_tts(short_data.get("part3_cta", "Watch our full 9-minute clinical breakdown linked right below on MedPulse 5 to see the exact study and action plan.")),
        "visual_query_1": str(short_data.get("visual_query_1", "close up prescription medicine pills capsules pharmacy")),
        "visual_query_2": str(short_data.get("visual_query_2", "scientist analyzing blood sample tube in medical laboratory")),
        "visual_query_3": str(short_data.get("visual_query_3", "doctor consulting patient and explaining medical chart"))
    }
    if not data.get("description"):
        data["description"] = f"In this episode of MedPulse 5, we do a deep clinical investigation into {topic['title']}."
    if not data.get("tags"):
        data["tags"] = "evidence based medicine, clinical study explained, medication truth, vitamin science, doctor explains, health breakthrough, medpulse 5"
    return data

def generate_script(topic):
    corroboration_text = "\n".join(f"- {c}" for c in topic.get("corroborating_angles", [])) or "- Direct clinical analysis."
    prompt = f"""
You are a charismatic, evidence-based physician-communicator modeled after the YouTube channel 'Leonid Kim MD'.
Instead of covering 5 random stories, you are dedicating this ENTIRE 9-to-10 minute investigative episode to ONE viral medical topic that patients are searching for today:

PRIMARY VIRAL TOPIC: {topic['title']}
CLINICAL SUMMARY: {topic['summary']}
RELATED ANGLES:
{corroboration_text}

CRITICAL RULES:
1. Speak directly to the viewer ('you', 'your body', 'what I want you to notice') in a candid, clear, authoritative doctor-to-patient tone like Leonid Kim MD.
2. Break this SINGLE topic into 5 sequential investigative chapters:
   - Chapter 1: The Hidden Truth Behind The Headline
   - Chapter 2: What The New Clinical Study Shows
   - Chapter 3: How It Works Inside Your Body
   - Chapter 4: Hidden Risks & Mistakes To Avoid
   - Chapter 5: The Doctor's Practical Action Plan
3. WORD COUNT FOR 9-TO-10 MINUTE DURATION:
   - 'intro_hook': 52 to 60 words.
   - Each of the 5 chapters has 4 acts ('act1_hook', 'act2_science', 'act3_impact', 'act4_takeaway').
   - EVERY single act MUST be between 66 and 72 words.
   - 'outro': 42 to 50 words.
4. SPELLING & SUBTITLE CLARITY: Use 100% flawless English spelling.
5. Also generate 'short_script' for a thrilling 45-second YouTube Short on the EXACT SAME topic.

Return ONLY valid JSON:
{{
  "title_options": ["Option 1", "Option 2", "Option 3"],
  "thumbnail_prompt": " prompt ",
  "intro_hook": "52-60 words",
  "chapters": [
    {{
      "chapter_title": "The Hidden Truth Behind The Headline",
      "act1_hook": "66-72 words",
      "act2_science": "66-72 words",
      "act3_impact": "66-72 words",
      "act4_takeaway": "66-72 words",
      "search_query_1": "4-6 word Pexels query",
      "search_query_2": "4-6 word Pexels query",
      "search_query_3": "4-6 word Pexels query",
      "search_query_4": "4-6 word Pexels query"
    }}
  ],
  "outro": "42-50 words",
  "description": "SEO YouTube description",
  "tags": "18 comma-separated SEO tags",
  "short_script": {{
    "short_title": "Viral Short title with #Shorts",
    "part1_hook": "25-32 words",
    "part2_reveal": "35-42 words",
    "part3_cta": "22-28 words",
    "visual_query_1": "Pexels query",
    "visual_query_2": "Pexels query",
    "visual_query_3": "Pexels query"
  }}
}}
"""
    client = genai.Client(api_key=GEMINI_API_KEY)
    for model_name in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
        for attempt in range(2):
            try:
                print(f"Generating Leonid Kim MD script with {model_name} (attempt {attempt + 1})...")
                res = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.65)
                )
                raw_text = res.text.strip()
                raw_text = re.sub(r"^```(?:json)?", "", raw_text).strip()
                raw_text = re.sub(r"```$", "", raw_text).strip()
                parsed = json.loads(raw_text)
                return validate_and_repair_script_data(parsed, topic)
            except Exception as e:
                print(f"Model {model_name} error: {e}")
                time.sleep(3)
    return validate_and_repair_script_data({}, topic)

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
        except Exception as e:
            print(f"TTS retry {attempt + 1}: {e}")
            time.sleep(2)
    return False

def extract_search_keywords(query):
    words = [w for w in re.sub(r"[^a-zA-Z0-9 ]", " ", str(query)).lower().split() if len(w) > 2]
    return " ".join(words[:5]) if words else "doctor medical clinic"

def search_and_download_video(query, out_path, used_ids, min_dur=4, orientation="landscape"):
    headers = {"Authorization": PEXELS_API_KEY}
    search_candidates = [
        extract_search_keywords(query),
        random.choice(SAFE_MEDICAL_QUERIES),
        "doctor medical laboratory clinic",
        "medicine pills healthcare hospital"
    ]
    for q in search_candidates:
        try:
            url = f"https://api.pexels.com/videos/search?query={urllib.parse.quote(q)}&per_page=15&orientation={orientation}"
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                continue
            videos = r.json().get("videos", [])
            random.shuffle(videos)
            for v in videos:
                vid_id = str(v.get("id", ""))
                dur = v.get("duration", 0)
                if not vid_id or vid_id in used_ids or dur < min_dur or dur > 90:
                    continue
                files = v.get("video_files", [])
                best_file = None
                for vf in files:
                    if vf.get("file_type") == "video/mp4" and 480 <= (vf.get("height", 0) or 0) <= 1440:
                        best_file = vf
                        break
                if not best_file and files:
                    best_file = files[0]
                if best_file and best_file.get("link"):
                    vr = requests.get(best_file["link"], stream=True, timeout=25)
                    if vr.status_code == 200:
                        with open(out_path, "wb") as f:
                            for chunk in vr.iter_content(chunk_size=65536):
                                if chunk:
                                    f.write(chunk)
                        if os.path.exists(out_path) and os.path.getsize(out_path) > 50000:
                            used_ids.append(vid_id)
                            return True
        except Exception:
            continue
    return False

def normalize_clip_hd(in_path, out_path, target_w=W, target_h=H):
    vf_str = f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,crop={target_w}:{target_h},setsar=1,fps={FPS}"
    cmd = ["ffmpeg", "-y", "-i", in_path, "-t", "14", "-vf", vf_str, "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-threads", "4", out_path]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45)
        return os.path.exists(out_path) and os.path.getsize(out_path) > 30000
    except Exception:
        return False

def create_chapter_bumper(ch_num, ch_title, duration=2.4):
    img = Image.new("RGB", (W, H), (8, 16, 30))
    draw = ImageDraw.Draw(img)
    for y in range(H):
        c = int(16 + (y / H) * 20)
        draw.line([(0, y), (W, y)], fill=(8, c, c + 18))
    draw.rectangle([90, 210, 102, 510], fill=(0, 215, 255))
    draw.rectangle([90, 210, 1190, 214], fill=(0, 215, 255))
    draw.rectangle([90, 506, 1190, 510], fill=(0, 215, 255))
    draw.text((130, 245), f"CLINICAL CHAPTER 0{ch_num} OF 05", font=load_font(28, True), fill=(0, 215, 255))
    draw.text((130, 315), ch_title[:46], font=load_font(44, True), fill=(255, 255, 255))
    draw.text((130, 415), "MEDPULSE 5  |  EVIDENCE-BASED MEDICAL ANALYSIS", font=load_font(22, False), fill=(175, 200, 225))
    if LOGO_PIL is not None:
        img.paste(LOGO_PIL, (W - 68 - 32, 32), LOGO_PIL)
    clip = ImageClip(np.array(img)).set_duration(duration)
    sr = 44100
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    env = np.exp(-3.0 * t)
    wave = (0.14 * np.sin(2 * np.pi * 528.0 * t) + 0.09 * np.sin(2 * np.pi * 792.0 * t)) * env
    chime = AudioArrayClip(np.column_stack([wave, wave]).astype(np.float32), fps=sr)
    return clip.set_audio(chime)

def render_overlay_frame_with_subtitle(ch_num, ch_title, subtitle_text):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if LOGO_PIL is not None:
        img.paste(LOGO_PIL, (W - 68 - 24, 22), LOGO_PIL)
    if subtitle_text:
        f_sub = load_font(30, True)
        bbox = draw.textbbox((0, 0), subtitle_text, font=f_sub)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        bx1 = max(30, (W - tw) // 2 - 22)
        bx2 = min(W - 30, (W + tw) // 2 + 22)
        by1, by2 = 562, 562 + th + 24
        draw.rounded_rectangle([bx1, by1, bx2, by2], radius=12, fill=(6, 12, 24, 225), outline=(0, 210, 255, 195), width=2)
        tx, ty = (W - tw) // 2, by1 + 10
        draw.text((tx + 2, ty + 2), subtitle_text, font=f_sub, fill=(0, 0, 0, 255))
        draw.text((tx, ty), subtitle_text, font=f_sub, fill=(255, 248, 150, 255))
    bar_y = 644
    draw.rectangle([0, bar_y, W, H], fill=(8, 15, 28, 225))
    draw.rectangle([0, bar_y, W, bar_y + 3], fill=(0, 210, 255, 255))
    draw.rectangle([24, bar_y + 14, 185, bar_y + 52], fill=(0, 185, 235, 255))
    badge_txt = f"CHAPTER 0{ch_num}" if ch_num > 0 else "MEDPULSE 5"
    draw.text((38, bar_y + 22), badge_txt, font=load_font(20, True), fill=(8, 15, 28, 255))
    draw.text((205, bar_y + 20), ch_title[:56], font=load_font(24, True), fill=(245, 250, 255, 255))
    return np.array(img)

def build_synchronized_overlay_track(ch_num, ch_title, full_narration, total_duration):
    chunks = split_into_subtitle_chunks(full_narration, max_words=7)
    if not chunks:
        return ImageClip(render_overlay_frame_with_subtitle(ch_num, ch_title, "")).set_duration(total_duration)
    char_lengths = [max(len(c), 4) for c in chunks]
    total_chars = sum(char_lengths)
    sub_clips, elapsed = [], 0.0
    for idx, chunk in enumerate(chunks):
        dur = max(0.15, total_duration - elapsed) if idx == len(chunks) - 1 else max(0.25, total_duration * (char_lengths[idx] / total_chars))
        elapsed += dur
        sub_clips.append(ImageClip(render_overlay_frame_with_subtitle(ch_num, ch_title, chunk)).set_duration(dur))
    return concatenate_videoclips(sub_clips).set_duration(total_duration)

def render_short_frame_with_subtitle(hook_banner, subtitle_text):
    img = Image.new("RGBA", (SHORT_W, SHORT_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([36, 70, SHORT_W - 120, 142], radius=14, fill=(10, 18, 34, 230), outline=(0, 215, 255, 240), width=3)
    draw.text((58, 90), f"MEDPULSE 5: {hook_banner[:22]}", font=load_font(26, True), fill=(0, 230, 255, 255))
    if LOGO_SHORT_PIL is not None:
        img.paste(LOGO_SHORT_PIL, (SHORT_W - 56 - 24, 72), LOGO_SHORT_PIL)
    if subtitle_text:
        f_sub = load_font(34, True)
        words = subtitle_text.split()
        mid = max(1, len(words) // 2)
        lines = [" ".join(words[:mid]), " ".join(words[mid:])] if len(words) > 4 else [subtitle_text]
        by1, by2 = 880, 880 + len(lines) * 48 + 30
        draw.rounded_rectangle([40, by1, SHORT_W - 40, by2], radius=16, fill=(6, 12, 24, 230), outline=(255, 220, 60, 220), width=3)
        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=f_sub)
            tw = bbox[2] - bbox[0]
            tx, ty = (SHORT_W - tw) // 2, by1 + 14 + i * 46
            draw.text((tx + 2, ty + 2), line, font=f_sub, fill=(0, 0, 0, 255))
            draw.text((tx, ty), line, font=f_sub, fill=(255, 245, 110, 255))
    draw.rectangle([0, SHORT_H - 90, SHORT_W, SHORT_H], fill=(8, 15, 28, 235))
    draw.text((55, SHORT_H - 60), "FULL 9-MIN CLINICAL DEEP DIVE ON MEDPULSE 5", font=load_font(22, True), fill=(255, 255, 255, 255))
    return np.array(img)

def build_short_overlay_track(hook_banner, full_narration, total_duration):
    chunks = split_into_subtitle_chunks(full_narration, max_words=5)
    if not chunks:
        return ImageClip(render_short_frame_with_subtitle(hook_banner, "")).set_duration(total_duration)
    char_lengths = [max(len(c), 3) for c in chunks]
    total_chars = sum(char_lengths)
    clips, elapsed = [], 0.0
    for idx, chunk in enumerate(chunks):
        dur = max(0.15, total_duration - elapsed) if idx == len(chunks) - 1 else max(0.25, total_duration * (char_lengths[idx] / total_chars))
        elapsed += dur
        clips.append(ImageClip(render_short_frame_with_subtitle(hook_banner, chunk)).set_duration(dur))
    return concatenate_videoclips(clips).set_duration(total_duration)

def generate_ambient_music(duration, sr=44100):
    chunk_len = 10.0
    t = np.linspace(0, chunk_len, int(sr * chunk_len), endpoint=False)
    wave = (0.35 * np.sin(2 * np.pi * 110.0 * t) + 0.25 * np.sin(2 * np.pi * 164.81 * t) + 0.20 * np.sin(2 * np.pi * 220.0 * t))
    mod = 0.75 + 0.25 * np.sin(2 * np.pi * 0.1 * t)
    cycle = (wave * mod * 0.045).astype(np.float32)
    stereo_cycle = np.column_stack([cycle, cycle])
    repeats = int(math.ceil(duration / chunk_len)) + 1
    full_arr = np.tile(stereo_cycle, (repeats, 1))[:int(sr * duration)]
    return AudioArrayClip(full_arr, fps=sr).set_duration(duration)

def build_visual_track_for_duration(clip_paths, target_duration, w=W, h=H):
    loaded = []
    for p in clip_paths:
        if p and os.path.exists(p):
            try:
                c = VideoFileClip(p).without_audio()
                if c.duration and c.duration > 1.2:
                    loaded.append(c)
            except Exception:
                pass
    if not loaded:
        return ColorClip(size=(w, h), color=(12, 24, 42), duration=target_duration), []
    pieces, cur, idx = [], 0.0, 0
    slice_target = max(3.2, target_duration / max(len(loaded), 3))
    while cur < target_duration:
        base = loaded[idx % len(loaded)]
        rem = target_duration - cur
        seg_dur = min(slice_target, base.duration, rem)
        if seg_dur < 0.25:
            seg_dur = min(rem, base.duration)
        pieces.append(base.subclip(0, seg_dur))
        cur += seg_dur
        idx += 1
    return concatenate_videoclips(pieces, method="compose").set_duration(target_duration), loaded

def build_companion_short(script_data, used_videos):
    print("Building Thrilling Companion YouTube Short (<58s)...")
    short_cfg = script_data["short_script"]
    parts = [
        ("p1", short_cfg["part1_hook"], short_cfg["visual_query_1"]),
        ("p2", short_cfg["part2_reveal"], short_cfg["visual_query_2"]),
        ("p3", short_cfg["part3_cta"], short_cfg["visual_query_3"])
    ]
    short_segments, open_clips = [], []
    for tag, narration, v_query in parts:
        tts_path = f"temp/short_{tag}.mp3"
        if not generate_tts(narration, tts_path, rate="+6%"):
            continue
        raw_audio = AudioFileClip(tts_path)
        open_clips.append(raw_audio)
        safe_dur = max(0.3, raw_audio.duration - 0.08)
        trimmed_audio = raw_audio.subclip(0, safe_dur)
        raw_vid = f"temp/short_raw_{tag}.mp4"
        norm_vid = f"temp/short_norm_{tag}.mp4"
        clip_list = []
        if search_and_download_video(v_query, raw_vid, used_videos, min_dur=4, orientation="portrait"):
            if normalize_clip_hd(raw_vid, norm_vid, target_w=SHORT_W, target_h=SHORT_H):
                clip_list.append(norm_vid)
        bg_track, loaded = build_visual_track_for_duration(clip_list, safe_dur, w=SHORT_W, h=SHORT_H)
        open_clips.extend(loaded)
        ov_track = build_short_overlay_track(short_cfg["hook_banner"], narration, safe_dur)
        comp = CompositeVideoClip([bg_track, ov_track], size=(SHORT_W, SHORT_H)).set_duration(safe_dur).set_audio(trimmed_audio)
        short_segments.append(comp)
    if not short_segments:
        return False
    final_short = concatenate_videoclips(short_segments, method="compose")
    if final_short.duration > 57.5:
        final_short = final_short.subclip(0, 57.5)
    bg_music = generate_ambient_music(final_short.duration)
    final_short = final_short.set_audio(CompositeAudioClip([final_short.audio, bg_music]))
    out_short = "output/short_video.mp4"
    final_short.write_videofile(out_short, fps=FPS, codec="libx264", audio_codec="aac", preset="ultrafast", threads=4, logger=None)
    for c in open_clips:
        try:
            c.close()
        except Exception:
            pass
    print(f"Companion Short Ready: {out_short} ({final_short.duration:.1f}s)")
    return True

def main():
    if not GEMINI_API_KEY or not PEXELS_API_KEY:
        raise RuntimeError("Missing GEMINI_API_KEY or PEXELS_API_KEY in GitHub Secrets!")
    used_videos = load_used_items(USED_VIDEOS_FILE)
    used_news = load_used_items(USED_NEWS_FILE)
    topic = fetch_viral_trending_topic()
    script_data = generate_script(topic)
    final_segments, open_resources = [], []

    print("Building Intro Hook...")
    intro_tts = "temp/intro.mp3"
    if generate_tts(script_data["intro_hook"], intro_tts):
        a_clip = AudioFileClip(intro_tts)
        open_resources.append(a_clip)
        safe_dur = max(0.3, a_clip.duration - 0.08)
        trimmed_a = a_clip.subclip(0, safe_dur)
        intro_queries = build_harmonized_visual_queries(script_data["intro_hook"], topic["title"])
        intro_vids = []
        for qi, q in enumerate(intro_queries[:3]):
            rv, nv = f"temp/intro_raw_{qi}.mp4", f"temp/intro_norm_{qi}.mp4"
            if search_and_download_video(q, rv, used_videos):
                if normalize_clip_hd(rv, nv):
                    intro_vids.append(nv)
        bg_v, loaded_v = build_visual_track_for_duration(intro_vids, safe_dur)
        open_resources.extend(loaded_v)
        ov_v = build_synchronized_overlay_track(0, script_data["title_options"][0], script_data["intro_hook"], safe_dur)
        final_segments.append(CompositeVideoClip([bg_v, ov_v], size=(W, H)).set_duration(safe_dur).set_audio(trimmed_a))

    for idx, ch in enumerate(script_data["chapters"]):
        ch_num = idx + 1
        ch_title = ch["chapter_title"]
        print(f"Building Chapter {ch_num}/5: {ch_title}")
        final_segments.append(create_chapter_bumper(ch_num, ch_title, duration=2.4))
        acts = [
            ("act1", ch["act1_hook"], ch["search_query_1"]),
            ("act2", ch["act2_science"], ch["search_query_2"]),
            ("act3", ch["act3_impact"], ch["search_query_3"]),
            ("act4", ch["act4_takeaway"], ch["search_query_4"])
        ]
        for act_tag, act_text, base_q in acts:
            tts_file = f"temp/ch{ch_num}_{act_tag}.mp3"
            if not generate_tts(act_text, tts_file):
                continue
            a_clip = AudioFileClip(tts_file)
            open_resources.append(a_clip)
            safe_dur = max(0.3, a_clip.duration - 0.08)
            trimmed_a = a_clip.subclip(0, safe_dur)
            act_queries = build_harmonized_visual_queries(act_text, base_q)
            act_vids = []
            for qi, q in enumerate(act_queries[:4]):
                rv = f"temp/ch{ch_num}_{act_tag}_raw_{qi}.mp4"
                nv = f"temp/ch{ch_num}_{act_tag}_norm_{qi}.mp4"
                if search_and_download_video(q, rv, used_videos):
                    if normalize_clip_hd(rv, nv):
                        act_vids.append(nv)
            bg_v, loaded_v = build_visual_track_for_duration(act_vids, safe_dur)
            open_resources.extend(loaded_v)
            ov_v = build_synchronized_overlay_track(ch_num, ch_title, act_text, safe_dur)
            final_segments.append(CompositeVideoClip([bg_v, ov_v], size=(W, H)).set_duration(safe_dur).set_audio(trimmed_a))

    print("Building Outro...")
    outro_tts = "temp/outro.mp3"
    if generate_tts(script_data["outro"], outro_tts):
        a_clip = AudioFileClip(outro_tts)
        open_resources.append(a_clip)
        safe_dur = max(0.3, a_clip.duration - 0.08)
        trimmed_a = a_clip.subclip(0, safe_dur)
        outro_queries = build_harmonized_visual_queries(script_data["outro"], "doctor consulting patient clinic")
        outro_vids = []
        for qi, q in enumerate(outro_queries[:2]):
            rv, nv = f"temp/outro_raw_{qi}.mp4", f"temp/outro_norm_{qi}.mp4"
            if search_and_download_video(q, rv, used_videos):
                if normalize_clip_hd(rv, nv):
                    outro_vids.append(nv)
        bg_v, loaded_v = build_visual_track_for_duration(outro_vids, safe_dur)
        open_resources.extend(loaded_v)
        ov_v = build_synchronized_overlay_track(0, "SUBSCRIBE TO MEDPULSE 5 FOR DAILY CLINICAL BRIEFINGS", script_data["outro"], safe_dur)
        final_segments.append(CompositeVideoClip([bg_v, ov_v], size=(W, H)).set_duration(safe_dur).set_audio(trimmed_a))

    cur_total = sum(seg.duration for seg in final_segments)
    print(f"Initial Assembled Duration: {cur_total / 60.0:.2f} minutes ({cur_total:.1f}s)")
    if cur_total < 542.0:
        pad_needed = min(45.0, 548.0 - cur_total)
        print(f"Adding {pad_needed:.1f}s Clinical Summary Review to lock >9m00s duration...")
        final_segments.append(create_chapter_bumper(5, "KEY CLINICAL SUMMARY & PATIENT CHECKLIST", duration=pad_needed))

    full_video = concatenate_videoclips(final_segments, method="compose")
    if full_video.duration > 598.0:
        print("Clamping video at 9m58s (598.0s) so it NEVER exceeds 10 minutes...")
        full_video = full_video.subclip(0, 598.0)

    print(f"Final Locked Long Video Duration: {full_video.duration / 60.0:.2f} minutes ({full_video.duration:.1f}s)")
    ambient = generate_ambient_music(full_video.duration)
    full_video = full_video.set_audio(CompositeAudioClip([full_video.audio, ambient]))
    out_long = "output/final_video.mp4"
    full_video.write_videofile(out_long, fps=FPS, codec="libx264", audio_codec="aac", preset="ultrafast", threads=4, logger=None)

    try:
        build_companion_short(script_data, used_videos)
    except Exception as e:
        print(f"Short generation warning: {e}")

    timestamps, t_cursor = ["00:00 Clinical Introduction"], 0.0
    if final_segments:
        t_cursor += final_segments[0].duration
    seg_ptr = 1
    for idx, ch in enumerate(script_data["chapters"]):
        mm, ss = int(t_cursor // 60), int(t_cursor % 60)
        timestamps.append(f"{mm:02d}:{ss:02d} Chapter {idx + 1}: {ch['chapter_title']}")
        for _ in range(5):
            if seg_ptr < len(final_segments):
                t_cursor += final_segments[seg_ptr].duration
                seg_ptr += 1

    ar_h1 = "=== \u0627\u0644\u0639\u0646\u0627\u0648\u064a\u0646 \u0627\u0644\u0645\u0642\u062a\u0631\u062d\u0629 \u0644\u0644\u0641\u064a\u062f\u064a\u0648 \u0627\u0644\u0637\u0648\u064a\u0644 (\u0627\u062e\u062a\u0631 \u0627\u0644\u062e\u064a\u0627\u0631 1 \u0644\u062a\u0637\u0627\u0628\u0642 \u0627\u0644\u0635\u0648\u0631\u0629 \u0627\u0644\u0645\u0635\u063a\u0631\u0629 \u0648\u0627\u0644\u0641\u064a\u062f\u064a\u0648 \u0627\u0644\u0642\u0635\u064a\u0631) ==="
    ar_opt1 = "\u0627\u0644\u062e\u064a\u0627\u0631 1 (\u0645\u0648\u0635\u0649 \u0628\u0647): "
    ar_opt2 = "\u0627\u0644\u062e\u064a\u0627\u0631 2: "
    ar_opt3 = "\u0627\u0644\u062e\u064a\u0627\u0631 3: "
    ar_h2 = "=== \u0648\u0635\u0641 \u0627\u0644\u0635\u0648\u0631\u0629 \u0627\u0644\u0645\u0635\u063a\u0631\u0629 (Thumbnail Prompt - Landscape 16:9) ==="
    ar_h3 = "=== \u0639\u0646\u0648\u0627\u0646 \u0648\u0648\u0635\u0641 \u0627\u0644\u0641\u064a\u062f\u064a\u0648 \u0627\u0644\u0642\u0635\u064a\u0631 \u0627\u0644\u0645\u0631\u0641\u0642 (YouTube Short) ==="
    ar_h4 = "=== \u0635\u0646\u062f\u0648\u0642 \u0627\u0644\u0648\u0635\u0641 \u0627\u0644\u0643\u0627\u0645\u0644 \u0644\u0644\u0641\u064a\u062f\u064a\u0648 \u0627\u0644\u0637\u0648\u064a\u0644 (Description) ==="
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
        f"Short Description: Watch the full 9-minute clinical breakdown on MedPulse 5: {script_data['title_options'][0]} #Shorts #MedicalNews #DoctorExplains #Health",
        "",
        ar_h4,
        script_data["description"],
        "",
        "Clinical Chapters:",
        *timestamps,
        "",
        f"Primary Source Reference: {topic['title']} ({topic['link']})",
        "Educational Disclaimer: This video is for informational and educational purposes only and does not substitute professional medical advice.",
        "",
        ar_h5,
        script_data["tags"]
    ]
    with open("output/youtube_details.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(details_lines))

    used_news.append(topic["norm_key"])
    if topic.get("link"):
        used_news.append(topic["link"])
    save_used_items(USED_NEWS_FILE, used_news)
    save_used_items(USED_VIDEOS_FILE, used_videos)

    for r in open_resources:
        try:
            r.close()
        except Exception:
            pass
    print("ALL DONE SUCCESSFULLY! Both Long Video (9-10m) and Companion Short are ready.")

if __name__ == "__main__":
    main()
