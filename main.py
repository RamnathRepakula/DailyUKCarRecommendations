import requests
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime
import time
from groq import Groq
from dotenv import load_dotenv
load_dotenv()

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

SEEN_FILE = "seen_listings.json"
BUDGET = 6000  # Max price in GBP for car search
LOCATION_POSTCODE = "BH12PJ"  # Bournemouth area postcode for radius search

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}


# ─── Persistence ──────────────────────────────────────────────────────────────

def load_seen():
    try:
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)


# ─── Scrapers ─────────────────────────────────────────────────────────────────

def scrape_autotrader():
    cars = []
    url = (
        "https://www.autotrader.co.uk/car-search"
        f"?postcode={LOCATION_POSTCODE}&radius=30&price-to={BUDGET}"
        "&transmission=Automatic&sort=price-asc&page=1"
    )
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.select("[data-testid='trader-seller-listing']")
        if not cards:
            cards = soup.select("li[data-standout-type]") or soup.select("article.product-card")
        for card in cards[:25]:
            try:
                title_el = card.select_one(
                    "[data-testid='search-listing-title'], h3.product-card-details__title"
                )
                price_el = card.select_one(
                    "[data-testid='search-listing-price'], div.product-card-pricing__price"
                )
                mileage_el = card.select_one("[data-spec='mileage'], li.atc-type-picanto--medium")
                year_el = card.select_one("[data-spec='year']")
                link_el = card.select_one("a[href*='/car-details/']")

                if not title_el or not price_el or not link_el:
                    continue
                price = int("".join(filter(str.isdigit, price_el.text)))
                if not (500 < price <= BUDGET):
                    continue
                link = "https://www.autotrader.co.uk" + link_el["href"].split("?")[0]
                cars.append({
                    "source": "AutoTrader",
                    "title": title_el.text.strip(),
                    "price": price,
                    "mileage": mileage_el.text.strip() if mileage_el else "Unknown",
                    "year": year_el.text.strip() if year_el else "Unknown",
                    "link": link,
                    "id": link,
                })
            except Exception:
                continue
    except Exception as e:
        print(f"[AutoTrader] Error: {e}")
    print(f"[AutoTrader] {len(cars)} listings")
    return cars


def scrape_gumtree():
    cars = []
    url = (
        "https://www.gumtree.com/search"
        "?search_category=cars-vans-motorbikes"
        "&search_location=bournemouth"
        f"&max_price={BUDGET}"
        "&vehicle_transmission=automatic"
        "&sort=date"
    )
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.select("li.listing-maxi, article.listing")
        for card in cards[:25]:
            try:
                title_el = card.select_one("h2.listing-title, .listing-title a")
                price_el = card.select_one(".listing-price strong, span.ad-price")
                link_el = card.select_one("a[href*='/cars-vans-motorbikes/']")

                if not title_el or not link_el:
                    continue
                price_text = price_el.text if price_el else "0"
                digits = "".join(filter(str.isdigit, price_text))
                price = int(digits) if digits else 0
                if not (500 < price <= BUDGET):
                    continue
                href = link_el["href"]
                link = href if href.startswith("http") else "https://www.gumtree.com" + href
                cars.append({
                    "source": "Gumtree",
                    "title": title_el.text.strip(),
                    "price": price,
                    "mileage": "See listing",
                    "year": "See listing",
                    "link": link,
                    "id": link,
                })
            except Exception:
                continue
    except Exception as e:
        print(f"[Gumtree] Error: {e}")
    print(f"[Gumtree] {len(cars)} listings")
    return cars


def scrape_motors():
    """
    Motors.co.uk — search page for automatic cars near Bournemouth under budget.
    URL pattern uses postcode radius, max price, and gearbox=automatic filters.
    """
    cars = []
    url = (
        "https://www.motors.co.uk/search/car/results/"
        f"?price-to={BUDGET}"
        f"&postcode={LOCATION_POSTCODE}"
        "&distance=30"
        "&gearbox=automatic"
        "&page=1"
    )
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")

        # Motors.co.uk renders listings inside <div class="card"> or <article>
        cards = soup.select("div.card--vehicle, article.vehicle-card, div[data-vehicle-id]")
        if not cards:
            # Fallback: grab any block with a price and a title
            cards = soup.select("div.listing-item, li.vehicle-result")

        for card in cards[:25]:
            try:
                title_el = card.select_one(
                    "h2.card__title, h3.vehicle-title, a.vehicle-name, "
                    "[class*='title'] a, [class*='heading']"
                )
                price_el = card.select_one(
                    "span.price, div.price, [class*='price']"
                )
                mileage_el = card.select_one(
                    "[class*='mileage'], [data-spec='mileage'], li:contains('miles')"
                )
                year_el = card.select_one(
                    "[class*='year'], [data-spec='year']"
                )
                link_el = card.select_one("a[href]")

                if not title_el or not price_el or not link_el:
                    continue

                price_digits = "".join(filter(str.isdigit, price_el.text))
                price = int(price_digits) if price_digits else 0
                if not (500 < price <= BUDGET):
                    continue

                href = link_el["href"]
                link = href if href.startswith("http") else "https://www.motors.co.uk" + href

                cars.append({
                    "source": "Motors.co.uk",
                    "title": title_el.text.strip(),
                    "price": price,
                    "mileage": mileage_el.text.strip() if mileage_el else "See listing",
                    "year": year_el.text.strip() if year_el else "See listing",
                    "link": link,
                    "id": link,
                })
            except Exception:
                continue
    except Exception as e:
        print(f"[Motors.co.uk] Error: {e}")
    print(f"[Motors.co.uk] {len(cars)} listings")
    return cars


