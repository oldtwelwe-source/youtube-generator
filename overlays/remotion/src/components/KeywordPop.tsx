import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

export type Position =
  | "top-left" | "top-center" | "top-right"
  | "middle-left" | "middle-center" | "middle-right"
  | "bottom-left" | "bottom-center" | "bottom-right";

export type AnimationIntensity = "subtle" | "medium" | "playful";

export type KeywordPopProps = {
  keyword: string;           // одно слово или короткая фраза
  position: Position;
  accent_color: string;      // цвет самого слова
  secondary_color: string;   // цвет обводки/подложки
  font_family: string;
  animation_intensity: AnimationIntensity;
};

export const defaultKeywordPop: KeywordPopProps = {
  keyword: "БУМ!",
  position: "middle-center",
  accent_color: "#FFD700",
  secondary_color: "#1A1A1A",
  font_family: "Inter, system-ui, sans-serif",
  animation_intensity: "playful",
};

const POSITION_STYLES: Record<Position, React.CSSProperties> = {
  "top-left":      { justifyContent: "flex-start",  alignItems: "flex-start",  padding: 80 },
  "top-center":    { justifyContent: "center",      alignItems: "flex-start",  padding: 80 },
  "top-right":     { justifyContent: "flex-end",    alignItems: "flex-start",  padding: 80 },
  "middle-left":   { justifyContent: "flex-start",  alignItems: "center",      padding: 80 },
  "middle-center": { justifyContent: "center",      alignItems: "center" },
  "middle-right":  { justifyContent: "flex-end",    alignItems: "center",      padding: 80 },
  "bottom-left":   { justifyContent: "flex-start",  alignItems: "flex-end",    padding: 80 },
  "bottom-center": { justifyContent: "center",      alignItems: "flex-end",    padding: 80 },
  "bottom-right":  { justifyContent: "flex-end",    alignItems: "flex-end",    padding: 80 },
};

export const KeywordPop: React.FC<KeywordPopProps> = ({
  keyword,
  position,
  accent_color,
  secondary_color,
  font_family,
  animation_intensity,
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames, fps } = useVideoConfig();

  // Более резкие параметры чем у других — KeywordPop должен ПЛЮХАТЬ на экран
  const intensityMap: Record<AnimationIntensity, { damping: number; stiffness: number; overshoot: number; rotate: number }> = {
    subtle:  { damping: 16, stiffness: 140, overshoot: 1.1, rotate: 0  },
    medium:  { damping: 10, stiffness: 220, overshoot: 1.3, rotate: -4 },
    playful: { damping: 6,  stiffness: 320, overshoot: 1.5, rotate: -8 },
  };
  const cfg = intensityMap[animation_intensity];

  // Резкий spring — слово буквально отскакивает
  const pop = spring({
    frame,
    fps,
    config: { damping: cfg.damping, stiffness: cfg.stiffness, mass: 0.6 },
  });

  const scale = interpolate(pop, [0, 0.6, 1], [0, cfg.overshoot, 1]);
  const rotate = interpolate(pop, [0, 1], [cfg.rotate * 3, cfg.rotate]);
  const opacity = interpolate(pop, [0, 0.25], [0, 1]);

  // Лёгкая вибрация после выхода — только для playful
  const wobble =
    animation_intensity === "playful" && pop > 0.9
      ? Math.sin((frame - 20) * 0.5) * 1.5
      : 0;

  // Короткий fade out в последние 10 кадров — KeywordPop быстрый
  const fadeOut = interpolate(
    frame,
    [durationInFrames - 10, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  return (
    // AbsoluteFill по дефолту flexDirection:"column" — переворачивает оси flexbox.
    // POSITION_STYLES написан под row, явно ставим row.
    <AbsoluteFill style={{ ...POSITION_STYLES[position], display: "flex", flexDirection: "row" }}>
      <div
        style={{
          opacity: opacity * fadeOut,
          transform: `scale(${scale}) rotate(${rotate + wobble}deg)`,
          fontSize: 120,
          fontFamily: font_family,
          fontWeight: 900,
          color: accent_color,
          letterSpacing: -2,
          lineHeight: 1,
          // Жирная обводка secondary_color — чтобы слово читалось на любом фоне
          WebkitTextStroke: `6px ${secondary_color}`,
          // Тень добавляет "глубину" и отделяет от видео-фона
          textShadow: `
            0 0 20px ${accent_color}88,
            0 8px 0 ${secondary_color}CC,
            0 14px 30px ${secondary_color}99
          `,
          textTransform: "uppercase",
          padding: "0 20px",
        }}
      >
        {keyword}
      </div>
    </AbsoluteFill>
  );
};
