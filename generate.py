#!/usr/bin/env python3
"""
YouTube Video Image Generator v5
==================================
Визуал: Kie API (z-image) / Replicate (FLUX) / Pexels (бесплатное видео) / Pixabay (бесплатное видео)
Промпты: DeepSeek / OpenAI
Монтаж: Whisper + FFmpeg

Переменные окружения:
    DEEPSEEK_API_KEY, OPENAI_API_KEY, KIE_API_KEY, REPLICATE_API_TOKEN, PEXELS_API_KEY, PIXABAY_API_KEY
"""

import os, re, sys, json, time, argparse, subprocess, ssl, urllib.request, urllib.parse, urllib.error
from pathlib import Path

# ============================================================
# HTTP helpers (без requests/urllib3 — только stdlib).
# verify=False эквивалент для Pexels/Pixabay: у юзера VPN + самоподписные
# сертификаты бьют проверку — раньше это решалось через urllib3.disable_warnings
# ============================================================
_UNVERIFIED_SSL_CTX = ssl.create_default_context()
_UNVERIFIED_SSL_CTX.check_hostname = False
_UNVERIFIED_SSL_CTX.verify_mode = ssl.CERT_NONE

# Pexels/Pixabay за Cloudflare — голый `Python-urllib/*` UA режется с 403.
# Браузерный UA гарантированно пропускается, это не обход защиты,
# а просто нормальная идентификация HTTP-клиента (как делал requests)
_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

def _http_get_json(url, params=None, headers=None, timeout=30):
    """GET → parsed JSON. Бросает RuntimeError на не-2xx или не-JSON ответе."""
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    merged = dict(_DEFAULT_HEADERS)
    if headers:
        merged.update(headers)
    req = urllib.request.Request(url, headers=merged, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_UNVERIFIED_SSL_CTX) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}")
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        raise RuntimeError(f"{type(e).__name__}: {e}")

def _http_download(url, filepath, min_size=10000, timeout=120, chunk=1024*1024):
    """Скачивает url в filepath стримом. Возвращает (ok, size_bytes).
    Минимальный размер защищает от "успешного" скачивания 404-заглушки."""
    req = urllib.request.Request(url, headers=_DEFAULT_HEADERS, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_UNVERIFIED_SSL_CTX) as resp:
            total = 0
            with open(filepath, "wb") as f:
                while True:
                    buf = resp.read(chunk)
                    if not buf:
                        break
                    f.write(buf)
                    total += len(buf)
            if total < min_size:
                try: os.remove(filepath)
                except OSError: pass
                return False, total
            return True, total
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
        return False, 0

# ============================================================
# КОНФИГУРАЦИЯ КАНАЛОВ
# ============================================================
DEFAULT_CONFIG = {
    "channels": {
        "finance": {
            "style": "oil painting style, rich warm colors, textured brushstrokes, classical art aesthetic, golden light, detailed composition, museum quality artwork",
            "topic": "финансы, инвестиции, экономика"
        },
        "garden": {
            "style": "photorealistic, beautiful natural lighting, lush green garden, warm golden sunlight, shallow depth of field, macro photography details, 4k",
            "topic": "садоводство, огородство, растения, дача"
        }
    }
}

def load_config(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    return DEFAULT_CONFIG

def save_default_config(path):
    with open(path, "w", encoding="utf-8") as f: json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)

# ============================================================
# РАЗБИВКА НА ПРЕДЛОЖЕНИЯ
# ============================================================
MAX_SENTENCE_WORDS = 20
MIN_LONG_SENTENCE_SIDE_WORDS = 8

def _choose_long_sentence_split(words):
    center = len(words) // 2
    min_side = min(MIN_LONG_SENTENCE_SIDE_WORDS, max(1, center))

    comma_splits = [
        i + 1
        for i, word in enumerate(words[:-1])
        if word.rstrip("\"')]}").endswith(",")
        and i + 1 >= min_side
        and len(words) - (i + 1) >= min_side
    ]
    if comma_splits:
        return min(comma_splits, key=lambda idx: abs(idx - center))

    return center

def _split_long_sentence(sentence):
    words = sentence.split()
    if len(words) <= MAX_SENTENCE_WORDS:
        return [sentence]

    split_at = _choose_long_sentence_split(words)
    left = " ".join(words[:split_at]).strip()
    right = " ".join(words[split_at:]).strip()

    parts = []
    for part in (left, right):
        if part:
            parts.extend(_split_long_sentence(part))
    return parts

def _split_sentences_impl(text):
    """Внутренняя реализация: возвращает (texts, group_ids).
    group_ids[i] — индекс исходного предложения (до split_long).
    Половины одного длинного предложения имеют одинаковый group_id."""
    raw = re.split(r'(?<=[.!?])\s+', text.strip())
    raw = [s.strip() for s in raw if s.strip()]
    sentences = []
    for s in raw:
        if sentences and len(s.split()) < 3:
            sentences[-1] += " " + s
        else:
            sentences.append(s)

    result_texts, result_groups = [], []
    for group_id, s in enumerate(sentences):
        parts = _split_long_sentence(s)
        for part in parts:
            result_texts.append(part)
            result_groups.append(group_id)
    return result_texts, result_groups

def split_into_sentences(text):
    texts, _ = _split_sentences_impl(text)
    return texts

def split_into_sentences_with_groups(text):
    """Возвращает (sentences, group_ids). group_ids[i] — индекс исходного
    предложения до разбивки длинных — все половины одного предложения
    имеют одинаковый group_id."""
    return _split_sentences_impl(text)

# ============================================================
# ПРОМПТЫ ДЛЯ КАРТИНОК — DeepSeek / OpenAI
# ============================================================
def _call_openai_compat(api_key, base_url, model, system, user, max_tokens, temperature):
    """Один chat-completions вызов через urllib (без openai SDK).
    DeepSeek и OpenAI используют совместимый формат — отличается только base_url + model."""
    import urllib.error
    endpoint = f"{base_url.rstrip('/')}/chat/completions"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        raise RuntimeError(f"HTTP {e.code}: {e.reason} — {err_body[:300]}")
    data = json.loads(raw)
    return data["choices"][0]["message"]["content"].strip()


def generate_prompts_llm(sentences, style, topic, llm_provider):
    if llm_provider == "deepseek":
        api_key, base_url, model, name = os.environ.get("DEEPSEEK_API_KEY",""), "https://api.deepseek.com/v1", "deepseek-chat", "DeepSeek"
    else:
        api_key, base_url, model, name = os.environ.get("OPENAI_API_KEY",""), "https://api.openai.com/v1", "gpt-4.1-mini", "OpenAI"

    if not api_key:
        print(f"   ⚠️  Ключ {name} не найден.")
        return [f"{style}. Scene: {s[:200]}" for s in sentences]

    sys_prompt = f"""You are an expert at writing image generation prompts.
For each sentence from a video script, create an image prompt.
Rules: write in ENGLISH, start with style: {style}, describe visual scene, add lighting/composition/mood, NO text in image, keep SAME style, 1-3 sentences max, topic: {topic}.
Reply with ONLY the prompt."""

    prompts = []
    for i, s in enumerate(sentences):
        try:
            content = _call_openai_compat(api_key, base_url, model, sys_prompt, f'Sentence: "{s}"', 200, 0.7)
            prompts.append(content)
            print(f"  📝 [{i+1}/{len(sentences)}] {prompts[-1][:70]}...")
        except Exception as e:
            print(f"  ⚠️  [{i+1}]: {e}")
            prompts.append(f"{style}. Scene depicting: {s[:200]}")
            time.sleep(2)
        time.sleep(0.3)
    return prompts

# ============================================================
# КЛЮЧЕВЫЕ СЛОВА ДЛЯ PEXELS — DeepSeek / OpenAI
# ============================================================
def generate_keywords_llm(sentences, topic, llm_provider):
    if llm_provider == "deepseek":
        api_key, base_url, model, name = os.environ.get("DEEPSEEK_API_KEY",""), "https://api.deepseek.com/v1", "deepseek-chat", "DeepSeek"
    else:
        api_key, base_url, model, name = os.environ.get("OPENAI_API_KEY",""), "https://api.openai.com/v1", "gpt-4.1-mini", "OpenAI"

    if not api_key:
        print(f"   ⚠️  Ключ {name} не найден.")
        return [s.split()[0] for s in sentences]

    sys_prompt = f"""You generate search keywords for finding stock videos on Pexels.
For each sentence from a video script, write 2-3 English keywords for video search.
Rules:
- Keywords must be in ENGLISH
- 2-3 words maximum, separated by spaces
- Think about what VIDEO would illustrate this sentence
- Be specific enough to find relevant footage, but general enough that results exist
- Topic: {topic}
- Reply with ONLY the keywords, nothing else"""

    keywords = []
    for i, s in enumerate(sentences):
        try:
            content = _call_openai_compat(api_key, base_url, model, sys_prompt, f'Sentence: "{s}"', 20, 0.5)
            kw = content.strip('"').strip("'")
            keywords.append(kw)
            print(f"  🔑 [{i+1}/{len(sentences)}] {kw}")
        except Exception as e:
            print(f"  ⚠️  [{i+1}]: {e}")
            keywords.append("nature landscape")
            time.sleep(2)
        time.sleep(0.3)
    return keywords

