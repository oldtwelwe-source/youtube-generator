# CLAUDE.md — YouTube Video Generator

## Назначение проекта
Python-скрипт для автоматической генерации видео для YouTube из текстового сценария и озвучки. Каждое предложение сценария получает свой визуал (картинку или видеоклип), синхронизированный с речью диктора. Поверх основного видео накладываются motion-graphics оверлеи через Remotion.

## Структура проекта
Код и данные разнесены по разным папкам, чтобы корень кода оставался чистым.

```
D:\YouTube-Generator\             # Только код/конфиги
├── START.bat                     # Запускает start.py
├── start.py                      # Интерактивный лаунчер (канал → видео → действие)
├── generate.py                   # Основной пайплайн (~1400 строк, планируется рефакторинг в lib/)
├── config.json                   # Стили и топики для каждого канала + overlay_style
│
├── lib/                          # Вынесенные модули (начало рефакторинга generate.py)
│   └── transitions.py            # xfade-переходы: план границ + сборка filter_complex
│
└── overlays/                     # Motion-graphics оверлеи (Remotion + Python)
    ├── analyzer.py               # Python: OpenAI gpt-4.1-mini → overlays.json
    ├── renderer.py               # Python: запускает npx remotion render для каждого оверлея
    ├── compositor.py             # Python: накладывает webm-оверлеи на видео через FFmpeg
    ├── sample_overlays.json      # Пример данных для тестирования
    └── remotion/                 # Node.js проект (Remotion 4.x)
        ├── package.json
        ├── tsconfig.json
        ├── node_modules/         # Установлен через npm install
        └── src/
            ├── index.ts          # Точка входа Remotion
            ├── Root.tsx          # Регистрация композиций с calculateMetadata
            └── components/
                ├── TestCard.tsx      # Тестовый компонент
                └── NumberReveal.tsx  # Анимированное появление числа/даты

D:\MyChannelsIRL\                 # Данные каналов (CHANNELS_ROOT в start.py)
├── finance/                      # Каналы с видео
│   └── {video_name}/
│       ├── script.txt            # Сценарий (или любой *.txt — analyzer/start берут единственный)
│       ├── voiceover.mp3         # Озвучка (имя гибкое — start.py ищет любой *.mp3 в папке)
│       ├── frames/               # Визуал (frame_NNNN.png или clip_NNNN.mp4)
│       │   ├── sentences.json
│       │   ├── prompts.json
│       │   └── timings.json
│       ├── final_video.mp4       # Собранное видео
│       ├── overlays.json         # Список оверлеев (генерирует OpenAI/gpt-4.1-mini)
│       └── final_video_enhanced.mp4  # Видео с наложенными оверлеями
├── erifan/
├── machine/
└── history/
```

`start.py` сканирует только `CHANNELS_ROOT` (захардкожен `D:\MyChannelsIRL`) для
списка каналов и видео. Сам процесс запускается из `D:\YouTube-Generator` (cwd
через `START.bat` и `os.chdir(base)`) — относительные пути к `overlays/*.py` и
`lib/*` продолжают работать. `generate.py`, `overlays/analyzer.py` и остальные
скрипты получают полный путь к папке видео через аргументы, своих
предположений о расположении не делают.

