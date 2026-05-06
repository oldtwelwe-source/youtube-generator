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

export type LocationLabelProps = {
  location_name: string;     // "Москва", "Уолл-стрит", и т.п.
  position: Position;
  accent_color: string;      // цвет пина и акцентов
  secondary_color: string;   // цвет фона плашки
  font_family: string;
  animation_intensity: AnimationIntensity;
};

export const defaultLocationLabel: LocationLabelProps = {
  location_name: "Москва",
  position: "top-left",
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

export const LocationLabel: React.FC<LocationLabelProps> = ({
  location_name,
  position,
  accent_color,
  secondary_color,
  font_family,
  animation_intensity,
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames, fps } = useVideoConfig();

  const intensityMap: Record<AnimationIntensity, { damping: number; stiffness: number; pinOvershoot: number }> = {
    subtle:  { damping: 18, stiffness: 110, pinOvershoot: 1.0  },
    medium:  { damping: 12, stiffness: 180, pinOvershoot: 1.1  },
    playful: { damping: 8,  stiffness: 260, pinOvershoot: 1.25 },
  };
  const cfg = intensityMap[animation_intensity];

  // Пин "падает" сверху с отскоком
  const pinDrop = spring({
    frame,
    fps,
    config: { damping: cfg.damping, stiffness: cfg.stiffness, mass: 0.9 },
  });

  // Плашка с названием выезжает справа от пина с задержкой
  const labelReveal = spring({
    frame: frame - 8,
    fps,
    config: { damping: 16, stiffness: 150, mass: 0.8 },
  });

  const pinTranslateY = interpolate(pinDrop, [0, 0.7, 1], [-80, 6, 0]);
  const pinScale = interpolate(pinDrop, [0, 0.8, 1], [0.3, cfg.pinOvershoot, 1]);
  const pinOpacity = interpolate(pinDrop, [0, 0.3], [0, 1]);

  const labelWidth = interpolate(labelReveal, [0, 1], [0, 1]);
  const labelOpacity = interpolate(labelReveal, [0, 0.5], [0, 1]);

  // Общий fade out
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
          display: "flex",
          alignItems: "center",
          gap: 0,
          opacity: fadeOut,
        }}
      >
        {/* Пин — круглая плашка с эмодзи 📍 */}
        <div
          style={{
            opacity: pinOpacity,
            transform: `translateY(${pinTranslateY}px) scale(${pinScale})`,
            width: 64,
            height: 64,
            borderRadius: "50%",
            backgroundColor: accent_color,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 36,
            zIndex: 2,
          }}
        >
          📍
        </div>
        {/* Плашка с названием: растёт в ширину от пина */}
        <div
          style={{
            opacity: labelOpacity,
            transformOrigin: "left center",
            transform: `scaleX(${labelWidth})`,
            height: 48,
            display: "flex",
            alignItems: "center",
            paddingLeft: 28,
            paddingRight: 24,
            marginLeft: -14, // чуть заезжает под пин чтобы не было шва
            backgroundColor: secondary_color,
            borderRadius: "0 24px 24px 0",
            fontSize: 28,
            fontFamily: font_family,
            fontWeight: 600,
            color: accent_color,
            letterSpacing: 1,
            whiteSpace: "nowrap",
            zIndex: 1,
          }}
        >
          {/* Текст не масштабируется вместе с плашкой — компенсируем scaleX
              через inverse scale, чтобы буквы оставались нормальной ширины */}
          <span
            style={{
              transform: `scaleX(${labelWidth === 0 ? 1 : 1 / labelWidth})`,
              transformOrigin: "left center",
              display: "inline-block",
            }}
          >
            {location_name}
          </span>
        </div>
      </div>
    </AbsoluteFill>
  );
};
