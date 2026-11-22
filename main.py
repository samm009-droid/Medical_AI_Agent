import os, re, json, math, time, random, asyncio, subprocess, urllib.parse
import requests, feedparser, edge_tts, numpy as np
from PIL import Image, ImageDraw, ImageFont
import PIL.Image

setattr(PIL.Image, "ANTIALIAS", getattr(PIL.Image, "LANCZOS", PIL.Image.BICUBIC))

import google.generativeai as genai
from moviepy.editor import (
    VideoFileClip, AudioFileClip, ImageClip, ColorClip,
    CompositeVideoClip, CompositeAudioClip, concatenate_videoclips
)
from moviepy.audio.AudioClip import AudioArrayClip, concatenate_audioclips

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "").strip()

W, H = 1280, 720
SHORT_W, SHORT_H = 720, 1280
FPS = 24

VOICE_NAME = "en-US-ChristopherNeural"
VOICE_RATE = "-7%"
VOICE_PITCH = "-2Hz"

USED_VIDEOS_FILE = "used_videos.txt"
USED_NEWS_FILE = "used_news.txt"
LOGO_PATH = "\u062a\u0646\u0632\u064a\u0644.jpeg"

os.makedirs("temp", exist_ok=True)
os.makedirs("output", exist_ok=True)

DR_BERG_CURATED_TOPICS = [
    {"title": "What Happens to Your Body When You Chew 1 Clove Daily for 7 Days", "symptom": "bloating, gum inflammation, sluggish digestion, and morning fatigue", "root": "eugenol oil activating digestive enzymes, lowering oral bacteria, and calming gut inflammation", "visual": "spices herbs healthy nutrition kitchen table"},
    {"title": "Why You Wake Up Between 2 AM and 3 AM Every Night (The Cortisol & Liver Secret)", "symptom": "sudden nighttime waking, racing thoughts, and unrefreshing sleep", "root": "late-night blood sugar drop triggering a cortisol spike and sluggish liver glycogen regulation", "visual": "person sleeping peacefully bedroom night rest"},
    {"title": "7 Warning Signs of a Fatty Liver That Show Up on Your Skin and Feet", "symptom": "right shoulder ache, red palms, cracked heels, and stubborn belly fat", "root": "congested bile ducts and visceral fat accumulation inside liver cells blocking detoxification", "visual": "doctor examining abdominal scan medical clinic"},
    {"title": "What Drinking Apple Cider Vinegar Before Bed Does to Your Blood Sugar", "symptom": "high morning fasting glucose, cravings after dinner, and slow metabolism", "root": "acetic acid improving insulin sensitivity in muscle cells and slowing stomach starch breakdown", "visual": "healthy drink glass lemon nutrition kitchen"},
    {"title": "Tingling and Numbness in Hands and Feet: The Hidden Vitamin Deficiency", "symptom": "pins and needles in toes, burning feet at night, and weak grip", "root": "myelin nerve sheath erosion from low Vitamin B1 (Benfotiamine) and Vitamin B12 absorption", "visual": "vitamin supplement capsules medicine bottle table"},
    {"title": "Why Taking Vitamin D3 Alone Can Be Dangerous Without Vitamin K2 and Magnesium", "symptom": "stiff joints, muscle cramps, and fatigue despite taking Vitamin D", "root": "unactivated vitamin D leaving calcium in soft arteries instead of directing it into bone matrix", "visual": "golden vitamin capsules healthy lifestyle sunlight"},
    {"title": "The #1 Mineral Deficiency Behind High Blood Pressure and Night Leg Cramps", "symptom": "throbbing pulse in ears, tight calves at night, and afternoon exhaustion", "root": "intracellular potassium and magnesium depletion stiffening arterial smooth muscle walls", "visual": "doctor checking patient blood pressure clinic"},
    {"title": "5 Silent Signs of Insulin Resistance Most People Ignore Until It Is Too Late", "symptom": "skin tags on neck, dark skin folds, afternoon sleepiness after meals, and belly fat", "root": "chronically elevated insulin locking fat inside cells and blocking cellular energy uptake", "visual": "patient checking blood sugar glucose meter"},
    {"title": "Why Your Stomach Bloats Immediately After Eating (It Is Not Too Much Acid)", "symptom": "tightness after meals, burping, heartburn, and undigested food sensation", "root": "low stomach acid failing to trigger the lower esophageal valve and pancreatic enzyme release", "visual": "healthy fresh vegetables gut health food"},
    {"title": "What Happens When You Drink Turmeric and Black Pepper Water Every Morning", "symptom": "morning joint stiffness, swollen fingers, and brain fog", "root": "curcumin enhanced by piperine downregulating inflammatory cytokines and supporting liver bile", "visual": "healthy herbal tea cup fresh ingredients"},
    {"title": "Cracked Heels, Brittle Nails, and Hair Thinning: What Your Body Is Begging For", "symptom": "dry split heels, vertical nail ridges, and outer eyebrow thinning", "root": "subclinical sluggish thyroid conversion, low trace minerals (zinc and selenium), and Vitamin B3", "visual": "healthy nutrition seeds nuts vitamins table"},
    {"title": "The Best Type of Magnesium for Deep Sleep, Anxiety, and Muscle Recovery", "symptom": "restless legs, difficulty falling asleep, and daytime tension", "root": "magnesium glycinate crossing the blood-brain barrier to calm excitatory NMDA receptors", "visual": "supplement capsules glass of water bedroom"},
    {"title": "How to Flush Uric Acid, Prevent Kidney Stones, and Protect Kidney Filtration", "symptom": "stiff big toe, lower back dull ache, and foamy or dark morning urine", "root": "fructose and purine overload acidifying urine while low citrate allows crystal formation", "visual": "fresh lemon water hydration healthy kidney"},
    {"title": "Cold Hands and Feet All the Time? The Hidden Thyroid and Iron Connection", "symptom": "icy fingers indoors, pale nail beds, and sluggish morning energy", "root": "impaired peripheral microcirculation from low ferritin stores and slow T4-to-T3 hormone conversion", "visual": "doctor consulting patient in modern clinic"},
    {"title": "What Happens to Your Body After 16 Hours of Intermittent Fasting (Autophagy)", "symptom": "stubborn weight plateau, brain fog, and sluggish cellular recovery", "root": "insulin dropping low enough to switch on cellular self-cleaning autophagy and growth hormone", "visual": "healthy lifestyle fitness clock nutrition"}
]

