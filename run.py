from __future__ import annotations

import argparse
import hashlib
import os
import re
import sqlite3
import smtplib
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from tempfile import template
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urljoin, urlparse, quote

import feedparser
import pandas as pd
import requests
import yaml
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from dotenv import load_dotenv
load_dotenv(override=True)

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


EXCLUDED_TERMS = [
    "maestría",
    "maestrias",
    "master",
    "masters",
    "posgrado",
    "posgrados",
    "licenciatura",
    "licenciaturas",
    "doctorado",
    "doctorados",
    "estudiar en francia",
    "programas de posgrado",
    "admisión",
    "admisiones",
    "inscripción",
    "inscripciones",
    "estudiante internacional",
    "campus france",
    "carta compromiso",
    "ejemplo - carta compromiso",
    "carta solicitud",
    "carta exposición",
    "definiciones y lineamientos",
    "lineamientos generales",
    "registro de bienes muebles",
    "sicop",
    "registro universitario de la propiedad intelectual",
    "acuerdo por el que se constituye",
    "acuerdo por el que se establecen",
    "procedimiento de validación, registro y depósito",
    "instrumentos consensuales",
    "convenios, contratos",
    "convenios y contratos",
    "convenio, contrato",
    "dgpu/06/2016",
    "propiedad intelectual",
    "normatividad",
    "política institucional",
    "política de propiedad",
    "registro universitario",
    "formato a",
    "formato b",
    "manual para el registro",
    "manual para el registro de participantes",
    "comité evaluador",
    "cierre del sistema",
    "circulares-unam",
    "programa anual de adquisiciones",
    "documento de apoyo",
]

FUNDING_TERMS = [
    "convocatoria",
    "call for proposals",
    "funding opportunity",
    "funding opportunities",
    "research award",
    "research awards",
    "research grant",
    "research grants",
    "grant",
    "grant program",
    "fellowship",
    "fellowships",
    "apoyo a la investigación",
    "financiamiento",
    "fondo para investigación",
    "propuesta de investigación",
    "proyecto de investigación",
]

def is_excluded_content(text: str) -> bool:
    t = (text or "").lower()
    return any(term in t for term in EXCLUDED_TERMS)


def has_funding_signal(text: str) -> bool:
    t = (text or "").lower()
    return any(term in t for term in FUNDING_TERMS)


def is_publishable_link(url: str) -> bool:
    path = urlparse(url).path.lower()
    return not path.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"))

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


def request_url(url: str, user_agent: str, timeout_seconds: int) -> Optional[requests.Response]:
    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
    }
    for attempt in range(3):
        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=min(timeout_seconds, 20),
                allow_redirects=True,
            )
            if response.status_code < 500 or attempt == 2:
                return response
        except requests.RequestException:
            if attempt == 2:
                return None
        time.sleep(0.5 * (attempt + 1))
    return None


def validate_url(url: str, user_agent: str, timeout_seconds: int) -> tuple[bool, Optional[int], str]:
    response = request_url(url, user_agent, timeout_seconds)
    if response is None:
        return False, None, "request failed"
    return response.status_code < 400, response.status_code, response.url


def load_valid_editorial_cards(path: str, user_agent: str, timeout_seconds: int) -> List[Dict[str, str]]:
    try:
        raw_cards = load_yaml(path).get("cards", [])
    except FileNotFoundError:
        return []

    valid_cards: List[Dict[str, str]] = []
    for card in raw_cards:
        link = str(card.get("link", "")).strip()
        if not link:
            continue
        available, status_code, final_url = validate_url(link, user_agent, timeout_seconds)
        if not available:
            print(f"[SKIP CARD] {card.get('title', 'Untitled')}: HTTP {status_code or final_url} -> {link}")
            continue
        card = dict(card)
        card["link"] = final_url
        valid_cards.append(card)
        print(f"[CARD] {card.get('title', 'Untitled')}: HTTP {status_code} -> {final_url}")
    return valid_cards


def source_is_available(url: str, user_agent: str, timeout_seconds: int) -> bool:
    available, _, _ = validate_url(url, user_agent, timeout_seconds)
    return available


def link_is_available(url: str, user_agent: str, timeout_seconds: int) -> bool:
    return source_is_available(url, user_agent, timeout_seconds)


