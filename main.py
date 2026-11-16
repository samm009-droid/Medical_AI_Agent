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
# 3. المصادر الطبية العالمية الكبرى ونظام التنويع والترند
# ==========================================
RSS_FEEDS = [
    ("MedicalXpress", "https://medicalxpress.com/rss-feed/"),
    ("SciTechDaily Medicine", "https://scitechdaily.com/tag/medicine/feed/"),
    ("SciTechDaily Health", "https://scitechdaily.com/tag/health/feed/"),
    ("Drugs.com Medical News", "https://www.drugs.com/feeds/medical_news.xml"),
    ("Drugs.com New Drugs & Trials", "https://www.drugs.com/feeds/headline_news.xml"),
    ("MedPage Today", "https://www.medpagetoday.com/rss/headlines.xml"),
    ("Mayo Clinic News", "https://newsnetwork.mayoclinic.org/feed/"),
    ("News-Medical", "https://www.news-medical.net/tag/feed/Medical-Research.aspx"),
    ("EurekAlert Medicine", "https://www.eurekalert.org/rss/medicine_health.xml"),
    ("ScienceDaily Health", "https://www.sciencedaily.com/rss/health_medicine.xml"),
    ("New Scientist Health", "https://www.newscientist.com/subject/health/feed/"),
    ("Harvard Health", "https://www.health.harvard.edu/blog/feed"),
]

BANNED_KEYWORDS = [
    "suicide", "self-harm", "abortion", "rape", "sexual assault", "pedophil",
    "porn", "erectile", "genital", "gun violence", "mass shooting", "terrorist",
    "bioweapon", "biological weapon", "overdose death", "cocaine", "heroin",
    "fentanyl", "methamphetamine", "racism", "transgender", "political",
    "homicide", "murder", "autopsy", "mutilat", "execution", "euthanasia"
]

# استبعاد الأخبار الإدارية أو المملة أو التجارب على الحشرات والحيوانات غير المهمة للمشاهد
BORING_ACADEMIC_KEYWORDS = [
    "fruit flies", "drosophila", "zebrafish", "nematode", "c. elegans",
    "hospital billing", "insurance coverage", "medicare policy", "nursing curriculum",
    "medical students", "hospital staffing", "healthcare administration",
    "telehealth survey", "veterinary", "cattle", "poultry", "swine", "crop yield"
]

# الكلمات المفتاحية التي ترفع جاذبية الخبر وتجعله ترند يهم ملايين المشاهدين
VIRAL_BREAKTHROUGH_KEYWORDS = [
    "breakthrough", "clinical trial", "fda", "approved", "new drug", "pill",
    "medication", "treatment", "therapy", "reverses", "prevents", "restores",
    "early sign", "warning sign", "hidden risk", "symptom", "first-ever",
    "surprising", "unexpected", "millions", "common habit", "daily habit",
    "cure", "survival", "regenerat", "repair", "eliminat", "protects against",
    "blocks", "doubles", "cuts risk", "reduces risk", "game-changer", "vaccine"
]

MEDICAL_PRIORITY_KEYWORDS = [
    "treatment", "therapy", "clinical trial", "breakthrough", "cancer", "tumor",
    "alzheimer", "dementia", "parkinson", "brain", "heart", "cardiovascular",
    "diabetes", "insulin", "obesity", "metabolism", "longevity", "aging",
    "immune", "vaccine", "antibiotic", "virus", "infection", "stem cell",
    "gene", "dna", "rna", "crispr", "drug", "fda", "medication", "blood",
    "kidney", "liver", "lung", "sleep", "depression", "anxiety", "stroke",
    "microbiome", "gut", "inflammation", "arthritis", "vision", "hearing",
    "stomach", "pancreas", "thyroid", "bone", "muscle", "skin", "migraine",
    "cholesterol", "blood pressure", "asthma", "allergy", "vitamin"
]

