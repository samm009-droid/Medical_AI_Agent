import os
import re
import json
import time
import math
import glob
import random
import asyncio
import datetime
import subprocess
import urllib.parse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import requests
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import edge_tts
import google.generativeai as genai
from moviepy.editor import (
    VideoFileClip,
    ImageClip,
    AudioFileClip,
    CompositeVideoClip,
    CompositeAudioClip,
    concatenate_videoclips,
    concatenate_audioclips,
)
from moviepy.audio.AudioClip import AudioClip

# ==========================================
# 1. إعدادات النظام والمفاتيح السرية
# ==========================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "").strip()

if not GEMINI_API_KEY:
    raise ValueError("Missing GEMINI_API_KEY in environment variables.")
if not PEXELS_API_KEY:
    raise ValueError("Missing PEXELS_API_KEY in environment variables.")

genai.configure(api_key=GEMINI_API_KEY)

USED_NEWS_FILE = "used_news.txt"
USED_VIDEOS_FILE = "used_videos.txt"
FINAL_VIDEO_PATH = "final_video.mp4"
YOUTUBE_DETAILS_PATH = "youtube_details.txt"

VOICE_NAME = "en-US-ChristopherNeural"
VIDEO_W, VIDEO_H = 1280, 720
FPS = 24

# ==========================================
# 2. البحث التلقائي عن شعار القناة في المستودع
# ==========================================
def find_repo_logo():
    """يبحث تلقائياً عن صورة الشعار التي رفعها المستخدم في المستودع."""
    candidates = [
        "logo.png", "logo.jpg", "logo.jpeg", "logo.webp",
        "تنزيل.jpeg", "تنزيل.jpg", "تنزيل.png",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    for ext in ("*.jpeg", "*.jpg", "*.png", "*.webp"):
        for f in glob.glob(ext):
            if not f.startswith("temp_"):
                return f
    return None

CHANNEL_LOGO_PATH = find_repo_logo()
print(f"Detected Channel Logo: {CHANNEL_LOGO_PATH}")

# ==========================================
# 3. المصادر الطبية العالمية (أدوية، أمراض مستعصية، فيتامينات وصحة الجسم)
# ==========================================
RSS_FEEDS = [
    ("Drugs.com New Medications", "https://www.drugs.com/feeds/medical_news.xml"),
    ("Drugs.com Clinical Headlines", "https://www.drugs.com/feeds/headline_news.xml"),
    ("Mayo Clinic Health", "https://newsnetwork.mayoclinic.org/feed/"),
    ("Harvard Health", "https://www.health.harvard.edu/blog/feed"),
    ("MedPage Today", "https://www.medpagetoday.com/rss/headlines.xml"),
    ("SciTechDaily Medicine", "https://scitechdaily.com/tag/medicine/feed/"),
    ("SciTechDaily Health", "https://scitechdaily.com/tag/health/feed/"),
    ("MedicalXpress", "https://medicalxpress.com/rss-feed/"),
    ("News-Medical", "https://www.news-medical.net/tag/feed/Medical-Research.aspx"),
    ("ScienceDaily Health", "https://www.sciencedaily.com/rss/health_medicine.xml"),
    ("ScienceDaily Nutrition & Vitamins", "https://www.sciencedaily.com/rss/health_medicine/nutrition.xml"),
    ("EurekAlert Medicine", "https://www.eurekalert.org/rss/medicine_health.xml"),
]

BANNED_KEYWORDS = [
    "suicide", "self-harm", "abortion", "rape", "sexual assault", "pedophil",
    "porn", "erectile", "genital", "gun violence", "mass shooting", "terrorist",
    "bioweapon", "biological weapon", "overdose death", "cocaine", "heroin",
    "fentanyl", "methamphetamine", "racism", "transgender", "political",
    "homicide", "murder", "autopsy", "mutilat", "execution", "euthanasia"
]

# حظر أبحاث الأحياء النظرية المملة والتجارب غير البشرية والتقارير الإدارية
BORING_LECTURE_KEYWORDS = [
    "fruit flies", "drosophila", "zebrafish", "nematode", "c. elegans", "yeast",
    "protein folding", "ribosome", "transcriptome", "organelle", "chromatin",
    "phylogenetic", "evolutionary", "paleontol", "archaeolog", "botany", "plant cell",
    "hospital billing", "insurance coverage", "medicare policy", "nursing curriculum",
    "medical students", "hospital staffing", "healthcare administration",
    "telehealth survey", "veterinary", "cattle", "poultry", "swine", "crop yield",
    "biophysics", "cryo-em", "x-ray crystallography", "in silico", "computational model"
]

# كلمات الإثارة التي تهم المشاهد العادي (علاجات، أدوية جديدة، فيتامينات، شفاء أمراض مستعصية)
VIRAL_HUMAN_HEALTH_KEYWORDS = [
    "new drug", "pill", "medication", "fda", "approved", "cure", "treatment",
    "therapy", "clinical trial", "reverses", "restores", "heals", "eliminates",
    "vitamin", "supplement", "nutrient", "magnesium", "omega-3", "vitamin d",
    "vitamin b12", "iron", "zinc", "antioxidant", "probiotic", "diet", "fasting",
    "early sign", "warning sign", "symptom", "body", "organ", "chronic",
    "stubborn", "incurable", "deadly", "survival", "pain relief", "blocks",
    "cuts risk", "reduces risk", "prevents", "breakthrough", "game-changer"
]

MEDICAL_PRIORITY_KEYWORDS = [
    "treatment", "therapy", "clinical trial", "breakthrough", "cancer", "tumor",
    "diabetes", "insulin", "blood sugar", "obesity", "weight loss", "metabolism",
    "liver", "kidney", "lung", "stomach", "gut", "colon", "pancreas", "thyroid",
    "heart", "cardiovascular", "artery", "blood pressure", "cholesterol", "stroke",
    "arthritis", "joint pain", "bone", "muscle", "autoimmune", "lupus", "fibromyalgia",
    "vitamin", "supplement", "nutrient", "deficiency", "drug", "pill", "medication",
    "fda", "antibiotic", "vaccine", "immune", "inflammation", "vision", "eye",
    "hearing", "sleep", "insomnia", "migraine", "skin", "alzheimer", "parkinson"
]

# تقسيم الأخبار إلى 5 مجالات عملية مثيرة تمنع الملل وتركز على الأدوية والأمراض والفيتامينات
MEDICAL_DOMAINS = {
    "new_drugs_and_pills": [
        "drug", "pill", "medication", "fda", "approved", "approval", "capsule",
        "tablet", "injection", "pharmaceutical", "prescription", "antibiotic",
        "vaccine", "glp-1", "statin", "painkiller", "inhibitor", "dose"
    ],
    "vitamins_nutrition_and_body": [
        "vitamin", "supplement", "magnesium", "omega-3", "zinc", "iron", "calcium",
        "potassium", "probiotic", "prebiotic", "antioxidant", "nutrient", "deficiency",
        "diet", "nutrition", "fasting", "protein", "fiber", "hydration", "metabolism",
        "weight loss", "fat burning", "obesity", "longevity", "anti-aging"
    ],
    "stubborn_chronic_diseases": [
        "cancer", "tumor", "leukemia", "chemotherapy", "diabetes", "insulin",
        "blood sugar", "autoimmune", "arthritis", "rheumatoid", "lupus", "multiple sclerosis",
        "fibromyalgia", "chronic pain", "migraine", "asthma", "allergy", "psoriasis"
    ],
    "vital_internal_organs": [
        "liver", "fatty liver", "kidney", "renal", "lung", "respiratory", "stomach",
        "ulcer", "gut", "microbiome", "intestin", "colon", "bowel", "pancreas",
        "gallbladder", "thyroid", "bladder", "digestion", "eye", "vision", "retina", "hearing"
    ],
    "heart_blood_and_nerves": [
        "heart", "cardiac", "cardiovascular", "artery", "plaque", "blood pressure",
        "hypertension", "cholesterol", "stroke", "blood clot", "circulation",
        "parkinson", "alzheimer", "dementia", "sleep", "insomnia", "nerve"
    ]
}

FALLBACK_QUERIES = [
    "pharmacist holding medicine pills bottle",
    "doctor talking to patient in clinic",
    "healthy vitamins capsules supplements",
    "medical scientist clinical trial lab",
    "surgeon operating room hospital",
    "red blood cells flowing artery",
    "fresh healthy food vegetables nutrition",
    "cardiologist checking heart monitor",
    "doctor examining x-ray scan",
    "modern hospital corridor doctors",
    "woman taking daily vitamin pill",
    "senior patient smiling with doctor",
    "pharmaceutical factory medicine production",
    "healthy human heart beat 3d",
    "vaccine vial syringe medical",
    "doctor checking patient blood pressure",
    "medical researcher looking at monitor",
    "CT scan diagnostic hospital room",
    "immune system cells fighting virus",
    "people exercising outdoors healthy lifestyle",
    "doctor prescribing medication clinic",
    "deep sleep rest bedroom night",
    "ophthalmologist eye vision exam",
    "physical therapy joint pain relief",
    "blood test tube medical laboratory"
]

def load_set_file(filepath):
    if not os.path.exists(filepath):
        return set()
    with open(filepath, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def append_set_file(filepath, items):
    with open(filepath, "a", encoding="utf-8") as f:
        for item in items:
            f.write(f"{item}\n")

def clean_html(raw_html):
    if not raw_html:
        return ""
    cleanr = re.compile("<.*?>")
    text = re.sub(cleanr, " ", raw_html)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def is_safe_and_exciting_for_viewers(title, summary):
    combined = (title + " " + summary).lower()
    for bad in BANNED_KEYWORDS:
        if bad.lower() in combined:
            return False
    for boring in BORING_LECTURE_KEYWORDS:
        if boring.lower() in combined:
            return False
    if ("mice" in combined or "mouse" in combined or "rodent" in combined):
        if not any(w in combined for w in ["drug", "pill", "treatment", "therapy", "cure", "cancer", "diabetes", "reverse", "human", "patient", "vitamin"]):
            return False

    score = sum(1 for kw in MEDICAL_PRIORITY_KEYWORDS if kw in combined)
    return score >= 1

def classify_medical_domain(title, summary):
    combined = (title + " " + summary).lower()
    title_low = title.lower()
    best_domain = "stubborn_chronic_diseases"
    best_hits = 0

    domain_order = [
        "new_drugs_and_pills",
        "vitamins_nutrition_and_body",
        "stubborn_chronic_diseases",
        "vital_internal_organs",
        "heart_blood_and_nerves"
    ]
    for dom in domain_order:
        kws = MEDICAL_DOMAINS[dom]
        hits = sum(2 if kw in title_low else (1 if kw in combined else 0) for kw in kws)
        if hits > best_hits:
            best_hits = hits
            best_domain = dom
    return best_domain

def calculate_viral_and_freshness_rank(title, summary, dt, domain):
    now = datetime.datetime.now(datetime.timezone.utc)
    hours_old = max(0.0, (now - dt).total_seconds() / 3600.0)

    if hours_old <= 24:
        freshness_pts = 14
    elif hours_old <= 48:
        freshness_pts = 10
    elif hours_old <= 72:
        freshness_pts = 6
    else:
        freshness_pts = 2

    combined = (title + " " + summary).lower()
    title_low = title.lower()

    med_pts = sum(1 for kw in MEDICAL_PRIORITY_KEYWORDS if kw in combined)
    viral_pts = sum(3 if kw in title_low else (2 if kw in combined else 0) for kw in VIRAL_HUMAN_HEALTH_KEYWORDS)

    domain_bonus = 5 if domain in ("new_drugs_and_pills", "vitamins_nutrition_and_body", "stubborn_chronic_diseases") else 2

    return freshness_pts + med_pts + viral_pts + domain_bonus

def parse_rss_date(date_str):
    now = datetime.datetime.now(datetime.timezone.utc)
    if not date_str:
        return now
    try:
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        if dt > now:
            dt = now
        return dt
    except Exception:
        return now

def fetch_top_5_medical_news():
    used_links = load_set_file(USED_NEWS_FILE)
    candidates = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    for source_name, url in RSS_FEEDS:
        try:
            resp = requests.get(url, headers=headers, timeout=20)
            if resp.status_code != 200:
                continue
            root = ET.fromstring(resp.content)
            for item in root.findall(".//item"):
                title = clean_html(item.findtext("title") or "")
                link = (item.findtext("link") or "").strip()
                desc = clean_html(item.findtext("description") or "")
                pub_date_raw = item.findtext("pubDate") or ""

                if not title or not link:
                    continue
                if link in used_links:
                    continue
                if not is_safe_and_exciting_for_viewers(title, desc):
                    continue

                dt = parse_rss_date(pub_date_raw)
                domain = classify_medical_domain(title, desc)
                total_rank = calculate_viral_and_freshness_rank(title, desc, dt, domain)

                candidates.append({
                    "source": source_name,
                    "title": title,
                    "link": link,
                    "summary": desc[:850],
                    "datetime": dt,
                    "date_str": dt.strftime("%B %d, %Y"),
                    "domain": domain,
                    "score": total_rank
                })
        except Exception as e:
            print(f"RSS warning for {source_name}: {e}")

    candidates.sort(key=lambda x: (x["score"], x["datetime"]), reverse=True)

    selected = []
    seen_titles = set()
    source_counts = {}
    domain_counts = {}

    for item in candidates:
        norm_title = re.sub(r"[^a-z0-9]", "", item["title"].lower())[:45]
        if norm_title in seen_titles:
            continue
        src = item["source"]
        dom = item["domain"]

        if domain_counts.get(dom, 0) >= 1:
            continue
        if source_counts.get(src, 0) >= 2 and len(candidates) > 12:
            continue

        selected.append(item)
        seen_titles.add(norm_title)
        source_counts[src] = source_counts.get(src, 0) + 1
        domain_counts[dom] = domain_counts.get(dom, 0) + 1
        if len(selected) == 5:
            break

    if len(selected) < 5:
        for item in candidates:
            if item in selected:
                continue
            norm_title = re.sub(r"[^a-z0-9]", "", item["title"].lower())[:45]
            if norm_title in seen_titles:
                continue
            dom = item["domain"]
            if domain_counts.get(dom, 0) >= 2 and len(candidates) > 10:
                continue

            selected.append(item)
            seen_titles.add(norm_title)
            domain_counts[dom] = domain_counts.get(dom, 0) + 1
            if len(selected) == 5:
                break

    if len(selected) < 5:
        for item in candidates:
            if item not in selected:
                selected.append(item)
                if len(selected) == 5:
                    break

    if len(selected) < 5:
        raise RuntimeError(f"Not enough fresh medical news found. Only found {len(selected)}.")

    return selected

# ==========================================
# 4. توليد السيناريو المشوق والعناوين البحثية القوية
# ==========================================
def clean_json_text(text):
    cleaned = re.sub(r"^\x60{3}(?:json)?\s*", "", text.strip())
    cleaned = re.sub(r"\s*\x60{3}$", "", cleaned.strip())
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start:end + 1]
    return cleaned

def get_available_gemini_models():
    preferred = [
        "gemini-3-flash-preview",
        "gemini-2.5-flash-lite",
        "gemini-flash-lite-latest",
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-flash-latest",
    ]
    available = []
    try:
        for m in genai.list_models():
            if "generateContent" in getattr(m, "supported_generation_methods", []):
                name = m.name.replace("models/", "")
                available.append(name)
    except Exception as e:
        print(f"Warning listing models: {e}")

    ordered = [m for m in preferred if m in available]
    for m in available:
        if m not in ordered and ("flash" in m or "pro" in m):
            ordered.append(m)
    return ordered if ordered else preferred

# عبارات وأسئلة مصغرة مدققة لغوياً وإملائياً 100% ومصنفة حسب موضوع الخبر
VERIFIED_THUMBNAIL_HOOKS = {
    "new_drugs_and_pills": [
        "NEW MIRACLE PILL?",
        "GAME CHANGING DRUG!",
        "ONE PILL FIXES THIS?",
        "NEW FDA BREAKTHROUGH!",
        "DOCTORS STUNNED!"
    ],
    "vitamins_nutrition_and_body": [
        "VITAMIN WARNING!",
        "HEALS YOUR BODY!",
        "DAILY HABIT DANGER?",
        "THE MISSING VITAMIN?",
        "REPAIRS YOUR ORGANS!"
    ],
    "stubborn_chronic_diseases": [
        "IS THIS THE CURE?",
        "FINALLY A CURE?",
        "STOPS DISEASE FAST!",
        "HOPE FOR MILLIONS!",
        "REVERSING DISEASE?"
    ],
    "vital_internal_organs": [
        "SAVE YOUR ORGANS!",
        "SILENT BODY WARNING!",
        "HEALS LIVER & KIDNEY?",
        "HIDDEN ORGAN RISK!",
        "CLEANSE YOUR BODY?"
    ],
    "heart_blood_and_nerves": [
        "CLEAN YOUR ARTERIES?",
        "SILENT HEART SIGN!",
        "BLOOD PRESSURE FIX?",
        "PROTECT YOUR HEART!",
        "WARNING IN YOUR BLOOD!"
    ]
}

def generate_script_with_gemini(news_items):
    pacing_profiles = [
        {"target_label": "10 to 11 minutes", "words_per_act": "75 to 85 words", "min_words": 72},
        {"target_label": "11.5 to 12.5 minutes", "words_per_act": "88 to 98 words", "min_words": 84},
        {"target_label": "13 to 14 minutes", "words_per_act": "102 to 112 words", "min_words": 96},
        {"target_label": "14 to 15 minutes", "words_per_act": "115 to 126 words", "min_words": 108},
    ]
    profile = random.choice(pacing_profiles)
    print(f"Selected Episode Pacing Profile: {profile['target_label']} ({profile['words_per_act']} per act)")

    non_brain_candidates = [
        (idx, it) for idx, it in enumerate(news_items, 1)
        if "brain" not in (it["title"] + " " + it["summary"]).lower()
        and "alzheimer" not in (it["title"] + " " + it["summary"]).lower()
        and "dementia" not in (it["title"] + " " + it["summary"]).lower()
    ]
    if non_brain_candidates:
        thumb_story_idx, thumb_story_item = random.choice(non_brain_candidates)
    else:
        thumb_story_idx, thumb_story_item = 1, news_items[0]

    thumb_domain = thumb_story_item.get("domain", "new_drugs_and_pills")
    verified_hook = random.choice(VERIFIED_THUMBNAIL_HOOKS.get(thumb_domain, VERIFIED_THUMBNAIL_HOOKS["new_drugs_and_pills"]))

    color_palettes = [
        "vibrant emerald green, warm gold, and deep clinical navy",
        "crimson red, glowing amber gold, and dark cinematic teal",
        "radiant golden-orange, electric cyan, and deep obsidian",
        "ruby red, bright turquoise, and clean laboratory white",
        "royal purple, glowing magenta, and bright silver-white"
    ]
    chosen_palette = random.choice(color_palettes)

    news_blob = ""
    for idx, item in enumerate(news_items, 1):
        news_blob += (
            f"STORY {idx} (Focus: {item.get('domain', 'medicine')}):\n"
            f"Title: {item['title']}\n"
            f"Summary: {item['summary']}\n\n"
        )

    prompt = f"""
You are a charismatic, captivating, world-class medical TV host and YouTube SEO strategist for the hit channel "MedPulse 5".
Your mission is to turn these 5 real medical breakthroughs into an exciting, suspenseful, deeply relatable health show for everyday viewers.
Target total video duration for today's episode: {profile['target_label']}.

INPUT STORIES:
{news_blob}

STRICT ANTI-LECTURE RULES (READ CAREFULLY!):
1. DO NOT sound like a biology professor, textbook, or dry academic research report!
2. FORBIDDEN: Never bore the viewer with complicated molecular receptor names, dry statistics, or university lecture tone.
3. MAKE IT EXCITING & PERSONAL: Every single sentence must connect directly to the viewer's own human body, their daily symptoms, their kitchen vitamins, their organs (liver, kidneys, heart, gut, eyes, joints), new life-saving pills/drugs, and real hope for stubborn or chronic diseases!
4. Speak directly to the viewer ("you", "your body", "your organs", "your daily health") with warmth, suspense, and excitement.
5. NEVER say website names (like MedicalXpress, ScienceDaily, EurekAlert, MedPage, SciTechDaily, Drugs.com) or publication dates out loud!
6. Each of the 5 stories MUST be divided into 4 thrilling, viewer-focused acts:
   - Act 1: The Body Mystery & Warning Sign (Hook the viewer with how this disease, symptom, or vitamin deficiency secretly affects the human body in daily life).
   - Act 2: The Game-Changing Breakthrough (Reveal the exciting new drug, pill, vitamin effect, or treatment for a stubborn disease in simple, dramatic everyday language).
   - Act 3: What Happens Inside Your Body (Vividly explain how this treatment, medication, or nutrient heals, protects, or repairs human organs and blood from within).
   - Act 4: How This Changes Your Health & Future (Practical takeaway for the viewer's life, real hope for patients, and what this means for your body starting today).
7. LENGTH REQUIREMENT: Each of the 20 acts (5 stories x 4 acts) MUST contain {profile['words_per_act']} of natural spoken narration.
8. For EVERY act, provide 3 distinct, specific visual Pexels search queries (3 to 5 English words each, focusing on medicine pills, vitamins, doctors with patients, specific human organs, blood flow, healthy food, joint pain relief, hospital care).
9. YOUTUBE SEARCH SEO TITLE RULES (CRITICAL FOR ALL 3 `youtube_titles`):
   - Every title MUST be 70 to 92 characters long.
   - THE FIRST 4 WORDS RULE: The first 3 to 5 words of EVERY title MUST be high-volume everyday health search keywords that millions of people type into YouTube Search daily (e.g., "New Pill Stops Cancer", "Fatty Liver & Kidney Repair", "Vitamin D & Gut Relief", "Lowering Blood Pressure Fast", "Reversing Diabetes & Heart Damage", "Early Warning Signs of...").
   - STRICTLY FORBIDDEN IN TITLES: NEVER start a title with technical academic jargon (like "CRISPR", "AI Mapping", "mRNA", "Nanoparticles") or vague textbook phrases (like "From X to Y: The New Science of...").
   - END BOOSTER RULE: End each title with a strong search-boosting hook in parentheses or after a colon, such as "(Major Treatment Breakthrough)", "(Hidden Diet Warning)", or ": 5 New Treatments Saving Lives".
   - Title #1 MUST be the strongest #1 recommended search + curiosity title.
10. For `thumbnail_prompt`: Base the visual strictly on STORY #{thumb_story_idx} ("{thumb_story_item['title']}").
    - STRICTLY FORBIDDEN: Do NOT draw a human brain, head silhouette, or neural synapses!
    - Depict a concrete, exciting medical visual from Story #{thumb_story_idx} (such as a glowing translucent medicine pill/capsule, golden vitamin softgels, human heart/liver/kidneys/lungs/gut, or blood cells healing).
    - Use a rich color palette featuring {chosen_palette}.
    - LINGUISTIC ACCURACY RULE: Instruct the image generator to render the EXACT verified English text "{verified_hook}" in LARGE BOLD GLOWING YELLOW AND WHITE SANS-SERIF LETTERS on the left side, with 100% exact spelling and clear typography.

Return ONLY valid JSON matching this exact structure (no markdown fences, no extra commentary):
{{
  "youtube_titles": [
    "High-Search First 4 Words + Exciting Breakthrough Hook! (Major Treatment Breakthrough)",
    "Specific Disease/Vitamin/Organ Search Term + 5 New Treatments That Repair Your Body",
    "Early Warning Sign / New Pill Search Term & How It Protects Your Organs (Health Alert)"
  ],
  "youtube_description": "3-paragraph engaging SEO description summarizing the 5 breakthroughs and how they impact human health",
  "youtube_tags": "tag1, tag2, tag3, ... (15 high-volume search tags)",
  "thumbnail_prompt": "Ultra-realistic 16:9 cinematic medical illustration of [specific non-brain visual from Story #{thumb_story_idx}], rich color palette of {chosen_palette}, dramatic lighting, 8k resolution, with large bold glowing yellow and white sans-serif text on the left side with exact spelling that says \\"{verified_hook}\\"",
  "hook_narration": "55 to 70 words thrilling opening hook welcoming viewers to MedPulse 5 and teasing today's new treatments, medications, and body discoveries",
  "hook_queries": ["pharmacist medicine pills", "doctor talking to patient", "healthy vitamins capsules"],
  "stories": [
    {{
      "story_number": 1,
      "chapter_title": "Short Exciting Chapter Title (max 42 chars)",
      "lower_third": "Short Punchy Headline (max 52 chars)",
      "acts": [
        {{
          "act_number": 1,
          "narration": "Spoken narration of {profile['words_per_act']}...",
          "search_queries": ["query one", "query two", "query three"]
        }},
        {{
          "act_number": 2,
          "narration": "Spoken narration of {profile['words_per_act']}...",
          "search_queries": ["query one", "query two", "query three"]
        }},
        {{
          "act_number": 3,
          "narration": "Spoken narration of {profile['words_per_act']}...",
          "search_queries": ["query one", "query two", "query three"]
        }},
        {{
          "act_number": 4,
          "narration": "Spoken narration of {profile['words_per_act']}...",
          "search_queries": ["query one", "query two", "query three"]
        }}
      ]
    }}
  ],
  "outro_narration": "55 to 70 words warm conclusion inviting viewers to subscribe to MedPulse 5 and share which breakthrough gave them the most hope",
  "outro_queries": ["doctor smiling hospital", "healthy senior couple walking", "modern medical clinic"]
}}
"""

    models_to_try = get_available_gemini_models()
    last_err = None

    for model_name in models_to_try:
        for attempt in range(2):
            try:
                print(f"Trying Gemini model: {model_name} (Attempt {attempt+1})...")
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(
                    prompt,
                    generation_config={"temperature": 0.72},
                    request_options={"timeout": 90}
                )
                raw_text = response.text
                cleaned = clean_json_text(raw_text)
                data = json.loads(cleaned)
                if "stories" in data and len(data["stories"]) == 5:
                    tp = data.get("thumbnail_prompt", "")
                    if verified_hook not in tp:
                        tp = re.sub(r'says\s+"[^"]*"', f'says "{verified_hook}"', tp)
                        if verified_hook not in tp:
                            tp = f'{tp}, with large bold glowing yellow and white sans-serif text on the left side with exact spelling that says "{verified_hook}"'
                        data["thumbnail_prompt"] = tp
                    print(f"Successfully generated script with {model_name}!")
                    return data
            except Exception as e:
                last_err = e
                print(f"Model {model_name} failed: {e}")
                time.sleep(3)

    raise RuntimeError(f"All Gemini models failed. Last error: {last_err}")

# ==========================================
# 5. توليد الصوت الاحترافي مع حماية ضد التوقف
# ==========================================
async def _edge_tts_save(text, out_path):
    communicate = edge_tts.Communicate(text, VOICE_NAME, rate="+4%", pitch="-1Hz")
    await asyncio.wait_for(communicate.save(out_path), timeout=40.0)

def generate_tts(text, out_path):
    clean_text = re.sub(r"\s+", " ", text).strip()
    for attempt in range(5):
        try:
            if os.path.exists(out_path):
                os.remove(out_path)
            asyncio.run(_edge_tts_save(clean_text, out_path))
            if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
                return out_path
        except Exception as e:
            print(f"TTS attempt {attempt+1} failed for {out_path}: {e}")
            time.sleep(2 + attempt * 2)
    raise RuntimeError(f"Failed to generate TTS audio for {out_path}")

# ==========================================
# 6. تحميل وتطبيع مقاطع الفيديو عالية الدقة (منع التجميد والغبش + تسريع المعالجة)
# ==========================================
def normalize_clip_hd(raw_path, norm_path):
    """
    يحول المقطع إلى دقة 1280x720 فائقة الوضوح و24 إطاراً ثابتاً لمنع التجميد،
    مع معالجة أول 14 ثانية فقط من المقطع الخام لاختصار وقت التوليد إلى النصف دون أي مساس بالجودة.
    """
    cmd = [
        "ffmpeg", "-y",
        "-t", "14",
        "-i", raw_path,
        "-vf", "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,fps=24,format=yuv420p",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "19",
        "-an",
        norm_path
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return res.returncode == 0 and os.path.exists(norm_path) and os.path.getsize(norm_path) > 20000

def search_and_download_pexels_clips(queries, count_needed, used_video_ids, prefix):
    headers = {"Authorization": PEXELS_API_KEY}
    downloaded_paths = []

    search_pool = list(queries) if queries else []
    shuffled_fallbacks = list(FALLBACK_QUERIES)
    random.shuffle(shuffled_fallbacks)
    search_pool.extend(shuffled_fallbacks)

    for q in search_pool:
        if len(downloaded_paths) >= count_needed:
            break
        try:
            url = f"https://api.pexels.com/videos/search?query={urllib.parse.quote(q)}&per_page=40&orientation=landscape"
            r = requests.get(url, headers=headers, timeout=20)
            if r.status_code != 200:
                continue
            videos = r.json().get("videos", [])
            random.shuffle(videos)

            for v in videos:
                if len(downloaded_paths) >= count_needed:
                    break
                vid_id = str(v.get("id", ""))
                duration = v.get("duration", 0)
                if not vid_id or vid_id in used_video_ids:
                    continue
                if duration < 6 or duration > 90:
                    continue

                v_files = v.get("video_files", [])
                hd_files = [
                    vf for vf in v_files
                    if vf.get("file_type") == "video/mp4"
                    and 1280 <= (vf.get("width") or 0) <= 2560
                    and (vf.get("height") or 0) >= 720
                ]
                if not hd_files:
                    continue

                hd_files.sort(key=lambda x: (x.get("width") or 0), reverse=True)
                chosen_file = hd_files[0]
                dl_link = chosen_file.get("link")
                if not dl_link:
                    continue

                idx = len(downloaded_paths)
                raw_path = f"temp_raw_{prefix}_{idx}_{vid_id}.mp4"
                norm_path = f"temp_norm_{prefix}_{idx}_{vid_id}.mp4"

                vr = requests.get(dl_link, stream=True, timeout=30)
                if vr.status_code == 200:
                    with open(raw_path, "wb") as f:
                        for chunk in vr.iter_content(chunk_size=65536):
                            if chunk:
                                f.write(chunk)

                    if normalize_clip_hd(raw_path, norm_path):
                        used_video_ids.add(vid_id)
                        downloaded_paths.append(norm_path)
                    if os.path.exists(raw_path):
                        os.remove(raw_path)
        except Exception as e:
            print(f"Pexels search warning for '{q}': {e}")

    return downloaded_paths

def build_visual_track(clip_paths, target_duration):
    """
    يركب المقاطع المرئية بدون تكرار نفس الكائن البرمجي أبداً لمنع تجميد الصورة،
    مع فتح قارئ فيديو مستقل لكل جزء.
    """
    if not clip_paths:
        bg = Image.new("RGB", (VIDEO_W, VIDEO_H), (12, 22, 38))
        return ImageClip(np.array(bg)).set_duration(target_duration)

    num_clips = len(clip_paths)
    seg_dur = target_duration / num_clips
    segments = []

    for path in clip_paths:
        try:
            vc = VideoFileClip(path, audio=False)
            safe_max = max(0.5, vc.duration - 0.15)

            if safe_max >= seg_dur:
                max_start = max(0.0, safe_max - seg_dur)
                start_t = random.uniform(0.0, min(1.5, max_start))
                sub = vc.subclip(start_t, start_t + seg_dur)
                segments.append(sub)
            else:
                vc.close()
                rem = seg_dur
                parts = []
                while rem > 0.05:
                    fresh_vc = VideoFileClip(path, audio=False)
                    fresh_max = max(0.5, fresh_vc.duration - 0.15)
                    take = min(rem, fresh_max)
                    parts.append(fresh_vc.subclip(0, take))
                    rem -= take
                segments.append(concatenate_videoclips(parts, method="compose"))
        except Exception as e:
            print(f"Warning loading clip {path}: {e}")

    if not segments:
        bg = Image.new("RGB", (VIDEO_W, VIDEO_H), (12, 22, 38))
        return ImageClip(np.array(bg)).set_duration(target_duration)

    combined = concatenate_videoclips(segments, method="compose")
    return combined.set_duration(target_duration)

# ==========================================
# 7. تصميم الرسوميات والشارات الاحترافية (MedPulse 5)
# ==========================================
def get_font(size, bold=True):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for c in candidates:
        if os.path.exists(c):
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                pass
    return ImageFont.load_default()

def load_circular_logo(size=68):
    if not CHANNEL_LOGO_PATH or not os.path.exists(CHANNEL_LOGO_PATH):
        return None
    try:
        img = Image.open(CHANNEL_LOGO_PATH).convert("RGBA")
        img = img.resize((size, size), Image.Resampling.LANCZOS)
        mask = Image.new("L", (size, size), 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0, size - 1, size - 1), fill=235)

        out = Image.new("RGBA", (size + 6, size + 6), (0, 0, 0, 0))
        border_draw = ImageDraw.Draw(out)
        border_draw.ellipse((0, 0, size + 5, size + 5), outline=(0, 215, 255, 220), width=2)
        out.paste(img, (3, 3), mask)
        return out
    except Exception as e:
        print(f"Logo load warning: {e}")
        return None

def create_overlay_png(story_num, lower_third_text, out_png):
    img = Image.new("RGBA", (VIDEO_W, VIDEO_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    logo_img = load_circular_logo(68)
    if logo_img:
        img.paste(logo_img, (VIDEO_W - 68 - 24, 22), logo_img)

    if lower_third_text:
        bar_y = 644
        bar_h = 76
        draw.rectangle([0, bar_y, VIDEO_W, VIDEO_H], fill=(8, 16, 28, 225))
        draw.rectangle([0, bar_y, VIDEO_W, bar_y + 3], fill=(0, 210, 255, 255))
        draw.rectangle([0, bar_y, 12, VIDEO_H], fill=(0, 210, 255, 255))

        f_tag = get_font(15, bold=True)
        f_main = get_font(24, bold=True)

        tag_label = f"MEDPULSE 5  |  BREAKTHROUGH #{story_num}" if story_num else "MEDPULSE 5  |  DAILY MEDICAL BRIEFING"
        draw.text((48, bar_y + 11), tag_label, font=f_tag, fill=(0, 215, 255, 255))
        draw.text((48, bar_y + 35), lower_third_text[:58].upper(), font=f_main, fill=(255, 255, 255, 255))

    img.save(out_png)
    return out_png

def make_chime_audio(duration=2.4, fps=44100):
    def make_frame(t):
        t_arr = np.atleast_1d(t)
        env = np.exp(-2.2 * t_arr)
        wave = 0.14 * env * (
            np.sin(2 * np.pi * 528.0 * t_arr) +
            0.6 * np.sin(2 * np.pi * 792.0 * t_arr) +
            0.3 * np.sin(2 * np.pi * 1056.0 * t_arr)
        )
        res = np.column_stack([wave, wave])
        return res[0] if np.ndim(t) == 0 else res
    return AudioClip(make_frame, duration=duration, fps=fps)

def create_chapter_bumper(story_num, chapter_title, duration=2.4):
    img = Image.new("RGB", (VIDEO_W, VIDEO_H), (7, 15, 26))
    draw = ImageDraw.Draw(img)

    for y in range(0, VIDEO_H, 40):
        draw.line([(0, y), (VIDEO_W, y)], fill=(14, 28, 46), width=1)
    for x in range(0, VIDEO_W, 40):
        draw.line([(x, 0), (x, VIDEO_H)], fill=(14, 28, 46), width=1)

    draw.rectangle([140, 210, VIDEO_W - 140, 510], fill=(11, 24, 42), outline=(0, 210, 255), width=3)

    logo_img = load_circular_logo(84)
    if logo_img:
        img.paste(logo_img, (VIDEO_W // 2 - 42, 230), logo_img)
        num_y = 330
    else:
        num_y = 265

    f_sub = get_font(22, bold=True)
    f_title = get_font(36, bold=True)

    header_txt = f"MEDPULSE 5  •  STORY #{story_num}"
    hw = draw.textlength(header_txt, font=f_sub)
    draw.text(((VIDEO_W - hw) / 2, num_y), header_txt, font=f_sub, fill=(0, 215, 255))

    clean_title = chapter_title[:44].upper()
    tw = draw.textlength(clean_title, font=f_title)
    draw.text(((VIDEO_W - tw) / 2, num_y + 52), clean_title, font=f_title, fill=(255, 255, 255))

    clip = ImageClip(np.array(img)).set_duration(duration)
    clip = clip.set_audio(make_chime_audio(duration))
    return clip

def make_ambient_pad(duration, fps=44100):
    def make_frame(t):
        t_arr = np.atleast_1d(t)
        wave = 0.015 * (
            np.sin(2 * np.pi * 110.0 * t_arr) +
            0.5 * np.sin(2 * np.pi * 165.0 * t_arr)
        )
        res = np.column_stack([wave, wave])
        return res[0] if np.ndim(t) == 0 else res
    return AudioClip(make_frame, duration=duration, fps=fps)

# ==========================================
# 8. بناء المشاهد وتجميع الفيديو النهائي
# ==========================================
def build_spoken_scene(narration_text, queries, story_num, lower_third, used_video_ids, scene_tag):
    aud_path = f"temp_aud_{scene_tag}.mp3"
    generate_tts(narration_text, aud_path)

    raw_audio = AudioFileClip(aud_path)
    safe_aud_dur = max(0.2, raw_audio.duration - 0.08)
    audio_clip = raw_audio.subclip(0, safe_aud_dur)
    dur = safe_aud_dur + 0.20

    clips_needed = 4 if dur > 26 else 3
    clip_paths = search_and_download_pexels_clips(queries, clips_needed, used_video_ids, scene_tag)

    visual_bg = build_visual_track(clip_paths, dur)

    ov_path = f"temp_ov_{scene_tag}.png"
    create_overlay_png(story_num, lower_third, ov_path)
    ov_clip = ImageClip(ov_path).set_duration(dur)

    comp = CompositeVideoClip([visual_bg, ov_clip], size=(VIDEO_W, VIDEO_H)).set_duration(dur)
    comp = comp.set_audio(audio_clip)
    return comp, dur

def format_timestamp(seconds):
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"

def main():
    print("1. Fetching top 5 exciting medical stories (new drugs, stubborn disease cures, vitamins & organs)...")
    news_items = fetch_top_5_medical_news()
    for i, it in enumerate(news_items, 1):
        print(f"  Story {i} [{it.get('domain')}]: {it['title']} ({it['source']} - Score: {it.get('score')})")

    print("2. Generating captivating, non-lecture medical TV script & SEO titles via Gemini...")
    script_data = generate_script_with_gemini(news_items)

    used_video_ids = load_set_file(USED_VIDEOS_FILE)
    initial_known_videos = set(used_video_ids)

    timeline_clips = []
    current_time = 0.0
    timestamps = [("00:00", "Introduction: Today's Top 5 Medical Breakthroughs")]

    print("3. Building Intro Hook...")
    hook_clip, hook_dur = build_spoken_scene(
        script_data["hook_narration"],
        script_data.get("hook_queries", ["pharmacist medicine pills", "doctor talking to patient"]),
        story_num=None,
        lower_third="TODAY'S TOP 5 MEDICAL BREAKTHROUGHS",
        used_video_ids=used_video_ids,
        scene_tag="hook"
    )
    timeline_clips.append(hook_clip)
    current_time += hook_dur

    for idx, story in enumerate(script_data["stories"], 1):
        ch_title = story.get("chapter_title", f"Medical Breakthrough #{idx}")
        l_third = story.get("lower_third", ch_title)
        timestamps.append((format_timestamp(current_time), f"Story #{idx}: {ch_title}"))

        print(f"4.{idx} Building Chapter Bumper & 4 Acts for Story #{idx}...")
        bumper = create_chapter_bumper(idx, ch_title, duration=2.4)
        timeline_clips.append(bumper)
        current_time += 2.4

        for act in story["acts"]:
            act_num = act.get("act_number", 1)
            tag = f"s{idx}_a{act_num}"
            scene_clip, scene_dur = build_spoken_scene(
                act["narration"],
                act.get("search_queries", []),
                story_num=idx,
                lower_third=l_third,
                used_video_ids=used_video_ids,
                scene_tag=tag
            )
            timeline_clips.append(scene_clip)
            current_time += scene_dur

    print("5. Building Outro...")
    timestamps.append((format_timestamp(current_time), "Conclusion & Health Takeaway"))
    outro_clip, outro_dur = build_spoken_scene(
        script_data["outro_narration"],
        script_data.get("outro_queries", ["healthy lifestyle", "modern hospital"]),
        story_num=None,
        lower_third="SUBSCRIBE TO MEDPULSE 5 FOR DAILY UPDATES",
        used_video_ids=used_video_ids,
        scene_tag="outro"
    )
    timeline_clips.append(outro_clip)
    current_time += outro_dur

    print(f"Total assembled video duration: {current_time/60:.2f} minutes.")
    final_video = concatenate_videoclips(timeline_clips, method="compose")

    ambient = make_ambient_pad(final_video.duration)
    mixed_audio = CompositeAudioClip([final_video.audio, ambient])
    final_video = final_video.set_audio(mixed_audio)

    print("6. Rendering final HD video (1280x720, crisp visual quality)...")
    final_video.write_videofile(
        FINAL_VIDEO_PATH,
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        audio_bitrate="128k",
        preset="veryfast",
        threads=4,
        ffmpeg_params=[
            "-crf", "21",
            "-maxrate", "2200k",
            "-bufsize", "4400k",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart"
        ]
    )

    # حفظ الأخبار والمقاطع المرئية المستخدمة لعدم تكرارها مستقبلاً
    append_set_file(USED_NEWS_FILE, [it["link"] for it in news_items])
    new_vids = used_video_ids - initial_known_videos
    if new_vids:
        append_set_file(USED_VIDEOS_FILE, list(new_vids))

    # تجهيز خيارات العناوين الثلاثة البحثية مع علامة (موصى به)
    titles_list = script_data.get("youtube_titles", [])
    if not isinstance(titles_list, list) or len(titles_list) == 0:
        single_t = script_data.get("youtube_title", "New Pill & Vitamin Breakthroughs That Repair Your Organs! (Major Health Update)")
        titles_list = [
            single_t,
            "Reversing Organ Damage & Chronic Disease: 5 New Treatments Saving Lives",
            "Early Body Warning Signs & New Medications You Need to Know Today"
        ]
    while len(titles_list) < 3:
        titles_list.append(titles_list[0])

    titles_block = (
        f"الخيار 1 (موصى به):\n{titles_list[0]}\n\n"
        f"الخيار 2:\n{titles_list[1]}\n\n"
        f"الخيار 3:\n{titles_list[2]}"
    )

    # إعداد ملف تفاصيل اليوتيوب الجاهز للنسخ واللصق
    ts_block = "\n".join([f"{t} - {label}" for t, label in timestamps])
    src_block = "\n".join([f"{i}. {it['title']} ({it['source']}):\n{it['link']}" for i, it in enumerate(news_items, 1)])

    details_content = f"""==================================================
1. YOUTUBE TITLES (اختر عنواناً واحداً فقط من العناوين البحثية الثلاثة التالية وضعه في خانة العنوان):
==================================================
{titles_block}

==================================================
2. YOUTUBE DESCRIPTION (انسخ هذا الوصف بالكامل وضعه في خانة الوصف):
==================================================
{script_data.get('youtube_description', '')}

TIMESTAMPS / CHAPTERS:
{ts_block}

SCIENTIFIC SOURCES & REFERENCES:
{src_block}

MEDICAL DISCLAIMER:
The content on MedPulse 5 is for informational and educational purposes only and does not substitute professional medical advice, diagnosis, or treatment. Always consult your physician or qualified healthcare provider with any questions you may have regarding a medical condition.

#MedPulse5 #MedicalBreakthroughs #HealthNews #NewTreatments #Vitamins #Medicine

==================================================
3. YOUTUBE TAGS (انسخ هذه الكلمات المفتاحية وضعها في خانة العلامات Tags):
==================================================
{script_data.get('youtube_tags', 'medical breakthroughs, new medications, vitamins, disease cures, health news, MedPulse 5')}

==================================================
4. AI THUMBNAIL PROMPT (انسخ هذا الوصف وضعه في موقع الصور لتوليد صورة مصغرة متنوعة ومدققة لغوياً):
==================================================
{script_data.get('thumbnail_prompt', 'Dramatic ultra-realistic 16:9 medical illustration showing a glowing translucent pharmaceutical capsule and golden vitamin softgels healing human organs, emerald and crimson cinematic lighting, 8k, with large bold glowing yellow and white sans-serif text on the left side with exact spelling that says "NEW MIRACLE PILL?"')}
"""
    with open(YOUTUBE_DETAILS_PATH, "w", encoding="utf-8") as f:
        f.write(details_content)

    # تنظيف الملفات المؤقتة
    for pattern in ("temp_raw_*.mp4", "temp_norm_*.mp4", "temp_aud_*.mp3", "temp_ov_*.png"):
        for fpath in glob.glob(pattern):
            try:
                os.remove(fpath)
            except Exception:
                pass

    print("All done successfully!")

if __name__ == "__main__":
    main()
