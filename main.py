import sys
import subprocess

# Auto-install required latest packages including Arabic text shaping
subprocess.run([
    sys.executable, "-m", "pip", "install", "-q", "--upgrade",
    "edge-tts", "google-generativeai", "arabic-reshaper", "python-bidi"
], check=False)

import os
import re
import json
import time
import random
import asyncio
import urllib.parse
import feedparser
import requests
import edge_tts
import arabic_reshaper
from bidi.algorithm import get_display
import google.generativeai as genai
from PIL import Image, ImageDraw, ImageFont

# ==================== 1. CONFIGURATION ====================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")

VOICE_EN = "en-US-ChristopherNeural"  # Constant American Documentary Host
VOICE_AR = "ar-SA-HamedNeural"        # Constant Arabic Documentary Host
USED_NEWS_FILE = "used_news.txt"

RSS_FEEDS = [
    ("ScienceDaily", "https://www.sciencedaily.com/rss/health_medicine.xml"),
    ("MedicalXpress", "https://medicalxpress.com/rss-feed/"),
    ("ScienceDaily Brain", "https://www.sciencedaily.com/rss/mind_brain.xml"),
    ("EurekAlert Medicine", "https://www.eurekalert.org/rss/medicine_health.xml"),
    ("News-Medical", "https://www.news-medical.net/tag/feed/Medical-Research.aspx")
]

FALLBACK_VIDEO_QUERIES = [
    "scientist microscope laboratory", "medical research lab",
    "doctor talking patient hospital", "dna genetics animation",
    "medicine pills manufacturing", "brain scan hospital",
    "surgeon operating room", "heart monitor hospital",
    "blood test tube laboratory", "pharmacist medicine",
    "doctor computer hospital", "clinical trial scientist"
]

os.makedirs("temp", exist_ok=True)
used_pexels_ids = set()

# ==================== 2. SMART AI MODEL DETECTOR ====================
genai.configure(api_key=GEMINI_API_KEY)
ACTIVE_GEMINI_MODEL = None

def get_available_models():
    preferred = [
        "gemini-3.0-flash",
        "gemini-3-flash-preview",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash"
    ]
    discovered = []
    try:
        for m in genai.list_models():
            methods = getattr(m, "supported_generation_methods", [])
            if "generateContent" in methods:
                name = m.name.replace("models/", "")
                low = name.lower()
                if "gemini" in low and not any(x in low for x in ["vision", "embedding", "tts", "image", "audio"]):
                    discovered.append(name)
    except Exception as e:
        print(f"Model discovery note: {e}")

    flash_first = [m for m in discovered if "flash" in m.lower()] + [m for m in discovered if "flash" not in m.lower()]
    combined = []
    for m in preferred + flash_first:
        if m not in combined:
            combined.append(m)
    return combined

AVAILABLE_MODELS = get_available_models()

def ask_gemini(prompt):
    global ACTIVE_GEMINI_MODEL
    models_to_try = [ACTIVE_GEMINI_MODEL] + [m for m in AVAILABLE_MODELS if m != ACTIVE_GEMINI_MODEL] if ACTIVE_GEMINI_MODEL else AVAILABLE_MODELS

    for model_name in models_to_try:
        for attempt in range(3):
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(prompt)
                if response and response.text:
                    ACTIVE_GEMINI_MODEL = model_name
                    return response.text.strip()
            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "quota" in err_str.lower() or "rate" in err_str.lower():
                    time.sleep(20)
                else:
                    break
    raise Exception("Failed to get response from Gemini models.")

def clean_json_response(text):
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        return json.loads(text[start:end+1])
    raise ValueError("Invalid JSON format from AI")

# ==================== 3. FETCH FRESH MEDICAL NEWS WITH SOURCES ====================
def load_used_titles():
    if os.path.exists(USED_NEWS_FILE):
        with open(USED_NEWS_FILE, "r", encoding="utf-8") as f:
            return set(line.strip().lower() for line in f if line.strip())
    return set()

def save_used_titles(new_titles):
    with open(USED_NEWS_FILE, "a", encoding="utf-8") as f:
        for t in new_titles:
            f.write(t.strip() + "\n")

