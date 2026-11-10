import os
import re
import json
import time
import random
import asyncio
import subprocess
import urllib.parse
import feedparser
import requests
import edge_tts
import google.generativeai as genai
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (
    VideoFileClip, AudioFileClip, ImageClip,
    CompositeVideoClip, concatenate_videoclips, ColorClip
)

# ==================== 1. CONFIGURATION ====================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")
VOICE_NAME = "en-US-ChristopherNeural"  # Constant Professional American Documentary Host
USED_NEWS_FILE = "used_news.txt"

# Top Global Medical & Health Breakthrough Sources
RSS_FEEDS = [
    "https://www.sciencedaily.com/rss/health_medicine.xml",
    "https://medicalxpress.com/rss-feed/",
    "https://www.sciencedaily.com/rss/mind_brain.xml",
    "https://www.eurekalert.org/rss/medicine_health.xml",
    "https://www.news-medical.net/tag/feed/Medical-Research.aspx"
]

FALLBACK_MEDICAL_QUERIES = [
    "scientist looking through microscope", "medical research laboratory",
    "doctor examining patient hospital", "dna double helix animation",
    "pharmaceutical medicine pills", "brain mri scan doctor",
    "surgeon operating room hospital", "heart monitor cardiology"
]

os.makedirs("temp", exist_ok=True)
used_pexels_ids = set()

# ==================== 2. AI MODEL SETUP ====================
genai.configure(api_key=GEMINI_API_KEY)

def ask_gemini(prompt):
    models_to_try = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    for model_name in models_to_try:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            if response and response.text:
                return response.text.strip()
        except Exception as e:
            print(f"Model {model_name} attempt note: {e}")
            time.sleep(3)
    raise Exception("Failed to get response from Gemini API.")

def clean_json_response(text):
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        return json.loads(text[start:end+1])
    raise ValueError("Invalid JSON format from AI")

# ==================== 3. FETCH FRESH MEDICAL NEWS (NO DUPLICATES) ====================
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
    print("Fetching fresh medical breakthroughs from global sources...")
    used_titles = load_used_titles()
    articles = []
    seen_now = set()

    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:15]:
                title = entry.get("title", "").strip()
                summary = re.sub(r"<[^>]+>", "", entry.get("summary", "")).strip()
                t_lower = title.lower()
                if title and len(summary) > 50 and t_lower not in used_titles and t_lower not in seen_now:
                    seen_now.add(t_lower)
                    articles.append({"title": title, "summary": summary[:900]})
        except Exception as e:
            print(f"RSS error ({url}): {e}")

    # If all recent news were somehow used, fallback to ignoring history
    if len(articles) < count:
        for url in RSS_FEEDS:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
                title = entry.get("title", "").strip()
                summary = re.sub(r"<[^>]+>", "", entry.get("summary", "")).strip()
                if title and title.lower() not in seen_now:
                    seen_now.add(title.lower())
                    articles.append({"title": title, "summary": summary[:900]})

    selected = articles[:count]
    save_used_titles([a["title"] for a in selected])
    return selected