## Pipeline основного видео (generate.py)
1. **Разбивка сценария** на предложения через regex (1 предложение = 1 визуал)
2. **Генерация промптов/ключевых слов** через DeepSeek или OpenAI (gpt-4.1-mini)
3. **Генерация визуала** — 6 провайдеров:
   - Kie API (z-image) — картинки, $0.004/шт, async polling
   - Replicate (FLUX-schnell) — картинки, $0.003/шт, последовательный режим
     (по одной задаче за раз: submit → 3 проверки с паузами 3/5/7s → следующая).
     Batch-отправка всех задач подряд упиралась в rate limit (429). На submit
     экспоненциальный backoff на 429 (5/10/20/40/80s, до 5 попыток). Если за
     3 проверки задача не готова — frame пропускается, идём к следующему промпту.
   - Pexels (видео) — стоковые видеоклипы, бесплатно
   - Pixabay (видео) — стоковые видеоклипы, бесплатно
   - Pexels (фото 16:9) — стоковые фото, бесплатно, фильтр по ratio 1.6..2.0
   - Pixabay (фото 16:9) — стоковые фото, бесплатно, `min_width=1280, min_height=720`

   **Именование файлов:** видео-стоки → `clip_NNNN.mp4`, фото-стоки и
   Kie/Replicate → `frame_NNNN.png`. Сборка выбирается автоматически по тому,
   какие файлы лежат в папке (`frame_*` → `assemble_video_images`, `clip_*` →
   `assemble_video_clips`), поэтому фото-стоки собираются так же, как
   сгенерированные картинки.

   **Стоки и LLM:** для всех четырёх стоковых провайдеров (видео и фото)
   `generate_keywords_llm` даёт короткие ключевые слова вместо рисовательных
   промптов — иначе поиск по стокам промахивается.

   **Фильтр 16:9 для фото:** Pexels возвращает `width/height` на уровне фото —
   проверяем `1.6 <= w/h <= 2.0` и берём `src.large2x → large → original`.
   Pixabay отдаёт `imageWidth/imageHeight` и отдельно `largeImageURL/webformatURL`.
   Жёстко 16:9 (1.777) не делаем — стоки редко кадрируют под идеальное
   соотношение, 1.6..2.0 покрывает всё, что FFmpeg потом без проблем паддит
   до 1280×720.

   **Отдельные used-ids файлы:** `used_pexels_photo_ids.json` /
   `used_pixabay_photo_ids.json` — чтобы видео- и фото-режимы одного провайдера
   не конфликтовали при смешанной работе над одним видео.
4. **Тайминги через Whisper** (medium model, word_timestamps=True)
5. **Сборка видео через FFmpeg** (concat demuxer + аудио)

## Флаги generate.py
- `--split-only` — только разбивка сценария (шаг 1)
- `--prompts-only` — только промпты (шаги 1-2)
- `--images-only` — только визуал (шаги 1-3), требует prompts.json
- `--assemble-only` — только сборка (шаги 4-5), требует визуал + аудио
- `--all` — все шаги подряд
- `--transitions` — включает xfade-переходы между клипами/картинками в паузах
  речи (см. раздел ниже). В интерактивном режиме start.py спрашивает y/N.
- `--dry-run` — deprecated алиас для --split-only

## xfade-переходы (lib/transitions.py)
Опциональная фича: плавные переходы между соседними визуалами в финальной
сборке (`--transitions` / y в start.py). Работает и для картинок, и для клипов.
Вся чистая логика (без ffmpeg) вынесена в `lib/transitions.py` — удобно юнит-тестировать.

### Где стоит переход
- Переход размещается **строго в паузах между предложениями**, симметрично
  вокруг `boundary_time = start_{i+1}`: от `boundary - D/2` до `boundary + D/2`.
  При `pause >= D` переход целиком в тишине — речь не задевается.
- Если пауза `< MIN_PAUSE_FOR_TRANSITION` (0.1s) — на этой границе **hard-cut**
  через `concat=n=2:v=1:a=0`, без xfade. Лучше резкий стык, чем наезд на речь.
- `_sentence_end(timings_i, whisper_words)` — реальный конец речи предложения,
  берётся как максимум из `timings[i].end` и конца последнего whisper-слова
  в диапазоне предложения (но не дальше `timings[i].end`). Нужен чтобы отличать
  «предложение кончилось раньше, а tail в timings это просто зазор» от
  «речь идёт до последней миллисекунды».

