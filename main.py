import os
import re
import json
import math
import time
import glob
import random
import asyncio
import requests
import subprocess
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps
import edge_tts
from moviepy.editor import (
    VideoFileClip, ImageClip, AudioFileClip, CompositeVideoClip,
    concatenate_videoclips, concatenate_audioclips
)
import moviepy.audio.fx.all as afx
from google import genai

if not hasattr(Image, 'ANTIALIAS'):
    Image.ANTIALIAS = Image.Resampling.LANCZOS

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "").strip()

if not GEMINI_API_KEY:
    raise ValueError("Missing GEMINI_API_KEY environment variable!")
if not PEXELS_API_KEY:
    raise ValueError("Missing PEXELS_API_KEY environment variable!")

client = genai.Client(api_key=GEMINI_API_KEY)

USED_NEWS_FILE = "used_news.txt"
USED_VIDEOS_FILE = "used_videos.txt"
LOGO_PATH = "تنزيل.jpeg"

os.makedirs("temp_Media", exist_ok=True)
os.makedirs("output", exist_ok=True)

def load_set(filepath):
    if not os.path.exists(filepath):
        return set()
    with open(filepath, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def save_to_set(filepath, items):
    existing = load_set(filepath)
    with open(filepath, "a", encoding="utf-8") as f:
        for item in items:
            item_str = str(item).strip()
            if item_str and item_str not in existing:
                f.write(item_str + "\n")
                existing.add(item_str)

used_news = load_set(USED_NEWS_FILE)
used_videos = load_set(USED_VIDEOS_FILE)

RSS_FEEDS = [
    ("Drugs.com New Medications", "https://www.drugs.com/feeds/new_drugs.xml"),
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
    ("EurekAlert Medicine", "https://www.eurekalert.org/rss/medicine_health.xml")
]

BANNED_KEYWORDS = [
    "gaza", "israel", "ukraine", "russia", "war", "military", "missile", "soldier",
    "trump", "biden", "election", "parliament", "senate", "congress", "democrat",
    "republican", "abortion", "transgender", "lgbt", "suicide", "homicide", "murder",
    "shooting", "gun", "terror", "assault", "rape", "racism", "police", "prison",
    "lawsuit", "court", "tax", "budget", "strike", "union", "protest", "climate policy"
]

BORING_LECTURE_KEYWORDS = [
    "drosophila", "fruit fly", "fruit flies", "zebrafish", "nematode", "c. elegans",
    "petri dish", "in silico", "phylogenetic", "taxonomic", "curriculum", "medical school",
    "medicaid", "medicare", "insurance billing", "hospital staffing", "nursing shortage",
    "administrative", "telehealth policy", "wait times", "survey of doctors", "medical students",
    "paleolithic", "neanderthal", "fossil", "archaeological", "veterinary", "canine", "bovine",
    "plant biology", "crop yield", "photosynthesis", "ribosomal", "transcriptomic atlas",
    "chromatin remodeling", "protein folding simulation", "single-cell rna-seq"
]

EXCITING_PATIENT_KEYWORDS = [
    "pill", "drug", "medication", "vitamin", "supplement", "cure", "treatment", "therapy",
    "reverse", "restore", "repair", "organ", "heart", "liver", "kidney", "lung", "eye",
    "vision", "hearing", "diabetes", "insulin", "blood pressure", "cholesterol", "artery",
    "cancer", "tumor", "arthritis", "pain", "alzheimer", "dementia", "sleep", "gut",
    "stomach", "digestion", "immune", "vaccine", "infection", "antibiotic", "longevity",
    "aging", "fasting", "diet", "nutrient", "clinical trial", "fda", "patients", "chronic"
]

DOMAIN_BUCKETS = {
    "new_drugs_and_pills": ["pill", "drug", "medication", "fda", "capsule", "tablet", "dose", "injection", "antibiotic", "antiviral", "clinical trial"],
    "vitamins_nutrition_and_body": ["vitamin", "supplement", "nutrient", "diet", "fasting", "food", "mineral", "omega", "protein", "gut", "microbiome", "metabolism", "sugar", "cholesterol"],
    "stubborn_chronic_diseases": ["cancer", "tumor", "diabetes", "autoimmune", "arthritis", "fibromyalgia", "chronic pain", "lupus", "multiple sclerosis", "asthma", "allergy", "obesity"],
    "vital_internal_organs": ["liver", "kidney", "lung", "pancreas", "stomach", "colon", "eye", "retina", "vision", "ear", "hearing", "skin", "bone", "muscle", "cartilage"],
    "heart_blood_and_nerves": ["heart", "cardiac", "artery", "blood pressure", "stroke", "vascular", "vein", "alzheimer", "parkinson", "memory", "nerve", "sleep", "migraine"]
}

def normalize_title(title):
    return re.sub(r'[^a-z0-9]', '', title.lower())[:65]

def is_safe_and_exciting_medical_news(title, summary):
    text = (title + " " + summary).lower()
    for word in BANNED_KEYWORDS:
        if re.search(r'\b' + re.escape(word) + r'\b', text):
            return False
    for word in BORING_LECTURE_KEYWORDS:
        if word in text:
            return False
    if ("mice" in text or "mouse" in text or "rodent" in text) and not any(
        w in text for w in ["pill", "drug", "cure", "reverse", "restore", "treatment", "tumor", "organ", "vitamin"]
    ):
        return False
    return True

def score_patient_excitement(title, summary):
    text = (title + " " + summary).lower()
    score = 0
    for kw in EXCITING_PATIENT_KEYWORDS:
        if kw in text:
            score += 2
    if any(w in text for w in ["pill", "drug", "vitamin", "cure", "reverse", "restore", "organ", "fda", "clinical trial"]):
        score += 5
    return score

def classify_story_domain(title, summary):
    text = (title + " " + summary).lower()
    best_domain = "general_breakthrough"
    best_hits = 0
    for domain, keywords in DOMAIN_BUCKETS.items():
        hits = sum(1 for kw in keywords if kw in text)
        if hits > best_hits:
            best_hits = hits
            best_domain = domain
    return best_domain

def is_brain_story(story):
    text = (story["title"] + " " + story["summary"]).lower()
    return any(w in text for w in ["brain", "alzheimer", "dementia", "neural", "neuron", "cognitive", "neurology", "parkinson", "memory", "migraine"])

def get_matched_thumbnail_hook(story_text):
    text = story_text.lower()
    if any(w in text for w in ["pill", "drug", "medication", "capsule", "tablet", "fda", "dose"]):
        hooks = [
            {"text": "ONE DAILY PILL?", "type": "question"},
            {"text": "NEW PILL CURE!", "type": "statement"},
            {"text": "THE CURE PILL?", "type": "question"},
            {"text": "ONE DOSE ONLY!", "type": "statement"},
            {"text": "END OF SURGERY?", "type": "question"},
            {"text": "FINALLY A CURE!", "type": "statement"}
        ]
    elif any(w in text for w in ["vitamin", "supplement", "nutrient", "diet", "food", "fasting", "sugar", "mineral"]):
        hooks = [
            {"text": "MISSING VITAMIN?", "type": "question"},
            {"text": "1 VITAMIN FIX!", "type": "statement"},
            {"text": "HEAL BY DIET?", "type": "question"},
            {"text": "HIDDEN BODY FUEL!", "type": "statement"},
            {"text": "TOXIC DAILY FOOD?", "type": "question"},
            {"text": "NATURE'S CURE!", "type": "statement"}
        ]
    elif any(w in text for w in ["heart", "cardiac", "artery", "arteries", "blood pressure", "cholesterol", "stroke", "vascular"]):
        hooks = [
            {"text": "CLEAN ARTERIES?", "type": "question"},
            {"text": "HEART REBORN!", "type": "statement"},
            {"text": "HEART REPAIRED?", "type": "question"},
            {"text": "ARTERIES CLEARED!", "type": "statement"},
            {"text": "NO MORE STATINS?", "type": "question"},
            {"text": "BLOOD FLOW FIXED!", "type": "statement"}
        ]
    elif any(w in text for w in ["cancer", "tumor", "oncology", "leukemia", "malignant", "carcinoma"]):
        hooks = [
            {"text": "CANCER STOPPED?", "type": "question"},
            {"text": "TUMORS VANISH!", "type": "statement"},
            {"text": "TUMOR DESTROYED?", "type": "question"},
            {"text": "CANCER DEFEATED!", "type": "statement"},
            {"text": "THE FINAL CURE?", "type": "question"},
            {"text": "CELLS FIGHT BACK!", "type": "statement"}
        ]
    elif any(w in text for w in ["kidney", "liver", "lung", "gut", "stomach", "eye", "vision", "blind", "organ", "pancreas", "hearing"]):
        hooks = [
            {"text": "ORGAN REPAIRED?", "type": "question"},
            {"text": "ORGANS HEALED!", "type": "statement"},
            {"text": "DAMAGE REVERSED?", "type": "question"},
            {"text": "BODY REBUILT!", "type": "statement"},
            {"text": "SELF HEALING?", "type": "question"},
            {"text": "FULL RECOVERY!", "type": "statement"}
        ]
    elif any(w in text for w in ["diabetes", "insulin", "glucose", "arthritis", "pain", "joint", "inflammation", "autoimmune", "chronic"]):
        hooks = [
            {"text": "NO MORE INSULIN?", "type": "question"},
            {"text": "PAIN SWITCHED OFF!", "type": "statement"},
            {"text": "PAIN GONE FOREVER?", "type": "question"},
            {"text": "DISEASE REVERSED!", "type": "statement"},
            {"text": "INFLAMMATION OFF?", "type": "question"},
            {"text": "JOINTS REPAIRED!", "type": "statement"}
        ]
    else:
        hooks = [
            {"text": "THE FINAL CURE?", "type": "question"},
            {"text": "DOCTORS STUNNED!", "type": "statement"},
            {"text": "DISEASE REVERSED?", "type": "question"},
            {"text": "MEDICAL MIRACLE!", "type": "statement"},
            {"text": "BODY REBUILT!", "type": "statement"},
            {"text": "FINALLY CURED!", "type": "statement"}
        ]
    return random.choice(hooks)

def fetch_fresh_medical_news(target_count=5):
    print("Fetching patient-focused medical breakthroughs, new drugs, vitamins, and organ cures...")
    candidates = []
    seen_norms = set()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    for source_name, url in RSS_FEEDS:
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                continue
            root = ET.fromstring(resp.content)
            for item in root.findall(".//item"):
                title_el = item.find("title")
                link_el = item.find("link")
                desc_el = item.find("description")

                title = title_el.text.strip() if (title_el is not None and title_el.text) else ""
                link = link_el.text.strip() if (link_el is not None and link_el.text) else ""
                desc = desc_el.text.strip() if (desc_el is not None and desc_el.text) else ""
                desc = re.sub(r'<[^>]+>', ' ', desc)
                desc = re.sub(r'\s+', ' ', desc).strip()

                if not title or not link:
                    continue

                norm_t = normalize_title(title)
                if link in used_news or norm_t in used_news or norm_t in seen_norms:
                    continue

                if not is_safe_and_exciting_medical_news(title, desc):
                    continue

                excitement = score_patient_excitement(title, desc)
                domain = classify_story_domain(title, desc)

                seen_norms.add(norm_t)
                candidates.append({
                    "source": source_name,
                    "title": title,
                    "link": link,
                    "summary": desc[:900],
                    "norm_title": norm_t,
                    "excitement": excitement,
                    "domain": domain
                })
        except Exception as e:
            print(f"Warning fetching {source_name}: {e}")

    candidates.sort(key=lambda x: x["excitement"], reverse=True)

    selected = []
    used_domains = set()

    for c in candidates:
        if len(selected) >= target_count:
            break
        if c["domain"] not in used_domains:
            selected.append(c)
            used_domains.add(c["domain"])

    for c in candidates:
        if len(selected) >= target_count:
            break
        if c not in selected:
            selected.append(c)

    if len(selected) < target_count:
        raise RuntimeError(f"Only found {len(selected)} fresh exciting stories. Need at least {target_count}.")

    print(f"Selected {len(selected)} diverse, high-excitement medical stories:")
    for idx, s in enumerate(selected, 1):
        print(f"  {idx}. [{s['domain']}] {s['title']} (Score: {s['excitement']})")
    return selected

def clean_json_text(text):
    text = text.strip()
    text = re.sub(r'^\x60{3}(?:json)?\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*\x60{3}$', '', text)
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        return text[start:end+1]
    return text

THUMBNAIL_COLOR_PALETTES = [
    "Vibrant Ruby Red, Warm Amber Gold, and Crisp Clinical White lighting with deep contrast",
    "Emerald Healing Green, Radiant Golden Sunlight, and Clean Silver highlights",
    "Royal Violet, Warm Magenta Glow, and Bright Pearl White medical studio lighting",
    "Fiery Sunset Orange, Warm Copper Gold, and Deep Charcoal cinematic shadows",
    "Warm Golden Honey, Turquoise Teal accents, and Ultra-Clean Ivory studio lighting"
]

def generate_script_with_gemini(stories):
    print("Selecting Hero Story to synchronize Recommended Title #1 and Thumbnail Prompt...")
    non_brain_indices = [i for i, s in enumerate(stories) if not is_brain_story(s)]
    hero_index = non_brain_indices[0] if non_brain_indices else 0
    hero_story = stories[hero_index]
    hero_story_num = hero_index + 1

    stories_text = ""
    for i, s in enumerate(stories, 1):
        hero_tag = " [HERO STORY FOR RECOMMENDED TITLE #1 AND THUMBNAIL]" if i == hero_story_num else ""
        stories_text += (
            f"STORY {i}{hero_tag} (Domain: {s['domain']}):\n"
            f"Headline: {s['title']}\n"
            f"Summary: {s['summary']}\n"
            f"Link: {s['link']}\n\n"
        )

    duration_profiles = [
        {"label": "10 to 11 minutes", "words_per_act": "75 to 85 words", "min_words": 72},
        {"label": "11.5 to 12.5 minutes", "words_per_act": "88 to 98 words", "min_words": 84},
        {"label": "13 to 14 minutes", "words_per_act": "102 to 112 words", "min_words": 96},
        {"label": "14 to 15 minutes", "words_per_act": "115 to 126 words", "min_words": 108}
    ]
    chosen_profile = random.choice(duration_profiles)
    print(f"Target Episode Pacing Profile: {chosen_profile['label']} ({chosen_profile['words_per_act']} per scene)")

    chosen_palette = random.choice(THUMBNAIL_COLOR_PALETTES)
    chosen_thumb_hook = get_matched_thumbnail_hook(hero_story["title"] + " " + hero_story["summary"])

    print(f"Synchronized Hero Story #{hero_story_num}: {hero_story['title']}")
    print(f"Matched Verified Thumbnail Hook: '{chosen_thumb_hook['text']}' ({chosen_thumb_hook['type']})")

    prompt = (
        f"You are the charismatic lead host of 'MedPulse 5', a hugely popular medical television show for everyday people.\n"
        f"Your viewers are NOT biology students looking for a dry textbook lecture! They are everyday people who care deeply about their bodies, their organs, new pills and medications, curing stubborn diseases, vitamins, longevity, and protecting the people they love.\n\n"
        f"Today's target episode length is {chosen_profile['label']}.\n\n"
        f"Here are the 5 real medical breakthroughs for today's episode:\n"
        f"{stories_text}\n"
        f"CRITICAL ANTI-LECTURE & EXCITEMENT RULES (MUST FOLLOW STRICTLY):\n"
        f"1. NO BIOLOGY LECTURES: Never sound like a dry university professor or academic report. Translate every complex term immediately into vivid human reality.\n"
        f"2. FOCUS ON PILLS, VITAMINS, ORGANS & STUBBORN DISEASES: Speak directly to the viewer ('you', 'your heart', 'your kidneys', 'your joints', 'your daily supplements'). Highlight what this means for stubborn illnesses, new medications, vitamins, and organ repair.\n"
        f"3. NEVER mention website names (like MedicalXpress, ScienceDaily, Drugs.com) or publication dates out loud. Only credit universities, hospitals, or clinical teams naturally.\n"
        f"4. Keep the intro fast, warm, and irresistible (2 sentences max) before teasing what is coming up and jumping into Story #1.\n\n"
        f"DOCUMENTARY STRUCTURE (22 NARRATION SEGMENTS TOTAL):\n"
        f"- 'intro': 1 segment (50 to 65 words). Hook the viewer immediately with the most exciting cure/pill/vitamin discovery of the day, welcome them to MedPulse 5, and promise 5 breakthroughs that could change how they care for their body.\n"
        f"- 'stories': Exactly 5 stories. Each story MUST have:\n"
        f"  - 'story_number': 1 to 5\n"
        f"  - 'chapter_title': Compelling, everyday human-interest chapter title (4 to 7 words)\n"
        f"  - 'source_url': Exact link provided\n"
        f"  - 'acts': Exactly 4 acts per story (20 story acts total across the 5 stories).\n"
        f"    Each act MUST contain:\n"
        f"    - 'act_type':\n"
        f"       * Act 1: 'What This Means For Your Body'\n"
        f"       * Act 2: 'How The Treatment Or Vitamin Works'\n"
        f"       * Act 3: 'Inside The Clinical Proof'\n"
        f"       * Act 4: 'Your Practical Health Takeaway'\n"
        f"    - 'narration': Rich, warm, energetic spoken narration of {chosen_profile['words_per_act']} (minimum {chosen_profile['min_words']} words per act).\n"
        f"    - 'lower_third': Crisp TV banner headline (maximum 55 characters).\n"
        f"    - 'search_queries': A list of 3 DIFFERENT, VIVID, CONCRETE visual search queries for Pexels HD stock video (2 to 4 words each).\n"
        f"- 'outro': 1 segment (55 to 70 words). Warmly wrap up today's 5 breakthroughs, ask viewers to share in the comments which discovery gave them the most hope (#1 through #5), invite them to subscribe to MedPulse 5, and end with an uplifting sign-off.\n\n"
        f"YOUTUBE SEARCH SEO TITLES & 100% SYNCHRONIZED THUMBNAIL PROMPT:\n"
        f"1. 'youtube_titles': Provide a list of 3 HIGH-CTR, SEARCH-OPTIMIZED English YouTube titles:\n"
        f"   - CRITICAL SYNCHRONIZATION RULE FOR TITLE #1 (First item in the list, which is the Recommended Title):\n"
        f"     * Title #1 MUST be 100% about HERO STORY #{hero_story_num} ('{hero_story['title']}')!\n"
        f"     * Why? Because the video's Thumbnail Prompt is locked to HERO STORY #{hero_story_num}, so Title #1 and the Thumbnail MUST match 100%!\n"
        f"   - Title #2: Combine HERO STORY #{hero_story_num} with one other major breakthrough from today's episode.\n"
        f"   - Title #3: A high-curiosity multi-story title combining 3 of today's most searched health topics.\n"
        f"   - ALL 3 titles MUST start their FIRST 4 WORDS with high-volume everyday health search keywords that millions of regular people type into YouTube Search (such as 'New Pill Stops...', '1 Daily Vitamin...', 'Reversing Kidney Damage...', 'Curing Chronic Pain...', 'Restoring Lost Vision...', 'Cleaning Clogged Arteries...', 'New Diabetes Treatment...').\n"
        f"   - NEVER start a title with obscure technical jargon or weak textbook phrasing.\n"
        f"   - End each title with a strong parenthetical or colon search booster.\n\n"
        f"2. 'thumbnail_prompt': Write a detailed English image-generation prompt (85 to 120 words) that is 100% SYNCHRONIZED with Title #1 and HERO STORY #{hero_story_num} ('{hero_story['title']}'):\n"
        f"   - VISUAL ALIGNMENT WITH TITLE #1: Depict the exact medical miracle, organ, pill, vitamin, or cure featured in Title #1 (HERO STORY #{hero_story_num}).\n"
        f"   - STRICT NO-BRAIN RULE: Do NOT draw a human brain or glowing head silhouette! Focus on the specific organ, glowing pill/capsule, vitamin, heart, lungs, kidneys, eyes, arteries, joints, or cellular shield of HERO STORY #{hero_story_num}.\n"
        f"   - COLOR PALETTE: Explicitly require this exact color scheme: '{chosen_palette}'.\n"
        f"   - VERIFIED TEXT OVERLAY: Require massive, ultra-clean 3D cinematic typography on the left side in bold yellow and white font reading the exact verified English hook: '{chosen_thumb_hook['text']}' (spell every letter identically, maximum 3 words, no extra words on the image).\n"
        f"   - Explicitly specify: 'Photorealistic 8k medical documentary thumbnail, 16:9 widescreen aspect ratio, dramatic rim lighting, razor-sharp focus, ultra-high CTR composition.'\n\n"
        f"3. 'description_intro': A compelling 3-sentence SEO paragraph summarizing today's 5 medical breakthroughs.\n"
        f"4. 'tags': A comma-separated string of 18 high-traffic English YouTube SEO tags.\n\n"
        f"Return ONLY valid JSON matching the exact keys: youtube_titles, thumbnail_prompt, description_intro, tags, intro, stories, outro."
    )

    models_to_try = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    for model_name in models_to_try:
        for attempt in range(3):
            try:
                print(f"Requesting script from {model_name} (Attempt {attempt+1})...")
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                raw_text = clean_json_text(response.text)
                data = json.loads(raw_text)
                if "stories" in data and len(data["stories"]) == 5:
                    thumb_p = data.get("thumbnail_prompt", "").strip()
                    if chosen_thumb_hook["text"] not in thumb_p:
                        thumb_p += f' Massive bold 3D yellow and white text on the left side reading "{chosen_thumb_hook["text"]}".'
                    if "16:9" not in thumb_p:
                        thumb_p += " Photorealistic 8k 16:9 widescreen medical thumbnail."
                    data["thumbnail_prompt"] = thumb_p
                    data["synchronized_hero_story_number"] = hero_story_num
                    data["synchronized_thumb_hook"] = chosen_thumb_hook["text"]
                    print("Successfully generated and validated synchronized TV-host script JSON!")
                    return data
            except Exception as e:
                print(f"Error with {model_name} (attempt {attempt+1}): {e}")
                time.sleep(4)

    raise RuntimeError("Failed to generate valid script JSON from Gemini after all retries.")

VOICE_NAME = "en-US-ChristopherNeural"

async def _synthesize_async(text, out_path):
    communicate = edge_tts.Communicate(text, VOICE_NAME, rate="+4%", pitch="-1Hz")
    await asyncio.wait_for(communicate.save(out_path), timeout=40.0)

def generate_voiceover(text, out_path):
    clean_text = re.sub(r'\s+', ' ', text).strip()
    for attempt in range(5):
        try:
            asyncio.run(_synthesize_async(clean_text, out_path))
            if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
                return out_path
        except Exception as e:
            print(f"TTS attempt {attempt+1} failed: {e}")
            time.sleep(2)
    raise RuntimeError(f"Failed to synthesize voiceover for: {out_path}")

def normalize_clip_hd(input_path, output_path):
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", input_path,
        "-t", "14",
        "-vf", "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,fps=24,format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
        "-an", output_path
    ]
    subprocess.run(cmd, check=True)
    return output_path

