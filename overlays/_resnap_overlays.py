"""Служебный скрипт: применяет snap start_time из analyzer._snap_start_time
к уже готовому overlays.json, не дёргая LLM. Нужен, чтобы протестировать
новую логику таймингов на существующих данных без повторного вызова OpenAI.

Usage:
    python _resnap_overlays.py --video <path> --out <new_overlays.json>
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from analyzer import _load_whisper_words, _snap_start_time, _detect_language  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True, help="Папка с видео")
    parser.add_argument("--in", dest="inp", default=None,
                        help="Исходный overlays.json (по умолчанию <video>/overlays.json)")
    parser.add_argument("--out", required=True, help="Куда сохранить snap-версию")
    args = parser.parse_args()

    video_dir = Path(args.video).resolve()
    src = Path(args.inp).resolve() if args.inp else video_dir / "overlays.json"
    out = Path(args.out).resolve()

    overlays = json.loads(src.read_text(encoding="utf-8"))
    whisper_words = _load_whisper_words(video_dir)

    # Язык нужен, чтобы выкинуть стоп-слова при snap'е
    script_candidates = sorted(video_dir.glob("*.txt"))
    lang = "ru"
    if script_candidates:
        lang = _detect_language(script_candidates[0].read_text(encoding="utf-8"))

    print(f"📂 Исходник:       {src}")
    print(f"📂 Whisper-слов:   {len(whisper_words)}")
    print(f"🗣  Язык:           {lang}")
    print(f"🎬 Оверлеев:       {len(overlays)}\n")

    for i, ov in enumerate(overlays):
        original = float(ov["start_time"])
        snapped, matched = _snap_start_time(ov, whisper_words, lang)
        delta = snapped - original
        flag = "🎯" if matched and abs(delta) > 0.05 else "· "
        print(f"   {flag} [{ov['id']}] {ov['type']:<14} "
              f"{original:6.2f}s → {snapped:6.2f}s  Δ={delta:+5.2f}s")
        ov["start_time"] = round(snapped, 2)

    out.write_text(json.dumps(overlays, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n💾 Сохранено: {out}")


if __name__ == "__main__":
    main()
