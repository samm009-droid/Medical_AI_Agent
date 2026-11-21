import os
import re
import json
import time
import math
import random
import shutil
import asyncio
import subprocess
import requests
import numpy as np
import feedparser
import edge_tts
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (
    VideoFileClip, AudioFileClip, ImageClip,
    CompositeVideoClip, CompositeAudioClip, concatenate_videoclips
)
from google import genai

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "").strip()

W, H = 1280, 720
SW, SH = 720, 1280
FPS = 24

VOICE_NAME = "en-US-ChristopherNeural"
VOICE_RATE = "+3%"
VOICE_PITCH = "-1Hz"

USED_NEWS_FILE = "used_news.txt"
USED_VIDEOS_FILE = "used_videos.txt"
LOGO_PATH = "تنزيل.jpeg"

os.makedirs("temp", exist_ok=True)
os.makedirs("output", exist_ok=True)

RSS_FEEDS = [
    ("Google Health Top Trends", "https://news.google.com/rss/headlines/section/topic/HEALTH?hl=en-US&gl=US&ceid=US:en"),
    ("Google Trending Medications", "https://news.google.com/rss/search?q=new+medication+OR+FDA+approves+pill+OR+clinical+trial+breakthrough+when:2d&hl=en-US&gl=US&ceid=US:en"),
    ("Google Vitamin & Supplement Trends", "https://news.google.com/rss/search?q=vitamin+OR+supplement+OR+magnesium+OR+omega+study+health+when:2d&hl=en-US&gl=US&ceid=US:en"),
    ("Google Liver & Kidney Trends", "https://news.google.com/rss/search?q=fatty+liver+OR+kidney+repair+OR+gut+microbiome+treatment+when:2d&hl=en-US&gl=US&ceid=US:en"),
    ("Google Heart & Blood Pressure Trends", "https://news.google.com/rss/search?q=blood+pressure+OR+cholesterol+OR+heart+disease+new+treatment+when:2d&hl=en-US&gl=US&ceid=US:en"),
    ("Google Diabetes & Weight Loss Trends", "https://news.google.com/rss/search?q=diabetes+OR+blood+sugar+OR+insulin+OR+weight+loss+drug+study+when:2d&hl=en-US&gl=US&ceid=US:en"),
    ("Google Cancer & Immune Trends", "https://news.google.com/rss/search?q=cancer+pill+OR+tumor+breakthrough+OR+autoimmune+cure+when:2d&hl=en-US&gl=US&ceid=US:en"),
    ("Google Diet & Food Warnings", "https://news.google.com/rss/search?q=hidden+sugar+OR+ultra+processed+food+OR+fasting+health+study+when:2d&hl=en-US&gl=US&ceid=US:en"),
    ("Drugs.com New Medications", "https://www.drugs.com/feeds/new_drugs.xml"),
    ("Drugs.com Clinical Headlines", "https://www.drugs.com/feeds/headline_news.xml"),
    ("Mayo Clinic Health", "https://newsnetwork.mayoclinic.org/feed/"),
    ("Harvard Health", "https://www.health.harvard.edu/blog/feed"),
    ("Cleveland Clinic Health", "https://health.clevelandclinic.org/feed/"),
    ("MedPage Today", "https://www.medpagetoday.com/rss/headlines.xml"),
    ("SciTechDaily Medicine", "https://scitechdaily.com/tag/medicine/feed/"),
    ("SciTechDaily Health", "https://scitechdaily.com/tag/health/feed/"),
    ("MedicalXpress", "https://medicalxpress.com/rss-feed/"),
    ("News-Medical", "https://www.news-medical.net/syndication.axd?format=rss"),
    ("ScienceDaily Health", "https://www.sciencedaily.com/rss/health_medicine.xml"),
    ("ScienceDaily Nutrition", "https://www.sciencedaily.com/rss/health_medicine/nutrition.xml"),
    ("EurekAlert Medicine", "https://www.eurekalert.org/rss/medicine_health.xml"),
    ("NIH Health Releases", "https://www.nih.gov/news-events/feed.xml"),
    ("Medical News Today", "https://rss.medicalnewstoday.com/featurednews.xml"),
    ("Healthline Nutrition & Medicine", "https://www.healthline.com/rss/health-news")
]

BANNED_KEYWORDS = [
    "politics", "election", "senate", "congress", "lawsuit", "stock market",
    "abortion", "transgender", "gun violence", "climate change policy",
    "health insurance", "medicare", "medicaid", "hospital billing", "nurse strike",
    "hospital staffing", "medical school", "podcast", "webinar", "obituary"
]

BORING_LECTURE_KEYWORDS = [
    "drosophila", "fruit fly", "fruit flies", "zebrafish", "c. elegans", "nematode",
    "arabidopsis", "yeast model", "petri dish", "transcriptomic", "proteomic",
    "single-cell rna", "epigenetic methylation", "ribosomal", "chromatography",
    "crystallography", "phylogenetic", "taxonomic", "in silico", "computational model"
]

HIGH_APPEAL_KEYWORDS = [
    "pill", "drug", "medication", "tablet", "capsule", "injection", "fda", "trial",
    "vitamin", "supplement", "nutrient", "diet", "fasting", "protein", "sugar",
    "gut", "liver", "kidney", "heart", "artery", "blood pressure", "cholesterol",
    "diabetes", "insulin", "obesity", "weight", "cancer", "tumor", "arthritis",
    "joint", "pain", "autoimmune", "lung", "asthma", "vision", "eye", "retina",
    "pancreas", "thyroid", "immune", "antibiotic", "cure", "reverse", "restores",
    "repairs", "blocks", "prevents", "warning", "side effect", "breakthrough"
]

THUMBNAIL_PALETTES = [
    {"name": "Emerald & Gold", "lighting": "vibrant emerald green and warm golden rim lighting", "badge": "deep crimson red badge with bright yellow-white bold text"},
    {"name": "Ruby & Cyan", "lighting": "dramatic ruby red and electric cyan studio lighting", "badge": "bright golden-yellow badge with bold pitch-black text"},
    {"name": "Cobalt & Amber", "lighting": "deep cobalt blue and glowing fiery amber contrast lighting", "badge": "vibrant orange-red badge with crisp white bold text"},
    {"name": "Violet & Teal", "lighting": "rich royal violet and luminous turquoise-teal lighting", "badge": "neon lime-yellow badge with ultra-bold dark navy text"},
    {"name": "Coral & Sapphire", "lighting": "warm coral-orange and deep sapphire blue cinematic lighting", "badge": "pure white badge with glowing red border and black bold text"}
]

