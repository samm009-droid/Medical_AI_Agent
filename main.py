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
import math
import wave
import struct
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
USED_VIDEOS_FILE = "used_videos.txt"  # Permanent memory so video clips NEVER repeat across episodes!

RSS_FEEDS = [
    ("ScienceDaily Health", "https://www.sciencedaily.com/rss/health_medicine.xml"),
    ("MedicalXpress", "https://medicalxpress.com/rss-feed/"),
    ("ScienceDaily Mind & Brain", "https://www.sciencedaily.com/rss/mind_brain.xml"),
    ("ScienceDaily Living Well", "https://www.sciencedaily.com/rss/living_well.xml"),
    ("EurekAlert Medicine", "https://www.eurekalert.org/rss/medicine_health.xml"),
    ("News-Medical", "https://www.news-medical.net/tag/feed/Medical-Research.aspx")
]

# Massive diverse fallback pool to prevent visual repetition
FALLBACK_VIDEO_QUERIES = [
    "red blood cells animation", "human brain neurons glowing", "scientist pipette test tube",
    "mri scanner hospital room", "heartbeat monitor screen", "dna strand rotation",
    "surgeon adjusting operating light", "microscope lens close up", "woman sleeping peacefully night",
    "man jogging morning park", "pouring cup of coffee morning", "fresh vegetables healthy meal",
    "pharmacist counting medicine pills", "senior couple walking nature", "doctor tablet xray scan",
    "chemist analyzing blue liquid", "human eye pupil close up", "woman drinking glass water",
    "medical robot surgery technology", "stretching yoga morning sunlight", "hands holding medicine capsule",
    "stethoscope on hospital desk", "blood pressure cuff patient", "brain waves monitor neurology",
    "immune system cells animation", "laboratory centrifuge spinning", "person waking up alarm clock",
    "healthy heart animation", "scientist typing computer lab", "hospital corridor modern"
]

# Professional TV Broadcast xfade transitions
XFADE_TRANSITIONS = [
    "smoothleft", "smoothright", "wipeleft", "wiperight",
    "slideleft", "slideright", "circleopen", "dissolve", "radial"
]

os.makedirs("temp", exist_ok=True)
http_session = requests.Session()

# ==================== 2. PERMANENT VISUAL & NEWS MEMORY ====================
def load_set_from_file(filepath):
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def append_to_file(filepath, items):
    with open(filepath, "a", encoding="utf-8") as f:
        for item in items:
            f.write(str(item).strip() + "\n")

used_pexels_ids = load_set_from_file(USED_VIDEOS_FILE)
newly_used_pexels_ids = []
print(f"Loaded {len(used_pexels_ids)} previously used video IDs from permanent memory (Zero Repetition Active).")

# ==================== 3. SMART AI MODEL DETECTOR ====================
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