# تقسيم الطب إلى 6 مجالات مستقلة لضمان تنوع كل فيديو وعدم التركيز على عضو واحد
MEDICAL_DOMAINS = {
    "pharma_drugs": [
        "drug", "pill", "medication", "fda", "approval", "approved", "pharmaceutical",
        "prescription", "antibiotic", "vaccine", "injection", "dose", "statin",
        "glp-1", "ozempic", "inhibitor", "capsule", "tablet", "clinical trial"
    ],
    "internal_organs": [
        "liver", "kidney", "renal", "hepatic", "lung", "pulmonary", "respiratory",
        "asthma", "gut", "microbiome", "stomach", "gastric", "intestin", "colon",
        "bowel", "pancreas", "gallbladder", "thyroid", "bladder", "digestive"
    ],
    "major_diseases_immunity": [
        "cancer", "tumor", "oncology", "leukemia", "melanoma", "chemotherapy",
        "diabetes", "insulin", "glucose", "blood sugar", "autoimmune", "immune system",
        "immunity", "virus", "viral", "infection", "bacteria", "sepsis", "arthritis", "lupus"
    ],
    "senses_bones_sleep_skin": [
        "eye", "vision", "blind", "retina", "glaucoma", "macular", "hearing",
        "ear", "deaf", "tinnitus", "bone", "osteoporosis", "muscle", "joint",
        "cartilage", "skin", "eczema", "psoriasis", "hair", "sleep", "insomnia",
        "apnea", "migraine", "chronic pain", "dental", "tooth", "gum"
    ],
    "metabolism_nutrition_aging": [
        "obesity", "weight loss", "fat", "metabolism", "metabolic", "cholesterol",
        "triglyceride", "diet", "nutrition", "vitamin", "supplement", "protein",
        "fasting", "exercise", "longevity", "aging", "cellular", "lifespan"
    ],
    "heart_and_brain": [
        "brain", "alzheimer", "dementia", "parkinson", "memory", "cognitive",
        "neuro", "stroke", "heart", "cardiac", "cardiovascular", "artery",
        "blood pressure", "hypertension", "vascular"
    ]
}