### Длительности источников (ключевая формула)
`xfade(A, B, duration=D, offset=T)` → итоговая длина = `len(A) + len(B) - D`.
Чтобы на финальном таймлайне клип `i` занимал ровно `display_i = start_{i+1} - start_i`,
исходник должен быть на `D/2` длиннее с каждой стороны, где есть переход:
```
source_i = display_i + left_half_i + right_half_i
left_half_i  = D/2 если boundary[i-1].has_transition (и i>0)
right_half_i = D/2 если boundary[i].has_transition  (и i<n-1)
```
См. `clip_source_durations`. Всё округляется до кратности кадра (`0.04s` при 25fps).

### Пул переходов и порядок
`TRANSITION_POOL` — 19 переходов (17 из списка + `dissolve`, `wipeleft`).
Порядок детерминированный: `seed = md5(video_name)[:8]` → shuffle пула → циклический
проход. Если сосед совпал с предыдущим — сдвиг на один. Так одно и то же видео
всегда пересобирается с одинаковыми переходами.

### Нормализация входов перед xfade (НЕ УБИРАТЬ)
```
scale=1280:720:force_original_aspect_ratio=decrease,
pad=1280:720:(ow-iw)/2:(oh-ih)/2,
fps=25,format=yuv420p,setsar=1,settb=AVTB
```
- `setsar=1` + `format=yuv420p` — без них xfade падает с
  «First input link parameters do not match».
- `settb=AVTB` — **критично** при смешанной цепочке xfade+concat. `concat`
  по умолчанию выдаёт timebase `1/AV_TIME_BASE` (1/1000000), а `fps=25`
  даёт `1/25`. Как только в цепочке встречается хотя бы один hard-cut
  (concat), running-output становится 1/1000000, а свежий `v_k` остаётся
  1/25 → следующий xfade ловит **«timebase do not match»** и падает.
  `settb=AVTB` выравнивает всё на 1/1000000.

### Сборка filter_complex
`build_filter_complex(source_durations, boundaries)` собирает граф:
```
[k:v]{scale_pad},setpts=PTS-STARTPTS[v{k}]
[v{k}][v{k+1}]xfade=transition=T:duration=D:offset=O[x{step}]   # если has_transition
[v{k}][v{k+1}]concat=n=2:v=1:a=0[c{step}]                       # если hard-cut
```
`offset` k-го xfade = `running_length - D`. После xfade running-length растёт
на `len(v{k+1}) - D`, после concat — на полную длину `v{k+1}`.

### FFmpeg-запуск (generate.py → _ffmpeg_xfade)
- Re-encode обязателен (`-c:v copy` с xfade невозможен). Пресет `libx264 -preset medium -crf 20`,
  аудио `-c:a aac -b:a 192k`. Для пользователя выводится предупреждение
  «в 3-5 раз дольше обычной сборки».
- `filter_complex` **всегда** пишется в `_filter.txt` и передаётся через
  `-filter_complex_script`.
- Запуск идёт через `subprocess.run(args_list, shell=False)`, НЕ через
  `os.system(cmd_string)`. Причина: на 150+ клипах даже один только список
  `-i "..."` (по ~60 символов на путь) вылезал за cmd.exe лимит 8191 и
  падал с «The command line is too long», даже когда filter_complex уже
  был в файле. `CreateProcess` (shell=False) поднимает лимит до ~32K и
  не тянет за собой cmd-парсер, так что кавычки в путях не нужны.
- Временные mp4 в `frames/_xfade_tmp/` (для картинок) и `frames/_trimmed/`
  (для клипов). Чистятся после успешной сборки.
6. **Анализ сценария через OpenAI gpt-4.1-mini** (analyzer.py) — генерирует overlays.json,
   после LLM-ответа каждый `start_time` подтягивается к моменту реального произнесения
   ключевого слова через whisper-тайминги (word-level snap, см. ниже)
7. **Рендер оверлеев через Remotion** → webm с alpha-каналом (renderer.py)
8. **Композитинг через FFmpeg** — overlay поверх final_video.mp4 (compositor.py)

Интегрировано в start.py пунктами [6]/[7]/[8]/[9]. `[9]` прогоняет всю цепочку 6→7→8.

