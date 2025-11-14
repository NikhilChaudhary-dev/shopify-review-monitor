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

# --- APPS CONFIG ---
# Note: There are 12 apps listed here, covering the main subscription apps.
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
    """Initializes a headless ChromeDriver instance."""
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
    """Loads state from file, handling migration from old single-app format."""
    default_state = {key: {"1_star": 0, "2_star": 0, "last_1_id": None, "last_2_id": None} for key in APPS}
    
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r') as f:
                old_state = json.load(f)
            
            # Migration check: If old state contains single-app keys (like "1_star_count")
            if "1_star_count" in old_state and "Recharge" not in old_state:
                print("Old single-app state detected. Migrating to multi-app format...")
                migrated = default_state
                migrated["Recharge"] = {
                    "1_star": old_state.get("1_star_count", 0),
                    "2_star": old_state.get("2_star_count", 0),
                    "last_1_id": old_state.get("last_1_star_id"),
                    "last_2_id": old_state.get("last_2_star_id")
                }
                print("Migration complete.")
                return migrated
            
            # Clean up state to ensure all expected keys exist in the current APPS list
            current_state = default_state
            for k in APPS:
                if k in old_state:
                    # Merge existing state with default structure to prevent missing keys
                    current_state[k] = {**default_state[k], **old_state[k]}
            
            print("State loaded successfully.")
            return current_state
        
        except Exception as e:
            print(f"State load error: {e}. Creating fresh state.")
            
    print("Creating fresh state for all apps...")
    return default_state

def save_state(state):
    """Saves the current state to the JSON file."""
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=4)
        print("State saved.")
    except Exception as e:
        print(f"Save failed: {e}")

# --- SLACK ---
def send_to_slack(message):
    """Sends a message to the configured Slack webhook."""
    if "YOUR_SLACK_WEBHOOK_URL_HERE" in SLACK_WEBHOOK_URL:
        print(f"[SLACK PREVIEW] {message}")
        return
    try:
        requests.post(SLACK_WEBHOOK_URL, json={"text": message}, timeout=10)
        print("Sent notification to Slack.")
    except Exception as e:
        print(f"Slack error: {e}")

# --- SCRAPING ---
def get_counts(driver, url):
    """Scrapes the 1-star and 2-star review counts from the app's main page."""
    try:
        driver.get(url)
        # Wait for review counts element to be present (part of the summary section)
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, 'a[href*="ratings"]')))
        time.sleep(3) # Give extra time for JS to render counts
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        c1 = c2 = 0
        
        # Iterate over 1 and 2 star ratings
        for r in ['1', '2']:
            # Select the link that filters by the specific star rating
            link = soup.select_one(f'a[href*="ratings%5B%5D={r}"]')
            if link:
                # The count is usually in a span inside the link
                span = link.select_one('span')
                if span:
                    txt = span.get_text(strip=True).upper().replace(',', '')
                    # Handle 'K' (thousands) in counts
                    if 'K' in txt:
                        val = int(float(txt.replace('K', '')) * 1000)
                    else:
                        val = int(txt)
                        
                    if r == '1': c1 = val
                    else: c2 = val
                    
        return c1, c2
    except Exception as e:
        print(f"Count error for {url}: {e}")
        return None, None

def get_new_reviews(driver, url, last_id):
    """Scrapes new reviews for a specific star rating (1 or 2)."""
    try:
        # Navigate to the filtered, newest-first review page
        driver.get(url)
        # Wait for a review content element to appear
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-review-content-id]")))
        time.sleep(5) # Allow the page to fully load and render reviews
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        reviews = []
        # Select all review blocks
        elements = soup.select("div[data-review-content-id]")
        
        if not elements:
            return [], None
            
        # The ID of the newest review on this page
        newest_id_on_page = elements[0].get('data-review-content-id')
        
        for el in elements:
            rid = el.get('data-review-content-id')
            # Stop once we hit a review we've already processed
            if rid == last_id: 
                break
            
            # Scrape details
            # Author can be in h3 or span with title attribute
            author = el.select_one('span[title]') or el.select_one('h3')
            author = author.get('title', 'Unknown Store') if author else "Unknown Store"
            
            # Date can be in tw-text-body-xs or time tag
            date_el = el.select_one('.tw-text-body-xs') or el.select_one('time')
            date = date_el.get_text(strip=True) if date_el else "Unknown Date"
            
            # The link to the review itself is constructed using the review ID
            link = f"https://apps.shopify.com/reviews/{rid}"
            
            reviews.append({"id": rid, "author": author, "date": date, "link": link})
        
        # New reviews are scraped from newest to oldest, so reverse the list for proper alerting order
        return list(reversed(reviews)), newest_id_on_page
        
    except Exception as e:
        print(f"Review scraping error for {url}: {e}")
        return [], None