FALLBACK_QUERIES = [
    "medical scientist microscope laboratory",
    "doctor examining mri brain scan",
    "pharmaceutical research laboratory",
    "human dna double helix animation",
    "surgeon operating room hospital",
    "red blood cells flowing artery",
    "chemist pipette test tube lab",
    "cardiologist checking heart monitor",
    "neurology brain synapses network",
    "modern hospital corridor doctors",
    "pharmacist checking medicine pills",
    "senior patient talking to doctor",
    "biotechnology automated laboratory",
    "healthy human heart beat 3d",
    "vaccine vial syringe laboratory",
    "microbiology petri dish bacteria",
    "medical researcher looking at screen",
    "CT scan diagnostic hospital room",
    "immune system cells microscopic",
    "woman exercising healthy lifestyle",
    "healthy nutrition fresh vegetables",
    "deep sleep brain waves monitoring",
    "ophthalmologist eye examination",
    "orthopedic physical therapy clinic",
    "genetic sequencing computer screen"
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

def is_safe_and_engaging_medical(title, summary):
    combined = (title + " " + summary).lower()
    for bad in BANNED_KEYWORDS:
        if bad.lower() in combined:
            return False
    for boring in BORING_ACADEMIC_KEYWORDS:
        if boring.lower() in combined:
            return False
    score = sum(1 for kw in MEDICAL_PRIORITY_KEYWORDS if kw in combined)
    return score >= 1

def classify_medical_domain(title, summary):
    """يحدد المجال الطبي للخبر لضمان تنوع أخبار الحلقة بين الأدوية والأعضاء والأمراض."""
    combined = (title + " " + summary).lower()
    title_low = title.lower()
    best_domain = "general_medicine"
    best_hits = 0

    domain_order = [
        "pharma_drugs",
        "internal_organs",
        "major_diseases_immunity",
        "senses_bones_sleep_skin",
        "metabolism_nutrition_aging",
        "heart_and_brain"
    ]
    for dom in domain_order:
        kws = MEDICAL_DOMAINS[dom]
        hits = sum(2 if kw in title_low else (1 if kw in combined else 0) for kw in kws)
        if hits > best_hits:
            best_hits = hits
            best_domain = dom
    return best_domain

def calculate_viral_and_freshness_rank(title, summary, dt):
    """يحسب قوة الخبر وإثارته للجمهور مع مراعاة حداثته."""
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
    viral_pts = sum(3 if kw in title_low else (2 if kw in combined else 0) for kw in VIRAL_BREAKTHROUGH_KEYWORDS)

    return freshness_pts + med_pts + viral_pts

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
                if not is_safe_and_engaging_medical(title, desc):
                    continue

                dt = parse_rss_date(pub_date_raw)
                domain = classify_medical_domain(title, desc)
                total_rank = calculate_viral_and_freshness_rank(title, desc, dt)

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
            if dom == "heart_and_brain" and domain_counts.get(dom, 0) >= 1 and len(candidates) > 10:
                continue
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
# 4. توليد السيناريو الديناميكي (بين 10 و 15 دقيقة)
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

def generate_script_with_gemini(news_items):
    # اختيار طول الحلقة عشوائياً كل يوم ليتراوح الفيديو طبيعياً بين 10 و 15 دقيقة
    pacing_profiles = [
        {"target_label": "10 to 11 minutes", "words_per_act": "75 to 85 words", "min_words": 72},
        {"target_label": "11.5 to 12.5 minutes", "words_per_act": "88 to 98 words", "min_words": 84},
        {"target_label": "13 to 14 minutes", "words_per_act": "102 to 112 words", "min_words": 96},
        {"target_label": "14 to 15 minutes", "words_per_act": "115 to 126 words", "min_words": 108},
    ]
    profile = random.choice(pacing_profiles)
    print(f"Selected Episode Pacing Profile: {profile['target_label']} ({profile['words_per_act']} per act)")

    # التنويع التلقائي بين سؤال مشوق أو عبارة/كلمات خاطفة على الصورة المصغرة
    thumbnail_hook_styles = [
        'a short 2-to-4 word curiosity QUESTION ending with a question mark (e.g., "IS THIS THE CURE?", "WHY DID THIS WORK?")',
        'a bold, punchy 2-to-4 word dramatic STATEMENT or PHRASE without a question mark (e.g., "HIDDEN ORGAN TRIGGER!", "NEW PILL BREAKTHROUGH", "CELLULAR REPAIR UNLOCKED")'
    ]
    chosen_thumb_style = random.choice(thumbnail_hook_styles)

    # اختيار خبر غير متعلق بالمخ ليكون هو محور الصورة المصغرة مع تنويع الألوان السينمائية
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

    color_palettes = [
        "vibrant emerald green, gold, and deep clinical navy",
        "crimson red, warm amber gold, and dark cinematic teal",
        "glowing magenta, royal purple, and bright silver-white",
        "radiant golden-orange, electric cyan, and deep obsidian",
        "ruby red, bright turquoise, and clean laboratory white"
    ]
    chosen_palette = random.choice(color_palettes)

    news_blob = ""
    for idx, item in enumerate(news_items, 1):
        news_blob += (
            f"STORY {idx} (Category: {item.get('domain', 'medicine')}):\n"
            f"Title: {item['title']}\n"
            f"Summary: {item['summary']}\n\n"
        )

    prompt = f"""
You are the lead medical science documentary narrator for the YouTube channel "MedPulse 5".
Write a deeply engaging, authoritative, empathetic, 100% policy-safe English script covering these 5 real medical breakthroughs.
Target total video duration for today's episode: {profile['target_label']}.

INPUT STORIES:
{news_blob}

CRITICAL RULES:
1. Speak directly to the viewer ("you", "your body", "your health").
2. NEVER say website names (like MedicalXpress, ScienceDaily, EurekAlert, MedPage, SciTechDaily) or publication dates out loud in the spoken narration!
3. Instead, attribute findings naturally to "researchers", "clinical investigators", "medical scientists", or the university/hospital mentioned in the summary.
4. Keep all language 100% YouTube Advertiser-Friendly. Avoid graphic descriptions of violence or disturbing imagery.
5. Each of the 5 stories MUST be divided into exactly 4 narrative acts (Act 1: The Hidden Medical Challenge, Act 2: The Discovery & Mechanism, Act 3: Clinical Evidence & Impact, Act 4: What This Means For Your Health).
6. LENGTH REQUIREMENT: Each of the 20 acts (5 stories x 4 acts) MUST contain {profile['words_per_act']} of natural spoken narration.
7. For EVERY act, provide 3 distinct, specific, visual Pexels search queries (3 to 5 English words each, matching the exact organ, medication, disease, or laboratory process in that story) so the video never shows repetitive footage.
8. For EVERY story, provide a short, punchy `lower_third` headline (maximum 52 characters) and a `chapter_title` (maximum 42 characters).
9. In `outro_narration`, thank the viewer for watching and invite them to subscribe to "MedPulse 5" for daily medical breakthroughs.
10. Provide 3 distinct, high-CTR `youtube_titles` (under 90 chars each). Title #1 MUST be the strongest, most clickable recommended title.
11. For `thumbnail_prompt`: Base the visual strictly on STORY #{thumb_story_idx} ("{thumb_story_item['title']}").
    - STRICTLY FORBIDDEN: Do NOT draw a human brain, head silhouette, or neural synapses!
    - Instead, depict the specific subject of Story #{thumb_story_idx} (such as a glowing translucent medical capsule/pill, heart & arteries, liver/kidney/lungs/gut, microscopic immune cells fighting disease, vaccine vial, or a doctor examining a futuristic diagnostic display).
    - Use a rich, eye-catching color palette featuring {chosen_palette}.
    - MUST include instructions to render {chosen_thumb_style} in LARGE BOLD GLOWING YELLOW AND WHITE CINEMATIC TEXT on the left side of the image (in ALL CAPS).

Return ONLY valid JSON matching this exact structure (no markdown fences, no extra commentary):
{{
  "youtube_titles": [
    "Title Option 1 (The #1 Best High-CTR Recommended Title)",
    "Title Option 2 (Curiosity & Health Impact Angle)",
    "Title Option 3 (Direct Clinical Breakthrough Angle)"
  ],
  "youtube_description": "3-paragraph SEO description summarizing the 5 breakthroughs",
  "youtube_tags": "tag1, tag2, tag3, ... (15 tags)",
  "thumbnail_prompt": "Ultra-realistic 16:9 cinematic medical illustration of [specific non-brain visual from Story #{thumb_story_idx}], rich color palette of {chosen_palette}, dramatic lighting, 8k resolution, with large bold glowing yellow and white cinematic text on the left side that says \\"YOUR 2-4 WORD HOOK HERE\\"",
  "hook_narration": "55 to 70 words captivating opening hook introducing today's 5 breakthroughs on MedPulse 5",
  "hook_queries": ["medical laboratory scientist", "pharmacist medicine pills", "red blood cells artery"],
  "stories": [
    {{
      "story_number": 1,
      "chapter_title": "Short Chapter Title (max 42 chars)",
      "lower_third": "Short Banner Headline (max 52 chars)",
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
  "outro_narration": "55 to 70 words warm conclusion inviting viewers to subscribe to MedPulse 5 and share their thoughts",
  "outro_queries": ["doctor smiling hospital", "healthy senior couple walking", "modern medical center"]
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
                    generation_config={"temperature": 0.7},
                    request_options={"timeout": 90}
                )
                raw_text = response.text
                cleaned = clean_json_text(raw_text)
                data = json.loads(cleaned)
                if "stories" in data and len(data["stories"]) == 5:
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
# 6. تحميل وتطبيع مقاطع الفيديو عالية الدقة (منع التجميد والغبش)
# ==========================================
def normalize_clip_hd(raw_path, norm_path):
    """
    يحول أي فيديو تم تحميله إلى صيغة قياسية ثابتة الإطارات (24 إطار/ثانية)
    وبدقة 1280x720 وجودة عالية جداً لمنع أي تجميد أو غبش أثناء المونتاج.
    """
    cmd = [
        "ffmpeg", "-y",
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

    # الشعار الدائري في الزاوية العلوية اليمنى
    logo_img = load_circular_logo(68)
    if logo_img:
        img.paste(logo_img, (VIDEO_W - 68 - 24, 22), logo_img)

    # شريط الأخبار السفلي الأنيق والنحيف
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
    print("1. Fetching top 5 fresh, diverse, high-impact medical news stories...")
    news_items = fetch_top_5_medical_news()
    for i, it in enumerate(news_items, 1):
        print(f"  Story {i} [{it.get('domain')}]: {it['title']} ({it['source']} - Score: {it.get('score')})")

    print("2. Generating dynamic documentary script via Gemini...")
    script_data = generate_script_with_gemini(news_items)

    used_video_ids = load_set_file(USED_VIDEOS_FILE)
    initial_known_videos = set(used_video_ids)

    timeline_clips = []
    current_time = 0.0
    timestamps = [("00:00", "Introduction: Today's Top 5 Medical Breakthroughs")]

    print("3. Building Intro Hook...")
    hook_clip, hook_dur = build_spoken_scene(
        script_data["hook_narration"],
        script_data.get("hook_queries", ["medical research laboratory", "doctor hospital"]),
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
        threads=2,
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

    # تجهيز خيارات العناوين الثلاثة مع علامة (موصى به)
    titles_list = script_data.get("youtube_titles", [])
    if not isinstance(titles_list, list) or len(titles_list) == 0:
        single_t = script_data.get("youtube_title", "Top 5 Medical Breakthroughs Changing Healthcare Today")
        titles_list = [
            single_t,
            "5 Surprising Medical Discoveries & Treatments You Need to Know",
            "New Clinical Breakthroughs: Medications, Organs & Disease Prevention"
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
1. YOUTUBE TITLES (اختر عنواناً واحداً فقط من العناوين الثلاثة التالية وضعه في خانة العنوان):
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

#MedPulse5 #MedicalBreakthroughs #HealthNews #Medicine #Longevity #ClinicalResearch

==================================================
3. YOUTUBE TAGS (انسخ هذه الكلمات المفتاحية وضعها في خانة العلامات Tags):
==================================================
{script_data.get('youtube_tags', 'medical breakthroughs, health news, medicine, longevity, clinical trials, MedPulse 5')}

==================================================
4. AI THUMBNAIL PROMPT (انسخ هذا الوصف وضعه في موقع الصور لتوليد صورة مصغرة متنوعة للفيديو):
==================================================
{script_data.get('thumbnail_prompt', 'Dramatic ultra-realistic 16:9 medical illustration showing a glowing translucent pharmaceutical capsule releasing golden healing particles inside the bloodstream, emerald and crimson cinematic lighting, 8k, with large bold glowing yellow text on the left side that says "NEW PILL BREAKTHROUGH!"')}
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