Служебная тулза `overlays/_resnap_overlays.py` применяет word-snap к уже готовому
`overlays.json` без повторного вызова LLM — полезно для перегенерации только
таймингов после правок в snap-логике.

## Технические ограничения (НЕ ЛОМАТЬ)
- Python 3.14, глобальная установка в `C:\Python314` (без venv)
- ВСЕ API-вызовы через stdlib `urllib` — никакой `requests`, `urllib3`, `openai`, `replicate`, etc.
- Единственная тяжёлая зависимость — `openai-whisper` (локальная ML-модель, НЕ API)
- Pexels/Pixabay/Kie: SSL-контекст с `CERT_NONE` + browser User-Agent (Cloudflare фильтрует дефолтные UA)
- Kie API и Replicate: асинхронная отправка задач + polling результатов
- Разрешение видео: 1280x720 (720p) — захардкожено в FFmpeg-фильтрах
- Node.js v20.9.0 установлен, Remotion 4.x
- Короткие клипы растягиваются через boomerang (forward+reverse loop), НЕ через freeze

## API и переменные окружения
- `DEEPSEEK_API_KEY` — LLM для промптов (base_url: `https://api.deepseek.com/v1`)
- `OPENAI_API_KEY` — LLM для промптов И для analyzer.py (gpt-4.1-mini)
- `KIE_API_KEY` — картинки (z-image)
- `REPLICATE_API_TOKEN` — FLUX-schnell картинки
- `PEXELS_API_KEY` — стоковое видео и фото (16:9)
- `PIXABAY_API_KEY` — стоковое видео и фото (16:9)

## HTTP через urllib (generate.py)
Все сетевые запросы в `generate.py` идут через два хелпера:
- `_http_get_json(url, params, headers, timeout)` — GET + JSON-парсинг
- `_http_download(url, filepath, min_size, timeout, chunk)` — стрим в файл

Оба используют `_UNVERIFIED_SSL_CTX` (CERT_NONE для VPN) и `_DEFAULT_HEADERS` с браузерным
Chrome User-Agent. **Без этого UA Cloudflare отдаёт 403 на Pexels и 1010 на Kie.**

LLM-вызовы к DeepSeek/OpenAI (и Kie Sonnet, если понадобится) идут через
`_call_openai_compat(api_key, base_url, model, system, user, max_tokens, temperature)`.

## analyzer.py — LLM-анализ для оверлеев
- Endpoint: `https://api.openai.com/v1/chat/completions`
- Model: `gpt-4.1-mini` (раньше был Sonnet на Kie — мигрировали из-за нестабильности Kie)
- Вызов через tool calling: `{type: "function", function: {...}}` (OpenAI-формат, НЕ плоский Anthropic)
- `tool_choice: {type: "function", function: {name: "submit_overlays"}}` форсит структурированный ответ
- `tool_calls[0].function.arguments` — это **строка**, нужен `json.loads` (не готовый объект как в Anthropic)
- System-промпт подаётся первым сообщением в `messages`, не отдельным полем
- Retry: 3 попытки с backoff на {408,425,429,500,502,503,504}, timeout=90s
- `_apply_channel_style` подмешивает overlay_style из config.json в каждый overlay
  и чистит служебные поля (`notes`, `reason`)
- `_find_script_file` ищет сценарий: сначала `script.txt`, иначе единственный `*.txt`
  в папке видео (несколько `*.txt` → явная ошибка с перечислением имён)
- `_normalize_overlay_shape` чинит случай, когда gpt-4.1-mini кладёт поля компонента
  в корень оверлея вместо вложенного `params` — переносит известные по COMPONENT_SPECS
  поля внутрь params перед валидацией
- Tool-схема явно описывает все возможные поля `params` (`text`, `value`, `location_name`, …)
  с `additionalProperties: false`, чтобы модель не могла выдумать свои имена
- При валидации сырой ответ модели сохраняется в `overlays_raw.json`, а при отбраковке
  оверлея печатается его содержимое (`raw: {...}`) для диагностики