def search_and_download_pexels_clips(queries, needed_count, scene_prefix):
    headers = {"Authorization": PEXELS_API_KEY}
    downloaded_norm_paths = []
    fallback_queries = [
        "doctor talking patient clinic",
        "pharmacist medicine pills",
        "medical researcher microscope lab",
        "surgeon hospital operating room",
        "healthy heart rate monitor",
        "vitamin capsules close up",
        "senior couple walking park"
    ]
    all_queries = list(queries) + [q for q in fallback_queries if q not in queries]

    clip_idx = 0
    for q in all_queries:
        if len(downloaded_norm_paths) >= needed_count:
            break
        try:
            params = {
                "query": q,
                "orientation": "landscape",
                "size": "medium",
                "per_page": 40
            }
            resp = requests.get("https://api.pexels.com/videos/search", headers=headers, params=params, timeout=15)
            if resp.status_code != 200:
                continue
            videos = resp.json().get("videos", [])
            random.shuffle(videos)

            for v in videos:
                if len(downloaded_norm_paths) >= needed_count:
                    break
                vid_id = str(v.get("id"))
                duration = v.get("duration", 0)
                if vid_id in used_videos or duration < 6:
                    continue

                video_files = v.get("video_files", [])
                best_file = None
                for vf in sorted(video_files, key=lambda x: x.get("width", 0)):
                    w = vf.get("width", 0)
                    h = vf.get("height", 0)
                    link = vf.get("link", "")
                    if 1280 <= w <= 2560 and h >= 720 and link:
                        best_file = vf
                        break

                if not best_file:
                    continue

                raw_path = f"temp_Media/{scene_prefix}_raw_{clip_idx}.mp4"
                norm_path = f"temp_Media/{scene_prefix}_norm_{clip_idx}.mp4"

                r = requests.get(best_file["link"], stream=True, timeout=25)
                if r.status_code == 200:
                    with open(raw_path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=1024 * 256):
                            if chunk:
                                f.write(chunk)
                    try:
                        normalize_clip_hd(raw_path, norm_path)
                        if os.path.exists(norm_path) and os.path.getsize(norm_path) > 50000:
                            downloaded_norm_paths.append(norm_path)
                            used_videos.add(vid_id)
                            save_to_set(USED_VIDEOS_FILE, [vid_id])
                            clip_idx += 1
                    except Exception as ne:
                        print(f"Normalization error on {raw_path}: {ne}")
                    finally:
                        if os.path.exists(raw_path):
                            os.remove(raw_path)

                if len(downloaded_norm_paths) >= 1 and q in queries:
                    break
        except Exception as e:
            print(f"Pexels search warning for '{q}': {e}")

    return downloaded_norm_paths