# --- MAIN EXECUTION ---
def main():
    print("Multi-App Monitor: 12 Apps")
    state = load_state()

    # Create a deep copy of the state to track changes safely
    new_state = {key: val.copy() for key, val in state.items()}

    driver = init_driver()
    if not driver:
        send_to_slack("Driver failed to start! Cannot run monitoring.")
        return

    any_new = False
    try:
        for key, app in APPS.items():
            print(f"\nChecking: {app['name']}")
            
            # Step 1: Get current total counts
            c1, c2 = get_counts(driver, app["url"])
            if c1 is None:
                send_to_slack(f"⚠️ {app['name']} - Failed to load review counts.")
                continue

            # Update state with latest counts
            new_state[key]["1_star"] = c1
            new_state[key]["2_star"] = c2

            # --- Check 1-star reviews ---
            if c1 > state[key]["1_star"]:
                any_new = True
                print(f"Found new 1-star count: {c1} (was {state[key]['1_star']}). Checking individual reviews...")
                url = f"{app['url']}/reviews?ratings%5B%5D=1&sort_by=newest"
                
                # Get the new reviews and the ID of the newest one
                reviews, nid = get_new_reviews(driver, url, state[key]["last_1_id"])
                
                # Only update the last ID if we successfully got one
                if nid: 
                    # FIX: Corrected from 'fallout' to 'nid'
                    new_state[key]["last_1_id"] = nid
                    
                for r in reviews:
                    msg = (
                        f"🚨 *New 1-Star Review Found!* 🚨\n"
                        f"*App:* {app['name']}\n"
                        f"*Store:* {r['author']}\n"
                        f"*Date:* {r['date']}\n"
                        f"*Review Link:* <{r['link']}|View Review>"
                    )
                    send_to_slack(msg)

            # --- Check 2-star reviews ---
            if c2 > state[key]["2_star"]:
                any_new = True
                print(f"Found new 2-star count: {c2} (was {state[key]['2_star']}). Checking individual reviews...")
                url = f"{app['url']}/reviews?ratings%5B%5D=2&sort_by=newest"
                
                # Get the new reviews and the ID of the newest one
                reviews, nid = get_new_reviews(driver, url, state[key]["last_2_id"])
                
                # Only update the last ID if we successfully got one
                if nid: 
                    # FIX: Corrected from 'fallout' to 'nid'
                    new_state[key]["last_2_id"] = nid
                    
                for r in reviews:
                    msg = (
                        f"🟡 *New 2-Star Review Found!* 🟡\n"
                        f"*App:* {app['name']}\n"
                        f"*Store:* {r['author']}\n"
                        f"*Date:* {r['date']}\n"
                        f"*Review Link:* <{r['link']}|View Review>"
                    )
                    send_to_slack(msg)

        if not any_new:
            send_to_slack("✅ All 12 apps checked. No new 1/2-star reviews found. (Monitor Heartbeat)")

        # Step 2: Save the updated state
        save_state(new_state)

    except Exception as e:
        print(f"An unexpected error occurred in main loop: {e}")
        send_to_slack(f"❌ Monitor failed with an unexpected error: {e}")

    finally:
        if driver:
            driver.quit()
        print("Monitor Finished")

if __name__ == "__main__":
    main()