- `_detect_language(script)` — простая автодетекция: доля кириллических букв >30% → `ru`,
  иначе `en`. Результат прокидывается в user-промпт как обязательное требование
  («все тексты оверлеев на языке X») — без этого gpt-4.1-mini выдавал русские оверлеи
  на английском сценарии

### Word-level snap таймингов (критично для синхронизации)
LLM ставит `start_time` обычно в начало предложения, а не в момент самого слова —
визуально оверлей появляется «рядом с» фразой, а не вместе с ней. После валидации
каждого оверлея вызывается `_snap_start_time(overlay, whisper_words, language)`,
который двигает `start_time` к реальному моменту произнесения ключевого поля:
- `_KEY_FIELD_BY_TYPE` задаёт, какое поле params несёт озвученный текст:
  `text` (NamedHighlight), `location_name` (LocationLabel), `title` (SectionTitle),
  `quote_text` (QuoteCard), `label` (ProgressBar). **NumberReveal намеренно
  исключён**: Whisper расшифровывает «1998» как «тысяча девятьсот девяносто
  восемь» — матч строк не работает, оставляем LLM-время как есть.
- `_load_whisper_words` читает полный список слов из `sentence_breakdown.json`
  (поле `whisper_words`; для старых данных фоллбэк на `whisper_words_sample`).
  Поэтому `generate.py` теперь сохраняет все слова, а не первые 200.
- `_tokens_match` — мягкое совпадение: точное равенство ИЛИ общий префикс
  ≥4 симв и ≥ `min(len)-2`. Ловит падежи: «серебро»↔«серебре»,
  «золото»↔«золотые», «лондонская»↔«лондонской». Слова короче 4 симв
  требуют точного совпадения (иначе ложные срабатывания на «а»/«в»/«и»).
- `_STOPWORDS` (ru/en) отсекает артикли, предлоги, союзы при snap'е —
  иначе «А если» сматчится куда угодно.
- Скоринг: `match_len * 10 - |w_start - proposed|`. Длинный непрерывный
  матч ценнее близости по времени; окно поиска ±12s от proposed_start.
- Если ни одного матча нет (напр. LLM придумал локацию, которой нет в
  аудио) — `start_time` остаётся как у LLM, без ошибки.

### Продуктовые правила в промпте (не менять без причины)
- 6 типов компонентов: NumberReveal, NamedHighlight, LocationLabel, SectionTitle,
  QuoteCard, ProgressBar. KeywordPop и Chapter **исключены из генерации** —
  не соответствуют документальному тону / плохо вписываются. Сами компоненты
  остаются в Remotion для превью в Studio, но analyzer их не выбирает
- Плотность: 4-6 оверлеев на минуту видео, минимум 4s между оверлеями
- Позиции: только top-*/middle-* (6-точечная сетка). Нижняя треть зарезервирована
  под YouTube-субтитры. `VALID_POSITIONS_9` несмотря на название содержит 6 позиций
- Запрет дублирования содержания (один факт — один оверлей за всё видео)
- Запрет двух подряд оверлеев одного type

## Kie API для Sonnet 4.6 (НЕ ИСПОЛЬЗУЕТСЯ, справочно)
Оставлено на случай возврата к Sonnet, если OpenAI перестанет справляться:
- Endpoint: `https://api.kie.ai/claude/v1/messages`
- Auth: `Authorization: Bearer ${KIE_API_KEY}`
- Model: `claude-sonnet-4-6`
- Формат полностью совместим с Anthropic Messages API (tools — плоский формат, не обёрнутый)
- Причина миграции: Kie часто отдаёт 500/1010, висит, нестабилен под нагрузкой

## Remotion-компоненты (overlays/remotion/)
Все компоненты рендерятся на прозрачном фоне (без backgroundColor).
Props передаются через JSON-файл: `--props=path/to/file.json`
Длительность определяется через `calculateMetadata` по полю `duration_seconds` в props.

