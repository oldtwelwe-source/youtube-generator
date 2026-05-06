import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";

export type TestCardProps = {
  text: string;
  accent_color: string;
  secondary_color: string;
};

export const defaultTestCard: TestCardProps = {
  text: "Test Card",
  accent_color: "#FFD700",
  secondary_color: "#1A1A1A",
};

export const TestCard: React.FC<TestCardProps> = ({
  text,
  accent_color,
  secondary_color,
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  // Fade in за первые 10 кадров, fade out за последние 10
  const opacity = interpolate(
    frame,
    [0, 10, durationInFrames - 10, durationInFrames],
    [0, 1, 1, 0],
    { extrapolateRight: "clamp" }
  );

  // Лёгкий scale-in
  const scale = interpolate(frame, [0, 15], [0.8, 1], {
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        alignItems: "center",
        // ВАЖНО: НЕ ставим background — оставляем прозрачный фон,
        // чтобы оверлей накладывался поверх основного видео
        backgroundColor: "transparent",
      }}
    >
      <div
        style={{
          opacity,
          transform: `scale(${scale})`,
          padding: "40px 80px",
          backgroundColor: secondary_color,
          color: accent_color,
          fontSize: 80,
          fontFamily: "system-ui, -apple-system, sans-serif",
          fontWeight: 700,
          borderRadius: 20,
          border: `4px solid ${accent_color}`,
          boxShadow: "0 20px 60px rgba(0,0,0,0.5)",
        }}
      >
        {text}
      </div>
    </AbsoluteFill>
  );
};