def fetch_top_medical_news(count=5):
    print("Fetching latest medical breakthroughs with sources...")
    used_titles = load_used_titles()
    articles = []
    seen_now = set()

    for source_name, url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:15]:
                title = entry.get("title", "").strip()
                summary = re.sub(r"<[^>]+>", "", entry.get("summary", "")).strip()
                link = entry.get("link", "").strip()
                t_lower = title.lower()
                if title and len(summary) > 50 and t_lower not in used_titles and t_lower not in seen_now:
                    seen_now.add(t_lower)
                    articles.append({
                        "title": title,
                        "summary": summary[:900],
                        "source": source_name,
                        "link": link
                    })
        except Exception as e:
            print(f"RSS error ({url}): {e}")

    if len(articles) < count:
        for source_name, url in RSS_FEEDS:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
                title = entry.get("title", "").strip()
                summary = re.sub(r"<[^>]+>", "", entry.get("summary", "")).strip()
                link = entry.get("link", "").strip()
                if title and title.lower() not in seen_now:
                    seen_now.add(title.lower())
                    articles.append({
                        "title": title,
                        "summary": summary[:900],
                        "source": source_name,
                        "link": link
                    })

    selected = articles[:count]
    save_used_titles([a["title"] for a in selected])
    return selected

# ==================== 4. BILINGUAL SCRIPT & DYNAMIC HOOK GENERATOR ====================
def build_bilingual_script(articles):
    print("Building English & Arabic scripts with unique daily Hook & Source citations...")
    segments = []
    titles_list = "\n".join([f"{i+1}. {a['title']} (Source: {a['source']})" for i, a in enumerate(articles)])

    # A. Dynamic Cold-Open Hook + Intro (Unique Every Video!)
    intro_prompt = f"""
    You are an elite medical documentary producer creating BOTH an English version (for US/Europe) and a professional Modern Standard Arabic version (الفصحى الإخبارية الوثائقية) of today's medical episode covering:
    {titles_list}

    Create a UNIQUE, dramatic "Cold Open Hook" + Introduction (around 140 words in English, and equivalent 130 words in eloquent Arabic):
    - Start immediately with a shocking scientific question or dramatic hook about Story #1 (DO NOT start with "Welcome back" in the first sentence—hook the viewer first, then welcome them to the briefing!).
    - Also provide viral YouTube titles, descriptions, and tags in both English and Arabic.

    Return ONLY valid JSON in this exact structure:
    {{
      "en_title": "Viral English YouTube Title under 90 chars",
      "en_description": "Detailed English SEO description...",
      "en_tags": ["medical news", "health breakthrough", "medicine"],
      "ar_title": "عنوان يوتيوب عربي جذاب ومثير للاهتمام",
      "ar_description": "وصف تفصيلي للفيديو باللغة العربية...",
      "ar_tags": ["أخبار الطب", "اكتشافات طبية", "الصحة"],
      "en_narration": "140 words English spoken hook and intro only...",
      "ar_narration": "130 كلمة تعليق صوتي عربي فصيح ومشوق للمقدمة...",
      "visual_queries": ["doctor medical technology", "scientist laboratory microscope", "hospital health care"]
    }}
    """
    meta_data = clean_json_response(ask_gemini(intro_prompt))
    segments.append({
        "is_transition_start": True,
        "source_badge_en": "DAILY MEDICAL BRIEFING",
        "source_badge_ar": "النشرة الطبية اليومية",
        "headline_en": "TODAY'S TOP 5 MEDICAL BREAKTHROUGHS",
        "headline_ar": "أهم ٥ اكتشافات وأبحاث طبية عالمية اليوم",
        "narration_en": meta_data["en_narration"],
        "narration_ar": meta_data["ar_narration"],
        "queries": meta_data.get("visual_queries", ["medical technology", "scientist laboratory", "hospital doctor"])
    })
    time.sleep(5)

    # B. 5 Stories x 4 Synchronized Scenes (Both English & Arabic)
    for idx, article in enumerate(articles):
        print(f"Writing Bilingual Synchronized Scenes for Story {idx+1}/5...")
        story_prompt = f"""
        You are an elite medical documentary writer in English and Modern Standard Arabic (الفصحى الوثائقية).
        Write an in-depth report on this medical breakthrough:
        Title: {article['title']}
        Source: {article['source']}
        Details: {article['summary']}

        Break this story into EXACTLY 4 chronological scenes (~95 words per scene in English, and ~85 words per scene in eloquent Arabic):
        - Scene 1: Dramatic Transition & The Discovery (Explicitly mention the source "{article['source']}" or research team, and explain what was discovered).
        - Scene 2: Mechanism Inside the Body (How this drug, therapy, or biological mechanism works).
        - Scene 3: Clinical Evidence & Trial Results (What the study proved and who benefits).
        - Scene 4: Future Outlook & Medical Takeaway (When it will help patients and key health takeaway).

        VISUAL MATCHING RULE:
        For EACH scene, provide 3 concrete English stock-video search queries (2-3 simple words each, e.g., "brain scan hospital", "pills medicine", "scientist microscope", "doctor patient", "heart monitor") matching the start, middle, and end of that scene.

        Return ONLY valid JSON in this exact format:
        {{
          "headline_en": "SHORT ENGLISH HEADLINE UNDER 58 CHARS",
          "headline_ar": "عنوان عربي مختصر للخبر الطبي",
          "scenes": [
            {{
              "narration_en": "95 words spoken English text...",
              "narration_ar": "85 كلمة تعليق صوتي عربي فصيح...",
              "visual_queries": ["query 1", "query 2", "query 3"]
            }},
            {{
              "narration_en": "95 words spoken English text...",
              "narration_ar": "85 كلمة تعليق صوتي عربي فصيح...",
              "visual_queries": ["query 1", "query 2", "query 3"]
            }},
            {{
              "narration_en": "95 words spoken English text...",
              "narration_ar": "85 كلمة تعليق صوتي عربي فصيح...",
              "visual_queries": ["query 1", "query 2", "query 3"]
            }},
            {{
              "narration_en": "95 words spoken English text...",
              "narration_ar": "85 كلمة تعليق صوتي عربي فصيح...",
              "visual_queries": ["query 1", "query 2", "query 3"]
            }}
          ]
        }}
        """
        story_data = clean_json_response(ask_gemini(story_prompt))
        h_en = story_data.get("headline_en", article["title"][:58]).upper()
        h_ar = story_data.get("headline_ar", "تقرير طبي جديد")

        for s_idx, scene in enumerate(story_data["scenes"]):
            segments.append({
                "is_transition_start": (s_idx == 0),  # Triggers smooth Story Transition effect on Scene 1
                "source_badge_en": f"REPORT #{idx+1} OF 5  |  SOURCE: {article['source'].upper()}",
                "source_badge_ar": f"التقرير {idx+1} من 5  |  المصدر: {article['source']}",
                "headline_en": h_en,
                "headline_ar": h_ar,
                "narration_en": scene["narration_en"],
                "narration_ar": scene["narration_ar"],
                "queries": scene.get("visual_queries", ["medical research", "doctor patient", "laboratory"])
            })
        time.sleep(5)

    # C. Outro (Bilingual)
    outro_prompt = """
    Write a warm, authoritative 95-word conclusion for a medical documentary in BOTH English and Modern Standard Arabic.
    Remind viewers that all scientific sources are linked in the description and that this content is for educational purposes, and invite them to subscribe.
    Return ONLY valid JSON:
    {
      "en_outro": "95 words spoken English conclusion...",
      "ar_outro": "85 كلمة خاتمة عربية فصيحة ومشوقة...",
      "visual_queries": ["doctor talking patient", "modern hospital building", "healthy active lifestyle"]
    }
    """
    outro_data = clean_json_response(ask_gemini(outro_prompt))
    segments.append({
        "is_transition_start": True,
        "source_badge_en": "VERIFIED MEDICAL SOURCES IN DESCRIPTION",
        "source_badge_ar": "المصادر العلمية موثقة في صندوق الوصف",
        "headline_en": "SUBSCRIBE FOR DAILY MEDICAL BREAKTHROUGHS",
        "headline_ar": "اشترك في القناة لمتابعة أحدث الاكتشافات الطبية يومياً",
        "narration_en": outro_data["en_outro"],
        "narration_ar": outro_data["ar_outro"],
        "queries": outro_data.get("visual_queries", ["doctor smiling", "healthy lifestyle", "hospital"])
    })

    return meta_data, segments

