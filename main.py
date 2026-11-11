import os
import re
import json
import time
import shutil
import asyncio
import calendar
import subprocess
import feedparser
import requests
import edge_tts
import google.generativeai as genai

# ==============================================================================
# 1. CONFIGURATION & API KEYS
# ==============================================================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "").strip()

if not GEMINI_API_KEY:
    raise ValueError("❌ GEMINI_API_KEY is missing! Check GitHub Secrets.")
if not PEXELS_API_KEY:
    raise ValueError("❌ PEXELS_API_KEY is missing! Check GitHub Secrets.")

genai.configure(api_key=GEMINI_API_KEY, transport="rest")

USED_NEWS_FILE = "used_news.txt"
USED_VIDEOS_FILE = "used_videos.txt"
WORK_DIR = "build_workspace"
os.makedirs(WORK_DIR, exist_ok=True)

VOICE_EN = "en-US-ChristopherNeural"

RSS_FEEDS = [
    ("MedicalXpress", "https://medicalxpress.com/rss-feed/"),
    ("News-Medical", "https://www.news-medical.net/tag/feed/Medical-Research.aspx"),
    ("EurekAlert Medicine", "https://www.eurekalert.org/rss/medicine_health.xml"),
    ("ScienceDaily Health", "https://www.sciencedaily.com/rss/health_medicine.xml"),
    ("ScienceDaily Brain", "https://www.sciencedaily.com/rss/mind_brain.xml"),
    ("ScienceDaily Longevity", "https://www.sciencedaily.com/rss/living_well.xml"),
]

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

# Universal FFmpeg 4.x - 8.x encoding flags (No deprecated -vsync flag)
VIDEO_ENC_FLAGS = [
    "-c:v", "libx264",
    "-preset", "superfast",
    "-crf", "27",
    "-maxrate", "950k",
    "-bufsize", "1900k",
    "-pix_fmt", "yuv420p",
    "-r", "24",
]


# ==============================================================================
# 2. PERSISTENT MEMORY (NO REPEATED NEWS OR VIDEOS)
# ==============================================================================
def load_set(filepath):
    if not os.path.exists(filepath):
        return set()
    with open(filepath, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def append_to_file(filepath, items):
    with open(filepath, "a", encoding="utf-8") as f:
        for item in items:
            f.write(f"{item}\n")


def clean_html(raw_html):
    cleanr = re.compile("<.*?>")
    text = re.sub(cleanr, "", raw_html or "")
    return re.sub(r"\s+", " ", text).strip()


# ==============================================================================
# 3. FETCH LATEST RSS CANDIDATES FOR VIRAL CURATION
# ==============================================================================
def fetch_candidate_medical_news(candidate_limit=28):
    print("📡 Fetching global medical & research feeds (Real-Time)...")
    used_titles = load_set(USED_NEWS_FILE)
    candidates = []
    seen_now = set()

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    for source_name, url in RSS_FEEDS:
        try:
            resp = requests.get(url, headers=headers, timeout=12)
            if resp.status_code != 200:
                continue
            feed = feedparser.parse(resp.content)
            for entry in feed.entries[:12]:
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                summary = clean_html(entry.get("summary", entry.get("description", "")))

                if not title or title in used_titles or title in seen_now:
                    continue

                pub_struct = entry.get("published_parsed") or entry.get("updated_parsed")
                timestamp = calendar.timegm(pub_struct) if pub_struct else time.time()
                pub_date_str = time.strftime("%B %d, %Y", time.gmtime(timestamp))

                seen_now.add(title)
                candidates.append({
                    "source": source_name,
                    "title": title,
                    "link": link,
                    "summary": summary[:650],
                    "pub_date": pub_date_str,
                    "timestamp": timestamp
                })
        except Exception as e:
            print(f"⚠️ Warning fetching {source_name}: {e}")

    candidates.sort(key=lambda x: x["timestamp"], reverse=True)
    top_pool = candidates[:candidate_limit]

    if len(top_pool) < 5:
        raise RuntimeError("❌ Not enough new medical articles found.")

    print(f"✅ Collected {len(top_pool)} fresh candidate breakthroughs for AI viral selection.")
    return top_pool


# ==============================================================================
# 4. GEMINI AI: VIRAL CURATION + HIGH-RETENTION SCRIPT + SCHEMA VALIDATION
# ==============================================================================
def get_working_gemini_model():
    preferred = [
        "gemini-3.0-flash",
        "gemini-3-flash-preview",
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-1.5-flash",
    ]
    try:
        available = [
            m.name.replace("models/", "")
            for m in genai.list_models(request_options={"timeout": 20})
            if "generateContent" in getattr(m, "supported_generation_methods", [])
        ]
        for p in preferred:
            if p in available:
                print(f"🤖 Selected Gemini Model: {p}")
                return genai.GenerativeModel(p)
        for a in available:
            if "gemini" in a.lower():
                print(f"🤖 Selected Available Gemini Model: {a}")
                return genai.GenerativeModel(a)
    except Exception as e:
        print(f"⚠️ list_models notice: {e}")

    return genai.GenerativeModel("gemini-3-flash-preview")


def extract_json_safely(raw_text):
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]
    return json.loads(text)


