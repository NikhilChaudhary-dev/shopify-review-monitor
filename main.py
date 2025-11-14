import os
import sys
import json
import time
import requests
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup

# YE LINE ADD KI HAI (sirf yahi)
from webdriver_manager.chrome import ChromeDriverManager

# --- Configuration ---
APP_URL = "https://apps.shopify.com/subscription-payments"
STATE_FILE = Path("review_state.json")

# YE LINE SABSE ZAROORI HAI
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "YOUR_SLACK_WEBHOOK_URL_HERE")

def init_driver():
    print("Initializing browser driver...")
    driver = None
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

    try:
        # Attempt 1: Manual driver (local)
        manual_driver_path = Path(os.getcwd()) / "chromedriver.exe"
        print(f"Attempt 1: Trying manual driver path: {manual_driver_path}")
        
        if manual_driver_path.exists():
            service = Service(executable_path=str(manual_driver_path))
            print("Driver Service created from manual path.")
            driver = webdriver.Chrome(service=service, options=options)
            print("webdriver.Chrome() successfully called (Manual Path).")
        else:
            # Attempt 2: webdriver_manager (GitHub Actions)
            print("Manual driver not found. Trying webdriver-manager...")
            service = Service(ChromeDriverManager().install())
            print("Driver Service created from webdriver-manager.")
            driver = webdriver.Chrome(service=service, options=options)
            print("webdriver.Chrome() successfully called (webdriver-manager).")

        print("Browser driver is ready.")
        return driver

    except Exception as e:
        print(f"Failed to start driver: {e}")
        return None

def load_state():
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            print("Error reading state file. Starting fresh.")
    
    return {
        "1_star_count": 0,
        "2_star_count": 0,
        "last_1_star_id": None,
        "last_2_star_id": None
    }

def save_state(state):
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=4)
        print("New state saved: review_state.json")
    except Exception as e:
        print(f"Error saving state file: {e}")

def send_to_slack(message):
    if "YOUR_SLACK_WEBHOOK_URL_HERE" in SLACK_WEBHOOK_URL:
        print("Slack Webhook URL configured nahi hai. Notification skip kar raha hoon.")
        return
    
    try:
        payload = {"text": message}
        response = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        if response.status_code == 200:
            print("Successfully sent notification to Slack.")
        else:
            print(f"Error sending message to Slack: {response.status_code} {response.text}")
    except Exception as e:
        print(f"Exception while sending to Slack: {e}")

def get_review_counts(driver, url):
    print(f"Fetching review counts from: {url}")
    try:
        driver.get(url)
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'a[aria-label*="total reviews"]'))
        )
        time.sleep(3)

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        counts = {'1': 0, '2': 0}

        for rating in ['1', '2']:
            link_element = soup.select_one(f'a[href*="ratings%5B%5D={rating}"]')
            if link_element:
                count_element = link_element.select_one('span.link-block--underline')
                if count_element:
                    count_text = count_element.get_text(strip=True)
                    if 'K' in count_text:
                        count = int(float(count_text.replace('K', '')) * 1000)
                    else:
                        count = int(count_text)
                    counts[rating] = count

        print(f"Current counts: 1-star={counts['1']}, 2-star={counts['2']}")
        return counts['1'], counts['2']

    except TimeoutException:
        print("Timed out waiting for review counts to load.")
        return None, None
    except Exception as e:
        print(f"Error scraping review counts: {e}")
        return None, None

def get_new_reviews(driver, url, last_known_id):
    print(f"Checking for new reviews on: {url}")
    new_reviews = []
    try:
        driver.get(url)
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-review-content-id]"))
        )
        time.sleep(7)

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        review_elements = soup.select("div[data-review-content-id]")

        if not review_elements:
            print("No review elements found on page.")
            return [], None

        first_review_id_on_page = review_elements[0].get('data-review-content-id')

        for element in review_elements:
            review_id = element.get('data-review-content-id')
            if review_id == last_known_id:
                print(f"Found last known review ID ({last_known_id}). Stopping search.")
                break

            author = "N/A"
            author_element = element.select_one('span[title]')
            if author_element:
                author = author_element.get('title', 'N/A').strip()

            date = "N/A"
            date_block = element.select_one('.lg\\:tw-col-span-3')
            if date_block:
                date_element = date_block.select_one('.tw-text-body-xs.tw-text-fg-tertiary')
                if date_element:
                    date = date_element.get_text(strip=True)

            text = "N/A"
            text_element = element.select_one('div[data-truncate-content-copy] p')
            if text_element:
                text = text_element.get_text(strip=True)

            review = {
                "id": review_id,
                "author": author,
                "date": date,
                "text": text
            }
            new_reviews.append(review)

        return list(reversed(new_reviews)), first_review_id_on_page

    except Exception as e:
        print(f"Error scraping new reviews: {e}")
        return [], None

def main():
    print("--- Shopify Review Monitor Started ---")
    state = load_state()
    print(f"Old state loaded: {state}")
    new_state = state.copy()
    has_new_reviews = False

    driver = init_driver()
    if not driver:
        print("Driver failed to initialize. Exiting script.")
        sys.exit(1)

    try:
        current_1_star_count, current_2_star_count = get_review_counts(driver, APP_URL)
        if current_1_star_count is None:
            print("Could not fetch review counts. Exiting.")
            return

        new_state["1_star_count"] = current_1_star_count
        new_state["2_star_count"] = current_2_star_count

        # 1-Star
        if current_1_star_count > state["1_star_count"]:
            print(f"New 1-star review count ({current_1_star_count}) > old count ({state['1_star_count']}). Checking...")
            has_new_reviews = True
            review_url_1 = f"{APP_URL}/reviews?ratings%5B%5D=1&sort_by=newest"
            reviews, newest_id = get_new_reviews(driver, review_url_1, state["last_1_star_id"])
            if newest_id:
                new_state["last_1_star_id"] = newest_id
            for review in reviews:
                message = (
                    f"*New 1-Star Negative Review (App: Recharge Subscription)*\n\n"
                    f"*Author:* {review['author']}\n"
                    f"*Date:* {review['date']}\n"
                    f"*Link:* https://apps.shopify.com/reviews/{review['id']}"
                )
                send_to_slack(message)

        # 2-Star
        if current_2_star_count > state["2_star_count"]:
            print(f"New 2-star review count ({current_2_star_count}) > old count ({state['2_star_count']}). Checking...")
            has_new_reviews = True
            review_url_2 = f"{APP_URL}/reviews?ratings%5B%5D=2&sort_by=newest"
            reviews, newest_id = get_new_reviews(driver, review_url_2, state["last_2_star_id"])
            if newest_id:
                new_state["last_2_star_id"] = newest_id
            for review in reviews:
                message = (
                    f"*New 2-Star Negative Review (App: Recharge Subscription)*\n\n"
                    f"*Author:* {review['author']}\n"
                    f"*Date:* {review['date']}\n"
                    f"*Link:* https://apps.shopify.com/reviews/{review['id']}"
                )
                send_to_slack(message)

        # HEARTBEAT
        if not has_new_reviews:
            print("No new 1 or 2-star reviews found.")
            send_to_slack("Shopify Monitor ran successfully. No new negative reviews found. (Heartbeat)")

        save_state(new_state)

    except Exception as e:
        print(f"An unexpected error occurred in main loop: {e}")
        send_to_slack(f"Shopify Monitor script failed with error: {e}")
    finally:
        if driver:
            driver.quit()
        print("--- Script Finished ---")

if __name__ == "__main__":
    main()
