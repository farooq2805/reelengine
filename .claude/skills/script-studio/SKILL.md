---
name: script-studio
description: Write reel scripts in the user's own voice using a proven structure from the niche repository, with a fact check and a shot list. Use when the user asks for scripts, hooks, ideas, a content batch, "what should I post", or to remake a reference reel's format on their own topic.
---

# Script Studio

Scripts go to `data/scripts/YYYY-MM-DD-<topic-slug>.md`; the dashboard's Scripts tab shows them.

## Before writing

1. Read `data/voice.md` (the user's voice profile) and `data/rules.md` (lessons from past corrections).
   If `data/voice.md` does not exist, build it first: transcripts of the user's own reels
   (`engine.cmd top --window 0 --limit 200` then the rows marked as theirs, i.e. owner = `self_username` in the niche
   recipe, and their `analysis.json` transcripts). Capture: language mix (Hindi / English / Hinglish), sentence
   length, favourite phrases, how they open and close, energy, words they never use. If they have no decoded reels,
   ask them 5 quick questions instead and save the answers.
2. Pick the references. If the user named a reel or Style Card, use it. Otherwise take the top 5 by outlier score in
   the last 7 days (`engine.cmd top <niche> --window 7`) that have a `stylecard.json`, and say which you used.
3. Read each reference's `stylecard.json` (hook type, structure timings, pacing) and `breakdown.md`.

## Writing

For each script (default 3 per request, each on a different reference structure):

```markdown
# <Working title>

**Reference:** <shortcode> · <style card name> · <outlier score>x
**Length:** ~<seconds>s · **Hook type:** <type>

## Hook (0–3 s)
Spoken: "<line>"
On screen: "<title overlay text>"
Visual: <what we see>

## Script
[0:03] <line>  — B-roll: <shot>
[0:08] <line>  — On screen: <text>
...
[0:25] CTA: <line>

## Shot list
- [ ] A-roll: <setup, framing, location>
- [ ] B-roll: <specific shots to grab>

## Fact check
- <claim> — ✅ source / ⚠️ needs checking: <why>

## Caption + hashtags
<caption> #tag #tag
```

Rules:
- Same structure and pacing as the reference; **never** reuse its words or footage.
- In the user's voice (voice.md), at the reference's words-per-minute.
- Real estate in India: every price, rate, RERA rule, stamp duty, tax or loan figure must appear in Fact check.
  Mark anything you cannot verify with a source as ⚠️ and suggest the user confirms it. Don't invent numbers.
- Keep the hook under 3 seconds of speech.

## Learning from corrections

When the user corrects a script, fix it, then add the general lesson to `data/rules.md` under `## Scripts`
(or to `data/voice.md` if it is about how they talk). Every correction must change future scripts, not just this one.