def validate_and_normalize_script(data):
    if not isinstance(data, dict):
        raise ValueError("Root JSON is not an object.")

    intro = data.get("intro", {})
    intro_narr = intro.get("narration_en") or intro.get("narration") or intro.get("text")
    if not intro_narr or len(str(intro_narr).strip()) < 20:
        raise ValueError("Intro narration is missing.")
    intro["narration_en"] = str(intro_narr).strip()
    data["intro"] = intro

    outro = data.get("outro", {})
    outro_narr = outro.get("narration_en") or outro.get("narration") or outro.get("text")
    if not outro_narr or len(str(outro_narr).strip()) < 20:
        raise ValueError("Outro narration is missing.")
    outro["narration_en"] = str(outro_narr).strip()
    data["outro"] = outro

    stories = data.get("stories", [])
    if not isinstance(stories, list) or len(stories) != 5:
        raise ValueError(f"Expected 5 stories, got {len(stories) if isinstance(stories, list) else 0}.")

    for idx, st in enumerate(stories, 1):
        for act_key in ["act_1", "act_2", "act_3", "act_4"]:
            act_obj = st.get(act_key)
            if not isinstance(act_obj, dict):
                raise ValueError(f"Story #{idx} missing {act_key} object.")
            narr = (
                act_obj.get("narration_en")
                or act_obj.get("narration")
                or act_obj.get("text")
                or act_obj.get("script")
            )
            if not narr or len(str(narr).strip()) < 15:
                raise ValueError(f"Story #{idx} {act_key} missing narration_en.")
            act_obj["narration_en"] = str(narr).strip()
            if not act_obj.get("headline_en"):
                act_obj["headline_en"] = act_obj.get("headline") or f"MEDICAL BREAKTHROUGH #{idx}"
            if not act_obj.get("search_queries") or not isinstance(act_obj.get("search_queries"), list):
                act_obj["search_queries"] = ["medical research laboratory", "doctor hospital", "dna cells"]

    return data