# ============================================================
# PEXELS — поиск и скачивание видео
# ============================================================
def search_and_download_pexels(keywords_list, indices, output_dir, token, used_ids=None):
    if not indices: return 0
    if used_ids is None: used_ids = set()

    os.makedirs(output_dir, exist_ok=True)
    headers = {"Authorization": token}
    success = 0

    for idx in indices:
        kw = keywords_list[idx]
        kw = kw.split("\n")[0].strip().strip('"').strip("'")
        kw_words = kw.split()[:3]
        kw = " ".join(kw_words)

        filepath = os.path.join(output_dir, f"clip_{idx:04d}.mp4")
        print(f"  🎬 [{idx+1}/{len(keywords_list)}] Поиск: \"{kw}\"...")

        found = False
        queries_to_try = [kw]
        if len(kw_words) > 2:
            queries_to_try.append(" ".join(kw_words[:2]))
        if len(kw_words) > 1:
            queries_to_try.append(kw_words[0])
        queries_to_try.append("nature landscape")

        for query in queries_to_try:
            try:
                data = _http_get_json(
                    "https://api.pexels.com/videos/search",
                    params={"query": query, "orientation": "landscape", "size": "medium", "per_page": 15},
                    headers=headers,
                    timeout=30,
                )
                videos = data.get("videos", [])

                for video in videos:
                    if video["id"] in used_ids:
                        continue

                    # Ищем HD горизонтальный файл
                    best_file = None
                    for vf in video.get("video_files", []):
                        w, h = vf.get("width", 0), vf.get("height", 0)
                        if w >= 1280 and w > h and vf.get("link"):
                            if best_file is None or w < best_file.get("width", 9999):
                                best_file = vf

                    if not best_file:
                        # Пробуем любое горизонтальное >= 720p
                        for vf in video.get("video_files", []):
                            w, h = vf.get("width", 0), vf.get("height", 0)
                            if w >= 720 and w > h and vf.get("link"):
                                best_file = vf
                                break

                    if best_file:
                        ok, fsize = _http_download(best_file["link"], filepath, min_size=10000)
                        if ok:
                            used_ids.add(video["id"])
                            success += 1
                            found = True
                            print(f"     ✅ clip_{idx:04d}.mp4 ({fsize // 1024} KB)")
                        else:
                            print(f"     ⚠️  Скачивание не удалось (или файл слишком мал)")
                        break

                if found:
                    break

            except Exception as e:
                print(f"     ⚠️  \"{query}\": {e}")

            time.sleep(0.5)

        if not found:
            print(f"     ❌ Не найдено для [{idx+1}]")

        time.sleep(0.3)

    return success

# ============================================================
# PIXABAY — поиск и скачивание видео
# ============================================================
def search_and_download_pixabay(keywords_list, indices, output_dir, token, used_ids=None):
    if not indices: return 0
    if used_ids is None: used_ids = set()

    os.makedirs(output_dir, exist_ok=True)
    success = 0

    for idx in indices:
        kw = keywords_list[idx]
        kw = kw.split("\n")[0].strip().strip('"').strip("'")
        kw_words = kw.split()[:3]
        kw = " ".join(kw_words)

        filepath = os.path.join(output_dir, f"clip_{idx:04d}.mp4")
        print(f"  🎬 [{idx+1}/{len(keywords_list)}] Поиск Pixabay: \"{kw}\"...")

        found = False
        queries_to_try = [kw]
        if len(kw_words) > 2:
            queries_to_try.append(" ".join(kw_words[:2]))
        if len(kw_words) > 1:
            queries_to_try.append(kw_words[0])
        queries_to_try.append("nature landscape")

        for query in queries_to_try:
            try:
                data = _http_get_json(
                    "https://pixabay.com/api/videos/",
                    params={
                        "key": token,
                        "q": query,
                        "video_type": "film",
                        "per_page": 15,
                        "safesearch": "true",
                        "editors_choice": "false",
                    },
                    timeout=30,
                )
                videos = data.get("hits", [])

                for video in videos:
                    vid_id = video.get("id")
                    if vid_id in used_ids:
                        continue

                    # Pixabay: videos.large > videos.medium > videos.small
                    video_data = video.get("videos", {})
                    best_file = None

                    for quality in ["large", "medium", "small"]:
                        vf = video_data.get(quality, {})
                        url = vf.get("url", "")
                        w = vf.get("width", 0)
                        h = vf.get("height", 0)
                        if url and w >= 720 and w > h:
                            best_file = {"url": url, "width": w, "height": h}
                            break

                    if not best_file:
                        continue

                    ok, fsize = _http_download(best_file["url"], filepath, min_size=10000)
                    if ok:
                        used_ids.add(vid_id)
                        success += 1
                        found = True
                        print(f"     ✅ clip_{idx:04d}.mp4 ({fsize // 1024} KB)")
                    else:
                        print(f"     ⚠️  Скачивание не удалось (или файл слишком мал)")
                    break

                if found:
                    break

            except Exception as e:
                print(f"     ⚠️  \"{query}\": {e}")

            time.sleep(0.5)

        if not found:
            print(f"     ❌ Не найдено для [{idx+1}]")

        time.sleep(0.3)

    return success

# ============================================================
# Нормализация скачанного фото → настоящий PNG
# Pexels/Pixabay отдают JPEG, но мы сохраняем файл как frame_NNNN.png.
# Если оставить JPEG-байты в .png, concat demuxer ломается на смеси
# кодеков (JPEG/PNG) и разрешений и обрывает видео после 1-2 кадров.
# Прогоняем через ffmpeg — на выходе гарантированно PNG 1280x720.
# ============================================================
def _normalize_photo_to_png(path):
    """Перекодирует файл по пути `path` в настоящий PNG 1280x720 in-place.
    Возвращает True при успехе, False если ffmpeg упал."""
    tmp = path + ".src"
    try:
        os.replace(path, tmp)
    except Exception:
        return False
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", tmp,
             "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,"
                     "pad=1280:720:(ow-iw)/2:(oh-ih)/2",
             "-frames:v", "1", path, "-loglevel", "error"],
            shell=False,
        ).returncode
        if r == 0 and os.path.exists(path) and os.path.getsize(path) > 1000:
            try: os.remove(tmp)
            except: pass
            return True
        # откатываемся, если не получилось
        try: os.replace(tmp, path)
        except: pass
        return False
    except Exception:
        try: os.replace(tmp, path)
        except: pass
        return False


# ============================================================
# PEXELS — поиск и скачивание фотографий (16:9)
# ============================================================
def search_and_download_pexels_photos(keywords_list, indices, output_dir, token, used_ids=None):
    if not indices: return 0
    if used_ids is None: used_ids = set()

    os.makedirs(output_dir, exist_ok=True)
    headers = {"Authorization": token}
    success = 0

    for idx in indices:
        kw = keywords_list[idx]
        kw = kw.split("\n")[0].strip().strip('"').strip("'")
        kw_words = kw.split()[:3]
        kw = " ".join(kw_words)

        filepath = os.path.join(output_dir, f"frame_{idx:04d}.png")
        print(f"  🖼️  [{idx+1}/{len(keywords_list)}] Поиск Pexels фото: \"{kw}\"...")

        found = False
        queries_to_try = [kw]
        if len(kw_words) > 2:
            queries_to_try.append(" ".join(kw_words[:2]))
        if len(kw_words) > 1:
            queries_to_try.append(kw_words[0])
        queries_to_try.append("nature landscape")

        for query in queries_to_try:
            try:
                data = _http_get_json(
                    "https://api.pexels.com/v1/search",
                    params={"query": query, "orientation": "landscape", "size": "large", "per_page": 15},
                    headers=headers,
                    timeout=30,
                )
                photos = data.get("photos", [])

                for photo in photos:
                    if photo["id"] in used_ids:
                        continue

                    w = photo.get("width", 0)
                    h = photo.get("height", 0)
                    if h == 0:
                        continue
                    # Только близкие к 16:9 (допуск 1.6..2.0)
                    if not (1.6 <= w / h <= 2.0):
                        continue

                    src = photo.get("src", {})
                    url = src.get("large2x") or src.get("large") or src.get("original")
                    if not url:
                        continue

                    ok, fsize = _http_download(url, filepath, min_size=10000)
                    if ok:
                        if not _normalize_photo_to_png(filepath):
                            print(f"     ⚠️  frame_{idx:04d}.png: не удалось перекодировать в PNG")
                            try: os.remove(filepath)
                            except: pass
                            break
                        used_ids.add(photo["id"])
                        success += 1
                        found = True
                        print(f"     ✅ frame_{idx:04d}.png ({fsize // 1024} KB, {w}x{h} → 1280x720)")
                    else:
                        print(f"     ⚠️  Скачивание не удалось (или файл слишком мал)")
                    break

                if found:
                    break

            except Exception as e:
                print(f"     ⚠️  \"{query}\": {e}")

            time.sleep(0.5)

        if not found:
            print(f"     ❌ Не найдено для [{idx+1}]")

        time.sleep(0.3)

    return success

# ============================================================
# PIXABAY — поиск и скачивание фотографий (16:9)
# ============================================================
def search_and_download_pixabay_photos(keywords_list, indices, output_dir, token, used_ids=None):
    if not indices: return 0
    if used_ids is None: used_ids = set()

    os.makedirs(output_dir, exist_ok=True)
    success = 0

    for idx in indices:
        kw = keywords_list[idx]
        kw = kw.split("\n")[0].strip().strip('"').strip("'")
        kw_words = kw.split()[:3]
        kw = " ".join(kw_words)

        filepath = os.path.join(output_dir, f"frame_{idx:04d}.png")
        print(f"  🖼️  [{idx+1}/{len(keywords_list)}] Поиск Pixabay фото: \"{kw}\"...")

        found = False
        queries_to_try = [kw]
        if len(kw_words) > 2:
            queries_to_try.append(" ".join(kw_words[:2]))
        if len(kw_words) > 1:
            queries_to_try.append(kw_words[0])
        queries_to_try.append("nature landscape")

        for query in queries_to_try:
            try:
                data = _http_get_json(
                    "https://pixabay.com/api/",
                    params={
                        "key": token,
                        "q": query,
                        "image_type": "photo",
                        "orientation": "horizontal",
                        "min_width": 1280,
                        "min_height": 720,
                        "per_page": 15,
                        "safesearch": "true",
                    },
                    timeout=30,
                )
                photos = data.get("hits", [])

                for photo in photos:
                    pid = photo.get("id")
                    if pid in used_ids:
                        continue

                    w = photo.get("imageWidth", 0)
                    h = photo.get("imageHeight", 0)
                    if h == 0:
                        continue
                    # Только близкие к 16:9 (допуск 1.6..2.0)
                    if not (1.6 <= w / h <= 2.0):
                        continue

                    url = photo.get("largeImageURL") or photo.get("webformatURL")
                    if not url:
                        continue

                    ok, fsize = _http_download(url, filepath, min_size=10000)
                    if ok:
                        if not _normalize_photo_to_png(filepath):
                            print(f"     ⚠️  frame_{idx:04d}.png: не удалось перекодировать в PNG")
                            try: os.remove(filepath)
                            except: pass
                            break
                        used_ids.add(pid)
                        success += 1
                        found = True
                        print(f"     ✅ frame_{idx:04d}.png ({fsize // 1024} KB, {w}x{h} → 1280x720)")
                    else:
                        print(f"     ⚠️  Скачивание не удалось (или файл слишком мал)")
                    break

                if found:
                    break

            except Exception as e:
                print(f"     ⚠️  \"{query}\": {e}")

            time.sleep(0.5)

        if not found:
            print(f"     ❌ Не найдено для [{idx+1}]")

        time.sleep(0.3)

    return success