# ==================== 4. SCENE-BY-SCENE SCRIPT & VISUAL SYNC ====================
def build_full_script(articles):
    print("Building 10-15 minute script with scene-by-scene visual matching...")
    segments = []
    titles_list = "\n".join([f"{i+1}. {a['title']}" for i, a in enumerate(articles)])

    # A. Intro & US/EU SEO Metadata
    intro_prompt = f"""
    You are an elite American medical documentary narrator for a top US/European YouTube channel.
    Write a captivating 130-word introduction for today's medical news episode covering these 5 breakthroughs:
    {titles_list}

    Also generate:
    - A high-CTR YouTube Title tailored for US & European audiences (under 90 chars).
    - A comprehensive YouTube Description summarizing all 5 stories.
    - 12 high-ranking English medical SEO tags.
    - 3 exact visual search queries matching the beginning, middle, and end of the intro narration.

    Return ONLY valid JSON:
    {{
      "youtube_title": "Viral medical news title...",
      "youtube_description": "Full SEO description...",
      "youtube_tags": ["medical news", "health breakthrough", "new medicine"],
      "intro_narration": "130 words spoken narration only (no stage directions, no speaker labels)...",
      "visual_queries": ["doctor medical technology", "scientist laboratory microscope", "hospital health care"]
    }}
    """
    meta_data = clean_json_response(ask_gemini(intro_prompt))
    segments.append({
        "headline": "TODAY'S TOP 5 MEDICAL BREAKTHROUGHS",
        "narration": meta_data["intro_narration"],
        "queries": meta_data.get("visual_queries", ["medical technology", "scientist laboratory", "hospital doctor"])
    })
    time.sleep(4)

    # B. 5 Stories x 4 Visual Scenes each (~380 words per story -> ~2100 words total = 12-14 mins)
    for idx, article in enumerate(articles):
        print(f"Writing synchronized visual scenes for Story {idx+1}/5: {article['title'][:50]}...")
        story_prompt = f"""
        You are an elite American medical documentary producer. Write an in-depth, engaging report on this medical breakthrough:
        Title: {article['title']}
        Details: {article['summary']}

        Break this story into EXACTLY 4 chronological scenes (90 to 100 words per scene, total ~380 words):
        - Scene 1: The Breakthrough & Medical Condition (Start with "Story number {idx+1} brings major news regarding..." and explain the condition/problem and what scientists just discovered).
        - Scene 2: Inside the Body & Mechanism (Explain clearly how this treatment, drug, or biological mechanism works inside the human body or cells).
        - Scene 3: Clinical Study & Real Results (Detail the research experiments, patient outcomes, accuracy, or statistics discovered by the team).
        - Scene 4: Future Impact & Patient Takeaway (Explain when this could reach hospitals/pharmacies and what it means for global health in the US, Europe, and worldwide).

        CRITICAL VISUAL MATCHING RULE:
        For EACH scene, provide 3 concrete, physical stock-footage search queries (2 to 4 English words each) that chronologically match the exact objects, organs, symptoms, or actions spoken in the First third, Middle third, and Final third of that scene's narration!
        (Examples of great concrete queries: "brain mri scan", "pills pharmaceutical capsule", "senior man chest pain", "scientist pipette laboratory", "surgeon operating room", "blood sample test tube", "sleeping woman insomnia").

        Return ONLY valid JSON in this exact format:
        {{
          "banner_headline": "SHORT NEWS HEADLINE UNDER 62 CHARS",
          "scenes": [
            {{
              "narration": "90-100 words spoken narration only...",
              "visual_queries": ["exact visual 1", "exact visual 2", "exact visual 3"]
            }},
            {{
              "narration": "90-100 words spoken narration only...",
              "visual_queries": ["exact visual 1", "exact visual 2", "exact visual 3"]
            }},
            {{
              "narration": "90-100 words spoken narration only...",
              "visual_queries": ["exact visual 1", "exact visual 2", "exact visual 3"]
            }},
            {{
              "narration": "90-100 words spoken narration only...",
              "visual_queries": ["exact visual 1", "exact visual 2", "exact visual 3"]
            }}
          ]
        }}
        """
        story_data = clean_json_response(ask_gemini(story_prompt))
        headline = story_data.get("banner_headline", article["title"][:62]).upper()
        for scene in story_data["scenes"]:
            segments.append({
                "headline": f"STORY #{idx+1}: {headline}",
                "narration": scene["narration"],
                "queries": scene.get("visual_queries", ["medical research", "doctor patient", "laboratory"])
            })
        time.sleep(4)

    # C. Outro
    outro_prompt = """
    Write a professional 100-word conclusion for an American medical news documentary episode.
    Include a clear educational disclaimer (not personal medical advice) and invite viewers in the US, Europe, and around the world to subscribe and comment.
    Return ONLY valid JSON:
    {
      "outro_narration": "100 words spoken text only...",
      "visual_queries": ["doctor talking patient", "modern hospital building", "healthy active lifestyle"]
    }
    """
    outro_data = clean_json_response(ask_gemini(outro_prompt))
    segments.append({
        "headline": "THANK YOU FOR WATCHING - SUBSCRIBE FOR DAILY UPDATES",
        "narration": outro_data["outro_narration"],
        "queries": outro_data.get("visual_queries", ["doctor smiling", "healthy lifestyle"])
    })

    return meta_data, segments

# ==================== 5. VOICEOVER GENERATION ====================
async def _generate_tts(text, output_file):
    communicate = edge_tts.Communicate(text, VOICE_NAME, rate="-3%", pitch="-2Hz")
    await communicate.save(output_file)

def create_voiceover(text, output_file):
    clean_text = re.sub(r"[*#_~`]", "", text).strip()
    asyncio.run(_generate_tts(clean_text, output_file))

