Design a web app called "Reel Engine": a research and editing studio for Instagram Reels creators. The first niche is real estate in India. It helps a creator see which reels are blowing up in their niche, understand why (hook, transcript, editing style), save them as references, turn them into scripts in their own voice, and edit their own footage in the same style.

LOOK AND FEEL
- Dark, video-first, premium "editing room" feel, like a mix of Linear, Frame.io and the Instagram Explore grid. Not a spreadsheet.
- Background near-black #0F1012, panels #17181B, borders #2A2C31, text #ECEDEF, secondary text #9A9EA8.
- One accent colour: hot coral #FF5A36, used only for "outlier" scores, rising items and primary buttons. Success green #3ECF8E.
- Font: Inter (or Geist). Big bold numbers, small grey labels. Rounded corners 12px. No gradients, subtle hover lift.
- Reels always shown as 9:16 vertical cards that autoplay muted on hover.
- Desktop first (1440px) but must work on a phone (2-column grid, bottom tab bar).

TOP BAR (all screens)
Logo dot + "Reel Engine", a niche switcher dropdown ("Real estate India"), tabs: Radar, Library, Style Cards, Scripts, Edit Room, My Reels. On the right: small status text "1,240 reels · 86 creators · 212 decoded · scanned 2h ago".

SCREEN 1: RADAR (home)
- Filter row: segmented control "24 h / 7 days / 30 days / All", a Sort dropdown (Outlier score, Views, Likes, Comments, Engagement %, Velocity, Newest), and a wide search box "Search captions, transcripts, breakdowns…".
- Right side rail: "Rising this week": rising audio tracks, rising hashtags (#punerealestate +38%), rising hook types ("Price reveal", "Rent vs EMI").
- Main grid of 9:16 reel cards. Each card: thumbnail, coral pill badge top-left with outlier score ("12.4x"), small green "Style Card" tag top-right if decoded, then @creator · 2d ago, three stats in a row (views, likes, comments) with big numbers, 2-line caption.

SCREEN 2: REEL DETAIL (opens as a large right-side drawer over the Radar)
- Left column: 9:16 video player, "Save to Library" coral button, "Open on Instagram", inputs for Board and Tags, small line chart "Views over time".
- Right column: 4 KPI tiles (Outlier 12.4x vs creator median 18K, Views 223K, Engagement 6.2%, Velocity 1.9K views/hour).
- "Hook (first 3 seconds)" box with the hook line in bold.
- Transcript with clickable words; words in the first 3 seconds highlighted coral.
- "Cuts" timeline bar: alternating grey blocks for each shot, hook zone shaded coral; label "14 shots · 4.2 cuts per 10s · avg 2.3s".
- "Colour" palette strip of 6 swatches with the grade label "warm, bright, punchy".
- Key frames: row of small 9:16 frames with timestamps and shot type ("b-roll · drone").
- Style Card panel (see screen 3) and a "Why it worked" breakdown.

SCREEN 3: STYLE CARDS
Gallery of cards, each a decoded editing style: name ("Price-reveal walkthrough"), one-line summary, a live caption sample on a dark tile (bold uppercase white text with one yellow #FFD400 highlighted word), rows for Hook, Captions, Pacing (a small meter bar for cuts per 10s), Colour (swatches), Audio, CTA. Buttons: "Write scripts in this style", "Edit my footage in this style". A "House styles" section on top for merged personal styles.

SCREEN 4: SCRIPTS
List on the left (title, reference reel, date), script on the right: Hook (spoken, on screen, visual), timestamped lines with B-roll notes, Shot list as checkboxes, Fact check list with ✅ / ⚠️ icons, Caption + hashtags. Buttons: "Approve", "Give a note".

SCREEN 5: EDIT ROOM
Upload area for raw clips, Style Card picker, a 9:16 preview of the first cut, a horizontal timeline of clips with removed takes struck through, a notes box, and a coral "Render" button with progress.

SCREEN 6: MY REELS (performance)
The creator's own reels as cards, each next to the reference reel it was based on, with "vs your median" scores; a weekly report card with "What worked", "What didn't", "Make next week" (5 ideas).

EMPTY STATE
Friendly empty state for Radar with three numbered setup steps shown as code chips.

Use realistic Indian real-estate sample data: made-up creator handles like @demo.realty and @sample.homes, captions like "Stop paying rent in Pune: 2 BHK in Hinjewadi for less than your rent", prices in ₹ lakh and crore.
