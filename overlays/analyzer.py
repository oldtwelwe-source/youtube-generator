"""
Analyzer — анализирует сценарий через OpenAI (gpt-4.1-mini) и генерирует
overlays.json для рендера motion-graphics оверлеев.

Разделение ответственности:
  - LLM решает ЧТО показывать (тип компонента, текст/число, когда, как долго)
  - Python решает КАК показывать (цвета, шрифт, интенсивность — из overlay_style канала)
Это даёт консистентность стиля канала: LLM не видит цветов, не может их выдумать,
а стиль канала меняется за 30 секунд правкой config.json без переписывания промпта.

Использование:
    python analyzer.py --video finance/test --channel finance

Требует OPENAI_API_KEY в переменных окружения.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


# OpenAI chat-completions endpoint (тот же что и для генерации промптов в generate.py)
OPENAI_ENDPOINT = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL = "gpt-4.1-mini"

# Максимум токенов на ответ — 8000 с запасом на 10-15 оверлеев + reasoning
DEFAULT_MAX_TOKENS = 8000

# Типы компонентов и обязательные параметры — для валидации ответа модели.
# Должно точно соответствовать компонентам в overlays/remotion/src/components/.
# Позиции: 9-точечная сетка. Некоторые компоненты позиционируются автоматически —
# для них position от модели игнорируется.
COMPONENT_SPECS = {
    "NumberReveal": {
        "required": ["value", "position"],
        "optional": ["caption"],
        "uses_position": True,
    },
    "NamedHighlight": {
        "required": ["text", "position"],
        "optional": [],
        "uses_position": True,
    },
    "LocationLabel": {
        "required": ["location_name", "position"],
        "optional": [],
        "uses_position": True,
    },
    "SectionTitle": {
        "required": ["number", "title"],
        "optional": [],
        "uses_position": False,  # всегда по центру экрана
    },
    "QuoteCard": {
        "required": ["quote_text"],
        "optional": ["author"],
        "uses_position": False,  # всегда по центру экрана
    },
    "ProgressBar": {
        "required": ["label", "value_percent"],
        "optional": ["value_display"],
        "uses_position": False,  # позиционируется автоматически
    },
    # KeywordPop и Chapter сознательно исключены:
    # - KeywordPop не соответствует документальному тону (эмоциональные "БУМ!" вставки)
    # - Chapter — длинная HUD-полоска, отключена по продуктовому решению
    # Компоненты остаются в Remotion для превью в Studio, но analyzer их не генерит.
}

# Нижняя треть экрана зарезервирована под YouTube-субтитры — оверлеи туда не ставим.
VALID_POSITIONS_9 = {
    "top-left", "top-center", "top-right",
    "middle-left", "middle-center", "middle-right",
}


def _detect_language(script: str) -> str:
    """Простая автодетекция языка сценария.

    Считаем долю кириллических букв среди всех букв. Если > 30% — русский,
    иначе английский. Цифры/пунктуация игнорируются (иначе английский сценарий
    с датами/числами мог бы перекосить долю).
    """
    cyr = 0
    lat = 0
    for ch in script:
        if "а" <= ch.lower() <= "я" or ch.lower() == "ё":
            cyr += 1
        elif "a" <= ch.lower() <= "z":
            lat += 1
    total = cyr + lat
    if total == 0:
        return "en"
    return "ru" if (cyr / total) > 0.3 else "en"


def _build_system_prompt() -> str:
    """Собирает системный промпт с описанием задачи и контракта компонентов."""
    return """Ты — motion-graphics дизайнер для YouTube-видео в документальном стиле. Твоя задача: проанализировать сценарий и расставить сдержанные оверлеи-акценты, которые помогают зрителю усвоить ключевые факты. Это НЕ развлекательные вставки и НЕ реакционные мемы — это информационная надстройка поверх документального повествования.

## Что ты решаешь
1. ТИП оверлея (из 6 доступных — см. ниже)
2. СОДЕРЖАНИЕ: текст/число на основе сценария
3. КОГДА показать (start_time в секундах — обязательно синхронно с моментом произнесения в аудио)
4. КАК ДОЛГО (duration_seconds — обычно 2-4 секунды)

## Что ты НЕ решаешь
- Цвета, шрифты, интенсивность анимации — это стиль канала, добавится автоматически
- Разрешение/позицию макета — фиксировано 1280x720