def generate_script_with_gemini(candidates):
    print("🧠 Gemini AI is selecting the 5 most fascinating stories & writing the script...")
    model = get_working_gemini_model()

    news_block = ""
    for i, item in enumerate(candidates, 1):
        news_block += (
            f"\nCANDIDATE #{i}:\n"
            f"- Source: {item['source']} ({item['pub_date']})\n"
            f"- Title: {item['title']}\n"
            f"- Summary: {item['summary']}\n"
            f"- Link: {item['link']}\n"
        )

    prompt = f"""
You are the Executive Producer and Lead Storyteller for a viral 5-Million-Subscriber Medical & Longevity YouTube Channel (inspired by Cleo Abram, Veritasium, and Huberman Lab).

Below is a pool of {len(candidates)} real-time medical research candidates published in the last 24-48 hours:
{news_block}

STEP 1 — VIRAL STORY SELECTION:
Out of the {len(candidates)} candidates above, choose the 5 MOST FASCINATING, SHOCKING, and HUMAN-RELEVANT breakthroughs.
Prioritize breakthroughs about:
- Everyday habits, sleep, metabolism, brain aging, longevity, cancer, heart health, gut microbiome, or game-changing drugs.
- Stories that make an ordinary viewer immediately think: "Wait—this affects MY body and MY family!"
Return their exact candidate numbers in `selected_candidate_indices` (1-based).

STEP 2 — HIGH-RETENTION CONVERSATIONAL STORYTELLING:
Write an unforgettable 13 to 15 minute episode (~2,000 to 2,200 spoken words total).
CRITICAL STYLE RULES:
1. NEVER sound like a dry news anchor! Speak directly to one person ("You", "Imagine waking up...", "Right now inside your cells...").
2. UNIQUE COLD-OPEN HOOK: Start `intro.narration_en` with a gripping, surprising 2-sentence mystery or question inspired by the #1 story BEFORE welcoming viewers to the episode. Never use the same generic opening twice!
3. EVERYDAY ANALOGIES: Whenever you explain a biological mechanism, use a vivid everyday analogy (e.g., comparing immune cells to security guards with updated mugshots, or mitochondria to tiny rechargeable batteries).
4. SCIENTIFIC CREDIBILITY: Naturally weave the real source name and date (`According to researchers at... published via MedicalXpress...`) into the story.
5. CLIFFHANGER BRIDGES: End `act_4` of each story with a 1-sentence teaser that makes the viewer curious about the NEXT story.
6. THUMBNAIL TEXT: Create a super punchy 2-line YouTube thumbnail hook:
   - `thumbnail_line1`: 2 to 3 words in ALL CAPS (White text, e.g., "DOCTORS SHOCKED" or "BRAIN RESET")
   - `thumbnail_line2`: 2 to 3 words in ALL CAPS (Yellow text, e.g., "NEW SLEEP CURE!" or "CELLS REVERSED!")
   - `thumbnail_search_query`: 2-3 visual keywords for a striking medical background (e.g., "glowing brain neuron doctor").

OUTPUT STRICTLY VALID JSON matching this exact structure (every act MUST have "narration_en", "headline_en", and "search_queries"):
{{
  "selected_candidate_indices": [1, 3, 5, 8, 12],
  "youtube_title": "Viral, curiosity-driven YouTube title (under 90 chars)",
  "youtube_description_intro": "Engaging 3-sentence hook for the YouTube description box.",
  "youtube_tags": ["medical breakthroughs", "health news", "longevity", "science news", "medical research"],
  "thumbnail_line1": "BRAIN AGING",
  "thumbnail_line2": "REVERSED?!",
  "thumbnail_search_query": "glowing brain neurology scan",
  "intro": {{
    "narration_en": "140-160 words. Start IMMEDIATELY with a shocking cold-open hook/question, then welcome the viewer and tease the 5 breakthroughs.",
    "headline_en": "5 BREAKTHROUGHS CHANGING HUMAN HEALTH",
    "subheadline_en": "Verified Clinical & Research Report",
    "search_queries": ["cinematic hospital doctor", "dna double helix glowing", "medical laboratory scientist"]
  }},
  "stories": [
    {{
      "story_number": 1,
      "candidate_index": 1,
      "chapter_title_en": "Short compelling chapter title (max 52 chars)",
      "source_citation_en": "Source Name • Date",
      "act_1": {{
        "narration_en": "90-105 words. Hook the viewer with a relatable human problem, then reveal the new discovery and cite the institution/source.",
        "headline_en": "UPPERCASE HEADLINE (MAX 48 CHARS)",
        "search_queries": ["specific visual query 1", "specific visual query 2", "specific visual query 3"]
      }},
      "act_2": {{
        "narration_en": "90-105 words. Explain HOW it works inside the body using a brilliant, simple everyday analogy.",
        "headline_en": "HOW IT WORKS INSIDE YOUR CELLS",
        "search_queries": ["microscope cells dividing", "bloodstream red blood cells", "brain neurons firing"]
      }},
      "act_3": {{
        "narration_en": "90-105 words. Share the concrete proof from the study, surprising numbers, and why scientists were stunned.",
        "headline_en": "SURPRISING CLINICAL STUDY RESULTS",
        "search_queries": ["scientist analyzing data", "medical scanner mri", "laboratory test tubes"]
      }},
      "act_4": {{
        "narration_en": "90-105 words. What this means for YOU and your family, practical takeaway, and a 1-sentence cliffhanger for the next story.",
        "headline_en": "WHAT THIS MEANS FOR YOUR FUTURE",
        "search_queries": ["healthy active senior", "doctor consulting patient", "happy family outdoors"]
      }}
    }}
  ],
  "outro": {{
    "narration_en": "90-110 words. Inspiring takeaway, question asking viewers which of the 5 discoveries amazed them most in the comments, subscribe reminder, and educational medical disclaimer.",
    "headline_en": "THE FUTURE OF MEDICINE IS HERE",
    "subheadline_en": "Subscribe for Daily Evidence-Based Breakthroughs",
    "search_queries": ["futuristic medicine technology", "doctor smiling camera", "sunrise healthy lifestyle"]
  }}
}}

IMPORTANT: The `stories` array MUST contain all 5 selected stories (story_number 1 through 5), and every act_1, act_2, act_3, act_4 MUST contain the key `narration_en`.
"""

    last_err = None
    for attempt in range(4):
        try:
            response = model.generate_content(
                prompt,
                generation_config={"temperature": 0.65},
                request_options={"timeout": 65}
            )
            raw_data = extract_json_safely(response.text)
            data = validate_and_normalize_script(raw_data)
            print("✅ High-retention script & viral selection generated and verified!")
            return data
        except Exception as e:
            last_err = e
            print(f"⚠️ Gemini attempt {attempt + 1} notice: {e}. Retrying in 4s...")
            time.sleep(4)

    raise RuntimeError(f"❌ Failed to generate valid script from Gemini: {last_err}")