RSS_FEEDS = [
    "https://news.google.com/rss/search?q=vitamin+deficiency+OR+magnesium+OR+vitamin+D+symptoms+when:7d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=fatty+liver+OR+insulin+resistance+OR+blood+sugar+signs+when:7d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=gut+health+OR+bloating+OR+sleep+cortisol+natural+remedy+when:7d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=high+blood+pressure+OR+cholesterol+OR+kidney+health+diet+when:7d&hl=en-US&gl=US&ceid=US:en",
    "https://www.health.harvard.edu/blog/feed",
    "https://health.clevelandclinic.org/feed/",
    "https://www.medicalnewstoday.com/rss",
    "https://www.healthline.com/rss/health-news"
]

SECTION_ROLES = [
    "The Everyday Symptom & Surprising Root Cause",
    "3 Warning Signs Your Body Sends You",
    "The Hidden Mechanism Inside Your Body",
    "Daily Mistakes That Make It Worse",
    "The Step-by-Step Practical Home Protocol"
]

SAFE_MEDICAL_QUERIES = [
    "healthy fresh vegetables herbs and nutrition on table",
    "vitamin supplement capsules and glass of water",
    "doctor explaining medical chart to patient in clinic",
    "close up natural spices turmeric cloves lemon",
    "person sleeping peacefully in bedroom night rest",
    "doctor checking patient blood pressure in office",
    "scientist examining blood sample in laboratory",
    "healthy Mediterranean food preparation kitchen",
    "pharmacist organizing supplement bottles pharmacy",
    "active adult walking outdoors healthy lifestyle"
]

THUMBNAIL_PALETTES = [
    {"glow": "vibrant emerald green and warm gold", "accent": "bright yellow"},
    {"glow": "deep crimson red and clinical cyan", "accent": "crisp white"},
    {"glow": "warm amber orange and dark navy blue", "accent": "neon yellow"},
    {"glow": "royal teal and bright coral", "accent": "warm gold"}
]

def load_Circular_Logo(path, size=64):
    if not os.path.exists(path):
        return None
    try:
        img = Image.open(path).convert("RGBA").resize((size, size), PIL.Image.LANCZOS)
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
        out = Image.new("RGBA", (size + 8, size + 8), (0, 0, 0, 0))
        ImageDraw.Draw(out).ellipse((0, 0, size + 7, size + 7), fill=(0, 210, 255, 240), outline=(255, 255, 255, 240), width=2)
        out.paste(img, (4, 4), mask)
        return out
    except Exception:
        return None

LOGO_PIL = load_Circular_Logo(LOGO_PATH, size=64)
LOGO_SHORT_PIL = load_Circular_Logo(LOGO_PATH, size=54)

def load_font(size, bold=True):
    candidates = [
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()

def load_used_items(filepath, max_keep=500):
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()][-max_keep:]

def save_used_items(filepath, items, max_keep=500):
    with open(filepath, "w", encoding="utf-8") as f:
        for item in items[-max_keep:]:
            f.write(f"{item}\n")

def clean_text_for_tts(text):
    text = re.sub(r"[*_#`~>]", " ", str(text))
    return re.sub(r"\s+", " ", text).strip()

def select_dr_berg_trending_topic():
    print("Scanning live patient search trends & Dr. Berg symptom-to-root-cause matrix...")
    used_news = set(load_used_items(USED_NEWS_FILE))
    trend_words = {}
    headers = {"User-Agent": "Mozilla/5.0"}
    for url in RSS_FEEDS:
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                feed = feedparser.parse(r.content)
                for entry in feed.entries[:15]:
                    txt = (entry.get("title", "") + " " + entry.get("summary", "")).lower()
                    for w in re.findall(r"[a-z]{4,}", txt):
                        trend_words[w] = trend_words.get(w, 0) + 1
        except Exception:
            continue

    scored_topics = []
    for item in DR_BERG_CURATED_TOPICS:
        norm_key = re.sub(r"[^a-z0-9]", "", item["title"].lower())[:55]
        if norm_key in used_news:
            continue
        words = re.findall(r"[a-z]{4,}", (item["title"] + " " + item["symptom"] + " " + item["root"]).lower())
        score = sum(min(trend_words.get(w, 0), 8) for w in set(words)) + random.randint(1, 10)
        scored_topics.append((score, norm_key, item))

    if not scored_topics:
        chosen = random.choice(DR_BERG_CURATED_TOPICS)
        norm_key = f"cycle_{int(time.time())}"
    else:
        scored_topics.sort(key=lambda x: x[0], reverse=True)
        _, norm_key, chosen = scored_topics[0]

    chosen["norm_key"] = norm_key
    print(f"Selected #1 Dr. Berg Single-Topic Deep Dive: {chosen['title']}")
    return chosen