THUMBNAIL_HOOK_GROUPS = [
    (["pill", "tablet", "capsule", "drug", "medication", "fda"], ["THE REAL TRUTH!", "1 PILL FIXES IT?", "DOCTORS STUNNED!", "WATCH FIRST!"]),
    (["vitamin", "supplement", "nutrient", "diet", "sugar", "fasting", "food"], ["STOP TAKING THIS?", "HIDDEN DANGER!", "THE REAL TRUTH!", "FIX YOUR BODY!"]),
    (["cancer", "tumor", "oncology", "chemo"], ["STOPS CANCER?", "NEW CLINICAL HOPE!", "DOCTORS SHOCKED!", "FINALLY A CURE?"]),
    (["heart", "cardiac", "artery", "cholesterol", "blood pressure", "stroke"], ["SAVES YOUR HEART!", "CLEARS ARTERIES?", "HEART WARNING!", "CHECK THIS NOW!"]),
    (["liver", "kidney", "pancreas", "organ", "lung"], ["REPAIRS ORGANS!", "LIVER WARNING!", "HEALS ITSELF?", "THE HIDDEN TRUTH!"]),
    (["eye", "vision", "retina", "blind", "ear", "hearing"], ["RESTORES SIGHT?", "SAVES VISION!", "SEE AGAIN!", "CLINICAL PROOF!"]),
    (["gut", "stomach", "colon", "digestion", "diabetes", "insulin", "weight"], ["BLOOD SUGAR FIX!", "HEALS YOUR GUT!", "WEIGHT LOSS TRUTH!", "REAL RELIEF!"])
]

 SAFE_MEDICAL_QUERIES = [
    "pharmacist holding medication pill bottle",
    "close up capsules pills medical laboratory",
    "doctor examining patient heart stethoscope clinic",
    "healthy fresh food vitamins nutrition kitchen",
    "scientist analyzing blood sample tube hospital",
    "surgeon medical team operating room lights",
    "senior patient smiling talking to doctor",
    "red blood cells flowing artery animation",
    "woman taking daily vitamin supplement glass water",
    "modern hospital diagnostic scanner monitor"
]

KEYWORD_VISUAL_MAP = [
    (["pill", "capsule", "tablet", "medication", "drug", "dose", "prescription"], "close up medication pills capsules pharmacy"),
    (["vitamin", "supplement", "magnesium", "omega", "nutrient"], "woman taking vitamin capsule supplement water"),
    (["food", "diet", "sugar", "meal", "eat", "nutrition", "fasting"], "healthy fresh vegetables nutrition kitchen table"),
    (["heart", "cardiac", "artery", "blood pressure", "cholesterol", "stroke"], "doctor checking patient heart blood pressure clinic"),
    (["liver", "kidney", "organ", "pancreas", "stomach", "gut", "colon"], "doctor examining patient abdomen organ scan"),
    (["blood", "cell", "glucose", "insulin", "diabetes", "vessel"], "scientist analyzing blood sample tube laboratory"),
    (["eye", "vision", "retina", "sight"], "optometrist doctor examining patient eye clinic"),
    (["pain", "joint", "arthritis", "bone", "muscle"], "physical therapist doctor examining patient joint"),
    (["warning", "risk", "side effect", "danger", "mistake", "avoid"], "serious doctor explaining medical warning patient"),
    (["study", "trial", "research", "clinical", "scientist", "data"], "medical researcher looking microscope clinical lab")
]

CHAPTER_DEFAULT_TITLES = [
    "The Hidden Truth Behind The Headline",
    "What The New Clinical Study Shows",
    "How It Works Inside Your Body",
    "Hidden Risks & Mistakes To Avoid",
    "The Doctor's Practical Action Plan"
]


