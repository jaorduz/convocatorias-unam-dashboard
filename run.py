from __future__ import annotations

import argparse
import hashlib
import os
import re
import sqlite3
import smtplib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urljoin, urlparse

import feedparser
import pandas as pd
import requests
import yaml
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Item:
    source: str
    title: str
    url: str
    snippet: str
    detected_deadline: Optional[str]  # ISO date string or None
    detected_language: str            # "es" | "en" | "mixed" | "unknown"
    detected_status: str              # "open" | "closed" | "unknown"
    fetched_at: str                   # ISO datetime


def load_yaml(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def guess_lang(text: str) -> str:
    t = (text or "").lower()
    es_hits = sum(
        w in t for w in ["convocatoria", "beca", "financiamiento", "apoyo", "proyecto", "cierre", "fecha límite"]
    )
    en_hits = sum(
        w in t for w in ["call for proposals", "grant", "funding", "deadline", "solicitation", "fellowship"]
    )
    if es_hits and en_hits:
        return "mixed"
    if es_hits:
        return "es"
    if en_hits:
        return "en"
    return "unknown"


def detect_status(text: str) -> str:
    t = (text or "").lower()
    if any(k in t for k in ["abierta", "abierto", "open", "vigente", "en curso"]):
        return "open"
    if any(k in t for k in ["cerrada", "cerrado", "closed", "concluida", "concluida", "finalizada", "terminada"]):
        return "closed"
    return "unknown"


def stable_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


DEADLINE_PATTERNS = [
    r"(fecha\s*l[ií]mite|cierre|hasta)\s*[:\-]?\s*(.+)",  # ES
    r"(deadline|due\s*date)\s*[:\-]?\s*(.+)",            # EN
]


def extract_deadline(text: str) -> Optional[str]:
    """
    Best-effort deadline extraction from free text.
    Returns ISO date (YYYY-MM-DD) if found.
    Only accepts dates in current year or future.
    """
    t = norm_space(text)
    tl = t.lower()

    candidate_chunks: List[str] = []
    for pat in DEADLINE_PATTERNS:
        m = re.search(pat, tl, flags=re.IGNORECASE)
        if m:
            candidate_chunks.append(m.group(2))

    candidate_chunks.append(t)

    current_year = datetime.now().year

    for chunk in candidate_chunks:
        chunk = chunk[:2000]

        m = re.search(r"\b(20\d{2})[-/](0?\d|1[0-2])[-/](0?\d|[12]\d|3[01])\b", chunk)
        if m:
            yyyy, mm, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if yyyy >= current_year:
                return f"{yyyy:04d}-{mm:02d}-{dd:02d}"
            continue

        try:
            dt = dateparser.parse(chunk, fuzzy=True, dayfirst=True)
            if dt and 2000 <= dt.year <= 2100 and dt.year >= current_year:
                return dt.date().isoformat()
        except Exception:
            pass

    return None


def is_same_domain(base: str, target: str) -> bool:
    try:
        return urlparse(base).netloc == urlparse(target).netloc
    except Exception:
        return False


def allow_link(url: str, include_if_url_contains: Optional[List[str]]) -> bool:
    if not url:
        return False
    if include_if_url_contains:
        u = url.lower()
        return any(tok.lower() in u for tok in include_if_url_contains)
    return True


def fetch_html(url: str, user_agent: str, timeout_seconds: int) -> str:
    r = requests.get(
        url,
        headers={"User-Agent": user_agent},
        timeout=min(timeout_seconds, 20),
    )
    r.raise_for_status()
    return r.text


def fetch_deadline_from_page(url: str, user_agent: str, timeout_seconds: int) -> Optional[str]:
    try:
        html = fetch_html(url, user_agent, timeout_seconds)
        text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
        return extract_deadline(text)
    except Exception:
        return None


def parse_html_source(
    source_name: str,
    base_url: str,
    html: str,
    include_if_url_contains: Optional[List[str]],
    keywords_es: List[str],
    keywords_en: List[str],
    max_items: int,
    user_agent: str,
    timeout_seconds: int,
) -> List[Item]:
    soup = BeautifulSoup(html, "html.parser")
    anchors = soup.find_all("a", href=True)

    items: List[Item] = []
    seen_urls = set()

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

        if not is_same_domain(base_url, abs_url) and not allow_link(abs_url, include_if_url_contains):
            continue

        if not allow_link(abs_url, include_if_url_contains):
            continue

        container = a.find_parent(["article", "div", "li"])
        context = container.get_text(" ", strip=True) if container else a.get_text(" ", strip=True)
        context = norm_space(context)[:1200]

        if len(text) < 10:
            continue

        cl = context.lower()
        if kws and not any(k in cl for k in kws):
            continue

        # Fallback: try to fetch destination page for better deadline/status extraction
        full_text = context
        try:
            full_html = fetch_html(abs_url, user_agent, timeout_seconds)
            full_text = BeautifulSoup(full_html, "html.parser").get_text(" ", strip=True)
        except Exception:
            pass

        detected_deadline = extract_deadline(full_text) or fetch_deadline_from_page(abs_url, user_agent, timeout_seconds)
        detected_language = guess_lang(full_text)
        detected_status = detect_status(full_text)
        snippet = norm_space(full_text)[:240]

        title = text if text else abs_url
        items.append(
            Item(
                source=source_name,
                title=title[:160],
                url=abs_url,
                snippet=snippet,
                detected_deadline=detected_deadline,
                detected_language=detected_language,
                detected_status=detected_status,
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
            detected_status TEXT,
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
            conn.execute(
                """
                UPDATE calls SET
                  source = ?,
                  title = ?,
                  url = ?,
                  snippet = ?,
                  detected_deadline = ?,
                  detected_language = ?,
                  detected_status = ?,
                  fetched_at = ?
                WHERE id = ?
                """,
                (
                    it.source,
                    it.title,
                    it.url,
                    it.snippet,
                    it.detected_deadline,
                    it.detected_language,
                    it.detected_status,
                    it.fetched_at,
                    _id,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO calls (
                    id, source, title, url, snippet,
                    detected_deadline, detected_language, detected_status,
                    fetched_at, first_seen_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _id,
                    it.source,
                    it.title,
                    it.url,
                    it.snippet,
                    it.detected_deadline,
                    it.detected_language,
                    it.detected_status,
                    it.fetched_at,
                    now_iso,
                ),
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
          detected_status,
          first_seen_at
        FROM calls
        ORDER BY COALESCE(detected_deadline, '9999-12-31') ASC, first_seen_at DESC
        """,
        conn,
    )
    df.to_csv(path, index=False, encoding="utf-8")
    return df


def write_digest(df: pd.DataFrame, path: str) -> None:
    lines = []
    lines.append("# Calls Digest (auto)\n")
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}\n")

    if df.empty:
        lines.append("No items collected yet.\n")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return

    soon = df.dropna(subset=["detected_deadline"]).head(15)
    if not soon.empty:
        lines.append("## Upcoming deadlines\n")
        for _, r in soon.iterrows():
            dl = r["detected_deadline"]
            status = r.get("detected_status", "unknown")
            lines.append(
                f"- **{dl}** ({status}) — {r['title']}  \n  Source: {r['source']}  \n  Link: {r['url']}\n"
            )

    recent = df.sort_values("first_seen_at", ascending=False).head(20)
    lines.append("\n## Recently found\n")
    for _, r in recent.iterrows():
        dl = r["detected_deadline"] if pd.notna(r["detected_deadline"]) else "—"
        status = r.get("detected_status", "unknown")
        lines.append(
            f"- **Deadline:** {dl} ({status}) — {r['title']}  \n  Source: {r['source']}  \n  Link: {r['url']}\n"
        )

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def parse_rss_source(source_name: str, url: str, keywords_es: List[str], keywords_en: List[str], max_items: int) -> List[Item]:
    feed = feedparser.parse(url)
    items: List[Item] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    kws = [k.lower() for k in (keywords_es + keywords_en)]

    for entry in feed.entries[:max_items]:
        title = entry.get("title", "")
        link = entry.get("link", "")
        summary = entry.get("summary", "")

        content = f"{title} {summary}".lower()
        if kws and not any(k in content for k in kws):
            continue

        detected_deadline = extract_deadline(summary or title)
        detected_language = guess_lang(content)
        detected_status = detect_status(content)

        items.append(
            Item(
                source=source_name,
                title=title[:160],
                url=link,
                snippet=summary[:240],
                detected_deadline=detected_deadline,
                detected_language=detected_language,
                detected_status=detected_status,
                fetched_at=now_iso,
            )
        )

    return items


def send_email_digest(filepath: str, recipients: List[str]) -> None:
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
    today = datetime.now(timezone.utc)

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

            # Filter by future deadlines when available; keep if no deadline but open/unknown
            filtered_items: List[Item] = []
            for it in items:
                if it.detected_deadline:
                    try:
                        d = datetime.fromisoformat(it.detected_deadline).replace(tzinfo=timezone.utc)
                        if d >= today:
                            filtered_items.append(it)
                    except Exception:
                        # keep if parsing fails
                        filtered_items.append(it)
                else:
                    filtered_items.append(it)

            all_items.extend(filtered_items)
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--send-email", action="store_true", help="Send digest email")
    args = parser.parse_args()

    main()

    if args.send_email:
        recipients_env = os.getenv("EMAIL_RECIPIENTS")
        if recipients_env and recipients_env.strip():
            recipients = [e.strip() for e in recipients_env.split(",") if e.strip()]
        else:
            recipients = [os.getenv("EMAIL_USER")]

        send_email_digest("data/digest.md", recipients)