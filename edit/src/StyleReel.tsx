import React from "react";
import {
  AbsoluteFill,
  Audio,
  OffthreadVideo,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { loadFont as loadMontserrat } from "@remotion/google-fonts/Montserrat";
import { loadFont as loadInter } from "@remotion/google-fonts/Inter";
import { loadFont as loadPoppins } from "@remotion/google-fonts/Poppins";
import { loadFont as loadBebas } from "@remotion/google-fonts/BebasNeue";

const FONTS: Record<string, string> = {
  montserrat: loadMontserrat("normal", { weights: ["700", "800", "900"] }).fontFamily,
  inter: loadInter("normal", { weights: ["600", "800"] }).fontFamily,
  poppins: loadPoppins("normal", { weights: ["600", "800"] }).fontFamily,
  bebas: loadBebas().fontFamily,
};

/** One piece of your footage: a file in public/, trimmed from `in` to `out` seconds. */
export type Clip = { src: string; in: number; out: number; zoom?: boolean; label?: string };
/** Word timings on the FINAL timeline (seconds), e.g. from Whisper after trimming. */
export type Word = { start: number; end: number; word: string; emphasis?: boolean };
/** Mirrors the Style Card's captions / pacing / colour fields. */
export type Style = {
  captions?: {
    style?: "word_by_word" | "phrase" | "full_line" | "none";
    words_per_chunk?: number;
    position?: "top" | "middle" | "lower_third" | "bottom";
    font?: string; // montserrat | inter | poppins | bebas
    weight?: number;
    size_pct?: number; // of frame height
    case?: "upper" | "sentence";
    color?: string;
    highlight_color?: string;
    background?: "none" | "box";
    box_color?: string;
    stroke?: boolean;
    pop_in?: boolean;
  };
  pacing?: { zoom_on_cut?: boolean; punch_in_pct?: number; slow_push?: boolean };
  colour?: { brightness?: number; contrast?: number; saturation?: number; warmth?: number };
  hook_title?: { text: string; seconds?: number };
  music?: { src: string; volume?: number };
};
export type EditProps = { fps: number; clips: Clip[]; words: Word[]; style: Style };

export const totalFrames = (p: EditProps) =>
  Math.round(p.clips.reduce((s, c) => s + Math.max(c.out - c.in, 0), 0) * (p.fps || 30));

const POS: Record<string, React.CSSProperties> = {
  top: { top: "12%" },
  middle: { top: "46%" },
  lower_third: { top: "66%" },
  bottom: { bottom: "14%" },
};

const ClipView: React.FC<{ clip: Clip; index: number; style: Style; frames: number }> = ({ clip, index, style, frames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pace = style.pacing || {};
  const punch = (pace.punch_in_pct ?? 8) / 100;
  // Alternate a punch-in on every other cut, plus an optional slow push across the clip.
  const base = (clip.zoom ?? (pace.zoom_on_cut && index % 2 === 1)) ? 1 + punch : 1;
  const push = pace.slow_push ? interpolate(frame, [0, frames], [0, 0.04], { extrapolateRight: "clamp" }) : 0;
  return (
    <AbsoluteFill style={{ transform: `scale(${base + push})` }}>
      <OffthreadVideo
        src={clip.src.startsWith("http") ? clip.src : staticFile(clip.src)}
        startFrom={Math.round(clip.in * fps)}
        endAt={Math.round(clip.out * fps)}
        style={{ width: "100%", height: "100%", objectFit: "cover" }}
      />
    </AbsoluteFill>
  );
};

const Captions: React.FC<{ words: Word[]; style: Style }> = ({ words, style }) => {
  const frame = useCurrentFrame();
  const { fps, height } = useVideoConfig();
  const c = style.captions || {};
  if (c.style === "none" || !words.length) return null;
  const t = frame / fps;
  const per = c.style === "word_by_word" ? 1 : c.words_per_chunk || (c.style === "full_line" ? 7 : 3);

  // Group words into chunks; show the chunk containing the current time.
  const chunks: Word[][] = [];
  for (let i = 0; i < words.length; i += per) chunks.push(words.slice(i, i + per));
  const chunk = chunks.find((ch) => t >= ch[0].start - 0.05 && t <= ch[ch.length - 1].end + 0.15);
  if (!chunk) return null;
  const startFrame = Math.round(chunk[0].start * fps);
  const pop = c.pop_in === false ? 1 : spring({ frame: frame - startFrame, fps, config: { damping: 14, stiffness: 220 } });

  const size = ((c.size_pct ?? 6.5) / 100) * height;
  const font = FONTS[(c.font || "montserrat").toLowerCase()] || c.font || FONTS.montserrat;
  return (
    <AbsoluteFill style={{ alignItems: "center", pointerEvents: "none" }}>
      <div
        style={{
          position: "absolute",
          ...POS[c.position || "lower_third"],
          width: "86%",
          textAlign: "center",
          fontFamily: font,
          fontWeight: c.weight ?? 800,
          fontSize: size,
          lineHeight: 1.12,
          textTransform: c.case === "upper" ? "uppercase" : "none",
          color: c.color || "#ffffff",
          transform: `scale(${interpolate(pop, [0, 1], [0.82, 1])})`,
          textShadow: c.background === "box" ? "none" : "0 4px 18px rgba(0,0,0,.55)",
          WebkitTextStroke: c.stroke ? `${Math.max(size / 22, 2)}px #000` : undefined,
          paintOrder: "stroke fill",
        }}
      >
        <span
          style={
            c.background === "box"
              ? { background: c.box_color || "#000", padding: "0.08em 0.3em", borderRadius: 10, boxDecorationBreak: "clone", WebkitBoxDecorationBreak: "clone" }
              : undefined
          }
        >
          {chunk.map((w, i) => {
            const active = t >= w.start && t <= w.end + 0.05;
            const hi = w.emphasis || (per > 1 && active);
            return (
              <span key={i} style={{ color: hi ? c.highlight_color || "#FFD400" : undefined }}>
                {w.word}
                {i < chunk.length - 1 ? " " : ""}
              </span>
            );
          })}
        </span>
      </div>
    </AbsoluteFill>
  );
};

const HookTitle: React.FC<{ style: Style }> = ({ style }) => {
  const frame = useCurrentFrame();
  const { fps, height } = useVideoConfig();
  const h = style.hook_title;
  if (!h) return null;
  const end = (h.seconds ?? 2.5) * fps;
  if (frame > end) return null;
  const inS = spring({ frame, fps, config: { damping: 16 } });
  const out = interpolate(frame, [end - 6, end], [1, 0], { extrapolateLeft: "clamp" });
  const c = style.captions || {};
  return (
    <AbsoluteFill style={{ alignItems: "center" }}>
      <div
        style={{
          position: "absolute",
          top: "14%",
          width: "84%",
          textAlign: "center",
          fontFamily: FONTS[(c.font || "montserrat").toLowerCase()] || FONTS.montserrat,
          fontWeight: 900,
          fontSize: height * 0.05,
          color: "#fff",
          textTransform: "uppercase",
          background: c.highlight_color || "#FF5A36",
          padding: "0.25em 0.4em",
          borderRadius: 14,
          opacity: out,
          transform: `translateY(${interpolate(inS, [0, 1], [-40, 0])}px) scale(${interpolate(inS, [0, 1], [0.9, 1])})`,
        }}
      >
        {h.text}
      </div>
    </AbsoluteFill>
  );
};

export const StyleReel: React.FC<EditProps> = (props) => {
  const { fps } = useVideoConfig();
  const g = props.style.colour || {};
  const filter = [
    `brightness(${g.brightness ?? 1})`,
    `contrast(${g.contrast ?? 1})`,
    `saturate(${g.saturation ?? 1})`,
    g.warmth ? `sepia(${Math.max(g.warmth, 0)})` : "",
    g.warmth && g.warmth < 0 ? `hue-rotate(${g.warmth * 40}deg)` : "",
  ].join(" ");
  let at = 0;
  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      <AbsoluteFill style={{ filter }}>
        {props.clips.map((clip, i) => {
          const frames = Math.round((clip.out - clip.in) * fps);
          const from = at;
          at += frames;
          return (
            <Sequence key={i} from={from} durationInFrames={frames}>
              <ClipView clip={clip} index={i} style={props.style} frames={frames} />
            </Sequence>
          );
        })}
      </AbsoluteFill>
      <Captions words={props.words} style={props.style} />
      <HookTitle style={props.style} />
      {props.style.music ? <Audio src={staticFile(props.style.music.src)} volume={props.style.music.volume ?? 0.12} /> : null}
    </AbsoluteFill>
  );
};