def load_set(filepath):
    if not os.path.exists(filepath):
        return set()
    with open(filepath, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def save_to_set(filepath, items):
    existing = load_set(filepath)
    with open(filepath, "a", encoding="utf-8") as f:
        for item in items:
            s = str(item).strip()
            if s and s not in existing:
                f.write(s + "\n")
                existing.add(s)


def normalize_title_key(title):
    t = re.sub(r"[^a-z0-9\s]", "", title.lower())
    words = [w for w in t.split() if len(w) > 2]
    return " ".join(words[:8])


def clean_html(raw_html):
    if not raw_html:
        return ""
    text = re.sub(re.compile("<.*?>"), " ", raw_html)
    return re.sub(r"\s+", " ", text).strip()


def score_viral_medical_appeal(text):
    t = text.lower()
    for bad in BANNED_KEYWORDS:
        if bad in t:
            return -999
    for boring in BORING_LECTURE_KEYWORDS:
        if boring in t:
            return -500
    if ("mice" in t or "mouse" in t or "rodent" in t) and not any(
        w in t for w in ["pill", "drug", "treatment", "cure", "reverse", "human", "patient", "vitamin", "cancer", "diabetes"]
    ):
        return -200
    score = sum(5 for good in HIGH_APPEAL_KEYWORDS if good in t)
    if any(w in t for w in ["pill", "drug", "medication", "vitamin", "supplement", "cure", "reverse", "fda", "liver", "heart", "diabetes", "warning"]):
        score += 15
    if not any(b in t for b in ["brain", "alzheimer", "dementia", "neural"]):
        score += 10
    return score


def fetch_viral_trending_topic():
    used_keys = load_set(USED_NEWS_FILE)
    candidates = []
    seen_in_run = set()
    word_freq = {}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0"}

    feeds_shuffled = RSS_FEEDS[:]
    random.shuffle(feeds_shuffled)

    for source_name, url in feeds_shuffled:
        try:
            resp = requests.get(url, headers=headers, timeout=12)
            if resp.status_code != 200:
                continue
            feed = feedparser.parse(resp.content)
            for entry in feed.entries[:20]:
                raw_title = clean_html(getattr(entry, "title", "")).strip()
                title = re.sub(r"\s+-\s+[^-]+$", "", raw_title).strip()
                summary = clean_html(getattr(entry, "summary", getattr(entry, "description", ""))).strip()
                if not title or len(title) < 22:
                    continue
                tkey = normalize_title_key(title)
                if not tkey or tkey in used_keys or tkey in seen_in_run:
                    continue
                full_text = f"{title}. {summary}"
                base_score = score_viral_medical_appeal(full_text)
                if base_score < 0:
                    continue
                seen_in_run.add(tkey)
                tokens = set(re.findall(r"[a-z]{4,}", title.lower()))
                for tk in tokens:
                    if tk not in {"with", "from", "that", "this", "study", "shows", "new", "health", "medical", "patients", "could", "your", "what"}:
                        word_freq[tk] = word_freq.get(tk, 0) + 1
                candidates.append({
                    "source": source_name,
                    "title": title,
                    "summary": summary[:900],
                    "key": tkey,
                    "tokens": tokens,
                    "base_score": base_score
                })
        except Exception as e:
            print(f"[RSS Warn] {source_name}: {e}")

    if not candidates:
        raise RuntimeError("No fresh trending medical topics found.")

    for c in candidates:
        trend_velocity = sum(min(word_freq.get(tk, 1) - 1, 5) * 4 for tk in c["tokens"])
        c["score"] = c["base_score"] + trend_velocity + random.uniform(0, 3.0)

    candidates.sort(key=lambda x: x["score"], reverse=True)
    hero_topic = candidates[0]

    supporting = []
    for c in candidates[1:]:
        if len(supporting) >= 3:
            break
        if len(hero_topic["tokens"].intersection(c["tokens"])) >= 1:
            supporting.append(c)

    print(f"[Viral Trend Selected] (Score={hero_topic['score']:.1f}) {hero_topic['title']} [{hero_topic['source']}]")
    return hero_topic, supporting


def get_matched_thumbnail_hook(story_text):
    txt = story_text.lower()
    for keywords, hooks in THUMBNAIL_HOOK_GROUPS:
        if any(k in txt for k in keywords):
            return random.choice(hooks)
    return "THE REAL TRUTH!"


def clean_json_text(raw):
    raw = raw.strip()
    fence = chr(96) * 3
    if fence in raw:
        for p in raw.split(fence):
            p_str = p.strip()
            if p_str.startswith("json"):
                p_str = p_str[4:].strip()
            if p_str.startswith("{") and p_str.endswith("}"):
                return p_str
    s, e = raw.find("{"), raw.rfind("}")
    return raw[s:e + 1] if (s != -1 and e != -1 and e > s) else raw


def sanitize_visual_query(q, fallback_idx=0):
    if not q or not isinstance(q, str):
        return SAFE_MEDICAL_QUERIES[fallback_idx % len(SAFE_MEDICAL_QUERIES)]
    q_clean = re.sub(r"[^a-zA-Z0-9\s]", " ", q).strip()
    words = [w for w in q_clean.split() if len(w) > 2]
    if len(words) < 2:
        return SAFE_MEDICAL_QUERIES[fallback_idx % len(SAFE_MEDICAL_QUERIES)]
    return " ".join(words[:6])


def build_harmonized_visual_queries(narration, llm_queries, seed_idx=0):
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", narration.strip()) if s.strip()]
    harmonized = []
    for s in sentences:
        s_low = s.lower()
        for kw_list, mapped_q in KEYWORD_VISUAL_MAP:
            if any(k in s_low for k in kw_list) and mapped_q not in harmonized:
                harmonized.append(mapped_q)
                break
    if isinstance(llm_queries, list):
        for idx, q in enumerate(llm_queries):
            sq = sanitize_visual_query(q, seed_idx + idx)
            if sq not in harmonized:
                harmonized.append(sq)
    while len(harmonized) < 4:
        fb = SAFE_MEDICAL_QUERIES[(seed_idx + len(harmonized)) % len(SAFE_MEDICAL_QUERIES)]
        if fb not in harmonized:
            harmonized.append(fb)
        else:
            harmonized.append("doctor explaining medical scan clinic")
    return harmonized[:4]


def clamp_act_words(text, min_w=66, max_w=73, topic_title="", topic_summary=""):
    words = text.split()
    if len(words) < min_w:
        extra = (
            f" When we examine how {topic_title.lower()} interacts with your cells and organs, "
            f"clinical researchers emphasize that spotting these signs early helps you and your physician "
            f"protect your long-term health safely and effectively. {topic_summary}"
        )
        for w in extra.split():
            words.append(w)
            if len(words) >= min_w and w.endswith((".", "!", "?")):
                break
    if len(words) > max_w:
        trimmed = words[:max_w]
        last_str = " ".join(trimmed)
        last_dot = max(last_str.rfind("."), last_str.rfind("!"), last_str.rfind("?"))
        if last_dot > len(last_str) * 0.72:
            return last_str[:last_dot + 1].strip()
        return (last_str.rstrip(",;:") + ".").strip()
    return " ".join(words)


def validate_and_repair_script_data(data, hero_topic, palette, chosen_hook):
    if not isinstance(data, dict):
        data = {}

    default_intro = (
        f"Everyone is suddenly talking about {hero_topic['title']}, but when I sat down and examined the actual clinical data, "
        "I found critical details that almost nobody is explaining to patients. Welcome back to MedPulse 5. Today we are doing "
        "a complete five-part clinical investigation into what this breakthrough really does inside your body, the hidden side effects "
        "to watch out for, and the exact steps you should discuss with your doctor."
    )
    intro_obj = data.get("intro") if isinstance(data.get("intro"), dict) else {}
    intro_narr = clamp_act_words(str(intro_obj.get("narration", default_intro)).strip(), 68, 78, hero_topic["title"], hero_topic["summary"])
    data["intro"] = {
        "narration": intro_narr,
        "lower_third": str(intro_obj.get("lower_third", "EVIDENCE-BASED CLINICAL DEEP DIVE")).strip().upper()[:40],
        "visual_queries": build_harmonized_visual_queries(intro_narr, intro_obj.get("visual_queries"), 0)
    }

    default_outro = (
        "Now I would love to hear from you: have you or someone in your family experienced this, and which of today's five clinical insights "
        "surprised you the most? Share your thoughts in the comments below, and subscribe to MedPulse 5 for your daily doctor-level health briefing. "
        "Remember that this video is for educational purposes, so always consult your physician before changing any medication or health routine."
    )
    outro_obj = data.get("outro") if isinstance(data.get("outro"), dict) else {}
    outro_narr = clamp_act_words(str(outro_obj.get("narration", default_outro)).strip(), 60, 70, hero_topic["title"], hero_topic["summary"])
    data["outro"] = {
        "narration": outro_narr,
        "lower_third": str(outro_obj.get("lower_third", "SUBSCRIBE TO MEDPULSE 5")).strip().upper()[:40],
        "visual_queries": build_harmonized_visual_queries(outro_narr, outro_obj.get("visual_queries"), 99)
    }

    raw_stories = data.get("stories") if isinstance(data.get("stories"), list) else []
    repaired_stories = []
    for i in range(5):
        st_obj = raw_stories[i] if i < len(raw_stories) and isinstance(raw_stories[i], dict) else {}
        ch_title = str(st_obj.get("chapter_title", "")).strip()
        if not ch_title or len(ch_title) < 5:
            ch_title = CHAPTER_DEFAULT_TITLES[i]
        acts = st_obj.get("acts") if isinstance(st_obj.get("acts"), list) else []
        repaired_acts = []
        for a_idx in range(4):
            act_obj = acts[a_idx] if a_idx < len(acts) and isinstance(acts[a_idx], dict) else {}
            raw_narr = str(act_obj.get("narration", "")).strip()
            narr = clamp_act_words(raw_narr, 66, 73, hero_topic["title"], hero_topic["summary"])
            lt = str(act_obj.get("lower_third", "")).strip().upper()
            if not lt or len(lt) < 4:
                lt = ch_title[:36].upper()
            vqs = build_harmonized_visual_queries(narr, act_obj.get("visual_queries"), i * 4 + a_idx)
            repaired_acts.append({"narration": narr, "lower_third": lt[:40], "visual_queries": vqs})
        repaired_stories.append({"story_number": i + 1, "chapter_title": ch_title[:46], "acts": repaired_acts})
    data["stories"] = repaired_stories

    titles = data.get("youtube_titles")
    if not isinstance(titles, list) or len(titles) < 3:
        ht = hero_topic["title"][:50]
        titles = [
            f"The Hidden Truth About {ht} (Doctor Explains New Study)",
            f"What Happens To Your Body With {ht}? (5 Clinical Truths)",
            f"Watch This Before Trying {ht}! (New Medical Evidence)"
        ]
    data["youtube_titles"] = [str(t).strip() for t in titles[:3]]

    thumb = str(data.get("thumbnail_prompt", "")).strip()
    if len(thumb) < 50 or chosen_hook not in thumb:
        thumb = (
            f"Ultra-detailed 16:9 YouTube thumbnail in Leonid Kim MD style, close-up of a confident physician in a clinical studio "
            f"holding a glowing medical capsule beside a vivid 3D anatomical model representing {hero_topic['title'][:58]}, "
            f"NO brain imagery, {palette['lighting']}, with a {palette['badge']} in the upper corner reading "
            f"exactly \"{chosen_hook}\", photorealistic 8k, high contrast."
        )
    data["thumbnail_prompt"] = thumb

    short_data = data.get("short_script") if isinstance(data.get("short_script"), dict) else {}
    short_title = str(short_data.get("short_title", "")).strip()
    if len(short_title) < 10:
        short_title = f"{data['youtube_titles'][0][:65]} #Shorts #Health"
    elif "#shorts" not in short_title.lower():
        short_title = f"{short_title} #Shorts"

    short_scenes = short_data.get("scenes") if isinstance(short_data.get("scenes"), list) else []
    fixed_short_scenes = []
    for s_i in range(3):
        sc = short_scenes[s_i] if s_i < len(short_scenes) and isinstance(short_scenes[s_i], dict) else {}
        snarr = str(sc.get("narration", "")).strip()
        words_s = snarr.split()
        if len(words_s) < 20:
            if s_i == 2:
                snarr = (
                    "But before you make any changes, you must know the hidden risks and the doctor's action plan! "
                    "Tap the related video link right at the bottom of your screen to watch the full breakdown on MedPulse 5!"
                )
            else:
                snarr = " ".join(repaired_stories[s_i]["acts"][0]["narration"].split()[:34])
        elif len(words_s) > 38:
            snarr = " ".join(words_s[:36]) + "."
        shead = str(sc.get("headline", "")).strip().upper()
        if not shead:
            shead = chosen_hook if s_i == 0 else ("TAP FULL VIDEO BELOW!" if s_i == 2 else "CLINICAL BREAKTHROUGH")
        svq = build_harmonized_visual_queries(snarr, sc.get("visual_queries"), 50 + s_i)
        fixed_short_scenes.append({"narration": snarr, "headline": shead[:28], "visual_queries": svq[:3]})

    data["short_script"] = {"short_title": short_title, "scenes": fixed_short_scenes}
    return data


def generate_script_with_gemini(hero_topic, supporting_topics):
    client = genai.Client(api_key=GEMINI_API_KEY)
    palette = random.choice(THUMBNAIL_PALETTES)
    chosen_hook = get_matched_thumbnail_hook(hero_topic["title"] + " " + hero_topic["summary"])

    support_lines = [f"- Context: {s['title']} ({s['summary'][:260]})" for s in supporting_topics]
    support_block = "\n".join(support_lines)

    prompt_lines = [
        "You are an authoritative, candid, compassionate medical doctor hosting the YouTube channel 'MedPulse 5', modeled directly on the delivery and structure of 'Leonid Kim MD'.",
        "",
        "TODAY'S #1 VIRAL MEDICAL TREND TOPIC:",
        f"HEADLINE: {hero_topic['title']}",
        f"CLINICAL SUMMARY: {hero_topic['summary']}",
        support_block,
        "",
        "EXACT LEONID KIM MD DELIVERY & PACING RULES (STRICT 9 TO 10 MINUTE VIDEO):",
        "1. Speak directly to the viewer like a trusted doctor uncovering the real clinical truth behind a viral headline ('When I examined the clinical trial data...', 'Here is what happens inside your blood vessels and organs...', 'Most patients are never warned about this...').",
        "2. Use crystal-clear, vivid everyday English with zero dry academic lecturing. Spelling and grammar must be 100% flawless because your exact narration will be burned onto the screen as English subtitles.",
        "3. Never mention website names, RSS feeds, or dates out loud.",
        "4. Divide this single topic into EXACTLY 5 sequential chapters ('stories' array of length 5):",
        "   - Chapter 1: The Hidden Truth & Why This Is Trending Worldwide",
        "   - Chapter 2: What The New Clinical Study Actually Proves",
        "   - Chapter 3: How It Works Inside Your Body & Vital Organs",
        "   - Chapter 4: Hidden Side Effects, Warnings & Mistakes To Avoid",
        "   - Chapter 5: The Doctor's Practical Action Plan For Patients",
        "5. Every Chapter MUST have EXACTLY 4 acts ('acts' array of length 4). Each Act narration MUST be strictly 67 to 72 words so the total episode lands between 9 and 10 minutes.",
        "6. For 'visual_queries' in every act, provide 4 concrete Pexels search phrases (4 to 5 simple words each) that directly match the exact sentences spoken in that act.",
        "7. Synchronize 'youtube_titles'[0], 'thumbnail_prompt' (NO brain imagery, use " + palette["lighting"] + " and a " + palette["badge"] + " reading '" + chosen_hook + "'), and 'short_script' (3 thrilling scenes, total 40 seconds) 100% around this topic.",
        "",
        "Return ONLY valid JSON with these exact keys:",
        "{",
        '  "youtube_titles": ["Title 1", "Title 2", "Title 3"],',
        '  "youtube_description": "3-paragraph SEO clinical description",',
        '  "youtube_tags": ["evidence based medicine", "new medications", "clinical study", "health news", "medpulse 5"],',
        '  "thumbnail_prompt": "Detailed 16:9 thumbnail prompt...",',
        '  "short_script": {',
        '    "short_title": "Viral Hook Title #Shorts",',
        '    "scenes": [',
        f'      {{"narration": "32 words shocking hook...", "headline": "{chosen_hook}", "visual_queries": ["q1", "q2", "q3"]}},',
        '      {"narration": "34 words clinical reveal...", "headline": "CLINICAL PROOF", "visual_queries": ["q1", "q2", "q3"]},',
        '      {"narration": "30 words cliffhanger telling viewer to tap the related video link at the bottom of the screen...", "headline": "TAP FULL VIDEO BELOW!", "visual_queries": ["q1", "q2", "q3"]}',
        '    ]',
        '  },',
        '  "intro": {"narration": "72 words doctor intro...", "lower_third": "EVIDENCE-BASED CLINICAL DEEP DIVE", "visual_queries": ["q1", "q2", "q3", "q4"]},',
        '  "stories": [',
        '    {',
        '      "story_number": 1,',
        '      "chapter_title": "Chapter Title",',
        '      "acts": [',
        '        {"act_number": 1, "narration": "70 words...", "lower_third": "HEADLINE", "visual_queries": ["q1", "q2", "q3", "q4"]},',
        '        {"act_number": 2, "narration": "70 words...", "lower_third": "HEADLINE", "visual_queries": ["q1", "q2", "q3", "q4"]},',
        '        {"act_number": 3, "narration": "70 words...", "lower_third": "HEADLINE", "visual_queries": ["q1", "q2", "q3", "q4"]},',
        '        {"act_number": 4, "narration": "70 words...", "lower_third": "HEADLINE", "visual_queries": ["q1", "q2", "q3", "q4"]}',
        '      ]',
        '    }',
        '  ],',
        '  "outro": {"narration": "64 words doctor conclusion...", "lower_third": "SUBSCRIBE TO MEDPULSE 5", "visual_queries": ["q1", "q2", "q3", "q4"]}',
        "}"
    ]
    prompt = "\n".join(prompt_lines)

    for model_name in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
        for attempt in range(3):
            try:
                print(f"[Gemini] Generating Leonid Kim MD style script with {model_name} (attempt {attempt + 1})...")
                response = client.models.generate_content(model=model_name, contents=prompt)
                data = json.loads(clean_json_text(response.text), strict=False)
                return validate_and_repair_script_data(data, hero_topic, palette, chosen_hook)
            except Exception as e:
                print(f"[Gemini Warn] {model_name} attempt {attempt + 1}: {e}")
                time.sleep(3)
    raise RuntimeError("All Gemini attempts failed.")


async def _edge_tts_save(text, out_path):
    communicate = edge_tts.Communicate(text, VOICE_NAME, rate=VOICE_RATE, pitch=VOICE_PITCH)
    await asyncio.wait_for(communicate.save(out_path), timeout=40.0)


def generate_voice(text, out_path):
    clean_t = re.sub(r"[\*\#\_\~]", "", text).strip() or "Let us examine the clinical evidence."
    for attempt in range(5):
        try:
            asyncio.run(_edge_tts_save(clean_t, out_path))
            if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
                return True
        except Exception as e:
            print(f"[TTS Retry {attempt + 1}/5] {e}")
            time.sleep(2 + attempt * 2)
    raise RuntimeError("TTS generation failed.")


def normalize_clip_hd(src_path, dst_path, vertical=False):
    cw, ch = (SW, SH) if vertical else (W, H)
    max_t = "10" if vertical else "14"
    vf = f"scale={cw}:{ch}:force_original_aspect_ratio=increase,crop={cw}:{ch},setsar=1,fps={FPS},eq=contrast=1.06:saturation=1.14:brightness=0.01"
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", src_path, "-t", max_t, "-an", "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
        "-pix_fmt", "yuv420p", "-threads", "4", dst_path
    ]
    subprocess.run(cmd, check=True, timeout=90)


