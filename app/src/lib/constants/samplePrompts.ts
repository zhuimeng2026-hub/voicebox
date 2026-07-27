// A ~20-second Chinese passage covering common initials, finals, and tones.
// Designed for voice cloning: balanced phoneme coverage, natural sentence flow.
export const CHINESE_SAMPLE_PROMPT = {
  text: `今天天气真好，阳光洒在窗台上，微风轻轻吹过树梢。我泡了一杯热茶，翻开那本买了很久却一直没看的书。书里说，人生就像一场旅行，不在乎目的地，而在乎沿途的风景和看风景的心情。`,
  language: "zh",
  estimatedDurationSeconds: 20,
};

// Fallback shorter version (~12s)
export const CHINESE_SAMPLE_PROMPT_SHORT = {
  text: `今天阳光很好，我坐在窗前喝茶看书。书里有一句话让我印象深刻：人生最重要的不是终点，而是沿途的风景。`,
  language: "zh",
  estimatedDurationSeconds: 12,
};

// Generic prompts for other languages (extensible later)
export const SAMPLE_PROMPTS: Record<string, typeof CHINESE_SAMPLE_PROMPT> = {
  zh: CHINESE_SAMPLE_PROMPT,
  // en, ja, ko, ... can be added here
};
