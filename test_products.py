
from playwright.sync_api import sync_playwright
from urllib.parse import urljoin, urlparse
from datetime import datetime
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

# Separate database for simulated testing.
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
        print("ERROR: Telegram bot token is missing.")
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

        response.raise_for_status()

        result = response.json()

        if result.get("ok") is True:
            print("Telegram message accepted.")
            return True

        print("Telegram rejected the message.")
        return False

    except requests.RequestException as error:
        # Do not print raw URLs because they
        # contain the Telegram bot token.
        print(
            "Telegram request error:",
            type(error).__name__
        )
        return False

    except ValueError:
        print("Invalid Telegram response.")
        return False


# ==========================================
# PRODUCT HELPERS
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

    slug = urlparse(url).path.rstrip("/").split("/")[-1]

    return slug.replace("-", " ").title()


# ==========================================
# DATABASE FUNCTIONS
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

    temporary_file = database_file.with_suffix(".tmp")

    with temporary_file.open(
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            sorted(products),
            file,
            indent=4,
            ensure_ascii=False
        )

    temporary_file.replace(database_file)


# ==========================================
# NOTIFICATIONS
# ==========================================

def notify_product(product, test_mode=False):

    if test_mode:
        title = "🧪 SIMULATED K/DA PRODUCT ALERT"
    else:
        title = "🚨 NEW RIFTBOUND K/DA PRODUCT!"

    message = (
        f"{title}\n\n"
        f"🎴 Product: {product['name']}\n\n"
        "🇩🇪 Store: Riot Merch Germany\n\n"
        f"🔗 Product URL:\n{product['url']}\n\n"
    )

    if test_mode:
        message += (
            "TEST ONLY: This product is fictional.\n"
            "No purchase or cart action was performed."
        )
    else:
        message += (
            "Open the product link on your phone "
            "to continue shopping."
        )

    return send_telegram(message)


# ==========================================
# COMMON NEW-PRODUCT PROCESSING
# ==========================================

def process_new_products(
    products,
    database_file,
    test_mode=False
):
    """
    Process products and notify new K/DA matches.

    Only mark a K/DA item as known after
    Telegram accepts its notification.

    Non-K/DA products are saved without alerts.
    """

    known_products = load_products(database_file)

    current_urls = set(products.keys())
    new_urls = current_urls - known_products

    kda_products = [
        product
        for product in products.values()
        if product["is_kda_product"]
    ]

    new_kda_products = [
        products[url]
        for url in sorted(new_urls)
        if products[url]["is_kda_product"]
    ]

    print(f"Products scanned: {len(products)}")
    print(f"K/DA products: {len(kda_products)}")
    print(f"New products: {len(new_urls)}")
    print(f"New K/DA products: {len(new_kda_products)}")

    updated_known = known_products.copy()

    for url in new_urls:
        if not products[url]["is_kda_product"]:
            updated_known.add(url)

    notifications_sent = 0
    notifications_failed = 0

    for product in new_kda_products:

        print(f"\nNEW K/DA: {product['name']}")

        success = notify_product(
            product,
            test_mode=test_mode
        )

        if success:
            updated_known.add(product["url"])
            notifications_sent += 1
        else:
            notifications_failed += 1

    save_products(database_file, updated_known)

    return {
        "new_kda_products": len(new_kda_products),
        "notifications_sent": notifications_sent,
        "notifications_failed": notifications_failed
    }


# ==========================================
# RIOT MERCH SCANNER
# ==========================================

def scan_products(page):

    products = {}
    successful_pages = 0

    for page_number in range(
        1, PAGES_TO_SCAN + 1
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

            for href in hrefs:

                if not href:
                    continue

                product_url = normalize_product_url(
                    href
                )

                if not product_url:
                    continue

                name = product_name_from_url(
                    product_url
                )

                products[product_url] = {
                    "name": name,
                    "url": product_url,
                    "is_kda_product": is_kda_product(
                        name,
                        product_url
                    )
                }

            successful_pages += 1

        except Exception as error:
            print(
                f"Scan error on page {page_number}: "
                f"{type(error).__name__}"
            )

    return products, successful_pages


# ==========================================
# REAL MONITOR
# ==========================================

def run_monitor():

    started_at = time.time()

    print("=" * 60)
    print("RIFTBOUND K/DA TELEGRAM MONITOR")
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

    if (
        successful_pages != PAGES_TO_SCAN
        or not products
    ):
        print("Incomplete scan. History unchanged.")
        return False

    # First-run protection applies only
    # to the real store database.
    first_run = not DATABASE_FILE.exists()

    if first_run:
        save_products(
            DATABASE_FILE,
            set(products.keys())
        )

        print("Initial product baseline created.")
        print("No alerts on first run.")
        return True

    try:
        result = process_new_products(
            products,
            DATABASE_FILE,
            test_mode=False
        )
    except (OSError, ValueError):
        print("ERROR: Could not load/save product history.")
        return False

    output = {
        "scan_time": datetime.now().isoformat(),
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

    print("\n" + "=" * 60)
    print("SCAN SUMMARY")
    print("=" * 60)

    print(f"Products scanned: {len(products)}")
    print(
        f"Notifications sent: "
        f"{result['notifications_sent']}"
    )
    print(
        f"Notifications failed: "
        f"{result['notifications_failed']}"
    )

    print(
        f"Elapsed: {round(time.time() - started_at, 2)}s"
    )

    return result["notifications_failed"] == 0


# ==========================================
# SIMULATED K/DA TEST
# ==========================================

def test_kda_detection():

    print("=" * 60)
    print("SIMULATED K/DA NOTIFICATION TEST")
    print("=" * 60)

    # Fictional product. It is NOT a real
    # Riot Merch product or checkout URL.

    fake_url = (
        "https://merch.riotgames.com/de-de/"
        "product/kda-firestarter-beta-test/"
    )

    fake_product = {
        "name": "Riftbound K/DA Test Edition",
        "url": fake_url,
        "is_kda_product": is_kda_product(
            "Riftbound K/DA Test Edition",
            fake_url
        )
    }

    products = {
        fake_url: fake_product
    }

    try:
        result = process_new_products(
            products,
            TEST_DATABASE_FILE,
            test_mode=True
        )

    except (OSError, ValueError):
        print("Test database could not be read or saved.")
        return False

    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    print(
        f"New K/DA products: "
        f"{result['new_kda_products']}"
    )

    print(
        f"Notifications sent: "
        f"{result['notifications_sent']}"
    )

    print(
        f"Notifications failed: "
        f"{result['notifications_failed']}"
    )

    if result["notifications_failed"]:
        return False

    if result["notifications_sent"] == 1:
        print("PASS: New K/DA notification sent.")
        print("Run again to verify no duplicate alert.")

    elif result["new_kda_products"] == 0:
        print("PASS: Existing product not notified again.")

    return True


# ==========================================
# COMMAND LINE
# ==========================================

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--test-kda",
        action="store_true",
        help="Simulate a new K/DA product and notify"
    )

    parser.add_argument(
        "--reset-test-kda",
        action="store_true",
        help="Reset simulated test history only"
    )

    args = parser.parse_args()

    if args.reset_test_kda:
        TEST_DATABASE_FILE.unlink(missing_ok=True)
        print("Simulated test history reset.")
        return

    if args.test_kda:
        success = test_kda_detection()
    else:
        success = run_monitor()

    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
