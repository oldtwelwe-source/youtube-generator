"""xfade-переходы между клипами в паузах между предложениями.

Логика чистая (без ffmpeg), чтобы можно было тестировать отдельно.
Использует только stdlib — как и весь проект.

Основные инварианты:
  - Каждый клип i занимает на финальном таймлайне ровно [start_i, start_{i+1}]
    (для последнего — до конца аудио). Длина финального видео не плывёт.
  - xfade длиной D располагается СИММЕТРИЧНО вокруг boundary_time = start_{i+1}:
    от boundary_time - D/2 до boundary_time + D/2. Если pause >= D, вся xfade-зона
    целиком в тишине — речь не задевается.
  - Если pause < MIN_PAUSE_FOR_TRANSITION (0.1s) — на этой границе делается
    hard-cut (concat=n=2:v=1:a=0), без xfade, без наезда на речь.
  - Формула xfade: xfade(A, B, duration=D, offset=T) → длина(A) + длина(B) - D.
    Чтобы таймлайн сохранился, source_dur[i] = display_dur[i] + left_half + right_half,
    где half = D/2 только на тех стыках, где реально будет xfade.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from typing import Optional

# ---- Пул переходов ----
# 17 переходов из списка пользователя + 2 добавленных (dissolve, wipeleft)
TRANSITION_POOL = [
    "hrslice", "diagbr", "diagbl", "vuwind", "vdwind",
    "coverright", "coverup", "revealup", "radial", "vuslice",
    "horzopen", "vertclose", "diagtr", "circleopen", "smoothup",
    "fade", "fadeblack",
    "dissolve", "wipeleft",
]

DEFAULT_TRANSITION_DUR = 0.5
MIN_PAUSE_FOR_TRANSITION = 0.1
FPS = 25
FRAME = 1.0 / FPS  # 0.04s

# Обязательные фильтры нормализации входа перед xfade. Без setsar=1 и
# format=yuv420p xfade ругается "First input link parameters do not match".
# settb=AVTB принудительно выставляет timebase 1/1000000 всем входам — это нужно
# при смешанной цепочке xfade+concat: concat по умолчанию выдаёт AV_TIME_BASE
# (1/1000000), а fps=25 даёт 1/25 → следующий xfade ловит "timebase do not match"
# между running-output (после concat) и свежим v_k.
DEFAULT_SCALE_PAD = (
    "scale=1280:720:force_original_aspect_ratio=decrease,"
    "pad=1280:720:(ow-iw)/2:(oh-ih)/2,"
    "fps=25,format=yuv420p,setsar=1,settb=AVTB"
)


@dataclass
class Boundary:
    """Описание стыка между клипом index и index+1."""
    index: int                      # 0..n-2
    boundary_time: float            # timings[index+1]["start"] — граница речи
    sentence_end: float             # реальный конец речи предложения index
    pause: float                    # boundary_time - sentence_end
    has_transition: bool
    transition_type: Optional[str]  # None если hard-cut
    transition_duration: float      # 0.0 если hard-cut


def _sentence_end(timings_i: dict, whisper_words: list) -> float:
    """Фактический конец речи предложения i.

    Берём максимум из timings[i].end и end последнего whisper-слова,
    попадающего в диапазон [start_i - 0.05, end_i + 0.05], но не позже
    timings[i].end (иначе уедем в следующее предложение).
    """
    s = timings_i["start"]
    e = timings_i["end"]
    last_w_end = s  # дефолт: начало предложения (означает паузу с самого начала)
    for w in whisper_words:
        w_start = w.get("start")
        if w_start is None:
            continue
        if s - 0.05 <= w_start <= e + 0.05:
            w_end = w.get("end", w_start)
            if w_end > last_w_end:
                last_w_end = w_end
    # не выходим за границу предложения
    return min(last_w_end, e)


def _pick_order(n_boundaries: int, seed: int) -> list:
    """Детерминированный порядок переходов без повторов подряд.

    Shuffle пула с seed, проходим по кругу. Если сосед совпал с предыдущим —
    сдвигаемся на следующий элемент.
    """
    rng = random.Random(seed)
    pool = TRANSITION_POOL[:]
    rng.shuffle(pool)
    out = []
    prev = None
    i = 0
    while len(out) < n_boundaries:
        cand = pool[i % len(pool)]
        i += 1
        if cand == prev:
            cand = pool[i % len(pool)]
            i += 1
        out.append(cand)
        prev = cand
    return out


def _round_to_frame(value: float) -> float:
    """Округляет длительность до кратности кадра (0.04s при 25fps)."""
    return round(round(value / FRAME) * FRAME, 4)


def plan_boundaries(timings: list,
                    whisper_words: list,
                    audio_duration: float,
                    video_name: str,
                    default_dur: float = DEFAULT_TRANSITION_DUR) -> list:
    """Главный алгоритм. Для каждой границы между N предложениями возвращает N-1 Boundary.

    - Если пауза между предложениями >= MIN_PAUSE_FOR_TRANSITION — ставим xfade.
    - Длительность перехода: min(default_dur, pause), округлённо до кадра.
    - Тип перехода — ротация пула с детерминированным seed от имени видео.
    """
    n = len(timings)
    if n < 2:
        return []

    seed = int(hashlib.md5(video_name.encode("utf-8")).hexdigest()[:8], 16)

    # 1) Предрасчёт sentence_end для каждого предложения
    sent_ends = [_sentence_end(timings[i], whisper_words) for i in range(n)]

    # 2) Сначала считаем все паузы и помечаем, где будет переход
    raw = []  # (b_time, pause, has_transition, d)
    for i in range(n - 1):
        b_time = timings[i + 1]["start"]
        pause = b_time - sent_ends[i]
        # Половины одного предложения: group_id совпадает → только hard-cut
        same_group = (
            timings[i].get("group_id") is not None
            and timings[i].get("group_id") == timings[i + 1].get("group_id")
        )
        if pause < MIN_PAUSE_FOR_TRANSITION or same_group:
            raw.append((b_time, pause, False, 0.0))
        else:
            d = min(default_dur, pause)
            d = max(FRAME, _round_to_frame(d))
            raw.append((b_time, pause, True, d))

    # 3) Выбираем типы переходов (только для реальных переходов)
    n_transitions = sum(1 for _, _, has, _ in raw if has)
    order = _pick_order(n_transitions, seed)
    oi = 0

    boundaries = []
    for i, (b_time, pause, has, d) in enumerate(raw):
        if has:
            boundaries.append(Boundary(
                index=i,
                boundary_time=b_time,
                sentence_end=sent_ends[i],
                pause=pause,
                has_transition=True,
                transition_type=order[oi],
                transition_duration=d,
            ))
            oi += 1
        else:
            boundaries.append(Boundary(
                index=i,
                boundary_time=b_time,
                sentence_end=sent_ends[i],
                pause=pause,
                has_transition=False,
                transition_type=None,
                transition_duration=0.0,
            ))
    return boundaries


def clip_source_durations(display_durations: list, boundaries: list) -> list:
    """Длительность, которую реально надо сгенерировать в файле-источнике.

    Клип i имеет:
      display_i    = длительность в финальном таймлайне (start_{i+1} - start_i)
      left_half_i  = D/2 если boundary[i-1].has_transition (только для i>0)
      right_half_i = D/2 если boundary[i].has_transition (только для i<n-1)
      source_i     = display_i + left_half_i + right_half_i

    Обоснование: xfade «съедает» D секунд с каждой стороны стыка. Чтобы в итоге
    клип i занимал ровно display_i, исходник должен иметь на D/2 больше с каждой
    стороны, где будет переход.
    """
    n = len(display_durations)
    out = []
    for i in range(n):
        left = 0.0
        right = 0.0
        if i > 0:
            b = boundaries[i - 1]
            if b.has_transition:
                left = b.transition_duration / 2.0
        if i < n - 1:
            b = boundaries[i]
            if b.has_transition:
                right = b.transition_duration / 2.0
        # округляем до кратности кадра
        out.append(_round_to_frame(display_durations[i] + left + right))
    return out


def build_filter_complex(source_durations: list,
                         boundaries: list,
                         scale_pad: str = DEFAULT_SCALE_PAD) -> tuple:
    """Собирает filter_complex для ffmpeg: нормализация входов + цепочка xfade/concat.

    Возвращает (filter_string, final_video_label).

    Для N входов:
      [0:v]{scale_pad},setpts=PTS-STARTPTS[v0];
      [1:v]{scale_pad},setpts=PTS-STARTPTS[v1];
      ...
      [vk][v{k+1}]xfade=transition=T:duration=D:offset=O[xN]  # если has_transition
      [vk][v{k+1}]concat=n=2:v=1:a=0[cN]                       # если hard cut

    offset для k-го xfade = текущая длина running-output минус D,
    где running-output обновляется после каждого узла по правилам xfade/concat.
    """
    n = len(source_durations)
    if n == 0:
        return "", ""
    if n == 1:
        return f"[0:v]{scale_pad},setpts=PTS-STARTPTS[v0]", "v0"

    lines = []
    for i in range(n):
        lines.append(f"[{i}:v]{scale_pad},setpts=PTS-STARTPTS[v{i}]")

    cur_label = "v0"
    cur_len = source_durations[0]
    step = 0
    for i in range(n - 1):
        b = boundaries[i]
        nxt = f"v{i + 1}"
        if b.has_transition:
            d = b.transition_duration
            offset = round(cur_len - d, 4)
            out_label = f"x{step}"
            lines.append(
                f"[{cur_label}][{nxt}]xfade=transition={b.transition_type}:"
                f"duration={d}:offset={offset}[{out_label}]"
            )
            cur_len = round(cur_len + source_durations[i + 1] - d, 4)
        else:
            out_label = f"c{step}"
            lines.append(
                f"[{cur_label}][{nxt}]concat=n=2:v=1:a=0[{out_label}]"
            )
            cur_len = round(cur_len + source_durations[i + 1], 4)
        cur_label = out_label
        step += 1

    return ";".join(lines), cur_label


def summarize(boundaries: list) -> str:
    """Строка для лога: сколько xfade vs hard-cut."""
    if not boundaries:
        return "0 границ"
    trans = sum(1 for b in boundaries if b.has_transition)
    hard = len(boundaries) - trans
    return f"{trans}/{len(boundaries)} переходов, {hard} hard-cut (короткие паузы)"
