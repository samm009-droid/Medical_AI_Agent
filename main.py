import sys
import subprocess

# Ensure latest voice & AI libraries
subprocess.run([
    sys.executable, "-m", "pip", "install", "-q", "--upgrade",
    "edge-tts", "google-generativeai"
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
import google.generativeai as genai
from PIL import Image, ImageDraw, ImageFont

# ==================== 1. CONFIGURATION ====================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")
VOICE_EN = "en-US-ChristopherNeural"  # Constant American Documentary Narrator
USED_NEWS_FILE = "used_news.txt"

RSS_FEEDS = [
    ("ScienceDaily Health", "https://www.sciencedaily.com/rss/health_medicine.xml"),
    ("MedicalXpress", "https://medicalxpress.com/rss-feed/"),
    ("ScienceDaily Mind & Brain", "https://www.sciencedaily.com/rss/mind_brain.xml"),
    ("ScienceDaily Living Well", "https://www.sciencedaily.com/rss/living_well.xml"),
    ("EurekAlert Medicine", "https://www.eurekalert.org/rss/medicine_health.xml"),
    ("News-Medical", "https://www.news-medical.net/tag/feed/Medical-Research.aspx")
]

FALLBACK_VIDEO_QUERIES = [
    "scientist microscope laboratory", "medical research lab",
    "doctor talking patient hospital", "dna genetics animation",
    "medicine pills manufacturing", "brain scan hospital",
    "surgeon operating room", "heart monitor hospital",
    "blood test tube laboratory", "pharmacist medicine",
    "healthy food nutrition", "person sleeping bedroom",
    "doctor computer hospital", "clinical trial scientist"
]

os.makedirs("temp", exist_ok=True)
used_pexels_ids = set()
http_session = requests.Session()

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

# ==================== 3. VIRAL MEDICAL NEWS FILTER (PICK MOST EXCITING 5 OF 30) ====================
def load_used_titles():
    if os.path.exists(USED_NEWS_FILE):
        with open(USED_NEWS_FILE, "r", encoding="utf-8") as f:
            return set(line.strip().lower() for line in f if line.strip())
    return set()

def save_used_titles(new_titles):
    with open(USED_NEWS_FILE, "a", encoding="utf-8") as f:
        for t in new_titles:
            f.write(t.strip() + "\n")

def fetch_viral_medical_news(count=5):
    print("Scanning global feeds for candidate medical breakthroughs...")
    used_titles = load_used_titles()
    candidates = []
    seen_now = set()

    for source_name, url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:12]:
                title = entry.get("title", "").strip()
                summary = re.sub(r"<[^>]+>", "", entry.get("summary", "")).strip()
                link = entry.get("link", "").strip()
                t_lower = title.lower()
                if title and len(summary) > 60 and t_lower not in used_titles and t_lower not in seen_now:
                    seen_now.add(t_lower)
                    candidates.append({
                        "title": title,
                        "summary": summary[:900],
                        "source": source_name,
                        "link": link
                    })
        except Exception as e:
            print(f"RSS error ({url}): {e}")

    if len(candidates) < count:
        for source_name, url in RSS_FEEDS:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
                title = entry.get("title", "").strip()
                summary = re.sub(r"<[^>]+>", "", entry.get("summary", "")).strip()
                link = entry.get("link", "").strip()
                if title and title.lower() not in seen_now:
                    seen_now.add(title.lower())
                    candidates.append({
                        "title": title,
                        "summary": summary[:900],
                        "source": source_name,
                        "link": link
                    })

    pool = candidates[:28]
    if len(pool) <= count:
        selected = pool[:count]
        save_used_titles([a["title"] for a in selected])
        return selected

    print(f"Using AI Viral Editor to select the 5 most fascinating human-relevant breakthroughs out of {len(pool)}...")
    numbered_list = "\n".join([f"{i}: {a['title']} — {a['summary'][:180]}" for i, a in enumerate(pool)])
    selector_prompt = f"""
    You are a viral YouTube Medical Documentary Producer (like Dr. Eric Berg, Institute of Human Anatomy, and Veritasium).
    Below are {len(pool)} newly published medical & health news articles:
    {numbered_list}

    Select the 5 MOST FASCINATING, SHOCKING, AND HUMAN-RELEVANT stories that everyday viewers in the US and Europe will care deeply about (prioritize topics about: sleep, brain/memory, heart health, longevity/aging, common medications/drugs, everyday foods/drinks, cancer breakthroughs, gut health, or surprising body secrets. AVOID dry, overly technical lab-only chemistry stories).

    Order them from #1 (Most Mind-Blowing Hook Story) to #5.
    Return ONLY valid JSON in this exact format:
    {{
      "selected_indices": [0, 4, 7, 12, 19]
    }}
    """
    try:
        sel_data = clean_json_response(ask_gemini(selector_prompt))
        indices = [int(x) for x in sel_data.get("selected_indices", []) if 0 <= int(x) < len(pool)]
        selected = []
        for idx in indices:
            if pool[idx] not in selected:
                selected.append(pool[idx])
        for item in pool:
            if len(selected) >= count:
                break
            if item not in selected:
                selected.append(item)
        selected = selected[:count]
    except Exception as e:
        print(f"Viral selector fallback note: {e}")
        selected = pool[:count]

    save_used_titles([a["title"] for a in selected])
    return selected

# ==================== 4. HIGH-RETENTION STORYTELLING SCRIPT BUILDER ====================
def build_storytelling_script(articles):
    print("Crafting High-Retention YouTube Medical Storytelling Script...")
    segments = []
    titles_list = "\n".join([f"Story #{i+1}: {a['title']} (Source: {a['source']})" for i, a in enumerate(articles)])

    # A. Explosive Cold-Open Hook & Episode Intro
    intro_prompt = f"""
    You are a charismatic, million-subscriber American YouTube medical storyteller.
    Today's 5 real-time medical breakthroughs are:
    {titles_list}
    Lead Story Summary: {articles[0]['summary']}

    Write a high-retention 135-word "Cold-Open Hook & Intro":
    - DO NOT sound like a boring news anchor. Never say "Welcome to today's report."
    - Start Sentence #1 by addressing the viewer directly ("You") with a mind-blowing question, everyday habit, or shocking scenario from Story #1 that grabs their attention in the first 5 seconds!
    - Then tease how today's new medical discoveries are flipping what we know about the human body upside down, and briefly tease the other breakthroughs coming up in this episode so viewers stay until the end.
    - Also generate a high-CTR viral YouTube Title (curiosity-driven, under 85 chars), a compelling SEO Description, and 12 tags.

    Return ONLY valid JSON in this exact structure:
    {{
      "youtube_title": "Curiosity-driven viral medical YouTube title...",
      "youtube_description": "Engaging SEO description...",
      "youtube_tags": ["medical breakthroughs", "health news", "human body"],
      "intro_narration": "135 words spoken conversational storytelling only (no stage directions, no labels)...",
      "visual_queries": ["human brain glowing", "doctor examining patient", "scientist laboratory", "medical technology"]
    }}
    """
    meta_data = clean_json_response(ask_gemini(intro_prompt))
    segments.append({
        "is_transition_start": True,
        "source_badge": "BREAKING HEALTH SCIENCE  |  VERIFIED RESEARCH",
        "headline": meta_data.get("youtube_title", "5 NEW DISCOVERIES CHANGING HUMAN HEALTH").upper()[:62],
        "narration": meta_data["intro_narration"],
        "queries": meta_data.get("visual_queries", ["human brain", "doctor patient", "scientist laboratory", "medical technology"])
    })
    time.sleep(4)

    # B. 5 Stories x 4 Fast-Paced Storytelling Acts (With Analogies & Cliffhangers!)
    for idx, article in enumerate(articles):
        next_story_title = articles[idx + 1]["title"] if idx + 1 < len(articles) else "our final health takeaway"
        print(f"Writing High-Retention Storytelling Acts for Breakthrough {idx+1}/5...")

        story_prompt = f"""
        You are an elite American YouTube medical storyteller (like Institute of Human Anatomy & Veritasium).
        Transform this brand-new scientific study into a gripping, easy-to-follow, conversational story that keeps viewers glued to the screen:

        Study Title: {article['title']}
        Scientific Source: {article['source']}
        Study Details: {article['summary']}
        Next Story Coming Up After This One: {next_story_title}

        STORYTELLING RULES (CRITICAL):
        - NEVER use boring phrases like "Report number {idx+1}" or "In this article."
        - Speak directly to the viewer ("you", "your body", "your brain", "imagine waking up...").
        - Explain complex medical terms using vivid, everyday analogies (e.g., comparing immune cells to security guards, blood vessels to highways, brain signals to electrical wiring).
        - Naturally mention the scientific source ("Researchers featured in {article['source']}" or the specific university in the summary) to build authority.

        Divide this story into EXACTLY 4 engaging acts (90 to 100 words per act, total ~380 words):
        - Act 1 (The Relatable Mystery & Shocking Discovery): Start with a relatable human symptom, daily habit, or mystery the viewer experiences, then reveal the surprising breakthrough scientists just uncovered.
        - Act 2 (Inside Your Body - The Simple Analogy): Take the viewer on a visual journey inside the human body. Use a crystal-clear analogy to explain how this drug, cell, or biological mechanism actually works.
        - Act 3 (The Plot Twist & Real Proof): Share what happened in the study or clinical trials—the surprising numbers, why doctors were stunned, and who this can save or help.
        - Act 4 (What This Means For YOU + Cliffhanger Bridge): Give the viewer a practical takeaway for their own health awareness, and in the final sentence, create a suspenseful cliffhanger transition teasing the next story ("{next_story_title}")! (If this is Story #5, tease the final big takeaway instead).

        FAST VISUAL PACING RULE:
        For EACH act, provide 4 concrete, physical stock-video search queries (2 to 3 simple English words each, e.g., "person drinking coffee", "brain mri scan", "pills medicine", "doctor talking patient", "microscope cells", "woman sleeping bed", "man chest pain", "surgeon operating room") matching the 4 quarters of that act's narration!

        Return ONLY valid JSON in this exact format:
        {{
          "curiosity_headline": "INTRIGUING 6-TO-9 WORD HEADLINE UNDER 58 CHARS",
          "acts": [
            {{
              "narration": "90-100 words conversational spoken narration...",
              "visual_queries": ["query 1", "query 2", "query 3", "query 4"]
            }},
            {{
              "narration": "90-100 words conversational spoken narration...",
              "visual_queries": ["query 1", "query 2", "query 3", "query 4"]
            }},
            {{
              "narration": "90-100 words conversational spoken narration...",
              "visual_queries": ["query 1", "query 2", "query 3", "query 4"]
            }},
            {{
              "narration": "90-100 words conversational spoken narration...",
              "visual_queries": ["query 1", "query 2", "query 3", "query 4"]
            }}
          ]
        }}
        """
        story_data = clean_json_response(ask_gemini(story_prompt))
        headline = story_data.get("curiosity_headline", article["title"][:58]).upper()

        for a_idx, act in enumerate(story_data["acts"]):
            segments.append({
                "is_transition_start": (a_idx == 0),
                "source_badge": f"BREAKTHROUGH #{idx+1}  |  SOURCE: {article['source'].upper()}",
                "headline": headline,
                "narration": act["narration"],
                "queries": act.get("visual_queries", ["medical research", "doctor patient", "scientist lab", "human health"])
            })
        time.sleep(4)

    # C. Inspiring YouTube Outro
    outro_prompt = """
    Write an energetic, inspiring 95-word YouTube conclusion for a medical storytelling episode.
    Ask the viewer a specific engagement question ("Which of today's 5 breakthroughs surprised you the most? Let us know in the comments below!"), remind them that all verified scientific sources are linked in the description and that this video is for educational purposes, and invite them to subscribe.
    Return ONLY valid JSON:
    {
      "outro_narration": "95 words spoken English conclusion only...",
      "visual_queries": ["happy healthy people", "doctor smiling hospital", "modern medical technology", "active lifestyle running"]
    }
    """
    outro_data = clean_json_response(ask_gemini(outro_prompt))
    segments.append({
        "is_transition_start": True,
        "source_badge": "VERIFIED SCIENTIFIC LINKS IN DESCRIPTION",
        "headline": "WHICH BREAKTHROUGH SURPRISED YOU MOST? COMMENT BELOW!",
        "narration": outro_data["outro_narration"],
        "queries": outro_data.get("visual_queries", ["doctor smiling", "healthy lifestyle", "hospital", "medical technology"])
    })

    return meta_data, segments

# ==================== 5. ENERGETIC AMERICAN NARRATOR (+4% PACING) ====================
async def _generate_tts(text, output_file):
    # +4% rate gives engaging, energetic YouTube documentary pacing (never slow or robotic!)
    communicate = edge_tts.Communicate(text, VOICE_EN, rate="+4%", pitch="-1Hz")
    await communicate.save(output_file)

def create_voiceover(text, output_file):
    clean_text = re.sub(r"[*#_~`]", "", text).strip()
    for attempt in range(3):
        try:
            asyncio.run(_generate_tts(clean_text, output_file))
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

# ==================== 6. FAST 100% MOVING VIDEO DOWNLOADER ====================
def score_video_relevance(video_obj, query):
    slug = video_obj.get("url", "").lower()
    keywords = [w.lower() for w in re.findall(r"\w+", query) if len(w) > 2]
    score = sum(3 for kw in keywords if kw in slug)
    dur = video_obj.get("duration", 0)
    if 6 <= dur <= 28:
        score += 2
    return score

def download_strict_video(query, dest_path):
    headers = {"Authorization": PEXELS_API_KEY}
    words = query.split()
    attempts = [query]
    if len(words) > 2:
        attempts.append(" ".join(words[:2]))
    attempts.extend(random.sample(FALLBACK_VIDEO_QUERIES, 4))

    for q in attempts:
        url = f"https://api.pexels.com/videos/search?query={urllib.parse.quote(q)}&orientation=landscape&size=medium&per_page=15"
        try:
            r = http_session.get(url, headers=headers, timeout=15)
            if r.status_code == 200:
                videos = [v for v in r.json().get("videos", []) if v.get("id") not in used_pexels_ids]
                videos.sort(key=lambda v: score_video_relevance(v, q), reverse=True)

                for v in videos:
                    vid_id = v.get("id")
                    for vf in v.get("video_files", []):
                        w = vf.get("width", 0)
                        if 1280 <= w <= 1920 and vf.get("link"):
                            vid_resp = http_session.get(vf["link"], timeout=30)
                            if vid_resp.status_code == 200 and len(vid_resp.content) > 50000:
                                with open(dest_path, "wb") as f:
                                    f.write(vid_resp.content)
                                used_pexels_ids.add(vid_id)
                                return True
        except Exception as e:
            print(f"Video search note for '{q}': {e}")
    return False

# ==================== 7. SLEEK YOUTUBE DOCUMENTARY GRAPHICS ====================
def create_broadcast_overlay(headline, source_badge, output_png, is_new_story=False):
    img = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    accent_color = (230, 35, 50, 255) if is_new_story else (0, 200, 240, 255)

    # Top-right Sleek Badge
    draw.rectangle([985, 30, 1242, 68], fill=(15, 28, 55, 225))
    draw.rectangle([985, 30, 992, 68], fill=accent_color)

    # Modern Lower-Third Overlay
    draw.rectangle([0, 604, 1280, 688], fill=(8, 18, 38, 235))
    draw.rectangle([0, 597, 1280, 604], fill=accent_color)
    draw.rectangle([40, 562, 600, 597], fill=(0, 130, 180, 255))

    try:
        font_badge = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 17)
        font_main = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 25)
    except Exception:
        font_badge = ImageFont.load_default()
        font_main = ImageFont.load_default()

    draw.text((1005, 40), "MEDICAL SCIENCE HD", fill=(255, 255, 255, 255), font=font_badge)
    draw.text((55, 571), source_badge[:60], fill=(255, 255, 255, 255), font=font_badge)
    draw.text((45, 630), headline[:66], fill=(255, 255, 255, 255), font=font_main)
    img.save(output_png)