# ==================== 6. SMART VISUAL MATCHING & TV GRAPHICS ====================
def create_news_overlay(headline_text, output_png):
    img = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Top-right Broadcast Badge
    draw.rectangle([1010, 32, 1235, 72], fill=(185, 18, 28, 235))
    # Lower-Third Broadcast Banner
    draw.rectangle([0, 602, 1280, 685], fill=(8, 20, 42, 235))
    draw.rectangle([0, 595, 1280, 602], fill=(0, 195, 235, 255))
    draw.rectangle([40, 565, 365, 598], fill=(0, 135, 185, 255))

    try:
        font_badge = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
        font_main = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 25)
    except Exception:
        font_badge = ImageFont.load_default()
        font_main = ImageFont.load_default()

    draw.text((1028, 42), "MEDICAL REPORT", fill=(255, 255, 255, 255), font=font_badge)
    draw.text((55, 572), "GLOBAL HEALTH BREAKTHROUGH", fill=(255, 255, 255, 255), font=font_badge)
    draw.text((45, 628), headline_text[:72], fill=(255, 255, 255, 255), font=font_main)
    img.save(output_png)

def score_video_relevance(video_obj, query):
    """Scores Pexels video URL description against the exact spoken medical keywords."""
    slug = video_obj.get("url", "").lower()
    keywords = [w.lower() for w in re.findall(r"\w+", query) if len(w) > 2]
    score = sum(3 for kw in keywords if kw in slug)
    dur = video_obj.get("duration", 0)
    if 6 <= dur <= 25:
        score += 2
    return score

def download_matched_visual(query, dest_path):
    headers = {"Authorization": PEXELS_API_KEY}
    url = f"https://api.pexels.com/videos/search?query={urllib.parse.quote(query)}&orientation=landscape&size=medium&per_page=15"
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            videos = [v for v in r.json().get("videos", []) if v.get("id") not in used_pexels_ids]
            # Sort videos by highest relevance to the medical query
            videos.sort(key=lambda v: score_video_relevance(v, query), reverse=True)

            for v in videos:
                vid_id = v.get("id")
                for vf in v.get("video_files", []):
                    w = vf.get("width", 0)
                    if 1280 <= w <= 1920 and vf.get("link"):
                        vid_resp = requests.get(vf["link"], timeout=30)
                        if vid_resp.status_code == 200:
                            with open(dest_path, "wb") as f:
                                f.write(vid_resp.content)
                            used_pexels_ids.add(vid_id)
                            return "video"
    except Exception as e:
        print(f"Pexels video search note for '{query}': {e}")

    # Fallback to Pexels High-Res Photo if video for ultra-specific medical term wasn't found
    photo_url = f"https://api.pexels.com/v1/search?query={urllib.parse.quote(query)}&orientation=landscape&per_page=5"
    try:
        r = requests.get(photo_url, headers=headers, timeout=15)
        if r.status_code == 200:
            photos = [p for p in r.json().get("photos", []) if p.get("id") not in used_pexels_ids]
            for p in photos:
                img_link = p.get("src", {}).get("large2x") or p.get("src", {}).get("large")
                if img_link:
                    img_resp = requests.get(img_link, timeout=20)
                    if img_resp.status_code == 200:
                        img_path = dest_path.replace(".mp4", ".jpg")
                        with open(img_path, "wb") as f:
                            f.write(img_resp.content)
                        used_pexels_ids.add(p.get("id"))
                        return "photo"
    except Exception as e:
        print(f"Pexels photo search note for '{query}': {e}")

    return None

