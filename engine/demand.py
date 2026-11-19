"""Audience demand: what people ask and complain about, compared with what reels already cover."""
from __future__ import annotations

import html
import json
import math
import re
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote_plus

import requests

from . import db
from .config import REELS, load_niche

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
SOURCE_WEIGHT = {"reddit": 2.0, "quora": 1.5, "hackernews": 1.5, "google": 1.0, "youtube": 1.0, "blog": 0.6, "news": 0.4}
TEXT_ANSWER_SOURCES = {"blog", "news", "quora", "hackernews"}
PREFIXES = ["how to {}", "why {}", "{} not working", "is {} worth it", "best {} for", "{} vs", "can {}"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS demand (
    niche TEXT NOT NULL, url TEXT NOT NULL, source TEXT NOT NULL, title TEXT NOT NULL, body TEXT,
    score INTEGER DEFAULT 0, comments INTEGER DEFAULT 0, community TEXT, posted_at TEXT, fetched_at TEXT,
    PRIMARY KEY (niche, url)
);
"""

PAIN_RULES = [
    ("Problem", re.compile(r"\b(struggl\w*|not working|doesn'?t work|stuck|frustrat\w*|hate|waste\w*|fail\w*|problem|issue|regret\w*|worse|dropped|decreased|burn\w*|scar\w* from|side effects?|came back|grow(s|ing)? back|scam|help)\b", re.I)),
    ("Fear", re.compile(r"\b(replace\w*|penali[sz]e\w*|safe|safety|risk\w*|danger\w*|punish\w*|ban\w*|harm\w*|hurt)\b", re.I)),
    ("Decision", re.compile(r"\b(worth it|vs\.?|versus|best|which|should i|alternative\w*|cost|price|cheap\w*|genuine|recommend\w*)\b", re.I)),
    ("How-to", re.compile(r"\b(how (to|do|can|should)|ways? to|guide|steps?)\b", re.I)),
]
PAIN_WEIGHT = {"Problem": 1.5, "Fear": 1.3, "Decision": 1.2, "How-to": 1.1, "Mention": 0.6}
PAIN_FORMAT = {"Problem": "Myth vs truth", "Fear": "Question", "Decision": "Ranked list", "How-to": "How-to", "Mention": "Statement"}
PAIN_ANGLE = {
    "Problem": "Name the frustration in their exact words, show why the usual fix fails, then give the one change that works.",
    "Fear": "Say the fear out loud, separate what's true from what's hype, and end with what to do this week.",
    "Decision": "Make the decision for them: compare the options on one screen and name your pick and why.",
    "How-to": "Show the result first, then the shortest path to it in three steps.",
    "Mention": "Lead with your strongest opinion on this and back it with one real example.",
}
STOP = set("""a an and are as at be but by can do does for from get got has have how i if in into is it its just like make more most my
not of on or our so than that the their them then there these they this to too up us use using vs want was we what when where which who
why will with would you your about after all also any been being could did every first good great here need new now only other out over
really should some still very way ways best top quora reddit""".split())


PROMO = re.compile(r"^\s*(show hn|launch hn)\b", re.I)
SPAMMY = re.compile(r"print(s|ing)? money|\$\d|\bhyderabad\b|\bbangalore\b|\bgurgaon\b|\bmumbai\b|\bchennai\b|\bpune\b", re.I)
QUESTION = re.compile(r"^\s*(how|why|what|which|is|are|can|does|do|will|should|ask hn)\b", re.I)


def _as_question(title: str) -> str:
    t = title.strip()
    t = t[0].upper() + t[1:]
    return t + "?" if QUESTION.match(t) and t[-1] not in "?.!" else t


def _ensure(con):
    con.executescript(SCHEMA)


def pain_type(text: str) -> str:
    for name, rx in PAIN_RULES:
        if rx.search(text):
            return name
    return "Mention"


def _clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _save(niche: str, rows: list[dict]) -> int:
    with db.connect() as con:
        _ensure(con)
        for r in rows:
            if not r.get("url") or not r.get("title"):
                continue
            con.execute(
                """INSERT INTO demand (niche,url,source,title,body,score,comments,community,posted_at,fetched_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(niche,url) DO UPDATE SET title=excluded.title, body=excluded.body, score=excluded.score,
                   comments=excluded.comments, fetched_at=excluded.fetched_at""",
                (niche, r["url"], r["source"], r["title"][:300], (r.get("body") or "")[:2000], int(r.get("score") or 0),
                 int(r.get("comments") or 0), r.get("community"), r.get("posted_at"), db.now()))
    return len(rows)


def _hn(q: str) -> list[dict]:
    hits = requests.get("https://hn.algolia.com/api/v1/search", params={"query": q, "tags": "story", "hitsPerPage": 30}, timeout=20).json()["hits"]
    return [{"source": "hackernews", "title": h.get("title"), "url": f"https://news.ycombinator.com/item?id={h['objectID']}",
             "score": h.get("points"), "comments": h.get("num_comments"), "posted_at": h.get("created_at"), "body": _clean(h.get("story_text"))} for h in hits]


def _suggest(seed: str, ds: str | None) -> list[dict]:
    out = []
    source = "youtube" if ds else "google"
    for p in PREFIXES:
        params = {"client": "firefox", "q": p.format(seed)}
        if ds:
            params["ds"] = ds
        for s in requests.get("https://suggestqueries.google.com/complete/search", params=params, headers=UA, timeout=15).json()[1]:
            base = "https://www.youtube.com/results?search_query=" if ds else "https://www.google.com/search?q="
            out.append({"source": source, "title": s, "url": base + quote_plus(s)})
        time.sleep(0.15)
    return out


def _rss(url: str, source: str) -> list[dict]:
    root = ET.fromstring(requests.get(url, headers=UA, timeout=20).content)
    out = []
    for it in root.iter():
        if it.tag.split("}")[-1] not in ("item", "entry"):
            continue
        f = {c.tag.split("}")[-1]: c for c in it}
        link = f.get("link")
        href = (link.text or link.get("href")) if link is not None else None
        title = _clean(f["title"].text) if "title" in f else ""
        if source == "news":
            title = title.rsplit(" - ", 1)[0]
        body = f.get("description") if "description" in f else f.get("summary")
        date = f.get("pubDate") if "pubDate" in f else f.get("published")
        out.append({"source": source, "title": title, "url": href, "body": _clean(body.text if body is not None else ""),
                    "posted_at": date.text if date is not None else None})
    return out


def collect(niche: str, log=print) -> dict:
    cfg = load_niche(niche).get("demand") or {}
    jobs = [(f"hackernews: {q}", lambda q=q: _hn(q)) for q in cfg.get("hn", [])]
    for seed in cfg.get("seeds", []):
        jobs += [(f"google: {seed}", lambda s=seed: _suggest(s, None)), (f"youtube: {seed}", lambda s=seed: _suggest(s, "yt"))]
    for q in cfg.get("news", []):
        u = f"https://news.google.com/rss/search?q={quote_plus(q)}&hl={cfg.get('hl', 'en-US')}&gl={cfg.get('gl', 'US')}&ceid={cfg.get('gl', 'US')}:en"
        jobs.append((f"news: {q}", lambda u=u: _rss(u, "news")))
    jobs += [(f"blog: {u}", lambda u=u: _rss(u, "blog")) for u in cfg.get("feeds", [])]
    counts, failed = Counter(), []
    for name, fn in jobs:
        try:
            rows = fn()
            _save(niche, rows)
            counts[name.split(":")[0]] += len(rows)
        except Exception as e:
            failed.append(f"{name} ({type(e).__name__})")
    log(dict(counts), "failed:", failed)
    return {"collected": dict(counts), "failed": failed}


def import_file(path: str, niche: str, source: str) -> int:
    """Load an Apify export (reddit or quora) or a plain list of {title, url}."""
    rows = []
    for it in json.loads(Path(path).read_text(encoding="utf-8")):
        if source == "reddit":
            if it.get("type") not in (None, "post"):
                continue
            url = it.get("url") if "reddit.com" in (it.get("url") or "") else "https://www.reddit.com" + (it.get("permalink") or "")
            rows.append({"source": "reddit", "title": it.get("title"), "body": it.get("selfText") or it.get("body"), "url": url,
                         "score": it.get("score"), "comments": it.get("numComments"), "community": it.get("subreddit"), "posted_at": it.get("createdAt")})
        else:
            q = it.get("question") or {}
            m = q.get("metrics") or it.get("metrics") or {}
            rows.append({"source": "quora", "title": q.get("title") or it.get("title"), "url": q.get("url") or it.get("url"),
                         "score": m.get("followers") or 0, "comments": m.get("answers") or 0, "posted_at": q.get("posted_at") or it.get("posted_at"),
                         "body": it.get("text")})
    return _save(niche, [r for r in rows if r.get("title") and r.get("url")])


def _rx(terms: list[str]):
    return re.compile(r"\b(" + "|".join(re.escape(t).replace(r"\ ", r"[\s-]+") for t in terms) + r")\w{0,3}\b", re.I)


def _reel_texts(niche: str, tracked: set[str]) -> list[dict]:
    with db.connect() as con:
        rows = [dict(r) for r in con.execute("SELECT shortcode, owner, caption, COALESCE(plays, views, 0) v FROM reels WHERE niche=?", (niche,))]
    out = []
    for r in rows:
        if tracked and r["owner"] not in tracked:
            continue
        text = r["caption"] or ""
        an = REELS / r["shortcode"] / "analysis.json"
        if an.exists():
            try:
                text += " " + (json.loads(an.read_text(encoding="utf-8"))["transcript"]["text"] or "")
            except (ValueError, KeyError):
                pass
        out.append({**r, "text": text})
    return out


def _discover(docs: list[dict], stop: set[str]) -> dict[str, list[str]]:
    """Find recurring two-word phrases in questions that no curated topic caught."""
    seen: dict[str, set] = defaultdict(set)
    for d in docs:
        if d["source"] in ("blog", "news"):
            continue
        w = [x for x in re.findall(r"[a-z][a-z'-]+", d["title"].lower())]
        for a, b in zip(w, w[1:]):
            if a not in STOP and b not in STOP and a not in stop and b not in stop:
                seen[f"{a} {b}"].add(d["source"])
    counts = Counter(p for d in docs if d["source"] not in ("blog", "news") for p in seen if p in d["title"].lower())
    picks = [p for p, n in counts.most_common(40) if n >= 4 and len(seen[p]) >= 2][:8]
    return {p.capitalize(): [p] for p in picks}


def analyze(niche: str) -> dict:
    recipe = load_niche(niche)
    cfg = recipe.get("demand") or {}
    with db.connect() as con:
        _ensure(con)
        docs = [dict(r) for r in con.execute("SELECT * FROM demand WHERE niche=?", (niche,))]
    anchors = _rx([str(a) for a in cfg["anchors"]]) if cfg.get("anchors") else None
    docs = [d for d in docs if not PROMO.match(d["title"]) and (not anchors or anchors.search(d["title"]))]
    tracked ={c.lower() for c in recipe.get("creators") or []}
    reels = _reel_texts(niche, tracked)
    medians: dict[str, list[int]] = defaultdict(list)
    for r in reels:
        if r["v"]:
            medians[r["owner"]].append(r["v"])
    med = {o: sorted(v)[len(v) // 2] for o, v in medians.items()}

    topics = {t["name"]: t["terms"] for t in cfg.get("topics", [])}
    compiled = {n: _rx(t) for n, t in topics.items()}
    matched, rest = defaultdict(list), []
    for d in docs:
        text = d["title"] if d["source"] in ("google", "youtube") else f"{d['title']} {d.get('body') or ''}"
        hits = [n for n, rx in compiled.items() if rx.search(d["title"])] or [n for n, rx in compiled.items() if rx.search(text) and d["source"] != "news"]
        for n in hits[:2]:
            matched[n].append(d)
        if not hits:
            rest.append(d)
    stop = {str(w).lower() for w in cfg.get("stop", [])}
    for name, terms in _discover(rest, stop).items():
        rx = _rx(terms)
        found = [d for d in rest if rx.search(d["title"])]
        if len(found) >= 4:
            compiled[name] = rx
            matched[name] = found

    out = []
    for name, items in matched.items():
        rx = compiled[name]
        weighted, pains, sources = [], Counter(), Counter()
        for d in items:
            p = pain_type(d["title"])
            eng = (d.get("score") or 0) + 2 * (d.get("comments") or 0)
            w = SOURCE_WEIGHT.get(d["source"], 1) * PAIN_WEIGHT[p] * (1 + math.log10(1 + eng))
            weighted.append((w, p, d))
            sources[d["source"]] += 1
            if d["source"] not in ("blog", "news") and p != "Mention":
                pains[p] += w
        asks = sum(n for s, n in sources.items() if s not in ("blog", "news"))
        if asks < 2:
            continue
        cover = [r for r in reels if rx.search(r["text"])]
        cover.sort(key=lambda r: r["v"] / med.get(r["owner"], 1) if med.get(r["owner"]) else 0, reverse=True)
        best = cover[0] if cover else None
        best_mult = round(best["v"] / med[best["owner"]], 1) if best and med.get(best["owner"]) else None
        pain = pains.most_common(1)[0][0] if pains else "Mention"
        weighted.sort(key=lambda x: x[0], reverse=True)
        questions = [x for x in weighted if x[2]["source"] not in ("blog", "news")]
        questions.sort(key=lambda x: (bool(rx.search(x[2]["title"])) and not SPAMMY.search(x[2]["title"]),
                                      bool(QUESTION.match(x[2]["title"])) and x[1] != "Mention", x[0]), reverse=True)
        answers = sum(n for s, n in sources.items() if s in ("blog", "quora", "hackernews"))
        demand = sum(w for w, _, d in weighted if d["source"] not in ("blog", "news")) * (1 + 0.2 * (len([s for s in sources if s not in ("blog", "news")]) - 1))
        status = "Untapped" if not cover else "Thin" if len(cover) <= 3 else "Crowded"
        out.append({
            "topic": name, "demand_raw": demand, "pain": pain, "status": status, "reels": len(cover), "reel_share": round(len(cover) / max(len(reels), 1), 3),
            "best_reel": {"shortcode": best["shortcode"], "owner": best["owner"], "views": best["v"], "outlier": best_mult} if best else None,
            "sources": dict(sources), "signals": len(items), "text_coverage": answers, "answered_elsewhere": sources.get("blog", 0) + sources.get("news", 0) > 0 or sources.get("quora", 0) > 0,
            "hook": _as_question(questions[0][2]["title"]) if questions else name, "format": PAIN_FORMAT[pain], "angle": PAIN_ANGLE[pain],
            "evidence": [{"title": d["title"], "url": d["url"], "source": d["source"], "score": d.get("score") or 0, "comments": d.get("comments") or 0,
                          "community": d.get("community"), "pain": p} for _, p, d in questions[:5]],
            "reading": [{"title": d["title"], "url": d["url"], "source": d["source"]} for _, _, d in weighted if d["source"] in ("blog", "news")][:3],
        })
    top = max((t["demand_raw"] for t in out), default=1)
    for t in out:
        t["demand"] = round(t["demand_raw"] / top * 100)
        t["gap"] = round(t["demand"] / (1 + t["reels"] / 3))
        del t["demand_raw"]
    out.sort(key=lambda t: t["gap"], reverse=True)
    with db.connect() as con:
        last = con.execute("SELECT MAX(fetched_at) FROM demand WHERE niche=?", (niche,)).fetchone()[0]
    return {"topics": out, "signals": len(docs), "sources": dict(Counter(d["source"] for d in docs)), "reels_checked": len(reels),
            "untapped": sum(t["status"] == "Untapped" for t in out), "updated": last}
