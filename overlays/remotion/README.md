# YouTube Generator — Overlays (Remotion)

Motion-graphics оверлеи для основного пайплайна. Рендерятся как отдельные
WebM-клипы с alpha-каналом, потом накладываются на final_video.mp4 через FFmpeg.

## Установка (один раз)

Открой cmd в папке `D:\YouTube-Generator\overlays\remotion\` и выполни:

```cmd
npm install
```

Это скачает Remotion и его зависимости (~300 МБ вместе с headless Chrome,
который Remotion скачает автоматически при первом запуске). Займёт несколько минут.

## Проверка установки: Remotion Studio

Чтобы посмотреть превью оверлеев в браузере (как дизайнер видит анимации),
выполни из той же папки:

```cmd
npm run preview
```

Откроется браузер с Remotion Studio. Ты должен увидеть слева две композиции:
- **TestCard** — простая карточка с текстом
- **NumberReveal** — цифра вылетает с анимацией

Нажми на любую, посмотри превью, покрути параметры справа (там должны быть
`value`, `caption`, `position`, `accent_color` и т.д.).

**Если Studio открылся и превью работает — фундамент готов, можно идти дальше.**

## Тестовый рендер в файл

Чтобы проверить, что рендер в webm действительно работает:

```cmd
npx remotion render src/index.ts NumberReveal out/test.webm
```

На выходе получишь `out/test.webm` — прозрачный видео-файл 2.5 сек, который
можно открыть в VLC или наложить через FFmpeg на любое видео:

```cmd
ffmpeg -i your_video.mp4 -i out/test.webm -filter_complex "[0][1]overlay=enable='between(t,2,4.5)'" result.mp4
```

## Если что-то пошло не так

1. Проверь версию Node: `node --version` должна быть 20.x или выше
2. Если `npm install` падает на скачивании Chrome — иногда помогает запустить ещё раз
3. Если Studio открывается но ничего не показывает — глянь в cmd, там будут ошибки