# ==================== 5. VOICEOVER ENGINE & DURATION PROBE ====================
async def _generate_tts(text, voice, output_file):
    communicate = edge_tts.Communicate(text, voice, rate="-3%", pitch="-2Hz")
    await communicate.save(output_file)

def create_voiceover(text, voice, output_file):
    clean_text = re.sub(r"[*#_~`]", "", text).strip()
    for attempt in range(3):
        try:
            asyncio.run(_generate_tts(clean_text, voice, output_file))
            if os.path.exists(output_file) and os.path.getsize(output_file) > 1000:
                return
        except Exception as e:
            print(f"TTS retry {attempt+1}: {e}")
            time.sleep(3)
    raise Exception("Failed to generate voiceover audio.")

def get_media_duration(file_path):
    res = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", file_path
    ], capture_output=True, text=True)
    try:
        return float(res.stdout.strip())
    except Exception:
        return 10.0

# ==================== 6. 100% MOVING VIDEO DOWNLOADER (NO STATIC PHOTOS!) ====================
def score_video_relevance(video_obj, query):
    slug = video_obj.get("url", "").lower()
    keywords = [w.lower() for w in re.findall(r"\w+", query) if len(w) > 2]
    score = sum(3 for kw in keywords if kw in slug)
    dur = video_obj.get("duration", 0)
    if 7 <= dur <= 30:
        score += 2
    return score