## ЯЗЫК ОВЕРЛЕЕВ — КРИТИЧЕСКИ ВАЖНО
Весь текст в оверлеях (value, caption, text, location_name, title, label, quote_text, chapter_name, и т.д.) ДОЛЖЕН быть на том же языке, что и сценарий. Если сценарий английский — оверлеи на английском. Если русский — на русском. Язык передаётся явно в user-сообщении. Никогда не смешивай языки и не переводи содержание сценария на другой язык.

## Доступные компоненты

### NumberReveal — число/дата/сумма
Когда: в сценарии упомянуты конкретные цифры (год, процент, сумма, статистика).
Параметры:
- value (строка): "1998", "$1.2M", "500%", "3 декабря 1999"
- caption (строка, опционально): короткая подпись под числом — "год", "рост", "украдено"
- position: одно из "top-left" "top-center" "top-right" "middle-left" "middle-center" "middle-right". НИЖНЯЯ ТРЕТЬ ЗАПРЕЩЕНА (там субтитры YouTube).

### NamedHighlight — имя или термин
Когда: упоминается значимое имя (человек, компания, термин), которое нужно подсветить.
Параметры:
- text: "Сергей Мавроди", "Goldman Sachs", "quantitative easing"
- position: top-*/middle-* (без bottom-*)

### LocationLabel — метка места
Когда: упоминается локация (город, страна, улица, биржа).
Параметры:
- location_name: "Москва", "Wall Street", "Zurich"
- position: top-*/middle-* (без bottom-*)

### SectionTitle — заставка смены темы (полноэкранная, по центру)
Когда: сценарий переходит к новой крупной теме/разделу. Использовать умеренно — 1-3 раза на видео, не на каждый абзац.
Параметры:
- number: "1", "2", "3" (номер раздела, выведется как "№1")
- title: "Первые шаги МММ", "Pyramid Collapse"

### QuoteCard — карточка для цитаты (по центру)
Когда: в сценарии приводится прямая цитата известного человека. Только если цитата буквально звучит в аудио.
Параметры:
- quote_text: сам текст цитаты (≤150 символов)
- author (опционально): имя автора

### ProgressBar — горизонтальный бар процента/статистики
Когда: упоминается процентное значение или сравнение (инфляция, рост, доля).
Параметры:
- label: короткое описание — "Инфляция 1992", "Market growth"
- value_percent: число 0-100 (визуальное заполнение бара)
- value_display (опционально): что написать справа — "2500%", "$1.2M", "×25"

## Правила и ограничения (соблюдать СТРОГО)

### Плотность
- На 60 секунд видео — 4-6 оверлеев. Не 10, не 15. Лучше меньше, но точнее.
- Между любыми двумя оверлеями — минимум 4 секунды.
- Не более 1 SectionTitle на каждые 40 секунд видео.

### Типы подряд
- Два оверлея одного и того же type НЕ должны идти подряд. Если после NumberReveal напрашивается ещё одно число — либо пропусти (не всё надо подсвечивать), либо используй другой тип, либо разнеси их другим типом.
- Максимум 2 оверлея одного type подряд при невозможности иначе, но цель — 0.

### Запрет дубликатов по содержанию
- Каждая цифра/имя/место/факт упоминается оверлеем МАКСИМУМ ОДИН РАЗ за всё видео.
- Запрещено дублировать один факт разными типами. Если "3 из 4" уже показано как NumberReveal — не добавляй KeywordPop/NamedHighlight с тем же содержанием.

### Триггеры — что подсвечивать
Оверлей уместен для:
- конкретных цифр, дат, сумм (NumberReveal, ProgressBar)
- имён людей, компаний, брендов (NamedHighlight)
- географических мест (LocationLabel)
- настоящих цитат (QuoteCard)
- переходов к крупному новому разделу (SectionTitle)

Оверлей НЕ нужен для:
- общих фраз, пересказа, связок
- эмоциональных восклицаний сценариста
- каждого предложения

### Формат
- start_time должен попадать в момент, когда в аудио звучит соответствующее содержание
- duration_seconds: NumberReveal/NamedHighlight/LocationLabel 2.5-3s, QuoteCard 3.5-5s, SectionTitle 2.5-3s, ProgressBar 3-4s
- position: запрещены bottom-left/bottom-center/bottom-right (зона YouTube-субтитров)
- id формата "overlay_001", "overlay_002", ... в порядке start_time
- reasoning: 1 короткое предложение на языке сценария, почему именно этот оверлей и именно в этот момент

