"""YouTube Video Generator — Launcher"""
import os, sys, subprocess

# Python 3.14 на Windows по умолчанию открывает stdout в cp1251 и падает на эмодзи,
# если вывод перенаправлен (tee, файл, фоновый запуск). Фиксим до любых print'ов.
os.environ["PYTHONIOENCODING"] = "utf-8"
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Корень папок каналов. Сам код живёт в D:\YouTube-Generator,
# а все каналы/видео — отдельно, чтобы не мешались.
CHANNELS_ROOT = r"D:\MyChannelsIRL"

OVERLAYS_ANALYZER = "overlays/analyzer.py"
OVERLAYS_RENDERER = "overlays/renderer.py"
OVERLAYS_COMPOSITOR = "overlays/compositor.py"
# Имя подпапки с отрендеренными webm-оверлеями внутри папки видео
OVERLAYS_RENDERS_SUBDIR = "overlays_rendered"

def cls():
    os.system("cls" if os.name == "nt" else "clear")

def _find_file(directory, ext):
    """Ищет единственный файл с расширением ext в папке. Возвращает путь или None."""
    found = [f for f in os.listdir(directory)
             if f.lower().endswith(ext) and os.path.isfile(os.path.join(directory, f))]
    if len(found) == 1:
        return os.path.join(directory, found[0])
    return None

def _find_filename(directory, ext):
    """Возвращает имя файла с расширением ext или None."""
    found = [f for f in os.listdir(directory)
             if f.lower().endswith(ext) and os.path.isfile(os.path.join(directory, f))]
    if len(found) == 1:
        return found[0]
    return None

def _count_visuals(frames_dir):
    """Возвращает (картинки, клипы) из папки frames/."""
    if not os.path.isdir(frames_dir):
        return 0, 0
    imgs, clips = 0, 0
    for f in os.listdir(frames_dir):
        if f.startswith("frame_") and f.endswith(".png"):
            imgs += 1
        elif f.startswith("clip_") and f.endswith(".mp4"):
            clips += 1
    return imgs, clips

def _count_rendered_overlays(renders_dir):
    """Считает количество отрендеренных .webm в папке оверлеев."""
    if not os.path.isdir(renders_dir):
        return 0
    return sum(1 for f in os.listdir(renders_dir) if f.endswith(".webm"))


def _ask_transitions():
    """Спрашивает, включать ли xfade-переходы. Возвращает bool."""
    print()
    print("  Плавные переходы между клипами? (xfade)")
    print("    Переходы размещаются строго в паузах между предложениями.")
    print("    Сборка в 3-5 раз медленнее (re-encode через libx264).")
    try:
        yn = input("  Включить? (y/N): ").strip().lower()
    except EOFError:
        return False
    return yn in ("y", "yes", "д", "да")

