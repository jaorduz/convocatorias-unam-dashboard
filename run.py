from __future__ import annotations

import hashlib

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional, Dict, Any, List
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
import yaml
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
import feedparser


import smtplib
import argparse
import os
from email.mime.text import MIMEText



@dataclass
class Item:
    source: str
    title: str
    url: str
    snippet: str
    detected_deadline: Optional[str]  # ISO date string or None
    detected_language: str            # "es" | "en" | "mixed" | "unknown"
    fetched_at: str                   # ISO datetime


def load_yaml(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def guess_lang(text: str) -> str:
    t = (text or "").lower()
    es_hits = sum(w in t for w in ["convocatoria", "beca", "financiamiento", "apoyo", "proyecto", "cierre", "fecha límite"])
    en_hits = sum(w in t for w in ["call for proposals", "grant", "funding", "deadline", "solicitation", "fellowship"])
    if es_hits and en_hits:
        return "mixed"
    if es_hits:
        return "es"
    if en_hits:
        return "en"
    return "unknown"


def stable_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


DEADLINE_PATTERNS = [
    # ES examples: "cierre: 15 de marzo de 2026", "fecha límite 2026-03-15"
    r"(fecha\s*l[ií]mite|cierre|hasta)\s*[:\-]?\s*(.+)",
    # EN examples: "deadline: March 15, 2026", "due date 2026-03-15"
    r"(deadline|due\s*date)\s*[:\-]?\s*(.+)",
]


def extract_deadline(text: str) -> Optional[str]:
    """
    Best-effort deadline extraction from free text.
    Returns ISO date (YYYY-MM-DD) if found.
    """
    t = norm_space(text)
    tl = t.lower()

    # quick scan for date-like substrings
    candidate_chunks: List[str] = []
    for pat in DEADLINE_PATTERNS:
        m = re.search(pat, tl, flags=re.IGNORECASE)
        if m:
            candidate_chunks.append(m.group(2))

    # also consider raw dates anywhere
    candidate_chunks.append(t)

    for chunk in candidate_chunks:
        chunk = chunk[:2000]
        # Look for explicit YYYY-MM-DD
        m = re.search(r"\b(20\d{2})[-/](0?\d|1[0-2])[-/](0?\d|[12]\d|3[01])\b", chunk)
        if m:
            yyyy, mm, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return f"{yyyy:04d}-{mm:02d}-{dd:02d}"

        # Try dateutil parse with fuzzy
        try:
            dt = dateparser.parse(chunk, fuzzy=True, dayfirst=True)
            if dt:
                # guardrail: only accept plausible modern deadlines
                if 2000 <= dt.year <= 2100:
                    return dt.date().isoformat()
        except Exception:
            pass
    return None


# 👇 ADD IT RIGHT HERE # JO
def fetch_deadline_from_page(url, user_agent, timeout_seconds):
    try:
        html = fetch_html(url, user_agent, timeout_seconds)
        text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
        return extract_deadline(text)
    except Exception:
        return None

def allow_link(url: str, include_if_url_contains: Optional[List[str]]) -> bool:
    if not url:
        return False
    if include_if_url_contains:
        u = url.lower()
        return any(tok.lower() in u for tok in include_if_url_contains)
    return True


def is_same_domain(base: str, target: str) -> bool:
    try:
        return urlparse(base).netloc == urlparse(target).netloc
    except Exception:
        return False


def fetch_html(url: str, user_agent: str, timeout_seconds: int) -> str:
    r = requests.get(
        url,
        headers={"User-Agent": user_agent},
        timeout=min(timeout_seconds, 20)
    )
    r.raise_for_status()
    return r.text


def parse_html_source(
    source_name: str,
    base_url: str,
    html: str,
    include_if_url_contains: Optional[List[str]],
    keywords_es: List[str],
    keywords_en: List[str],
    max_items: int,
    user_agent, timeout_seconds #JO
) -> List[Item]:
    soup = BeautifulSoup(html, "html.parser")
    anchors = soup.find_all("a", href=True)

    items: List[Item] = []
    seen_urls = set()

    # keywords for filtering by anchor text + nearby context
    kws = [k.lower() for k in (keywords_es + keywords_en)]
    now_iso = datetime.now(timezone.utc).isoformat()

    for a in anchors:
        href = a.get("href")
        text = norm_space(a.get_text(" ", strip=True))
        if not href:
            continue

        abs_url = urljoin(base_url, href)
        if abs_url in seen_urls:
            continue
        seen_urls.add(abs_url)

        # keep mainly same domain (safe + relevant), but allow if explicitly includes patterns
        if not is_same_domain(base_url, abs_url) and not allow_link(abs_url, include_if_url_contains):
            continue

        if not allow_link(abs_url, include_if_url_contains):
            continue

        context = text
        # include a small context window around the anchor (parent text)
        parent = a.parent.get_text(" ", strip=True) if a.parent else ""
        context = norm_space(f"{text} {parent}")[:800]

        cl = context.lower()
        if not any(k in cl for k in kws):
            continue

        snippet = context[:240]
        detected_deadline = extract_deadline(context)

        detected_language = guess_lang(context)

        title = text if text else abs_url
        items.append(
            Item(
                source=source_name,
                title=title[:160],
                url=abs_url,
                snippet=snippet,
                detected_deadline=detected_deadline,
                detected_language=detected_language,
                fetched_at=now_iso,
            )
        )
        if len(items) >= max_items:
            break

    return items


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS calls (
            id TEXT PRIMARY KEY,
            source TEXT,
            title TEXT,
            url TEXT,
            snippet TEXT,
            detected_deadline TEXT,
            detected_language TEXT,
            fetched_at TEXT,
            first_seen_at TEXT
        )
        """
    )
    conn.commit()


def upsert_items(conn: sqlite3.Connection, items: Iterable[Item]) -> int:
    inserted = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    for it in items:
        _id = stable_id(it.url)
        cur = conn.execute("SELECT id FROM calls WHERE id = ?", (_id,))
        exists = cur.fetchone() is not None
        if exists:
            # update basic fields (title/snippet might change)
            conn.execute(
                """
                UPDATE calls SET
                  source = ?,
                  title = ?,
                  url = ?,
                  snippet = ?,
                  detected_deadline = ?,
                  detected_language = ?,
                  fetched_at = ?
                WHERE id = ?
                """,
                (it.source, it.title, it.url, it.snippet, it.detected_deadline, it.detected_language, it.fetched_at, _id),
            )
        else:
            conn.execute(
                """
                INSERT INTO calls (id, source, title, url, snippet, detected_deadline, detected_language, fetched_at, first_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (_id, it.source, it.title, it.url, it.snippet, it.detected_deadline, it.detected_language, it.fetched_at, now_iso),
            )
            inserted += 1
    conn.commit()
    return inserted


def cleanup_old(conn: sqlite3.Connection, keep_days: int) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
    conn.execute("DELETE FROM calls WHERE first_seen_at < ?", (cutoff.isoformat(),))
    conn.commit()


def export_csv(conn: sqlite3.Connection, path: str) -> pd.DataFrame:
    df = pd.read_sql_query(
        """
        SELECT
          source,
          title,
          url,
          snippet,
          detected_deadline,
          detected_language,
          first_seen_at
        FROM calls
        ORDER BY COALESCE(detected_deadline, '9999-12-31') ASC, first_seen_at DESC
        """,
        conn,
    )
    df.to_csv(path, index=False, encoding="utf-8")
    return df


def write_digest(df: pd.DataFrame, path: str) -> None:
    # pick "soonest deadlines" first, then recent
    lines = []
    lines.append(f"# Calls Digest (auto)\n")
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}\n")

    if df.empty:
        lines.append("No items collected yet.\n")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return

    # top by deadline
    soon = df.dropna(subset=["detected_deadline"]).head(15)
    if not soon.empty:
        lines.append("## Upcoming deadlines\n")
        for _, r in soon.iterrows():
            dl = r["detected_deadline"]
            lines.append(f"- **{dl}** — {r['title']}  \n  Source: {r['source']}  \n  Link: {r['url']}\n")

    # most recent additions
    recent = df.sort_values("first_seen_at", ascending=False).head(20)
    lines.append("\n## Recently found\n")
    for _, r in recent.iterrows():
        dl = r["detected_deadline"] if pd.notna(r["detected_deadline"]) else "—"
        lines.append(f"- **Deadline:** {dl} — {r['title']}  \n  Source: {r['source']}  \n  Link: {r['url']}\n")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    cfg = load_yaml("config.yaml")
    srcs = load_yaml("sources.yaml")

    keywords_es = cfg["keywords"]["es"]
    keywords_en = cfg["keywords"]["en"]
    s = cfg["settings"]

    sqlite_path = s["sqlite_path"]
    out_csv = s["output_csv"]
    out_md = s["output_md"]

    conn = sqlite3.connect(sqlite_path)
    init_db(conn)

    all_items: List[Item] = []

    for src in srcs["sources"]:
        name = src["name"]
        typ = src["type"]
        url = src["url"]
        include_if = src.get("include_if_url_contains")

        try:
            if typ == "html":
                html = fetch_html(url, s["user_agent"], s["timeout_seconds"])
                items = parse_html_source(
                    source_name=name,
                    base_url=url,
                    html=html,
                    include_if_url_contains=include_if,
                    keywords_es=keywords_es,
                    keywords_en=keywords_en,
                    max_items=s["max_items_per_source"],
                    user_agent=s["user_agent"],
                    timeout_seconds=s["timeout_seconds"],
                )

            elif typ == "rss":
                items = parse_rss_source(
                    source_name=name,
                    url=url,
                    keywords_es=keywords_es,
                    keywords_en=keywords_en,
                    max_items=s["max_items_per_source"],
                )

            else:
                print(f"Unknown source type: {typ}")
                continue

            all_items.extend(items)
            print(f"[OK] {name}: {len(items)} items")

        except Exception as e:
            print(f"[WARN] {name}: {e}")

    inserted = upsert_items(conn, all_items)
    cleanup_old(conn, s["only_keep_days"])
    df = export_csv(conn, out_csv)
    write_digest(df, out_md)
    conn.close()

    print(f"\nDone. Inserted new: {inserted}")
    print(f"CSV: {out_csv}")
    print(f"Digest: {out_md}")





