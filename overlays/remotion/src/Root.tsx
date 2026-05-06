import React from "react";
import { Composition } from "remotion";
import { NumberReveal, defaultNumberReveal, NumberRevealProps } from "./components/NumberReveal";
import { TestCard, defaultTestCard, TestCardProps } from "./components/TestCard";
import { NamedHighlight, defaultNamedHighlight, NamedHighlightProps } from "./components/NamedHighlight";
import { LocationLabel, defaultLocationLabel, LocationLabelProps } from "./components/LocationLabel";
import { SectionTitle, defaultSectionTitle, SectionTitleProps } from "./components/SectionTitle";
import { QuoteCard, defaultQuoteCard, QuoteCardProps } from "./components/QuoteCard";
import { KeywordPop, defaultKeywordPop, KeywordPopProps } from "./components/KeywordPop";
import { ProgressBar, defaultProgressBar, ProgressBarProps } from "./components/ProgressBar";
import { Chapter, defaultChapter, ChapterProps } from "./components/Chapter";

// Default canvas dimensions (соответствует 720p из основного пайплайна)
const WIDTH = 1280;
const HEIGHT = 720;
const FPS = 30;

// Универсальный calculateMetadata:
// если в props пришёл `duration_seconds` — конвертим в кадры,
// иначе оставляем дефолтную длительность композиции.
// Это позволяет рендерить один и тот же компонент разной длительности,
// не создавая кучу композиций под каждую секунду.
const makeCalc = (defaultFrames: number) =>
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ({ props }: { props: any }) => {
    const dur = props?.duration_seconds;
    const frames = typeof dur === "number" && dur > 0
      ? Math.round(dur * FPS)
      : defaultFrames;
    return { durationInFrames: frames };
  };

// Default props с дополнительным полем duration_seconds,
// чтобы TypeScript не ругался при его чтении в calculateMetadata
const defaultTestCardWithDur: TestCardProps & { duration_seconds?: number } = {
  ...defaultTestCard,
  duration_seconds: 3,
};

const defaultNumberRevealWithDur: NumberRevealProps & { duration_seconds?: number } = {
  ...defaultNumberReveal,
  duration_seconds: 2.5,
};

const defaultNamedHighlightWithDur: NamedHighlightProps & { duration_seconds?: number } = {
  ...defaultNamedHighlight,
  duration_seconds: 2.5,
};

const defaultLocationLabelWithDur: LocationLabelProps & { duration_seconds?: number } = {
  ...defaultLocationLabel,
  duration_seconds: 2.5,
};

const defaultSectionTitleWithDur: SectionTitleProps & { duration_seconds?: number } = {
  ...defaultSectionTitle,
  duration_seconds: 2.5,
};

const defaultQuoteCardWithDur: QuoteCardProps & { duration_seconds?: number } = {
  ...defaultQuoteCard,
  duration_seconds: 4.0,
};

const defaultKeywordPopWithDur: KeywordPopProps & { duration_seconds?: number } = {
  ...defaultKeywordPop,
  duration_seconds: 1.5,
};

const defaultProgressBarWithDur: ProgressBarProps & { duration_seconds?: number } = {
  ...defaultProgressBar,
  duration_seconds: 3.5,
};

const defaultChapterWithDur: ChapterProps & { duration_seconds?: number } = {
  ...defaultChapter,
  duration_seconds: 6.0,
};

export const RemotionRoot: React.FC = () => {
  return (
    <>
      {/* TestCard — простая карточка для проверки, что рендер вообще работает */}
      <Composition
        id="TestCard"
        component={TestCard}
        durationInFrames={90}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        defaultProps={defaultTestCardWithDur}
        calculateMetadata={makeCalc(90)}
      />

      {/* NumberReveal — первый реальный оверлей, цифра вылетает и зумится */}
      <Composition
        id="NumberReveal"
        component={NumberReveal}
        durationInFrames={75}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        defaultProps={defaultNumberRevealWithDur}
        calculateMetadata={makeCalc(75)}
      />

      {/* NamedHighlight — подсвечивает имя или термин маркером снизу */}
      <Composition
        id="NamedHighlight"
        component={NamedHighlight}
        durationInFrames={75}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        defaultProps={defaultNamedHighlightWithDur}
        calculateMetadata={makeCalc(75)}
      />

      {/* LocationLabel — пин с названием места (Москва, Уолл-стрит...) */}
      <Composition
        id="LocationLabel"
        component={LocationLabel}
        durationInFrames={75}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        defaultProps={defaultLocationLabelWithDur}
        calculateMetadata={makeCalc(75)}
      />

      {/* SectionTitle — полноэкранная заставка смены темы с номером */}
      <Composition
        id="SectionTitle"
        component={SectionTitle}
        durationInFrames={75}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        defaultProps={defaultSectionTitleWithDur}
        calculateMetadata={makeCalc(75)}
      />

      {/* QuoteCard — карточка для цитаты с автором, центр экрана */}
      <Composition
        id="QuoteCard"
        component={QuoteCard}
        durationInFrames={120}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        defaultProps={defaultQuoteCardWithDur}
        calculateMetadata={makeCalc(120)}
      />

      {/* KeywordPop — короткий "выкрик" ключевого слова с bounce */}
      <Composition
        id="KeywordPop"
        component={KeywordPop}
        durationInFrames={45}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        defaultProps={defaultKeywordPopWithDur}
        calculateMetadata={makeCalc(45)}
      />

      {/* ProgressBar — горизонтальный бар процента/сравнения внизу экрана */}
      <Composition
        id="ProgressBar"
        component={ProgressBar}
        durationInFrames={105}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        defaultProps={defaultProgressBarWithDur}
        calculateMetadata={makeCalc(105)}
      />

      {/* Chapter — постоянная HUD-полоска с названием раздела */}
      <Composition
        id="Chapter"
        component={Chapter}
        durationInFrames={180}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        defaultProps={defaultChapterWithDur}
        calculateMetadata={makeCalc(180)}
      />
    </>
  );
};
