import os
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
from bs4 import BeautifulSoup
from webdriver_manager.chrome import ChromeDriverManager

# --- 11 APPS CONFIG ---
APPS = {
    "Recharge": {"url": "https://apps.shopify.com/subscription-payments", "name": "Recharge"},
    "Appstle": {"url": "https://apps.shopify.com/subscriptions-by-appstle", "name": "Appstle Subscriptions"},
    "Seal": {"url": "https://apps.shopify.com/seal-subscriptions", "name": "Seal Subscriptions"},
    "Kaching": {"url": "https://apps.shopify.com/kaching-subscriptions", "name": "Kaching Subscriptions"},
    "Joy": {"url": "https://apps.shopify.com/joy-subscription", "name": "Joy Subscriptions"},
    "Subi": {"url": "https://apps.shopify.com/subi-subscriptions-memberships", "name": "Subi Subscriptions"},
    "Bold": {"url": "https://apps.shopify.com/bold-subscriptions", "name": "Bold Subscriptions"},
    "Recurpay": {"url": "https://apps.shopify.com/recurpay-subscriptions", "name": "Recurpay"},
    "ShopifySubs": {"url": "https://apps.shopify.com/shopify-subscriptions", "name": "Shopify Subscriptions"},
    "StayAI": {"url": "https://apps.shopify.com/stayai-subscriptions", "name": "Stay AI"},
    "Smartrr": {"url": "https://apps.shopify.com/smartrr", "name": "Smartrr"},
    "PayWhirl": {"url": "https://apps.shopify.com/paywhirl", "name": "PayWhirl"}
}

STATE_FILE = Path("review_state.json")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "YOUR_SLACK_WEBHOOK_URL_HERE")

# --- DRIVER ---
def init_driver():
    print("Initializing ChromeDriver...")
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        print("Driver ready!")
        return driver
    except Exception as e:
        print(f"Driver failed: {e}")
        return None

# --- STATE WITH MIGRATION ---
def load_state():
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r') as f:
                old_state = json.load(f)
            
            if "1_star_count" in old_state:
                print("Old state detected. Migrating to 11-app format...")
                migrated = {
                    "Recharge": {
                        "1_star": old_state.get("1_star_count", 0),
                        "2_star": old_state.get("2_star_count", 0),
                        "last_1_id": old_state.get("last_1_star_id"),
                        "last_2_id": old_state.get("last_2_star_id")
                    }
                }
                for key in [k for k in APPS.keys() if k != "Recharge"]:
                    migrated[key] = {"1_star": 0, "2_star": 0, "last_1_id": None, "last_2_id": None}
                print("Migration complete.")
                return migrated
            else:
                print("New state format loaded.")
                return old_state
        except Exception as e:
            print(f"State load error: {e}")
    
    print("Creating fresh state for 11 apps...")
    return {key: {"1_star": 0, "2_star": 0, "last_1_id": None, "last_2_id": None} for key in APPS}

def save_state(state):
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=4)
        print("State saved.")
    except Exception as e:
        print(f"Save failed: {e}")

# --- SLACK ---
def send_to_slack(message):
    if "YOUR_SLACK" in SLACK_WEBHOOK_URL:
        print(f"[SLACK] {message}")
        return
    try:
        requests.post(SLACK_WEBHOOK_URL, json={"text": message}, timeout=10)
        print("Sent to Slack.")
    except Exception as e:
        print(f"Slack error: {e}")

# --- SCRAPING ---
def get_counts(driver, url):
    try:
        driver.get(url)
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, 'a[href*="ratings"]')))
        time.sleep(3)
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        c1 = c2 = 0
        for r in ['1', '2']:
            link = soup.select_one(f'a[href*="ratings%5B%5D={r}"]')
            if link:
                span = link.select_one('span')
                if span:
                    txt = span.get_text(strip=True).upper()
                    val = int(float(txt.replace('K', '')) * 1000) if 'K' in txt else int(txt)
                    if r == '1': c1 = val
                    else: c2 = val
        return c1, c2
    except Exception as e:
        print(f"Count error: {e}")
        return None, None

def get_new_reviews(driver, url, last_id):
    try:
        driver.get(url)
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-review-content-id]")))
        time.sleep(5)
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        reviews = []
        elements = soup.select("div[data-review-content-id]")
        if not elements: return [], None
        newest = elements[0].get('data-review-content-id')
        for el in elements:
            rid = el.get('data-review-content-id')
            if rid == last_id: break
            author = el.select_one('span[title]') or el.select_one('h3')
            author = author.get('title', 'Unknown') if author else "Unknown"
            date = el.select_one('.tw-text-body-xs') or el.select_one('time')
            date = date.get_text(strip=True) if date else "Unknown"
            link = f"https://apps.shopify.com/reviews/{rid}"
            reviews.append({"id": rid, "author": author, "date": date, "link": link})
        return list(reversed(reviews)), newest
    except Exception as e:
        print(f"Review error: {e}")
        return [], None

# --- MAIN ---
def main():
    print("Multi-App Monitor: 11 Apps")
    state = load_state()

    # SAFE NEW_STATE
    new_state = {}
    for k, v in state.items():
        if isinstance(v, dict):
            new_state[k] = v.copy()
        else:
            new_state[k] = v

    driver = init_driver()
    if not driver:
        send_to_slack("Driver failed to start!")
        return

    any_new = False
    try:
        for key, app in APPS.items():
            print(f"\nChecking: {app['name']}")
            c1, c2 = get_counts(driver, app["url"])
            if c1 is None:
                send_to_slack(f"{app['name']} - Failed to load")
                continue

            new_state[key]["1_star"] = c1
            new_state[key]["2_star"] = c2

            # 1-star
            if c1 > state[key]["1_star"]:
                any_new = True
                url = f"{app['url']}/reviews?ratings%5B%5D=1&sort_by=newest"
                reviews, nid = get_new_reviews(driver, url, state[key]["last_1_id"])
                if nid: 
                    new_state[key]["last_1_id"] = nid  # FIXED
                for r in reviews:
                    msg = f"*New 1-Star Review*\n*App:* {app['name']}\n*Store:* {r['author']}\n*Date:* {r['date']}\n*Link:* {r['link']}"
                    send_to_slack(msg)

            # 2-star
            if c2 > state[key]["2_star"]:
                any_new = True
                url = f"{app['url']}/reviews?ratings%5B%5D=2&sort_by=newest"
                reviews, nid = get_new_reviews(driver, url, state[key]["last_2_id"])
                if nid: 
                    new_state[key]["last_2_id"] = nid  # FIXED
                for r in reviews:
                    msg = f"*New 2-Star Review*\n*App:* {app['name']}\n*Store:* {r['author']}\n*Date:* {r['date']}\n*Link:* {r['link']}"
                    send_to_slack(msg)

        if not any_new:
            send_to_slack("All 11 apps checked. No new 1/2-star reviews. (Heartbeat)")

        save_state(new_state)

    finally:
        driver.quit()
        print("Monitor Finished")

if __name__ == "__main__":
    main()