def get_font(size, bold=True):
    font_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"
    ]
    for fp in font_candidates:
        if os.path.exists(fp):
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()

def create_circular_logo_overlay(logo_path):
    canvas = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
    if not os.path.exists(logo_path):
        return np.array(canvas)
    try:
        logo_size = 68
        img = Image.open(logo_path).convert("RGBA")
        img = ImageOps.fit(img, (logo_size, logo_size), Image.Resampling.LANCZOS)

        mask = Image.new("L", (logo_size, logo_size), 0)
        draw_mask = ImageDraw.Draw(mask)
        draw_mask.ellipse((0, 0, logo_size, logo_size), fill=255)

        circ_logo = Image.new("RGBA", (logo_size, logo_size), (0, 0, 0, 0))
        circ_logo.paste(img, (0, 0), mask=mask)

        border_draw = ImageDraw.Draw(circ_logo)
        border_draw.ellipse((1, 1, logo_size - 2, logo_size - 2), outline=(0, 210, 255, 220), width=2)

        canvas.paste(circ_logo, (1280 - logo_size - 24, 22), circ_logo)
    except Exception as e:
        print(f"Logo overlay warning: {e}")
    return np.array(canvas)

def create_lower_third_overlay(headline_text, sub_label="MEDPULSE 5  |  CLINICAL HEALTH BRIEFING"):
    canvas = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    bar_x, bar_y = 48, 644
    bar_w, bar_h = 860, 76

    draw.rounded_rectangle(
        [bar_x, bar_y, bar_x + bar_w, bar_y + bar_h],
        radius=8,
        fill=(10, 22, 38, 215)
    )
    draw.rounded_rectangle(
        [bar_x, bar_y, bar_x + 8, bar_y + bar_h],
        radius=4,
        fill=(0, 210, 255, 255)
    )

    font_sub = get_font(15, bold=True)
    font_main = get_font(22, bold=True)

    draw.text((bar_x + 24, bar_y + 11), sub_label.upper(), font=font_sub, fill=(0, 215, 255, 255))
    clean_headline = headline_text.strip()[:56]
    draw.text((bar_x + 24, bar_y + 36), clean_headline, font=font_main, fill=(255, 255, 255, 255))

    return np.array(canvas)

