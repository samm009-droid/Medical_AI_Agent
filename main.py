import os
import re
import json
import time
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

genai.configure(api_key=GEMINI_API_KEY)

USED_NEWS_FILE = "used_news.txt"
USED_VIDEOS_FILE = "used_videos.txt"
WORK_DIR = "build_workspace"
os.makedirs(WORK_DIR, exist_ok=True)

VOICE_NAME = "en-US-ChristopherNeural"

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
# 3. FETCH 5 FRESH, REAL-TIME MEDICAL BREAKTHROUGHS
# ==============================================================================
def fetch_latest_medical_news(count=5):
    print("📡 Fetching global medical & research feeds (Real-Time)...")
    used_titles = load_set(USED_NEWS_FILE)
    candidates = []
    seen_now = set()

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    for source_name, url in RSS_FEEDS:
        try:
            resp = requests.get(url, headers=headers, timeout=15)
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
                    "summary": summary[:700],
                    "pub_date": pub_date_str,
                    "timestamp": timestamp
                })
        except Exception as e:
            print(f"⚠️ Warning fetching {source_name}: {e}")

    candidates.sort(key=lambda x: x["timestamp"], reverse=True)
    selected = candidates[:count]

    if len(selected) < count:
        raise RuntimeError(f"❌ Not enough new articles found (found {len(selected)}).")

    print(f"✅ Selected {len(selected)} fresh medical breakthroughs:")
    for idx, item in enumerate(selected, 1):
        print(f"  {idx}. [{item['source']} - {item['pub_date']}] {item['title']}")
    return selected


# ==============================================================================
# 4. GEMINI AI: DOCUMENTARY SCRIPT GENERATION
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
            for m in genai.list_models()
            if "generateContent" in getattr(m, "supported_generation_methods", [])
        ]
        for p in preferred:
            if p in available:
                print(f"🤖 Using Gemini Model: {p}")
                return genai.GenerativeModel(p)
        for a in available:
            if "gemini" in a.lower():
                print(f"🤖 Using Available Gemini Model: {a}")
                return genai.GenerativeModel(a)
    except Exception as e:
        print(f"⚠️ Could not list models dynamically: {e}")

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