# ==============================================================================
# 5. VOICEOVER GENERATION (EDGE-TTS WITH TIMEOUT PROTECTION)
# ==============================================================================
async def _edge_tts_save(text, voice, rate, pitch, out_path):
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await asyncio.wait_for(communicate.save(out_path), timeout=45)


def generate_voiceover(text, out_path):
    clean_text = re.sub(r"[*_#`~]", "", str(text)).strip()
    for attempt in range(4):
        try:
            asyncio.run(_edge_tts_save(clean_text, VOICE_EN, "+4%", "-1Hz", out_path))
            if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
                return
        except Exception as e:
            print(f"⚠️ TTS retry {attempt + 1}: {e}")
            time.sleep(2)
    raise RuntimeError(f"❌ Failed to generate audio for {out_path}")


def get_media_duration(path):
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    try:
        return max(1.0, float(res.stdout.strip()))
    except Exception:
        return 10.0


# ==============================================================================
# 6. PEXELS SMART 720p HD DOWNLOADER (NO 4K BLOAT, NO STATIC PHOTOS)
# ==============================================================================
def download_file(url, dest_path):
    with requests.get(url, stream=True, timeout=20) as r:
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=131072):
                if chunk:
                    f.write(chunk)


def get_pexels_videos_for_scene(queries, count_needed, used_video_ids, scene_prefix):
    headers = {"Authorization": PEXELS_API_KEY}
    downloaded_clips = []

    fallback_queries = [
        "medical laboratory scientist",
        "doctor hospital technology",
        "microscope cells research",
        "dna genetics science",
        "brain scan neurology",
        "heart health cardiology",
        "surgeon operating room",
        "pharmaceutical medicine production"
    ]
    search_list = list(queries) + fallback_queries

    for q in search_list:
        if len(downloaded_clips) >= count_needed:
            break
        try:
            url = "https://api.pexels.com/videos/search"
            params = {
                "query": q,
                "per_page": 12,
                "orientation": "landscape",
                "size": "medium"
            }
            resp = requests.get(url, headers=headers, params=params, timeout=12)
            if resp.status_code != 200:
                continue

            videos = resp.json().get("videos", [])
            for v in videos:
                if len(downloaded_clips) >= count_needed:
                    break
                vid_id = str(v.get("id"))
                if vid_id in used_video_ids:
                    continue

                v_files = v.get("video_files", [])
                valid_files = [
                    vf for vf in v_files
                    if vf.get("file_type") == "video/mp4"
                    and 640 <= vf.get("width", 0) <= 1920
                    and vf.get("width", 0) >= vf.get("height", 0)
                ]
                if not valid_files:
                    continue

                valid_files.sort(key=lambda x: abs(x.get("width", 0) - 1280))
                chosen = valid_files[0]
                dl_link = chosen.get("link")
                if not dl_link:
                    continue

                clip_path = os.path.join(
                    WORK_DIR, f"{scene_prefix}_raw_{len(downloaded_clips)}.mp4"
                )
                try:
                    download_file(dl_link, clip_path)
                    if os.path.exists(clip_path) and os.path.getsize(clip_path) > 40000:
                        used_video_ids.add(vid_id)
                        downloaded_clips.append(clip_path)
                except Exception as e:
                    print(f"⚠️ Clip download skip: {e}")
        except Exception as e:
            print(f"⚠️ Pexels search error for '{q}': {e}")

    return downloaded_clips