def create_chapter_bumper_frame(story_num, chapter_title):
    canvas = Image.new("RGB", (1280, 720), (8, 18, 34))
    draw = ImageDraw.Draw(canvas)

    for r in range(380, 20, -20):
        c_val = int(18 + (380 - r) * 0.08)
        draw.ellipse([640 - r * 1.4, 360 - r, 640 + r * 1.4, 360 + r], fill=(8, c_val, int(c_val * 1.6)))

    draw.rectangle([140, 210, 1140, 214], fill=(0, 210, 255))
    draw.rectangle([140, 506, 1140, 510], fill=(0, 210, 255))

    font_tag = get_font(26, bold=True)
    font_title = get_font(42, bold=True)
    font_brand = get_font(20, bold=False)

    tag_text = f"MEDICAL BREAKTHROUGH  #{story_num}"
    draw.text((140, 245), tag_text, font=font_tag, fill=(0, 220, 255))

    words = chapter_title.split()
    lines = []
    curr = ""
    for w in words:
        if len(curr + " " + w) <= 36:
            curr = (curr + " " + w).strip()
        else:
            lines.append(curr)
            curr = w
    if curr:
        lines.append(curr)

    y_text = 310
    for line in lines[:2]:
        draw.text((140, y_text), line, font=font_title, fill=(255, 255, 255))
        y_text += 56

    draw.text((140, 455), "MEDPULSE 5  •  EVIDENCE-BASED HEALTH & LONGEVITY", font=font_brand, fill=(180, 205, 230))
    return np.array(canvas)