def get_thumbnail_spec(topic_title):
    t = topic_title.lower()
    if "clove" in t or "turmeric" in t or "vinegar" in t:
        return "DO THIS DAILY", "a hyper-detailed clinical kitchen table with natural herbs, a glowing glass tonic, and an anatomical digestive glow"
    if "liver" in t:
        return "FATTY LIVER SIGNS", "an anatomical 3D glowing liver illustration beside fresh lemon water and diagnostic markers"
    if "sleep" in t or "2 am" in t or "3 am" in t:
        return "WAKE UP AT 3 AM?", "a glowing digital bedside clock reading 3:00 AM with a calm metabolic hormone wave graphic"
    if "tingling" in t or "numbness" in t or "heels" in t:
        return "HIDDEN DEFICIENCY", "a glowing golden vitamin capsule illuminating microscopic nerve fibers in high contrast"
    if "vitamin d" in t or "magnesium" in t:
        return "NEVER TAKE ALONE", "three luminous translucent supplement capsules arranged in a golden triangle on a dark clinical desk"
    if "blood pressure" in t or "insulin" in t or "kidney" in t:
        return "THE ROOT CAUSE", "a high-contrast clinical blood pressure and metabolic monitor beside natural mineral-rich foods"
    return "BODY WARNING SIGNS", "a high-contrast clinical illustration of cellular repair and natural nutrients on a dark studio background"

def validate_and_repair_script(data, topic):
    if not isinstance(data, dict):
        data = {}
    hook_badge, visual_subj = get_thumbnail_spec(topic["title"])
    palette = random.choice(THUMBNAIL_PALETTES)

    titles = data.get("title_options", [])
    if not isinstance(titles, list) or len(titles) < 3:
        titles = [
            topic["title"],
            f"The Real Reason Behind {topic['symptom'].title()[:42]} (And How to Fix It)",
            f"Do This Every Day to Fix {topic['symptom'].title()[:38]} Naturally"
        ]
    data["title_options"] = [str(t).strip()[:92] for t in titles[:3]]

    data["thumbnail_prompt"] = (
        f"Hyper-realistic 8K YouTube thumbnail in Dr. Eric Berg style, 16:9 aspect ratio. "
        f"Main subject: {visual_subj}, ultra-sharp focus, dramatic lighting in {palette['glow']}. "
        f"Strictly NO brains or skulls. "
        f"Massive bold 3D typography on the left reading '{hook_badge}' in {palette['accent']} with deep black outline, clean high-CTR medical design."
    )

    raw_sections = data.get("sections", [])
    repaired_sections = []
    for idx in range(5):
        sec = raw_sections[idx] if idx < len(raw_sections) and isinstance(raw_sections[idx], dict) else {}
        sec_title = str(sec.get("section_title", SECTION_ROLES[idx])).strip()[:52]
        if len(sec_title) < 5:
            sec_title = SECTION_ROLES[idx]

        bullets = sec.get("board_bullets", [])
        if not isinstance(bullets, list) or len(bullets) < 3:
            bullets = [
                f"Key Factor 1: {topic['symptom'][:36].title()}",
                f"Key Factor 2: {topic['root'][:38].title()}",
                "Key Factor 3: Daily Cellular Balance & Recovery"
            ]
        bullets = [re.sub(r"\s+", " ", str(b)).strip()[:54] for b in bullets[:3]]

        flow_str = str(sec.get("mechanism_flow", "Root Trigger  ->  Cellular Shift  ->  Daily Relief")).strip()[:62]
        if "->" not in flow_str:
            flow_str = "Root Cause  ->  Body Mechanism  ->  Natural Fix"

        paragraphs = sec.get("paragraphs", [])
        if not isinstance(paragraphs, list) or len(paragraphs) < 3:
            paragraphs = [
                f"Let us look closely at step {idx + 1} regarding {topic['title']}. Many people experience {topic['symptom']} every single day without realizing what their body is trying to tell them. Think of this process like a simple lock and key inside your cells.",
                f"When we look beneath the surface symptom, the real driver is {topic['root']}. Once this balance shifts, your tissues cannot absorb nutrients or clear metabolic waste efficiently, which is why temporary quick fixes rarely solve the problem.",
                "By addressing this specific mechanism directly through simple daily timing and the right nutritional cofactors, you give your organs the exact raw materials they need to restore normal function naturally."
            ]

        clean_paras = []
        for p_idx in range(3):
            p_txt = clean_text_for_tts(paragraphs[p_idx] if p_idx < len(paragraphs) else paragraphs[-1])
            words = p_txt.split()
            if len(words) < 42:
                p_txt += f" Remember that consistent daily habits targeting {topic['root'][:45]} make the biggest difference in how quickly your energy and comfort recover."
            elif len(words) > 62:
                trimmed = " ".join(words[:62])
                dot = max(trimmed.rfind("."), trimmed.rfind("?"), trimmed.rfind("!"))
                p_txt = trimmed[:dot + 1] if dot > 120 else trimmed + "."
            clean_paras.append(p_txt)

        v_query = str(sec.get("visual_query", topic["visual"])).strip()
        if len(v_query) < 4:
            v_query = topic["visual"]

        repaired_sections.append({
            "section_num": idx + 1,
            "section_title": sec_title,
            "board_bullets": bullets,
            "mechanism_flow": flow_str,
            "paragraphs": clean_paras,
            "visual_query": v_query
        })

    data["sections"] = repaired_sections

    short_d = data.get("short_script", {})
    if not isinstance(short_d, dict):
        short_d = {}
    data["short_script"] = {
        "short_title": str(short_d.get("short_title", f"{hook_badge}: {data['title_options'][0][:45]} #Shorts")).strip(),
        "hook_banner": hook_badge,
        "takeaway_points": [
            str(short_d.get("point_1", f"1. Symptom: {topic['symptom'][:32].title()}"))[:44],
            str(short_d.get("point_2", f"2. Root Cause: {topic['root'][:30].title()}"))[:44],
            str(short_d.get("point_3", "3. Watch Full Step-by-Step Protocol Below"))[:44]
        ],
        "part1_hook": clean_text_for_tts(short_d.get("part1_hook", f"If you struggle with {topic['symptom']}, stop ignoring what your body is telling you.")),
        "part2_root": clean_text_for_tts(short_d.get("part2_root", f"The real root cause is rarely what you think. It comes down to {topic['root']}.")),
        "part3_action": clean_text_for_tts(short_d.get("part3_action", "Tap the related video link right below on MedPulse 5 for the complete step-by-step home protocol and exact daily timing.")),
        "visual_query": topic["visual"]
    }

    if not data.get("description"):
        data["description"] = f"In this episode on MedPulse 5, we break down {topic['title']} using simple physiology, root-cause analysis, and a practical daily protocol."
    if not data.get("tags"):
        data["tags"] = "Dr Berg style health, root cause medicine, natural remedies, vitamin deficiency signs, fatty liver, insulin resistance, magnesium benefits, MedPulse 5"
    return data