# ==================== 7. RENDER SYNCHRONIZED SCENE ====================
def render_segment_video(idx, segment):
    audio_path = f"temp/audio_{idx}.mp3"
    overlay_path = f"temp/overlay_{idx}.png"
    out_segment_path = f"temp/segment_{idx:03d}.mp4"

    create_voiceover(segment["narration"], audio_path)
    audio_clip = AudioFileClip(audio_path)
    target_duration = audio_clip.duration + 0.35

    create_news_overlay(segment["headline"], overlay_path)

    # Divide the scene duration evenly across its 3 chronological visual queries
    scene_queries = list(segment["queries"])
    while len(scene_queries) < 3:
        scene_queries.append(random.choice(FALLBACK_MEDICAL_QUERIES))

    slot_duration = target_duration / len(scene_queries)
    visual_clips = []

    for q_idx, q in enumerate(scene_queries):
        raw_base = f"temp/raw_{idx}_{q_idx}.mp4"
        media_type = download_matched_visual(q, raw_base)

        # If specific query failed, try a clean medical fallback
        if not media_type:
            media_type = download_matched_visual(random.choice(FALLBACK_MEDICAL_QUERIES), raw_base)

        try:
            if media_type == "video":
                vc = VideoFileClip(raw_base).without_audio().resize((1280, 720))
                if vc.duration >= slot_duration:
                    vc = vc.subclip(0, slot_duration)
                else:
                    # Loop seamlessly to fill the exact spoken slot
                    repeats = int(slot_duration // vc.duration) + 1
                    vc = concatenate_videoclips([vc] * repeats).subclip(0, slot_duration)
                visual_clips.append(vc)
            elif media_type == "photo":
                img_file = raw_base.replace(".mp4", ".jpg")
                im = Image.open(img_file).convert("RGB").resize((1280, 720))
                im.save(img_file)
                ic = ImageClip(img_file).set_duration(slot_duration)
                visual_clips.append(ic)
            else:
                visual_clips.append(ColorClip(size=(1280, 720), color=(12, 28, 52), duration=slot_duration))
        except Exception as e:
            print(f"Visual clip build note: {e}")
            visual_clips.append(ColorClip(size=(1280, 720), color=(12, 28, 52), duration=slot_duration))

    bg = concatenate_videoclips(visual_clips, method="compose").set_duration(target_duration)
    overlay_clip = ImageClip(overlay_path).set_duration(target_duration)
    final_seg = CompositeVideoClip([bg, overlay_clip]).set_audio(audio_clip)

    final_seg.write_videofile(
        out_segment_path,
        fps=24,
        codec="libx264",
        audio_codec="aac",
        preset="ultrafast",
        threads=2,
        ffmpeg_params=["-pix_fmt", "yuv420p", "-ar", "44100", "-ac", "2"],
        logger=None
    )

    final_seg.close()
    audio_clip.close()
    for c in visual_clips:
        c.close()

    return out_segment_path, target_duration

# ==================== 8. SAVE READY-TO-COPY YOUTUBE DETAILS ====================
def save_youtube_package(meta_data, story_timestamps, articles):
    tags_str = ", ".join(meta_data.get("youtube_tags", ["medical news", "health", "medicine"]))
    chapters_str = "\n".join(story_timestamps)

    content = f"""====================================================================
🎬 READY-TO-COPY YOUTUBE DETAILS (TARGETED FOR US & EUROPE)
====================================================================

📌 YOUTUBE TITLE (Copy & Paste):
{meta_data.get('youtube_title', 'Latest Medical Breakthroughs & Health Science News')}

--------------------------------------------------------------------
📝 YOUTUBE DESCRIPTION (Copy & Paste):
{meta_data.get('youtube_description', '')}

⏱️ VIDEO CHAPTERS:
{chapters_str}

⚠️ Medical Disclaimer:
The information provided in this video is for educational and informational purposes only and is not intended as a substitute for professional medical advice, diagnosis, or treatment. Always seek the advice of your physician or other qualified health provider with any questions you may have regarding a medical condition.

--------------------------------------------------------------------
🏷️ YOUTUBE TAGS (Copy & Paste):
{tags_str}
====================================================================
"""
    with open("youtube_details.txt", "w", encoding="utf-8") as f:
        f.write(content)
    print("Saved youtube_details.txt for easy mobile copy-paste!")

def format_time(seconds):
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"

# ==================== MAIN EXECUTION ====================
if __name__ == "__main__":
    articles = fetch_top_medical_news(5)
    meta_data, segments = build_full_script(articles)

    segment_files = []
    current_time = 0.0
    story_timestamps = ["00:00 Introduction - Today's Medical Briefing"]

    for i, seg in enumerate(segments):
        # Record chapter timestamps at the start of each story (segments 1, 5, 9, 13, 17)
        if i in [1, 5, 9, 13, 17]:
            story_num = ((i - 1) // 4) + 1
            story_title = articles[story_num - 1]["title"][:65]
            story_timestamps.append(f"{format_time(current_time)} Story #{story_num}: {story_title}")

        print(f"Rendering synchronized scene {i+1}/{len(segments)}...")
        seg_file, seg_dur = render_segment_video(i, seg)
        segment_files.append(seg_file)
        current_time += seg_dur

    concat_list_path = "temp/concat_list.txt"
    with open(concat_list_path, "w") as f:
        for sf in segment_files:
            f.write(f"file '{os.path.abspath(sf)}'\n")

    print("Merging all scenes into final 10-15 minute HD video...")
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_list_path, "-c", "copy", "final_video.mp4"
    ], check=True)

    save_youtube_package(meta_data, story_timestamps, articles)
    print(f"SUCCESS! Final video duration: {format_time(current_time)} -> Saved as final_video.mp4")