def generate_ambient_background_music(output_wav_path, duration_sec=60):
    sr = 44100
    t = np.linspace(0, duration_sec, int(sr * duration_sec), endpoint=False)
    freqs = [110.0, 164.81, 220.0, 277.18]
    signal = np.zeros_like(t)
    for f in freqs:
        signal += 0.15 * np.sin(2 * np.pi * f * t)
    lfo = 0.65 + 0.35 * np.sin(2 * np.pi * 0.12 * t)
    signal = signal * lfo
    signal = np.clip(signal * 0.25, -0.9, 0.9)
    pcm = (signal * 32767).astype(np.int16)

    import wave
    with wave.open(output_wav_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
    return output_wav_path

def generate_bumper_chime(output_wav_path, duration_sec=2.4):
    sr = 44100
    t = np.linspace(0, duration_sec, int(sr * duration_sec), endpoint=False)
    env = np.exp(-1.8 * t) * np.sin(np.pi * np.minimum(t / 0.08, 1.0))
    tone = (0.4 * np.sin(2 * np.pi * 523.25 * t) +
            0.3 * np.sin(2 * np.pi * 659.25 * t) +
            0.25 * np.sin(2 * np.pi * 783.99 * t)) * env
    pcm = (np.clip(tone * 0.35, -0.9, 0.9) * 32767).astype(np.int16)

    import wave
    with wave.open(output_wav_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
    return output_wav_path

LOGO_ARRAY = create_circular_logo_overlay(LOGO_PATH)

def build_spoken_scene(narration_text, lower_third_text, sub_label, search_queries, scene_prefix):
    audio_path = f"temp_Media/{scene_prefix}_vo.mp3"
    generate_voiceover(narration_text, audio_path)
    raw_audio = AudioFileClip(audio_path)

    safe_aud_dur = max(0.2, raw_audio.duration - 0.08)
    audio_clip = raw_audio.subclip(0, safe_aud_dur)
    dur = audio_clip.duration

    needed_clips = max(3, min(4, int(math.ceil(dur / 8.5))))
    norm_paths = search_and_download_pexels_clips(search_queries, needed_clips, scene_prefix)

    sub_vids = []
    if not norm_paths:
        fallback_frame = create_chapter_bumper_frame(1, lower_third_text)
        base_video = ImageClip(fallback_frame).set_duration(dur)
    else:
        seg_dur = dur / len(norm_paths)
        for idx, np_path in enumerate(norm_paths):
            vc = VideoFileClip(np_path, audio=False)
            if vc.duration > seg_dur + 0.2:
                max_start = max(0, vc.duration - seg_dur - 0.15)
                start_t = random.uniform(0, min(1.5, max_start))
                part = vc.subclip(start_t, start_t + seg_dur)
            else:
                loops = int(math.ceil((seg_dur + 0.5) / max(0.5, vc.duration)))
                looped_list = [VideoFileClip(np_path, audio=False) for _ in range(loops)]
                conc = concatenate_videoclips(looped_list, method="compose")
                part = conc.subclip(0, seg_dur)
            sub_vids.append(part)
        base_video = concatenate_videoclips(sub_vids, method="compose").set_duration(dur)

    lt_array = create_lower_third_overlay(lower_third_text, sub_label)
    lt_clip = ImageClip(lt_array).set_duration(dur)
    logo_clip = ImageClip(LOGO_ARRAY).set_duration(dur)

    composed = CompositeVideoClip([base_video, lt_clip, logo_clip], size=(1280, 720))
    composed = composed.set_duration(dur).set_audio(audio_clip)
    return composed, dur

def build_chapter_bumper(story_num, chapter_title, chime_path):
    dur = 2.4
    frame = create_chapter_bumper_frame(story_num, chapter_title)
    img_clip = ImageClip(frame).set_duration(dur)
    logo_clip = ImageClip(LOGO_ARRAY).set_duration(dur)
    chime_audio = AudioFileClip(chime_path).subclip(0, dur)
    comp = CompositeVideoClip([img_clip, logo_clip], size=(1280, 720)).set_duration(dur).set_audio(chime_audio)
    return comp, dur

def format_timestamp(seconds):
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"

def main():
    stories = fetch_fresh_medical_news(target_count=5)
    script_data = generate_script_with_gemini(stories)

    chime_path = "temp_Media/bumper_chime.wav"
    generate_bumper_chime(chime_path, duration_sec=2.4)

    all_scene_clips = []
    current_time = 0.0
    timestamps = []

    print("Building Intro scene...")
    timestamps.append("00:00 What New Medical Breakthroughs Mean For Your Body")
    intro_data = script_data["intro"]
    intro_clip, intro_dur = build_spoken_scene(
        intro_data["narration"],
        intro_data.get("lower_third", "MEDPULSE 5: DAILY HEALTH BRIEFING"),
        "MEDPULSE 5  |  HEALTH, MEDICATIONS & LONGEVITY",
        intro_data.get("search_queries", ["doctor smiling clinic", "vitamin capsules close up"]),
        "scene_intro"
    )
    all_scene_clips.append(intro_clip)
    current_time += intro_dur

    for s_idx, story in enumerate(script_data["stories"], 1):
        ch_title = story.get("chapter_title", f"Medical Breakthrough #{s_idx}")
        timestamps.append(f"{format_timestamp(current_time)} Story #{s_idx}: {ch_title}")

        print(f"Building Story #{s_idx} Chapter Bumper: {ch_title}...")
        bumper_clip, b_dur = build_chapter_bumper(s_idx, ch_title, chime_path)
        all_scene_clips.append(bumper_clip)
        current_time += b_dur

        acts = story.get("acts", [])
        for a_idx, act in enumerate(acts, 1):
            act_type = act.get("act_type", f"Part {a_idx}")
            print(f"  Building Story #{s_idx} - Act {a_idx} ({act_type})...")
            sub_lbl = f"STORY #{s_idx} OF 5  •  {act_type.upper()}"
            sc_clip, sc_dur = build_spoken_scene(
                act["narration"],
                act.get("lower_third", ch_title),
                sub_lbl,
                act.get("search_queries", ["doctor patient clinic", "medical treatment hospital"]),
                f"s{s_idx}_a{a_idx}"
            )
            all_scene_clips.append(sc_clip)
            current_time += sc_dur

    print("Building Outro scene...")
    timestamps.append(f"{format_timestamp(current_time)} Your Daily Health Takeaway & Question of the Day")
    outro_data = script_data["outro"]
    outro_clip, outro_dur = build_spoken_scene(
        outro_data["narration"],
        outro_data.get("lower_third", "SUBSCRIBE TO MEDPULSE 5"),
        "MEDPULSE 5  |  DAILY MEDICAL & HEALTH NEWS",
        outro_data.get("search_queries", ["doctor shaking hands patient", "healthy seniors walking"]),
        "scene_outro"
    )
    all_scene_clips.append(outro_clip)
    current_time += outro_dur

    print(f"Total documentary duration: {current_time/60:.2f} minutes ({int(current_time)} seconds).")

    final_voice_video = concatenate_videoclips(all_scene_clips, method="compose")

    bg_wav = "temp_Media/ambient_bg.wav"
    generate_ambient_background_music(bg_wav, duration_sec=60)
    bg_music = AudioFileClip(bg_wav)
    bg_looped = afx.audio_loop(bg_music, duration=final_voice_video.duration).volumex(0.05)

    from moviepy.audio.AudioClip import CompositeAudioClip
    mixed_audio = CompositeAudioClip([final_voice_video.audio, bg_looped]).set_duration(final_voice_video.duration)
    final_video = final_voice_video.set_audio(mixed_audio)

    output_video_path = "output/final_video.mp4"
    print("Rendering final HD video (1280x720) with multi-core speed optimization...")
    final_video.write_videofile(
        output_video_path,
        fps=24,
        codec="libx264",
        audio_codec="aac",
        audio_bitrate="128k",
        threads=4,
        ffmpeg_params=[
            "-preset", "veryfast",
            "-crf", "21",
            "-maxrate", "2200k",
            "-bufsize", "4400k",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart"
        ]
    )

    new_used_items = []
    for s in stories:
        new_used_items.append(s["link"])
        new_used_items.append(s["norm_title"])
    save_to_set(USED_NEWS_FILE, new_used_items)

    yt_titles = script_data.get("youtube_titles", [
        "New Pill & Organ Repair: 5 Medical Breakthroughs Changing Healthcare",
        "1 Daily Vitamin & New Treatments That Reverse Chronic Disease",
        "Restoring Organ Health & Stopping Stubborn Disease: 5 New Discoveries"
    ])
    thumb_prompt = script_data.get(
        "thumbnail_prompt",
        "Photorealistic 8k medical documentary thumbnail, 16:9 widescreen aspect ratio, glowing golden vitamin capsule repairing a human heart with vibrant ruby red and warm gold lighting, bold 3D yellow and white text on the left reading 'ONE DAILY PILL?', ultra-sharp focus."
    )
    desc_intro = script_data.get("description_intro", "Discover 5 exciting medical breakthroughs, new medications, vitamin discoveries, and organ treatments in today's MedPulse 5 briefing.")
    tags_str = script_data.get("tags", "new medications, medical breakthroughs, health news, vitamins, organ repair, chronic disease treatment, longevity, clinical trials, MedPulse 5")
    hero_num = script_data.get("synchronized_hero_story_number", 1)
    sync_hook = script_data.get("synchronized_thumb_hook", "ONE DAILY PILL?")

    sources_block = "\n".join([
        f"- Story #{i}: {s['title']}\n  Source: {s['link']}"
        for i, s in enumerate(stories, 1)
    ])
    chapters_block = "\n".join(timestamps)

    sep = "=" * 68
    t1 = yt_titles[0] if len(yt_titles) > 0 else "New Pill & Organ Repair: 5 Medical Breakthroughs For Your Body"
    t2 = yt_titles[1] if len(yt_titles) > 1 else "Reversing Organ Damage & New Treatments: 5 Health Breakthroughs"
    t3 = yt_titles[2] if len(yt_titles) > 2 else "New Medications, Vitamins & Cures Changing Modern Medicine"

    details_lines = [
        sep,
        "3 عناوين مقترحة للفيديو (مرتبة حسب قوة البحث في يوتيوب - انسخ واحداً منها)",
        sep,
        f"الخيار 1 (موصى به - متطابق 100% مع الصورة المصغرة وخبر القصة رقم #{hero_num}):",
        t1,
        "",
        "الخيار 2:",
        t2,
        "",
        "الخيار 3:",
        t3,
        "",
        "",
        sep,
        "وصف الصورة المصغرة (مربوط برمجياً بالخيار 1 الموصى به)",
        f'(العبارة المعتمدة داخل الصورة: "{sync_hook}")',
        "(انسخه وضعه في موقع توليد الصور المجاني واختر مقاس عرضي 16:9)",
        sep,
        thumb_prompt,
        "",
        "",
        sep,
        "صندوق الوصف الكامل الجاهز للنسخ واللصق في يوتيوب",
        sep,
        desc_intro,
        "",
        "In today's episode of MedPulse 5, we break down five exciting medical breakthroughs—covering new pills and medications, vitamin and nutrition science, stubborn disease treatments, and ways to protect and repair your vital organs.",
        "",
        "VIDEO CHAPTERS (TIMESTAMPS):",
        chapters_block,
        "",
        "CLINICAL SOURCES & FURTHER READING:",
        sources_block,
        "",
        "MEDICAL DISCLAIMER:",
        "The content on MedPulse 5 is for educational and informational purposes only and is not a substitute for professional medical advice, diagnosis, or treatment. Always consult a qualified healthcare provider with any questions you may have regarding a medical condition, medication, or supplement.",
        "",
        "Subscribe to MedPulse 5 for your daily briefing on medical breakthroughs, new treatments, vitamins, and healthy longevity!",
        "",
        "#MedicalBreakthroughs #HealthNews #NewMedications #Vitamins #OrganHealth #MedPulse5",
        "",
        "",
        sep,
        "الكلمات المفتاحية الجاهزة للنسخ واللصق في قسم العلامات",
        sep,
        tags_str,
        ""
    ]

    details_path = "output/youtube_details.txt"
    with open(details_path, "w", encoding="utf-8") as f:
        f.write("\n".join(details_lines))

    print("Successfully created output/final_video.mp4 and output/youtube_details.txt!")

if __name__ == "__main__":
    main()
