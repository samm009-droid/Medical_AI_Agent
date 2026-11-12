import os
import re
import json
import math
import time
import wave
import struct
import random
import requests
import feedparser
import asyncio
import edge_tts
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import google.generativeai as genai
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (
    VideoFileClip, AudioFileClip, ImageClip,
    CompositeVideoClip, concatenate_videoclips
)

# ==========================================
# 1. الإعدادات والمفاتيح السرية
# ==========================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "").strip()

USED_NEWS_FILE = "used_news.txt"
USED_VIDEOS_FILE = "used_videos.txt"

RSS_FEEDS = [
    ("MedicalXpress", "https://medicalxpress.com/rss-feed/"),
    ("News-Medical", "https://www.news-medical.net/tag/feed/Medical-Research.aspx"),
    ("EurekAlert", "https://www.eurekalert.org/rss/medicine_health.xml"),
    ("ScienceDaily Health", "https://www.sciencedaily.com/rss/health_medicine.xml"),
    ("ScienceDaily Brain", "https://www.sciencedaily.com/rss/mind_brain.xml"),
    ("ScienceDaily Longevity", "https://www.sciencedaily.com/rss/living_well.xml"),
]

# كلمات محظورة (حساسة لإعلانات يوتيوب أو إدارية غير طبية)
BANNED_KEYWORDS = [
    "sexual", "rape", "assault", "abuse", "violence", "suicide", "self-harm",
    "homicide", "murder", "gun", "shooting", "abortion", "transgender", "lgbt",
    "politics", "political", "trump", "biden", "election", "war", "military",
    "racism", "racial", "discrimination", "protest", "lawsuit", "tax", "insurance",
    "billing", "staffing", "burnout", "workplace", "nurse shortage", "hospital budget",
    "parenting app", "toddlers", "preschool", "climate policy", "carbon tax"
]

# كلمات ذات أولوية قصوى (جسم الإنسان، الأمراض، الأدوية، الدماغ، القلب، طول العمر)
MEDICAL_PRIORITY_KEYWORDS = [
    "brain", "alzheimer", "dementia", "parkinson", "memory", "stroke", "neuron",
    "heart", "cardiac", "artery", "blood pressure", "cholesterol", "vascular",
    "cancer", "tumor", "oncology", "chemotherapy", "immunotherapy",
    "diabetes", "insulin", "glucose", "obesity", "metabolism", "weight loss",
    "liver", "kidney", "lung", "gut", "microbiome", "immune", "inflammation",
    "longevity", "aging", "anti-aging", "lifespan", "dna", "gene", "genetic",
    "stem cell", "drug", "pill", "therapy", "treatment", "clinical trial",
    "vitamin", "supplement", "sleep", "pain", "virus", "infection", "antibiotic"
]

FALLBACK_QUERIES = [
    "medical research laboratory",
    "scientist microscope",
    "dna double helix",
    "human brain scan",
    "heart monitor hospital",
    "pharmaceutical medicine pills",
    "doctor analyzing medical scan",
    "blood cells microbiology"
]