def download_strict_video(query, dest_path):
    """Strictly downloads moving HD MP4 videos only (never static photos) to prevent any screen freeze."""
    headers = {"Authorization": PEXELS_API_KEY}
    # Try exact query first, then simplified 2-word query, then medical fallback
    words = query.split()
    attempts = [query]
    if len(words) > 2:
        attempts.append(" ".join(words[:2]))
    attempts.extend(random.sample(FALLBACK_VIDEO_QUERIES, 4))

    for q in attempts:
        url = f"https://api.pexels.com/videos/search?query={urllib.parse.quote(q)}&orientation=landscape&size=medium&per_page=15"
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code == 200:
                videos = [v for v in r.json().get("videos", []) if v.get("id") not in used_pexels_ids]
                videos.sort(key=lambda v: score_video_relevance(v, q), reverse=True)

                for v in videos:
                    vid_id = v.get("id")
                    for vf in v.get("video_files", []):
                        w = vf.get("width", 0)
                        if 1280 <= w <= 1920 and vf.get("link"):
                            vid_resp = requests.get(vf["link"], timeout=30)
                            if vid_resp.status_code == 200 and len(vid_resp.content) > 50000:
                                with open(dest_path, "wb") as f:
                                    f.write(vid_resp.content)
                                used_pexels_ids.add(vid_id)
                                return True
        except Exception as e:
            print(f"Video search note for '{q}': {e}")
    return False

# ==================== 7. BROADCAST GRAPHICS (ENGLISH & ARABIC) ====================
def shape_arabic_text(text):
    try:
        reshaped = arabic_reshaper.reshape(text)
        return get_display(reshaped)
    except Exception:
        return text

def create_broadcast_overlay(headline, source_badge, output_png, lang="en", is_new_report=False):
    img = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    accent_color = (220, 30, 45, 255) if is_new_report else (0, 190, 235, 255)

    # Top-right Channel Badge
    draw.rectangle([980, 32, 1240, 72], fill=(180, 18, 28, 235))
    # Lower-Third Broadcast Banner
    draw.rectangle([0, 600, 1280, 686], fill=(8, 20, 42, 238))
    draw.rectangle([0, 593, 1280, 600], fill=accent_color)
    draw.rectangle([40, 560, 560, 595], fill=(0, 125, 175, 255))

    try:
        font_badge = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 17)
        font_main = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 25)
    except Exception:
        font_badge = ImageFont.load_default()
        font_main = ImageFont.load_default()

    if lang == "ar":
        top_txt = shape_arabic_text("النشرة الطبية العالمية")
        src_txt = shape_arabic_text(source_badge[:55])
        main_txt = shape_arabic_text(headline[:68])
        draw.text((1005, 41), top_txt, fill=(255, 255, 255, 255), font=font_badge)
        draw.text((55, 568), src_txt, fill=(255, 255, 255, 255), font=font_badge)
        draw.text((55, 626), main_txt, fill=(255, 255, 255, 255), font=font_main)
    else:
        draw.text((1005, 42), "MEDICAL REPORT HD", fill=(255, 255, 255, 255), font=font_badge)
        draw.text((55, 569), source_badge[:55], fill=(255, 255, 255, 255), font=font_badge)
        draw.text((45, 628), headline[:68], fill=(255, 255, 255, 255), font=font_main)

    img.save(output_png)

