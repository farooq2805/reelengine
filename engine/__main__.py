"""Command line: `engine <command>` (via engine.cmd) or `python -m engine <command>`."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from .config import DATA, ROOT, list_niches, save_settings, settings


def fmt(n) -> str:
    if n is None:
        return "-"
    n = float(n)
    for unit, div in (("M", 1e6), ("K", 1e3)):
        if n >= div:
            return f"{n / div:.1f}{unit}"
    return f"{n:.0f}"


def cmd_top(a):
    from .score import leaderboard

    rows = leaderboard(a.niche, window_days=a.window, sort=a.sort, limit=a.limit)
    if not rows:
        print("No reels yet. Run: engine scrape", a.niche)
        return
    print(f"{'#':>2}  {'outlier':>7}  {'views':>7}  {'likes':>6}  {'comm':>5}  {'eng%':>5}  {'owner':<22} link")
    for i, r in enumerate(rows, 1):
        out = f"{r['outlier']}x" if r["outlier"] else "-"
        link = f"instagram.com/reel/{r['shortcode']}" if r["source"] not in ("file", "url") else r["shortcode"]
        print(f"{i:>2}  {out:>7}  {fmt(r['views_best']):>7}  {fmt(r['likes']):>6}  {fmt(r['comments']):>5}  "
              f"{(r['engagement'] or 0):>5}  {('@' + (r['owner'] or ''))[:22]:<22} {link}")


def cmd_scrape(a):
    from .scrape import scrape

    only = [u.strip().lower() for u in a.only.split(",")] if a.only else None
    s = scrape(a.niche, hashtags=not a.no_hashtags, creators=not a.no_creators, only=only)
    print(f"\n{s['new']} new reels, {s['updated']} updated.")
    for e in s["errors"]:
        print("  !", e)


def cmd_discover(a):
    from .scrape import discover

    added = discover(a.niche, max_new=a.max)
    print(f"Added {len(added)} creators: " + ", ".join("@" + u for u in added) if added else "No new creators found.")


def cmd_analyze(a):
    from .analyze import analyze, queue

    codes = a.reel or queue(a.niche, window_days=a.window, top=a.top, min_outlier=a.min_outlier)
    if not codes:
        print("Nothing to analyse (all top reels already done).")
        return
    for i, sc in enumerate(codes, 1):
        print(f"[{i}/{len(codes)}] {sc}")
        try:
            analyze(sc, use_vision=not a.no_vision, max_frames=a.frames)
        except Exception as e:
            print(f"  failed: {e}")


def cmd_daily(a):
    """What the scheduler runs: scrape, grow the creator list, analyse new outliers."""
    a.no_hashtags = a.no_creators = False
    a.only = None
    cmd_scrape(a)
    cmd_discover(argparse.Namespace(niche=a.niche, max=10))
    cmd_analyze(argparse.Namespace(niche=a.niche, reel=None, window=7, top=a.top, min_outlier=None,
                                   no_vision=False, frames=10))


def cmd_add_url(a):
    from .media import add_url

    sc = add_url(a.url, a.niche, a.cookies)
    print("Saved as", sc)
    if not a.skip_analysis:
        from .analyze import analyze

        analyze(sc)


def cmd_add_file(a):
    from .media import add_file

    sc = add_file(a.path, a.niche, a.name)
    print("Saved as", sc)
    if not a.skip_analysis:
        from .analyze import analyze

        analyze(sc, use_vision=not a.no_vision)


def cmd_export(a):
    from .score import leaderboard

    rows = leaderboard(a.niche, window_days=a.window, sort="outlier", limit=10_000)
    out = Path(a.out or DATA / f"{a.niche}-swipe-file.csv")
    cols = ["shortcode", "owner", "posted_at", "views_best", "likes", "comments", "outlier", "engagement",
            "velocity", "board", "tags", "caption"]
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(cols + ["link", "hook", "cuts_per_10s"])
        for r in rows:
            an = ROOT / "data" / "reels" / r["shortcode"] / "analysis.json"
            m = json.loads(an.read_text(encoding="utf-8"))["metrics"] if an.exists() else {}
            w.writerow([r.get(c) for c in cols] + [f"https://www.instagram.com/reel/{r['shortcode']}/",
                                                   m.get("hook_text", ""), m.get("cuts_per_10s", "")])
    print("Wrote", out)


def cmd_settings(a):
    s = save_settings(whisper_model=a.whisper, vision_model=a.vision, ollama_url=a.ollama)
    print(json.dumps(s, indent=2))


def cmd_schedule(a):
    """Print the Windows Task Scheduler command for a daily run (you run it yourself)."""
    cmdfile = ROOT / "engine.cmd"
    print("Run this once in your own terminal to scan every morning:\n")
    print(f'schtasks /Create /SC DAILY /ST {a.time} /TN "ReelEngine {a.niche}" '
          f'/TR "\\"{cmdfile}\\" daily {a.niche}" /F')


def _cmd_agents(a):
    from .agents import get_agent_status, run_agent, scheduler_status, start_scheduler
    if a.action == "status":
        ss = scheduler_status()
        print(f"Scheduler: {'RUNNING' if ss['running'] else 'STOPPED'}")
        for ag in get_agent_status():
            lr = ag["last_run"]
            last = f"last: {lr['finished_at'] or lr['started_at']} — {lr['summary']}" if lr else "never run"
            print(f"  {ag['name']:10s} | runs: {ag['total_runs']:3d} | items: {ag['total_items']:4d} | {last}")
    elif a.action == "run":
        agent = a.agent
        if not agent:
            print("Specify --agent: scout | analyst | decoder | reporter")
            return
        niche = a.niche
        print(f"Running {agent} for {niche}...")
        result = run_agent(agent, niche)
        print(f"  → {result['summary']}")
    else:
        print("Starting agent scheduler (press Ctrl+C to stop)...")
        start_scheduler()
        try:
            while True:
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            from .agents import stop_scheduler
            stop_scheduler()
            print("\nStopped.")


def cmd_serve(a):
    import uvicorn

    print(f"Dashboard: http://localhost:{a.port}")
    uvicorn.run("engine.server:app", host="127.0.0.1", port=a.port, log_level="warning")


def main(argv=None):
    p = argparse.ArgumentParser(prog="engine", description="Niche content engine: research, decode, script, edit.")
    sub = p.add_subparsers(dest="cmd", required=True)
    default_niche = (list_niches() or ["real-estate-india"])[0]

    def niche_arg(sp):
        sp.add_argument("niche", nargs="?", default=default_niche)

    sp = sub.add_parser("login", help="log in a SPARE Instagram account (you type the password)")
    sp.add_argument("username")
    sp.set_defaults(fn=lambda a: __import__("engine.scrape", fromlist=["x"]).login(a.username))

    sp = sub.add_parser("login-firefox", help="import the spare account's session from Firefox instead")
    sp.add_argument("username", nargs="?", default="")
    sp.set_defaults(fn=lambda a: __import__("engine.scrape", fromlist=["x"]).import_firefox_session(a.username))

    sp = sub.add_parser("login-chrome", help="import the spare account's session from Chrome cookies")
    sp.set_defaults(fn=lambda a: __import__("engine.scrape", fromlist=["x"]).import_chrome_session())

    sp = sub.add_parser("login-cookie", help="paste a sessionid cookie value to log in")
    sp.add_argument("sessionid", help="the sessionid cookie value from Instagram")
    sp.set_defaults(fn=lambda a: __import__("engine.scrape", fromlist=["x"]).import_sessionid(a.sessionid))

    sp = sub.add_parser("niches", help="list niche recipes")
    sp.set_defaults(fn=lambda a: print("\n".join(list_niches())))

    sp = sub.add_parser("scrape", help="scan hashtags and creators for new reels")
    niche_arg(sp)
    sp.add_argument("--no-hashtags", action="store_true")
    sp.add_argument("--no-creators", action="store_true")
    sp.add_argument("--only", help="comma-separated creator usernames")
    sp.set_defaults(fn=cmd_scrape)

    sp = sub.add_parser("discover", help="add creators found in the hashtag feeds")
    niche_arg(sp)
    sp.add_argument("--max", type=int, default=25)
    sp.set_defaults(fn=cmd_discover)

    sp = sub.add_parser("import-apify", help="import reels from an Apify Instagram scraper dataset")
    sp.add_argument("dataset_id")
    sp.add_argument("--niche", default=default_niche)
    sp.add_argument("--source", default="apify")
    sp.add_argument("--token", help="Apify API token, only if the dataset is private")
    sp.set_defaults(fn=lambda a: print(__import__("engine.apify_import", fromlist=["x"]).import_dataset(
        a.dataset_id, a.niche, a.source, a.token)))

    sp = sub.add_parser("import-file", help="import reels from a local JSON file exported from Apify console")
    sp.add_argument("file", help="path to the exported JSON file")
    sp.add_argument("--niche", default=default_niche)
    sp.add_argument("--source", default="apify")
    sp.set_defaults(fn=lambda a: print(__import__("engine.apify_import", fromlist=["x"]).import_file(
        a.file, a.niche, a.source)))

    sp = sub.add_parser("demand", help="collect audience questions and pain points for a niche")
    niche_arg(sp)
    sp.set_defaults(fn=lambda a: print(__import__("engine.demand", fromlist=["x"]).collect(a.niche)))

    sp = sub.add_parser("demand-import", help="import a Reddit or Quora export into a niche's audience research")
    sp.add_argument("file")
    sp.add_argument("--niche", default=default_niche)
    sp.add_argument("--source", choices=["reddit", "quora"], required=True)
    sp.set_defaults(fn=lambda a: print(__import__("engine.demand", fromlist=["x"]).import_file(a.file, a.niche, a.source), "items imported"))

    sp = sub.add_parser("harvest", help="fill in details for collected reel links (no login)")
    sp.add_argument("file", help="lines of '<hashtag> <shortcode> ...' or one link per line")
    sp.add_argument("--niche", default=default_niche)
    sp.set_defaults(fn=lambda a: print(__import__("engine.harvest", fromlist=["x"]).harvest(a.file, a.niche)))

    sp = sub.add_parser("top", help="print the leaderboard")
    niche_arg(sp)
    sp.add_argument("--window", type=int, default=7, help="days: 1, 7, 30, or 0 for all")
    sp.add_argument("--sort", default="outlier", help="outlier | views | likes | comments | engagement | velocity | recent")
    sp.add_argument("--limit", type=int, default=20)
    sp.set_defaults(fn=cmd_top)

    sp = sub.add_parser("analyze", help="transcript, cuts, frames, colours, vision for top reels")
    niche_arg(sp)
    sp.add_argument("--reel", nargs="*", help="specific shortcodes")
    sp.add_argument("--top", type=int, default=10)
    sp.add_argument("--window", type=int, default=7)
    sp.add_argument("--min-outlier", type=float)
    sp.add_argument("--frames", type=int, default=10)
    sp.add_argument("--no-vision", action="store_true")
    sp.set_defaults(fn=cmd_analyze)

    sp = sub.add_parser("daily", help="scrape + discover + analyse (for the scheduler)")
    niche_arg(sp)
    sp.add_argument("--top", type=int, default=10)
    sp.set_defaults(fn=cmd_daily)

    sp = sub.add_parser("add-url", help="save any reel/short by link as a reference")
    sp.add_argument("url")
    sp.add_argument("--niche", default=default_niche)
    sp.add_argument("--cookies", help="browser with the spare account logged in: firefox | chrome | edge")
    sp.add_argument("--skip-analysis", action="store_true")
    sp.set_defaults(fn=cmd_add_url)

    sp = sub.add_parser("add-file", help="use a video file on your laptop as a reference")
    sp.add_argument("path")
    sp.add_argument("--niche", default=default_niche)
    sp.add_argument("--name")
    sp.add_argument("--skip-analysis", action="store_true")
    sp.add_argument("--no-vision", action="store_true")
    sp.set_defaults(fn=cmd_add_file)

    sp = sub.add_parser("export", help="swipe file as CSV (opens in Excel / Google Sheets)")
    niche_arg(sp)
    sp.add_argument("--window", type=int, default=30)
    sp.add_argument("--out")
    sp.set_defaults(fn=cmd_export)

    sp = sub.add_parser("settings", help="show or change settings")
    sp.add_argument("--whisper", help="tiny | base | small | medium | large-v3")
    sp.add_argument("--vision", help="Ollama model, e.g. qwen3-vl:4b or qwen3-vl:2b")
    sp.add_argument("--ollama", help="Ollama URL")
    sp.set_defaults(fn=cmd_settings)

    sp = sub.add_parser("schedule", help="print the command that runs `daily` every morning")
    niche_arg(sp)
    sp.add_argument("--time", default="06:30")
    sp.set_defaults(fn=cmd_schedule)

    sp = sub.add_parser("edit", help="first cut of your raw clips in a Style Card")
    sp.add_argument("name", help="project name, e.g. home-loan-myths")
    sp.add_argument("--clips", nargs="+", required=True, help="raw clip files in order")
    sp.add_argument("--card", help="reel shortcode with a Style Card, or a house style in data/cards")
    sp.add_argument("--keep-pauses", action="store_true")
    sp.set_defaults(fn=lambda a: __import__("engine.edit", fromlist=["x"]).prepare(a.name, a.clips, a.card, a.keep_pauses))

    sp = sub.add_parser("render", help="render an edit project to MP4 with Remotion")
    sp.add_argument("name")
    sp.set_defaults(fn=lambda a: __import__("engine.edit", fromlist=["x"]).render(a.name))

    sp = sub.add_parser("autopilot", help="full pipeline: scout → analyst → decoder → reporter")
    niche_arg(sp)
    sp.add_argument("--top", type=int, default=10)
    sp.add_argument("--window", type=int, default=7)
    sp.add_argument("--harvest", help="harvest file with shortcodes")
    sp.set_defaults(fn=lambda a: __import__("engine.autopilot", fromlist=["x"]).autopilot(
        a.niche, top=a.top, window=a.window, harvest_file=a.harvest))

    sp = sub.add_parser("agents", help="run the autonomous agent scheduler")
    sp.add_argument("action", choices=["start", "status", "run"], default="start", nargs="?")
    sp.add_argument("--agent", help="run a specific agent: scout | analyst | decoder | reporter")
    niche_arg(sp)
    sp.set_defaults(fn=lambda a: _cmd_agents(a))

    sp = sub.add_parser("serve", help="open the dashboard")
    sp.add_argument("--port", type=int, default=8765)
    sp.set_defaults(fn=cmd_serve)

    a = p.parse_args(argv)
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    a.fn(a)


if __name__ == "__main__":
    main()