# ==================== 8. FAST-PACED 4-CUT FFMPEG RENDERER (ZERO FREEZE) ====================
def render_scene(idx, segment):
    audio_path = f"temp/audio_{idx}.mp3"
    overlay_path = f"temp/overlay_{idx}.png"
    out_segment = f"temp/seg_{idx:03d}.mp4"

    is_trans = segment.get("is_transition_start", False)

    create_voiceover(segment["narration"], audio_path)
    audio_dur = get_media_duration(audio_path)
    target_dur = audio_dur + 0.40

    create_broadcast_overlay(segment["headline"], segment["source_badge"], overlay_path, is_new_story=is_trans)

    # 4 dynamic visual cuts per scene (~6 seconds per cut) for high viewer retention!
    scene_queries = list(segment["queries"])
    while len(scene_queries) < 4:
        scene_queries.append(random.choice(FALLBACK_VIDEO_QUERIES))

    raw_files = []
    for q_idx, q in enumerate(scene_queries[:4]):
        raw_path = f"temp/raw_{idx}_{q_idx}.mp4"
        if download_strict_video(q, raw_path):
            raw_files.append(raw_path)

    slot_dur = target_dur / max(len(raw_files), 1)
    slot_clips = []

    for r_idx, r_path in enumerate(raw_files):
        slot_out = f"temp/slot_{idx}_{r_idx}.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-stream_loop", "-1", "-i", r_path,
            "-t", f"{slot_dur:.2f}",
            "-vf", "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,setsar=1,fps=24,format=yuv420p",
            "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
            slot_out
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        slot_clips.append(slot_out)

    concat_slots_txt = f"temp/slots_{idx}.txt"
    with open(concat_slots_txt, "w") as f:
        for sc in slot_clips:
            f.write(f"file '{os.path.abspath(sc)}'\n")

    bg_joined = f"temp/bg_{idx}.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_slots_txt, "-c", "copy", bg_joined
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    fade_in_dur = 0.80 if is_trans else 0.20
    fade_out_start = max(0.1, target_dur - 0.30)
    filter_chain = (
        f"[0:v][1:v]overlay=0:0,"
        f"fade=t=in:st=0:d={fade_in_dur},"
        f"fade=t=out:st={fade_out_start:.2f}:d=0.30[v]"
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

# ==================== 9. SAVE READY YOUTUBE DETAILS WITH SOURCES ====================
def format_time(seconds):
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"

def save_youtube_package(meta_data, chapters, articles):
    tags_str = ", ".join(meta_data.get("youtube_tags", ["medical breakthroughs", "health science", "medicine"]))
    chapters_str = "\n".join(chapters)
    sources_list = "\n".join([f"• Breakthrough #{i+1} ({a['source']}): {a['title']}\n  {a['link']}" for i, a in enumerate(articles)])

    content = f"""====================================================================
🎬 READY-TO-COPY YOUTUBE PACKAGE (HIGH-RETENTION STORYTELLING)
====================================================================

📌 YOUTUBE TITLE (Copy & Paste):
{meta_data.get('youtube_title', '5 New Medical Breakthroughs Changing Human Health')}

--------------------------------------------------------------------
📝 YOUTUBE DESCRIPTION (Copy & Paste):
{meta_data.get('youtube_description', '')}

⏱️ VIDEO CHAPTERS:
{chapters_str}

🔬 VERIFIED SCIENTIFIC SOURCES & STUDIES IN THIS EPISODE:
{sources_list}

⚠️ Medical Disclaimer:
The information provided in this video is for educational and informational purposes only and is not intended as a substitute for professional medical advice, diagnosis, or treatment. Always seek the advice of your physician or other qualified health provider with any questions you may have regarding a medical condition.

--------------------------------------------------------------------
🏷️ YOUTUBE TAGS (Copy & Paste):
{tags_str}
====================================================================
"""
    with open("youtube_details.txt", "w", encoding="utf-8") as f:
        f.write(content)

# ==================== MAIN EXECUTION ====================
if __name__ == "__main__":
    articles = fetch_viral_medical_news(5)
    meta_data, segments = build_storytelling_script(articles)

    segment_files = []
    current_time = 0.0
    chapters = ["00:00 Cold Open: Today's Biggest Medical Mystery"]

    for i, seg in enumerate(segments):
        if i in [1, 5, 9, 13, 17]:
            s_num = ((i - 1) // 4) + 1
            art = articles[s_num - 1]
            chapters.append(f"{format_time(current_time)} Breakthrough #{s_num}: {seg['headline'].title()} ({art['source']})")

        print(f"Rendering Fast-Paced Storytelling Scene {i+1}/{len(segments)}...")
        seg_file, seg_dur = render_scene(i, seg)
        segment_files.append(seg_file)
        current_time += seg_dur

    with open("temp/concat_list.txt", "w") as f:
        for sf in segment_files:
            f.write(f"file '{os.path.abspath(sf)}'\n")

    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", "temp/concat_list.txt", "-c", "copy", "-movflags", "+faststart", "final_video.mp4"
    ], check=True)

    save_youtube_package(meta_data, chapters, articles)
    print(f"SUCCESS! High-Retention Compressed HD Video Ready: final_video.mp4 ({format_time(current_time)})")