# ==============================================================================
# 7. YOUTUBE THUMBNAIL GENERATOR (1280x720 HIGH-CTR DESIGN)
# ==============================================================================
def generate_youtube_thumbnail(thumb_query, line1, line2, sample_video_path, out_jpg="thumbnail.jpg"):
    print("🖼️ Generating High-CTR YouTube Thumbnail (thumbnail.jpg)...")
    bg_video = sample_video_path

    try:
        headers = {"Authorization": PEXELS_API_KEY}
        resp = requests.get(
            "https://api.pexels.com/videos/search",
            headers=headers,
            params={"query": thumb_query, "per_page": 5, "orientation": "landscape"},
            timeout=10
        )
        if resp.status_code == 200:
            vids = resp.json().get("videos", [])
            if vids:
                vfiles = [
                    vf for vf in vids[0].get("video_files", [])
                    if vf.get("file_type") == "video/mp4" and vf.get("width", 0) >= 1280
                ]
                if vfiles:
                    tmp_thumb_vid = os.path.join(WORK_DIR, "thumb_bg.mp4")
                    download_file(vfiles[0]["link"], tmp_thumb_vid)
                    if os.path.exists(tmp_thumb_vid) and os.path.getsize(tmp_thumb_vid) > 50000:
                        bg_video = tmp_thumb_vid
    except Exception:
        pass

    t1_file = os.path.join(WORK_DIR, "thumb_t1.txt")
    t2_file = os.path.join(WORK_DIR, "thumb_t2.txt")
    t3_file = os.path.join(WORK_DIR, "thumb_t3.txt")

    with open(t1_file, "w", encoding="utf-8") as f:
        f.write("BREAKING MEDICAL DISCOVERY")
    with open(t2_file, "w", encoding="utf-8") as f:
        f.write(str(line1).upper()[:22])
    with open(t3_file, "w", encoding="utf-8") as f:
        f.write(str(line2).upper()[:22])

    vf = (
        f"scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,"
        f"eq=contrast=1.18:saturation=1.25:brightness=-0.06,"
        f"drawbox=x=0:y=390:w=1280:h=330:color=#050b14@0.82:t=fill,"
        f"drawbox=x=0:y=390:w=1280:h=8:color=#00f5d4@1.0:t=fill,"
        f"drawbox=x=48:y=420:w=490:h=48:color=#e63946@1.0:t=fill,"
        f"drawtext=fontfile='{FONT_BOLD}':textfile='{t1_file}':fontcolor=white:fontsize=25:x=64:y=432,"
        f"drawtext=fontfile='{FONT_BOLD}':textfile='{t2_file}':fontcolor=white:fontsize=78:x=50:y=490:shadowcolor=black@0.9:shadowx=4:shadowy=4,"
        f"drawtext=fontfile='{FONT_BOLD}':textfile='{t3_file}':fontcolor=#ffd166:fontsize=84:x=50:y=590:shadowcolor=black@0.9:shadowx=4:shadowy=4"
    )

    if bg_video and os.path.exists(bg_video):
        cmd = [
            "ffmpeg", "-y", "-ss", "00:00:01.50", "-i", bg_video,
            "-frames:v", "1", "-vf", vf, "-q:v", "2", out_jpg
        ]
    else:
        cmd = [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=#0a1526:s=1280x720",
            "-frames:v", "1", "-vf", vf, "-q:v", "2", out_jpg
        ]

    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=25)


# ==============================================================================
# 8. SINGLE-PASS BROADCAST RENDERING (FAST & RELIABLE)
# ==============================================================================
def write_text_file(filename, content):
    clean = re.sub(r"\s+", " ", str(content)).strip()
    with open(filename, "w", encoding="utf-8") as f:
        f.write(clean)


def create_chapter_bumper(story_num, title_text, source_text, out_path):
    dur = 2.4
    f_badge = os.path.join(WORK_DIR, f"b_badge_{story_num}.txt")
    f_title = os.path.join(WORK_DIR, f"b_title_{story_num}.txt")
    f_src = os.path.join(WORK_DIR, f"b_src_{story_num}.txt")

    write_text_file(f_badge, f"BREAKTHROUGH #{story_num}")
    write_text_file(f_title, str(title_text).upper()[:52])
    write_text_file(f_src, f"VERIFIED SOURCE: {str(source_text)[:65]}")

    vf = (
        f"drawbox=x=80:y=190:w=1120:h=340:color=#0f1b2d@0.95:t=fill,"
        f"drawbox=x=80:y=190:w=14:h=340:color=#00f5d4@1.0:t=fill,"
        f"drawbox=x=80:y=524:w=1120:h=6:color=#ffd166@1.0:t=fill,"
        f"drawtext=fontfile='{FONT_BOLD}':textfile='{f_badge}':fontcolor=#00f5d4:fontsize=30:x=130:y=240,"
        f"drawtext=fontfile='{FONT_BOLD}':textfile='{f_title}':fontcolor=white:fontsize=38:x=130:y=315,"
        f"drawtext=fontfile='{FONT_REG}':textfile='{f_src}':fontcolor=#ffd166:fontsize=23:x=130:y=415,"
        f"fade=t=in:st=0:d=0.30,fade=t=out:st=2.05:d=0.35"
    )

    af = (
        "aevalsrc='0.12*sin(2*PI*523.25*t)*exp(-2.5*t)"
        "+0.10*sin(2*PI*659.25*t)*exp(-2.2*t)"
        "+0.08*sin(2*PI*783.99*t)*exp(-1.8*t)"
        "+0.06*sin(2*PI*1174.66*t)*exp(-1.5*t)':s=44100:d=2.4,"
        "pan=stereo|c0=c0|c1=c0"
    )

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=#080e18:s=1280x720:r=24:d={dur}",
        "-f", "lavfi", "-i", af,
        "-vf", vf,
        *VIDEO_ENC_FLAGS,
        "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "128k",
        "-t", str(dur),
        out_path
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)


