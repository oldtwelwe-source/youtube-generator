import { Config } from "@remotion/cli/config";

// Настройки рендера для прозрачных webm-оверлеев.
// Источник: https://www.remotion.dev/docs/transparent-videos
//
// vp8 + yuva420p + png — официальный набор для alpha-канала в Remotion.
// vp9 тоже поддерживает alpha, но в WebM хранит её иначе и наш FFmpeg-
// пайплайн (compositor.py использует -c:v libvpx) заточен под vp8.
// Ровно те же флаги дублируются в renderer.py как --codec/--pixel-format/
// --image-format, чтобы CLI не молча откатывался на дефолты.
Config.setCodec("vp8");
Config.setPixelFormat("yuva420p");
Config.setVideoImageFormat("png");
Config.setConcurrency(1); // стабильнее на Windows + предсказуемая память

// CRF для VP8: диапазон 4..63, меньше = выше качество. Remotion-дефолт = 9,
// на нём шрифты оверлеев заметно пикселизировались после композитинга.
// 4 — практически максимум VP8 без раздувания размера (короткие оверлеи).
Config.setCrf(4);
