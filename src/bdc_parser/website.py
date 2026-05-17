"""Polite scraper for a portfolio company website (homepage + about + product pages)."""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from bdc_parser.paths import website_json

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
}
DEFAULT_DELAY = 1.5


def fetch_page(url: str, headers: dict) -> tuple[int, str | None]:
    """Fetch a URL, return (status_code, html_or_none)."""
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        print(f"  {resp.status_code} {url} ({len(resp.text):,} bytes)")
        if resp.status_code == 200:
            return resp.status_code, resp.text
        return resp.status_code, None
    except requests.RequestException as e:
        print(f"  ERROR {url}: {e}")
        return 0, None


def clean_text(soup: BeautifulSoup) -> str:
    """Extract main content text, stripping nav/footer/scripts/styles."""
    for tag in soup.find_all(["script", "style", "noscript", "nav", "footer",
                               "header", "iframe"]):
        tag.decompose()

    main = soup.find("main") or soup.find("article") or soup.find("div", class_=re.compile(r"content|entry|page"))
    target = main if main else soup.body

    if not target:
        return ""

    text = target.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def extract_nav_links(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """Extract navigation links to find product/service/about pages."""
    nav_links = []
    nav_areas = soup.find_all(["nav"]) or soup.find_all(class_=re.compile(r"menu|nav", re.I))

    for nav in nav_areas:
        for a in nav.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True)
            if not text or len(text) > 60:
                continue
            if href.startswith("/"):
                href = base_url.rstrip("/") + href
            if href.startswith(base_url):
                nav_links.append({"text": text, "url": href})

    seen = set()
    unique = []
    for link in nav_links:
        if link["url"] not in seen:
            seen.add(link["url"])
            unique.append(link)
    return unique


def classify_page_type(url: str, base_url: str, nav_text: str = "") -> str | None:
    """Classify a nav link as a structural page type, or None to skip."""
    path = url.lower().replace(base_url.lower(), "")
    combined = (path + " " + nav_text).lower()

    if any(kw in combined for kw in ["about", "team", "leadership", "who-we-are"]):
        return "about"
    if any(kw in combined for kw in ["product", "service", "solution", "platform",
                                      "what-we-do", "offerings", "capabilities"]):
        return "products"
    if any(kw in combined for kw in ["contact", "get-in-touch"]):
        return "contact"
    if any(kw in combined for kw in ["partner", "client", "customer", "case-stud"]):
        return "customers"
    return None


def extract_leadership(soup: BeautifulSoup) -> list[dict]:
    """Extract leadership names and titles from an about/team page."""
    leaders = []

    team_blocks = soup.find_all(class_=re.compile(
        r"team|member|leader|executive|staff|person|profile", re.I
    ))

    for block in team_blocks:
        name_el = block.find(["h2", "h3", "h4", "strong"])
        if not name_el:
            continue
        name = name_el.get_text(strip=True)
        if not name or len(name) > 60 or len(name) < 3:
            continue

        title = ""
        bio = ""
        for sib in name_el.find_next_siblings(limit=3):
            text = sib.get_text(strip=True)
            if not text:
                continue
            if not title and len(text) < 80:
                title = text
            elif not bio and len(text) > 20:
                bio = text[:500]

        if name:
            leaders.append({"name": name, "title": title, "bio": bio})

    if not leaders:
        for el in soup.find_all(["h2", "h3", "h4", "p", "div", "span"]):
            text = el.get_text(strip=True)
            m = re.match(r"^([A-Z][a-z]+ [A-Z][a-z\-]+(?:\s+[A-Z][a-z\-]+)?)\s*[—–,|]\s*(.+)$", text)
            if m and len(m.group(2)) < 80:
                leaders.append({"name": m.group(1), "title": m.group(2), "bio": ""})

    leaders = [l for l in leaders if l["title"] and
               any(kw in l["title"].lower() for kw in
                   ["chief", "president", "vp", "vice", "director", "manager",
                    "officer", "head", "founder", "ceo", "cfo", "cto", "coo",
                    "general manager", "partner", "executive"])]

    seen = set()
    unique = []
    for l in leaders:
        if l["name"] not in seen:
            seen.add(l["name"])
            unique.append(l)

    return unique


def extract_products(soup: BeautifulSoup) -> list[str]:
    """Extract product/service names from a products page."""
    products = []
    for h in soup.find_all(["h2", "h3"]):
        text = h.get_text(strip=True)
        if text and 3 < len(text) < 80:
            if not any(kw in text.lower() for kw in ["contact", "blog", "news",
                       "learn more", "get started", "ready to"]):
                products.append(text)
    return products