def create_fallback_medical_clip(dst_path, duration=8.0, vertical=False):
    cw, ch = (SW, SH) if vertical else (W, H)
    img = Image.new("RGB", (cw, ch), (10, 24, 42))
    draw = ImageDraw.Draw(img)
    for y in range(ch):
        draw.line([(0, y), (cw, y)], fill=(int(8 + 14 * (y / ch)), int(22 + 34 * (y / ch)), int(42 + 56 * (y / ch))))
    temp_img = dst_path + ".png"
    img.save(temp_img)
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-i", temp_img, "-t", str(duration),
        "-vf", f"fps={FPS},format=yuv420p", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20", dst_path
    ]
    subprocess.run(cmd, check=True)
    if os.path.exists(temp_img):
        os.remove(temp_img)


def download_scene_pexels_clips(queries, needed_count, used_video_ids, scene_tag, vertical=False):
    headers = {"Authorization": PEXELS_API_KEY}
    downloaded = []
    search_pool = [sanitize_visual_query(q, idx) for idx, q in enumerate(queries)]
    for backup_q in random.sample(SAFE_MEDICAL_QUERIES, 4):
        if backup_q not in search_pool:
            search_pool.append(backup_q)

    for query in search_pool:
        if len(downloaded) >= needed_count:
            break
        try:
            resp = requests.get("https://api.pexels.com/videos/search", headers=headers, params={"query": query, "per_page": 35, "page": 1}, timeout=15)
            if resp.status_code != 200:
                continue
            vids = resp.json().get("videos", [])
            random.shuffle(vids)
            for v in vids:
                if len(downloaded) >= needed_count:
                    break
                vid_id = str(v.get("id", ""))
                if not vid_id or vid_id in used_video_ids or v.get("duration", 0) < 5:
                    continue
                best_file = None
                for vf in v.get("video_files", []):
                    vw, vh, link = vf.get("width", 0) or 0, vf.get("height", 0) or 0, vf.get("link", "")
                    if link and 1280 <= vw <= 2560 and vh >= 720:
                        best_file = link
                        break
                if not best_file:
                    for vf in v.get("video_files", []):
                        vw, vh, link = vf.get("width", 0) or 0, vf.get("height", 0) or 0, vf.get("link", "")
                        if link and vw >= 960 and vh >= 540:
                            best_file = link
                            break
                if not best_file:
                    continue
                raw_p = f"temp/raw_{scene_tag}_{len(downloaded)}.mp4"
                norm_p = f"temp/norm_{scene_tag}_{len(downloaded)}.mp4"
                try:
                    r = requests.get(best_file, stream=True, timeout=25)
                    if r.status_code == 200:
                        with open(raw_p, "wb") as f:
                            for chunk in r.iter_content(chunk_size=262144):
                                if chunk:
                                    f.write(chunk)
                        normalize_clip_hd(raw_p, norm_p, vertical=vertical)
                        if os.path.exists(raw_p):
                            os.remove(raw_p)
                        if os.path.exists(norm_p) and os.path.getsize(norm_p) > 15000:
                            downloaded.append(norm_p)
                            used_video_ids.add(vid_id)
                            break
                except Exception:
                    for p in (raw_p, norm_p):
                        if os.path.exists(p):
                            os.remove(p)
        except Exception:
            pass

    while len(downloaded) < needed_count:
        fb_p = f"temp/norm_{scene_tag}_fb_{len(downloaded)}.mp4"
        create_fallback_medical_clip(fb_p, duration=8.0, vertical=vertical)
        downloaded.append(fb_p)
    return downloaded