def generate_script_with_gemini(news_items):
    print("🧠 Generating high-retention documentary script with Gemini AI...")
    model = get_working_gemini_model()

    news_block = ""
    for i, item in enumerate(news_items, 1):
        news_block += (
            f"\nSTORY #{i}:\n"
            f"- Title: {item['title']}\n"
            f"- Summary: {item['summary']}\n"
        )

    prompt = f"""
You are the Lead Producer and Host of a top-tier English Medical & Science YouTube Channel.
Your task is to write a gripping, conversational, high-retention 13 to 15 minute episode (~2,000 to 2,200 spoken words total) covering these 5 real-time medical breakthroughs:
{news_block}

CRITICAL STORYTELLING RULES:
1. Speak directly to the viewer ("you", "your body") with warmth, excitement, and scientific clarity.
2. Start the Intro with a unique, surprising Cold-Open Hook question or mystery before welcoming the viewer.
3. DO NOT read website names (like MedicalXpress, News-Medical, ScienceDaily) or publication dates out loud in the narration. Keep the spoken narration 100% immersive, natural storytelling (sources will be listed in the written video description box).
4. Divide EACH of the 5 stories into 4 distinct acts (Act 1: The Discovery, Act 2: How It Works Inside Your Body using a simple everyday analogy, Act 3: The Clinical Proof & Numbers, Act 4: What It Means For Your Future + a 1-sentence cliffhanger for the next story).
5. For every single act, provide 3 specific visual search queries (2-4 English words each) suitable for finding moving stock footage on Pexels (e.g., "microscope cells dividing", "doctor checking mri", "dna helix glowing").

Return STRICTLY valid JSON (no markdown code blocks) with this exact structure:
{{
  "youtube_title": "Viral, curiosity-driven YouTube title (under 90 chars)",
  "youtube_description_intro": "Engaging 3-sentence summary for YouTube description.",
  "youtube_tags": ["medical news", "health breakthroughs", "science news", "longevity", "medical research"],
  "intro": {{
    "narration": "140-160 words. Start with a shocking Cold-Open hook, then welcome viewers and preview today's 5 breakthroughs.",
    "headline": "5 BREAKTHROUGHS CHANGING HUMAN HEALTH",
    "subheadline": "Verified Clinical & Research Report",
    "search_queries": ["hospital doctor walking", "medical laboratory scientist", "dna double helix"]
  }},
  "stories": [
    {{
      "story_number": 1,
      "chapter_title": "Short compelling title for Story 1 (max 52 chars)",
      "act_1": {{
        "narration": "90-105 words. Hook the viewer with a relatable human problem, then reveal the new discovery.",
        "headline": "SHORT UPPERCASE HEADLINE (MAX 48 CHARS)",
        "search_queries": ["visual query 1", "visual query 2", "visual query 3"]
      }},
      "act_2": {{
        "narration": "90-105 words. Explain the biological mechanism inside the body using a vivid everyday analogy.",
        "headline": "HOW IT WORKS INSIDE YOUR CELLS",
        "search_queries": ["visual query 1", "visual query 2", "visual query 3"]
      }},
      "act_3": {{
        "narration": "90-105 words. Detail the clinical trial results, data, and why researchers were amazed.",
        "headline": "CLINICAL TRIAL DATA & PROOF",
        "search_queries": ["visual query 1", "visual query 2", "visual query 3"]
      }},
      "act_4": {{
        "narration": "90-105 words. Practical impact on patients, future outlook, and a cliffhanger bridge to the next story.",
        "headline": "WHAT THIS MEANS FOR YOUR HEALTH",
        "search_queries": ["visual query 1", "visual query 2", "visual query 3"]
      }}
    }}
  ],
  "outro": {{
    "narration": "95-115 words. Inspiring wrap-up, ask viewers which breakthrough amazed them most in the comments, remind to subscribe, and state that all scientific study links are in the description below along with an educational medical disclaimer.",
    "headline": "THE FUTURE OF MEDICINE IS HERE",
    "subheadline": "Subscribe for Daily Evidence-Based Breakthroughs",
    "search_queries": ["futuristic hospital technology", "doctor smiling", "healthy active lifestyle"]
  }}
}}

Ensure the `stories` list contains all 5 stories (story_number 1 to 5).
"""

    last_err = None
    for attempt in range(3):
        try:
            response = model.generate_content(
                prompt,
                generation_config={"temperature": 0.65}
            )
            data = extract_json_safely(response.text)
            if "stories" in data and len(data["stories"]) == 5:
                print("✅ Documentary script generated and validated!")
                return data
            else:
                raise ValueError("JSON did not contain 5 stories.")
        except Exception as e:
            last_err = e
            print(f"⚠️ Gemini attempt {attempt + 1} failed: {e}. Retrying in 5s...")
            time.sleep(5)

    raise RuntimeError(f"❌ Failed to generate script from Gemini: {last_err}")


# ==============================================================================
# 5. VOICEOVER GENERATION (EDGE-TTS)
# ==============================================================================
async def _edge_tts_save(text, out_path):
    communicate = edge_tts.Communicate(text, VOICE_NAME, rate="+4%", pitch="-1Hz")
    await communicate.save(out_path)


def generate_voiceover(text, out_path):
    clean_text = re.sub(r"[*_#`~]", "", str(text)).strip()
    for attempt in range(4):
        try:
            asyncio.run(_edge_tts_save(clean_text, out_path))
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
    res = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return max(1.0, float(res.stdout.strip()))
    except Exception:
        return 10.0


# ==============================================================================
# 6. PEXELS STRICT MOVING VIDEO DOWNLOADER (ZERO STATIC PHOTOS)
# ==============================================================================
def download_file(url, dest_path):
    with requests.get(url, stream=True, timeout=30) as r:
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
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
                "per_page": 15,
                "orientation": "landscape",
                "size": "medium"
            }
            resp = requests.get(url, headers=headers, params=params, timeout=15)
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
                    if os.path.exists(clip_path) and os.path.getsize(clip_path) > 50000:
                        used_video_ids.add(vid_id)
                        downloaded_clips.append(clip_path)
                except Exception as e:
                    print(f"⚠️ Clip download failed: {e}")
        except Exception as e:
            print(f"⚠️ Pexels search error for '{q}': {e}")

    return downloaded_clips


