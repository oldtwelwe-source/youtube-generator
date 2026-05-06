import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

export type AnimationIntensity = "subtle" | "medium" | "playful";

// Chapter поддерживает только top/bottom — это узкая полоска по ширине экрана,
// поэтому left/center/right не имеют смысла
export type ChapterPosition = "top" | "bottom";

export type ChapterProps = {
  chapter_name: string;      // "Глава 1: Зарождение МММ"
  position: ChapterPosition; // "top" или "bottom"
  accent_color: string;      // цвет подчёркивания + левой "засечки"
  secondary_color: string;   // цвет фона полоски
  font_family: string;
  animation_intensity: AnimationIntensity;
};

export const defaultChapter: ChapterProps = {
  chapter_name: "Глава 1: Зарождение МММ",
  position: "bottom",
  accent_color: "#FFD700",
  secondary_color: "#1A1A1A",
  font_family: "Playfair Display, serif",
  animation_intensity: "subtle",
};

// В отличие от остальных оверлеев, Chapter "живёт" всю свою длительность —
// это постоянный HUD-элемент, а не вспышка. Анимация входа и выхода
// занимает строго фикс. окна в начале и конце, остальное время он статичен
export const Chapter: React.FC<ChapterProps> = ({
  chapter_name,
  position,
  accent_color,
  secondary_color,
  font_family,
  animation_intensity,
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames, fps } = useVideoConfig();

  const intensityMap: Record<AnimationIntensity, { damping: number; stiffness: number }> = {
    subtle:  { damping: 22, stiffness: 100 },
    medium:  { damping: 16, stiffness: 150 },
    playful: { damping: 10, stiffness: 220 },
  };
  const cfg = intensityMap[animation_intensity];

  // Вход в первые 20 кадров (сверху или снизу в зависимости от position)
  const enterSpring = spring({
    frame,
    fps,
    config: { damping: cfg.damping, stiffness: cfg.stiffness, mass: 0.9 },
  });

  // Выход в последние 15 кадров — плавное исчезновение
  const exitFrame = durationInFrames - 15;
  const exitProgress = interpolate(
    frame,
    [exitFrame, durationInFrames],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  // Направление входа/выхода зависит от позиции
  const isTop = position === "top";
  const enterTranslateY = interpolate(enterSpring, [0, 1], [isTop ? -80 : 80, 0]);
  const exitTranslateY = interpolate(exitProgress, [0, 1], [0, isTop ? -80 : 80]);
  const translateY = enterTranslateY + exitTranslateY;
  const opacity = Math.min(
    interpolate(enterSpring, [0, 0.6], [0, 1]),
    interpolate(exitProgress, [0, 1], [1, 0])
  );

  return (
    <AbsoluteFill
      style={{
        justifyContent: isTop ? "flex-start" : "flex-end",
        alignItems: "stretch",
      }}
    >
      <div
        style={{
          opacity,
          transform: `translateY(${translateY}px)`,
          width: "100%",
          backgroundColor: `${secondary_color}E0`,
          // Верхняя полоска рисует засечку снизу, нижняя — сверху,
          // чтобы акцент "смотрел" в сторону видео
          borderTop: isTop ? "none" : `3px solid ${accent_color}`,
          borderBottom: isTop ? `3px solid ${accent_color}` : "none",
          padding: "14px 48px",
          display: "flex",
          alignItems: "center",
          gap: 20,
          boxShadow: isTop
            ? `0 4px 20px ${secondary_color}66`
            : `0 -4px 20px ${secondary_color}66`,
        }}
      >
        {/* Короткая цветная "засечка" слева — визуальный якорь */}
        <div
          style={{
            width: 8,
            height: 32,
            backgroundColor: accent_color,
            borderRadius: 2,
            flexShrink: 0,
          }}
        />
        {/* Название главы */}
        <div
          style={{
            fontSize: 26,
            fontFamily: font_family,
            fontWeight: 600,
            color: "#F5F5F5",
            letterSpacing: 1,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
            flex: 1,
          }}
        >
          {chapter_name}
        </div>
      </div>
    </AbsoluteFill>
  );
};