# ─── Orchestrator ─────────────────────────────────────────────────────────────

def scrape_all(seen: set):
    """
    Run all three scrapers, deduplicate against seen IDs and across sources.
    Returns (new_cars, source_stats).
    """
    raw = []
    scrapers = [
        ("AutoTrader", scrape_autotrader),
        ("Gumtree",    scrape_gumtree),
        ("Motors.co.uk", scrape_motors),
    ]
    source_stats = {}
    for name, fn in scrapers:
        try:
            results = fn()
            source_stats[name] = len(results)
            raw.extend(results)
        except Exception as e:
            print(f"[{name}] Scraper crashed: {e}")
            source_stats[name] = 0
        time.sleep(2)  # polite crawl delay between sites

    # Deduplicate by link — first occurrence wins
    seen_ids_this_run = set()
    deduped = []
    for car in raw:
        cid = car["id"]
        if cid not in seen and cid not in seen_ids_this_run:
            deduped.append(car)
            seen_ids_this_run.add(cid)

    print(f"Total new listings after dedup: {len(deduped)}")
    return deduped, source_stats


# ─── Claude analysis ──────────────────────────────────────────────────────────

def analyse_with_claude(cars):
    client = Groq(api_key=GROQ_API_KEY)

    car_list = "\n".join([
        f"{i+1}. {c['title']} | £{c['price']} | {c['mileage']} | {c['year']} | {c['source']}"
        for i, c in enumerate(cars)
    ])

    prompt = f"""You are a UK used car expert helping an Indian expat living in Bournemouth, UK, 
find a reliable automatic car under £{BUDGET}.

Listings are sourced from AutoTrader, Gumtree, and Motors.co.uk.
Note: AutoTrader/Motors tend to be dealer stock (often better condition); Gumtree is usually 
private sellers (more negotiable but higher risk).

Rate each car 1–10 considering:
- Value for money at this price point
- Reliability reputation (Toyota Yaris/Auris, Honda Jazz/Civic, Ford Fiesta auto = good bets;
  avoid high-end German brands — expensive to maintain at this budget)
- Mileage and age appropriateness
- Running costs and road tax (important for someone new to UK driving)
- Insurance cost (smaller engines = lower premiums, important for new UK licence holders)
- Any red flags (too cheap for age/mileage, unusual makes at this budget)

Listings:
{car_list}

Return ONLY a valid JSON array, no markdown fences, no preamble:
[{{"index": 1, "score": 8, "verdict": "Solid budget buy", "pros": "Reliable, cheap to insure", "cons": "High mileage", "recommend": true}}]"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",   # fast, free-tier friendly; swap to mixtral-8x7b-32768 if you need longer context
        messages=[
            {
                "role": "system",
                "content": "You are a UK used car expert. Always respond with valid JSON only."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0.3,
        max_tokens=2000,
    )

    raw = response.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())

# ─── Telegram ─────────────────────────────────────────────────────────────────

def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    resp = requests.post(url, json=payload, timeout=10)
    if not resp.ok:
        print(f"Telegram error: {resp.text}")


def format_message(cars, analyses, source_stats):
    scored = []
    for a in analyses:
        idx = a.get("index", 0) - 1
        if 0 <= idx < len(cars):
            scored.append({**cars[idx], **a})
    scored.sort(key=lambda x: x.get("score", 0), reverse=True)
    top5 = [c for c in scored if c.get("recommend")][:5]

    today = datetime.now().strftime("%d %b %Y")
    total = sum(source_stats.values())
    stats_line = " · ".join(f"{s}: {n}" for s, n in source_stats.items() if n > 0)

    msg = f"<b>Daily Car Hunt — {today}</b>\n"
    msg += f"Scanned {total} listings ({stats_line})\n"
    msg += f"New this run: {len(cars)} | Top picks below\n\n"

    if not top5:
        msg += "No strong recommendations today. Check again tomorrow!"
        return msg

    for i, car in enumerate(top5, 1):
        score = car.get("score", 0)
        filled = min(score, 5)
        stars = "★" * filled + "☆" * (5 - filled)
        msg += f"<b>{i}. {car['title']}</b>\n"
        msg += f"£{car['price']} | {stars} {score}/10 | {car['source']}\n"
        msg += f"Pros: {car.get('pros', '—')}\n"
        msg += f"Cons: {car.get('cons', '—')}\n"
        msg += f"<a href='{car['link']}'>View listing</a>\n\n"

    return msg


# ─── Entry point ──────────────────────────────────────────────────────────────

def run():
    seen = load_seen()
    new_cars, source_stats = scrape_all(seen)

    if not new_cars:
        send_telegram(
            "<b>Car Hunt</b>: No new listings today across AutoTrader, "
            "Gumtree, and Motors.co.uk. Will check again tomorrow!"
        )
        return

    # Claude can handle ~50 listings in one shot at haiku pricing
    batch = new_cars[:50]
    analyses = analyse_with_claude(batch)
    message = format_message(batch, analyses, source_stats)
    send_telegram(message)

    # Persist all seen IDs (not just the batch)
    seen.update(c["id"] for c in new_cars)
    save_seen(seen)
    print("Done.")


if __name__ == "__main__":
    run()