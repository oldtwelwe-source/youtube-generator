# YouTube Video Generator

Python-пайплайн, который превращает текстовый сценарий и озвучку в готовый ролик для YouTube: подбирает визуал под каждое предложение, синхронизирует с речью через Whisper, добавляет переходы и motion-graphics оверлеи.

> Полная техническая документация — в [CLAUDE.md](./CLAUDE.md).

---

## Что делает

```
script.txt + voiceover.mp3
        │
        ▼
┌───────────────────────────────────┐
│ 1. Разбивка на предложения        │
│ 2. LLM → промпты / keywords       │  DeepSeek / OpenAI gpt-4.1-mini
│ 3. Визуал на предложение          │  6 провайдеров с фолбэком
│ 4. Whisper word-level timings     │  локальная medium-модель
│ 5. FFmpeg сборка + xfade          │  19 переходов в паузах речи
│ 6. LLM → плотность оверлеев       │  tool calling, structured output
│ 7. Remotion → webm с alpha        │  React / TypeScript
│ 8. FFmpeg композитинг оверлеев    │  libvpx + setpts PTS-сдвиг
└───────────────────────────────────┘
        │
        ▼
   final_video_enhanced.mp4
```

## Технические особенности

**Мультипровайдерная генерация визуала** — 6 источников с автоматическим выбором по типу контента:
- Картинки: Kie API (z-image, $0.004), Replicate (FLUX-schnell, $0.003)
- Видео-стоки: Pexels, Pixabay (бесплатно)
- Фото-стоки 16:9: Pexels, Pixabay с фильтром по соотношению сторон
- Разные стратегии retry: экспоненциальный backoff на 429 для Replicate, polling для Kie

**Word-level синхронизация оверлеев.** LLM ставит `start_time` приблизительно — после валидации применяется `_snap_start_time`, который ищет момент реального произнесения ключевого слова через Whisper word timestamps. Мягкий матч с поддержкой падежей (общий префикс ≥4 символа), стоп-слова, скоринг `match_len*10 - |Δt|`.

**xfade-переходы только в паузах речи.** Переход размещается симметрично вокруг границы предложений. При паузе `< 0.1s` — hard-cut через `concat`, чтобы не наезжать на голос. Длительности источников считаются формулой `display + left_half + right_half` под xfade-математику `len(A)+len(B)-D`. Детерминированный seed по имени видео — пересборка даёт идентичный результат.

**Прозрачные оверлеи на VP8.** Все четыре флага рендера обязательны (`--image-format=png --pixel-format=yuva420p --codec=vp8 --crf=4`). FFmpeg композитинг требует явный `-c:v libvpx` перед каждым оверлеем + `setpts=PTS-STARTPTS+start/TB` внутри filter_complex (а не `-itsoffset`). В Remotion-компонентах вместо `textShadow`/`boxShadow` — `WebkitTextStroke` со 100% alpha, иначе VP8 4:2:0 субсэмплинг даёт цветные ореолы.

**Tool calling с строгой схемой.** OpenAI tool calling с `additionalProperties: false`, `tool_choice` форсит вызов нужной функции, retry на `{408, 425, 429, 500, 502, 503, 504}`. Перед валидацией — нормализация ответа (модель кладёт поля компонента в корень вместо `params` — вытягиваются обратно по `COMPONENT_SPECS`).

**Только stdlib для HTTP.** Все сетевые вызовы через `urllib` — никаких `requests`, `openai`, `replicate` SDK. Один общий `_call_openai_compat` для DeepSeek/OpenAI, кастомный SSL-контекст и браузерный User-Agent (Cloudflare блокирует дефолтные UA на Pexels/Kie).

## Стек

`Python 3.14` · `FFmpeg` · `OpenAI Whisper (medium)` · `Remotion 4.x` · `Node.js 20` · `React/TypeScript` · `OpenAI gpt-4.1-mini` · `DeepSeek` · `Replicate` · `Kie API` · `Pexels/Pixabay`

## Структура

```
YouTube-Generator/
├── start.py                    # Интерактивный лаунчер
├── generate.py                 # Основной пайплайн (~2000 строк)
├── lib/
│   └── transitions.py          # xfade: план границ + filter_complex
├── overlays/
│   ├── analyzer.py             # LLM → overlays.json + word-snap
│   ├── renderer.py             # npx remotion render
│   ├── compositor.py           # FFmpeg композитинг с alpha
│   └── remotion/src/
│       ├── Root.tsx            # calculateMetadata по props
│       └── components/         # NumberReveal, NamedHighlight, LocationLabel,
│                               # SectionTitle, QuoteCard, ProgressBar
└── config.json                 # Per-channel стили + overlay_style
```

## Запуск

```bash
START.bat
# или
python start.py
```

Перед запуском — переменные окружения:

```
DEEPSEEK_API_KEY      # LLM для промптов
OPENAI_API_KEY        # LLM для промптов и анализа оверлеев
KIE_API_KEY           # картинки (z-image)
REPLICATE_API_TOKEN   # картинки (FLUX-schnell)
PEXELS_API_KEY        # видео и фото стоки
PIXABAY_API_KEY       # видео и фото стоки
```

Данные каналов и видео живут в `D:\MyChannelsIRL\<channel>\<video>\` отдельно от кода:

```
<video>/
├── script.txt
├── voiceover.mp3
├── frames/                     # frame_NNNN.png или clip_NNNN.mp4
├── final_video.mp4             # после сборки
├── overlays.json               # после LLM-анализа
└── final_video_enhanced.mp4    # финал с оверлеями
```

## Флаги `generate.py`

| Флаг | Что делает |
|---|---|
| `--split-only` | Только разбивка сценария |
| `--prompts-only` | Промпты / keywords (требует sentences.json) |
| `--images-only` | Генерация визуала (требует prompts.json) |
| `--assemble-only` | Сборка видео (требует визуал + аудио) |
| `--all` | Все шаги подряд |
| `--transitions` | Включить xfade-переходы |
