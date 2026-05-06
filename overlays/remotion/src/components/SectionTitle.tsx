import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

export type AnimationIntensity = "subtle" | "medium" | "playful";

export type SectionTitleProps = {
  number: string;            // "1", "2", "№1" — как прислал Sonnet
  title: string;             // "Первые шаги МММ", "Крах пирамиды"
  accent_color: string;
  secondary_color: string;
  font_family: string;
  animation_intensity: AnimationIntensity;
};

export const defaultSectionTitle: SectionTitleProps = {
  number: "1",
  title: "Первые шаги",
  accent_color: "#FFD700",
  secondary_color: "#1A1A1A",
  font_family: "Playfair Display, serif",
  animation_intensity: "medium",
};

// SectionTitle всегда по центру — это полноэкранная заставка смены темы,
// поэтому позиция как props не задаётся (в отличие от других оверлеев)
export const SectionTitle: React.FC<SectionTitleProps> = ({
  number,
  title,
  accent_color,
  secondary_color,
  font_family,
  animation_intensity,
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames, fps } = useVideoConfig();

  const intensityMap: Record<AnimationIntensity, { damping: number; stiffness: number; barOvershoot: number }> = {
    subtle:  { damping: 20, stiffness: 100, barOvershoot: 1.0  },
    medium:  { damping: 14, stiffness: 160, barOvershoot: 1.05 },
    playful: { damping: 9,  stiffness: 240, barOvershoot: 1.15 },
  };
  const cfg = intensityMap[animation_intensity];

  // Горизонтальная линия-разделитель выезжает сначала
  const barEntry = spring({
    frame,
    fps,
    config: { damping: 16, stiffness: 140, mass: 0.7 },
  });

  // Номер появляется вторым с задержкой
  const numberEntry = spring({
    frame: frame - 6,
    fps,
    config: { damping: cfg.damping, stiffness: cfg.stiffness, mass: 0.8 },
  });

  // Заголовок — третьим
  const titleEntry = spring({
    frame: frame - 14,
    fps,
    config: { damping: 18, stiffness: 150, mass: 0.8 },
  });

  const barWidth = interpolate(barEntry, [0, 1], [0, 1]);
  const numberScale = interpolate(numberEntry, [0, 0.7, 1], [0.3, cfg.barOvershoot, 1]);
  const numberOpacity = interpolate(numberEntry, [0, 0.4], [0, 1]);
  const titleTranslateY = interpolate(titleEntry, [0, 1], [30, 0]);
  const titleOpacity = interpolate(titleEntry, [0, 0.5], [0, 1]);

  // Общий fade out в последние 15 кадров
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
        opacity: fadeOut,
      }}
    >
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 20,
        }}
      >
        {/* Короткое слово "ФАКТ" или "ГЛАВА" над номером — опускаем пока,
            чтобы компонент оставался универсальным: если Sonnet хочет слово,
            он кладёт его в title или в отдельный префикс (расширим позже) */}

        {/* Номер — крупный, с отскоком */}
        <div
          style={{
            opacity: numberOpacity,
            transform: `scale(${numberScale})`,
            fontSize: 180,
            fontFamily: font_family,
            fontWeight: 900,
            color: accent_color,
            lineHeight: 1,
            letterSpacing: -4,
            WebkitTextStroke: `4px ${secondary_color}`,
            paintOrder: "stroke fill",
          }}
        >
          №{number}
        </div>

        {/* Горизонтальная линия-разделитель — растёт от центра.
            Без partial opacity (VP8 альфа субсэмпл => ореол). */}
        <div
          style={{
            transform: `scaleX(${barWidth})`,
            transformOrigin: "center",
            width: 320,
            height: 3,
            backgroundColor: accent_color,
          }}
        />

        {/* Заголовок секции: плашка secondary_color с текстом accent_color —
            обеспечивает читаемость поверх любого видео и фирменный акцент */}
        <div
          style={{
            opacity: titleOpacity,
            transform: `translateY(${titleTranslateY}px)`,
            fontSize: 54,
            fontFamily: font_family,
            fontWeight: 600,
            color: accent_color,
            textAlign: "center",
            letterSpacing: 1,
            maxWidth: 1000,
            backgroundColor: secondary_color,
            padding: "14px 48px",
            borderRadius: 8,
          }}
        >
          {title}
        </div>
      </div>
    </AbsoluteFill>
  );
};