Всегда отвечай вызовом инструмента submit_overlays."""


def _build_user_prompt(
    script: str,
    timings: list,
    audio_duration: float,
    channel_topic: str,
    channel_name: str,
    language: str,
) -> str:
    """Собирает user-сообщение с конкретным сценарием для анализа."""
    # Таймлайн предложений — основной контекст для выбора start_time
    timeline_lines = []
    for i, s in enumerate(timings):
        timeline_lines.append(
            f"  [{i+1:02d}] {s['start']:6.2f}s — {s['end']:6.2f}s : {s['text']}"
        )
    timeline_str = "\n".join(timeline_lines)

    lang_label = {"ru": "русский", "en": "английский"}.get(language, language)

    return f"""Канал: {channel_name}
Тематика канала: {channel_topic}
Длительность видео: {audio_duration:.1f} секунд
Язык сценария: {lang_label} ({language})

ВАЖНО: все тексты внутри оверлеев (value, caption, text, location_name, title, \
quote_text, author, label, value_display) ДОЛЖНЫ быть на языке "{language}". \
Не переводи на другой язык, не смешивай языки.

## Полный сценарий
{script}

## Таймлайн произнесения (из Whisper)
{timeline_str}

Проанализируй сценарий и вызови submit_overlays со списком motion-графических оверлеев. \
Каждый start_time должен попадать внутрь окна соответствующего предложения из таймлайна."""


def _build_tool_schema() -> dict:
    """Function для OpenAI function calling — модель обязательно вернёт структурированный JSON.

    Формат: OpenAI wrapper {type: function, function: {...}}. Внутри function
    parameters — это стандартный JSON Schema (то же что input_schema у Anthropic,
    просто поле называется иначе).
    """
    return {
        "type": "function",
        "function": {
            "name": "submit_overlays",
            "description": "Возвращает список motion-графических оверлеев для видео в хронологическом порядке",
            "parameters": {
                "type": "object",
                "properties": {
                    "overlays": {
                        "type": "array",
                        "description": "Массив оверлеев, отсортированных по start_time",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {
                                    "type": "string",
                                    "description": "Уникальный id: overlay_001, overlay_002, ...",
                                },
                                "type": {
                                    "type": "string",
                                    "enum": list(COMPONENT_SPECS.keys()),
                                    "description": "Тип компонента",
                                },
                                "start_time": {
                                    "type": "number",
                                    "description": "Момент появления оверлея в секундах от начала видео",
                                },
                                "duration_seconds": {
                                    "type": "number",
                                    "description": "Длительность оверлея в секундах",
                                },
                                "reasoning": {
                                    "type": "string",
                                    "description": "Одно короткое предложение: почему этот оверлей в этот момент",
                                },
                                "params": {
                                    "type": "object",
                                    "description": (
                                        "Параметры компонента. ВСЕ поля компонента ОБЯЗАТЕЛЬНО "
                                        "кладутся сюда, а не в корень оверлея. Какие именно поля "
                                        "заполнять — зависит от type (см. ниже). Используй ТОЛЬКО "
                                        "перечисленные ниже имена полей, без синонимов."
                                    ),
                                    "properties": {
                                        "value": {
                                            "type": "string",
                                            "description": "NumberReveal: число/дата/сумма строкой, например '1998', '$1.2M', '500%'",
                                        },
                                        "caption": {
                                            "type": "string",
                                            "description": "NumberReveal (опционально): короткая подпись под числом, например 'год', 'рост'",
                                        },
                                        "text": {
                                            "type": "string",
                                            "description": "NamedHighlight: имя человека/компании/термин, который подсвечиваем",
                                        },
                                        "location_name": {
                                            "type": "string",
                                            "description": "LocationLabel: название места — 'Москва', 'Уолл-стрит'",
                                        },
                                        "number": {
                                            "type": "string",
                                            "description": "SectionTitle: номер раздела строкой — '1', '2', '3'",
                                        },
                                        "title": {
                                            "type": "string",
                                            "description": "SectionTitle: заголовок раздела",
                                        },
                                        "quote_text": {
                                            "type": "string",
                                            "description": "QuoteCard: сам текст цитаты (≤150 символов)",
                                        },
                                        "author": {
                                            "type": "string",
                                            "description": "QuoteCard (опционально): автор цитаты",
                                        },
                                        "label": {
                                            "type": "string",
                                            "description": "ProgressBar: короткое описание — 'Инфляция 1992'",
                                        },
                                        "value_percent": {
                                            "type": "number",
                                            "description": "ProgressBar: число 0-100 для визуального заполнения бара",
                                        },
                                        "value_display": {
                                            "type": "string",
                                            "description": "ProgressBar (опционально): что написать справа — '2500%', 'в 25 раз'",
                                        },
                                        "position": {
                                            "type": "string",
                                            "enum": [
                                                "top-left", "top-center", "top-right",
                                                "middle-left", "middle-center", "middle-right",
                                            ],
                                            "description": (
                                                "Позиция на экране для NumberReveal/NamedHighlight/LocationLabel. "
                                                "Разрешены только верхняя и средняя трети экрана — нижняя зарезервирована "
                                                "под YouTube-субтитры. Для SectionTitle/QuoteCard/ProgressBar поле не нужно "
                                                "(позиция фиксирована компонентом)."
                                            ),
                                        },
                                    },
                                    "additionalProperties": False,
                                },
                            },
                            "required": ["id", "type", "start_time", "duration_seconds", "reasoning", "params"],
                        },
                    },
                },
                "required": ["overlays"],
            },
        },
    }


def _call_openai(system: str, user: str, tool: dict, api_key: str) -> dict:
    """Один вызов OpenAI chat-completions с retry. Возвращает распарсенный JSON-ответ.

    OpenAI-специфика:
      - system идёт как первый message с role=system (не отдельное поле как у Anthropic)
      - tool_choice в формате {type: function, function: {name: ...}} (не Anthropic-формат)
      - response.choices[0].message.tool_calls[0].function.arguments — строка JSON,
        её надо отдельно json.loads (а не объект как в Anthropic content[].input)

    Retry-поведение:
      - До MAX_ATTEMPTS попыток с паузами
      - Повторяем только на временных ошибках: HTTP 5xx, 408, 429, таймауты, сетевые сбои
      - На клиентских 4xx (кроме 408/429) падаем сразу — это бага в запросе, не сервера
    """
    body = {
        "model": OPENAI_MODEL,
        "max_tokens": DEFAULT_MAX_TOKENS,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "tools": [tool],
        # Форсим вызов именно нашей функции — без вариантов текстового ответа
        "tool_choice": {"type": "function", "function": {"name": tool["function"]["name"]}},
    }
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
    }

    # gpt-4.1-mini отвечает за 5-15s на такую задачу; 90s — запас
    TIMEOUT = 90
    MAX_ATTEMPTS = 3
    RETRYABLE_STATUSES = {408, 425, 429, 500, 502, 503, 504}

    last_err = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        req = urllib.request.Request(OPENAI_ENDPOINT, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            try:
                return json.loads(raw)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"OpenAI вернул не-JSON (ошибка: {e}). Начало ответа:\n{raw[:500]}")

        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            last_err = f"HTTP {e.code} {e.reason}: {err_body[:300]}"
            if e.code in RETRYABLE_STATUSES and attempt < MAX_ATTEMPTS:
                delay = 5 * attempt
                print(f"   ⚠️  Попытка {attempt}/{MAX_ATTEMPTS}: {last_err}")
                print(f"   ⏳ Повтор через {delay}s...")
                time.sleep(delay)
                continue
            raise RuntimeError(f"OpenAI API: {last_err}")

        except urllib.error.URLError as e:
            last_err = f"Сетевая ошибка: {e.reason}"
            if attempt < MAX_ATTEMPTS:
                delay = 5 * attempt
                print(f"   ⚠️  Попытка {attempt}/{MAX_ATTEMPTS}: {last_err}")
                print(f"   ⏳ Повтор через {delay}s...")
                time.sleep(delay)
                continue
            raise RuntimeError(f"Не удалось достучаться до OpenAI API после {MAX_ATTEMPTS} попыток: {last_err}")

    raise RuntimeError(f"OpenAI API: все попытки исчерпаны. Последняя ошибка: {last_err}")


def _extract_tool_use(response: dict) -> dict:
    """Вытаскивает аргументы first tool_call из OpenAI-ответа.

    OpenAI формат:
      response.choices[0].message.tool_calls[0].function.arguments — СТРОКА с JSON,
      а не объект (в отличие от Anthropic, где input уже распарсен).
    """
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError(f"В ответе нет choices: {response}")

    message = choices[0].get("message", {})
    tool_calls = message.get("tool_calls") or []
    if not tool_calls:
        # Модель отдала текст вместо вызова функции — редко, но бывает при сбое
        text_fallback = message.get("content") or ""
        finish_reason = choices[0].get("finish_reason")
        raise RuntimeError(
            f"OpenAI не вернул tool_calls. "
            f"finish_reason={finish_reason}. "
            f"Текст (если есть): {text_fallback[:500]}"
        )

    args_str = tool_calls[0].get("function", {}).get("arguments", "")
    if not args_str:
        raise RuntimeError(f"В tool_call нет arguments: {tool_calls[0]}")

    try:
        return json.loads(args_str)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"tool_call.arguments не JSON (ошибка: {e}). Начало: {args_str[:500]}")


def _normalize_overlay_shape(ov: dict) -> dict:
    """Чинит случаи, когда модель уплощает структуру и кладёт поля компонента
    в корень оверлея вместо вложенного params.

    gpt-4.1-mini регулярно так делает, потому что в tool-схеме params объявлен
    как generic object без описания внутренностей — у модели нет сигнала, что
    туда надо вкладывать. Вместо того чтобы падать на валидации, переносим
    известные по COMPONENT_SPECS поля в params.
    """
    if not isinstance(ov, dict):
        return ov

    comp_type = ov.get("type")
    spec = COMPONENT_SPECS.get(comp_type)
    if not spec:
        return ov

    params = ov.get("params")
    if not isinstance(params, dict):
        params = {}

    # Поля верхнего уровня, которые НЕ надо трогать — это метаданные оверлея, не параметры компонента
    reserved_top = {"id", "type", "start_time", "duration_seconds", "reasoning", "params"}
    candidate_keys = set(spec["required"]) | set(spec["optional"])

    for key in list(ov.keys()):
        if key in reserved_top:
            continue
        if key in candidate_keys and key not in params:
            params[key] = ov.pop(key)

    ov["params"] = params
    return ov


def _validate_overlay(ov: dict, audio_duration: float) -> tuple[bool, str]:
    """Проверяет один оверлей. Возвращает (ok, reason_if_not_ok)."""
    # Наличие обязательных полей верхнего уровня
    for fld in ("id", "type", "start_time", "duration_seconds", "params"):
        if fld not in ov:
            return False, f"нет поля {fld}"

    comp_type = ov["type"]
    if comp_type not in COMPONENT_SPECS:
        return False, f"неизвестный type={comp_type}"

    start = float(ov["start_time"])
    dur = float(ov["duration_seconds"])

    if start < 0 or start >= audio_duration:
        return False, f"start_time={start:.2f} вне [0, {audio_duration:.2f})"

    if dur <= 0 or dur > 30:
        return False, f"duration_seconds={dur:.2f} вне (0, 30]"

    spec = COMPONENT_SPECS[comp_type]
    params = ov.get("params", {})
    if not isinstance(params, dict):
        return False, f"params не dict"

    # Обязательные параметры компонента
    for req in spec["required"]:
        if req not in params:
            return False, f"в params нет {req}"

    # Валидация позиций. Разрешены только top-* и middle-* — нижняя треть
    # зарезервирована под YouTube-субтитры.
    pos_mode = spec["uses_position"]
    if pos_mode is True:
        pos = params.get("position")
        if pos not in VALID_POSITIONS_9:
            return False, f"position={pos} не из разрешённых (top-*/middle-*)"

    # ProgressBar: value_percent в 0..100
    if comp_type == "ProgressBar":
        vp = params.get("value_percent")
        if not isinstance(vp, (int, float)) or vp < 0 or vp > 100:
            return False, f"value_percent={vp} не в [0, 100]"

    return True, ""


# Какое поле params компонента содержит ключевой текст, который фактически
# произносится в аудио. Используется для snap'а start_time к точному моменту
# произнесения в whisper-таймингах.
#
# NumberReveal намеренно отсутствует: число в params.value часто записано
# цифрами ("1998", "$1.2M", "+75%"), а Whisper расшифровывает их прописью
# ("тысяча девятьсот девяносто восемь") — сравнение строк не работает.
# Для чисел оставляем start_time, предложенный LLM (обычно корректный по
# предложению).
_KEY_FIELD_BY_TYPE = {
    "NamedHighlight": "text",
    "LocationLabel": "location_name",
    "SectionTitle": "title",
    "QuoteCard": "quote_text",
    "ProgressBar": "label",
}

# Короткие слова (артикли, предлоги, союзы) — плохие якоря, пропускаем их при
# snap'е, иначе "А если..." смэтчится куда угодно.
_STOPWORDS = {
    "ru": {"и", "в", "на", "по", "у", "о", "от", "до", "из", "за", "к", "с",
           "а", "но", "да", "не", "ни", "же", "ли", "бы", "то", "это",
           "для", "что", "как", "так", "там", "тут", "где", "еще"},
    "en": {"a", "an", "the", "of", "to", "in", "on", "at", "by", "for",
           "and", "or", "but", "so", "is", "it", "as", "be", "this", "that"},
}


def _tokenize_for_match(text: str) -> list:
    """Нормализует строку в список токенов для сравнения с whisper-словами.
    Регистр в нижний, пунктуация → пробел, \\w в юникод-режиме сохраняет кириллицу.
    """
    if not isinstance(text, str) or not text:
        return []
    norm = re.sub(r"[^\w\s]", " ", text.lower(), flags=re.UNICODE)
    norm = re.sub(r"\s+", " ", norm).strip()
    return norm.split()


def _tokens_match(a: str, b: str) -> bool:
    """Мягкое совпадение двух нормализованных токенов.
    Точное равенство ИЛИ общий префикс длиной ≥4 символов и
    ≥ min(len)-2 (допускаем отличие окончаний до 2 симв), чтобы ловить падежи:
    'серебро' ↔ 'серебре', 'золото' ↔ 'золотые', 'лондонская' ↔ 'лондонской'.
    Короткие слова (<4 симв) требуют точного совпадения — иначе ловим мусор.
    """
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) < 4 or len(b) < 4:
        return False
    limit = min(len(a), len(b))
    common = 0
    for i in range(limit):
        if a[i] == b[i]:
            common += 1
        else:
            break
    return common >= 4 and common >= limit - 2


def _load_whisper_words(video_dir: Path) -> list:
    """Читает полный список whisper-слов с таймингами из sentence_breakdown.json.
    Поддерживает два имени поля для обратной совместимости: новое
    `whisper_words` и старое `whisper_words_sample`.
    """
    bd_path = video_dir / "sentence_breakdown.json"
    if not bd_path.exists():
        return []
    try:
        bd = json.loads(bd_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return bd.get("whisper_words") or bd.get("whisper_words_sample") or []


def _snap_start_time(overlay: dict, whisper_words: list, language: str,
                     search_window: float = 12.0) -> tuple:
    """Подтягивает start_time оверлея к моменту, когда ключевое слово/фраза
    реально произносится в аудио.

    Алгоритм:
      1. Берём ключевое поле params (см. _KEY_FIELD_BY_TYPE) и токенизируем.
      2. Стоп-слова отбрасываем — они слишком часто встречаются и перетянут snap.
      3. По whisper_words внутри окна ±search_window от proposed_start ищем
         лучший непрерывный матч, предпочитая более длинные совпадения
         и меньшее расстояние до proposed_start.
      4. Если нашли — возвращаем start_time первого совпавшего слова,
         иначе оставляем исходный.

    Возвращает (new_start_time, matched: bool).
    """
    proposed = float(overlay.get("start_time", 0.0))

    if not whisper_words:
        return proposed, False

    comp_type = overlay.get("type")
    key_field = _KEY_FIELD_BY_TYPE.get(comp_type)
    if not key_field:
        return proposed, False

    params = overlay.get("params") or {}
    key_text = params.get(key_field, "")
    target_tokens = _tokenize_for_match(key_text)
    stop = _STOPWORDS.get(language, set())
    target_tokens = [t for t in target_tokens if t not in stop]
    if not target_tokens:
        return proposed, False

    best = None  # (score, start_time)
    n = len(whisper_words)

    for i, w in enumerate(whisper_words):
        w_start = float(w.get("start", 0.0))
        if abs(w_start - proposed) > search_window:
            continue
        w_norm = w.get("norm", "")
        if not w_norm or w_norm in stop:
            continue

        # Сколько подряд идущих таргет-токенов матчатся начиная с i
        match_len = 0
        for j, t in enumerate(target_tokens):
            k = i + j
            if k >= n:
                break
            if _tokens_match(whisper_words[k].get("norm", ""), t):
                match_len += 1
            else:
                break

        # Если 0 — пробуем: может текущее whisper-слово матчит ЛЮБОЙ токен таргета
        # (не обязательно первый), тогда это slabый, но всё же якорь длины 1
        if match_len == 0:
            if any(_tokens_match(w_norm, t) for t in target_tokens):
                match_len = 1
            else:
                continue

        time_dist = abs(w_start - proposed)
        # Длинный матч весомее близости: 1 совпадение = 10 "очков времени"
        score = match_len * 10 - time_dist
        if best is None or score > best[0]:
            best = (score, w_start)

    if best is None:
        return proposed, False
    return best[1], True


def _apply_channel_style(overlay: dict, overlay_style: dict) -> dict:
    """Мерджит цвета/шрифт/интенсивность канала в params оверлея.

    Параметры стиля применяются, только если их ещё нет в params
    (теоретически модель не должна их выдумывать, но на всякий случай).
    """
    params = dict(overlay.get("params", {}))

    style_keys = ("accent_color", "secondary_color", "font_family", "animation_intensity")
    for k in style_keys:
        if k in overlay_style and k not in params:
            params[k] = overlay_style[k]

    # Чистим служебные поля — в params компоненту они не нужны.
    # `reason` модель иногда дублирует из top-level `reasoning` — компонентам его знать не надо.
    params.pop("notes", None)
    params.pop("reason", None)

    overlay["params"] = params
    return overlay


def _find_script_file(video_dir: Path) -> Path:
    """Находит файл сценария в папке видео.

    Приоритет: script.txt (если есть), иначе единственный *.txt в папке.
    Если txt-файлов несколько — явная ошибка с перечислением, чтобы юзер
    переименовал нужный или убрал лишние.
    """
    default = video_dir / "script.txt"
    if default.exists():
        return default

    txt_files = sorted(p for p in video_dir.glob("*.txt") if p.is_file())
    if not txt_files:
        raise RuntimeError(f"В {video_dir} не найден ни один .txt со сценарием")
    if len(txt_files) > 1:
        names = ", ".join(p.name for p in txt_files)
        raise RuntimeError(
            f"В {video_dir} несколько .txt файлов ({names}) — "
            f"переименуйте сценарий в script.txt или оставьте только один .txt"
        )
    return txt_files[0]


def analyze_script(video_dir: Path, channel_name: str, config_path: Path) -> Path:
    """Главная функция: сценарий → overlays.json.

    Возвращает путь к созданному overlays.json.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Переменная окружения OPENAI_API_KEY не задана")

    # Читаем сценарий, тайминги, конфиг канала
    script_path = _find_script_file(video_dir)
    timings_path = video_dir / "timings.json"
    breakdown_path = video_dir / "sentence_breakdown.json"

    if not timings_path.exists():
        raise RuntimeError(
            f"Не найден {timings_path} — нужно сначала прогнать генерацию таймингов"
        )

    script = script_path.read_text(encoding="utf-8").strip()
    timings = json.loads(timings_path.read_text(encoding="utf-8"))

    # audio_duration предпочтительно из breakdown, иначе из последнего тайминга
    if breakdown_path.exists():
        breakdown = json.loads(breakdown_path.read_text(encoding="utf-8"))
        audio_duration = float(breakdown.get("audio_duration", 0))
    else:
        audio_duration = 0
    if audio_duration <= 0 and timings:
        audio_duration = float(timings[-1]["end"])

    # Конфиг канала
    config = json.loads(config_path.read_text(encoding="utf-8"))
    channels = config.get("channels", {})
    if channel_name not in channels:
        raise RuntimeError(
            f"Канал '{channel_name}' не найден в config.json. "
            f"Доступны: {list(channels.keys())}"
        )
    channel_cfg = channels[channel_name]
    overlay_style = channel_cfg.get("overlay_style", {})
    if not overlay_style:
        raise RuntimeError(
            f"У канала '{channel_name}' нет overlay_style в config.json"
        )
    channel_topic = channel_cfg.get("topic", "")

    language = _detect_language(script)

    print(f"📄 Видео:          {video_dir}")
    print(f"📺 Канал:          {channel_name} ({channel_topic})")
    print(f"🗣  Язык сценария:  {language}")
    print(f"🎨 Стиль оверлеев: font={overlay_style.get('font_family')}, "
          f"accent={overlay_style.get('accent_color')}, "
          f"intensity={overlay_style.get('animation_intensity')}")
    print(f"⏱  Длительность:   {audio_duration:.2f}s")
    print(f"📝 Предложений:    {len(timings)}")
    print(f"\n🧠 Запрос к {OPENAI_MODEL} (OpenAI)...")

    # Собираем промпт и дёргаем OpenAI
    system = _build_system_prompt()
    user = _build_user_prompt(
        script=script,
        timings=timings,
        audio_duration=audio_duration,
        channel_topic=channel_topic,
        channel_name=channel_name,
        language=language,
    )
    tool = _build_tool_schema()

    t0 = time.time()
    response = _call_openai(system, user, tool, api_key)
    elapsed = time.time() - t0

    # Метрики. В OpenAI поле usage.prompt_tokens/completion_tokens (не input/output как у Anthropic)
    usage = response.get("usage", {})
    print(f"⏲  Ответ получен за {elapsed:.1f}s")
    print(f"📊 Токены: prompt={usage.get('prompt_tokens')} "
          f"completion={usage.get('completion_tokens')} "
          f"total={usage.get('total_tokens')}")

    # Извлекаем и валидируем
    tool_input = _extract_tool_use(response)
    raw_overlays = tool_input.get("overlays", [])
    if not isinstance(raw_overlays, list):
        raise RuntimeError(f"overlays не массив: {type(raw_overlays).__name__}")

    print(f"\n📦 {OPENAI_MODEL} предложил {len(raw_overlays)} оверлеев")

    # Сохраняем сырой ответ сразу — пригодится для диагностики
    raw_dump_path = video_dir / "overlays_raw.json"
    raw_dump_path.write_text(
        json.dumps(raw_overlays, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Полные whisper-слова для снапа start_time к точным моментам произнесения
    whisper_words = _load_whisper_words(video_dir)
    if not whisper_words:
        print("   ⚠️  whisper_words не найдены в sentence_breakdown.json — "
              "snap таймингов пропускаем, start_time останется как у LLM")

    valid = []
    for i, ov in enumerate(raw_overlays):
        ov = _normalize_overlay_shape(ov)
        ok, reason = _validate_overlay(ov, audio_duration)
        if not ok:
            print(f"   ⚠️  [#{i+1}] отброшен: {reason}")
            # Показываем что пришло — чтобы видеть, какое поле модель выдумала
            preview = json.dumps(ov, ensure_ascii=False)
            if len(preview) > 300:
                preview = preview[:300] + "…"
            print(f"      raw: {preview}")
            continue

        # Snap start_time к реальному моменту произнесения ключевого слова.
        # LLM часто ставит start в начало предложения, а не в момент самого слова —
        # визуально оверлей появляется "рядом с" нужной фразой, а не вместе с ней.
        original_start = float(ov["start_time"])
        snapped, matched = _snap_start_time(ov, whisper_words, language)
        if matched and abs(snapped - original_start) > 0.05:
            print(f"   🎯 [#{i+1}] {ov['type']}: start_time "
                  f"{original_start:.2f}s → {snapped:.2f}s (snap к слову)")
        ov["start_time"] = round(snapped, 2)

        # Применяем стиль канала
        ov = _apply_channel_style(ov, overlay_style)
        valid.append(ov)

    # Сортируем по start_time и перенумеровываем id
    valid.sort(key=lambda x: float(x["start_time"]))
    for i, ov in enumerate(valid):
        ov["id"] = f"overlay_{i+1:03d}"

    print(f"✅ Валидных оверлеев: {len(valid)} (отброшено {len(raw_overlays) - len(valid)})")

    # Сохраняем overlays.json
    out_path = video_dir / "overlays.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(valid, f, ensure_ascii=False, indent=2)
    print(f"💾 Сохранено: {out_path}")

    # Дополнительно — полный лог с reasoning для отладки
    debug_path = video_dir / "overlays_debug.json"
    debug = {
        "channel": channel_name,
        "model": OPENAI_MODEL,
        "audio_duration": audio_duration,
        "llm_usage": usage,
        "raw_count": len(raw_overlays),
        "valid_count": len(valid),
        "raw_overlays": raw_overlays,
    }
    with open(debug_path, "w", encoding="utf-8") as f:
        json.dump(debug, f, ensure_ascii=False, indent=2)
    print(f"🔍 Отладка:    {debug_path}")

    return out_path


def main():
    parser = argparse.ArgumentParser(
        description="Analyze script and generate overlays.json via OpenAI (gpt-4.1-mini)"
    )
    parser.add_argument(
        "--video", required=True,
        help="Папка с видео (содержит script.txt + timings.json)"
    )
    parser.add_argument(
        "--channel", required=True,
        help="Имя канала (ключ в config.json / channels)"
    )
    parser.add_argument(
        "--config", default="config.json",
        help="Путь к config.json (по умолчанию ./config.json)"
    )
    args = parser.parse_args()

    video_dir = Path(args.video).resolve()
    config_path = Path(args.config).resolve()

    if not video_dir.is_dir():
        print(f"❌ Папка не найдена: {video_dir}")
        sys.exit(1)
    if not config_path.exists():
        print(f"❌ Не найден config: {config_path}")
        sys.exit(1)

    try:
        analyze_script(video_dir, args.channel, config_path)
    except RuntimeError as e:
        print(f"\n❌ {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