def render_scene_ffmpeg(
    scene_id,
    audio_path,
    video_clips,
    stage_label,
    headline,
    subheadline,
    out_path,
    accent="#00f5d4"
):
    dur = get_media_duration(audio_path) + 0.25
    num_clips = max(1, len(video_clips))
    slot_dur = dur / num_clips

    tf_stage = os.path.join(WORK_DIR, f"{scene_id}_stage.txt")
    tf_title = os.path.join(WORK_DIR, f"{scene_id}_title.txt")
    tf_sub = os.path.join(WORK_DIR, f"{scene_id}_sub.txt")

    write_text_file(tf_stage, str(stage_label).upper()[:55])
    write_text_file(tf_title, str(headline).upper()[:54])
    write_text_file(tf_sub, str(subheadline)[:72])

    sub_videos = []
    for idx, clip_path in enumerate(video_clips):
        sub_out = os.path.join(WORK_DIR, f"{scene_id}_sub_{idx}.mp4")
        fade_out_st = max(0.1, slot_dur - 0.35)

        vf_filter = (
            f"scale=1280:720:force_original_aspect_ratio=increase,"
            f"crop=1280:720,setsar=1,fps=24,format=yuv420p,"
            f"fade=t=in:st=0:d=0.35,"
            f"fade=t=out:st={fade_out_st:.2f}:d=0.35,"
            f"drawbox=x=0:y=585:w=1280:h=135:color=#070d17@0.88:t=fill,"
            f"drawbox=x=0:y=585:w=1280:h=5:color={accent}@1.0:t=fill,"
            f"drawbox=x=38:y=602:w=10:h=96:color={accent}@1.0:t=fill,"
            f"drawtext=fontfile='{FONT_BOLD}':textfile='{tf_stage}':fontcolor={accent}:fontsize=21:x=66:y=604,"
            f"drawtext=fontfile='{FONT_BOLD}':textfile='{tf_title}':fontcolor=white:fontsize=31:x=66:y=634,"
            f"drawtext=fontfile='{FONT_REG}':textfile='{tf_sub}':fontcolor=#ffd166:fontsize=21:x=66:y=676"
        )

        cmd_sub = [
            "ffmpeg", "-y",
            "-stream_loop", "3",
            "-t", f"{slot_dur:.2f}",
            "-i", clip_path,
            "-t", f"{slot_dur:.2f}",
            "-vf", vf_filter,
            *VIDEO_ENC_FLAGS,
            "-an",
            sub_out
        ]
        try:
            res = subprocess.run(cmd_sub, capture_output=True, text=True, timeout=60)
            if res.returncode == 0 and os.path.exists(sub_out) and os.path.getsize(sub_out) > 10000:
                sub_videos.append(sub_out)
            else:
                print(f"⚠️ Sub-clip {idx} stderr: {res.stderr[-250:] if res.stderr else 'unknown'}")
        except Exception as e:
            print(f"⚠️ Sub-clip {idx} notice: {e}")

    if not sub_videos:
        fallback_v = os.path.join(WORK_DIR, f"{scene_id}_fallback.mp4")
        vf_fb = (
            f"drawbox=x=0:y=585:w=1280:h=135:color=#070d17@0.88:t=fill,"
            f"drawbox=x=0:y=585:w=1280:h=5:color={accent}@1.0:t=fill,"
            f"drawtext=fontfile='{FONT_BOLD}':textfile='{tf_stage}':fontcolor={accent}:fontsize=21:x=66:y=604,"
            f"drawtext=fontfile='{FONT_BOLD}':textfile='{tf_title}':fontcolor=white:fontsize=31:x=66:y=634,"
            f"drawtext=fontfile='{FONT_REG}':textfile='{tf_sub}':fontcolor=#ffd166:fontsize=21:x=66:y=676"
        )
        cmd_fb = [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c=#101d30:s=1280x720:r=24:d={dur:.2f}",
            "-vf", vf_fb,
            *VIDEO_ENC_FLAGS,
            "-an", fallback_v
        ]
        subprocess.run(cmd_fb, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        sub_videos.append(fallback_v)

    concat_list_file = os.path.join(WORK_DIR, f"{scene_id}_subs.txt")
    with open(concat_list_file, "w", encoding="utf-8") as f:
        for sv in sub_videos:
            f.write(f"file '{os.path.abspath(sv)}'\n")

    cmd_mux = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", concat_list_file,
        "-i", audio_path,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "128k",
        "-t", f"{dur:.2f}",
        out_path
    ]
    subprocess.run(cmd_mux, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)

    for sv in sub_videos:
        if os.path.exists(sv):
            os.remove(sv)
    for raw_c in video_clips:
        if os.path.exists(raw_c):
            os.remove(raw_c)

    return dur