# ==========================================
# 2. إدارة الذاكرة (عدم تكرار الأخبار والفيديوهات)
# ==========================================
def load_set(filepath):
    if not os.path.exists(filepath):
        return set()
    with open(filepath, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def save_to_file(filepath, items):
    with open(filepath, "a", encoding="utf-8") as f:
        for item in items:
            f.write(f"{item}\n")

def clean_html(raw_html):
    if not raw_html:
        return ""
    cleanr = re.compile('<.*?>')
    text = re.sub(cleanr, '', raw_html)
    return re.sub(r'\s+', ' ', text).strip()

def format_pub_date(entry):
    now_utc = datetime.now(timezone.utc)
    for attr in ["published", "updated", "created"]:
        val = getattr(entry, attr, None)
        if val:
            try:
                dt = parsedate_to_datetime(val)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt > now_utc:
                    dt = now_utc
                return dt.strftime("%B %d, %Y")
            except Exception:
                pass
    return now_utc.strftime("%B %d, %Y")

# ==========================================
# 3. جلب وفلترة الأخبار الطبية (متنوعة وآمنة)
# ==========================================
def score_article(title, summary):
    text = f"{title} {summary}".lower()
    for bad in BANNED_KEYWORDS:
        if bad.lower() in text:
            return -999
    score = 0
    for kw in MEDICAL_PRIORITY_KEYWORDS:
        if kw.lower() in text:
            score += 2
    return score

def fetch_fresh_medical_news(count=5):
    print("📡 Fetching fresh medical breakthroughs from 6 global sources...")
    used_news = load_set(USED_NEWS_FILE)
    candidates = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    for source_name, url in RSS_FEEDS:
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            feed = feedparser.parse(resp.content)
            for entry in feed.entries[:25]:
                title = clean_html(getattr(entry, "title", ""))
                link = getattr(entry, "link", "").strip()
                summary = clean_html(getattr(entry, "summary", getattr(entry, "description", "")))
                if not title or not link:
                    continue
                norm_title = re.sub(r'[^a-z0-9]', '', title.lower())
                if link in used_news or norm_title in used_news:
                    continue
                sc = score_article(title, summary)
                if sc < 0:
                    continue
                pub_date = format_pub_date(entry)
                candidates.append({
                    "source": source_name,
                    "title": title,
                    "summary": summary[:700],
                    "link": link,
                    "date": pub_date,
                    "norm_title": norm_title,
                    "score": sc
                })
        except Exception as e:
            print(f"⚠️ Warning fetching {source_name}: {e}")

    # ترتيب حسب الأهمية الطبية مع ضمان تنوع المصادر (بحد أقصى خبران من نفس المصدر)
    candidates.sort(key=lambda x: x["score"], reverse=True)
    selected = []
    source_counts = {}
    seen_norms = set()

    for item in candidates:
        if len(selected) >= count:
            break
        src = item["source"]
        if item["norm_title"] in seen_norms:
            continue
        if source_counts.get(src, 0) >= 2:
            continue
        selected.append(item)
        seen_norms.add(item["norm_title"])
        source_counts[src] = source_counts.get(src, 0) + 1

    # إذا لم يكتمل العدد، نكمل من الباقي الآمن
    for item in candidates:
        if len(selected) >= count:
            break
        if item["norm_title"] not in seen_norms:
            selected.append(item)
            seen_norms.add(item["norm_title"])

    if len(selected) < count:
        raise RuntimeError(f"Not enough fresh medical news found (found {len(selected)}).")

    print(f"✅ Selected {len(selected)} diverse, ad-safe medical breakthroughs:")
    for i, s in enumerate(selected, 1):
        print(f"   {i}. [{s['source']}] {s['title']} (Score: {s['score']})")
    return selected

# ==========================================
# 4. كتابة السيناريو بالذكاء الاصطناعي (Gemini)
# ==========================================
def get_available_gemini_models():
    """يكتشف تلقائياً أحدث نماذج Gemini المتاحة في حساب المستخدم لمنع أخطاء 404 مستقبلاً"""
    preferred = [
        "gemini-3.8-flash",
        "gemini-flash-latest",
        "gemini-3-flash-preview",
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash",
    ]
    discovered = []
    try:
        for m in genai.list_models():
            methods = getattr(m, "supported_generation_methods", []) or []
            if "generateContent" in methods:
                name = m.name.replace("models/", "")
                low = name.lower()
                if "gemini" in low and not any(x in low for x in ["embedding", "imagen", "vision", "tts", "audio", "robotics", "computer-use"]):
                    discovered.append(name)
    except Exception as e:
        print(f"⚠️ Note: dynamic model listing returned: {e}")

    flash_models = [m for m in discovered if "flash" in m.lower()]
    other_models = [m for m in discovered if "flash" not in m.lower()]

    final_list = []
    # نضع أولاً النماذج المكتشفة فعلياً في السيرفر + النماذج المفضلة
    for m in preferred + flash_models + other_models:
        if m not in final_list:
            final_list.append(m)
    print(f"🔎 Available Gemini models to try: {final_list[:6]}")
    return final_list

def generate_script_with_gemini(articles):
    print("🧠 Generating high-retention documentary script via Gemini AI...")
    genai.configure(api_key=GEMINI_API_KEY)

    articles_text = ""
    for idx, art in enumerate(articles, 1):
        articles_text += (
            f"\n--- STORY {idx} ---\n"
            f"Headline: {art['title']}\n"
            f"Summary: {art['summary']}\n"
        )

    prompt = f"""
You are the lead science communicator and executive producer for 'MedPulse 5', a top US medical & health documentary YouTube channel.
Transform these 5 real medical research breakthroughs into a deeply engaging, 12-to-15 minute video script (approximately 2,000 to 2,300 spoken words total).

INPUT STORIES:
{articles_text}

STRICT SPOKEN SCRIPT RULES:
1. NEVER say website names (like MedicalXpress, ScienceDaily, EurekAlert, News-Medical) or publication dates out loud in the narration! Instead say phrases like "Researchers just discovered...", "A major clinical study reveals...", or "Scientists at a leading university found...". (Full links are in the written description).
2. Speak directly to the viewer using "You" and "Your body / Your brain / Your heart".
3. Use vivid everyday analogies to explain complex biology (e.g., comparing immune cells to security guards, DNA repair to fixing a broken zipper, arteries to city highways).
4. Start the episode at 0:00 with a gripping 20-second Cold-Open Hook teasing the most shocking discovery of the episode without any slow greeting.
5. In the Outro, naturally thank the viewer and invite them to subscribe to "MedPulse 5" for their daily dose of medical breakthroughs.
6. Provide 1 best high-CTR viral YouTube title (under 75 chars, curiosity-driven, human-health focused) and 3 alternative viral titles.
7. For each scene, provide 3 distinct, concrete visual search queries for Pexels HD stock footage (e.g., ["human heart medical scan", "doctor examining patient", "red blood cells microscope"]).

Return ONLY valid JSON matching this exact structure:
{{
  "recommended_title": "Main viral YouTube title here",
  "alternative_titles": [
    "Alternative viral title 1",
    "Alternative viral title 2",
    "Alternative viral title 3"
  ],
  "youtube_description_intro": "2-paragraph SEO-rich summary of today's 5 medical breakthroughs for MedPulse 5.",
  "youtube_tags": ["medical breakthroughs", "health news", "longevity", "science daily", "MedPulse 5"],
  "hook": {{
    "narration": "35-45 words gripping cold-open hook speaking directly to the viewer...",
    "banner_headline": "SHORT PUNCHY HOOK HEADLINE (MAX 55 CHARS)",
    "banner_sub": "MEDPULSE 5  •  5 NEW MEDICAL BREAKTHROUGHS",
    "search_queries": ["medical laboratory research", "human brain scan", "dna helix"]
  }},
  "stories": [
    {{
      "story_number": 1,
      "category": "NEUROSCIENCE / CARDIOLOGY / ONCOLOGY / LONGEVITY",
      "chapter_title": "Compelling 6-10 word headline for the chapter bumper",
      "acts": [
        {{
          "act_name": "The Discovery",
          "narration": "95-110 words explaining the core breakthrough and how it affects the viewer...",
          "banner_headline": "UPPERCASE SUMMARY OF THIS ACT (MAX 55 CHARS)",
          "banner_sub": "STORY #1  •  THE BREAKTHROUGH",
          "search_queries": ["query 1", "query 2", "query 3"]
        }},
        {{
          "act_name": "How It Works Inside Your Body",
          "narration": "95-110 words using a simple everyday analogy to explain the biological mechanism...",
          "banner_headline": "UPPERCASE MECHANISM SUMMARY (MAX 55 CHARS)",
          "banner_sub": "STORY #1  •  INSIDE YOUR BODY",
          "search_queries": ["query 1", "query 2", "query 3"]
        }},
        {{
          "act_name": "The Scientific Evidence",
          "narration": "95-110 words detailing what researchers observed in patients or lab tests...",
          "banner_headline": "UPPERCASE CLINICAL FINDINGS (MAX 55 CHARS)",
          "banner_sub": "STORY #1  •  CLINICAL EVIDENCE",
          "search_queries": ["query 1", "query 2", "query 3"]
        }},
        {{
          "act_name": "What This Means For Your Health",
          "narration": "95-110 words on practical future impact, prevention, and hope...",
          "banner_headline": "UPPERCASE FUTURE IMPACT (MAX 55 CHARS)",
          "banner_sub": "STORY #1  •  YOUR HEALTH TAKEAWAY",
          "search_queries": ["query 1", "query 2", "query 3"]
        }}
      ]
    }}
  ],
  "outro": {{
    "narration": "45-60 words inspiring conclusion asking viewers which of the 5 breakthroughs surprised them most, reminding them source links are in the description, and inviting them to subscribe to MedPulse 5.",
    "banner_headline": "SUBSCRIBE TO MEDPULSE 5 FOR DAILY BREAKTHROUGHS",
    "banner_sub": "ALL SCIENTIFIC STUDY LINKS IN DESCRIPTION BELOW",
    "search_queries": ["doctor smiling hospital", "healthy senior walking nature", "futuristic medical technology"]
  }}
}}
"""

    models_to_try = get_available_gemini_models()
    last_err = None
    for model_name in models_to_try:
        for attempt in range(2):
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(
                    prompt,
                    generation_config={"response_mime_type": "application/json", "temperature": 0.7}
                )
                raw = response.text.strip()
                raw = re.sub(r"^```json\s*", "", raw)
                raw = re.sub(r"\s*```$", "", raw)
                data = json.loads(raw)
                if "stories" in data and len(data["stories"]) == 5:
                    print(f"✅ Script generated successfully using {model_name}!")
                    return data
            except Exception as e:
                last_err = e
                err_str = str(e)
                print(f"⚠️ Gemini ({model_name}) attempt {attempt+1} failed: {err_str[:160]}")
                if "404" in err_str or "no longer available" in err_str.lower() or "not found" in err_str.lower():
                    break  # انتقل فوراً للنموذج التالي إذا كان الإصدار قديماً
                time.sleep(4)
    raise RuntimeError(f"Failed to generate script from Gemini: {last_err}")

# ==========================================
# 5. توليد الصوت البشري والمؤثر الصوتي للانتقالات
# ==========================================
async def _edge_tts_save(text, out_path):
    communicate = edge_tts.Communicate(text, voice="en-US-ChristopherNeural", rate="+4%", pitch="-1Hz")
    await communicate.save(out_path)

def generate_voiceover(text, out_path):
    clean_text = re.sub(r'[*_#`~]', '', text).strip()
    for attempt in range(4):
        try:
            asyncio.run(_edge_tts_save(clean_text, out_path))
            if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
                return
        except Exception as e:
            print(f"⚠️ TTS attempt {attempt+1} error: {e}")
            time.sleep(3)
    raise RuntimeError(f"Failed to generate TTS audio for: {out_path}")

def create_chime_wav(filepath, duration=2.4, sample_rate=44100):
    n_samples = int(duration * sample_rate)
    with wave.open(filepath, 'w') as wav_file:
        wav_file.setparams((1, 2, sample_rate, n_samples, 'NONE', 'not compressed'))
        for i in range(n_samples):
            t = i / sample_rate
            env1 = math.exp(-t * 3.5)
            tone1 = math.sin(2 * math.pi * 523.25 * t) * env1
            tone2 = 0.0
            if t >= 0.14:
                t2 = t - 0.14
                env2 = math.exp(-t2 * 2.2)
                tone2 = (math.sin(2 * math.pi * 659.25 * t2) + 0.5 * math.sin(2 * math.pi * 1046.50 * t2)) * env2
            val = int(max(-1.0, min(1.0, (tone1 + tone2) * 0.22)) * 32767)
            wav_file.writeframesraw(struct.pack('<h', val))

# ==========================================
# 6. تحميل مقاطع الفيديو المتحركة من Pexels
# ==========================================
def fetch_pexels_clips(queries, used_videos, clips_needed=3, prefix="scene"):
    headers = {"Authorization": PEXELS_API_KEY}
    downloaded = []
    search_pool = list(queries) + random.sample(FALLBACK_QUERIES, min(4, len(FALLBACK_QUERIES)))

    for q in search_pool:
        if len(downloaded) >= clips_needed:
            break
        try:
            url = f"https://api.pexels.com/videos/search?query={requests.utils.quote(q)}&per_page=12&orientation=landscape"
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                continue
            videos = r.json().get("videos", [])
            for v in videos:
                if len(downloaded) >= clips_needed:
                    break
                vid_id = str(v.get("id"))
                if vid_id in used_videos:
                    continue
                files = v.get("video_files", [])
                best_file = None
                for vf in files:
                    w = vf.get("width", 0) or 0
                    h = vf.get("height", 0) or 0
                    if w >= 1280 and h >= 720 and vf.get("file_type") == "video/mp4":
                        best_file = vf
                        break
                if not best_file and files:
                    best_file = files[0]
                if not best_file or not best_file.get("link"):
                    continue

                out_name = f"temp_{prefix}_{len(downloaded)}_{vid_id}.mp4"
                vr = requests.get(best_file["link"], stream=True, timeout=25)
                if vr.status_code == 200:
                    with open(out_name, "wb") as f:
                        for chunk in vr.iter_content(chunk_size=65536):
                            if chunk:
                                f.write(chunk)
                    if os.path.exists(out_name) and os.path.getsize(out_name) > 50000:
                        downloaded.append(out_name)
                        used_videos.add(vid_id)
                        save_to_file(USED_VIDEOS_FILE, [vid_id])
        except Exception as e:
            print(f"⚠️ Pexels fetch warning for '{q}': {e}")

    return downloaded

# ==========================================
# 7. تجهيز شعار القناة والرسوم الاحترافية
# ==========================================
def get_font(size, bold=True):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for p in paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()

_CACHED_LOGO_PATH = None

def find_repo_logo():
    global _CACHED_LOGO_PATH
    if _CACHED_LOGO_PATH is not None:
        return _CACHED_LOGO_PATH
    exts = (".png", ".jpg", ".jpeg", ".webp")
    ignore_prefixes = ("temp_", "ov_", "ch_", "final_")
    candidates = []
    for fname in os.listdir("."):
        low = fname.lower()
        if low.endswith(exts) and not low.startswith(ignore_prefixes):
            candidates.append(fname)
    candidates.sort(key=lambda x: (0 if "logo" in x.lower() else 1, x))
    _CACHED_LOGO_PATH = candidates[0] if candidates else ""
    if _CACHED_LOGO_PATH:
        print(f"🛡️ Loaded channel logo image: {_CACHED_LOGO_PATH}")
    return _CACHED_LOGO_PATH

def build_logo_badge(size=72, alpha=235):
    """يجهز شعار القناة داخل دائرة أنيقة بحواف سماوية مضيئة"""
    badge = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    logo_path = find_repo_logo()

    if logo_path and os.path.exists(logo_path):
        try:
            src = Image.open(logo_path).convert("RGBA")
            w, h = src.size
            m = min(w, h)
            left = (w - m) // 2
            top = (h - m) // 2
            src = src.crop((left, top, left + m, top + m)).resize((size, size), Image.LANCZOS)

            mask = Image.new("L", (size, size), 0)
            mdraw = ImageDraw.Draw(mask)
            mdraw.ellipse((2, 2, size - 3, size - 3), fill=alpha)
            badge.paste(src, (0, 0), mask)

            bdraw = ImageDraw.Draw(badge)
            bdraw.ellipse((1, 1, size - 2, size - 2), outline=(0, 215, 255, 220), width=2)
            return badge
        except Exception as e:
            print(f"⚠️ Fallback logo badge used due to: {e}")

    bdraw = ImageDraw.Draw(badge)
    bdraw.ellipse((2, 2, size - 3, size - 3), fill=(8, 18, 38, alpha), outline=(0, 215, 255, 230), width=2)
    f5 = get_font(int(size * 0.55), bold=True)
    bdraw.text((size // 2 - int(size * 0.18), size // 2 - int(size * 0.30)), "5", font=f5, fill=(0, 225, 255, 255))
    return badge

def create_overlay_png(headline, subtext, story_idx, out_path):
    """يرسم شعار القناة في أقصى الزاوية العلوية اليمنى + شريط الأخبار السفلي النحيف"""
    img = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 1. شعار القناة في أقصى الزاوية العلوية اليمنى
    logo_badge = build_logo_badge(size=68, alpha=230)
    img.paste(logo_badge, (1280 - 68 - 24, 22), logo_badge)

    # 2. الشريط الإخباري السفلي النحيف (76 بكسل فقط في أسفل الشاشة)
    bar_y = 644
    draw.rectangle([0, bar_y, 1280, 720], fill=(7, 14, 28, 228))
    draw.rectangle([0, bar_y, 1280, bar_y + 3], fill=(0, 215, 255, 255))
    draw.rectangle([0, bar_y + 3, 10, 720], fill=(0, 215, 255, 255))

    font_sub = get_font(15, bold=True)
    font_head = get_font(22, bold=True)

    sub_clean = (subtext or "MEDPULSE 5  •  MEDICAL BREAKTHROUGH").upper()[:65]
    head_clean = (headline or "LATEST CLINICAL RESEARCH DISCOVERY").upper()[:62]

    draw.text((26, bar_y + 11), sub_clean, font=font_sub, fill=(0, 215, 255, 255))
    draw.text((26, bar_y + 34), head_clean, font=font_head, fill=(255, 255, 255, 255))

    img.save(out_path, "PNG")
    return out_path

def create_chapter_bumper(story_idx, headline, category, out_path):
    """يرسم شاشة الانتقالة التصويرية السريعة بشعار واسم القناة MEDPULSE 5 قبل كل خبر"""
    img = Image.new("RGB", (1280, 720), (6, 13, 26))
    draw = ImageDraw.Draw(img)

    draw.rectangle([28, 28, 1252, 692], outline=(0, 180, 230), width=2)
    draw.rectangle([0, 708, 1280, 720], fill=(0, 215, 255))

    # 1. شعار القناة + اسم MEDPULSE 5 في أعلى شاشة الانتقالة
    logo_badge = build_logo_badge(size=78, alpha=255)
    img.paste(logo_badge, (490, 56), logo_badge)
    font_brand = get_font(30, bold=True)
    draw.text((582, 78), "MEDPULSE 5", font=font_brand, fill=(255, 255, 255))

    # 2. كبسولة رقم القصة
    font_badge = get_font(20, bold=True)
    font_cat = get_font(22, bold=True)
    font_title = get_font(40, bold=True)
    font_foot = get_font(18, bold=False)

    draw.rounded_rectangle([400, 165, 880, 215], radius=24, fill=(0, 215, 255))
    badge_txt = f"STORY 0{story_idx} OF 05  •  MEDICAL BREAKTHROUGH"
    draw.text((435, 178), badge_txt, font=font_badge, fill=(6, 13, 26))

    cat_txt = (category or "CLINICAL RESEARCH").upper()
    draw.text((640 - len(cat_txt) * 6, 245), cat_txt, font=font_cat, fill=(0, 215, 255))

    draw.line([480, 295, 800, 295], fill=(40, 80, 120), width=2)

    words = headline.upper().split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 <= 34:
            cur = f"{cur} {w}".strip()
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)

    y_text = 335
    for line in lines[:3]:
        x_pos = max(80, 640 - int(len(line) * 12))
        draw.text((x_pos, y_text), line, font=font_title, fill=(255, 255, 255))
        y_text += 56

    foot_txt = "FULL SCIENTIFIC STUDY & SOURCE LINK IN DESCRIPTION BELOW"
    draw.text((355, 610), foot_txt, font=font_foot, fill=(160, 195, 220))

    img.save(out_path, "PNG")
    return out_path

# ==========================================
# 8. بناء المشاهد وتجميع الفيديو النهائي
# ==========================================
def build_scene_clip(narration, banner_head, banner_sub, queries, story_idx, scene_id, used_videos):
    aud_path = f"temp_aud_{scene_id}.mp3"
    generate_voiceover(narration, aud_path)
    audio_clip = AudioFileClip(aud_path)
    dur = audio_clip.duration + 0.25

    video_paths = fetch_pexels_clips(queries, used_videos, clips_needed=3, prefix=scene_id)
    sub_clips = []
    target_each = dur / max(1, len(video_paths))

    for vp in video_paths:
        try:
            vc = VideoFileClip(vp).without_audio()
            vc = vc.resize((1280, 720))
            if vc.duration > target_each + 1.0:
                start_t = random.uniform(0, max(0.1, vc.duration - target_each - 0.5))
                vc = vc.subclip(start_t, start_t + target_each)
            else:
                loops = int(math.ceil(target_each / max(0.5, vc.duration)))
                vc = concatenate_videoclips([vc] * loops).subclip(0, target_each)
            vc = vc.fadein(0.25).fadeout(0.25)
            sub_clips.append(vc)
        except Exception as e:
            print(f"⚠️ Clip load warning ({vp}): {e}")

    if sub_clips:
        bg_video = concatenate_videoclips(sub_clips, method="compose").set_duration(dur)
    else:
        bg_img = create_chapter_bumper(story_idx or 1, banner_head, "MEDPULSE 5", f"temp_fb_{scene_id}.png")
        bg_video = ImageClip(bg_img).set_duration(dur)

    ov_png = f"temp_ov_{scene_id}.png"
    create_overlay_png(banner_head, banner_sub, story_idx, ov_png)
    ov_clip = ImageClip(ov_png).set_duration(dur)

    final_scene = CompositeVideoClip([bg_video, ov_clip]).set_audio(audio_clip).set_duration(dur)
    return final_scene

def build_chapter_transition(story_idx, headline, category, chime_path):
    dur = 2.4
    img_path = f"temp_ch_{story_idx}.png"
    create_chapter_bumper(story_idx, headline, category, img_path)
    aud = AudioFileClip(chime_path).set_duration(dur)
    clip = ImageClip(img_path).set_duration(dur).set_audio(aud).fadein(0.3).fadeout(0.3)
    return clip

def format_timestamp(seconds):
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"

# ==========================================
# 9. التشغيل الرئيسي وتصدير الفيديو وملف يوتيوب
# ==========================================
def main():
    print("🚀 Starting MedPulse 5 Automated Video Factory...")
    if not GEMINI_API_KEY or not PEXELS_API_KEY:
        raise RuntimeError("Missing GEMINI_API_KEY or PEXELS_API_KEY in GitHub Secrets!")

    articles = fetch_fresh_medical_news(count=5)
    script_data = generate_script_with_gemini(articles)
    used_videos = load_set(USED_VIDEOS_FILE)

    chime_path = "temp_chime.wav"
    create_chime_wav(chime_path, duration=2.4)

    all_clips = []
    timestamps = [("00:00", "Cold-Open Hook: Today's Top 5 Medical Breakthroughs")]
    current_time = 0.0

    # 1. مشهد الخُطّاف التشويقي (Hook)
    print("🎬 Rendering Cold-Open Hook...")
    hook = script_data["hook"]
    hook_clip = build_scene_clip(
        hook["narration"],
        hook.get("banner_headline", "5 NEW MEDICAL BREAKTHROUGHS"),
        hook.get("banner_sub", "MEDPULSE 5  •  DAILY HEALTH BRIEFING"),
        hook.get("search_queries", ["medical laboratory", "human brain scan", "dna"]),
        0, "hook", used_videos
    )
    all_clips.append(hook_clip)
    current_time += hook_clip.duration

    # 2. القصص الخمس (انتقالة الشعار + 4 فصول لكل قصة)
    for idx, story in enumerate(script_data["stories"], 1):
        print(f"🎬 Rendering Story #{idx}: {story.get('chapter_title', '')}...")
        timestamps.append((format_timestamp(current_time), f"Breakthrough #{idx}: {story.get('chapter_title', articles[idx-1]['title'])}"))

        ch_clip = build_chapter_transition(
            idx,
            story.get("chapter_title", articles[idx-1]["title"]),
            story.get("category", "MEDICAL BREAKTHROUGH"),
            chime_path
        )
        all_clips.append(ch_clip)
        current_time += ch_clip.duration

        for a_idx, act in enumerate(story.get("acts", []), 1):
            sc_clip = build_scene_clip(
                act["narration"],
                act.get("banner_headline", story.get("chapter_title", "")),
                act.get("banner_sub", f"BREAKTHROUGH #{idx}  •  {act.get('act_name', '').upper()}"),
                act.get("search_queries", ["medical research", "doctor hospital", "microscope"]),
                idx, f"s{idx}_a{a_idx}", used_videos
            )
            all_clips.append(sc_clip)
            current_time += sc_clip.duration

    # 3. الخاتمة (Outro)
    print("🎬 Rendering Outro...")
    outro = script_data["outro"]
    timestamps.append((format_timestamp(current_time), "Final Takeaway & Health Summary"))
    outro_clip = build_scene_clip(
        outro["narration"],
        outro.get("banner_headline", "SUBSCRIBE TO MEDPULSE 5 FOR DAILY BREAKTHROUGHS"),
        outro.get("banner_sub", "ALL SCIENTIFIC STUDY LINKS IN DESCRIPTION BELOW"),
        outro.get("search_queries", ["healthy lifestyle", "doctor smiling", "medical technology"]),
        0, "outro", used_videos
    )
    all_clips.append(outro_clip)

    print("⚙️ Concatenating and encoding final 720p HD video...")
    final_video = concatenate_videoclips(all_clips, method="compose")
    final_video.write_videofile(
        "final_video.mp4",
        fps=24,
        codec="libx264",
        audio_codec="aac",
        audio_bitrate="128k",
        preset="ultrafast",
        threads=4,
        ffmpeg_params=["-crf", "27", "-maxrate", "950k", "-bufsize", "1900k", "-movflags", "+faststart"]
    )

    # حفظ الأخبار المستخدمة حتى لا تتكرر أبداً
    new_used_entries = []
    for art in articles:
        new_used_entries.append(art["link"])
        new_used_entries.append(art["norm_title"])
    save_to_file(USED_NEWS_FILE, new_used_entries)

    # كتابة ملف تفاصيل يوتيوب الجاهز للنسخ واللصق
    rec_title = script_data.get("recommended_title", articles[0]["title"])
    alt_titles = script_data.get("alternative_titles", [])
    desc_intro = script_data.get("youtube_description_intro", "")
    tags_list = script_data.get("youtube_tags", [])
    base_tags = [
        "MedPulse 5", "medical breakthroughs", "health news", "medical discoveries",
        "longevity science", "brain health", "heart health", "new medical treatments",
        "clinical research", "science news", "disease prevention"
    ]
    all_tags = list(dict.fromkeys(base_tags + tags_list))

    ts_block = "\n".join([f"{t} - {label}" for t, label in timestamps])
    sources_block = "\n".join([
        f"{i}. {art['title']}\n   Source: {art['source']} ({art['date']})\n   Study Link: {art['link']}"
        for i, art in enumerate(articles, 1)
    ])
    alt_block = "\n".join([f"- {t}" for t in alt_titles])

    details_text = f"""====================================================================
🔥 RECOMMENDED TITLE (BEST FOR HIGH CTR):
{rec_title}

💡 ALTERNATIVE VIRAL TITLES:
{alt_block}
====================================================================

📝 YOUTUBE DESCRIPTION (COPY & PASTE EVERYTHING BELOW):
--------------------------------------------------------------------
{desc_intro}

Welcome to MedPulse 5 — your daily source for the 5 most important medical breakthroughs, health science updates, and longevity discoveries explained in simple English.

⏱️ VIDEO CHAPTERS & TIMESTAMPS:
{ts_block}

🔬 SCIENTIFIC SOURCES & ORIGINAL RESEARCH LINKS:
{sources_block}

⚠️ MEDICAL DISCLAIMER:
The content provided on MedPulse 5 is for informational and educational purposes only and is not intended as a substitute for professional medical advice, diagnosis, or treatment. Always seek the advice of your physician or other qualified health provider with any questions you may have regarding a medical condition.

#MedicalBreakthroughs #HealthNews #Longevity #MedicalScience #MedPulse5
--------------------------------------------------------------------

🏷️ YOUTUBE TAGS (COMMA SEPARATED):
{", ".join(all_tags)}
"""

    with open("youtube_details.txt", "w", encoding="utf-8") as f:
        f.write(details_text)

    print("🎉 SUCCESS! final_video.mp4 and youtube_details.txt are ready!")

if __name__ == "__main__":
    main()