# ==================== 4. VIRAL MEDICAL NEWS FILTER ====================
def fetch_viral_medical_news(count=5):
    print("Scanning global feeds for candidate medical breakthroughs...")
    used_titles = {t.lower() for t in load_set_from_file(USED_NEWS_FILE)}
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
        append_to_file(USED_NEWS_FILE, [a["title"] for a in selected])
        return selected

    numbered_list = "\n".join([f"{i}: {a['title']} — {a['summary'][:180]}" for i, a in enumerate(pool)])
    selector_prompt = f"""
    You are a viral YouTube Medical Documentary Producer.
    Below are {len(pool)} newly published medical & health news articles:
    {numbered_list}

    Select the 5 MOST FASCINATING, SHOCKING, AND HUMAN-RELEVANT stories for US and European viewers (prioritize: sleep, brain/memory, heart health, longevity/aging, common medications, everyday foods/drinks, cancer breakthroughs, gut health, or surprising body secrets).
    Order them from #1 (Most Mind-Blowing Hook Story) to #5.
    Return ONLY valid JSON:
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
    except Exception:
        selected = pool[:count]

    append_to_file(USED_NEWS_FILE, [a["title"] for a in selected])
    return selected

# ==================== 5. STORYTELLING SCRIPT WITH DIVERSE VISUAL QUERIES ====================
def build_storytelling_script(articles):
    print("Crafting High-Retention Storytelling Script with Unique Visual Scenes...")
    segments = []
    titles_list = "\n".join([f"Story #{i+1}: {a['title']} (Source: {a['source']})" for i, a in enumerate(articles)])

    intro_prompt = f"""
    You are a charismatic, million-subscriber American YouTube medical storyteller.
    Today's 5 real-time medical breakthroughs are:
    {titles_list}
    Lead Story Summary: {articles[0]['summary']}

    Write a high-retention 135-word "Cold-Open Hook & Intro":
    - Start Sentence #1 by addressing the viewer directly ("You") with a mind-blowing question, everyday habit, or shocking scenario from Story #1 that grabs attention in the first 5 seconds!
    - Then tease how today's new medical discoveries are changing what we know about the human body, and preview the 5 breakthroughs.
    - Provide 4 specific, visually distinct Pexels video search queries (AVOID generic "doctor hospital" — use vivid visuals like "pouring morning coffee", "human eye macro", "glowing brain neurons", "person running sunrise").

    Return ONLY valid JSON:
    {{
      "youtube_title": "Curiosity-driven viral medical YouTube title under 85 chars",
      "youtube_description": "Engaging SEO description...",
      "youtube_tags": ["medical breakthroughs", "health news", "human body"],
      "intro_narration": "135 words spoken conversational storytelling only...",
      "visual_queries": ["specific visual 1", "specific visual 2", "specific visual 3", "specific visual 4"]
    }}
    """
    meta_data = clean_json_response(ask_gemini(intro_prompt))
    segments.append({
        "story_number": 0,
        "source_badge": "BREAKING HEALTH SCIENCE  |  VERIFIED RESEARCH",
        "headline": meta_data.get("youtube_title", "5 NEW DISCOVERIES CHANGING HUMAN HEALTH").upper()[:62],
        "narration": meta_data["intro_narration"],
        "queries": meta_data.get("visual_queries", ["human brain neurons", "dna strand rotation", "heartbeat monitor", "morning sunlight nature"])
    })
    time.sleep(4)

    for idx, article in enumerate(articles):
        next_story_title = articles[idx + 1]["title"] if idx + 1 < len(articles) else "our final health takeaway"
        print(f"Writing Storytelling Acts for Breakthrough {idx+1}/5...")

        story_prompt = f"""
        You are an elite American YouTube medical storyteller (like Institute of Human Anatomy & Veritasium).
        Transform this brand-new scientific study into a gripping, conversational story:

        Study Title: {article['title']}
        Scientific Source: {article['source']}
        Study Details: {article['summary']}
        Next Story After This One: {next_story_title}

        STORYTELLING RULES:
        - Speak directly to the viewer ("you", "your body", "your brain").
        - Explain complex medical mechanisms using vivid everyday analogies.
        - Naturally cite the scientific source ("Researchers featured in {article['source']}" or the university).

        Divide this story into EXACTLY 4 acts (90 to 100 words per act):
        - Act 1 (Relatable Mystery & Discovery)
        - Act 2 (Inside Your Body - The Simple Analogy)
        - Act 3 (The Plot Twist & Clinical Proof)
        - Act 4 (Practical Takeaway For YOU + Suspenseful Cliffhanger teasing "{next_story_title}")

        ANTI-REPETITION VISUAL RULE (CRITICAL):
        For EACH act, provide 4 HIGHLY SPECIFIC, DIVERSE physical stock-video search queries (2 to 3 English words each).
        DO NOT repeat generic phrases like "doctor patient" or "scientist microscope". Instead, describe specific human actions, organs, foods, symptoms, nature, or daily life matching the narration (e.g., "woman headache temple", "red blood cells", "coffee cup steam", "man sleeping bed", "pills blister pack", "senior man smiling", "heart monitor screen", "dna helix glowing", "gut bacteria animation", "person walking forest").
        Every single query across all 4 acts MUST be completely different!

        Return ONLY valid JSON:
        {{
          "curiosity_headline": "INTRIGUING 6-TO-9 WORD HEADLINE UNDER 58 CHARS",
          "acts": [
            {{
              "narration": "90-100 words conversational spoken narration...",
              "visual_queries": ["unique query 1", "unique query 2", "unique query 3", "unique query 4"]
            }},
            {{
              "narration": "90-100 words conversational spoken narration...",
              "visual_queries": ["unique query 5", "unique query 6", "unique query 7", "unique query 8"]
            }},
            {{
              "narration": "90-100 words conversational spoken narration...",
              "visual_queries": ["unique query 9", "unique query 10", "unique query 11", "unique query 12"]
            }},
            {{
              "narration": "90-100 words conversational spoken narration...",
              "visual_queries": ["unique query 13", "unique query 14", "unique query 15", "unique query 16"]
            }}
          ]
        }}
        """
        story_data = clean_json_response(ask_gemini(story_prompt))
        headline = story_data.get("curiosity_headline", article["title"][:58]).upper()

        for a_idx, act in enumerate(story_data["acts"]):
            segments.append({
                "story_number": (idx + 1) if a_idx == 0 else 0,  # Triggers Dedicated TV Transition Bumper before Act 1!
                "story_source": article["source"].upper(),
                "source_badge": f"BREAKTHROUGH #{idx+1}  |  SOURCE: {article['source'].upper()}",
                "headline": headline,
                "narration": act["narration"],
                "queries": act.get("visual_queries", random.sample(FALLBACK_VIDEO_QUERIES, 4))
            })
        time.sleep(4)

    outro_prompt = """
    Write an energetic, inspiring 95-word YouTube conclusion for a medical storytelling episode.
    Ask viewers which of today's 5 breakthroughs surprised them most in the comments, remind them that all verified scientific sources are linked in the description and that this content is educational, and invite them to subscribe.
    Return ONLY valid JSON:
    {
      "outro_narration": "95 words spoken English conclusion only...",
      "visual_queries": ["happy healthy family", "sunrise jogging park", "modern hospital exterior", "smiling doctor stethoscope"]
    }
    """
    outro_data = clean_json_response(ask_gemini(outro_prompt))
    segments.append({
        "story_number": 0,
        "source_badge": "VERIFIED SCIENTIFIC LINKS IN DESCRIPTION",
        "headline": "WHICH BREAKTHROUGH SURPRISED YOU MOST? COMMENT BELOW!",
        "narration": outro_data["outro_narration"],
        "queries": outro_data.get("visual_queries", random.sample(FALLBACK_VIDEO_QUERIES, 4))
    })

    return meta_data, segments

# ==================== 6. AUDIO & BROADCAST CHIME GENERATOR ====================
async def _generate_tts(text, output_file):
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

def generate_broadcast_transition_sound(wav_path, duration=2.4):
    """Synthesizes a sleek, BBC/Vox-style warm harmonic broadcast transition chime + soft whoosh."""
    sample_rate = 44100
    n_samples = int(sample_rate * duration)
    # Warm futuristic C-Major-9 chord frequencies (C4, E4, G4, B4, D5)
    freqs = [261.63, 329.63, 392.00, 493.88, 587.33]

    with wave.open(wav_path, "w") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)

        frames = bytearray()
        for i in range(n_samples):
            t = i / sample_rate
            # Smooth attack and exponential decay envelope
            attack = min(1.0, t / 0.18)
            decay = math.exp(-2.2 * t)
            env = attack * decay * 0.22

            val = 0.0
            for idx, f in enumerate(freqs):
                # Slight arpeggio delay per note for a luxury TV network feel
                note_delay = idx * 0.06
                if t >= note_delay:
                    nt = t - note_delay
                    n_env = min(1.0, nt / 0.10) * math.exp(-2.4 * nt)
                    val += math.sin(2.0 * math.pi * f * nt) * n_env

            sample = max(-0.95, min(0.95, (val / len(freqs)) * env * 3.5))
            pcm = int(sample * 32767)
            frames.extend(struct.pack("<hh", pcm, pcm))
        wf.writeframes(frames)

def get_media_duration(file_path):
    res = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", file_path
    ], capture_output=True, text=True)
    try:
        return float(res.stdout.strip())
    except Exception:
        return 10.0

# ==================== 7. DEEP MULTI-PAGE PEXELS DOWNLOADER (ZERO REPETITION) ====================
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
    attempts = [(query, 1), (query, random.randint(2, 4))]
    if len(words) > 2:
        attempts.append((" ".join(words[:2]), random.randint(1, 3)))
    for fb in random.sample(FALLBACK_VIDEO_QUERIES, 5):
        attempts.append((fb, random.randint(1, 4)))

    for q, page_num in attempts:
        url = f"https://api.pexels.com/videos/search?query={urllib.parse.quote(q)}&orientation=landscape&size=medium&per_page=35&page={page_num}"
        try:
            r = http_session.get(url, headers=headers, timeout=15)
            if r.status_code == 200:
                all_vids = r.json().get("videos", [])
                fresh_vids = [v for v in all_vids if str(v.get("id")) not in used_pexels_ids]
                # Sort by relevance, then shuffle among the top 6 matches for visual variety
                fresh_vids.sort(key=lambda v: score_video_relevance(v, q), reverse=True)
                top_pool = fresh_vids[:6]
                random.shuffle(top_pool)
                candidates = top_pool + fresh_vids[6:]

                for v in candidates:
                    vid_id = str(v.get("id"))
                    for vf in v.get("video_files", []):
                        w = vf.get("width", 0)
                        if 1280 <= w <= 1920 and vf.get("link"):
                            vid_resp = http_session.get(vf["link"], timeout=30)
                            if vid_resp.status_code == 200 and len(vid_resp.content) > 50000:
                                with open(dest_path, "wb") as f:
                                    f.write(vid_resp.content)
                                used_pexels_ids.add(vid_id)
                                newly_used_pexels_ids.append(vid_id)
                                return True
        except Exception as e:
            print(f"Video search note for '{q}': {e}")
    return False

# ==================== 8. TV GRAPHICS & CHAPTER TRANSITION BUMPERS ====================
def create_broadcast_overlay(headline, source_badge, output_png):
    img = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Top-right Sleek Badge
    draw.rectangle([985, 30, 1242, 68], fill=(12, 24, 48, 225))
    draw.rectangle([985, 30, 992, 68], fill=(0, 205, 245, 255))

    # Modern Lower-Third Overlay
    draw.rectangle([0, 604, 1280, 688], fill=(8, 18, 38, 235))
    draw.rectangle([0, 597, 1280, 604], fill=(0, 200, 240, 255))
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

def create_story_bumper_card(story_num, headline, source_name, output_png):
    """Creates a full-screen translucent TV Chapter Transition Bumper Card."""
    img = Image.new("RGBA", (1280, 720), (6, 14, 32, 205))
    draw = ImageDraw.Draw(img)

    # Sleek center glass frame & glowing accent bars
    draw.rectangle([140, 190, 1140, 530], fill=(10, 24, 52, 240))
    draw.rectangle([140, 190, 1140, 200], fill=(0, 210, 255, 255))
    draw.rectangle([140, 522, 1140, 530], fill=(230, 35, 55, 255))
    draw.rectangle([460, 235, 820, 285], fill=(220, 30, 50, 255))

    try:
        font_pill = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 33)
        font_sub = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 19)
    except Exception:
        font_pill = ImageFont.load_default()
        font_title = ImageFont.load_default()
        font_sub = ImageFont.load_default()

    draw.text((495, 247), f"BREAKTHROUGH #{story_num} OF 5", fill=(255, 255, 255, 255), font=font_pill)

    # Split headline into 2 balanced centered lines if needed
    words = headline.split()
    mid = max(1, len(words) // 2)
    line1 = " ".join(words[:mid])
    line2 = " ".join(words[mid:])

    draw.text((200, 330), line1[:45], fill=(255, 255, 255, 255), font=font_title)
    if line2:
        draw.text((200, 380), line2[:45], fill=(0, 215, 255, 255), font=font_title)

    draw.text((200, 465), f"VERIFIED SOURCE: {source_name}", fill=(190, 215, 240, 255), font=font_sub)
    img.save(output_png)

def render_story_transition_bumper(story_num, segment):
    """Renders a 2.4-second kinematic TV Chapter Transition Clip with harmonic chime."""
    bumper_png = f"temp/bumper_{story_num}.png"
    bumper_wav = f"temp/bumper_{story_num}.wav"
    bumper_raw = f"temp/bumper_raw_{story_num}.mp4"
    bumper_out = f"temp/bumper_out_{story_num}.mp4"
    dur = 2.4

    create_story_bumper_card(story_num, segment["headline"], segment.get("story_source", "MEDICAL RESEARCH"), bumper_png)
    generate_broadcast_transition_sound(bumper_wav, duration=dur)

    q = segment["queries"][0] if segment.get("queries") else "medical technology"
    download_strict_video(q, bumper_raw)

    filter_chain = (
        f"[0:v]scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,setsar=1,fps=24,format=yuv420p[bg];"
        f"[bg][1:v]overlay=0:0,"
        f"fade=t=in:st=0:d=0.45,"
        f"fade=t=out:st=1.90:d=0.50[v]"
    )

    subprocess.run([
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", bumper_raw,
        "-i", bumper_png,
        "-i", bumper_wav,
        "-filter_complex", filter_chain,
        "-map", "[v]", "-map", "2:a",
        "-t", f"{dur:.2f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
        "-maxrate", "950k", "-bufsize", "1900k", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "96k", "-ar", "44100", "-ac", "2",
        bumper_out
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    return bumper_out, dur

# ==================== 9. KINEMATIC XFADE SCENE RENDERER ====================
def render_scene(idx, segment):
    audio_path = f"temp/audio_{idx}.mp3"
    overlay_path = f"temp/overlay_{idx}.png"
    out_segment = f"temp/seg_{idx:03d}.mp4"

    create_voiceover(segment["narration"], audio_path)
    audio_dur = get_media_duration(audio_path)
    target_dur = audio_dur + 0.40

    create_broadcast_overlay(segment["headline"], segment["source_badge"], overlay_path)

    scene_queries = list(segment["queries"])
    while len(scene_queries) < 4:
        scene_queries.append(random.choice(FALLBACK_VIDEO_QUERIES))

    raw_files = []
    for q_idx, q in enumerate(scene_queries[:4]):
        raw_path = f"temp/raw_{idx}_{q_idx}.mp4"
        if download_strict_video(q, raw_path):
            raw_files.append(raw_path)

    # Ensure exactly 4 clips for smooth 4-shot xfade choreography
    while len(raw_files) < 4 and raw_files:
        raw_files.append(raw_files[-1])

    xfade_dur = 0.65
    num_clips = 4
    # Exact clip duration so that after 3 overlapping xfade transitions, total duration == target_dur
    clip_dur = (target_dur + (num_clips - 1) * xfade_dur) / num_clips

    slot_clips = []
    for r_idx, r_path in enumerate(raw_files[:4]):
        slot_out = f"temp/slot_{idx}_{r_idx}.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-stream_loop", "-1", "-i", r_path,
            "-t", f"{clip_dur:.2f}",
            "-vf", "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,setsar=1,fps=24,format=yuv420p",
            "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "25",
            slot_out
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        slot_clips.append(slot_out)

    # Pick 3 distinct broadcast xfade transitions for this scene
    t1, t2, t3 = random.sample(XFADE_TRANSITIONS, 3)
    off1 = clip_dur - xfade_dur
    off2 = 2 * clip_dur - 2 * xfade_dur
    off3 = 3 * clip_dur - 3 * xfade_dur

    fade_out_start = max(0.1, target_dur - 0.35)

    filter_complex = (
        f"[0:v][1:v]xfade=transition={t1}:duration={xfade_dur}:offset={off1:.2f}[v01];"
        f"[v01][2:v]xfade=transition={t2}:duration={xfade_dur}:offset={off2:.2f}[v02];"
        f"[v02][3:v]xfade=transition={t3}:duration={xfade_dur}:offset={off3:.2f}[bg];"
        f"[bg][4:v]overlay=0:0,"
        f"fade=t=in:st=0:d=0.30,"
        f"fade=t=out:st={fade_out_start:.2f}:d=0.35[v]"
    )

    subprocess.run([
        "ffmpeg", "-y",
        "-i", slot_clips[0],
        "-i", slot_clips[1],
        "-i", slot_clips[2],
        "-i", slot_clips[3],
        "-i", overlay_path,
        "-i", audio_path,
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "5:a",
        "-t", f"{target_dur:.2f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "27",
        "-maxrate", "950k", "-bufsize", "1900k", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "96k", "-ar", "44100", "-ac", "2",
        out_segment
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    return out_segment, target_dur

# ==================== 10. SAVE YOUTUBE PACKAGE & VISUAL MEMORY ====================
def format_time(seconds):
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"

def save_youtube_package(meta_data, chapters, articles):
    tags_str = ", ".join(meta_data.get("youtube_tags", ["medical breakthroughs", "health science", "medicine"]))
    chapters_str = "\n".join(chapters)
    sources_list = "\n".join([f"• Breakthrough #{i+1} ({a['source']}): {a['title']}\n  {a['link']}" for i, a in enumerate(articles)])

    content = f"""====================================================================