def assemble_episode(segment_files, output_file):
    print(f"🎞️ Assembling final episode: {output_file}...")
    concat_file = os.path.join(WORK_DIR, "master_concat.txt")
    with open(concat_file, "w", encoding="utf-8") as f:
        for seg in segment_files:
            f.write(f"file '{os.path.abspath(seg)}'\n")

    cmd_fast = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", concat_file,
        "-c:v", "copy",
        "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "128k",
        "-movflags", "+faststart",
        output_file
    ]
    res = subprocess.run(cmd_fast, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)

    if res.returncode != 0 or not os.path.exists(output_file) or os.path.getsize(output_file) < 100000:
        print("⚡ Running fast unified stream encode...")
        cmd_fallback = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", concat_file,
            "-c:v", "libx264", "-preset", "ultrafast",
            "-crf", "27", "-maxrate", "950k", "-bufsize", "1900k",
            "-pix_fmt", "yuv420p", "-r", "24",
            "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "128k",
            "-movflags", "+faststart",
            output_file
        ]
        subprocess.run(cmd_fallback, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=600)

    size_mb = os.path.getsize(output_file) / (1024 * 1024)
    print(f"✅ Finished {output_file}! Size: {size_mb:.1f} MB (Mobile Friendly)")


def format_timestamp(seconds):
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"


