
from playwright.sync_api import sync_playwright
from urllib.parse import urljoin, urlparse
from datetime import datetime, timezone
from pathlib import Path

import argparse
import json
import os
import re
import time
import requests


# ==========================================
# CONFIGURATION
# ==========================================

BASE_URL = "https://merch.riotgames.com"

CATEGORY_URL = (
    "https://merch.riotgames.com/de-de/category/"
    "riftbound/?page={page}&sort=dateDesc"
)

HEADLESS = True
PAGES_TO_SCAN = 3

DATABASE_FILE = Path("known_products.json")
OUTPUT_FILE = Path("riftbound_products.json")
TEST_DATABASE_FILE = Path("test_known_products.json")

KDA_PATTERN = re.compile(
    r"k\s*/\s*da|kda",
    re.IGNORECASE
)

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN", ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID", ""
).strip()


# ==========================================
# TELEGRAM
# ==========================================

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN:
        print("ERROR: Telegram token is missing.")
        return False

    if not TELEGRAM_CHAT_ID:
        print("ERROR: Telegram chat ID is missing.")
        return False

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    try:
        response = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "disable_web_page_preview": True
            },
            timeout=30
        )

        # Avoid printing URLs containing the token.
        if not response.ok:
            print(
                f"Telegram HTTP error: "
                f"{response.status_code}"
            )
            return False

        data = response.json()

        if data.get("ok") is True:
            print("Telegram message accepted.")
            return True

        print("Telegram rejected the message.")
        return False

    except requests.RequestException as error:
        print(
            "Telegram connection error:",
            type(error).__name__
        )
        return False

    except ValueError:
        print("Invalid Telegram response.")
        return False


def send_scan_summary(
    products_count,
    kda_count,
    new_count,
    notifications_sent,
    notifications_failed,
    elapsed,
    first_run=False
):
    now = datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M UTC")

    status = (
        "Initial baseline created."
        if first_run
        else (
            "New K/DA products detected!"
            if new_count > 0
            else "No new K/DA products detected."
        )
    )

    message = (
        "✅ K/DA FIRESTARTER — SCAN COMPLETED\n\n"
        f"🕒 Time: {now}\n"
        "🇩🇪 Store: Riot Merch Germany\n\n"
        f"📦 Products scanned: {products_count}\n"
        f"🎴 K/DA products: {kda_count}\n"
        f"🆕 New K/DA products: {new_count}\n"
        f"📨 Product alerts sent: {notifications_sent}\n"
        f"⚠️ Product alerts failed: {notifications_failed}\n"
        f"⏱️ Scan duration: {elapsed:.2f}s\n\n"
        f"Status: {status}"
    )

    return send_telegram(message)


def notify_product(product, test_mode=False):
    title = (
        "🧪 SIMULATED K/DA PRODUCT ALERT"
        if test_mode
        else "🚨 NEW RIFTBOUND K/DA PRODUCT!"
    )

    message = (
        f"{title}\n\n"
        f"🎴 Product: {product['name']}\n\n"
        "🇩🇪 Riot Merch Germany\n\n"
        f"🔗 Product link:\n{product['url']}"
    )

    if test_mode:
        message += (
            "\n\nTEST ONLY — no purchase performed."
        )
    else:
        message += (
            "\n\nOpen the product link "
            "to continue shopping."
        )

    return send_telegram(message)


# ==========================================
# PRODUCT FUNCTIONS
# ==========================================

def is_kda_product(name, url):
    return bool(
        KDA_PATTERN.search(f"{name} {url}")
    )


def normalize_product_url(href):
    url = urljoin(BASE_URL, href)
    parsed = urlparse(url)

    if (
        parsed.scheme != "https"
        or parsed.hostname != "merch.riotgames.com"
    ):
        return None

    if "/product/" not in parsed.path:
        return None

    return (
        f"{parsed.scheme}://{parsed.netloc}"
        f"{parsed.path.rstrip('/')}/"
    )


def product_name_from_url(url):
    slug = (
        urlparse(url)
        .path.rstrip("/")
        .split("/")[-1]
    )

    return slug.replace("-", " ").title()


# ==========================================
# DATABASE
# ==========================================

def load_products(database_file):
    if not database_file.exists():
        return set()

    with database_file.open(
        "r",
        encoding="utf-8"
    ) as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise ValueError("Invalid product database.")

    return set(data)


def save_products(database_file, products):
    temporary = database_file.with_suffix(".tmp")

    with temporary.open(
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            sorted(products),
            file,
            indent=4,
            ensure_ascii=False
        )

    temporary.replace(database_file)


# ==========================================
# PRODUCT SCANNER
# ==========================================

