# Reel Engine

A free, local content engine for short-form creators: research a niche on Instagram, decode why reels work and
how they are edited, write scripts in the user's voice, and edit their footage in a chosen style.

## Run things with `.\engine.cmd`

Always call `.\engine.cmd <command>` from this folder (it uses the project's own Python environment).

| Command | What it does |
| --- | --- |
| `.\engine.cmd scrape <niche>` | Scan the niche's hashtags and creators for new reels (needs `.\engine.cmd login` once) |
| `.\engine.cmd discover <niche>` | Add creators found in the hashtag feeds to the recipe |
| `.\engine.cmd top <niche> --window 7 --sort outlier` | Leaderboard (window 1/7/30/0; sort outlier/views/likes/comments/engagement/velocity/recent) |
| `.\engine.cmd analyze <niche> --top 10` / `--reel <sc>` | Download + transcript + cuts + frames + colours + vision → `data/reels/<sc>/analysis.json` |
| `.\engine.cmd add-url <link>` / `add-file <path>` | Save any reel as a reference and decode it |
| `.\engine.cmd edit <name> --clips ... --card <sc>` | First cut of raw footage in a Style Card → `edit/props/<name>.json` |
| `.\engine.cmd render <name>` | Render with Remotion → `data/edits/<name>.mp4` |
| `.\engine.cmd serve` | Dashboard at http://localhost:8765 |
| `.\engine.cmd export <niche>` | Swipe file CSV |

## Skills

- `style-card`: analysis.json → stylecard.json + breakdown.md (and house styles in `data/cards/`)
- `script-studio`: scripts in the user's voice → `data/scripts/`
- `style-edit`: raw clips + Style Card → rendered reel
- `weekly-report`: niche + own-performance report → `data/reports/`

## Ground rules

- Scraping uses a **spare** Instagram account only, slowly. Never ask for or type the user's passwords; the user runs
  `.\engine.cmd login <spare>` themselves.
- Copy structure and style from references, never their words or footage.
- Every correction the user gives becomes a line in `data/rules.md` (or `data/voice.md`) so it sticks.
- Niche recipes live in `niches/*.yaml`; data (db, videos, cards, scripts, edits) lives in `data/`.
