import os
import sys
import json
import time
import requests
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from bs4 import BeautifulSoup

# --- ZAROORI: GitHub Actions ke liye ---
from webdriver_manager.chrome import ChromeDriverManager

# --- Configuration ---
APP_URL = "https://apps.shopify.com/subscription-payments"
STATE_FILE = Path("review_state.json")

# GitHub Secrets se webhook lega, local mein test karne ke liye default
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "YOUR_SLACK_WEBHOOK_URL_HERE")

# --- Driver Setup (Sirf webdriver-manager) ---
def init_driver():
    print("Initializing ChromeDriver using webdriver-manager...")
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        print("ChromeDriver initialized successfully!")
        return driver
    except Exception as e:
        print(f"Failed to initialize driver: {e}")
        return None

# --- State Management ---
def load_state():
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r') as f:
                data = json.load(f)
                print(f"Old state loaded: {data}")
                return data
        except json.JSONDecodeError:
            print("State file corrupt. Starting fresh.")
    
    default = {"1_star_count": 0, "2_star_count": 0, "last_1_star_id": None, "last_2_star_id": None}
    print(f"Default state created: {default}")
    return default

def save_state(state):
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=4)
        print("State saved to review_state.json")
    except Exception as e:
        print(f"Error saving state: {e}")

# --- Slack Notification ---
def send_to_slack(message):
    if "YOUR_SLACK_WEBHOOK_URL_HERE" in SLACK_WEBHOOK_URL:
        print("SLACK_WEBHOOK_URL not set. Skipping Slack message.")
        print(f"Would send: {message}")
        return

    try:
        payload = {"text": message}
        response = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        if response.status_code == 200:
            print("Slack message sent successfully.")
        else:
            print(f"Slack error: {response.status_code} {response.text}")
    except Exception as e:
        print(f"Slack request failed: {e}")

# --- Scrape Review Counts ---
def get_review_counts(driver):
    print(f"Fetching review counts from: {APP_URL}")
    try:
        driver.get(APP_URL)
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'a[href*="ratings"]'))
        )
        time.sleep(3)

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        counts = {'1': 0, '2': 0}

        for rating in ['1', '2']:
            link = soup.select_one(f'a[href*="ratings%5B%5D={rating}"]')
            if link:
                span = link.select_one('span.link-block--underline')
                if span:
                    text = span.get_text(strip=True).upper()
                    if 'K' in text:
                        counts[rating] = int(float(text.replace('K', '')) * 1000)
                    else:
                        counts[rating] = int(text)

        print(f"Current counts → 1-star: {counts['1']}, 2-star: {counts['2']}")
        return counts['1'], counts['2']

    except TimeoutException:
        print("Timeout: Review section not loaded.")
        return None, None
    except Exception as e:
        print(f"Error getting counts: {e}")
        return None, None

# --- Scrape New Reviews ---
def get_new_reviews(driver, url, last_known_id):
    print(f"Scraping new reviews from: {url}")
    try:
        driver.get(url)
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-review-content-id]"))
        )
        time.sleep(5)

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        elements = soup.select("div[data-review-content-id]")
        if not elements:
            print("No review elements found.")
            return [], None

        newest_id = elements[0].get('data-review-content-id')
        new_reviews = []

        for el in elements:
            rid = el.get('data-review-content-id')
            if rid == last_known_id:
                print(f"Found last known review ({rid}). Stopping.")
                break

            author = el.select_one('span[title]') or el.select_one('h3')
            author = author.get('title', 'Unknown') if author else "Unknown"

            date = el.select_one('.tw-text-body-xs.tw-text-fg-tertiary')
            date = date.get_text(strip=True) if date else "Unknown Date"

            text_el = el.select_one('div[data-truncate-content-copy] p')
            text = text_el.get_text(strip=True) if text_el else "No text"

            new_reviews.append({
                "id": rid,
                "author": author,
                "date": date,
                "text": text,
                "link": f"https://apps.shopify.com/reviews/{rid}"
            })

        return list(reversed(new_reviews)), newest_id

    except Exception as e:
        print(f"Error scraping reviews: {e}")
        return [], None

# --- Main Function ---
def main():
    print("--- Shopify Review Monitor Started ---")
    state = load_state()
    new_state = state.copy()
    has_new_reviews = False

    driver = init_driver()
    if not driver:
        send_to_slack("Driver failed to start. Monitor stopped.")
        sys.exit(1)

    try:
        # 1. Get current counts
        c1, c2 = get_review_counts(driver)
        if c1 is None:
            send_to_slack("Failed to fetch review counts. Check page layout.")
            return

        new_state["1_star_count"] = c1
        new_state["2_star_count"] = c2

        # 2. Check 1-star
        if c1 > state["1_star_count"]:
            print(f"New 1-star reviews: {c1 - state['1_star_count']}")
            has_new_reviews = True
            url = f"{APP_URL}/reviews?ratings%5B%5D=1&sort_by=newest"
            reviews, latest_id = get_new_reviews(driver, url, state["last_1_star_id"])
            if latest_id:
                new_state["last_1_star_id"] = latest_id
            for r in reviews:
                msg = (
                    f"*New 1-Star Review*\n"
                    f"*Store:* {r['author']}\n"
                    f"*Date:* {r['date']}\n"
                    f"*Link:* {r['link']}"
                )
                send_to_slack(msg)
                time.sleep(1)

        # 3. Check 2-star
        if c2 > state["2_star_count"]:
            print(f"New 2-star reviews: {c2 - state['2_star_count']}")
            has_new_reviews = True
            url = f"{APP_URL}/reviews?ratings%5B%5D=2&sort_by=newest"
            reviews, latest_id = get_new_reviews(driver, url, state["last_2_star_id"])
            if latest_id:
                new_state["last_2_star_id"] = latest_id
            for r in reviews:
                msg = (
                    f"*New 2-Star Review*\n"
                    f"*Store:* {r['author']}\n"
                    f"*Date:* {r['date']}\n"
                    f"*Link:* {r['link']}"
                )
                send_to_slack(msg)
                time.sleep(1)

        # 4. Heartbeat
        if not has_new_reviews:
            print("No new negative reviews.")
            send_to_slack("Shopify Monitor ran successfully. No new negative reviews. (Heartbeat)")

        # 5. Save state
        save_state(new_state)

    except Exception as e:
        error_msg = f"Script crashed: {e}"
        print(error_msg)
        send_to_slack(error_msg)
    finally:
        if driver:
            driver.quit()
        print("--- Script Finished ---")

if __name__ == "__main__":
    main()
