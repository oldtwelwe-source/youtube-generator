"""
Compositor — накладывает отрендеренные Remotion-оверлеи на основное видео.

Вход:
  - main_video: основное final_video.mp4 (результат assemble_video_*)
  - overlays_json: overlays.json со списком оверлеев и их start_time
  - renders_dir: папка с отрендеренными webm (имена: {id}.webm)

Выход:
  - enhanced_video: final_video.mp4 с наложенными оверлеями

Логика:
  Для каждого оверлея создаётся overlay-фильтр с enable='between(t,start,end)'.
  Все фильтры соединяются в цепочку через именованные потоки [v1][v2]...
  Финальный поток маппится как видео, аудио берётся из основного видео as-is.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def _get_duration(filepath: Path) -> float | None:
    """Длительность медиафайла через ffprobe."""
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(filepath)],
            capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        return float(json.loads(proc.stdout)["format"]["duration"])
    except Exception:
        return None


def build_filter_complex(overlays: list, main_duration: float) -> tuple[str, str]:
    """Собирает filter_complex-строку с цепочкой overlay-фильтров.

    Каждый оверлей — отдельный input (индекс от 1 до N, 0 — основное видео).

    Для каждого input-webm делаем два шага:
      1. [i:v]setpts=PTS-STARTPTS+{start}/TB[oi] — сдвигаем PTS оверлея
         на его start_time в основном видео. Это стандартный FFmpeg-идиом
         (ffmpeg-user mailing list, trac.ffmpeg.org/FilteringGuide).
         Более надёжен, чем -itsoffset на уровне демуксера, потому что работает
         полностью внутри filter-графа и не зависит от того, как libvpx
         декодирует поток.
      2. [prev][oi]overlay=enable='between(t,start,end)'[vi] — накладываем
         оверлей в окне enable. Благодаря шагу 1 у оверлея уже сдвинутый PTS,
         поэтому в момент t=start он проигрывает свой первый кадр, а не
         замороженный последний.

    Возвращает (filter_string, final_stream_name).
    Если оверлеев нет — ("", "[0:v]").
    """
    if not overlays:
        return "", "[0:v]"

    lines = []
    prev = "[0:v]"

    for i, ov in enumerate(overlays):
        start = float(ov["start_time"])
        duration = float(ov.get("duration_seconds", 2.5))
        end = start + duration

        # Срезаем end по длительности основного видео, чтобы FFmpeg не фантазировал
        if end > main_duration:
            end = main_duration

        # Пропускаем оверлей, который начинается за концом видео
        if start >= main_duration:
            print(f"   ⚠️  [{ov['id']}] start={start:.2f}s за концом видео ({main_duration:.2f}s), пропуск")
            continue

        input_idx = i + 1
        shifted_label = f"[o{input_idx}]"
        out_label = f"[v{input_idx}]"

        # Шаг 1: сдвиг PTS оверлея на start секунд.
        # PTS-STARTPTS нормализует начало к 0, затем +start/TB добавляет нужный offset.
        lines.append(f"[{input_idx}:v]setpts=PTS-STARTPTS+{start:.3f}/TB{shifted_label}")

        # Шаг 2: overlay с enable-окном. С уже сдвинутым PTS overlay
        # "сам по себе" знает, когда ему играть первый кадр.
        lines.append(
            f"{prev}{shifted_label}overlay=enable='between(t,{start:.3f},{end:.3f})'{out_label}"
        )
        prev = out_label

    return ";".join(lines), prev


def composite(main_video: Path, overlays_json: Path, renders_dir: Path, output: Path) -> bool:
    """Собирает финальное видео с оверлеями."""
    if not main_video.exists():
        print(f"❌ Основное видео не найдено: {main_video}")
        return False

    if not overlays_json.exists():
        print(f"❌ overlays.json не найден: {overlays_json}")
        return False

    with open(overlays_json, "r", encoding="utf-8") as f:
        overlays = json.load(f)

    if not isinstance(overlays, list):
        overlays = [overlays]

    # Проверяем, что для каждого оверлея есть webm
    missing = []
    valid_overlays = []
    for ov in overlays:
        webm_path = renders_dir / f"{ov['id']}.webm"
        if webm_path.exists() and webm_path.stat().st_size > 1000:
            ov["_webm"] = webm_path
            valid_overlays.append(ov)
        else:
            missing.append(ov["id"])

    if missing:
        print(f"⚠️  Пропущено оверлеев (webm не найден): {len(missing)}")
        for m in missing:
            print(f"   - {m}")

    if not valid_overlays:
        print("❌ Нет ни одного валидного оверлея для композитинга")
        return False

    main_duration = _get_duration(main_video)
    if main_duration is None:
        print(f"❌ Не удалось получить длительность {main_video}")
        return False

    print(f"\n📐 Основное видео: {main_video.name} ({main_duration:.2f}s)")
    print(f"🎬 Оверлеев к наложению: {len(valid_overlays)}\n")

    # Сортируем по start_time — не критично для FFmpeg, но удобнее читать логи
    valid_overlays.sort(key=lambda x: float(x["start_time"]))

    for ov in valid_overlays:
        print(f"   [{ov['id']}] t={float(ov['start_time']):.2f}s  dur={float(ov.get('duration_seconds', 2.5)):.2f}s  {ov['type']}")

    # Собираем filter_complex
    filter_str, final_stream = build_filter_complex(valid_overlays, main_duration)

    if not filter_str:
        print("❌ filter_complex пустой (все оверлеи отфильтрованы)")
        return False

    # Формируем FFmpeg-команду
    # -i main + по одному -i на каждый webm.
    # Сдвиг PTS оверлеев делаем через setpts внутри filter_complex (см.
    # build_filter_complex), поэтому -itsoffset на уровне демуксера больше
    # не используем — setpts надёжнее и не конфликтует с libvpx-декодером.
    # `-c:v libvpx` обязателен перед каждым webm-входом: это явный декодер
    # VP8, который умеет извлекать alpha-канал из WebM (тег alpha_mode=1).
    # Без него дефолтный декодер возвращает yuv420p без альфы, и оверлей
    # ложится с чёрным фоном вместо прозрачного.
    cmd = ["ffmpeg", "-y", "-i", str(main_video)]
    for ov in valid_overlays:
        cmd += ["-c:v", "libvpx", "-i", str(ov["_webm"])]

    # Для длинных цепочек filter_complex пишем в файл,
    # чтобы не упереться в лимит длины командной строки Windows (~8000 символов)
    use_script_file = len(filter_str) > 3000
    script_path = None

    if use_script_file:
        script_path = renders_dir / "_filter_complex.txt"
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(filter_str)
        cmd += ["-filter_complex_script", str(script_path)]
        print(f"\n   📄 filter_complex в файле ({len(filter_str)} симв): {script_path}")
    else:
        cmd += ["-filter_complex", filter_str]

    # Маппинг: финальный видеопоток + аудио из основного видео без перекодирования
    cmd += [
        "-map", final_stream,
        "-map", "0:a?",  # ? = не падать если аудио нет
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-crf", "18",     # высокое качество, размер умеренный
        "-preset", "medium",
        "-c:a", "copy",   # аудио не перекодируем
        "-loglevel", "error",
        "-stats",         # показывать прогресс (кадры/fps)
        str(output),
    ]

    print(f"\n🎬 Запуск FFmpeg...")

    # На Windows subprocess нормально понимает list, shell=False надёжнее
    proc = subprocess.run(cmd, capture_output=False)

    # Чистим временный filter_script
    if script_path and script_path.exists():
        try:
            script_path.unlink()
        except OSError:
            pass

    if proc.returncode == 0 and output.exists():
        size_mb = output.stat().st_size / (1024 * 1024)
        print(f"\n✅ Готово: {output} ({size_mb:.1f} MB)")
        return True
    else:
        print(f"\n❌ FFmpeg вернул код {proc.returncode}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Compose overlays onto main video via FFmpeg")
    parser.add_argument("--main", required=True, help="Основное видео (final_video.mp4)")
    parser.add_argument("--overlays", required=True, help="Путь к overlays.json")
    parser.add_argument("--renders", required=True, help="Папка с отрендеренными webm")
    parser.add_argument("--out", required=True, help="Выходной файл (final_video_enhanced.mp4)")
    args = parser.parse_args()

    ok = composite(
        main_video=Path(args.main).resolve(),
        overlays_json=Path(args.overlays).resolve(),
        renders_dir=Path(args.renders).resolve(),
        output=Path(args.out).resolve(),
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
