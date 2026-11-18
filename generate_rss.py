#!/usr/bin/env python3
"""Generate an RSS feed for changes on the public ACT Auto Controle page."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from datetime import datetime, timezone
from email.utils import format_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape

DEFAULT_URL = "https://examen.autocontrole.be/Home/SelectExamType"
USER_AGENT = "act-rss-monitor/1.0 (+https://github.com/alanspart/act-rss)"


class VisibleTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"script", "style", "noscript", "template", "svg"}:
            self.ignored += 1

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style", "noscript", "template", "svg"} and self.ignored:
            self.ignored -= 1

    def handle_data(self, data):
        if not self.ignored:
            value = re.sub(r"\\s+", " ", html.unescape(data)).strip()
            if value:
                self.parts.append(value)


def fetch_page(url):
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=45) as response:
        raw = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
    source = raw.decode(charset, errors="replace")
    title_match = re.search(r"<title[^>]*>(.*?)</title>", source, flags=re.I | re.S)
    title = re.sub(r"\\s+", " ", html.unescape(title_match.group(1))).strip() if title_match else "ACT Auto Controle"
    parser = VisibleTextParser()
    parser.feed(source)
    return title, " ".join(parser.parts)


def rss_item(item, target_url):
    description = (
        "Modification détectée sur la page publique ACT Auto Contrôle. "
        "Ce flux ne garantit pas la détection des créneaux d'examen disponibles.\\n\\n"
        + item["snippet"]
    )
    return (
        "    <item>\\n"
        f"      <title>{escape(item['title'])}</title>\\n"
        f"      <link>{escape(target_url)}</link>\\n"
        f"      <guid isPermaLink='false'>{escape(item['guid'])}</guid>\\n"
        f"      <pubDate>{escape(item['pubDate'])}</pubDate>\\n"
        f"      <description>{escape(description)}</description>\\n"
        "    </item>"
    )


def write_feed(path, target_url, items):
    body = "\\n".join(rss_item(item, target_url) for item in items)
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>ACT Auto Contrôle — changements publics</title>
    <link>{escape(target_url)}</link>
    <description>Changements détectés sur la page publique ACT Auto Contrôle. Ce flux ne garantit pas les disponibilités d'examen.</description>
    <language>fr-BE</language>
    <lastBuildDate>{escape(items[0]["pubDate"])}</lastBuildDate>
{body}
  </channel>
</rss>
'''
    path.write_text(xml, encoding="utf-8")


def write_index(path, target_url, latest):
    page = f'''<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Flux RSS ACT Auto Contrôle</title></head>
<body><h1>Flux RSS ACT Auto Contrôle</h1>
<p>Page publique surveillée : <a href="{escape(target_url)}">{escape(target_url)}</a></p>
<p><a href="feed.xml">Ouvrir le flux RSS</a></p>
<p>Dernière modification détectée : {escape(latest["pubDate"])}</p>
<p><strong>Limite :</strong> ce flux ne surveille pas de manière garantie les créneaux disponibles dans le parcours de réservation et n'effectue aucune réservation.</p>
</body></html>
'''
    path.write_text(page, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--output-dir", default="public")
    parser.add_argument("--state-file", default=".rss-state.json")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    state_path = Path(args.state_file)
    feed_path = output_dir / "feed.xml"
    index_path = output_dir / "index.html"
    page_title, visible_text = fetch_page(args.url)
    digest = hashlib.sha256(visible_text.encode("utf-8")).hexdigest()
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}

    items = state.get("items", [])
    changed = digest != state.get("digest") or not feed_path.exists()
    if changed:
        now = datetime.now(timezone.utc)
        item = {
            "title": page_title or "ACT Auto Controle — modification détectée",
            "guid": "sha256:" + digest,
            "pubDate": format_datetime(now, usegmt=True),
            "snippet": visible_text[:500],
        }
        items = [item] + [old for old in items if old.get("guid") != item["guid"]]
        items = items[:20]
        state_path.write_text(json.dumps({"url": args.url, "digest": digest, "updated_at": now.isoformat(), "items": items}, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
        write_feed(feed_path, args.url, items)
        write_index(index_path, args.url, item)
        print("Change detected; wrote " + str(feed_path))
    else:
        print("No public-page change detected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