def scan_products(page):
    products = {}
    successful_pages = 0

    for page_number in range(
        1,
        PAGES_TO_SCAN + 1
    ):
        category_url = CATEGORY_URL.format(
            page=page_number
        )

        print(f"Scanning page {page_number}...")

        try:
            page.goto(
                category_url,
                wait_until="domcontentloaded",
                timeout=60000
            )

            page.locator(
                'a[href*="/product/"]'
            ).first.wait_for(
                state="attached",
                timeout=20000
            )

            hrefs = page.locator(
                'a[href*="/product/"]'
            ).evaluate_all(
                """
                elements => elements.map(
                    element => element.getAttribute("href")
                )
                """
            )

            page_count = 0

            for href in hrefs:
                if not href:
                    continue

                url = normalize_product_url(href)

                if not url:
                    continue

                name = product_name_from_url(url)

                products[url] = {
                    "name": name,
                    "url": url,
                    "is_kda_product": is_kda_product(
                        name, url
                    )
                }

                page_count += 1

            print(
                f"Product links detected: {page_count}"
            )

            successful_pages += 1

        except Exception as error:
            print(
                f"Page {page_number} failed: "
                f"{type(error).__name__}"
            )

    return products, successful_pages


# ==========================================
# NEW PRODUCT PROCESSING
# ==========================================

def process_new_products(
    products,
    database_file,
    test_mode=False
):
    known = load_products(database_file)

    current_urls = set(products.keys())
    new_urls = current_urls - known

    kda_products = [
        product
        for product in products.values()
        if product["is_kda_product"]
    ]

    new_kda = [
        products[url]
        for url in sorted(new_urls)
        if products[url]["is_kda_product"]
    ]

    updated_known = known.copy()

    # Remember non-K/DA products without alerts.
    for url in new_urls:
        if not products[url]["is_kda_product"]:
            updated_known.add(url)

    sent = 0
    failed = 0

    for product in new_kda:
        print(f"New K/DA: {product['name']}")

        if notify_product(product, test_mode):
            updated_known.add(product["url"])
            sent += 1
        else:
            failed += 1

    save_products(database_file, updated_known)

    return {
        "kda_count": len(kda_products),
        "new_kda_count": len(new_kda),
        "sent": sent,
        "failed": failed
    }


# ==========================================
# REAL MONITOR
# ==========================================

def run_monitor():
    started_at = time.time()

    print("=" * 60)
    print("K/DA FIRESTARTER — TELEGRAM MONITOR")
    print("=" * 60)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=HEADLESS
        )

        context = browser.new_context(
            locale="de-DE",
            viewport={
                "width": 1440,
                "height": 900
            }
        )

        page = context.new_page()

        try:
            products, successful_pages = scan_products(
                page
            )
        finally:
            context.close()
            browser.close()

    # Do not mark products as known after
    # an incomplete or failed scan.
    if (
        successful_pages != PAGES_TO_SCAN
        or not products
    ):
        print("Incomplete scan. No success summary.")
        return False

    first_run = not DATABASE_FILE.exists()

    try:
        if first_run:
            save_products(
                DATABASE_FILE,
                set(products.keys())
            )

            result = {
                "kda_count": sum(
                    p["is_kda_product"]
                    for p in products.values()
                ),
                "new_kda_count": 0,
                "sent": 0,
                "failed": 0
            }
        else:
            result = process_new_products(
                products,
                DATABASE_FILE
            )

    except (OSError, ValueError) as error:
        print(
            "Database error:",
            type(error).__name__
        )
        return False

    output = {
        "scan_time": datetime.now(
            timezone.utc
        ).isoformat(),
        "products_found": len(products),
        "products": list(products.values()),
        "notification_summary": result
    }

    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            output,
            file,
            indent=4,
            ensure_ascii=False
        )

    elapsed = time.time() - started_at

    print("\n" + "=" * 60)
    print("SCAN SUMMARY")
    print("=" * 60)
    print(f"Products scanned: {len(products)}")
    print(f"K/DA products: {result['kda_count']}")
    print(f"New K/DA products: {result['new_kda_count']}")
    print(f"Product alerts sent: {result['sent']}")
    print(f"Product alerts failed: {result['failed']}")
    print(f"Elapsed: {elapsed:.2f}s")

    summary_sent = send_scan_summary(
        products_count=len(products),
        kda_count=result["kda_count"],
        new_count=result["new_kda_count"],
        notifications_sent=result["sent"],
        notifications_failed=result["failed"],
        elapsed=elapsed,
        first_run=first_run
    )

    if not summary_sent:
        print("ERROR: Scan summary notification failed.")

    return (
        result["failed"] == 0
        and summary_sent
    )


# ==========================================
# SIMULATED K/DA TEST
# ==========================================

def test_kda_detection():
    fake_url = (
        "https://merch.riotgames.com/de-de/"
        "product/kda-firestarter-beta-test/"
    )

    product = {
        "name": "Riftbound K/DA Test Edition",
        "url": fake_url,
        "is_kda_product": True
    }

    result = process_new_products(
        {fake_url: product},
        TEST_DATABASE_FILE,
        test_mode=True
    )

    print("\nTEST SUMMARY")
    print(result)

    return result["failed"] == 0


def test_summary():
    return send_scan_summary(
        products_count=26,
        kda_count=0,
        new_count=0,
        notifications_sent=0,
        notifications_failed=0,
        elapsed=6.42
    )


# ==========================================
# COMMAND LINE
# ==========================================

def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--test-kda",
        action="store_true"
    )

    parser.add_argument(
        "--test-summary",
        action="store_true"
    )

    args = parser.parse_args()

    if args.test_summary:
        success = test_summary()
    elif args.test_kda:
        success = test_kda_detection()
    else:
        success = run_monitor()

    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
