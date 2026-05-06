import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

export type AnimationIntensity = "subtle" | "medium" | "playful";

export type ProgressBarProps = {
  label: string;                 // "Инфляция", "Рост рынка", "Доля ММТТ"
  value_percent: number;         // целевое значение бара, 0..100
  value_display?: string;        // что писать справа ("72%", "$1.2M", "2/5")
                                 // если не задано — показывается value_percent + "%"
  accent_color: string;          // цвет заполненной части бара
  secondary_color: string;       // цвет подложки + фона блока
  font_family: string;
  animation_intensity: AnimationIntensity;
};

export const defaultProgressBar: ProgressBarProps = {
  label: "Инфляция 1992",
  value_percent: 85,
  value_display: "2500%",
  accent_color: "#FFD700",
  secondary_color: "#1A1A1A",
  font_family: "Inter, system-ui, sans-serif",
  animation_intensity: "medium",
};

// ProgressBar — всегда внизу экрана, широкий. Позиция как props не даётся,
// чтобы бар выглядел как элемент HUD, а не плавающий оверлей
export const ProgressBar: React.FC<ProgressBarProps> = ({
  label,
  value_percent,
  value_display,
  accent_color,
  secondary_color,
  font_family,
  animation_intensity,
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames, fps } = useVideoConfig();

  // Ограничиваем 0..100 на случай если Sonnet выдаст 150 или -10
  const targetPercent = Math.max(0, Math.min(100, value_percent));

  const intensityMap: Record<AnimationIntensity, { damping: number; stiffness: number; fillStart: number }> = {
    subtle:  { damping: 24, stiffness: 80,  fillStart: 10 },
    medium:  { damping: 18, stiffness: 120, fillStart: 8  },
    playful: { damping: 12, stiffness: 180, fillStart: 5  },
  };
  const cfg = intensityMap[animation_intensity];

  // Плашка-контейнер выезжает снизу
  const containerEntry = spring({
    frame,
    fps,
    config: { damping: 18, stiffness: 150, mass: 0.8 },
  });

  // Заполнение бара начинается с задержкой — сначала появляется плашка,
  // потом "наливается" прогресс. Даёт эффект "вижу шкалу → вижу значение"
  const fillProgress = spring({
    frame: frame - cfg.fillStart,
    fps,
    config: { damping: cfg.damping, stiffness: cfg.stiffness, mass: 1.0 },
  });

  // Числовое значение считается синхронно с заполнением бара
  const displayedPercent = Math.round(fillProgress * targetPercent);
  const fillWidth = fillProgress * targetPercent; // % от контейнера

  const containerTranslateY = interpolate(containerEntry, [0, 1], [120, 0]);
  const containerOpacity = interpolate(containerEntry, [0, 0.4], [0, 1]);

  // Fade out в последние 15 кадров
  const fadeOut = interpolate(
    frame,
    [durationInFrames - 15, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        alignItems: "center",
      }}
    >
      <div
        style={{
          opacity: containerOpacity * fadeOut,
          transform: `translateY(${containerTranslateY}px)`,
          width: 1000,
          backgroundColor: secondary_color,
          padding: "20px 28px",
          borderRadius: 10,
          borderBottom: `3px solid ${accent_color}`,
        }}
      >
        {/* Верхняя строка: подпись слева, число справа */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "baseline",
            marginBottom: 12,
          }}
        >
          <div
            style={{
              fontSize: 26,
              fontFamily: font_family,
              fontWeight: 600,
              color: "#F5F5F5",
              letterSpacing: 0.5,
            }}
          >
            {label}
          </div>
          <div
            style={{
              fontSize: 34,
              fontFamily: font_family,
              fontWeight: 900,
              color: accent_color,
              letterSpacing: -0.5,
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {value_display ?? `${displayedPercent}%`}
          </div>
        </div>

        {/* Сам бар: подложка + заполнение */}
        <div
          style={{
            position: "relative",
            height: 14,
            backgroundColor: `${accent_color}22`,
            borderRadius: 7,
            overflow: "hidden",
          }}
        >
          <div
            style={{
              position: "absolute",
              left: 0,
              top: 0,
              bottom: 0,
              width: `${fillWidth}%`,
              backgroundColor: accent_color,
              borderRadius: 7,
            }}
          />
        </div>
      </div>
    </AbsoluteFill>
  );
};
