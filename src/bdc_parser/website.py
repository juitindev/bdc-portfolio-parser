"""Scrape InductiveHealth Informatics website for company overview and leadership.

Migrated from src/scrape_company_website.py — logic unchanged.
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = PROJECT_ROOT / "data" / "inductivehealth_website.json"

BASE_URL = "https://inductivehealth.com/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
}
DELAY = 1.5


def fetch_page(url: str) -> tuple[int, str | None]:
    """Fetch a URL, return (status_code, html_or_none)."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
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


def extract_nav_links(soup: BeautifulSoup) -> list[dict]:
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
                href = BASE_URL + href
            if href.startswith(BASE_URL):
                nav_links.append({"text": text, "url": href})

    seen = set()
    unique = []
    for link in nav_links:
        if link["url"] not in seen:
            seen.add(link["url"])
            unique.append(link)
    return unique


def classify_page_type(url: str, nav_text: str = "") -> str | None:
    """Classify a nav link as a structural page type, or None to skip."""
    path = url.lower().replace(BASE_URL.lower(), "")
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


def main():
    scraped_at = datetime.now(timezone.utc).isoformat()
    pages = []
    all_leaders = []
    all_products = []
    pages_to_scrape = []

    print("Fetching homepage...")
    status, html = fetch_page(BASE_URL + "/")
    if not html:
        print("FATAL: Homepage failed to load")
        return

    soup = BeautifulSoup(html, "lxml")
    home_text = clean_text(BeautifulSoup(html, "lxml"))
    pages.append({
        "url": BASE_URL + "/",
        "title": soup.title.get_text(strip=True) if soup.title else "",
        "type": "homepage",
        "status_code": status,
        "clean_text": home_text[:3000],
        "structured": {},
    })

    nav_links = extract_nav_links(soup)
    print(f"\nFound {len(nav_links)} nav links:")
    for link in nav_links:
        page_type = classify_page_type(link["url"], link["text"])
        marker = f" → [{page_type}]" if page_type else " (skip)"
        print(f"  {link['text'][:40]:<40} {link['url'][:60]}{marker}")
        if page_type:
            pages_to_scrape.append((link["url"], page_type, link["text"]))

    about_url = BASE_URL + "/about-us/"
    if not any(u == about_url for u, _, _ in pages_to_scrape):
        pages_to_scrape.append((about_url, "about", "About Us"))

    product_pages = [
        (BASE_URL + "/inductivehealthedss/", "products", "InductiveHealth EDSS"),
        (BASE_URL + "/epitrax/", "products", "EpiTrax"),
        (BASE_URL + "/nbs/", "products", "NBS"),
        (BASE_URL + "/webiz/", "products", "WebIZ"),
        (BASE_URL + "/essence/", "products", "ESSENCE"),
    ]
    for url, ptype, text in product_pages:
        if not any(u == url for u, _, _ in pages_to_scrape):
            pages_to_scrape.append((url, ptype, text))

    seen_urls = {BASE_URL + "/"}
    unique_pages = []
    for url, ptype, nav_text in pages_to_scrape:
        norm = url.rstrip("/") + "/"
        if norm not in seen_urls:
            seen_urls.add(norm)
            unique_pages.append((url, ptype, nav_text))

    print(f"\nScraping {len(unique_pages)} structural pages...")

    for url, ptype, nav_text in unique_pages:
        time.sleep(DELAY)
        status, html = fetch_page(url)
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

    output = {
        "company_name": "InductiveHealth Informatics",
        "website": BASE_URL,
        "scraped_at": scraped_at,
        "pages": pages,
        "leadership": unique_leaders,
        "company_overview": {
            "what_they_do": "",
            "target_customers": "",
            "products": list(dict.fromkeys(all_products)),
        },
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*80}")
    print(f"Saved to {OUTPUT_PATH}")
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


if __name__ == "__main__":
    main()