### Существующие компоненты:
- **TestCard** — простая карточка с текстом (для отладки)
- **NumberReveal** — число/дата вылетает с spring-анимацией
- **NamedHighlight** — имя/термин подсвечивается
- **LocationLabel** — метка "📍 место"
- **QuoteCard** — карточка для цитаты (по центру)
- **SectionTitle** — заставка "ФАКТ №1" при смене темы (по центру)
- **ProgressBar** — бар для сравнений/процентов (по центру экрана, НЕ внизу —
  нижняя треть зарезервирована под субтитры YouTube)
- **KeywordPop** — ключевое слово с pop-эффектом *(в Studio остался, analyzer не генерит)*
- **Chapter** — постоянная полоска с названием раздела *(в Studio остался, analyzer не генерит)*

### Чёткая альфа на VP8: textShadow запрещён, stroke обязателен
VP8 в WebM субсэмплит alpha по 4:2:0, поэтому любой **градиентный alpha**
(полупрозрачные тени, blur, backgroundColor с `${color}DD`, boxShadow) после
компрессии превращается в цветной ореол и смаз. В компонентах для читаемости
текста используется **контур с 100% alpha**:
```tsx
WebkitTextStroke: `3px ${secondary_color}`,
paintOrder: "stroke fill",
```
Правило для любых новых компонентов: никаких `textShadow`, `boxShadow`,
`filter: blur(...)` и фоновых цветов с альфой (`#RRGGBBAA`) — только сплошной
цвет или чистый текст со stroke. Иначе ореолы вернутся.

## Рендер прозрачных оверлеев (КРИТИЧЕСКИ ВАЖНО)

### 1. Remotion render — четыре обязательных флага
Для качественного webm с alpha-каналом нужны ВСЕ флаги одновременно:
```
--image-format=png --pixel-format=yuva420p --codec=vp8 --crf=4
```
- `--image-format=png` — JPEG не поддерживает alpha, без этого флага alpha НЕВОЗМОЖЕН
- `--pixel-format=yuva420p` — формат с alpha-каналом (буква 'a' в 'yuva')
- `--codec=vp8` — официально рекомендованный кодек для alpha в Remotion
- `--crf=4` — верхняя граница качества VP8 (диапазон 4..63, дефолт 9). На дефолте
  шрифты оверлеев пикселизировались после композитинга в финальное mp4
- Источник: https://www.remotion.dev/docs/transparent-videos

Те же параметры продублированы в `overlays/remotion/remotion.config.ts`
через `Config.setCodec("vp8")` / `setPixelFormat("yuva420p")` /
`setVideoImageFormat("png")` / `setCrf(4)` — чтобы при запуске Remotion Studio
и при CLI-рендере поведение было одинаковым.

### 2. Диагностика: ffprobe врёт про alpha в VP8 WebM
`ffprobe -show_entries stream=pix_fmt` на готовом webm покажет `yuv420p`, а НЕ `yuva420p` —
и это **НОРМАЛЬНО**. VP8 в WebM хранит alpha не через yuva-формат видеопотока, а во
внутренней вторичной дорожке, помеченной метаданными контейнера. Проверять наличие
alpha надо по тегу:
```
ffprobe -show_entries stream_tags=alpha_mode file.webm
# ожидаемо: TAG:alpha_mode=1
```
Если `alpha_mode=1` есть — alpha ЕСТЬ, даже если pix_fmt показывает yuv420p.
Если тега нет — alpha потеряна ещё на этапе рендера Remotion.

### 3. Композитинг: FFmpeg требует явный libvpx-декодер + setpts-сдвиг PTS
При наложении webm-оверлея на основное видео FFmpeg по умолчанию декодирует VP8
без извлечения alpha-канала → оверлей ложится с чёрным фоном. Перед КАЖДЫМ
`-i overlay.webm` обязательно ставить `-c:v libvpx`:
```
ffmpeg -i main.mp4 \
       -c:v libvpx -i overlay.webm \
       -filter_complex "[1:v]setpts=PTS-STARTPTS+12.500/TB[o1]; \
                        [0:v][o1]overlay=enable='between(t,12.5,15.0)'" ...
```
Без `-c:v libvpx` никакие format-фильтры (`format=yuva420p`, `alphamerge` и т.п.) не
помогут — alpha потеряна уже на уровне демуксера.