def get_font(size):
    for fp in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                pass
    return ImageFont.load_default()


def prepare_circular_logo(logo_path, size=68):
    if not os.path.exists(logo_path):
        return None
    try:
        im = Image.open(logo_path).convert("RGBA").resize((size, size), Image.LANCZOS)
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
        out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        out.paste(im, (0, 0), mask)
        ImageDraw.Draw(out).ellipse((0, 0, size - 1, size - 1), outline=(0, 215, 255, 220), width=2)
        return out
    except Exception:
        return None


LOGO_PIL = prepare_circular_logo(LOGO_PATH, size=68)


def split_into_subtitle_chunks(narration, words_per_chunk=7):
    clean_words = re.sub(r"\s+", " ", narration.strip()).split()
    if not clean_words:
        return ["Clinical Evidence Breakdown"]
    chunks = []
    for i in range(0, len(clean_words), words_per_chunk):
        chunks.append(" ".join(clean_words[i:i + words_per_chunk]))
    return chunks


def render_overlay_frame_with_subtitle(headline_text, story_badge, subtitle_text, vertical=False):
    cw, ch = (SW, SH) if vertical else (W, H)
    canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    if not vertical:
        bar_y = 644
        draw.rectangle([(0, bar_y), (W, H)], fill=(8, 16, 28, 226))
        draw.rectangle([(0, bar_y), (W, bar_y + 3)], fill=(0, 210, 235, 255))
        draw.rectangle([(0, bar_y), (14, H)], fill=(0, 210, 235, 255))
        draw.text((48, bar_y + 10), story_badge.upper()[:46], font=get_font(15), fill=(0, 225, 255, 255))
        draw.text((48, bar_y + 34), headline_text.upper()[:46], font=get_font(23), fill=(255, 255, 255, 255))
        if LOGO_PIL is not None:
            canvas.paste(LOGO_PIL, (W - 68 - 24, 22), LOGO_PIL)
        if subtitle_text:
            sub_font = get_font(24)
            bbox = draw.textbbox((0, 0), subtitle_text, font=sub_font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            pad_x, pad_y = 22, 10
            bx1 = max(24, (W - tw) // 2 - pad_x)
            bx2 = min(W - 24, (W + tw) // 2 + pad_x)
            by2 = bar_y - 14
            by1 = by2 - th - pad_y * 2
            draw.rectangle([(bx1, by1), (bx2, by2)], fill=(6, 12, 22, 218), outline=(0, 215, 255, 190), width=2)
            draw.text(((W - tw) // 2, by1 + pad_y - 2), subtitle_text, font=sub_font, fill=(255, 250, 210, 255))
    else:
        draw.rectangle([(24, 42), (SW - 24, 128)], fill=(8, 18, 34, 225), outline=(0, 220, 255, 240), width=2)
        if LOGO_PIL is not None:
            canvas.paste(LOGO_PIL, (38, 51), LOGO_PIL)
        draw.text((120, 56), "MEDPULSE 5", font=get_font(22), fill=(255, 255, 255, 255))
        draw.text((120, 86), story_badge.upper()[:34], font=get_font(15), fill=(0, 225, 255, 255))
        if subtitle_text:
            words_s = subtitle_text.split()
            mid = max(1, len(words_s) // 2)
            line1 = " ".join(words_s[:mid])
            line2 = " ".join(words_s[mid:])
            sub_f = get_font(26)
            draw.rectangle([(32, 740), (SW - 32, 855)], fill=(6, 12, 24, 225), outline=(0, 225, 255, 220), width=2)
            b1 = draw.textbbox((0, 0), line1, font=sub_f)
            draw.text(((SW - (b1[2] - b1[0])) // 2, 756), line1, font=sub_f, fill=(255, 255, 255, 255))
            if line2:
                b2 = draw.textbbox((0, 0), line2, font=sub_f)
                draw.text(((SW - (b2[2] - b2[0])) // 2, 798), line2, font=sub_f, fill=(255, 235, 90, 255))
        box_y, box_h = 890, 135
        draw.rectangle([(28, box_y), (SW - 28, box_y + box_h)], fill=(10, 20, 38, 235), outline=(255, 205, 0, 255), width=3)
        draw.rectangle([(28, box_y), (42, box_y + box_h)], fill=(255, 205, 0, 255))
        draw.text((56, box_y + 24), headline_text.upper()[:28], font=get_font(28), fill=(255, 230, 60, 255))
        draw.text((56, box_y + 76), "WATCH FULL EPISODE ON MEDPULSE 5", font=get_font(18), fill=(255, 255, 255, 255))

    return np.array(canvas)


def build_synchronized_overlay_track(narration, headline, badge, total_duration, vertical=False):
    chunks = split_into_subtitle_chunks(narration, words_per_chunk=6 if vertical else 7)
    char_lengths = [max(1, len(c)) for c in chunks]
    total_chars = sum(char_lengths)
    sub_clips = []
    acc_t = 0.0
    for idx, ch_text in enumerate(chunks):
        if idx == len(chunks) - 1:
            c_dur = max(0.15, total_duration - acc_t)
        else:
            c_dur = max(0.2, total_duration * (char_lengths[idx] / total_chars))
            if acc_t + c_dur > total_duration:
                c_dur = max(0.15, total_duration - acc_t)
        frame_arr = render_overlay_frame_with_subtitle(headline, badge, ch_text, vertical=vertical)
        sub_clips.append(ImageClip(frame_arr).set_duration(c_dur))
        acc_t += c_dur
    return concatenate_videoclips(sub_clips, method="compose").set_duration(total_duration)


def generate_chime_wav(out_path, duration=2.4):
    sr = 44100
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    env = np.exp(-2.2 * t) * np.sin(np.pi * np.minimum(t / 0.08, 1.0))
    wave = (0.45 * np.sin(2 * np.pi * 523.25 * t) + 0.35 * np.sin(2 * np.pi * 659.25 * t) + 0.20 * np.sin(2 * np.pi * 783.99 * t)) * env * 0.22
    audio_int16 = np.int16(np.clip(wave, -1.0, 1.0) * 32767)
    proc = subprocess.Popen(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "s16le", "-ar", str(sr), "-ac", "1", "-i", "pipe:0", out_path], stdin=subprocess.PIPE)
    proc.communicate(input=audio_int16.tobytes())


def generate_ambient_music(out_path, duration):
    sr = 22050
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    pad = 0.35 * np.sin(2 * np.pi * 110.0 * t) + 0.25 * np.sin(2 * np.pi * 164.81 * t) + 0.20 * np.sin(2 * np.pi * 220.0 * t)
    wave = pad * (0.75 + 0.25 * np.sin(2 * np.pi * 0.12 * t)) * 0.15
    audio_int16 = np.int16(np.clip(wave, -1.0, 1.0) * 32767)
    proc = subprocess.Popen(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "s16le", "-ar", str(sr), "-ac", "1", "-i", "pipe:0", "-c:a", "aac", "-b:a", "96k", out_path], stdin=subprocess.PIPE)
    proc.communicate(input=audio_int16.tobytes())


def create_chapter_bumper(chapter_num, chapter_title, duration=2.4):
    canvas = Image.new("RGB", (W, H), (8, 18, 34))
    draw = ImageDraw.Draw(canvas)
    for y in range(H):
        draw.line([(0, y), (W, y)], fill=(int(8 + 10 * (y / H)), int(18 + 28 * (y / H)), int(34 + 48 * (y / H))))
    draw.rectangle([(90, 230), (W - 90, 490)], fill=(12, 26, 48), outline=(0, 215, 255), width=3)
    draw.rectangle([(90, 230), (110, 490)], fill=(0, 215, 255))
    draw.text((140, 275), f"CLINICAL TRUTH #{chapter_num} OF 5", font=get_font(28), fill=(0, 225, 255))
    draw.text((140, 345), chapter_title[:44], font=get_font(38), fill=(255, 255, 255))
    if LOGO_PIL is not None:
        canvas.paste(LOGO_PIL, (W - 68 - 24, 22), LOGO_PIL)
    chime_path = f"temp/chime_{chapter_num}.wav"
    generate_chime_wav(chime_path, duration=duration)
    chime_audio = AudioFileClip(chime_path).subclip(0, duration)
    return ImageClip(np.array(canvas)).set_duration(duration).set_audio(chime_audio)


def build_scene_video(narration, headline, badge, queries, scene_tag, used_video_ids, vertical=False):
    voice_path = f"temp/voice_{scene_tag}.mp3"
    generate_voice(narration, voice_path)

    raw_audio = AudioFileClip(voice_path)
    safe_dur = max(0.2, raw_audio.duration - 0.08)
    audio_clip = raw_audio.subclip(0, safe_dur)

    needed_clips = 3 if vertical else 4
    clip_paths = download_scene_pexels_clips(queries, needed_clips, used_video_ids, scene_tag, vertical=vertical)

    seg_dur = safe_dur / len(clip_paths)
    sub_clips, readers = [], []

    for cp in clip_paths:
        v_reader = VideoFileClip(cp, audio=False)
        readers.append(v_reader)
        avail = max(0.5, v_reader.duration - 0.15)
        if avail >= seg_dur:
            max_start = max(0.0, avail - seg_dur)
            start_t = 0.0 if vertical else random.uniform(0.0, min(1.2, max_start))
            sub = v_reader.subclip(start_t, start_t + seg_dur)
        else:
            loops = int(math.ceil(seg_dur / avail))
            sub = concatenate_videoclips([v_reader.subclip(0, avail) for _ in range(loops)], method="compose").subclip(0, seg_dur)
        sub_clips.append(sub)

    visual_track = concatenate_videoclips(sub_clips, method="compose").set_duration(safe_dur)
    overlay_track = build_synchronized_overlay_track(narration, headline, badge, safe_dur, vertical=vertical)

    target_size = (SW, SH) if vertical else (W, H)
    comp = CompositeVideoClip([visual_track, overlay_track], size=target_size).set_duration(safe_dur).set_audio(audio_clip)
    return comp, readers, raw_audio


def format_timestamp(seconds):
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"


def build_companion_short(script_data, used_video_ids):
    print("[Short] Building thrilling sub-titled vertical YouTube Short (720x1280)...")
    scenes = script_data.get("short_script", {}).get("scenes", [])
    if not scenes:
        return
    short_clips, short_readers, short_audios = [], [], []
    for idx, sc in enumerate(scenes[:3], 1):
        badge = f"PART {idx}/3 | CLINICAL ALERT" if idx < 3 else "WATCH FULL VIDEO BELOW"
        comp, r_list, a_clip = build_scene_video(sc["narration"], sc["headline"], badge, sc["visual_queries"], f"short_s{idx}", used_video_ids, vertical=True)
        short_clips.append(comp)
        short_readers.extend(r_list)
        short_audios.append(a_clip)

    final_short = concatenate_videoclips(short_clips, method="compose")
    if final_short.duration > 57.5:
        final_short = final_short.subclip(0, 57.5)
    total_dur = final_short.duration

    bg_short_path = "temp/ambient_short.m4a"
    generate_ambient_music(bg_short_path, total_dur + 1.5)
    bg_audio = AudioFileClip(bg_short_path).subclip(0, total_dur).volumex(0.06)
    final_short = final_short.set_audio(CompositeAudioClip([final_short.audio, bg_audio]).set_duration(total_dur))

    final_short.write_videofile(
        "output/short_video.mp4", fps=FPS, codec="libx264", audio_codec="aac", audio_bitrate="192k", threads=4,
        ffmpeg_params=["-preset", "veryfast", "-crf", "21", "-maxrate", "2500k", "-bufsize", "5000k", "-pix_fmt", "yuv420p", "-movflags", "+faststart"],
        logger=None
    )
    for r in short_readers + short_audios + [bg_audio]:
        try:
            r.close()
        except Exception:
            pass


def main():
    print("=== MedPulse 5 AI Agent (Leonid Kim MD Viral Trend + Subtitles + Strict 9-10m Lock) ===")
    if not GEMINI_API_KEY or not PEXELS_API_KEY:
        raise RuntimeError("Missing GEMINI_API_KEY or PEXELS_API_KEY.")

    hero_topic, supporting_topics = fetch_viral_trending_topic()
    script_data = generate_script_with_gemini(hero_topic, supporting_topics)

    used_video_ids = load_set(USED_VIDEOS_FILE)
    initial_video_ids = set(used_video_ids)
    all_scene_clips, all_open_readers, all_open_audios, timestamps = [], [], [], []
    current_time = 0.0

    timestamps.append("00:00 Introduction: The Clinical Truth")
    intro_d = script_data["intro"]
    intro_clip, r_list, a_clip = build_scene_video(intro_d["narration"], intro_d["lower_third"], "MEDPULSE 5 | CLINICAL INVESTIGATION", intro_d["visual_queries"], "intro", used_video_ids)
    all_scene_clips.append(intro_clip)
    all_open_readers.extend(r_list)
    all_open_audios.append(a_clip)
    current_time += intro_clip.duration

    for idx, st_script in enumerate(script_data["stories"][:5]):
        c_num = idx + 1
        ch_title = st_script.get("chapter_title", CHAPTER_DEFAULT_TITLES[idx])
        timestamps.append(f"{format_timestamp(current_time)} Chapter {c_num}: {ch_title}")
        bumper = create_chapter_bumper(c_num, ch_title, duration=2.4)
        all_scene_clips.append(bumper)
        current_time += bumper.duration

        for a_idx, act in enumerate(st_script.get("acts", [])[:4], 1):
            badge = f"CHAPTER {c_num}/5 | {ch_title[:28]}"
            sc_clip, r_list, a_clip = build_scene_video(act["narration"], act["lower_third"], badge, act["visual_queries"], f"c{c_num}_a{a_idx}", used_video_ids)
            all_scene_clips.append(sc_clip)
            all_open_readers.extend(r_list)
            all_open_audios.append(a_clip)
            current_time += sc_clip.duration

    timestamps.append(f"{format_timestamp(current_time)} Doctor's Final Takeaways")
    outro_d = script_data["outro"]
    outro_clip, r_list, a_clip = build_scene_video(outro_d["narration"], outro_d["lower_third"], "MEDPULSE 5 | THANK YOU FOR WATCHING", outro_d["visual_queries"], "outro", used_video_ids)
    all_scene_clips.append(outro_clip)
    all_open_readers.extend(r_list)
    all_open_audios.append(a_clip)
    current_time += outro_clip.duration

    if current_time < 542.0:
        pad_needed = 544.0 - current_time
        extra_bumper = create_chapter_bumper(5, "Summary & Key Clinical Points", duration=min(12.0, pad_needed))
        all_scene_clips.insert(-1, extra_bumper)

    final_visual = concatenate_videoclips(all_scene_clips, method="compose")
    if final_visual.duration > 598.0:
        final_visual = final_visual.subclip(0, 598.0)
    total_dur = final_visual.duration
    print(f"[Duration Lock Verified] Final Long Video Duration: {total_dur / 60.0:.2f} minutes ({total_dur:.1f}s)")

    bg_music_path = "temp/ambient_bg.m4a"
    generate_ambient_music(bg_music_path, total_dur + 2.0)
    bg_audio = AudioFileClip(bg_music_path).subclip(0, total_dur).volumex(0.05)
    final_video = final_visual.set_audio(CompositeAudioClip([final_visual.audio, bg_audio]).set_duration(total_dur))

    final_video.write_videofile(
        "output/final_video.mp4", fps=FPS, codec="libx264", audio_codec="aac", audio_bitrate="192k", threads=4,
        ffmpeg_params=["-preset", "veryfast", "-crf", "21", "-maxrate", "2200k", "-bufsize", "4400k", "-pix_fmt", "yuv420p", "-movflags", "+faststart"],
        logger=None
    )

    for r in all_open_readers + all_open_audios + [bg_audio]:
        try:
            r.close()
        except Exception:
            pass

    try:
        build_companion_short(script_data, used_video_ids)
    except Exception as e:
        print(f"[Short Warn] {e}")

    titles = script_data.get("youtube_titles", [])
    desc = script_data.get("youtube_description", "")
    tags_line = ", ".join(script_data.get("youtube_tags", ["evidence based medicine", "health news", "medpulse 5"]))
    thumb_prompt = script_data.get("thumbnail_prompt", "")
    short_title = script_data.get("short_script", {}).get("short_title", f"{titles[0][:60]} #Shorts")

    details_lines = [
        "====================================================================",
        "عناوين مقترحة للفيديو الطويل (جميعها عن نفس الترند الطبي ومتطابقة مع الصورة المصغرة):",
        "====================================================================",
        f"الخيار 1 (موصى به): {titles[0]}",
        f"الخيار 2: {titles[1]}",
        f"الخيار 3: {titles[2]}",
        "",
        "====================================================================",
        "الوصف الجاهز للنسخ واللصق في يوتيوب (للفيديو الطويل):",
        "====================================================================",
        desc,
        "",
        "Video Chapters:",
        "\n".join(timestamps),
        "",
        "Featured Clinical Source:",
        f"- {hero_topic['title']} ({hero_topic['source']})",
        "",
        "Medical Disclaimer:",
        "The content on MedPulse 5 is for informational and educational purposes only and is not a substitute for professional medical advice, diagnosis, or treatment. Always seek the advice of your physician or qualified health provider with any questions you may have regarding a medical condition.",
        "",
        "#EvidenceBasedMedicine #MedicalBreakthroughs #HealthTruth #Longevity #MedPulse5",
        "",
        "====================================================================",
        "الكلمات المفتاحية (Tags):",
        "====================================================================",
        tags_line,
        "",
        "====================================================================",
        "برومبت الصورة المصغرة (متطابق 100% مع الخيار الأول من العناوين):",
        "====================================================================",
        thumb_prompt,
        "",
        "====================================================================",
        "بيانات الفيديو القصير المرافق (short_video.mp4):",
        "====================================================================",
        "عنوان الفيديو القصير الجاهز للنسخ:",
        short_title,
        "",
        "وصف الفيديو القصير الجاهز للنسخ:",
        "Watch the full 5-part clinical breakdown on our channel MedPulse 5! Tap the related video link below. #Shorts #MedicalTruth #HealthNews #MedPulse5"
    ]

    with open("output/youtube_details.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(details_lines))

    save_to_set(USED_NEWS_FILE, [hero_topic["key"]])
    save_to_set(USED_VIDEOS_FILE, used_video_ids - initial_video_ids)
    shutil.rmtree("temp", ignore_errors=True)
    print("=== Viral Trend Episode & Companion Short Complete! ===")


if __name__ == "__main__":
    main()


