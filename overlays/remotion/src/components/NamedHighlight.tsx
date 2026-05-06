import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

// Типы и позиционирование — идентичны NumberReveal чтобы Sonnet мог
// выдавать одинаковые position-значения для всех компонентов
export type Position =
  | "top-left" | "top-center" | "top-right"
  | "middle-left" | "middle-center" | "middle-right"
  | "bottom-left" | "bottom-center" | "bottom-right";

export type AnimationIntensity = "subtle" | "medium" | "playful";

export type NamedHighlightProps = {
  text: string;              // имя или термин, который подсвечиваем
  position: Position;
  accent_color: string;      // цвет подсветки (маркера)
  secondary_color: string;   // цвет текста
  font_family: string;
  animation_intensity: AnimationIntensity;
};

export const defaultNamedHighlight: NamedHighlightProps = {
  text: "Сергей Мавроди",
  position: "bottom-center",
  accent_color: "#FFD700",
  secondary_color: "#1A1A1A",
  font_family: "Playfair Display, serif",
  animation_intensity: "medium",
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

export const NamedHighlight: React.FC<NamedHighlightProps> = ({
  text,
  position,
  accent_color,
  secondary_color,
  font_family,
  animation_intensity,
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames, fps } = useVideoConfig();

  const intensityMap: Record<AnimationIntensity, { damping: number; stiffness: number; highlightDelay: number }> = {
    subtle:  { damping: 20, stiffness: 100, highlightDelay: 10 },
    medium:  { damping: 14, stiffness: 160, highlightDelay: 8  },
    playful: { damping: 10, stiffness: 240, highlightDelay: 5  },
  };
  const cfg = intensityMap[animation_intensity];

  // Текст появляется быстрым fade-in + лёгкий slide снизу
  const textEntry = spring({
    frame,
    fps,
    config: { damping: cfg.damping, stiffness: cfg.stiffness, mass: 0.7 },
  });

  // Подсветка "прорастает" слева направо с задержкой, чтобы сначала
  // был виден текст, а потом под ним пробежала полоса маркера
  const highlightGrow = spring({
    frame: frame - cfg.highlightDelay,
    fps,
    config: { damping: 22, stiffness: 140, mass: 0.9 },
  });

  const textTranslateY = interpolate(textEntry, [0, 1], [20, 0]);
  const textOpacity = interpolate(textEntry, [0, 0.5], [0, 1]);
  const highlightScaleX = interpolate(highlightGrow, [0, 1], [0, 1]);

  // Fade out в последние 15 кадров — общий пэттерн всех оверлеев
  const fadeOut = interpolate(
    frame,
    [durationInFrames - 15, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  return (
    // AbsoluteFill по дефолту flexDirection:"column" — переворачивает оси flexbox.
    // POSITION_STYLES написан под row, явно ставим row.
    <AbsoluteFill style={{ ...POSITION_STYLES[position], display: "flex", flexDirection: "row" }}>
      <div
        style={{
          position: "relative",
          display: "inline-block",
          opacity: fadeOut,
        }}
      >
        {/* Подсветка-маркер под текстом: сплошная полоса,
            "прорастает" слева направо. Без partial opacity —
            VP8 альфа субсэмплится и превращает 0.55 в размытый ореол */}
        <div
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            bottom: 6,
            height: "40%",
            backgroundColor: accent_color,
            transformOrigin: "left center",
            transform: `scaleX(${highlightScaleX})`,
            borderRadius: 4,
            zIndex: 0,
          }}
        />
        {/* Сам текст поверх подсветки */}
        <div
          style={{
            position: "relative",
            opacity: textOpacity,
            transform: `translateY(${textTranslateY}px)`,
            fontSize: 64,
            fontFamily: font_family,
            fontWeight: 700,
            color: secondary_color,
            letterSpacing: -0.5,
            padding: "0 16px",
            zIndex: 1,
          }}
        >
          {text}
        </div>
      </div>
    </AbsoluteFill>
  );
};