**Сдвиг PTS оверлея делается через `setpts=PTS-STARTPTS+{start}/TB` внутри
filter_complex, а НЕ через `-itsoffset` на уровне демуксера.** Без сдвига webm
начинает проигрываться с output-t=0, за свои 2-3s отыгрывает полную анимацию ещё
до открытия `enable`-окна, а когда окно открывается — FFmpeg показывает
**замороженный последний кадр** webm. А последний кадр всех компонентов имеет
`opacity=0` из-за fadeOut → оверлей выглядит статичным и почти невидимым.

Почему `setpts`, а не `-itsoffset`: setpts работает целиком внутри filter-графа
и не зависит от того, как libvpx декодирует поток. На практике `-itsoffset`
иногда конфликтовал с `-c:v libvpx` и альфа-каналом — сдвиг применялся раньше
распаковки альфы. setpts-вариант стабилен. Это реализовано в `compositor.py`
(см. `build_filter_complex` → цикл по `valid_overlays`, две строки на оверлей:
`setpts` → `overlay enable='between(...)'`).

## config.json — стили каналов
Каждый канал имеет `style` (для генерации визуала), `topic` (для LLM-промптов),
и `overlay_style` (для Remotion-оверлеев). overlay_style задаёт визуальный язык
оверлеев для канала: шрифт, цвета, темп анимаций. Это ДАННЫЕ, не код —
редактируются в config.json за 30 секунд. Каналы:
- finance — oil painting, classical (Playfair Display, золотой акцент)
- erifan — Studio Ghibli, Russian culture (Caveat, зелёный акцент)
- machine — 1950s retro-futurism (ретро-стиль)
- history — cinematic realism, mystical (Cinzel, античное золото)

`animation_intensity` у всех каналов выставлен в `subtle` (сдержанные
документальные анимации). `medium`/`playful` поддерживаются в компонентах,
но продуктовое решение — не использовать их: реакционные вставки
не подходят под формат канала.

## Отладочные файлы (в папке видео)
- `sentences.json` — разбивка сценария
- `prompts.json` — промпты/ключевые слова для визуала
- `sentence_breakdown.json` — что услышал Whisper: нормализованные предложения
  + полный список слов с таймингами (`whisper_words`) для word-snap в analyzer.py
- `timings.json` — тайминги с методами (matched/interpolated/empty)
- `used_pexels_ids.json`, `used_pixabay_ids.json` — против повтора клипов
- `used_pexels_photo_ids.json`, `used_pixabay_photo_ids.json` — против повтора фото-стоков
- `overlays.json` — валидированный список оверлеев с параметрами и snap-таймингами
- `overlays_raw.json` — сырой ответ LLM до нормализации/валидации (для диагностики)
- `overlays_debug.json` — полный лог анализа (канал, модель, usage, raw/valid count)
- `render_report.json` — отчёт рендера оверлеев

## Планируемый рефакторинг
generate.py (~1400 строк) планируется разбить на модули в lib/. Первый кусок
уже вынесен — `lib/transitions.py` (xfade-логика). Дальше по плану:
- lib/script_split.py, lib/prompts.py, lib/visuals_*.py
- lib/timings.py, lib/assemble_images.py, lib/assemble_clips.py, lib/utils.py
Рефакторинг НЕ блокирует новые фичи — делается отдельной итерацией.

## Стиль кода
- Русские комментарии и пользовательский вывод
- Эмодзи в консольном выводе (📄🎬✅❌⚠️)
- Интерактивные меню через input() в start.py
- Все API-вызовы через stdlib `urllib` (НЕ через `requests` и НЕ через SDK-библиотеки)