def fetch_html(url: str, user_agent: str, timeout_seconds: int) -> str:
    r = request_url(url, user_agent, timeout_seconds)
    if r is None:
        raise requests.RequestException(f"Request failed: {url}")
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

    # =====================================================
    # 1) PRIMERO: intentar registrar la página fuente misma
    # =====================================================
    page_title = norm_space(soup.title.get_text(" ", strip=True)) if soup.title else source_name
    page_text = norm_space(soup.get_text(" ", strip=True))[:5000]
    page_text_lower = page_text.lower()

    # Registrar también la página fuente misma si corresponde a una convocatoria
    if (
        not is_excluded_content(page_text)
        and has_funding_signal(f"{page_title} {page_text}")
    ):
        items.append(
            Item(
                source=source_name,
                title=page_title[:160],
                url=base_url,
                snippet=page_text[:240],
                detected_deadline=extract_deadline(page_text),
                detected_language=guess_lang(page_text),
                detected_status=detect_status(page_text),
                fetched_at=now_iso,
            )
        )

    seen_urls.add(base_url)

    # =====================================================
    # 2) DESPUÉS: procesar links internos como antes
    # =====================================================
    for a in anchors:
        href = a.get("href")
        text = norm_space(a.get_text(" ", strip=True))
        if not href:
            continue

        abs_url = urljoin(base_url, href)

        if not is_publishable_link(abs_url):
            continue

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
        if is_excluded_content(cl):
            continue

        full_text = context
        try:
            full_html = fetch_html(abs_url, user_agent, timeout_seconds)
            full_text = BeautifulSoup(full_html, "html.parser").get_text(" ", strip=True)
        except Exception:
            continue

        if not link_is_available(abs_url, user_agent, timeout_seconds):
            continue

        if is_excluded_content(full_text):
            continue   
        if not has_funding_signal(f"{text} {context} {full_text}"):
            continue
        
        detected_deadline = extract_deadline(full_text) or fetch_deadline_from_page(
            abs_url, user_agent, timeout_seconds
        )
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


def remove_unvalidated_rows(conn: sqlite3.Connection, run_started_at: str) -> None:
    conn.execute("DELETE FROM calls WHERE fetched_at < ?", (run_started_at,))
    conn.commit()


def purge_non_funding_rows(conn: sqlite3.Connection) -> None:
    bad_tokens = [
        "carta compromiso",
        "carta solicitud",
        "carta exposición",
        "lineamientos generales",
        "registro universitario de la propiedad intelectual",
        "acuerdo por el que se constituye",
        "acuerdo por el que se establecen",
        "procedimiento de validación",
        "instrumentos consensuales",
        "formato a",
        "formato b",
        "manual para el registro",
        "comité evaluador",
        "cierre del sistema",
        "programa anual de adquisiciones",
        "circulares-unam",
        "normatividad",
        "sicop",
    ]
    for token in bad_tokens:
        conn.execute(
            "DELETE FROM calls WHERE lower(title) LIKE ? OR lower(url) LIKE ?",
            (f"%{token}%", f"%{token}%"),
        )
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


def write_digest(
    df: pd.DataFrame,
    path: str,
    source_sections: Optional[Dict[str, str]] = None,
    editorial_cards: Optional[List[Dict[str, str]]] = None,
) -> None:
    lines = []
    lines.append("# Calls Digest (auto)\n")
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}\n")
    editorial_cards = editorial_cards or []

    def append_editorial_cards() -> None:
        if not editorial_cards:
            return
        lines.append("## Avisos\n")
        for card in editorial_cards:
            poster = str(card.get("poster", "") or card.get("image", "") or card.get("poster_url", "")).strip()
            details = str(card.get("details", "")).strip()
            lines.append(
                f"- INFO — {card['title']}  \n"
                f"  Message: {card['message']}  \n"
                f"  Source: {card['source']}  \n"
                f"  Link: {card.get('link', '#')}  \n"
                f"  Poster: {poster}  \n"
                f"  Details: {details}  \n"
                f"  Label: {card.get('label', 'Ver aviso')}\n"
            )

    if df.empty:
        notice = (
            "Disculpe, actualmente estamos buscando y verificando las mejores oportunidades de financiamiento. "
            "Para más información, comuníquese con la Secretaría Académica de Investigación-UIMA."
        )
        for section in ["México", "Internacionales", "Investigadores senior"]:
            lines.append(f"## {section}\n")
            lines.append(f"> {notice}\n")
        append_editorial_cards()
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return

    source_sections = source_sections or {}
    section_order = ["México", "Internacionales", "Investigadores senior"]
    grouped = df.copy()
    grouped["newsletter_section"] = grouped["source"].map(source_sections).fillna("Internacionales")
    notice = (
        "Disculpe, actualmente estamos buscando y verificando las mejores oportunidades de financiamiento. "
        "Para más información, comuníquese con la Secretaría Académica de Investigación-UIMA."
    )

    for section in section_order:
        section_df = grouped[grouped["newsletter_section"] == section]
        lines.append(f"## {section}\n")
        if section_df.empty:
            lines.append(f"> {notice}\n")
            continue

        section_df = section_df.sort_values(
            ["first_seen_at", "detected_deadline"],
            ascending=[False, True],
            na_position="last",
        ).head(10)
        for _, r in section_df.iterrows():
            dl = r["detected_deadline"] if pd.notna(r["detected_deadline"]) else "—"
            status = r.get("detected_status", "unknown")
            lines.append(
                f"- {dl} ({status}) — {r['title']}  \n  Source: {r['source']}  \n  Link: {r['url']}\n"
            )

    append_editorial_cards()

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

        if not link or not link_is_available(link, "CallsMonitorBot/1.0 (contact: you@example.com)", 20):
            continue

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