def run(
    target: str,
    base_url: str,
    *,
    company_name: str | None = None,
    extra_urls: list[tuple[str, str, str]] | None = None,
    delay: float = DEFAULT_DELAY,
) -> Path:
    """Scrape a portfolio company website. Returns output JSON path.

    Args:
        target: short slug used for output filename (e.g., "inductivehealth")
        base_url: company website root (e.g., "https://inductivehealth.com/")
        company_name: display name for the output JSON; falls back to scraped <title>
        extra_urls: optional list of (url, page_type, nav_text) for product pages
            that may not be discoverable via nav-link crawling
    """
    base_url = base_url.rstrip("/") + "/"
    out_path = website_json(target)
    scraped_at = datetime.now(timezone.utc).isoformat()
    pages = []
    all_leaders = []
    all_products = []
    pages_to_scrape: list[tuple[str, str, str]] = []

    print("Fetching homepage...")
    status, html = fetch_page(base_url, DEFAULT_HEADERS)
    if not html:
        print("FATAL: Homepage failed to load")
        return out_path

    soup = BeautifulSoup(html, "lxml")
    home_title = soup.title.get_text(strip=True) if soup.title else ""
    home_text = clean_text(BeautifulSoup(html, "lxml"))
    pages.append({
        "url": base_url,
        "title": home_title,
        "type": "homepage",
        "status_code": status,
        "clean_text": home_text[:3000],
        "structured": {},
    })

    nav_links = extract_nav_links(soup, base_url)
    print(f"\nFound {len(nav_links)} nav links:")
    for link in nav_links:
        page_type = classify_page_type(link["url"], base_url, link["text"])
        marker = f" → [{page_type}]" if page_type else " (skip)"
        print(f"  {link['text'][:40]:<40} {link['url'][:60]}{marker}")
        if page_type:
            pages_to_scrape.append((link["url"], page_type, link["text"]))

    about_url = base_url + "about-us/"
    if not any(u == about_url for u, _, _ in pages_to_scrape):
        pages_to_scrape.append((about_url, "about", "About Us"))

    if extra_urls:
        for url, ptype, text in extra_urls:
            if not any(u == url for u, _, _ in pages_to_scrape):
                pages_to_scrape.append((url, ptype, text))

    seen_urls = {base_url}
    unique_pages = []
    for url, ptype, nav_text in pages_to_scrape:
        norm = url.rstrip("/") + "/"
        if norm not in seen_urls:
            seen_urls.add(norm)
            unique_pages.append((url, ptype, nav_text))

    print(f"\nScraping {len(unique_pages)} structural pages...")

    for url, ptype, nav_text in unique_pages:
        time.sleep(delay)
        status, html = fetch_page(url, DEFAULT_HEADERS)
        if not html:
            pages.append({
                "url": url,
                "title": nav_text,
                "type": ptype,
                "status_code": status,
                "clean_text": "",
                "structured": {"error": f"HTTP {status}"},
            })
            continue

        page_soup = BeautifulSoup(html, "lxml")
        page_text = clean_text(BeautifulSoup(html, "lxml"))

        page_data = {
            "url": url,
            "title": page_soup.title.get_text(strip=True) if page_soup.title else nav_text,
            "type": ptype,
            "status_code": status,
            "clean_text": page_text[:3000],
            "structured": {},
        }

        if ptype == "about":
            leaders = extract_leadership(page_soup)
            all_leaders.extend(leaders)
            page_data["structured"]["leadership_count"] = len(leaders)

        if ptype in ("products", "homepage"):
            prods = extract_products(page_soup)
            all_products.extend(prods)
            page_data["structured"]["headings"] = prods

        if ptype == "contact":
            emails = re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", html)
            phones = re.findall(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", page_text)
            page_data["structured"]["emails"] = list(set(emails))
            page_data["structured"]["phones"] = list(set(phones))

        pages.append(page_data)

    seen_names = set()
    unique_leaders = []
    for l in all_leaders:
        if l["name"] not in seen_names:
            seen_names.add(l["name"])
            unique_leaders.append(l)

    resolved_name = company_name or home_title or target

    output = {
        "company_name": resolved_name,
        "website": base_url,
        "scraped_at": scraped_at,
        "pages": pages,
        "leadership": unique_leaders,
        "company_overview": {
            "what_they_do": "",
            "target_customers": "",
            "products": list(dict.fromkeys(all_products)),
        },
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*80}")
    print(f"Saved to {out_path}")
    print(f"{'='*80}")

    print(f"\nPAGES SCRAPED ({len(pages)}):")
    for p in pages:
        print(f"  [{p['status_code']}] {p['type']:<12} {p['url']}")
        print(f"       Title: {p['title'][:70]}")
        print(f"       Text length: {len(p['clean_text'])} chars")
        if p["structured"]:
            print(f"       Structured: {p['structured']}")
        print()

    print(f"LEADERSHIP ({len(unique_leaders)}):")
    for l in unique_leaders:
        print(f"  {l['name']:<30} {l['title']}")
        if l["bio"]:
            print(f"    Bio: {l['bio'][:120]}...")
        print()

    print(f"PRODUCT HEADINGS ({len(all_products)}):")
    for p in dict.fromkeys(all_products):
        print(f"  - {p}")

    return out_path
