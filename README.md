# Reel Engine

Free, local content engine for Instagram creators: find what's blowing up in your niche, decode why
(hook, transcript, cuts, captions, colour), save references, write scripts in your voice, and edit your
footage in the same style. Everything runs on your laptop; the only "brain" you pay for is the Claude plan you already have.

## First run (once)

Everything is already installed on this laptop (Python packages, FFmpeg, Ollama + `qwen3-vl:2b-instruct`, Remotion).
On a new laptop, run `setup.cmd` and `cd edit && npm install`.

1. **Log in a spare Instagram account** (not your main one). In a terminal in this folder:
   ```
   .\engine.cmd login your_spare_account
   ```
   You type the password yourself; only the session is saved (in `data/`).
   Prefer not to type it? Log into the spare account in Firefox, then run `.\engine.cmd login-firefox`.
2. **Scan the niche** (takes 20–40 minutes; it pauses between requests on purpose):
   ```
   .\engine.cmd scrape real-estate-india
   .\engine.cmd discover real-estate-india
   ```
3. **Decode the top reels** (about 2 minutes each):
   ```
   .\engine.cmd analyze real-estate-india --top 10
   ```
4. **Open the dashboard:** `.\engine.cmd serve` and go to http://localhost:8765
5. **In Claude Code** (open this folder), ask for things in plain words:
   - "make a style card for <shortcode>"
   - "write 3 scripts on home-loan mistakes in the style of <shortcode>"
   - "edit my clips D:\shoot\a.mp4 D:\shoot\b.mp4 in the style of <shortcode>"
   - "give me the weekly report"

## Every day, automatically

`.\engine.cmd schedule real-estate-india --time 06:30` prints a Windows Task Scheduler command.
Run it once and the engine scans and decodes new outliers every morning.

## Commands

| Command | What it does |
| --- | --- |
| `scrape <niche>` | Scan hashtags + creators (last 30 days) |
| `discover <niche>` | Add creators found in hashtag feeds |
| `top <niche> --window 7 --sort outlier` | Leaderboard: window 1/7/30/0, sort outlier/views/likes/comments/engagement/velocity/recent |
| `analyze <niche> --top 10` / `--reel <sc>` | Transcript, cuts, frames, colours, vision |
| `add-url <link>` | Save any reel / Short / TikTok by link and decode it |
| `add-file <video>` | Use a video on your laptop as a reference |
| `edit <name> --clips ... --card <sc>` | First cut of your footage in a Style Card |
| `render <name>` | Render to `data/edits/<name>.mp4` |
| `export <niche>` | Swipe file CSV for Excel / Google Sheets |
| `settings --whisper medium` | Better transcripts (slower) |
| `serve` | Dashboard |

## How the scores work

- **Outlier score** = this reel's views ÷ the creator's median views (needs 3+ reels from that creator).
  10x from a small account is a stronger idea signal than a big account's average reel.
- **Velocity** = views gained per hour between the last two scans (or since posting, on the first scan).
- **Engagement** = (likes + comments + shares) ÷ views. Shares come only from Apify imports; Instagram hides them
  from the free route, and saves are never public.

## Adding another niche

Copy `niches/real-estate-india.yaml` to `niches/<new-slug>.yaml`, change the name and hashtags,
then `.\engine.cmd scrape <new-slug>`.

## Folder map

- `engine/`: Python engine (scraper, scoring, analysis, edit prep, dashboard API)
- `dashboard/`: the web dashboard (plain HTML/JS)
- `edit/`: Remotion template that renders Style Cards (`src/StyleReel.tsx`)
- `.claude/skills/`: style-card, script-studio, style-edit, weekly-report
- `niches/`: niche recipes
- `data/`: database, reels, Style Cards, scripts, edits, `rules.md` (lessons from your corrections)
