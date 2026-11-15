---
name: weekly-report
description: Weekly niche and performance report - what blew up in the niche this week, how the user's own reels did against their references, and what to make next week. Use when the user asks for the weekly report, "what's working", "what should I make next", or a niche summary.
---

# Weekly Report

1. Refresh data if the last scan is older than a day: `engine.cmd daily <niche> --top 10` (slow; tell the user).
2. Gather:
   - Niche: `engine.cmd top <niche> --window 7 --limit 25` and `--sort velocity --limit 10` (still rising).
   - Hook types and structures: the `stylecard.json` of this week's top reels (decode the top 5 first with the
     style-card skill if they have none).
   - The user's reels (owner = `self_username` in `niches/<niche>.yaml`): views, engagement and their outlier score
     against their own median; which Style Card / script each was based on (scripts in `data/scripts/` name their reference).
3. Write `data/reports/YYYY-MM-DD-<niche>.md`, under 400 words:
   - **This week in the niche**: top 5 reels (link, outlier score, one line on why), plus rising hashtags and hook types.
   - **Your reels**: table of reel · views · vs your median · reference used · verdict.
   - **What worked for you / what didn't**, tied to numbers.
   - **Next week**: 5 reel ideas, each with a reference shortcode and hook type. Flag 1–2 of the user's best reels
     worth rerunning as Trial Reels (Instagram's non-follower test).
4. Add lasting lessons (e.g. "price-reveal hooks beat question hooks for this account") to `data/rules.md` under
   `## Strategy`, so the Script Studio uses them.