def generate_dr_berg_script(topic):
    prompt = f"""
You are an expert medical educator modeled after Dr. Eric Berg ('Dr. Berg').
Your specialty is taking ONE high-demand everyday health symptom, nutrient, or food secret and explaining its hidden root cause using simple analogies, numbered whiteboard points, and a practical home action plan.

SINGLE TOPIC FOR THIS EPISODE: {topic['title']}
COMMON SYMPTOMS EXPERIENCED BY VIEWER: {topic['symptom']}
CORE BIOLOGICAL MECHANISM: {topic['root']}

STRICT DR. BERG STYLE RULES:
1. ZERO FLUFF: Start Section 1 Paragraph 1 immediately with the viewer's symptom ('If you have ever noticed...', 'Have you ever wondered why...'). Do NOT use boring news anchor introductions.
2. SIMPLE ANALOGIES: Use vivid everyday analogies (like 'dish soap dissolving grease', 'a key in a rusted lock', or 'a clogged kitchen filter') to explain physiology simply.
3. CALM, DELIBERATE PACING: Write short, clear sentences that sound natural when spoken slowly and calmly by a teaching doctor.
4. STRUCTURE THE SINGLE TOPIC INTO 5 SEQUENTIAL SECTIONS:
   - Section 1: The Everyday Symptom & Surprising Root Cause
   - Section 2: 3 Warning Signs Your Body Sends You
   - Section 3: The Hidden Mechanism Inside Your Body
   - Section 4: Daily Mistakes That Make It Worse
   - Section 5: The Step-by-Step Practical Home Protocol (Exact food/nutrient forms, timing, and 7-day habit)
5. Each of the 5 sections MUST contain:
   - 'section_title': Short clear title (under 48 chars)
   - 'board_bullets': List of EXACTLY 3 concise whiteboard summary points (under 48 chars each) that will be drawn on the Dr. Berg Whiteboard Card.
   - 'mechanism_flow': A 3-step arrow chain using '->' (e.g. 'Low Bile Flow -> Trapped Toxins -> Right Shoulder Ache', under 58 chars).
   - 'paragraphs': List of EXACTLY 3 spoken paragraphs. Each paragraph MUST be 46 to 56 words (100% accurate English spelling).
   - 'visual_query': 4 to 6 word Pexels search query for calm background footage (e.g. '{topic['visual']}').

Return ONLY valid JSON:
{{
  "title_options": ["Title 1", "Title 2", "Title 3"],
  "sections": [
    {{
      "section_title": "The Everyday Symptom & Surprising Root Cause",
      "board_bullets": ["Point 1...", "Point 2...", "Point 3..."],
      "mechanism_flow": "Step A -> Step B -> Step C",
      "paragraphs": ["46-56 words...", "46-56 words...", "46-56 words..."],
      "visual_query": "{topic['visual']}"
    }}
  ],
  "short_script": {{
    "short_title": "Short title #Shorts",
    "point_1": "1. Key symptom...",
    "point_2": "2. Hidden root cause...",
    "point_3": "3. Daily natural fix...",
    "part1_hook": "20-26 words...",
    "part2_root": "24-30 words...",
    "part3_action": "20-25 words..."
  }},
  "description": "Full SEO description...",
  "tags": "comma, separated, tags"
}}
"""
    genai.configure(api_key=GEMINI_API_KEY)
    for model_name in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
        for attempt in range(2):
            try:
                print(f"Generating Dr. Berg Whiteboard Script via {model_name} (attempt {attempt + 1})...")
                model = genai.GenerativeModel(model_name)
                res = model.generate_content(prompt, generation_config={"temperature": 0.6})
                raw = (res.text or "").strip()
                raw = re.sub(r"^```(?:json)?", "", raw).strip()
                raw = re.sub(r"```$", "", raw).strip()
                s_i, e_i = raw.find("{"), raw.rfind("}")
                if s_i != -1 and e_i != -1:
                    raw = raw[s_i:e_i + 1]
                return validate_and_repair_script(json.loads(raw), topic)
            except Exception as e:
                print(f"Model {model_name} warning: {e}")
                time.sleep(2)
    return validate_and_repair_script({}, topic)

async def _edge_tts_save(text, filename, rate=VOICE_RATE):
    communicate = edge_tts.Communicate(text, VOICE_NAME, rate=rate, pitch=VOICE_PITCH)
    await communicate.save(filename)

def generate_tts(text, filename, rate=VOICE_RATE):
    clean = clean_text_for_tts(text)
    for attempt in range(4):
        try:
            asyncio.run(_edge_tts_save(clean, filename, rate=rate))
            if os.path.exists(filename) and os.path.getsize(filename) > 800:
                return True
        except Exception:
            time.sleep(2)
    return False

def make_silence_audio(duration=0.38, sr=44100):
    arr = np.zeros((int(sr * duration), 2), dtype=np.float32)
    return AudioArrayClip(arr, fps=sr).set_duration(duration)