def main():
    base = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base)
    gen = os.path.join(base, "generate.py")

    while True:
        # === Выбор канала ===
        cls()
        print()
        print("  ========================================")
        print("       YouTube Video Generator")
        print("  ========================================")
        print()
        print("  Выбери канал:")
        print()

        channels = []
        if not os.path.isdir(CHANNELS_ROOT):
            print(f"  Папка с каналами не найдена: {CHANNELS_ROOT}")
            print(f"  Создай её и положи внутрь папки каналов (finance, erifan, ...)")
            print()
            input("  Нажми Enter для выхода...")
            break
        for d in sorted(os.listdir(CHANNELS_ROOT)):
            full = os.path.join(CHANNELS_ROOT, d)
            if os.path.isdir(full) and not d.startswith("."):
                channels.append(d)

        for i, ch in enumerate(channels, 1):
            print(f"    [{i}] {ch}")

        print()
        print("    [0] Выход")
        print()

        try:
            n = int(input("  Канал: "))
        except (ValueError, EOFError):
            continue
        if n == 0:
            break
        if n < 1 or n > len(channels):
            continue

        channel = channels[n - 1]

        while True:
            # === Выбор видео ===
            cls()
            print()
            print("  ========================================")
            print(f"  Канал: {channel}")
            print("  ========================================")
            print()
            print("  Выбери видео:")
            print()

            ch_path = os.path.join(CHANNELS_ROOT, channel)
            videos = []
            for d in sorted(os.listdir(ch_path)):
                full = os.path.join(ch_path, d)
                if os.path.isdir(full):
                    videos.append(d)

            if not videos:
                print(f"    Папок нет! Создай папку внутри \"{channel}\\\"")
                print("    и положи туда .txt (сценарий) и .mp3 (озвучка)")
                print()
                input("  Нажми Enter...")
                break

            for i, v in enumerate(videos, 1):
                print(f"    [{i}] {v}")

            print()
            print("    [0] Назад")
            print()

            try:
                vn = int(input("  Видео: "))
            except (ValueError, EOFError):
                continue
            if vn == 0:
                break
            if vn < 1 or vn > len(videos):
                continue

            video = videos[vn - 1]
            video_dir = os.path.join(ch_path, video)

            while True:
                # === Меню действий ===
                cls()
                print()
                print("  ========================================")
                print(f"  Канал: {channel}")
                print(f"  Видео: {video}")
                print("  ========================================")
                print()

                has_script = _find_file(video_dir, ".txt")
                has_audio = _find_file(video_dir, ".mp3")
                script_name = _find_filename(video_dir, ".txt") or "*.txt"
                audio_name = _find_filename(video_dir, ".mp3") or "*.mp3"
                frames_dir = os.path.join(video_dir, "frames")
                img_count, clip_count = _count_visuals(frames_dir)
                has_sentences = os.path.isfile(os.path.join(frames_dir, "sentences.json"))
                has_prompts = os.path.isfile(os.path.join(frames_dir, "prompts.json"))

                # Состояние overlay-пайплайна
                has_timings = os.path.isfile(os.path.join(video_dir, "timings.json"))
                has_final_video = os.path.isfile(os.path.join(video_dir, "final_video.mp4"))
                has_overlays_json = os.path.isfile(os.path.join(video_dir, "overlays.json"))
                renders_dir = os.path.join(video_dir, OVERLAYS_RENDERS_SUBDIR)
                rendered_count = _count_rendered_overlays(renders_dir)
                has_enhanced = os.path.isfile(os.path.join(video_dir, "final_video_enhanced.mp4"))

                print(f"  {'[OK]' if has_script else '[!!]'} {script_name} {'' if has_script else '- НЕ НАЙДЕН'}")
                print(f"  {'[OK]' if has_audio else '[--]'} {audio_name} {'' if has_audio else '- нет'}")
                print(f"  [ii] Разбивка: {'есть' if has_sentences else 'нет'}   Промпты: {'есть' if has_prompts else 'нет'}")
                print(f"  [ii] Картинок: {img_count}   Клипов: {clip_count}")
                print(f"  [ii] Видео: {'есть' if has_final_video else 'нет'}   "
                      f"Оверлеи: {'есть' if has_overlays_json else 'нет'}   "
                      f"Отрендерено: {rendered_count}   "
                      f"Enhanced: {'есть' if has_enhanced else 'нет'}")
                print()
                print("  Что делать?")
                print()
                print("    --- Основное видео ---")
                print("    [1] Разбить сценарий          бесплатно")
                print("    [2] Промпты                   ~$0.01")
                print("    [3] Картинки / Клипы          ~$1 / бесплатно")
                print("    [4] Собрать видео             бесплатно")
                print("    [5] Всё сразу")
                print()
                print("    --- Оверлеи ---")
                print("    [6] Анализ сценария (Sonnet)  ~$0.05")
                print("    [7] Рендер оверлеев           бесплатно")
                print("    [8] Наложить на видео         бесплатно")
                print("    [9] Оверлеи: всё сразу (6+7+8)")
                print()
                print("    [0] Назад")
                print()

                try:
                    act = int(input("  Действие: "))
                except (ValueError, EOFError):
                    continue
                if act == 0:
                    break

                if not has_script:
                    print("\n  .txt файл (сценарий) не найден!")
                    input("  Нажми Enter...")
                    continue

                script_path = has_script
                audio_path = has_audio
                out_dir = os.path.join(video_dir, "frames")
                video_out = os.path.join(video_dir, "final_video.mp4")

                cmd = [sys.executable, gen, "-s", script_path, "-c", channel, "-o", out_dir]

                if act == 1:
                    # Только разбивка — никаких LLM, никаких вопросов
                    cmd += ["--split-only"]
                elif act == 2:
                    # Только промпты — разбивка сделается автоматически внутри generate.py
                    cmd += ["--prompts-only"]
                elif act == 3:
                    # Только визуал — нужен prompts.json
                    if not has_prompts:
                        print("\n  prompts.json не найден — сначала сделай промпты (пункт [2])")
                        input("  Нажми Enter...")
                        continue
                    cmd += ["--images-only"]
                elif act == 4:
                    # Только сборка — нужен аудио и хотя бы один визуал
                    if not has_audio:
                        print("\n  .mp3 файл (озвучка) не найден!")
                        input("  Нажми Enter...")
                        continue
                    if img_count == 0 and clip_count == 0:
                        print("\n  В папке frames/ нет ни картинок, ни клипов — нечего собирать")
                        input("  Нажми Enter...")
                        continue
                    cmd += ["-a", audio_path, "--video-output", video_out, "--assemble-only"]
                    if _ask_transitions():
                        cmd += ["--transitions"]
                elif act == 5:
                    # Всё подряд
                    if not has_audio:
                        print("\n  .mp3 файл (озвучка) не найден!")
                        input("  Нажми Enter...")
                        continue
                    cmd += ["-a", audio_path, "--video-output", video_out, "--all"]
                    if _ask_transitions():
                        cmd += ["--transitions"]
                elif act in (6, 7, 8, 9):
                    # Overlay-пайплайн: отдельный cmd, не через generate.py
                    overlays_json = os.path.join(video_dir, "overlays.json")
                    enhanced_out = os.path.join(video_dir, "final_video_enhanced.mp4")
                    main_video = os.path.join(video_dir, "final_video.mp4")

                    # Проверки предусловий для одиночных действий
                    if act == 6 and not has_timings:
                        print("\n  timings.json не найден — сначала собери видео (пункт [4] или [5])")
                        input("  Нажми Enter...")
                        continue
                    if act == 7 and not has_overlays_json:
                        print("\n  overlays.json не найден — сначала сделай анализ (пункт [6])")
                        input("  Нажми Enter...")
                        continue
                    if act == 8:
                        if not has_overlays_json:
                            print("\n  overlays.json не найден — сначала пункт [6]")
                            input("  Нажми Enter...")
                            continue
                        if rendered_count == 0:
                            print("\n  .webm оверлеи не отрендерены — сначала пункт [7]")
                            input("  Нажми Enter...")
                            continue
                        if not has_final_video:
                            print("\n  final_video.mp4 не найден — сначала собери видео (пункт [4] или [5])")
                            input("  Нажми Enter...")
                            continue
                    if act == 9:
                        if not has_timings or not has_final_video:
                            print("\n  Для полного overlay-цикла нужно готовое видео + timings.json (пункт [4] или [5])")
                            input("  Нажми Enter...")
                            continue

                    # Собираем цепочку команд. rc != 0 → прерываем цепочку
                    steps = []
                    if act in (6, 9):
                        steps.append(("Анализ сценария", [
                            sys.executable, OVERLAYS_ANALYZER,
                            "--video", video_dir, "--channel", channel,
                        ]))
                    if act in (7, 9):
                        steps.append(("Рендер оверлеев", [
                            sys.executable, OVERLAYS_RENDERER,
                            "--overlays", overlays_json, "--out", renders_dir,
                        ]))
                    if act in (8, 9):
                        steps.append(("Композит", [
                            sys.executable, OVERLAYS_COMPOSITOR,
                            "--main", main_video,
                            "--overlays", overlays_json,
                            "--renders", renders_dir,
                            "--out", enhanced_out,
                        ]))

                    # В Windows-консоли без UTF-8 emoji-принты из дочерних скриптов падают
                    env = os.environ.copy()
                    env.setdefault("PYTHONIOENCODING", "utf-8")

                    for label, step_cmd in steps:
                        print(f"\n=== {label} ===")
                        rc = subprocess.run(step_cmd, env=env).returncode
                        if rc != 0:
                            print(f"\n❌ Шаг '{label}' завершился с кодом {rc} — остановка цепочки")
                            break

                    print()
                    input("  Нажми Enter...")
                    continue
                else:
                    continue

                print()
                subprocess.run(cmd)
                print()
                input("  Нажми Enter...")


if __name__ == "__main__":
    main()
