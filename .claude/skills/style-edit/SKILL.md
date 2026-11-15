---
name: style-edit
description: Edit the user's raw footage into a 9:16 reel that follows a decoded Style Card (captions, cut rhythm, punch-ins, colour, hook title), rendered locally with Remotion. Use when the user gives raw clips and asks to edit, cut, caption or "make it look like" a reference reel or their house style.
---

# Style Edit

## Steps

1. **Pick the style.** A reel shortcode with `data/reels/<sc>/stylecard.json`, or a house style in `data/cards/`.
   Ask only if the user gave neither and there are several good candidates; otherwise use the most recent house style.
2. **First cut.** Put the raw clips in shooting order and run:
   `engine.cmd edit <project-name> --clips "<clip1>" "<clip2>" ... --card <shortcode-or-house-style>`
   This copies clips to `edit/public/<project>/`, transcribes them, cuts pauses longer than 0.4 s, and writes
   `edit/props/<project>.json` plus `edit/props/<project>.takes.json` (full transcript per clip).
3. **Review the draft like an editor** (this is the important part):
   - Read `<project>.takes.json`. Find flubs, false starts, "cut", "one more time", and repeated takes of the same
     line. Keep only the best take of each line (usually the last complete one).
   - Edit `edit/props/<project>.json`: delete those pieces from `clips`, then **rebuild `words`** so their times match
     the new timeline (each piece contributes `out - in` seconds; shift following words accordingly). Mark 1–2 key
     words per sentence with `"emphasis": true` (numbers, prices, the payoff word).
   - Match the Style Card's pacing: if `cuts_per_10s` is high and a piece runs longer than ~2× `avg_shot_seconds`,
     split it in two (same src, adjacent in/out) so the punch-in alternates.
   - Set `style.hook_title.text` from the script's on-screen hook if there is one.
   - Read `data/rules.md` (## Edits) and apply it.
4. **Render:** `engine.cmd render <project-name>` → `data/edits/<project>.mp4`.
5. **Check it.** Grab 3 frames (`ffmpeg -ss <t> -i data/edits/<project>.mp4 -frames:v 1 check.jpg`) at the hook,
   middle and CTA and look at them: captions readable and inside the frame, no black frames, punch-ins not cropping
   faces. Fix and re-render if needed. Then tell the user where the file is.

## Notes

- The template is `edit/src/StyleReel.tsx`. Fonts available: montserrat, inter, poppins, bebas.
- For heavier work (relighting, eye-line, cloned voice, advanced motion graphics), the user's `aiiy-ad-editor`
  skill has a fuller Remotion pipeline; this skill is the fast, style-matched first cut.
- Music: put an mp3 in `edit/public/<project>/` and set `style.music = {"src": "<project>/song.mp3", "volume": 0.1}`.

## Learning from corrections

When the user gives a note on a cut ("captions too big", "cut faster in the middle"), fix it and add the general
lesson to `data/rules.md` under `## Edits`.