SIGNATURE_NAME = "Secretaría Académica de Investigación-UIMA"
SIGNATURE_INSTITUTION = "FES Acatlán – UNAM"
SIGNATURE_JO = "Dr. Javier Orduz"
SIGNATURE_CONTACT = "Teléfono: (+52) 555 623 1750. Ext.: 38903"
DASHBOARD_URL = "https://smcfesacatlanunam.streamlit.app/"


def build_share_email_link(dashboard_url: str) -> str:
    subject = "Boletín de Convocatorias"
    body = (
        "Le comparto el Boletín de Convocatorias del Sistema Institucional de Monitoreo de Convocatorias:\n\n"
        f"{dashboard_url}\n\n"
        "Puede revisar las convocatorias más relevantes y acceder al detalle completo desde el dashboard."
    )
    return f"mailto:?subject={quote(subject, safe='')}&body={quote(body, safe='')}"


def load_email_template(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def html_escape(value: str) -> str:
    return (
        (value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def digest_markdown_to_cards(markdown_text: str) -> str:
    lines = [line.rstrip() for line in markdown_text.splitlines()]
    sections: List[Dict[str, Any]] = []
    current_section: Optional[Dict[str, Any]] = None
    current_item: Optional[Dict[str, str]] = None

    def flush_item() -> None:
        nonlocal current_section, current_item
        if current_section is not None and current_item is not None:
            current_section["items"].append(current_item)
            current_item = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("Generated:") or line.startswith("# Calls Digest (auto)"):
            continue

        if line.startswith("## "):
            flush_item()
            current_section = {"title": line[3:].strip(), "items": [], "notice": ""}
            sections.append(current_section)
            continue

        if line.startswith("> "):
            if current_section is not None:
                current_section["notice"] = line[2:].strip()
            continue

        if line.startswith("- "):
            flush_item()
            if current_section is None:
                current_section = {"title": "Convocatorias", "items": []}
                sections.append(current_section)

            current_item = {"title": "", "source": "", "link": "#", "deadline": "Sin fecha", "status": "Sin información", "message": "", "label": "Ver convocatoria", "kind": "call", "poster": "", "details": ""}
            remainder = line[2:].strip()

            if " — " in remainder:
                prefix, title = remainder.split(" — ", 1)
                current_item["title"] = title.strip()
                prefix = prefix.strip()

                if prefix == "INFO":
                    current_item["kind"] = "info"

                if prefix.startswith("Estado:"):
                    status_value = prefix.replace("Estado:", "", 1).strip()
                    if status_value in {"—", "-", ""}:
                        current_item["status"] = "Sin información"
                    else:
                        current_item["status"] = status_value
                else:
                    match = re.search(r"([0-9]{4}-[0-9]{2}-[0-9]{2})\s*\(([^)]+)\)", prefix)
                    if match:
                        current_item["deadline"] = match.group(1)
                        current_item["status"] = match.group(2)
                    else:
                        if re.match(r"^\d{4}-\d{2}-\d{2}$", prefix):
                            current_item["deadline"] = prefix
                        elif "(" in prefix and prefix.endswith(")"):
                            status_value = prefix[prefix.rfind("(")+1:prefix.rfind(")")]
                            current_item["status"] = status_value
            else:
                current_item["title"] = remainder

            continue

        if line.startswith("Source: "):
            if current_item is not None:
                current_item["source"] = line.replace("Source: ", "", 1).strip()
            continue

        if line.startswith("Message: "):
            if current_item is not None:
                current_item["message"] = line.replace("Message: ", "", 1).strip()
            continue

        if line.startswith("Label: "):
            if current_item is not None:
                current_item["label"] = line.replace("Label: ", "", 1).strip()
            continue

        if line.startswith("Link: "):
            if current_item is not None:
                current_item["link"] = line.replace("Link: ", "", 1).strip()
            continue

        if line.startswith("Poster: "):
            if current_item is not None:
                current_item["poster"] = line.replace("Poster: ", "", 1).strip()
            continue

        if line.startswith("Details: "):
            if current_item is not None:
                current_item["details"] = line.replace("Details: ", "", 1).strip()
            continue

        if line.startswith("No items collected yet."):
            current_section = {"title": "Convocatorias", "items": [{"title": "Todavía no hay convocatorias registradas.", "source": "Sistema", "link": "#", "deadline": "Sin fecha", "status": "Sin información"}]}
            sections.append(current_section)
            continue

    flush_item()

    if not sections:
        return "<p style='margin:0;color:#334e68;line-height:1.6;font-size:14px;'>No hay convocatorias para mostrar.</p>"

    section_ids = {
        "México": "section-mexico",
        "Internacionales": "section-internacionales",
        "Investigadores senior": "section-investigadores-senior",
        "Avisos": "section-avisos",
    }
    visible_sections = [
        section for section in sections
        if section.get("title", "").strip() in section_ids
    ]
    toc_parts = [
        "<table role='presentation' width='100%' cellpadding='0' cellspacing='0' border='0' style='border-collapse:collapse;background:#F8FAFC;border:1px solid #D8E1EA;border-radius:14px;margin:0 0 18px 0;'>",
        "<tr><td style='padding:12px 14px;'>",
        "<div style='font-size:12px;font-weight:800;color:#334E68;letter-spacing:.2px;margin-bottom:8px;'>Contenido del boletín</div>",
    ]
    for section in visible_sections:
        section_title = section.get("title", "").strip()
        section_color = {
            "México": "#002855",
            "Internacionales": "#1F5F6B",
            "Investigadores senior": "#8A6D1D",
            "Avisos": "#1F5F6B",
        }.get(section_title, "#002855")
        toc_parts.append(
            f"<a href='#{section_ids[section_title]}' style='display:inline-block;margin:0 12px 4px 0;color:{section_color};text-decoration:none;font-size:13px;font-weight:700;'>{html_escape(section_title)}</a>"
        )
    toc_parts.extend(["</td></tr></table>", ""])
    html_parts: List[str] = toc_parts
    for section in sections:
        title = section.get("title", "").strip()
        section_colors = {
            "México": ("#002855", "#E6EEF8"),
            "Internacionales": ("#1F5F6B", "#E5F2F3"),
            "Investigadores senior": ("#8A6D1D", "#F8F1D8"),
            "Avisos": ("#1F5F6B", "#E5F2F3"),
        }
        accent_color, accent_background = section_colors.get(title, ("#002855", "#E6EEF8"))
        if title:
            html_parts.append(
                f"<h3 id='{section_ids.get(title, '')}' style='margin:22px 0 12px 0;color:{accent_color};font-size:16px;line-height:1.4;font-weight:700;border-bottom:2px solid {accent_color};padding-bottom:6px;'>"
                f"{html_escape(title)}</h3>"
            )

        items = section.get("items", [])
        if not items:
            notice = section.get("notice", "").strip()
            if notice:
                html_parts.append(
                    f"<p style='margin:0 0 14px 0;color:#475569;line-height:1.6;font-size:14px;'>"
                    f"{html_escape(notice)}</p>"
                )
            continue

        html_parts.append(
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">'
        )

        for item in items:
            title_text = item.get("title") or "Sin título"
            source_text = (item.get("source") or "").strip()
            if not source_text or source_text.lower() in {"fuente no disponible", "source unavailable", "sin fuente"}:
                continue
            link = item.get("link") or "#"
            if not link.startswith(("http://", "https://", "mailto:")):
                link = "#"
            deadline_text = item.get("deadline") or "Sin fecha"
            status_text = item.get("status") or "Sin información"
            message_text = item.get("message") or ""
            action_label = item.get("label") or "Ver convocatoria"
            metadata_html = (
                f"<div style='margin-top:8px;font-size:14px;color:#334e68;line-height:1.6;'>"
                f"{html_escape(message_text)}</div>"
                if item.get("kind") == "info" and message_text
                else f"<div style='margin-top:4px;font-size:12px;color:#475569;line-height:1.5;'>"
                     f"{html_escape(deadline_text)} &nbsp;|&nbsp; {html_escape(status_text)}</div>"
            )
            details_text = (item.get("details") or "").strip()
            poster_url = (item.get("poster") or "").strip()
            poster_html = (
                f"<div style='margin-top:12px;'><img src='{html_escape(poster_url)}' alt='{html_escape(title_text)}' style='display:block;width:100%;max-height:220px;object-fit:cover;border-radius:12px;border:1px solid #D8E1EA;box-shadow:0 8px 18px rgba(15,23,42,0.08);' /></div>"
                if poster_url.startswith(("http://", "https://"))
                else ""
            )
            details_html = (
                f"<div style='margin-top:10px;font-size:14px;color:#334e68;line-height:1.6;'>{html_escape(details_text)}</div>"
                if details_text
                else ""
            )

            html_parts.append(
                                """
                <tr>
                  <td style="padding:0 0 12px 0;">
                                        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:separate;border-spacing:0;background:{card_background};background-clip:padding-box;border:1px solid {accent};border-radius:14px;overflow:hidden;">
                      <tr>
                        <td style="padding:16px;">
                                                    <div style="font-size:16px;font-weight:700;color:{accent};line-height:1.4;">{title}</div>
                          <div style="margin-top:8px;font-size:12px;color:#475569;line-height:1.5;">{source}</div>
                                                    {metadata}
                                                    {poster_html}
                                                    {details_html}
                          <div style="margin-top:12px;">
                                                                                                                <a href="{link}" style="display:inline-block;background:{accent};color:#ffffff;text-decoration:none;padding:10px 14px;border-radius:10px;font-size:13px;font-weight:700;line-height:1.4;">{label}</a>
                          </div>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
                """.format(
                    title=html_escape(title_text),
                    source=html_escape(source_text),
                    deadline=html_escape(deadline_text),
                    status=html_escape(status_text),
                    metadata=metadata_html,
                    poster_html=poster_html,
                    details_html=details_html,
                    label=html_escape(action_label),
                    link=html_escape(link),
                    accent=accent_color,
                    card_background=accent_background,
                )
            )

        html_parts.append("</table>")

    return "\n".join(html_parts)


def build_rendered_email_html(filepath: str) -> str:
    with open(filepath, "r", encoding="utf-8") as f:
        body_md = f.read()

    html_body = digest_markdown_to_cards(body_md)

    template = load_email_template("templates/email_template.html")
    share_link = build_share_email_link(DASHBOARD_URL)

    return template \
        .replace("{{CONTENT}}", html_body) \
        .replace("{{DASHBOARD_URL}}", DASHBOARD_URL) \
        .replace("{{SHARE_LINK}}", share_link) \
        .replace("{{SIGNATURE_NAME}}", SIGNATURE_NAME) \
        .replace("{{SIGNATURE_JO}}", SIGNATURE_JO) \
        .replace("{{SIGNATURE_INSTITUTION}}", SIGNATURE_INSTITUTION) \
        .replace("{{SIGNATURE_CONTACT}}", SIGNATURE_CONTACT)


def write_preview_email(filepath: str, preview_path: str = "data/email_preview.html") -> str:
    html_template = build_rendered_email_html(filepath)
    with open(preview_path, "w", encoding="utf-8") as f:
        f.write(html_template)
    return preview_path


def send_email_digest(filepath: str, recipients: list[str]) -> None:
    sender = os.getenv("EMAIL_USER")
    password = os.getenv("EMAIL_PASS")

    if not sender or not password:
        raise ValueError("EMAIL_USER or EMAIL_PASS not set in environment")

    html_template = build_rendered_email_html(filepath)

    msg = MIMEText(html_template, "html", "utf-8")
    msg["Subject"] = "Boletín semanal de convocatorias"
    msg["From"] = sender
    msg["To"] = sender

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
    run_started_at = today.isoformat()

    for src in srcs["sources"]:
        name = src["name"]
        typ = src["type"]
        url = src["url"]
        include_if = src.get("include_if_url_contains")

        try:
            available, status_code, final_url = validate_url(
                url, s["user_agent"], s["timeout_seconds"]
            )
            if not available:
                status_text = status_code if status_code is not None else final_url
                print(f"[SKIP] {name}: HTTP {status_text} -> {final_url}")
                continue

            print(f"[SOURCE] {name}: HTTP {status_code} -> {final_url}")

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

    purge_non_funding_rows(conn)
    inserted = upsert_items(conn, all_items)
    remove_unvalidated_rows(conn, run_started_at)
    cleanup_old(conn, s["only_keep_days"])
    purge_non_funding_rows(conn)
    df = export_csv(conn, out_csv)
    source_sections = {
        source["name"]: source.get("newsletter_section", "Internacionales")
        for source in srcs["sources"]
    }
    editorial_cards = load_valid_editorial_cards(
        "data/editorial_cards.yaml",
        s["user_agent"],
        s["timeout_seconds"],
    )
    write_digest(df, out_md, source_sections, editorial_cards)
    conn.close()

    print(f"\nDone. Inserted new: {inserted}")
    print(f"CSV: {out_csv}")
    print(f"Digest: {out_md}")



# JO To send

def load_special_recipients(csv_path: str) -> list[str]:
    try:
        df = pd.read_csv(csv_path, dtype=str).fillna("")
    except pd.errors.EmptyDataError:
        return []

    df["selected"] = df["selected"].str.strip().str.lower()
    df["email"] = df["email"].str.strip().str.lower()

    selected_df = df[
        (df["selected"] == "true") &
        (df["email"] != "")
    ].copy()

    # quitar duplicados por seguridad
    selected_df = selected_df.drop_duplicates(subset=["email"])

    recipients = selected_df["email"].tolist()
    return recipients


def update_special_recipients_status(csv_path: str, sent_recipients: list[str]) -> None:
    try:
        df = pd.read_csv(csv_path, dtype=str).fillna("")
    except pd.errors.EmptyDataError:
        return

    df["email"] = df["email"].str.strip().str.lower()
    df["emailStatus"] = df["emailStatus"].astype(str)
    df["lastEmailSent"] = df["lastEmailSent"].astype(str)

    now_ts = datetime.now(timezone.utc).isoformat()

    mask = df["email"].isin([e.strip().lower() for e in sent_recipients])
    df.loc[mask, "emailStatus"] = "sent"
    df.loc[mask, "lastEmailSent"] = now_ts

    df.to_csv(csv_path, index=False, encoding="utf-8")


def normalize_special_recipients_status(csv_path: str) -> None:
    try:
        df = pd.read_csv(csv_path, dtype=str).fillna("")
    except pd.errors.EmptyDataError:
        return

    df["selected"] = df["selected"].str.strip().str.lower()
    df["email"] = df["email"].str.strip().str.lower()
    df["emailStatus"] = df["emailStatus"].astype(str).str.strip().str.lower()

    mask_pending = (
        (df["selected"] == "true") &
        (df["email"] != "") &
        (df["emailStatus"] != "sent")
    )

    df.loc[mask_pending, "emailStatus"] = "pending"

    df.to_csv(csv_path, index=False, encoding="utf-8")




if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--send-email", action="store_true", help="Send digest email")
    parser.add_argument("--preview-email", action="store_true", help="Generate an HTML preview without sending the email")
    args = parser.parse_args()

    main()

    if args.preview_email:
        preview_path = write_preview_email("data/digest.md")
        print(f"Preview generated at: {preview_path}")
        raise SystemExit(0)

    if args.send_email:
        csv_path = "data/special_recipients.csv"

        if os.path.exists(csv_path):
            normalize_special_recipients_status(csv_path)
            recipients = load_special_recipients(csv_path)
        else:
            recipients = []

        if not recipients:
            recipients_env = os.getenv("EMAIL_RECIPIENTS")

            if recipients_env and recipients_env.strip():
                recipients = [e.strip() for e in recipients_env.split(",") if e.strip()]
            else:
                recipients = [os.getenv("EMAIL_USER")]

        if recipients and any(r for r in recipients if r):
            answer = input(f"This will send the newsletter to {len(recipients)} recipient(s). Continue? [y/N]: ").strip().lower()
            if answer not in {"y", "yes"}:
                print("Email sending cancelled.")
                raise SystemExit(0)

        send_email_digest("data/digest.md", recipients)

        if os.path.exists(csv_path):
            update_special_recipients_status(csv_path, recipients)
