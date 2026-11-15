---
name: style-card
description: Decode a reference reel into a Style Card (stylecard.json) and a hook-and-structure breakdown (breakdown.md). Use when the user asks to "make a style card", "break down", "decode" or "analyse the editing style" of a reel, gives a reel shortcode or Instagram link, or asks why a reel worked. Also merges several cards into a house style.
---

# Style Card

Turns one decoded reel into two files in `data/reels/<shortcode>/`:

- `stylecard.json`: machine-readable editing style the Edit Engine follows.
- `breakdown.md`: a short human breakdown of why it worked.

## Steps

1. **Make sure the reel is decoded.** If `data/reels/<shortcode>/analysis.json` is missing, run
   `engine.cmd analyze --reel <shortcode>` (for a link: `engine.cmd add-url <url>`; it prints the shortcode).
2. **Read the evidence**, all of it, before writing:
   - `analysis.json`: `metrics` (cuts per 10 s, avg shot, words per minute, hook text), `transcript` (words with times),
     `shots`, `colour` (palette, brightness, saturation, warmth, grade), `audio` (loudness curve, silence ratio),
     and `frames[].vision` (shot type, on-screen text, caption style read by the local vision model).
   - **Look at the key frames yourself** (`data/reels/<shortcode>/frames/*.jpg`, especially `00.jpg` = hook frame).
     Your own reading of caption font, position, colours and graphics beats the small local model; correct it where it is wrong.
   - The reel's stats: `engine.cmd top --window 0 --limit 200` or the row in `data/engine.db` (outlier score, views, engagement).
3. **Write `stylecard.json`** with exactly this shape (omit nothing; use null when unknown):

```json
{
  "name": "Short memorable name, e.g. 'Price-reveal walkthrough'",
  "source": "<shortcode>",
  "summary": "One sentence: what this style is and when to use it.",
  "why_it_worked": ["2-4 concrete reasons tied to the numbers"],
  "hook": {
    "type": "question | shock_number | contrarian | pov | before_after | price_reveal | story | list | other",
    "text": "exact spoken or on-screen hook",
    "seconds": 2.4,
    "visual": "what the viewer sees in the first frame",
    "title_overlay": "short on-screen hook text to reuse, or null"
  },
  "structure": [
    {"part": "hook", "start": 0, "end": 2.4, "what": "..."},
    {"part": "setup", "start": 2.4, "end": 9, "what": "..."},
    {"part": "payoff", "start": 9, "end": 24, "what": "..."},
    {"part": "cta", "start": 24, "end": 28, "what": "..."}
  ],
  "pacing": {"cuts_per_10s": 4.2, "avg_shot_seconds": 2.3, "zoom_on_cut": true, "punch_in_pct": 8, "slow_push": false},
  "captions": {
    "style": "word_by_word | phrase | full_line | none",
    "words_per_chunk": 3,
    "position": "top | middle | lower_third | bottom",
    "font": "montserrat | inter | poppins | bebas",
    "weight": 800,
    "size_pct": 6.5,
    "case": "upper | sentence",
    "color": "#FFFFFF",
    "highlight_color": "#FFD400",
    "background": "none | box",
    "box_color": "#000000",
    "stroke": true,
    "pop_in": true,
    "sample": "a 5-7 word line in this style"
  },
  "colour": {"grade": "warm, bright, punchy", "palette": ["#hex", "#hex", "#hex"]},
  "colour_edit": {"brightness": 1.05, "contrast": 1.08, "saturation": 1.15, "warmth": 0.08},
  "shots": {"mix": {"talking_head": 0.6, "b_roll": 0.4}, "b_roll_ideas": ["..."]},
  "audio": {"music": "genre / mood", "energy": "how energy moves", "sfx": ["whoosh on cuts", "..."]},
  "graphics": ["price tag sticker", "arrow", "..."],
  "cta": "what they ask the viewer to do",
  "do": ["specific, copyable moves"],
  "dont": ["things to avoid when copying this style"]
}
```

   `captions` font must be one of montserrat, inter, poppins, bebas (closest match), because those are loaded in the
   Remotion template. `colour_edit` values are CSS-filter multipliers near 1.0 (warmth 0 to 0.2) chosen so the user's
   footage moves toward this reel's grade.

4. **Write `breakdown.md`**: under 250 words. Sections: Hook (with the exact words), Structure (timestamps),
   Why it worked (tied to outlier score, retention cues, the niche), How to remake it in your voice (3 bullets).
   Never copy the creator's script; describe the structure.
5. Tell the user the card is on the dashboard (Style Cards tab) and offer: script in this style, or edit footage in it.

## House style (merging cards)

When asked to merge cards ("make my house style from these"), read each `stylecard.json`, keep what they share,
pick one value where they differ (say which and why), and write `data/cards/<name>.json` in the same shape with
`"source": ["sc1", "sc2", ...]`.

## Learning from corrections

If the user corrects a card ("captions are actually yellow", "that's not the hook"), fix the file AND append the
general lesson to `data/rules.md` under `## Style Cards` (create the file if missing), e.g.
"- Treat on-screen text in the first frame as part of the hook." Read `data/rules.md` before every new card.