# ==============================================================================
# 7. FFMPEG BROADCAST RENDERING (CHAPTER BUMPERS + SLIM LOWER-THIRDS)
# ==============================================================================
def write_text_file(filename, content):
    clean = re.sub(r"\s+", " ", str(content)).strip()
    with open(filename, "w", encoding="utf-8") as f:
        f.write(clean)


def create_chapter_bumper(story_num, title_text, out_path):
    dur = 2.4
    f_badge = os.path.join(WORK_DIR, f"b_badge_{story_num}.txt")
    f_title = os.path.join(WORK_DIR, f"b_title_{story_num}.txt")
    f_sub = os.path.join(WORK_DIR, f"b_sub_{story_num}.txt")

    write_text_file(f_badge, f"BREAKTHROUGH #{story_num}")
    write_text_file(f_title, str(title_text).upper()[:52])
    write_text_file(f_sub, "FULL STUDY & SOURCE LINK IN DESCRIPTION BELOW")

    vf = (
        f"drawbox=x=80:y=190:w=1120:h=340:color=#0f1b2d@0.95:t=fill,"
        f"drawbox=x=80:y=190:w=14:h=340:color=#00f5d4@1.0:t=fill,"
        f"drawbox=x=80:y=524:w=1120:h=6:color=#ffd166@1.0:t=fill,"
        f"drawtext=fontfile='{FONT_BOLD}':textfile='{f_badge}':fontcolor=#00f5d4:fontsize=30:x=130:y=240,"
        f"drawtext=fontfile='{FONT_BOLD}':textfile='{f_title}':fontcolor=white:fontsize=38:x=130:y=315,"
        f"drawtext=fontfile='{FONT_REG}':textfile='{f_sub}':fontcolor=#ffd166:fontsize=21:x=130:y=415,"
        f"fade=t=in:st=0:d=0.35,fade=t=out:st=2.0:d=0.4"
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
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "25", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "128k",
        "-t", str(dur),
        out_path
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def render_scene_ffmpeg(
    scene_id,
    audio_path,
    video_clips,
    stage_label,
    headline,
    out_path,
    accent="#00f5d4"
):
    dur = get_media_duration(audio_path) + 0.25
    num_clips = max(1, len(video_clips))
    slot_dur = dur / num_clips

    sub_videos = []
    for idx, clip_path in enumerate(video_clips):
        sub_out = os.path.join(WORK_DIR, f"{scene_id}_sub_{idx}.mp4")
        fade_out_st = max(0.1, slot_dur - 0.35)

        vf = (
            f"scale=1280:720:force_original_aspect_ratio=increase,"
            f"crop=1280:720,setsar=1,fps=24,format=yuv420p,"
            f"fade=t=in:st=0:d=0.35,"
            f"fade=t=out:st={fade_out_st:.2f}:d=0.35"
        )

        cmd_sub = [
            "ffmpeg", "-y",
            "-stream_loop", "-1",
            "-t", f"{slot_dur:.2f}",
            "-i", clip_path,
            "-t", f"{slot_dur:.2f}",
            "-vf", vf,
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "25",
            "-an",
            sub_out
        ]
        try:
            subprocess.run(cmd_sub, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            sub_videos.append(sub_out)
        except Exception as e:
            print(f"⚠️ Sub-clip render warning: {e}")

    if not sub_videos:
        fallback_v = os.path.join(WORK_DIR, f"{scene_id}_fallback.mp4")
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c=#101d30:s=1280x720:r=24:d={dur:.2f}",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            fallback_v
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        sub_videos.append(fallback_v)

    concat_list_file = os.path.join(WORK_DIR, f"{scene_id}_subs.txt")
    with open(concat_list_file, "w", encoding="utf-8") as f:
        for sv in sub_videos:
            f.write(f"file '{os.path.abspath(sv)}'\n")

    bg_joined = os.path.join(WORK_DIR, f"{scene_id}_bg.mp4")
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_list_file, "-c", "copy", bg_joined
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    tf_stage = os.path.join(WORK_DIR, f"{scene_id}_stage.txt")
    tf_title = os.path.join(WORK_DIR, f"{scene_id}_title.txt")

    write_text_file(tf_stage, str(stage_label).upper()[:58])
    write_text_file(tf_title, str(headline).upper()[:58])

    # Sleek, compact 2-line lower-third banner (76px height instead of 135px)
    overlay_vf = (
        f"drawbox=x=0:y=644:w=1280:h=76:color=#070d17@0.84:t=fill,"
        f"drawbox=x=0:y=644:w=1280:h=3:color={accent}@1.0:t=fill,"
        f"drawbox=x=36:y=656:w=7:h=52:color={accent}@1.0:t=fill,"
        f"drawtext=fontfile='{FONT_BOLD}':textfile='{tf_stage}':fontcolor={accent}:fontsize=17:x=56:y=656,"
        f"drawtext=fontfile='{FONT_BOLD}':textfile='{tf_title}':fontcolor=white:fontsize=25:x=56:y=680"
    )

    cmd_final_scene = [
        "ffmpeg", "-y",
        "-i", bg_joined,
        "-i", audio_path,
        "-vf", overlay_vf,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "25", "-pix_fmt", "yuv420p", "-r", "24",
        "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "128k",
        "-t", f"{dur:.2f}",
        out_path
    ]
    subprocess.run(cmd_final_scene, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return dur


# ==============================================================================
# 8. MAIN PIPELINE ORCHESTRATOR
# ==============================================================================
def format_timestamp(seconds):
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"


def main():
    news_items = fetch_latest_medical_news(count=5)
    script_data = generate_script_with_gemini(news_items)

    used_video_ids = load_set(USED_VIDEOS_FILE)
    initial_video_ids = set(used_video_ids)

    scenes = []

    intro = script_data["intro"]
    scenes.append({
        "id": "intro",
        "type": "intro",
        "narration": intro.get("narration") or intro.get("narration_en"),
        "stage_label": "TODAY'S TOP 5 MEDICAL BREAKTHROUGHS",
        "headline": intro.get("headline", "5 BREAKTHROUGHS CHANGING HUMAN HEALTH"),
        "queries": intro.get("search_queries", ["medical research laboratory", "doctor hospital"]),
        "accent": "#00f5d4"
    })

    act_labels = [
        ("act_1", "STAGE 1: THE NEW DISCOVERY", "#00f5d4"),
        ("act_2", "STAGE 2: INSIDE YOUR BODY", "#00bbf9"),
        ("act_3", "STAGE 3: CLINICAL STUDY PROOF", "#ffd166"),
        ("act_4", "STAGE 4: WHAT IT MEANS FOR YOU", "#06d6a0"),
    ]

    for idx, st in enumerate(script_data["stories"]):
        s_num = idx + 1
        src_info = news_items[idx] if idx < len(news_items) else news_items[0]
        chapter_title = st.get("chapter_title") or src_info["title"][:50]

        for act_key, act_stage_name, accent_color in act_labels:
            act_data = st[act_key]
            scenes.append({
                "id": f"story_{s_num}_{act_key}",
                "type": "story_act",
                "story_num": s_num,
                "is_first_act": (act_key == "act_1"),
                "chapter_title": chapter_title,
                "narration": act_data.get("narration") or act_data.get("narration_en"),
                "stage_label": f"STORY #{s_num}  |  {act_stage_name}",
                "headline": act_data.get("headline", chapter_title),
                "queries": act_data.get("search_queries", ["medical research", "hospital doctor"]),
                "accent": accent_color
            })

    outro = script_data["outro"]
    scenes.append({
        "id": "outro",
        "type": "outro",
        "narration": outro.get("narration") or outro.get("narration_en"),
        "stage_label": "DAILY MEDICAL INTELLIGENCE SUMMARY",
        "headline": outro.get("headline", "THE FUTURE OF MEDICINE IS HERE"),
        "queries": outro.get("search_queries", ["futuristic hospital", "healthy lifestyle"]),
        "accent": "#00f5d4"
    })

    final_segments = []
    chapter_timestamps = [("00:00", "Cold Open: 5 Medical Breakthroughs")]
    current_time = 0.0

    print(f"🎬 Starting video production for {len(scenes)} scenes...")

    for i, sc in enumerate(scenes, 1):
        sid = sc["id"]
        print(f"  👉 [{i}/{len(scenes)}] Rendering scene: {sid}...")

        if sc.get("is_first_act"):
            s_num = sc["story_num"]
            chapter_timestamps.append(
                (format_timestamp(current_time), f"Breakthrough #{s_num}: {sc['chapter_title']}")
            )
            bumper_path = os.path.join(WORK_DIR, f"bumper_{s_num}.mp4")
            create_chapter_bumper(s_num, sc["chapter_title"], bumper_path)
            final_segments.append(bumper_path)
            current_time += 2.4

        audio_path = os.path.join(WORK_DIR, f"{sid}.mp3")
        generate_voiceover(sc["narration"], audio_path)

        clips = get_pexels_videos_for_scene(
            sc["queries"], count_needed=3, used_video_ids=used_video_ids, scene_prefix=sid
        )

        scene_mp4 = os.path.join(WORK_DIR, f"{sid}_final.mp4")
        sc_dur = render_scene_ffmpeg(
            scene_id=sid,
            audio_path=audio_path,
            video_clips=clips,
            stage_label=sc["stage_label"],
            headline=sc["headline"],
            out_path=scene_mp4,
            accent=sc["accent"]
        )
        final_segments.append(scene_mp4)
        current_time += sc_dur

    print("🎞️ Concatenating & compressing final HD episode for fast mobile download...")
    master_list = os.path.join(WORK_DIR, "master_concat.txt")
    with open(master_list, "w", encoding="utf-8") as f:
        for seg in final_segments:
            f.write(f"file '{os.path.abspath(seg)}'\n")

    output_video = "final_video.mp4"
    cmd_concat = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", master_list,
        "-c:v", "libx264", "-preset", "ultrafast",
        "-crf", "27", "-maxrate", "950k", "-bufsize", "1900k",
        "-pix_fmt", "yuv420p", "-r", "24",
        "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "128k",
        "-movflags", "+faststart",
        output_video
    ]
    subprocess.run(cmd_concat, check=True)

    size_mb = os.path.getsize(output_video) / (1024 * 1024)
    print(f"✅ Final video ready: {output_video} ({size_mb:.1f} MB - Total Duration: {format_timestamp(current_time)})")

    yt_title = script_data.get("youtube_title", "5 Shocking Medical Breakthroughs Discovered Today")
    yt_intro = script_data.get("youtube_description_intro", "")
    yt_tags = ", ".join(script_data.get("youtube_tags", ["medical news", "health breakthroughs"]))

    chapters_block = "\n".join([f"{ts} - {label}" for ts, label in chapter_timestamps])
    sources_block = "\n".join([
        f"• Breakthrough #{idx+1} ({item['source']} - {item['pub_date']}): {item['title']}\n  Study Link: {item['link']}"
        for idx, item in enumerate(news_items)
    ])

    details_content = f"""====================================================================
🎬 YOUTUBE VIDEO TITLE (COPY & PASTE):
====================================================================
{yt_title}

====================================================================
📝 YOUTUBE DESCRIPTION (WITH CHAPTERS & VERIFIED SOURCES):
====================================================================
{yt_intro}

In today's episode, we explore 5 brand-new medical, health, and clinical research breakthroughs published over the past 24 hours.

⏱️ VIDEO CHAPTERS (TIMESTAMPS):
{chapters_block}

🔬 VERIFIED SCIENTIFIC SOURCES & STUDIES CITED IN THIS VIDEO:
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

    append_to_file(USED_NEWS_FILE, [item["title"] for item in news_items])
    new_vid_ids = used_video_ids - initial_video_ids
    append_to_file(USED_VIDEOS_FILE, list(new_vid_ids))
    print("💾 Memory updated (used_news.txt & used_videos.txt). All done!")


if __name__ == "__main__":
    main()
