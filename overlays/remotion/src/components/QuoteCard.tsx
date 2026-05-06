import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

export type AnimationIntensity = "subtle" | "medium" | "playful";

export type QuoteCardProps = {
  quote_text: string;        // сама цитата, может быть в 2-3 строки
  author?: string;           // автор (опционально)
  accent_color: string;      // цвет кавычек и линии под автором
  secondary_color: string;   // цвет фона карточки и текста
  font_family: string;
  animation_intensity: AnimationIntensity;
};

export const defaultQuoteCard: QuoteCardProps = {
  quote_text: "Деньги — это отчеканенная свобода.",
  author: "Фёдор Достоевский",
  accent_color: "#FFD700",
  secondary_color: "#1A1A1A",
  font_family: "Playfair Display, serif",
  animation_intensity: "medium",
};

// QuoteCard — полноэкранная карточка по центру, как SectionTitle.
// Для цитаты не даём position чтобы Sonnet не ставил её в угол случайно
export const QuoteCard: React.FC<QuoteCardProps> = ({
  quote_text,
  author,
  accent_color,
  secondary_color,
  font_family,
  animation_intensity,
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames, fps } = useVideoConfig();

  const intensityMap: Record<AnimationIntensity, { damping: number; stiffness: number; overshoot: number }> = {
    subtle:  { damping: 22, stiffness: 100, overshoot: 1.0  },
    medium:  { damping: 16, stiffness: 150, overshoot: 1.03 },
    playful: { damping: 11, stiffness: 220, overshoot: 1.08 },
  };
  const cfg = intensityMap[animation_intensity];

  // Карточка появляется: fade + лёгкий scale
  const cardEntry = spring({
    frame,
    fps,
    config: { damping: cfg.damping, stiffness: cfg.stiffness, mass: 0.8 },
  });

  // Верхняя кавычка — с задержкой и отдельным движением (как "печать")
  const markEntry = spring({
    frame: frame - 10,
    fps,
    config: { damping: 12, stiffness: 180, mass: 0.7 },
  });

  // Автор — последним
  const authorEntry = spring({
    frame: frame - 20,
    fps,
    config: { damping: 18, stiffness: 140, mass: 0.8 },
  });

  const cardOpacity = interpolate(cardEntry, [0, 0.5], [0, 1]);
  const cardScale = interpolate(cardEntry, [0, 0.8, 1], [0.85, cfg.overshoot, 1]);
  const markScale = interpolate(markEntry, [0, 0.7, 1], [0, 1.3, 1]);
  const markOpacity = interpolate(markEntry, [0, 0.5], [0, 1]);
  const authorOpacity = interpolate(authorEntry, [0, 0.6], [0, 1]);
  const authorTranslateX = interpolate(authorEntry, [0, 1], [-20, 0]);

  // Общий fade out
  const fadeOut = interpolate(
    frame,
    [durationInFrames - 18, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        alignItems: "center",
        padding: 100,
        opacity: fadeOut,
      }}
    >
      <div
        style={{
          opacity: cardOpacity,
          transform: `scale(${cardScale})`,
          position: "relative",
          maxWidth: 900,
          backgroundColor: secondary_color,
          padding: "56px 72px 48px",
          borderRadius: 12,
          borderLeft: `6px solid ${accent_color}`,
        }}
      >
        {/* Декоративная большая кавычка слева сверху */}
        <div
          style={{
            position: "absolute",
            top: -20,
            left: 24,
            fontSize: 160,
            fontFamily: font_family,
            fontWeight: 900,
            color: accent_color,
            lineHeight: 1,
            opacity: markOpacity,
            transform: `scale(${markScale})`,
            transformOrigin: "top left",
            pointerEvents: "none",
            userSelect: "none",
          }}
        >
          &ldquo;
        </div>

        {/* Текст цитаты */}
        <div
          style={{
            fontSize: 40,
            fontFamily: font_family,
            fontWeight: 500,
            color: "#F5F5F5",
            lineHeight: 1.35,
            fontStyle: "italic",
            textAlign: "left",
            position: "relative",
            zIndex: 1,
          }}
        >
          {quote_text}
        </div>

        {/* Автор с тире и подчёркнутым именем */}
        {author && (
          <div
            style={{
              opacity: authorOpacity,
              transform: `translateX(${authorTranslateX}px)`,
              marginTop: 28,
              display: "flex",
              alignItems: "center",
              gap: 12,
            }}
          >
            <div style={{ width: 40, height: 2, backgroundColor: accent_color }} />
            <div
              style={{
                fontSize: 24,
                fontFamily: font_family,
                fontWeight: 600,
                color: accent_color,
                letterSpacing: 1,
                textTransform: "uppercase",
              }}
            >
              {author}
            </div>
          </div>
        )}
      </div>
    </AbsoluteFill>
  );
};