def search_and_download_video(query, out_path, used_ids):
    headers = {"Authorization": PEXELS_API_KEY}
    clean_q = " ".join(re.findall(r"[a-zA-Z]+", str(query))[:5]) or "healthy nutrition"
    candidates = [clean_q, random.choice(SAFE_MEDICAL_QUERIES), "healthy food nutrition table"]
    for q in candidates:
        try:
            url = f"https://api.pexels.com/videos/search?query={urllib.parse.quote(q)}&per_page=15&orientation=landscape"
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                continue
            videos = r.json().get("videos", [])
            random.shuffle(videos)
            for v in videos:
                vid_id = str(v.get("id", ""))
                dur = v.get("duration", 0)
                if not vid_id or vid_id in used_ids or dur < 5 or dur > 90:
                    continue
                files = v.get("video_files", [])
                best = None
                for vf in files:
                    w_v, h_v = vf.get("width", 0) or 0, vf.get("height", 0) or 0
                    if vf.get("file_type") == "video/mp4" and w_v >= h_v and 480 <= h_v <= 1080:
                        best = vf
                        break
                if not best and files:
                    best = files[0]
                if best and best.get("link"):
                    vr = requests.get(best["link"], stream=True, timeout=25)
                    if vr.status_code == 200:
                        with open(out_path, "wb") as f:
                            for chunk in vr.iter_content(chunk_size=65536):
                                if chunk:
                                    f.write(chunk)
                        if os.path.exists(out_path) and os.path.getsize(out_path) > 50000:
                            used_ids.append(vid_id)
                            return True
        except Exception:
            continue
    return False

def normalize_clip_strict_aspect(in_path, out_path, target_w, target_h):
    vf = (
        f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
        f"crop={target_w}:{target_h}:(iw-{target_w})/2:(ih-{target_h})/2,"
        f"setsar=1:1,fps={FPS},format=yuv420p"
    )
    cmd = ["ffmpeg", "-y", "-i", in_path, "-t", "16", "-vf", vf, "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22", "-threads", "4", out_path]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45)
        return os.path.exists(out_path) and os.path.getsize(out_path) > 25000
    except Exception:
        return False

def split_into_subtitle_chunks(text, max_words=6):
    words = clean_text_for_tts(text).split()
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= max_words or (len(cur) >= 4 and w.endswith((".", "?", "!", ",", ";", ":"))):
            chunks.append(" ".join(cur))
            cur = []
    if cur:
        chunks.append(" ".join(cur))
    return chunks