# ==============================================================================
# 9. MAIN PIPELINE ORCHESTRATOR
# ==============================================================================
def main():
    start_time = time.time()
    candidates = fetch_candidate_medical_news(candidate_limit=28)
    script_data = generate_script_with_gemini(candidates)

    used_video_ids = load_set(USED_VIDEOS_FILE)
    initial_video_ids = set(used_video_ids)

    stories = script_data["stories"]
    selected_articles = []
    for idx, st in enumerate(stories):
        cand_idx = int(st.get("candidate_index", idx + 1)) - 1
        if 0 <= cand_idx < len(candidates):
            selected_articles.append(candidates[cand_idx])
        else:
            selected_articles.append(candidates[idx % len(candidates)])

    scenes = []
    intro = script_data["intro"]
    scenes.append({
        "id": "intro",
        "type": "intro",
        "narration_en": intro["narration_en"],
        "stage_en": "TODAY'S TOP 5 MEDICAL BREAKTHROUGHS",
        "headline_en": intro.get("headline_en", "5 BREAKTHROUGHS CHANGING HUMAN HEALTH"),
        "sub_en": intro.get("subheadline_en", "Verified Clinical & Research Report"),
        "queries": intro.get("search_queries", ["medical research laboratory", "doctor hospital"]),
        "accent": "#00f5d4"
    })

    act_configs = [
        ("act_1", "STAGE 1: THE NEW DISCOVERY", "#00f5d4"),
        ("act_2", "STAGE 2: INSIDE YOUR BODY", "#00bbf9"),
        ("act_3", "STAGE 3: CLINICAL STUDY PROOF", "#ffd166"),
        ("act_4", "STAGE 4: WHAT IT MEANS FOR YOU", "#06d6a0"),
    ]

    for idx, st in enumerate(stories):
        s_num = idx + 1
        art = selected_articles[idx]
        citation_en = st.get("source_citation_en") or f"{art['source']} • {art['pub_date']}"
        chapter_en = st.get("chapter_title_en") or art["title"][:52]

        for act_key, act_label, accent_color in act_configs:
            act_data = st[act_key]
            scenes.append({
                "id": f"story_{s_num}_{act_key}",
                "type": "story_act",
                "story_num": s_num,
                "is_first_act": (act_key == "act_1"),
                "chapter_en": chapter_en,
                "citation_en": citation_en,
                "narration_en": act_data["narration_en"],
                "stage_en": f"STORY #{s_num}  |  {act_label}",
                "headline_en": act_data.get("headline_en", chapter_en),
                "sub_en": f"Source: {citation_en} — {art['title'][:45]}...",
                "queries": act_data.get("search_queries", ["medical research", "hospital doctor"]),
                "accent": accent_color
            })

    outro = script_data["outro"]
    scenes.append({
        "id": "outro",
        "type": "outro",
        "narration_en": outro["narration_en"],
        "stage_en": "DAILY MEDICAL INTELLIGENCE SUMMARY",
        "headline_en": outro.get("headline_en", "THE FUTURE OF MEDICINE IS HERE"),
        "sub_en": outro.get("subheadline_en", "Subscribe & Share Your Thoughts Below"),
        "queries": outro.get("search_queries", ["futuristic hospital", "healthy lifestyle"]),
        "accent": "#00f5d4"
    })

    segments_en = []
    chapter_timestamps = [("00:00", "Cold Open: 5 Medical Breakthroughs")]
    current_time_en = 0.0
    first_downloaded_clip = None

    print(f"🎬 Starting single-pass production for {len(scenes)} scenes...")

    for i, sc in enumerate(scenes, 1):
        sid = sc["id"]
        print(f"  👉 [{i}/{len(scenes)}] Processing: {sid}")

        if sc.get("is_first_act"):
            s_num = sc["story_num"]
            chapter_timestamps.append(
                (format_timestamp(current_time_en), f"Breakthrough #{s_num}: {sc['chapter_en']}")
            )
            bumper_en = os.path.join(WORK_DIR, f"bumper_en_{s_num}.mp4")
            create_chapter_bumper(s_num, sc["chapter_en"], sc["citation_en"], bumper_en)
            segments_en.append(bumper_en)
            current_time_en += 2.4

        audio_en = os.path.join(WORK_DIR, f"{sid}_en.mp3")
        generate_voiceover(sc["narration_en"], audio_en)

        clips = get_pexels_videos_for_scene(
            sc["queries"], count_needed=3, used_video_ids=used_video_ids, scene_prefix=sid
        )

        if first_downloaded_clip is None and clips:
            first_downloaded_clip = os.path.join(WORK_DIR, "thumb_sample.mp4")
            shutil.copyfile(clips[0], first_downloaded_clip)

        scene_en_mp4 = os.path.join(WORK_DIR, f"{sid}_en.mp4")
        dur_en = render_scene_ffmpeg(
            scene_id=f"{sid}_en",
            audio_path=audio_en,
            video_clips=clips,
            stage_label=sc["stage_en"],
            headline=sc["headline_en"],
            subheadline=sc["sub_en"],
            out_path=scene_en_mp4,
            accent=sc["accent"]
        )
        segments_en.append(scene_en_mp4)
        current_time_en += dur_en

    generate_youtube_thumbnail(
        thumb_query=script_data.get("thumbnail_search_query", "glowing brain doctor"),
        line1=script_data.get("thumbnail_line1", "MEDICAL SHOCK"),
        line2=script_data.get("thumbnail_line2", "NEW DISCOVERY!"),
        sample_video_path=first_downloaded_clip,
        out_jpg="thumbnail.jpg"
    )

    assemble_episode(segments_en, "final_video.mp4")

    yt_title = script_data.get("youtube_title", "5 Shocking Medical Breakthroughs Discovered Today")
    yt_intro = script_data.get("youtube_description_intro", "")
    yt_tags = ", ".join(script_data.get("youtube_tags", ["medical news", "health breakthroughs"]))

    chapters_block = "\n".join([f"{ts} - {label}" for ts, label in chapter_timestamps])
    sources_block = "\n".join([
        f"• Breakthrough #{idx+1} ({art['source']} - {art['pub_date']}): {art['title']}\n  Link: {art['link']}"
        for idx, art in enumerate(selected_articles)
    ])

    details_content = f"""====================================================================
🎬 YOUTUBE VIDEO TITLE (COPY & PASTE):
====================================================================
{yt_title}

====================================================================
📝 YOUTUBE DESCRIPTION (WITH CHAPTERS & VERIFIED SOURCES):
====================================================================
{yt_intro}

In today's episode, we explore the 5 most fascinating medical, health, and longevity breakthroughs published by leading research institutions over the past 24 hours.

⏱️ VIDEO CHAPTERS (TIMESTAMPS):
{chapters_block}

🔬 VERIFIED SCIENTIFIC SOURCES & STUDIES CITED:
{sources_block}

⚠️ MEDICAL DISCLAIMER:
The content in this video is strictly for educational and informational purposes based on newly published peer-reviewed studies and university press releases. It does not constitute professional medical advice, diagnosis, or treatment. Always consult a qualified healthcare provider with any questions regarding a medical condition.

====================================================================
🏷️ YOUTUBE TAGS (COPY & PASTE):
====================================================================
{yt_tags}
"""
    with open("youtube_details.txt", "w", encoding="utf-8") as f:
        f.write(details_content)

    append_to_file(USED_NEWS_FILE, [a["title"] for a in selected_articles])
    new_vid_ids = used_video_ids - initial_video_ids
    append_to_file(USED_VIDEOS_FILE, list(new_vid_ids))

    elapsed = (time.time() - start_time) / 60.0
    print(f"🎉 ALL DONE in {elapsed:.1f} minutes! Video + Thumbnail + Metadata ready.")


if __name__ == "__main__":
    main()