# ==================== 8. FFMPEG ANTI-FREEZE STUDIO RENDERER ====================
def prepare_scene_raw_videos(idx, queries):
    """Downloads 3 moving videos once per scene so both English and Arabic versions reuse them."""
    scene_queries = list(queries)
    while len(scene_queries) < 3:
        scene_queries.append(random.choice(FALLBACK_VIDEO_QUERIES))

    raw_files = []
    for q_idx, q in enumerate(scene_queries[:3]):
        raw_path = f"temp/raw_{idx}_{q_idx}.mp4"
        if not os.path.exists(raw_path):
            download_strict_video(q, raw_path)
        if os.path.exists(raw_path):
            raw_files.append(raw_path)
    return raw_files

def render_language_segment(idx, segment, raw_files, lang="en"):
    audio_path = f"temp/audio_{lang}_{idx}.mp3"
    overlay_path = f"temp/overlay_{lang}_{idx}.png"
    out_segment = f"temp/seg_{lang}_{idx:03d}.mp4"

    narration = segment["narration_en"] if lang == "en" else segment["narration_ar"]
    voice = VOICE_EN if lang == "en" else VOICE_AR
    headline = segment["headline_en"] if lang == "en" else segment["headline_ar"]
    badge = segment["source_badge_en"] if lang == "en" else segment["source_badge_ar"]
    is_trans = segment.get("is_transition_start", False)

    create_voiceover(narration, voice, audio_path)
    audio_dur = get_media_duration(audio_path)
    target_dur = audio_dur + 0.45

    create_broadcast_overlay(headline, badge, overlay_path, lang=lang, is_new_report=is_trans)

    slot_dur = target_dur / max(len(raw_files), 1)
    slot_clips = []

    for r_idx, r_path in enumerate(raw_files):
        slot_out = f"temp/slot_{lang}_{idx}_{r_idx}.mp4"
        # Native FFmpeg infinite loop + exact cut: NEVER freezes frames!
        subprocess.run([
            "ffmpeg", "-y", "-stream_loop", "-1", "-i", r_path,
            "-t", f"{slot_dur:.2f}",
            "-vf", "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,setsar=1,fps=24,format=yuv420p",
            "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
            slot_out
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        slot_clips.append(slot_out)

    concat_slots_txt = f"temp/slots_{lang}_{idx}.txt"
    with open(concat_slots_txt, "w") as f:
        for sc in slot_clips:
            f.write(f"file '{os.path.abspath(sc)}'\n")

    bg_joined = f"temp/bg_{lang}_{idx}.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_slots_txt, "-c", "copy", bg_joined
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Apply smooth cinematic fade-in on new story transitions & fade-out at segment end
    fade_in_dur = 0.75 if is_trans else 0.25
    fade_out_start = max(0.1, target_dur - 0.35)
    filter_chain = (
        f"[0:v][1:v]overlay=0:0,"
        f"fade=t=in:st=0:d={fade_in_dur},"
        f"fade=t=out:st={fade_out_start:.2f}:d=0.35[v]"
    )

    subprocess.run([
        "ffmpeg", "-y",
        "-i", bg_joined,
        "-i", overlay_path,
        "-i", audio_path,
        "-filter_complex", filter_chain,
        "-map", "[v]", "-map", "2:a",
        "-t", f"{target_dur:.2f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "27",
        "-maxrate", "950k", "-bufsize", "1900k", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "96k", "-ar", "44100", "-ac", "2",
        out_segment
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    return out_segment, target_dur

# ==================== 9. SAVE BILINGUAL YOUTUBE DETAILS WITH SOURCES ====================
def format_time(seconds):
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"

def save_bilingual_package(meta_data, en_chapters, ar_chapters, articles):
    en_tags = ", ".join(meta_data.get("en_tags", ["medical news", "health"]))
    ar_tags = ", ".join(meta_data.get("ar_tags", ["أخبار الطب", "صحة"]))
    en_ch_str = "\n".join(en_chapters)
    ar_ch_str = "\n".join(ar_chapters)
    sources_list = "\n".join([f"• Story #{i+1} ({a['source']}): {a['title']}\n  {a['link']}" for i, a in enumerate(articles)])

    content = f"""====================================================================
🇺🇸🇬🇧 1. ENGLISH YOUTUBE PACKAGE (Download: english_video.mp4)
====================================================================

📌 ENGLISH TITLE:
{meta_data.get('en_title', 'Latest Medical Breakthroughs & Health News')}

📝 ENGLISH DESCRIPTION:
{meta_data.get('en_description', '')}

⏱️ CHAPTERS:
{en_ch_str}

🔬 SCIENTIFIC SOURCES & REFERENCES CITED IN THIS EPISODE:
{sources_list}

⚠️ Medical Disclaimer:
This video is for educational and informational purposes only and does not constitute professional medical advice.

🏷️ ENGLISH TAGS:
{en_tags}


====================================================================
🇸🇦🇪🇬 2. الحزمة العربية لليوتيوب (حمّل ملف: arabic_video.mp4)
====================================================================

📌 العنوان باللغة العربية:
{meta_data.get('ar_title', 'أحدث الاكتشافات والأبحاث الطبية العالمية اليوم')}

📝 الوصف باللغة العربية:
{meta_data.get('ar_description', '')}

⏱️ فصول الفيديو:
{ar_ch_str}

🔬 المصادر والمراجع العلمية المعتمدة في هذه الحلقة:
{sources_list}

⚠️ إخلاء مسؤولية طبي:
المعلومات الواردة في هذا الفيديو هي لأغراض تعليمية وإعلامية فقط ولا تغني عن استشارة الطبيب المختص.

🏷️ الكلمات المفتاحية (Tags):
{ar_tags}
====================================================================
"""
    with open("youtube_details.txt", "w", encoding="utf-8") as f:
        f.write(content)

# ==================== MAIN EXECUTION ====================
if __name__ == "__main__":
    articles = fetch_top_medical_news(5)
    meta_data, segments = build_bilingual_script(articles)

    en_files, ar_files = [], []
    en_time, ar_time = 0.0, 0.0
    en_chapters = ["00:00 Cold Open & Medical Briefing Intro"]
    ar_chapters = ["00:00 مقدمة تشويقية وعناوين النشرة الطبية"]

    for i, seg in enumerate(segments):
        if i in [1, 5, 9, 13, 17]:
            s_num = ((i - 1) // 4) + 1
            art = articles[s_num - 1]
            en_chapters.append(f"{format_time(en_time)} Report #{s_num}: {art['title'][:58]} ({art['source']})")
            ar_chapters.append(f"{format_time(ar_time)} التقرير #{s_num}: {seg['headline_ar']} ({art['source']})")

        print(f"Processing Scene {i+1}/{len(segments)} (Downloading HD Moving Visuals + Rendering EN & AR)...")
        raw_vids = prepare_scene_raw_videos(i, seg["queries"])

        en_seg, en_dur = render_language_segment(i, seg, raw_vids, lang="en")
        en_files.append(en_seg)
        en_time += en_dur

        ar_seg, ar_dur = render_language_segment(i, seg, raw_vids, lang="ar")
        ar_files.append(ar_seg)
        ar_time += ar_dur

    # Merge English Video
    with open("temp/concat_en.txt", "w") as f:
        for sf in en_files:
            f.write(f"file '{os.path.abspath(sf)}'\n")
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", "temp/concat_en.txt", "-c", "copy", "-movflags", "+faststart", "english_video.mp4"
    ], check=True)

    # Merge Arabic Video
    with open("temp/concat_ar.txt", "w") as f:
        for sf in ar_files:
            f.write(f"file '{os.path.abspath(sf)}'\n")
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", "temp/concat_ar.txt", "-c", "copy", "-movflags", "+faststart", "arabic_video.mp4"
    ], check=True)

    save_bilingual_package(meta_data, en_chapters, ar_chapters, articles)
    print(f"SUCCESS! Both compressed HD videos ready: english_video.mp4 ({format_time(en_time)}) & arabic_video.mp4 ({format_time(ar_time)})")