def parse_rss_source(source_name, url, keywords_es, keywords_en, max_items):
    feed = feedparser.parse(url)
    items = []
    now_iso = datetime.now(timezone.utc).isoformat()

    kws = [k.lower() for k in (keywords_es + keywords_en)]

    for entry in feed.entries[:max_items]:
        title = entry.get("title", "")
        link = entry.get("link", "")
        summary = entry.get("summary", "")

        content = f"{title} {summary}".lower()

        if not any(k in content for k in kws):
            continue

        detected_deadline = extract_deadline(summary or title)

        detected_language = guess_lang(content)

        items.append(
            Item(
                source=source_name,
                title=title[:160],
                url=link,
                snippet=summary[:240],
                detected_deadline=detected_deadline,
                detected_language=detected_language,
                fetched_at=now_iso,
            )
        )

    return items


# simple email sending with SMTP; can be enhanced with templates, HTML formatting, etc.
def send_email_digest(filepath, recipients):

    sender = os.getenv("EMAIL_USER")
    password = os.getenv("EMAIL_PASS")

    if not sender or not password:
        raise ValueError("EMAIL_USER or EMAIL_PASS not set in environment")

    with open(filepath, "r", encoding="utf-8") as f:
        body = f.read()

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = "Resumen semanal de convocatorias"
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, recipients, msg.as_string())

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--send-email", action="store_true", help="Send digest email")
    args = parser.parse_args()

    main()

    if args.send_email:
        recipients = [os.getenv("EMAIL_USER")]
        send_email_digest("data/digest.md", recipients)