# ============================================================
# КАРТИНКИ — Kie API / Replicate (без изменений)
# ============================================================
def generate_images_kie(prompts, indices, output_dir, token):
    if not indices: return 0
    print(f"\n   📤 Отправка {len(indices)} задач...")
    tasks = {}
    for count, idx in enumerate(indices):
        try:
            payload = json.dumps({"model":"z-image","input":{"prompt":prompts[idx],"aspect_ratio":"16:9","nsfw_checker":False}}).encode("utf-8")
            req = urllib.request.Request("https://api.kie.ai/api/v1/jobs/createTask", data=payload, headers={"Authorization":f"Bearer {token}","Content-Type":"application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            if result.get("code") == 200:
                tasks[result["data"]["taskId"]] = idx
                print(f"   ✅ [{count+1}/{len(indices)}] Отправлено")
            elif result.get("code") == 429:
                time.sleep(5)
                with urllib.request.urlopen(req, timeout=30) as resp: result = json.loads(resp.read().decode("utf-8"))
                if result.get("code") == 200: tasks[result["data"]["taskId"]] = idx
        except Exception as e:
            print(f"   ❌ [{count+1}] {e}")
        time.sleep(0.3)

    if not tasks: return 0
    print(f"\n   ⏳ Жду 30 сек...")
    time.sleep(30)
    pending, success = dict(tasks), 0
    for rnd in range(30):
        if not pending: break
        print(f"\n   🔍 Проверка {rnd+1}: осталось {len(pending)}...")
        still = {}
        for tid, idx in pending.items():
            try:
                req = urllib.request.Request(f"https://api.kie.ai/api/v1/jobs/recordInfo?taskId={tid}", headers={"Authorization":f"Bearer {token}"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    st = json.loads(resp.read().decode("utf-8"))
                data = st.get("data") or {}
                state, result_str = data.get("state",""), data.get("resultJson","")
                if state == "success" and result_str:
                    rj = json.loads(result_str)
                    urls = rj.get("resultUrls", [])
                    if urls:
                        img_path = os.path.join(output_dir, f"frame_{idx:04d}.png")
                        dl_req = urllib.request.Request(urls[0], headers={"User-Agent":"Mozilla/5.0"})
                        with urllib.request.urlopen(dl_req, timeout=60) as dl: open(img_path,"wb").write(dl.read())
                        success += 1; print(f"   ✅ frame_{idx:04d}.png")
                elif state == "fail": print(f"   ❌ frame_{idx:04d}.png — {data.get('failMsg','?')}")
                else: still[tid] = idx
            except Exception as e:
                print(f"   ⚠️  {e}"); still[tid] = idx
            time.sleep(0.2)
        pending = still
        if pending: print(f"   ⏳ Ещё {len(pending)}, жду 30 сек..."); time.sleep(30)
    return success

def generate_images_replicate(prompts, indices, output_dir, token):
    """Replicate FLUX — последовательный режим: отправили → ждём → polling до 3 раз → следующий.
    FLUX-schnell генерит ~2-5s, последовательная отправка снимает 429 (too many requests)."""
    if not indices: return 0

    print(f"\n   📤 Генерация {len(indices)} картинок через Replicate (последовательно)...")
    success = 0
    POLL_DELAYS = (3, 5, 7)  # сек между проверками: ~15s в сумме

    for count, idx in enumerate(indices):
        pred_id = None

        # --- отправка с ретраями на 429/сетевых ---
        for attempt in range(5):
            try:
                payload = json.dumps({"input":{"prompt":prompts[idx],"aspect_ratio":"16:9","num_outputs":1,"output_format":"png","go_fast":True}}).encode("utf-8")
                req = urllib.request.Request(
                    "https://api.replicate.com/v1/models/black-forest-labs/flux-schnell/predictions",
                    data=payload,
                    headers={"Authorization":f"Bearer {token}","Content-Type":"application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                pred_id = result.get("id")
                if pred_id:
                    break
                raise Exception(f"Нет id в ответе: {result.get('detail', result.get('error', '?'))}")
            except urllib.error.HTTPError as e:
                # 429 — ждём дольше, экспоненциальный backoff
                wait = 5 * (2 ** attempt) if e.code == 429 else 2
                print(f"   ⚠️  [{count+1}/{len(indices)}] HTTP {e.code}, попытка {attempt+1}/5, жду {wait}s...")
                if attempt < 4: time.sleep(wait)
            except Exception as e:
                print(f"   ⚠️  [{count+1}/{len(indices)}] попытка {attempt+1}/5: {e}")
                if attempt < 4: time.sleep(2)

        if not pred_id:
            print(f"   ❌ frame_{idx:04d}.png — не удалось отправить задачу")
            continue

        # --- polling до 3 раз ---
        done = False
        for check_num, delay in enumerate(POLL_DELAYS, 1):
            time.sleep(delay)
            try:
                req = urllib.request.Request(
                    f"https://api.replicate.com/v1/predictions/{pred_id}",
                    headers={"Authorization":f"Bearer {token}"}
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                status = result.get("status", "")

                if status == "succeeded":
                    output = result.get("output")
                    if output:
                        url = output[0] if isinstance(output, list) else output
                        fp = os.path.join(output_dir, f"frame_{idx:04d}.png")
                        urllib.request.urlretrieve(str(url), fp)
                        success += 1
                        print(f"   ✅ [{count+1}/{len(indices)}] frame_{idx:04d}.png (проверка {check_num})")
                    else:
                        print(f"   ❌ frame_{idx:04d}.png — succeeded без output")
                    done = True
                    break
                elif status in ("failed", "canceled"):
                    err = result.get("error", status)
                    print(f"   ❌ frame_{idx:04d}.png — {err}")
                    done = True
                    break
                # иначе processing/starting — ждём следующей проверки
            except Exception as e:
                print(f"   ⚠️  проверка {check_num}/3: {e}")

        if not done:
            print(f"   ⏭️  frame_{idx:04d}.png — не готово за 3 проверки, пропуск")

    print(f"\n   📊 Готово: {success}/{len(indices)}")
    return success

# ============================================================
# НОРМАЛИЗАЦИЯ ТЕКСТА ДЛЯ СРАВНЕНИЯ
# ============================================================
def _normalize(text):
    """Убирает пунктуацию, лишние пробелы, приводит к нижнему регистру."""
    t = re.sub(r'[^\w\s]', '', text.lower())
    return re.sub(r'\s+', ' ', t).strip()

def _normalize_words(text):
    """Возвращает список нормализованных слов."""
    return _normalize(text).split()

def _detect_language(text):
    """Определяет язык текста по доле кириллических символов."""
    if not text:
        return "ru"
    alpha_chars = [c for c in text if c.isalpha()]
    if not alpha_chars:
        return "ru"
    cyrillic = sum(1 for c in alpha_chars if '\u0400' <= c <= '\u04ff')
    ratio = cyrillic / len(alpha_chars)
    return "ru" if ratio > 0.3 else "en"


# ============================================================
# WHISPER + МАППИНГ ПРЕДЛОЖЕНИЙ
# ============================================================
def get_timings(audio_path, sentences, group_ids=None):
    # --- Кэш: если timings.json + sentence_breakdown.json уже есть
    # и количество предложений совпадает — Whisper пропускаем.
    # Это спасает от повторного ожидания Whisper, если предыдущая
    # сборка упала на FFmpeg и final_video.mp4 так и не появился.
    breakdown_dir = os.path.dirname(audio_path) or "."
    timings_path = os.path.join(breakdown_dir, "timings.json")
    breakdown_path = os.path.join(breakdown_dir, "sentence_breakdown.json")
    if os.path.isfile(timings_path) and os.path.isfile(breakdown_path):
        try:
            with open(timings_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if isinstance(cached, list) and len(cached) == len(sentences):
                # Сверяем тексты предложений — если скрипт меняли, кэш невалиден
                texts_match = all(
                    str(cached[i].get("text", "")).strip() == str(sentences[i]).strip()
                    for i in range(len(sentences))
                )
                has_group_ids = all("group_id" in c for c in cached)
                if texts_match and has_group_ids:
                    print(f"♻️  Тайминги из кэша: {timings_path}")
                    print(f"   ({len(cached)} предложений — Whisper пропущен)")
                    return cached
                elif texts_match and not has_group_ids:
                    print("   ⚠️  timings.json без group_id (старый формат) — перезапуск Whisper")
                else:
                    print("   ⚠️  timings.json не совпадает со скриптом — перезапуск Whisper")
            else:
                print("   ⚠️  timings.json устарел (другое кол-во предложений) — перезапуск Whisper")
        except Exception as e:
            print(f"   ⚠️  не удалось прочитать кэш таймингов ({e}) — перезапуск Whisper")

    try: import whisper
    except ImportError: print("❌ pip install openai-whisper"); sys.exit(1)

    # Определяем язык по тексту скрипта
    all_text = " ".join(sentences)
    lang = _detect_language(all_text)
    lang_names = {"ru": "русский", "en": "English"}
    print(f"🌐 Язык скрипта: {lang_names.get(lang, lang)}")

    print("🎙️  Загрузка Whisper...")
    model = whisper.load_model("medium")
    print("🎙️  Транскрипция (word_timestamps=True)...")
    result = model.transcribe(audio_path, language=lang, word_timestamps=True)
    segments = result.get("segments", [])

    if not segments:
        print("   ⚠️  Whisper не вернул сегментов, фоллбэк по длине")
        return _fallback_timings(sentences, 15.0)

    audio_duration = segments[-1]["end"]

    # --- Собираем ВСЕ слова с таймингами из Whisper ---
    whisper_words = []
    for seg in segments:
        for w in seg.get("words", []):
            word_text = w.get("word", "").strip()
            if word_text:
                whisper_words.append({
                    "word": word_text,
                    "start": w["start"],
                    "end": w["end"],
                    "norm": _normalize(word_text),
                })

    if not whisper_words:
        print("   ⚠️  Whisper не вернул слов, фоллбэк по длине")
        return _fallback_timings(sentences, audio_duration)

    print(f"   Whisper: {len(whisper_words)} слов, {audio_duration:.1f} сек")

    # --- Сохраняем разбивку в файл для отладки ---
    breakdown_data = {
        "total_sentences": len(sentences),
        "total_whisper_words": len(whisper_words),
        "audio_duration": audio_duration,
        "detected_language": lang,
        "sentences": [{"index": i, "text": s, "words": _normalize_words(s), "group_id": group_ids[i] if group_ids else None} for i, s in enumerate(sentences)],
        # Полный список слов со временами — нужен analyzer.py для snap'а start_time
        # оверлеев к точному моменту произнесения ключевого слова.
        "whisper_words": [{"word": w["word"], "norm": w["norm"], "start": w["start"], "end": w["end"]} for w in whisper_words],
    }
    with open(breakdown_path, "w", encoding="utf-8") as f:
        json.dump(breakdown_data, f, ensure_ascii=False, indent=2)
    print(f"   📄 Разбивка сохранена: {breakdown_path}")

    # --- Маппинг: ищем каждое предложение в потоке слов Whisper ---
    timings = _map_sentences_to_words(sentences, whisper_words, audio_duration, group_ids)

    # --- Сохраняем тайминги для отладки ---
    with open(timings_path, "w", encoding="utf-8") as f:
        json.dump(timings, f, ensure_ascii=False, indent=2)
    print(f"   📄 Тайминги сохранены: {timings_path}")

    return timings


def _map_sentences_to_words(sentences, whisper_words, audio_duration, group_ids=None):
    """
    Последовательно сопоставляет предложения из скрипта со словами Whisper.
    Для каждого предложения ищет лучшее совпадение в потоке слов.
    
    Ключевые улучшения:
    - Широкое окно поиска (n_sent * 6) для устойчивости к числительным и аббревиатурам
    - Если не найдено в основном окне — расширяем поиск вперёд (recovery mode)
    - Два уровня порогов: 0.4 для основного окна, 0.3 для расширенного
    - При interpolated cursor двигается пропорционально, не сбивая последующие
    """
    from difflib import SequenceMatcher

    # Нормализованные слова Whisper (для сравнения)
    w_norms = [w["norm"] for w in whisper_words]
    total_w = len(w_norms)
    timings = []
    cursor = 0  # текущая позиция в потоке слов Whisper

    # Пропорция: сколько слов Whisper на одно слово скрипта (в среднем)
    total_script_words = sum(len(_normalize_words(s)) for s in sentences)
    words_ratio = total_w / max(total_script_words, 1)

    for sent_idx, sentence in enumerate(sentences):
        sent_words = _normalize_words(sentence)
        n_sent = len(sent_words)

        if n_sent == 0:
            if timings:
                prev = timings[-1]
                timings.append({"text": sentence, "start": prev["end"], "end": prev["end"], "duration": 0.0, "method": "empty"})
            else:
                timings.append({"text": sentence, "start": 0.0, "end": 0.0, "duration": 0.0, "method": "empty"})
            continue

        # --- Основной поиск: окно n_sent * 6 от cursor ---
        best_score = -1
        best_pos = cursor
        search_end = min(cursor + n_sent * 6, total_w)

        for pos in range(cursor, max(cursor + 1, search_end - n_sent + 1)):
            window = w_norms[pos:pos + n_sent]
            if not window:
                break
            score = SequenceMatcher(None, sent_words, window).ratio()
            if score > best_score:
                best_score = score
                best_pos = pos

        # --- Recovery: если основное окно не дало хорошего результата,
        #     ищем дальше (до cursor + n_sent * 15) ---
        if best_score < 0.4:
            recovery_start = search_end - n_sent + 1
            recovery_end = min(cursor + n_sent * 15, total_w)
            for pos in range(max(cursor, recovery_start), max(cursor + 1, recovery_end - n_sent + 1)):
                window = w_norms[pos:pos + n_sent]
                if not window:
                    break
                score = SequenceMatcher(None, sent_words, window).ratio()
                if score > best_score:
                    best_score = score
                    best_pos = pos

        # --- Определяем начало и конец ---
        if best_score >= 0.3:
            match_start = best_pos
            match_end = min(best_pos + n_sent, total_w) - 1
            start_time = whisper_words[match_start]["start"]
            end_time = whisper_words[match_end]["end"]
            cursor = match_end + 1
            method = f"matched({best_score:.2f})"
        else:
            # Не нашли — интерполируем, но двигаем cursor пропорционально
            # чтобы не сбить маппинг остальных предложений
            expected_w_count = max(1, round(n_sent * words_ratio))
            remaining_sents = len(sentences) - sent_idx
            remaining_words = total_w - cursor

            # Берём минимум из пропорционального и равномерного распределения
            words_for_this = min(expected_w_count, max(1, remaining_words // remaining_sents))

            match_start = cursor
            match_end = min(cursor + words_for_this, total_w) - 1

            if match_start < total_w:
                start_time = whisper_words[match_start]["start"]
                end_time = whisper_words[min(match_end, total_w - 1)]["end"]
            elif timings:
                start_time = timings[-1]["end"]
                end_time = start_time + 1.0
            else:
                start_time = 0.0
                end_time = 1.0

            cursor = match_end + 1
            method = f"interpolated({best_score:.2f})"

        duration = round(end_time - start_time, 2)
        if duration < 0.3:
            duration = 0.3
            end_time = start_time + duration

        gid = group_ids[sent_idx] if group_ids else sent_idx
        timings.append({
            "text": sentence,
            "start": round(start_time, 2),
            "end": round(end_time, 2),
            "duration": duration,
            "method": method,
            "group_id": gid,
        })

        split_mark = "✂" if group_ids and sent_idx > 0 and group_ids[sent_idx] == group_ids[sent_idx - 1] else " "
        print(f"   [{sent_idx+1:3d}/{len(sentences)}]{split_mark} {start_time:6.2f}s → {end_time:6.2f}s ({duration:.2f}s) {method}  «{sentence[:50]}»")

    # --- Финальная коррекция: убираем перекрытия и дыры ---
    for i in range(1, len(timings)):
        if timings[i]["start"] < timings[i-1]["end"]:
            timings[i]["start"] = timings[i-1]["end"]
            timings[i]["duration"] = round(timings[i]["end"] - timings[i]["start"], 2)
        # Если есть зазор — расширяем предыдущее до начала следующего
        gap = timings[i]["start"] - timings[i-1]["end"]
        if 0 < gap < 0.5:
            timings[i-1]["end"] = timings[i]["start"]
            timings[i-1]["duration"] = round(timings[i-1]["end"] - timings[i-1]["start"], 2)

    # Для половин одного предложения: end первой = start второй (точный стык)
    if group_ids:
        for i in range(len(timings) - 1):
            if group_ids[i] == group_ids[i + 1]:
                timings[i]["end"] = timings[i + 1]["start"]
                timings[i]["duration"] = round(timings[i]["end"] - timings[i]["start"], 2)

    # Последнее предложение — до конца аудио
    if timings and timings[-1]["end"] < audio_duration:
        timings[-1]["end"] = round(audio_duration, 2)
        timings[-1]["duration"] = round(timings[-1]["end"] - timings[-1]["start"], 2)

    return timings


def _fallback_timings(sentences, audio_duration):
    """Фоллбэк: распределение по количеству слов (как было раньше)."""
    wc = [max(len(s.split()), 1) for s in sentences]
    tw = sum(wc)
    timings, ct = [], 0.0
    for i, s in enumerate(sentences):
        d = max((wc[i] / tw) * audio_duration, 0.5)
        timings.append({"text": s, "start": round(ct, 2), "end": round(ct + d, 2), "duration": round(d, 2), "method": "fallback"})
        ct += d
    return timings

def _find_fallback_file(frames_dir, idx, total, ext, prefix):
    """Ищет ближайший существующий файл, если текущий пропущен."""
    # Ищем вперёд, потом назад
    for offset in range(1, total):
        for candidate in [idx + offset, idx - offset]:
            if 0 <= candidate < total:
                fp = os.path.join(frames_dir, f"{prefix}{candidate:04d}{ext}")
                if os.path.exists(fp):
                    return fp
    return None


def assemble_video_images(frames_dir, audio_path, timings, output, use_transitions=False):
    """Собирает видео из КАРТИНОК + аудио.
    Каждая картинка показывается от start текущего предложения до start следующего
    (включая зазоры между предложениями). Последняя — до конца аудио.
    Пропущенные кадры заменяются ближайшими.

    При use_transitions=True каждая картинка сначала конвертируется во временный
    mp4 нужной длительности, затем всё склеивается через xfade filter_complex
    (переходы размещаются в паузах между предложениями, см. lib/transitions.py)."""

    n = len(timings)
    if n == 0:
        print("❌ Нет таймингов!")
        return

    # Получаем точную длительность аудио
    audio_duration = _get_duration(audio_path)
    if audio_duration is None:
        audio_duration = timings[-1]["end"] + 1.0

    # Рассчитываем РЕАЛЬНУЮ длительность показа каждой картинки:
    # от start[i] до start[i+1], последняя — до конца аудио
    display_durations = []
    for i in range(n):
        if i < n - 1:
            dur = timings[i + 1]["start"] - timings[i]["start"]
        else:
            dur = audio_duration - timings[i]["start"]
        dur = max(dur, 0.1)  # минимум 0.1 сек
        display_durations.append(round(dur, 3))

    # --- Путь с xfade-переходами ---
    if use_transitions:
        from lib.transitions import (
            plan_boundaries, clip_source_durations, summarize, DEFAULT_SCALE_PAD,
        )
        whisper_words = _load_whisper_words(audio_path, frames_dir)
        video_name = os.path.basename(os.path.dirname(os.path.abspath(frames_dir)))
        boundaries = plan_boundaries(timings, whisper_words, audio_duration, video_name)
        source_durs = clip_source_durations(display_durations, boundaries)
        print(f"🎬 xfade: {summarize(boundaries)}")
        print(f"   ⚠️  Сборка с xfade — re-encode через libx264 (в 3-5 раз дольше обычной)")

        tmp_dir = os.path.join(frames_dir, "_xfade_tmp")
        os.makedirs(tmp_dir, exist_ok=True)
        parts = []
        used_count, fallback_count = 0, 0

        for i in range(n):
            fp = os.path.abspath(os.path.join(frames_dir, f"frame_{i:04d}.png"))
            if not os.path.exists(fp):
                fallback = _find_fallback_file(frames_dir, i, n, ".png", "frame_")
                if fallback:
                    fp = os.path.abspath(fallback)
                    fallback_count += 1
                    print(f"   ⚠️  frame_{i:04d}.png не найден → {os.path.basename(fallback)}")
                else:
                    print(f"   ❌ frame_{i:04d}.png — нет замены, пропуск")
                    continue
            else:
                used_count += 1

            d = source_durs[i]
            tmp_mp4 = os.path.join(tmp_dir, f"img_{i:04d}.mp4")
            cmd = (
                f'ffmpeg -y -loop 1 -t {d:.4f} -i "{fp}" '
                f'-vf "{DEFAULT_SCALE_PAD}" '
                f'-c:v libx264 -pix_fmt yuv420p -an -t {d:.4f} '
                f'"{tmp_mp4}" -loglevel error'
            )
            os.system(cmd)
            if os.path.exists(tmp_mp4):
                parts.append(tmp_mp4)
                print(f"   [{i+1:3d}/{n}] {timings[i]['start']:6.2f}s  dur={d:.3f}s  «{timings[i]['text'][:50]}»")

        total_visual = sum(display_durations)
        print(f"\n   📊 Кадров: {used_count} основных + {fallback_count} заменённых")
        print(f"   📊 Визуал: {total_visual:.2f}s / Аудио: {audio_duration:.2f}s")

        print("🎬 Сборка видео из картинок с xfade-переходами...")
        r = _ffmpeg_xfade(parts, audio_path, source_durs, boundaries, output, tmp_dir)

        # Чистим временные файлы
        try:
            for p in parts:
                if os.path.exists(p): os.remove(p)
            for f in os.listdir(tmp_dir):
                if f == "_filter.txt":
                    try: os.remove(os.path.join(tmp_dir, f))
                    except: pass
            os.rmdir(tmp_dir)
        except: pass

        print(f"✅ Видео готово: {output}" if r == 0 else "❌ Ошибка FFmpeg")
        return

    # --- Обычный путь через concat demuxer ---
    cf = os.path.join(frames_dir, "_concat.txt")
    used_count, fallback_count = 0, 0

    with open(cf, "w", encoding="utf-8") as f:
        for i in range(n):
            fp = os.path.abspath(os.path.join(frames_dir, f"frame_{i:04d}.png"))
            dur = display_durations[i]

            if not os.path.exists(fp):
                fallback = _find_fallback_file(frames_dir, i, n, ".png", "frame_")
                if fallback:
                    fp = os.path.abspath(fallback)
                    fallback_count += 1
                    print(f"   ⚠️  frame_{i:04d}.png не найден → {os.path.basename(fallback)}")
                else:
                    print(f"   ❌ frame_{i:04d}.png — нет замены, пропуск")
                    continue
            else:
                used_count += 1

            f.write(f"file '{fp}'\nduration {dur}\n")

            print(f"   [{i+1:3d}/{n}] {timings[i]['start']:6.2f}s  dur={dur:.3f}s  «{timings[i]['text'][:50]}»")

        # FFmpeg concat требует последний file без duration.
        # Записываем тот же последний файл ещё раз — он покажется ~1 кадр,
        # но к этому моменту всё уже отыграно, потому что мы включили
        # полную длительность в предыдущую запись.
        last_fp = os.path.abspath(os.path.join(frames_dir, f"frame_{n-1:04d}.png"))
        if not os.path.exists(last_fp):
            last_fp = _find_fallback_file(frames_dir, n - 1, n, ".png", "frame_")
        if last_fp:
            f.write(f"file '{os.path.abspath(last_fp)}'\n")

    total_visual = sum(display_durations)
    print(f"\n   📊 Кадров: {used_count} основных + {fallback_count} заменённых")
    print(f"   📊 Визуал: {total_visual:.2f}s / Аудио: {audio_duration:.2f}s")

    cmd = (f'ffmpeg -y -f concat -safe 0 -i "{cf}" -i "{audio_path}" '
           f'-c:v libx264 -pix_fmt yuv420p -vf "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2" '
           f'-c:a aac -b:a 192k -shortest "{output}"')
    print("🎬 Сборка видео...")
    r = os.system(cmd)
    try: os.remove(cf)
    except: pass
    print(f"✅ Видео готово: {output}" if r == 0 else "❌ Ошибка FFmpeg")


def _get_duration(filepath):
    """Получает длительность медиафайла через ffprobe."""
    import subprocess
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", filepath],
            capture_output=True, text=True
        )
        return float(json.loads(probe.stdout)["format"]["duration"])
    except Exception:
        return None


def _load_whisper_words(audio_path, output_dir):
    """Читает полный список слов из sentence_breakdown.json.

    Файл может лежать рядом с аудио (исторически) или в output_dir (frames/).
    Возвращает список вида [{word, norm, start, end}, ...] или [] если файла нет.
    """
    candidates = [
        os.path.join(output_dir, "sentence_breakdown.json"),
        os.path.join(os.path.dirname(audio_path), "sentence_breakdown.json"),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            try:
                with open(candidate, "r", encoding="utf-8") as f:
                    return json.load(f).get("whisper_words", []) or []
            except Exception:
                return []
    return []


def _ffmpeg_xfade(parts, audio_path, source_durs, boundaries, output, work_dir):
    """Финальная сборка видео через xfade filter_complex.

    parts           — список путей входных видео (уже нормализованных по длительности)
    audio_path      — путь к аудио-дорожке
    source_durs     — длительности parts (для построения offset'ов)
    boundaries      — список Boundary из lib.transitions.plan_boundaries
    output          — путь финального mp4
    work_dir        — рабочая папка (сюда пишется _filter.txt при необходимости)

    Использует re-encode через libx264 (xfade несовместим с -c:v copy).
    filter_complex пишется в файл (-filter_complex_script) всегда, а
    вызов идёт через subprocess.run(shell=False) — так на Windows работает
    лимит CreateProcess (~32K) вместо cmd.exe (8191 символ). При 150+
    клипах только список `-i` вылезал за cmd-лимит, даже когда
    filter_complex уже был в файле.
    """
    from lib.transitions import build_filter_complex

    if not parts:
        print("❌ Нет частей для сборки")
        return 1

    filt, final_label = build_filter_complex(source_durs, boundaries)
    audio_idx = len(parts)  # индекс аудио-входа

    # Собираем команду как список args для subprocess.run(shell=False).
    # Через os.system на Windows был лимит cmdline = 8191 символ, на 150+
    # клипах просто одни `-i "..."` вылезали за лимит → "The command line
    # is too long". У CreateProcess (shell=False) лимит 32768, + имена
    # файлов не проходят через shell-парсер, так что кавычки не нужны.
    args = ["ffmpeg", "-y"]
    for p in parts:
        args += ["-i", os.path.abspath(p)]
    args += ["-i", audio_path]

    # filter_complex всегда пишем в файл — и короткий, и длинный.
    # Так надёжнее: не зависим от экранирования в args, и cmdline не пухнет.
    fc_path = os.path.join(work_dir, "_filter.txt")
    with open(fc_path, "w", encoding="utf-8") as f:
        f.write(filt)
    args += ["-filter_complex_script", fc_path]

    args += [
        "-map", f"[{final_label}]",
        "-map", f"{audio_idx}:a",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", output,
        "-loglevel", "error",
    ]
    return subprocess.run(args, shell=False).returncode


def assemble_video_clips(clips_dir, audio_path, timings, output, use_transitions=False):
    """Собирает видео из ВИДЕОКЛИПОВ + аудио. Каждый клип подгоняется под длительность
    от start текущего предложения до start следующего (включая зазоры).
    Если клип короче нужного — последний кадр замораживается.
    Пропущенные клипы заменяются ближайшими.

    Сборка: все клипы обрезаются с точной длительностью, затем склеиваются
    через concat demuxer с принудительной нормализацией FPS/resolution.

    При use_transitions=True финальная склейка идёт через xfade filter_complex
    с размещением переходов в паузах между предложениями (см. lib/transitions.py)."""

    trimmed_dir = os.path.join(clips_dir, "_trimmed")
    os.makedirs(trimmed_dir, exist_ok=True)

    n = len(timings)
    if n == 0:
        print("❌ Нет таймингов!")
        return

    # Получаем точную длительность аудио
    audio_duration = _get_duration(audio_path)
    if audio_duration is None:
        audio_duration = timings[-1]["end"] + 1.0

    # Рассчитываем реальную длительность каждого клипа (display = на финальном таймлайне)
    display_durations = []
    for i in range(n):
        if i < n - 1:
            dur = timings[i + 1]["start"] - timings[i]["start"]
        else:
            dur = audio_duration - timings[i]["start"]
        dur = max(dur, 0.1)
        display_durations.append(round(dur, 3))

    # Если включены переходы — считаем boundaries и source-длительности клипов
    # (в исходнике каждый клип должен быть на transition_duration/2 длиннее по краям,
    # т.к. xfade «съедает» это время на стыках)
    boundaries = None
    if use_transitions:
        from lib.transitions import plan_boundaries, clip_source_durations, summarize
        whisper_words = _load_whisper_words(audio_path, clips_dir)
        video_name = os.path.basename(os.path.dirname(os.path.abspath(clips_dir)))
        boundaries = plan_boundaries(timings, whisper_words, audio_duration, video_name)
        source_durs = clip_source_durations(display_durations, boundaries)
        print(f"🎬 xfade: {summarize(boundaries)}")
        print(f"   ⚠️  Сборка с xfade — re-encode через libx264 (в 3-5 раз дольше обычной)")
    else:
        source_durs = display_durations

    parts = []
    fallback_count, frozen_count = 0, 0
    TARGET_FPS = 25

    for i in range(n):
        dur = source_durs[i]
        src = os.path.join(clips_dir, f"clip_{i:04d}.mp4")

        if not os.path.exists(src):
            fallback = _find_fallback_file(clips_dir, i, n, ".mp4", "clip_")
            if fallback:
                src = fallback
                fallback_count += 1
                print(f"   ⚠️  clip_{i:04d}.mp4 не найден → {os.path.basename(fallback)}")
            else:
                print(f"   ❌ clip_{i:04d}.mp4 — нет замены, пропуск")
                continue

        trimmed = os.path.join(trimmed_dir, f"part_{i:04d}.mp4")

        # Проверяем длительность исходного клипа
        clip_dur = _get_duration(src)
        status = ""

        # Рассчитываем точное кол-во кадров для нужной длительности
        target_frames = max(1, round(dur * TARGET_FPS))
        exact_dur = target_frames / TARGET_FPS

        if clip_dur is not None and clip_dur < dur - 0.1:
            # Клип короче чем нужно — делаем boomerang (forward+reverse loop),
            # чтобы не было статичной паузы. Двухпроходная схема:
            # 1) готовим boomerang_src = forward + reverse одного цикла
            # 2) зацикливаем boomerang_src через stream_loop до нужной длительности
            boomerang_src = os.path.join(trimmed_dir, f"boomerang_{i:04d}.mp4")
            # Шаг 1: forward + reverse в один файл
            # Именованные потоки [fwd]/[rev]/[out] требуют -filter_complex, не -vf
            cmd_boom = (f'ffmpeg -y -i "{src}" '
                        f'-filter_complex "[0:v]scale=1280:720:force_original_aspect_ratio=decrease,'
                        f'pad=1280:720:(ow-iw)/2:(oh-ih)/2,'
                        f'fps={TARGET_FPS},'
                        f'split[fwd][tmp];[tmp]reverse[rev];[fwd][rev]concat=n=2:v=1:a=0[out]" '
                        f'-map "[out]" '
                        f'-c:v libx264 -pix_fmt yuv420p -an '
                        f'-video_track_timescale {TARGET_FPS * 1000} '
                        f'"{boomerang_src}" -loglevel error')
            os.system(cmd_boom)

            if os.path.exists(boomerang_src) and _get_duration(boomerang_src):
                # Шаг 2: зацикливаем boomerang до нужной длительности
                cmd = (f'ffmpeg -y -stream_loop -1 -i "{boomerang_src}" '
                       f'-vf "trim=duration={exact_dur},setpts=PTS-STARTPTS" '
                       f'-c:v libx264 -pix_fmt yuv420p -an '
                       f'-video_track_timescale {TARGET_FPS * 1000} '
                       f'"{trimmed}" -loglevel error')
                status = f" [boomerang +{dur - clip_dur:.1f}s]"
            else:
                # Если boomerang не собрался (битый клип) — фоллбэк на stream_loop исходника
                cmd = (f'ffmpeg -y -stream_loop -1 -i "{src}" '
                       f'-vf "scale=1280:720:force_original_aspect_ratio=decrease,'
                       f'pad=1280:720:(ow-iw)/2:(oh-ih)/2,'
                       f'fps={TARGET_FPS},'
                       f'trim=duration={exact_dur},setpts=PTS-STARTPTS" '
                       f'-c:v libx264 -pix_fmt yuv420p -an '
                       f'-video_track_timescale {TARGET_FPS * 1000} '
                       f'"{trimmed}" -loglevel error')
                status = f" [loop fallback]"
            frozen_count += 1
        else:
            # Клип длиннее или равен — обрезаем с точным числом кадров
            cmd = (f'ffmpeg -y -i "{src}" '
                   f'-vf "scale=1280:720:force_original_aspect_ratio=decrease,'
                   f'pad=1280:720:(ow-iw)/2:(oh-ih)/2,'
                   f'fps={TARGET_FPS},'
                   f'trim=duration={exact_dur},setpts=PTS-STARTPTS" '
                   f'-c:v libx264 -pix_fmt yuv420p -an '
                   f'-video_track_timescale {TARGET_FPS * 1000} '
                   f'"{trimmed}" -loglevel error')

        os.system(cmd)

        if os.path.exists(trimmed):
            # Проверяем что получившийся файл правильной длины
            actual_dur = _get_duration(trimmed)
            if actual_dur is not None and actual_dur < dur - 0.5:
                print(f"   ⚠️  [{i+1:3d}/{n}] Клип {actual_dur:.1f}s < нужно {dur:.1f}s, пересоздаю через loop...")
                cmd2 = (f'ffmpeg -y -stream_loop -1 -i "{src}" '
                        f'-vf "scale=1280:720:force_original_aspect_ratio=decrease,'
                        f'pad=1280:720:(ow-iw)/2:(oh-ih)/2,'
                        f'fps={TARGET_FPS},'
                        f'trim=duration={exact_dur},setpts=PTS-STARTPTS" '
                        f'-c:v libx264 -pix_fmt yuv420p -an '
                        f'-video_track_timescale {TARGET_FPS * 1000} '
                        f'"{trimmed}" -loglevel error')
                os.system(cmd2)
                actual_dur = _get_duration(trimmed)
                status = f" [looped]"

            parts.append(trimmed)
            print(f"   [{i+1:3d}/{n}] {timings[i]['start']:6.2f}s  dur={dur:.3f}s{status}  «{timings[i]['text'][:50]}»")

    if not parts:
        print("❌ Нет обрезанных клипов!")
        return

    total_visual = sum(display_durations)
    print(f"\n   📊 Клипов: {len(parts)} (из них {fallback_count} заменённых, {frozen_count} растянутых)")
    print(f"   📊 Визуал: {total_visual:.2f}s / Аудио: {audio_duration:.2f}s")

    # Проверяем реальную суммарную длительность обрезанных клипов.
    # С xfade источники длиннее display на суммарный transition_duration —
    # сравниваем с source_durs, иначе с display.
    expected_parts_total = sum(source_durs)
    actual_total = 0
    for p in parts:
        d = _get_duration(p)
        if d: actual_total += d
    diff = abs(expected_parts_total - actual_total)
    if diff > 1.0:
        print(f"   ⚠️  Реальная длительность клипов: {actual_total:.2f}s (разница: {diff:.2f}s)")
    else:
        print(f"   ✅ Реальная длительность клипов: {actual_total:.2f}s — ОК")

    if use_transitions and boundaries is not None:
        print("🎬 Сборка видео из клипов с xfade-переходами...")
        r = _ffmpeg_xfade(parts, audio_path, source_durs, boundaries, output, trimmed_dir)
    else:
        cf = os.path.join(trimmed_dir, "_concat.txt")
        with open(cf, "w", encoding="utf-8") as f:
            for p in parts:
                f.write(f"file '{os.path.abspath(p)}'\n")

        cmd = (f'ffmpeg -y -f concat -safe 0 -i "{cf}" -i "{audio_path}" '
               f'-c:v copy -c:a aac -b:a 192k -shortest "{output}" -loglevel error')

        print("🎬 Сборка видео из клипов...")
        r = os.system(cmd)

    # Чистим временные файлы (включая boomerang-источники и xfade _filter.txt)
    try:
        for p in parts:
            if os.path.exists(p): os.remove(p)
        for f in os.listdir(trimmed_dir):
            if f.startswith("boomerang_") and f.endswith(".mp4"):
                try: os.remove(os.path.join(trimmed_dir, f))
                except: pass
            if f in ("_concat.txt", "_filter.txt"):
                try: os.remove(os.path.join(trimmed_dir, f))
                except: pass
        os.rmdir(trimmed_dir)
    except: pass

    print(f"✅ Видео готово: {output}" if r == 0 else "❌ Ошибка FFmpeg")

# ============================================================
# RETRY-ОБЁРТКА ДЛЯ ШАГА 3
# ============================================================
def _check_missing(prompts_count, output_dir, ext, prefix):
    """Возвращает список индексов, для которых файлы отсутствуют."""
    missing = []
    for i in range(prompts_count):
        if not os.path.exists(os.path.join(output_dir, f"{prefix}{i:04d}{ext}")):
            missing.append(i)
    return missing


def download_with_retry(download_fn, prompts, output_dir, ext, prefix, max_attempts=3):
    """Вызывает download_fn (idx_list) несколько раз, пока не будут скачаны все файлы.

    download_fn: callable(indices: list[int]) -> int (кол-во успешных)
    После каждой попытки проверяет ФАЙЛОВУЮ СИСТЕМУ, а не возврат функции,
    чтобы отловить случаи, когда функция соврала про успех.

    Возвращает: финальный список пропущенных индексов (пустой = успех).
    Между попытками бэкофф: 5, 10 секунд.
    """
    backoff = [5, 10]  # пауза перед 2-й и 3-й попыткой
    for attempt in range(1, max_attempts + 1):
        missing = _check_missing(len(prompts), output_dir, ext, prefix)
        if not missing:
            if attempt > 1:
                print(f"\n   🎯 Все файлы на месте после {attempt - 1} повтор(а/ов)")
            return []

        if attempt > 1:
            pause = backoff[min(attempt - 2, len(backoff) - 1)]
            print(f"\n   🔁 Попытка {attempt}/{max_attempts}: не хватает {len(missing)} шт.")
            print(f"   ⏳ Пауза {pause}с перед повтором...")
            time.sleep(pause)
            print(f"   Индексы для повтора: {[m + 1 for m in missing]}")
        else:
            print(f"\n   🚀 Попытка {attempt}/{max_attempts}: скачиваю/генерирую {len(missing)} шт.")

        try:
            download_fn(missing)
        except Exception as e:
            print(f"   ⚠️  Ошибка на попытке {attempt}: {e}")

    # Финальная проверка
    missing = _check_missing(len(prompts), output_dir, ext, prefix)
    return missing


# ============================================================
# ГЛАВНАЯ ФУНКЦИЯ
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="YouTube Video Generator v5")
    parser.add_argument("--init", action="store_true")
    parser.add_argument("-s", "--script")
    parser.add_argument("-a", "--audio")
    parser.add_argument("-c", "--channel")
    parser.add_argument("-o", "--output-dir", default="frames")
    # default=None — если юзер не указал явно, вычислим путь рядом с output_dir
    # (чтобы final_video.mp4 лежал в папке видео, а не в CWD).
    parser.add_argument("--video-output", default=None)
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--dry-run", action="store_true", help="[deprecated] то же что --split-only")
    parser.add_argument("--split-only", action="store_true", help="Только разбивка сценария на предложения")
    parser.add_argument("--prompts-only", action="store_true", help="Только генерация промптов/ключевых слов")
    parser.add_argument("--images-only", action="store_true", help="Только генерация визуала (промпты должны уже быть)")
    parser.add_argument("--assemble-only", action="store_true", help="Только сборка видео (визуал и аудио должны уже быть)")
    parser.add_argument("--all", action="store_true", help="Все этапы подряд")
    parser.add_argument("--transitions", action="store_true", help="xfade-переходы между клипами в паузах речи")
    args = parser.parse_args()

    # Если --video-output не задан — кладём рядом с output_dir (в родительскую
    # папку), чтобы при прямом вызове из CLI финальное видео попадало в папку
    # видео, а не в CWD. start.py всегда передаёт абсолютный путь сам.
    if args.video_output is None:
        parent = os.path.dirname(os.path.abspath(args.output_dir)) or "."
        args.video_output = os.path.join(parent, "final_video.mp4")

    # Обратная совместимость: --dry-run ≡ --split-only
    if args.dry_run:
        args.split_only = True

    # Определяем режим: если не указан ни один — это обычный полный прогон (--all поведение).
    # Если указан конкретный этап — выполняем только его.
    stage_flags = [args.split_only, args.prompts_only, args.images_only, args.assemble_only]
    if sum(stage_flags) > 1:
        print("❌ Укажите только один этап (--split-only / --prompts-only / --images-only / --assemble-only) или --all")
        return
    run_all = args.all or not any(stage_flags)

    if args.init: save_default_config(args.config); return
    if not args.script: parser.print_help(); return
    if not os.path.isfile(args.script): print(f"❌ {args.script} не найден"); return

    print("\n" + "="*60)
    print("  🎬 YouTube Video Generator v5")
    print("="*60)

    needs_llm = run_all or args.prompts_only
    needs_vis = not args.split_only and not args.assemble_only

    # --- Автоопределение типа визуала для assemble-only ---
    auto_vis = None
    if args.assemble_only:
        if not os.path.isdir(args.output_dir):
            print(f"\n  ❌ Папка {args.output_dir} не найдена — нечего собирать")
            return
        has_frames = any(f.startswith("frame_") and f.endswith(".png") for f in os.listdir(args.output_dir))
        has_clips = any(f.startswith("clip_") and f.endswith(".mp4") for f in os.listdir(args.output_dir))
        if has_frames and not has_clips:
            auto_vis = "kie"
            print(f"\n  🔍 Обнаружены картинки — режим сборки из картинок")
        elif has_clips and not has_frames:
            auto_vis = "pexels"
            print(f"\n  🔍 Обнаружены клипы — режим сборки из видеоклипов")
        elif has_frames and has_clips:
            print(f"\n  ⚠️  В {args.output_dir} есть и картинки, и клипы")
            ac = input("  Собирать из: [1] картинок  [2] клипов? Выбор: ").strip()
            auto_vis = "pexels" if ac == "2" else "kie"
        else:
            print(f"\n  ❌ В {args.output_dir} нет ни frame_*.png, ни clip_*.mp4 — нечего собирать")
            return

    llm = "deepseek"
    if needs_llm:
        print("\n  Кто пишет промпты?")
        print("    [1] DeepSeek  — ~$0.01")
        print("    [2] OpenAI    — ~$0.03")
        lc = input("  Выбор (1/2): ").strip()
        llm = "deepseek" if lc != "2" else "openai"

    if auto_vis is not None:
        vis = auto_vis
    elif needs_vis:
        print("\n  Визуал:")
        print("    [1] Kie API (z-image)     — картинки, $0.004/шт")
        print("    [2] Replicate (FLUX)      — картинки, $0.003/шт")
        print("    [3] Pexels (видео)        — стоковое видео, БЕСПЛАТНО")
        print("    [4] Pixabay (видео)       — стоковое видео, БЕСПЛАТНО")
        print("    [5] Pexels (фото 16:9)    — стоковые фото, БЕСПЛАТНО")
        print("    [6] Pixabay (фото 16:9)   — стоковые фото, БЕСПЛАТНО")
        ic = input("  Выбор (1-6): ").strip()
        if ic == "2": vis = "replicate"
        elif ic == "3": vis = "pexels"
        elif ic == "4": vis = "pixabay"
        elif ic == "5": vis = "pexels_photo"
        elif ic == "6": vis = "pixabay_photo"
        else: vis = "kie"
    else:
        vis = "kie"  # не используется, но должен быть определён

    # Конфиг
    config = load_config(args.config)
    style, topic = "digital illustration, cinematic lighting, vibrant colors, 4k", ""
    if args.channel and args.channel in config.get("channels", {}):
        ch = config["channels"][args.channel]
        style, topic = ch.get("style", style), ch.get("topic", "")

    vis_names = {"kie":"Kie API (z-image)","replicate":"Replicate (FLUX)","pexels":"Pexels (видео)","pixabay":"Pixabay (видео)","pexels_photo":"Pexels (фото 16:9)","pixabay_photo":"Pixabay (фото 16:9)"}
    vis_prices = {"kie":0.004,"replicate":0.003,"pexels":0.0,"pixabay":0.0,"pexels_photo":0.0,"pixabay_photo":0.0}
    llm_names = {"deepseek":"DeepSeek","openai":"OpenAI"}

    print(f"\n  {'─'*50}")
    print(f"  📺 Канал:    {args.channel or '—'}")
    print(f"  🧠 Промпты:  {llm_names[llm]}")
    print(f"  🖼️  Визуал:   {vis_names[vis]}")
    print(f"  {'─'*50}")

    # ШАГ 1
    print(f"\n{'='*60}")
    print("📄 ШАГ 1: Разбивка сценария")
    print("="*60)
    text = Path(args.script).read_text(encoding="utf-8")
    sentences, group_ids = split_into_sentences_with_groups(text)
    n = len(sentences)
    n_groups = max(group_ids) + 1 if group_ids else n
    n_splits = n - n_groups  # сколько предложений было разбито на части
    price = vis_prices[vis]

    print(f"   {n} частей из {n_groups} предложений" + (f" ({n_splits} разбито)" if n_splits else ""))
    if needs_vis:
        cost_str = "БЕСПЛАТНО" if vis in ("pexels", "pixabay", "pexels_photo", "pixabay_photo") else f"~${n*price:.2f}"
        print(f"\n💰 Визуал ({vis_names[vis]}): {cost_str}")

    os.makedirs(args.output_dir, exist_ok=True)

    # Сохраняем разбивку предложений — это файл-якорь для Whisper
    sentences_file = os.path.join(args.output_dir, "sentences.json")
    with open(sentences_file, "w", encoding="utf-8") as f:
        json.dump([{"index": i, "text": s, "group_id": group_ids[i]} for i, s in enumerate(sentences)], f, ensure_ascii=False, indent=2)
    print(f"   📄 Разбивка сохранена: {sentences_file}")

    if args.split_only:
        print(f"\n🏃 Первые 10 частей:\n")
        for i, s in enumerate(sentences[:10]):
            gmark = f" [g{group_ids[i]}]" if group_ids[i] != i else ""
            print(f"   [{i+1}]{gmark} {s}")
        if n > 10: print(f"\n   ... и ещё {n-10}")
        print(f"\n✅ Разбивка готова ({n} частей, {n_groups} предложений)")
        return

    # ШАГ 2: Промпты / Ключевые слова
    pf = os.path.join(args.output_dir, "prompts.json")

    if args.assemble_only:
        # Для сборки промпты не нужны — проверяем только наличие визуала
        # по реально существующим файлам (тип уже определён в auto_vis).
        ext, prefix = (".mp4", "clip_") if auto_vis in ("pexels", "pixabay") else (".png", "frame_")
        missing = _check_missing(len(sentences), args.output_dir, ext, prefix)
        if missing:
            kind = "клипов" if ext == ".mp4" else "картинок"
            have = len(sentences) - len(missing)
            print(f"\n❌ Не хватает {kind}: есть {have} из {len(sentences)}")
            print(f"   Пропущены индексы (1-based): {[m + 1 for m in missing]}")
            print(f"   Ожидаются файлы вида: {prefix}NNNN{ext} (NNNN = 0000..{len(sentences)-1:04d})")
            return
        print(f"\n   ✅ Визуал на месте: {len(sentences)} шт")
    elif args.images_only:
        # Читаем существующие промпты — без них не обойтись дальше
        if not os.path.exists(pf):
            print(f"\n❌ {pf} не найден. Сначала сгенерируйте промпты (--prompts-only).")
            return
        with open(pf, "r", encoding="utf-8") as f: saved = json.load(f)
        prompts = [x["prompt"] for x in saved]
        print(f"\n   ✅ Загружено промптов: {len(prompts)}")
    else:
        print(f"\n{'='*60}")
        if vis in ("pexels", "pixabay", "pexels_photo", "pixabay_photo"):
            print(f"🔑 ШАГ 2: Ключевые слова через {llm_names[llm]}")
        else:
            print(f"🧠 ШАГ 2: Промпты через {llm_names[llm]}")
        print("="*60)

        if os.path.exists(pf):
            with open(pf, "r", encoding="utf-8") as f: saved = json.load(f)
            prompts = [x["prompt"] for x in saved]
            print(f"   ✅ Уже есть ({len(prompts)} шт) — пропускаю")
        else:
            if vis in ("pexels", "pixabay", "pexels_photo", "pixabay_photo"):
                prompts = generate_keywords_llm(sentences, topic, llm)
            else:
                prompts = generate_prompts_llm(sentences, style, topic, llm)
            with open(pf, "w", encoding="utf-8") as f:
                json.dump([{"i":i,"text":s,"prompt":p} for i,(s,p) in enumerate(zip(sentences,prompts))], f, ensure_ascii=False, indent=2)

    if args.prompts_only:
        print(f"\n✅ Промпты готовы ({len(prompts)} шт): {pf}")
        return

    # ШАГ 3: Визуал (пропускаем в режиме assemble-only)
    if not args.assemble_only:
        print(f"\n{'='*60}")
        print(f"🖼️  ШАГ 3: {vis_names[vis]}")
        print("="*60)

        if vis in ("pexels", "pixabay"):
            ext, prefix = ".mp4", "clip_"
            missing_initial = _check_missing(len(prompts), args.output_dir, ext, prefix)
            existing = len(prompts) - len(missing_initial)

            if not missing_initial:
                print(f"   ✅ Все {existing} клипов есть — пропускаю")
            else:
                print(f"   Есть: {existing}, нужно: {len(missing_initial)}")

                if vis == "pexels":
                    token = os.environ.get("PEXELS_API_KEY", "")
                    if not token:
                        print("❌ PEXELS_API_KEY не найден!")
                        print("   Получить: https://www.pexels.com/api/")
                        return
                    used_file = os.path.join(args.output_dir, "used_pexels_ids.json")
                    used_ids = set()
                    if os.path.exists(used_file):
                        with open(used_file, "r") as f: used_ids = set(json.load(f))

                    def _dl(indices):
                        n_ok = search_and_download_pexels(prompts, indices, args.output_dir, token, used_ids)
                        with open(used_file, "w") as f: json.dump(list(used_ids), f)
                        return n_ok
                else:
                    token = os.environ.get("PIXABAY_API_KEY", "")
                    if not token:
                        print("❌ PIXABAY_API_KEY не найден!")
                        print("   Получить: https://pixabay.com/api/docs/")
                        return
                    used_file = os.path.join(args.output_dir, "used_pixabay_ids.json")
                    used_ids = set()
                    if os.path.exists(used_file):
                        with open(used_file, "r") as f: used_ids = set(json.load(f))

                    def _dl(indices):
                        n_ok = search_and_download_pixabay(prompts, indices, args.output_dir, token, used_ids)
                        with open(used_file, "w") as f: json.dump(list(used_ids), f)
                        return n_ok

                still_missing = download_with_retry(_dl, prompts, args.output_dir, ext, prefix, max_attempts=3)
                n_total, n_got = len(prompts), len(prompts) - len(still_missing)
                print(f"\n   📊 Итого клипов: {n_got}/{n_total}")

                if still_missing:
                    print(f"\n   ⚠️  Не хватает визуала для {len(still_missing)} предложений:")
                    print(f"   Индексы: {[m + 1 for m in still_missing]}")
                    if args.images_only:
                        print("   Скрипт останавливается (--images-only).")
                        return
                    # Для --all / интерактива: спрашиваем, продолжать ли со сборкой
                    ans = input(f"\n   Продолжить сборку с заменой пропусков на ближайшие клипы? (y/n): ").strip().lower()
                    if ans != "y":
                        print("   Остановлено пользователем.")
                        return
        elif vis in ("pexels_photo", "pixabay_photo"):
            ext, prefix = ".png", "frame_"
            missing_initial = _check_missing(len(prompts), args.output_dir, ext, prefix)
            existing = len(prompts) - len(missing_initial)

            if not missing_initial:
                print(f"   ✅ Все {existing} фото есть — пропускаю")
            else:
                print(f"   Есть: {existing}, нужно: {len(missing_initial)}")

                if vis == "pexels_photo":
                    token = os.environ.get("PEXELS_API_KEY", "")
                    if not token:
                        print("❌ PEXELS_API_KEY не найден!")
                        print("   Получить: https://www.pexels.com/api/")
                        return
                    used_file = os.path.join(args.output_dir, "used_pexels_photo_ids.json")
                    used_ids = set()
                    if os.path.exists(used_file):
                        with open(used_file, "r") as f: used_ids = set(json.load(f))

                    def _dl(indices):
                        n_ok = search_and_download_pexels_photos(prompts, indices, args.output_dir, token, used_ids)
                        with open(used_file, "w") as f: json.dump(list(used_ids), f)
                        return n_ok
                else:
                    token = os.environ.get("PIXABAY_API_KEY", "")
                    if not token:
                        print("❌ PIXABAY_API_KEY не найден!")
                        print("   Получить: https://pixabay.com/api/docs/")
                        return
                    used_file = os.path.join(args.output_dir, "used_pixabay_photo_ids.json")
                    used_ids = set()
                    if os.path.exists(used_file):
                        with open(used_file, "r") as f: used_ids = set(json.load(f))

                    def _dl(indices):
                        n_ok = search_and_download_pixabay_photos(prompts, indices, args.output_dir, token, used_ids)
                        with open(used_file, "w") as f: json.dump(list(used_ids), f)
                        return n_ok

                still_missing = download_with_retry(_dl, prompts, args.output_dir, ext, prefix, max_attempts=3)
                n_total, n_got = len(prompts), len(prompts) - len(still_missing)
                print(f"\n   📊 Итого фото: {n_got}/{n_total}")

                if still_missing:
                    print(f"\n   ⚠️  Не хватает визуала для {len(still_missing)} предложений:")
                    print(f"   Индексы: {[m + 1 for m in still_missing]}")
                    if args.images_only:
                        print("   Скрипт останавливается (--images-only).")
                        return
                    ans = input(f"\n   Продолжить сборку с заменой пропусков на ближайшие фото? (y/n): ").strip().lower()
                    if ans != "y":
                        print("   Остановлено пользователем.")
                        return
        else:
            # Картинки
            ext, prefix = ".png", "frame_"
            missing_initial = _check_missing(len(prompts), args.output_dir, ext, prefix)
            existing = len(prompts) - len(missing_initial)

            if not missing_initial:
                print(f"   ✅ Все {existing} есть — пропускаю")
            else:
                cost = len(missing_initial) * price
                print(f"   Есть: {existing}, нужно: {len(missing_initial)}")
                if input(f"\n   Генерировать {len(missing_initial)} шт (~${cost:.2f})? (y/n): ").strip().lower() != "y": return

                if vis == "kie":
                    token = os.environ.get("KIE_API_KEY","")
                    if not token: print("❌ KIE_API_KEY!"); return
                    def _dl(indices):
                        return generate_images_kie(prompts, indices, args.output_dir, token)
                else:
                    token = os.environ.get("REPLICATE_API_TOKEN","")
                    if not token: print("❌ REPLICATE_API_TOKEN!"); return
                    def _dl(indices):
                        return generate_images_replicate(prompts, indices, args.output_dir, token)

                still_missing = download_with_retry(_dl, prompts, args.output_dir, ext, prefix, max_attempts=3)
                n_total, n_got = len(prompts), len(prompts) - len(still_missing)
                print(f"\n   📊 Итого картинок: {n_got}/{n_total}")

                if still_missing:
                    print(f"\n   ⚠️  Не хватает визуала для {len(still_missing)} предложений:")
                    print(f"   Индексы: {[m + 1 for m in still_missing]}")
                    if args.images_only:
                        print("   Скрипт останавливается (--images-only).")
                        return
                    ans = input(f"\n   Продолжить сборку с заменой пропусков на ближайшие картинки? (y/n): ").strip().lower()
                    if ans != "y":
                        print("   Остановлено пользователем.")
                        return

    if args.images_only:
        print(f"\n✅ Визуал готов")
        return

    # ШАГ 4-5: Whisper + сборка
    if args.assemble_only and not args.audio:
        print(f"\n❌ Для сборки нужен -a audio.mp3")
        return

    if args.audio:
        if not os.path.isfile(args.audio): print(f"❌ {args.audio} не найден"); return

        print(f"\n{'='*60}")
        print("🎙️  ШАГ 4: Тайминги через Whisper")
        print("="*60)
        timings = get_timings(args.audio, sentences, group_ids)

        print(f"\n{'='*60}")
        print("🎬 ШАГ 5: Сборка видео")
        print("="*60)

        # Определяем тип сборки по реально существующим файлам в output_dir,
        # а не только по выбранному vis — так assemble-only работает корректно
        # независимо от того, что было выбрано в меню.
        has_frames = any(f.startswith("frame_") and f.endswith(".png") for f in os.listdir(args.output_dir))
        has_clips = any(f.startswith("clip_") and f.endswith(".mp4") for f in os.listdir(args.output_dir))

        if has_clips and not has_frames:
            assemble_video_clips(args.output_dir, args.audio, timings, args.video_output, use_transitions=args.transitions)
        elif has_frames and not has_clips:
            assemble_video_images(args.output_dir, args.audio, timings, args.video_output, use_transitions=args.transitions)
        elif vis in ("pexels", "pixabay"):
            assemble_video_clips(args.output_dir, args.audio, timings, args.video_output, use_transitions=args.transitions)
        else:
            assemble_video_images(args.output_dir, args.audio, timings, args.video_output, use_transitions=args.transitions)
    else:
        print(f"\n💡 Для видео: добавь -a voiceover.mp3")

    print(f"\n🎉 Готово!")

if __name__ == "__main__":
    main()