def render_dr_berg_long_frame(sec_num, sec_title, bullets, flow_str, active_bullet_idx, subtitle_text):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    card_x1, card_y1, card_x2, card_y2 = 34, 48, 635, 535
    draw.rounded_rectangle([card_x1, card_y1, card_x2, card_y2], radius=18, fill=(10, 20, 36, 232), outline=(0, 210, 255, 220), width=3)
    draw.rounded_rectangle([card_x1, card_y1, card_x2, card_y1 + 64], radius=18, fill=(0, 175, 225, 255))
    draw.rectangle([card_x1, card_y1 + 42, card_x2, card_y1 + 64], fill=(0, 175, 225, 255))
    draw.text((card_x1 + 22, card_y1 + 17), f"STEP 0{sec_num}: {sec_title.upper()[:34]}", font=load_font(22, True), fill=(8, 16, 28, 255))

    for b_i, b_text in enumerate(bullets[:3]):
        by = card_y1 + 92 + b_i * 102
        is_active = (b_i <= active_bullet_idx)
        bg_col = (18, 38, 66, 245) if is_active else (14, 26, 44, 180)
        border_col = (255, 215, 60, 255) if b_i == active_bullet_idx else ((0, 210, 255, 180) if is_active else (70, 95, 125, 120))
        draw.rounded_rectangle([card_x1 + 20, by, card_x2 - 20, by + 84], radius=12, fill=bg_col, outline=border_col, width=2)
        badge_col = (255, 215, 60, 255) if b_i == active_bullet_idx else (0, 200, 245, 230)
        draw.ellipse([card_x1 + 34, by + 20, card_x1 + 76, by + 62], fill=badge_col)
        draw.text((card_x1 + 49, by + 27), str(b_i + 1), font=load_font(22, True), fill=(8, 16, 28, 255))

        words = b_text.split()
        mid = max(1, len(words) // 2)
        b_lines = [" ".join(words[:mid]), " ".join(words[mid:])] if len(words) > 5 else [b_text]
        txt_col = (255, 255, 255, 255) if is_active else (160, 180, 200, 200)
        for l_i, line in enumerate(b_lines[:2]):
            draw.text((card_x1 + 92, by + 18 + l_i * 25), line, font=load_font(19, True), fill=txt_col)

    flow_y = card_y2 - 74
    draw.rounded_rectangle([card_x1 + 20, flow_y, card_x2 - 20, card_y2 - 18], radius=10, fill=(8, 15, 28, 250), outline=(0, 210, 255, 160), width=2)
    draw.text((card_x1 + 34, flow_y + 16), flow_str[:52], font=load_font(17, True), fill=(120, 235, 255, 255))

    if LOGO_PIL is not None:
        img.paste(LOGO_PIL, (W - 64 - 24, 22), LOGO_PIL)

    if subtitle_text:
        f_sub = load_font(29, True)
        bbox = draw.textbbox((0, 0), subtitle_text, font=f_sub)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        bx1 = max(24, (W - tw) // 2 - 22)
        bx2 = min(W - 24, (W + tw) // 2 + 22)
        by1, by2 = 562, 562 + th + 24
        draw.rounded_rectangle([bx1, by1, bx2, by2], radius=12, fill=(6, 12, 22, 235), outline=(255, 220, 70, 210), width=2)
        tx, ty = (W - tw) // 2, by1 + 10
        draw.text((tx + 2, ty + 2), subtitle_text, font=f_sub, fill=(0, 0, 0, 255))
        draw.text((tx, ty), subtitle_text, font=f_sub, fill=(255, 248, 140, 255))

    bar_y = 648
    draw.rectangle([0, bar_y, W, H], fill=(8, 15, 28, 235))
    draw.rectangle([0, bar_y, W, bar_y + 3], fill=(0, 210, 255, 255))
    draw.rectangle([24, bar_y + 14, 195, bar_y + 52], fill=(0, 185, 235, 255))
    draw.text((38, bar_y + 22), f"SECTION 0{sec_num}/05", font=load_font(19, True), fill=(8, 15, 28, 255))
    draw.text((215, bar_y + 20), f"{sec_title}  |  MEDPULSE 5 ROOT-CAUSE GUIDE", font=load_font(22, True), fill=(245, 250, 255, 255))
    return np.array(img)

def build_dr_berg_overlay_track(sec_num, sec_title, bullets, flow_str, p_idx, narration_text, total_duration):
    chunks = split_into_subtitle_chunks(narration_text, max_words=6)
    if not chunks:
        return ImageClip(render_dr_berg_long_frame(sec_num, sec_title, bullets, flow_str, p_idx, "")).set_duration(total_duration)
    char_lengths = [max(len(c), 4) for c in chunks]
    total_chars = sum(char_lengths)
    clips, elapsed = [], 0.0
    for idx, chunk in enumerate(chunks):
        dur = max(0.15, total_duration - elapsed) if idx == len(chunks) - 1 else max(0.25, total_duration * (char_lengths[idx] / total_chars))
        elapsed += dur
        frame = render_dr_berg_long_frame(sec_num, sec_title, bullets, flow_str, p_idx, chunk)
        clips.append(ImageClip(frame).set_duration(dur))
    return concatenate_videoclips(clips).set_duration(total_duration)

def create_section_bumper(sec_num, sec_title, flow_str, duration=2.3):
    img = Image.new("RGB", (W, H), (8, 16, 30))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([90, 170, W - 90, H - 170], radius=22, fill=(12, 24, 44), outline=(0, 215, 255), width=3)
    draw.rectangle([90, 170, 114, H - 170], fill=(0, 215, 255))
    draw.text((150, 220), f"DR. BERG STYLE CLINICAL BREAKDOWN  |  PART 0{sec_num} OF 05", font=load_font(24, True), fill=(0, 215, 255))
    draw.text((150, 285), sec_title[:44], font=load_font(42, True), fill=(255, 255, 255))
    draw.text((150, 385), f"PATHWAY:  {flow_str[:54]}", font=load_font(24, True), fill=(255, 230, 110))
    if LOGO_PIL is not None:
        img.paste(LOGO_PIL, (W - 180, 195), LOGO_PIL)
    clip = ImageClip(np.array(img)).set_duration(duration)
    sr = 44100
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    wave = (0.12 * np.sin(2 * np.pi * 528.0 * t) + 0.08 * np.sin(2 * np.pi * 660.0 * t)) * np.exp(-2.8 * t)
    chime = AudioArrayClip(np.column_stack([wave, wave]).astype(np.float32), fps=sr)
    return clip.set_audio(chime)

def generate_ambient_music(duration, sr=44100):
    chunk_len = 10.0
    t = np.linspace(0, chunk_len, int(sr * chunk_len), endpoint=False)
    wave = (0.32 * np.sin(2 * np.pi * 110.0 * t) + 0.22 * np.sin(2 * np.pi * 164.81 * t) + 0.16 * np.sin(2 * np.pi * 220.0 * t))
    cycle = (wave * 0.032).astype(np.float32)
    stereo = np.column_stack([cycle, cycle])
    repeats = int(math.ceil(duration / chunk_len)) + 1
    full_arr = np.tile(stereo, (repeats, 1))[:int(sr * duration)]
    return AudioArrayClip(full_arr, fps=sr).set_duration(duration)

def loop_or_trim_clip(clip_path, target_duration, w=W, h=H):
    if clip_path and os.path.exists(clip_path):
        try:
            c = VideoFileClip(clip_path).without_audio()
            if c.duration and c.duration > 1.0:
                if c.duration < target_duration:
                    n = int(math.ceil(target_duration / c.duration)) + 1
                     looped = concatenate_videoclips([c] * n)
                    return looped.subclip(0, target_duration), [c]
                return c.subclip(0, target_duration), [c]
        except Exception:
            pass
    return ColorClip(size=(w, h), color=(12, 24, 42), duration=target_duration), []

def render_short_card_overlay(hook_banner, takeaway_points, active_idx, subtitle_text):
    img = Image.new("RGBA", (SHORT_W, SHORT_H), (10, 18, 32, 255))
    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle([28, 42, SHORT_W - 105, 118], radius=14, fill=(0, 180, 230, 255))
    draw.text((46, 64), f"ROOT CAUSE: {hook_banner[:20]}", font=load_font(25, True), fill=(8, 16, 28, 255))
    if LOGO_SHORT_PIL is not None:
        img.paste(LOGO_SHORT_PIL, (SHORT_W - 54 - 24, 48), LOGO_SHORT_PIL)

    vp_x1, vp_y1, vp_x2, vp_y2 = 30, 145, SHORT_W - 30, 625
    draw.rectangle([vp_x1, vp_y1, vp_x2, vp_y2], fill=(0, 0, 0, 0))
    draw.rounded_rectangle([vp_x1 - 3, vp_y1 - 3, vp_x2 + 3, vp_y2 + 3], radius=16, outline=(0, 215, 255, 255), width=4)

    board_y = 650
    draw.rounded_rectangle([30, board_y, SHORT_W - 30, 915], radius=16, fill=(14, 28, 50, 245), outline=(0, 210, 255, 190), width=2)
    for idx, pt in enumerate(takeaway_points[:3]):
        py = board_y + 18 + idx * 80
        bg_c = (24, 48, 82, 255) if idx == active_idx else (12, 22, 38, 210)
        bd_c = (255, 220, 65, 255) if idx == active_idx else (60, 95, 135, 160)
        draw.rounded_rectangle([46, py, SHORT_W - 46, py + 66], radius=10, fill=bg_c, outline=bd_c, width=2)
        draw.text((64, py + 19), pt[:42], font=load_font(22, True), fill=(255, 255, 255, 255))

    if subtitle_text:
        f_sub = load_font(31, True)
        words = subtitle_text.split()
        mid = max(1, len(words) // 2)
        lines = [" ".join(words[:mid]), " ".join(words[mid:])] if len(words) > 4 else [subtitle_text]
        sy1, sy2 = 940, 940 + len(lines) * 44 + 28
        draw.rounded_rectangle([32, sy1, SHORT_W - 32, sy2], radius=14, fill=(6, 12, 22, 245), outline=(255, 220, 65, 240), width=3)
        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=f_sub)
            tw = bbox[2] - bbox[0]
            tx, ty = (SHORT_W - tw) // 2, sy1 + 12 + i * 42
            draw.text((tx + 2, ty + 2), line, font=f_sub, fill=(0, 0, 0, 255))
            draw.text((tx, ty), line, font=f_sub, fill=(255, 245, 120, 255))

    draw.rectangle([0, SHORT_H - 84, SHORT_W, SHORT_H], fill=(0, 175, 225, 255))
    draw.text((48, SHORT_H - 56), "TAP BELOW FOR FULL STEP-BY-STEP PROTOCOL", font=load_font(23, True), fill=(8, 16, 28, 255))
    return np.array(img)

def build_short_track(hook_banner, takeaway_points, active_idx, narration_text, total_duration):
    chunks = split_into_subtitle_chunks(narration_text, max_words=5)
    if not chunks:
        return ImageClip(render_short_card_overlay(hook_banner, takeaway_points, active_idx, "")).set_duration(total_duration)
    char_lengths = [max(len(c), 3) for c in chunks]
    total_chars = sum(char_lengths)
    clips, elapsed = [], 0.0
    for idx, chunk in enumerate(chunks):
        dur = max(0.15, total_duration - elapsed) if idx == len(chunks) - 1 else max(0.25, total_duration * (char_lengths[idx] / total_chars))
        elapsed += dur
        frame = render_short_card_overlay(hook_banner, takeaway_points, active_idx, chunk)
        clips.append(ImageClip(frame).set_duration(dur))
    return concatenate_videoclips(clips).set_duration(total_duration)

def build_companion_short(script_data, used_videos):
    print("Building Distortion-Free Dr. Berg Style Companion Short...")
    sc = script_data["short_script"]
    vw, vh = SHORT_W - 60, 480
    raw_v, norm_v = "temp/short_raw.mp4", "temp/short_norm_box.mp4"
    has_vid = False
    if search_and_download_video(sc["visual_query"], raw_v, used_videos):
        has_vid = normalize_clip_strict_aspect(raw_v, norm_v, vw, vh)

    parts = [
        (0, sc["part1_hook"]),
        (1, sc["part2_root"]),
        (2, sc["part3_action"])
    ]
    segments, open_res = [], []
    for idx, text in parts:
        tts_p = f"temp/short_p{idx}.mp3"
        if not generate_tts(text, tts_p, rate="-4%"):
            continue
        raw_a = AudioFileClip(tts_p)
        open_res.append(raw_a)
        safe_d = max(0.3, raw_a.duration - 0.06)
        voice_a = concatenate_audioclips([raw_a.subclip(0, safe_d), make_silence_audio(0.28)])
        seg_d = voice_a.duration

        base_bg = ColorClip(size=(SHORT_W, SHORT_H), color=(10, 18, 32), duration=seg_d)
        vid_clip, loaded = loop_or_trim_clip(norm_v if has_vid else None, seg_d, w=vw, h=vh)
        open_res.extend(loaded)
        vid_positioned = vid_clip.set_position((30, 145))
        ov_card = build_short_track(sc["hook_banner"], sc["takeaway_points"], idx, text, seg_d)
        comp = CompositeVideoClip([base_bg, vid_positioned, ov_card], size=(SHORT_W, SHORT_H)).set_duration(seg_d).set_audio(voice_a)
        segments.append(comp)

    if not segments:
        return False
    final_short = concatenate_videoclips(segments, method="compose")
    if final_short.duration > 57.5:
        final_short = final_short.subclip(0, 57.5)
    bg_m = generate_ambient_music(final_short.duration)
    final_short = final_short.set_audio(CompositeAudioClip([final_short.audio, bg_m]))
    final_short.write_videofile("output/short_video.mp4", fps=FPS, codec="libx264", audio_codec="aac", preset="ultrafast", threads=4, logger=None)
    for r in open_res:
        try:
            r.close()
        except Exception:
            pass
    print(f"Companion Short Ready: output/short_video.mp4 ({final_short.duration:.1f}s)")
    return True

def main():
    if not GEMINI_API_KEY or not PEXELS_API_KEY:
        raise RuntimeError("Missing GEMINI_API_KEY or PEXELS_API_KEY!")
    used_videos = load_used_items(USED_VIDEOS_FILE)
    used_news = load_used_items(USED_NEWS_FILE)

    topic = select_dr_berg_trending_topic()
    script_data = generate_dr_berg_script(topic)

    final_segments, open_resources = [], []
    timestamps, t_cursor = [], 0.0

    for sec in script_data["sections"]:
        s_num = sec["section_num"]
        s_title = sec["section_title"]
        bullets = sec["board_bullets"]
        flow_str = sec["mechanism_flow"]
        v_query = sec["visual_query"]

        mm, ss = int(t_cursor // 60), int(t_cursor % 60)
        timestamps.append(f"{mm:02d}:{ss:02d} - Step {s_num}: {s_title}")

        print(f"Building Dr. Berg Section {s_num}/5: {s_title}")
        bumper = create_section_bumper(s_num, s_title, flow_str, duration=2.3)
        final_segments.append(bumper)
        t_cursor += bumper.duration

        sec_clips = []
        for c_i in range(2):
            rv, nv = f"temp/sec{s_num}_raw_{c_i}.mp4", f"temp/sec{s_num}_norm_{c_i}.mp4"
            q_use = v_query if c_i == 0 else SAFE_MEDICAL_QUERIES[(s_num + c_i) % len(SAFE_MEDICAL_QUERIES)]
            if search_and_download_video(q_use, rv, used_videos):
                if normalize_clip_strict_aspect(rv, nv, W, H):
                    sec_clips.append(nv)

        for p_idx, p_text in enumerate(sec["paragraphs"]):
            tts_file = f"temp/sec{s_num}_p{p_idx}.mp3"
            if not generate_tts(p_text, tts_file):
                continue
            raw_a = AudioFileClip(tts_file)
            open_resources.append(raw_a)
            safe_voice_d = max(0.3, raw_a.duration - 0.06)
            calm_audio = concatenate_audioclips([raw_a.subclip(0, safe_voice_d), make_silence_audio(0.42)])
            seg_dur = calm_audio.duration

            chosen_vid = sec_clips[p_idx % len(sec_clips)] if sec_clips else None
            bg_v, loaded = loop_or_trim_clip(chosen_vid, seg_dur, w=W, h=H)
            open_resources.extend(loaded)

            ov_track = build_dr_berg_overlay_track(s_num, s_title, bullets, flow_str, p_idx, p_text, seg_dur)
            comp = CompositeVideoClip([bg_v, ov_track], size=(W, H)).set_duration(seg_dur).set_audio(calm_audio)
            final_segments.append(comp)
            t_cursor += seg_dur

    full_video = concatenate_videoclips(final_segments, method="compose")
    if full_video.duration > 595.0:
        full_video = full_video.subclip(0, 595.0)

    print(f"Final Dr. Berg Style Video Duration: {full_video.duration / 60.0:.2f} minutes ({full_video.duration:.1f}s)")
    ambient = generate_ambient_music(full_video.duration)
    full_video = full_video.set_audio(CompositeAudioClip([full_video.audio, ambient]))
    full_video.write_videofile("output/final_video.mp4", fps=FPS, codec="libx264", audio_codec="aac", preset="ultrafast", threads=4, logger=None)

    try:
        build_companion_short(script_data, used_videos)
    except Exception as e:
        print(f"Short warning: {e}")

    ar_h1 = "=== \u0627\u0644\u0639\u0646\u0627\u0648\u064a\u0646 \u0627\u0644\u0645\u0642\u062a\u0631\u062d\u0629 (\u0623\u0633\u0644\u0648\u0628 \u062f\u0643\u062a\u0648\u0631 \u0628\u064a\u0631\u062c - \u0627\u062e\u062a\u0631 \u0627\u0644\u062e\u064a\u0627\u0631 1) ==="
    ar_opt1 = "\u0627\u0644\u062e\u064a\u0627\u0631 1 (\u0645\u0648\u0635\u0649 \u0628\u0647): "
    ar_opt2 = "\u0627\u0644\u062e\u064a\u0627\u0631 2: "
    ar_opt3 = "\u0627\u0644\u062e\u064a\u0627\u0631 3: "
    ar_h2 = "=== \u0648\u0635\u0641 \u0627\u0644\u0635\u0648\u0631\u0629 \u0627\u0644\u0645\u0635\u063a\u0631\u0629 (Thumbnail Prompt - Landscape 16:9) ==="
    ar_h3 = "=== \u0639\u0646\u0648\u0627\u0646 \u0648\u0648\u0635\u0641 \u0627\u0644\u0641\u064a\u062f\u064a\u0648 \u0627\u0644\u0642\u0635\u064a\u0631 \u0627\u0644\u0645\u0631\u0641\u0642 (YouTube Short) ==="
    ar_h4 = "=== \u0635\u0646\u062f\u0648\u0642 \u0627\u0644\u0648\u0635\u0641 \u0627\u0644\u0643\u0627\u0645\u0644 \u0644\u0644\u0641\u064a\u062f\u064a\u0648 \u0627\u0644\u0637\u0648\u064a\u0644 ==="
    ar_h5 = "=== \u0627\u0644\u0643\u0644\u0645\u0627\u062a \u0627\u0644\u0645\u0641\u062a\u0627\u062d\u064a\u0629 (Tags) ==="

    details_lines = [
        ar_h1,
        f"{ar_opt1}{script_data['title_options'][0]}",
        f"{ar_opt2}{script_data['title_options'][1]}",
        f"{ar_opt3}{script_data['title_options'][2]}",
        "",
        ar_h2,
        script_data["thumbnail_prompt"],
        "",
        ar_h3,
        f"Short Title: {script_data['short_script']['short_title']}",
        f"Short Description: Watch the full step-by-step protocol on MedPulse 5: {script_data['title_options'][0]} #Shorts #HealthTips #NaturalRemedies #Nutrition",
        "",
        ar_h4,
        script_data["description"],
        "",
        "Step-by-Step Video Chapters:",
        *timestamps,
        "",
        "Educational Disclaimer: This video is for informational and educational purposes only and is not medical advice.",
        "",
        ar_h5,
        script_data["tags"]
    ]
    with open("output/youtube_details.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(details_lines))

    used_news.append(topic["norm_key"])
    save_used_items(USED_NEWS_FILE, used_news)
    save_used_items(USED_VIDEOS_FILE, used_videos)

    for r in open_resources:
        try:
            r.close()
        except Exception:
            pass
    print("ALL DONE! Dr. Berg Style Long Video + Distortion-Free Short Ready.")

if __name__ == "__main__":
    main()
