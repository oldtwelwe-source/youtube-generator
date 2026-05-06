"""
Remotion Renderer — Python-обёртка над `npx remotion render`.

Принимает список оверлеев из JSON и рендерит каждый в отдельный webm-файл
с alpha-каналом. На выходе — готовые клипы для композитинга через FFmpeg.

Формат входного JSON (overlays.json):
[
  {
    "id": "overlay_001",
    "type": "NumberReveal",         # имя композиции в Root.tsx
    "start_time": 3.5,              # когда показывать в финальном видео (сек)
    "duration_seconds": 2.5,        # сколько длится сам оверлей
    "params": {                     # props для компонента
      "value": "1998",
      "caption": "год",
      "position": "top-right",
      "accent_color": "#FFD700",
      "secondary_color": "#1A1A1A",
      "font_family": "Inter",
      "animation_intensity": "medium"
    }
  }
]

Usage:
    python renderer.py --overlays path/to/overlays.json --out path/to/output_dir
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


# Корень Remotion-проекта относительно этого скрипта
REMOTION_DIR = Path(__file__).parent / "remotion"
ENTRY_POINT = "src/index.ts"


def _run_npx_remotion(args: list, cwd: Path) -> tuple[int, str, str]:
    """Вызывает npx remotion с аргументами.

    На Windows npx — это npx.cmd, запускаем через shell=True для надёжности.
    Возвращает (returncode, stdout, stderr), декодированные в utf-8.
    """
    # Собираем команду: npx remotion <args...>
    cmd = ["npx", "remotion"] + args

    # На Windows shell=True нужен чтобы нашёлся npx.cmd в PATH
    use_shell = (os.name == "nt")

    if use_shell:
        # Для shell=True передаём строкой, экранируя пробелы в путях
        cmd_str = " ".join(f'"{a}"' if " " in str(a) else str(a) for a in cmd)
        proc = subprocess.run(
            cmd_str,
            cwd=str(cwd),
            shell=True,
            capture_output=True,
            # На Windows Remotion пишет в utf-8, но cmd по умолчанию cp866/cp1251,
            # явно указываем декодер и не падаем на неведомых байтах
            encoding="utf-8",
            errors="replace",
        )
    else:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
        )

    return proc.returncode, proc.stdout or "", proc.stderr or ""


def render_one_overlay(overlay: dict, out_dir: Path) -> dict:
    """Рендерит один оверлей. Возвращает dict с результатом."""
    ov_id = overlay["id"]
    comp_id = overlay["type"]
    duration = float(overlay.get("duration_seconds", 2.5))
    params = dict(overlay.get("params", {}))

    # duration_seconds передаём внутри props — его подхватит calculateMetadata в Root.tsx
    params["duration_seconds"] = duration

    out_file = out_dir / f"{ov_id}.webm"

    # На Windows нельзя передавать JSON inline (cmd съест кавычки),
    # обязательно через файл. Используем tempfile для чистоты.
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as pf:
        json.dump(params, pf, ensure_ascii=False)
        props_path = pf.name

    try:
        args = [
            "render",
            ENTRY_POINT,
            comp_id,
            str(out_file),
            f"--props={props_path}",
            # Официальный рецепт из доков Remotion для прозрачных webm:
            #   --image-format=png     — JPEG не поддерживает alpha, нужен PNG
            #   --pixel-format=yuva420p — формат с alpha-каналом
            #   --codec=vp8            — vp8 надёжнее работает с alpha чем vp9
            # https://www.remotion.dev/docs/transparent-videos
            "--image-format=png",
            "--pixel-format=yuva420p",
            "--codec=vp8",
            # CRF=4 — верхняя граница качества VP8 (диапазон 4..63, дефолт 9).
            # Нужен, чтобы шрифты оверлеев не пикселизировались после композитинга
            # в финальное mp4. Дублируется в remotion.config.ts через setCrf(4).
            "--crf=4",
            # Оверлеи беззвучные, отключаем аудио-дорожку
            "--muted",
        ]

        print(f"  🎬 [{ov_id}] {comp_id} ({duration:.1f}s) ...", flush=True)
        rc, stdout, stderr = _run_npx_remotion(args, REMOTION_DIR)

        if rc == 0 and out_file.exists() and out_file.stat().st_size > 1000:
            size_kb = out_file.stat().st_size // 1024
            print(f"     ✅ {out_file.name} ({size_kb} KB)")
            return {"id": ov_id, "ok": True, "path": str(out_file), "size_kb": size_kb}
        else:
            # Собираем диагностику для отладки
            tail = (stderr or stdout)[-800:] if (stderr or stdout) else "no output"
            print(f"     ❌ rc={rc}")
            print(f"     stderr tail: {tail}")
            return {"id": ov_id, "ok": False, "error": tail}
    finally:
        # Чистим временный props-файл
        try:
            os.unlink(props_path)
        except OSError:
            pass


def render_overlays(overlays_json_path: Path, out_dir: Path) -> list:
    """Главная функция — читает overlays.json и рендерит всё по списку."""
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(overlays_json_path, "r", encoding="utf-8") as f:
        overlays = json.load(f)

    if not isinstance(overlays, list):
        overlays = [overlays]

    print(f"📂 Remotion project: {REMOTION_DIR}")
    print(f"📂 Output dir:       {out_dir}")
    print(f"🎬 Всего оверлеев:   {len(overlays)}\n")

    # Проверяем, что Remotion-проект существует и был установлен
    if not (REMOTION_DIR / "node_modules").exists():
        print("❌ node_modules не найдена. Запусти в папке remotion/ команду: npm install")
        sys.exit(1)

    results = []
    for ov in overlays:
        results.append(render_one_overlay(ov, out_dir))

    # Итоги
    ok = sum(1 for r in results if r["ok"])
    fail = len(results) - ok
    print(f"\n📊 Готово: {ok} успешно, {fail} с ошибкой")

    # Сохраняем отчёт рядом с оверлеями
    report_path = out_dir / "render_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"📄 Отчёт: {report_path}")

    return results


def main():
    parser = argparse.ArgumentParser(description="Remotion overlays renderer")
    parser.add_argument(
        "--overlays",
        required=True,
        help="Путь к overlays.json",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Папка для выходных .webm файлов",
    )
    args = parser.parse_args()

    overlays_path = Path(args.overlays).resolve()
    out_dir = Path(args.out).resolve()

    if not overlays_path.exists():
        print(f"❌ Не найден файл: {overlays_path}")
        sys.exit(1)

    results = render_overlays(overlays_path, out_dir)
    failed = [r for r in results if not r["ok"]]
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