🎬 READY-TO-COPY YOUTUBE PACKAGE (PRO BROADCAST TRANSITIONS)
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
        story_num = seg.get("story_number", 0)
        if story_num > 0:
            art = articles[story_num - 1]
            chapters.append(f"{format_time(current_time)} Breakthrough #{story_num}: {seg['headline'].title()} ({art['source']})")
            print(f"Rendering TV Broadcast Transition Bumper for Breakthrough #{story_num}...")
            bumper_file, bumper_dur = render_story_transition_bumper(story_num, seg)
            segment_files.append(bumper_file)
            current_time += bumper_dur

        print(f"Rendering Scene {i+1}/{len(segments)} with Kinematic xfade Transitions...")
        seg_file, seg_dur = render_scene(i, seg)
        segment_files.append(seg_file)
        current_time += seg_dur

    # Save all newly used Pexels video IDs to permanent memory file
    if newly_used_pexels_ids:
        append_to_file(USED_VIDEOS_FILE, newly_used_pexels_ids)
        print(f"Saved {len(newly_used_pexels_ids)} new video IDs to {USED_VIDEOS_FILE} so they never repeat!")

    with open("temp/concat_list.txt", "w") as f:
        for sf in segment_files:
            f.write(f"file '{os.path.abspath(sf)}'\n")

    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", "temp/concat_list.txt", "-c", "copy", "-movflags", "+faststart", "final_video.mp4"
    ], check=True)

    save_youtube_package(meta_data, chapters, articles)
    print(f"SUCCESS! Pro-Transition Compressed HD Video Ready: final_video.mp4 ({format_time(current_time)})")
