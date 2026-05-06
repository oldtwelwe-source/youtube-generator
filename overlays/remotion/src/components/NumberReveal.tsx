import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

// Типы props — ровно то, что Sonnet будет возвращать через tool_use
export type Position =
  | "top-left" | "top-center" | "top-right"
  | "middle-left" | "middle-center" | "middle-right"
  | "bottom-left" | "bottom-center" | "bottom-right";

export type AnimationIntensity = "subtle" | "medium" | "playful";

export type NumberRevealProps = {
  value: string;
  caption?: string;
  position: Position;
  accent_color: string;
  secondary_color: string;
  font_family: string;
  animation_intensity: AnimationIntensity;
};

export const defaultNumberReveal: NumberRevealProps = {
  value: "1998",
  caption: "год",
  position: "top-right",
  accent_color: "#FFD700",
  secondary_color: "#1A1A1A",
  font_family: "Inter, system-ui, sans-serif",
  animation_intensity: "medium",
};

// Маппинг позиций на CSS flexbox
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

export const NumberReveal: React.FC<NumberRevealProps> = ({
  value,
  caption,
  position,
  accent_color,
  secondary_color,
  font_family,
  animation_intensity,
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames, fps } = useVideoConfig();

  // Параметры анимации зависят от "темперамента"
  const intensityMap: Record<AnimationIntensity, { damping: number; stiffness: number; overshoot: number }> = {
    subtle:  { damping: 20, stiffness: 100, overshoot: 1.0  },
    medium:  { damping: 12, stiffness: 180, overshoot: 1.05 },
    playful: { damping: 8,  stiffness: 260, overshoot: 1.15 },
  };
  const cfg = intensityMap[animation_intensity];

  // Spring для entry — естественное появление с отскоком
  const entry = spring({
    frame,
    fps,
    config: { damping: cfg.damping, stiffness: cfg.stiffness, mass: 0.8 },
  });

  // Translate Y: вылетает сверху (если позиция top) или снизу (если bottom)
  const isTop = position.startsWith("top");
  const translateY = interpolate(entry, [0, 1], [isTop ? -120 : 120, 0]);
  const scale = interpolate(entry, [0, 0.7, 1], [0.4, cfg.overshoot, 1]);

  // Fade out в последние 15 кадров
  const fadeOut = interpolate(
    frame,
    [durationInFrames - 15, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );
  const opacity = interpolate(entry, [0, 0.3], [0, 1]) * fadeOut;

  return (
    // AbsoluteFill по дефолту flexDirection:"column" — это переворачивает оси flexbox
    // (justifyContent→вертикаль, alignItems→горизонталь). POSITION_STYLES написан под row.
    <AbsoluteFill style={{ ...POSITION_STYLES[position], display: "flex", flexDirection: "row" }}>
      <div
        style={{
          opacity,
          transform: `translateY(${translateY}px) scale(${scale})`,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 8,
        }}
      >
        {/* Основное число */}
        <div
          style={{
            fontSize: 130,
            fontFamily: font_family,
            fontWeight: 900,
            color: accent_color,
            WebkitTextStroke: `3px ${secondary_color}`,
            paintOrder: "stroke fill",
            letterSpacing: -2,
            lineHeight: 1,
          }}
        >
          {value}
        </div>

        {/* Подпись (если задана) — без partial opacity, VP8 альфа
            субсэмплится по 4:2:0 и превращает 0.85 в грязный ореол */}
        {caption && (
          <div
            style={{
              fontSize: 28,
              fontFamily: font_family,
              fontWeight: 600,
              color: accent_color,
              WebkitTextStroke: `2px ${secondary_color}`,
              paintOrder: "stroke fill",
              textTransform: "uppercase",
              letterSpacing: 4,
            }}
          >
            {caption}
          </div>
        )}
      </div>
    </AbsoluteFill>
  );
};
