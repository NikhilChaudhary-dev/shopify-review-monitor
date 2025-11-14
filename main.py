import json
import os
import time
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
# Added webdriver_manager back, required for GitHub Actions.
from webdriver_manager.chrome import ChromeDriverManager 

# --- CONFIGURATION (You may need to edit this) ---

# The app to track
APP_URL_MAIN = "https://apps.shopify.com/subscription-payments"

# Direct links to 1-star and 2-star reviews (sorted by newest)
APP_URL_1_STAR = "https://apps.shopify.com/subscription-payments/reviews?ratings%5B%5D=1&sort_by=newest"
APP_URL_2_STAR = "https://apps.shopify.com/subscription-payments/reviews?ratings%5B%5D=2&sort_by=newest"

# Paste your Slack Webhook URL here
# Tutorial: https://api.slack.com/messaging/webhooks
# FOR GITHUB ACTIONS: We will read this from an environment variable
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "Secrt_url") # <-- EDIT THIS

# State file name (will store previous data)
STATE_FILE = "review_state.json"

# --- END OF CONFIGURATION ---


def init_driver():
    """Initializes a headless Chrome browser (for GitHub Actions)"""
    print("Initializing browser driver...")
    options = Options()
    options.add_argument("--headless")  # Runs the browser in the background
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    
    try:
        # --- ATTEMPT 1: MANUAL LOCAL DRIVER ---
        # (For local testing when webdriver-manager fails)
        # This path points to chromedriver.exe in your project folder
        DRIVER_PATH = r"C:\Users\Admin\Desktop\NEG\chromedriver.exe"
        print(f"Attempt 1: Trying manual driver path: {DRIVER_PATH}")
        
        if os.path.exists(DRIVER_PATH):
            s = Service(DRIVER_PATH)
            print("Driver Service created from manual path.")
            driver = webdriver.Chrome(service=s, options=options)
            print("webdriver.Chrome() successfully called (Manual Path).")
        else:
            # --- ATTEMPT 2: WEBDRIVER-MANAGER ---
            # (This will be used by GitHub Actions or if manual fails)
            print("Manual driver not found. Trying webdriver-manager...")
            driver_path_auto = ChromeDriverManager().install()
            print(f"Driver path found by manager: {driver_path_auto}")
            
            s_auto = Service(driver_path_auto)
            print("Driver Service created (Auto Path).")
            
            driver = webdriver.Chrome(service=s_auto, options=options)
            print("webdriver.Chrome() successfully called (Auto Path).")

    except Exception as e:
        print(f"Failed to start driver: {e}")
        return None
        
    driver.set_window_size(1920, 1080)
    print("Browser driver is ready.")
    return driver


def load_state():
    """Loads the previous state from the state file"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            print("State file is corrupt. Creating a new state.")
    
    # Default state if file is not found
    return {
        "1_star_count": 0,
        "2_star_count": 0,
        "last_1_star_id": None,  # ID of the newest 1-star review
        "last_2_star_id": None   # ID of the newest 2-star review
    }


def save_state(state):
    """Saves the new state to the file"""
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=4)
    print(f"New state saved: {STATE_FILE}")


def send_to_slack(message):
    """Sends a notification to Slack"""
    # Check if the URL is set or is still the default value
    if not SLACK_WEBHOOK_URL or "YOUR_SLACK_WEBHOOK_URL_HERE" in SLACK_WEBHOOK_URL:
        print("SLACK_WEBHOOK_URL is not set. Skipping Slack notification.")
        print("NOTE: If running on GitHub Actions, ensure the 'SLACK_WEBHOOK_URL' secret is set.")
        print(f"The message was: {message}")
        return

    try:
        payload = {"text": message}
        response = requests.post(SLACK_WEBHOOK_URL, json=payload)
        if response.status_code != 200:
            print(f"Error sending message to Slack: {response.status_code}, {response.text}")
    except Exception as e:
        print(f"Error with Slack request: {e}")


def clean_review_count(count_str):
    """Converts a review count string (e.g., '1.7K' or '110') into a number"""
    count_str = count_str.strip().lower().replace(',', '')
    if 'k' in count_str:
        return int(float(count_str.replace('k', '')) * 1000)
    elif count_str.isdigit():
        return int(count_str)
    return 0


def get_review_counts(driver, url):
    """Fetches the 1-star and 2-star review counts from the main app page"""
    print(f"Fetching review counts from: {url}")
    driver.get(url)
    time.sleep(7)  # Allow time for the page to load (essential)
    
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    
    # These selectors depend on Shopify's layout. If they change, the script may fail.
    try:
        # 1-Star count
        # New selector (based on your provided HTML):
        selector_1_star = 'a[href*="ratings%5B%5D=1"] span.link-block--underline'
        count_1_element = soup.select_one(selector_1_star)
        count_1_str = count_1_element.text if count_1_element else "0"
        
        # 2-Star count
        # New selector (based on your provided HTML):
        selector_2_star = 'a[href*="ratings%5B%5D=2"] span.link-block--underline'
        count_2_element = soup.select_one(selector_2_star)
        count_2_str = count_2_element.text if count_2_element else "0"
        
        count_1 = clean_review_count(count_1_str)
        count_2 = clean_review_count(count_2_str)
        
        if count_1 == 0 and count_2 == 0 and not (count_1_element or count_2_element):
            print("WARNING: Review count selectors not found. Shopify page layout might have changed.")
            return None, None

        return count_1, count_2
        
    except Exception as e:
        print(f"Error parsing review counts: {e}")
        print("Page source (first 500 characters):", driver.page_source[:500])
        return None, None


def get_new_reviews(driver, url, last_known_id):
    """Fetches new reviews from the review list page"""
    print(f"Checking for new reviews at: {url}")
    driver.get(url)
    time.sleep(7)  # Allow time for the page to load
    
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    
    new_reviews = []
    
    # New selector (based on your HTML):
    # Each review is in a 'div' with a 'data-review-content-id' attribute
    all_review_elements = soup.select('div[data-review-content-id]')
    
    if not all_review_elements:
        print("WARNING: No review elements found. Check page layout.")
        return [], last_known_id # No new reviews found

    # The first one on the page (newest)
    new_latest_id = all_review_elements[0].get('data-review-content-id')

    if not new_latest_id:
            print("ERROR: Found first review element but it has no 'data-review-content-id'.")
            return [], last_known_id
    
    print(f"Newest ID found: {new_latest_id}. Old ID was: {last_known_id}")

    for review_el in all_review_elements:
        current_id = review_el.get('data-review-content-id')
        
        if not current_id:
            continue # Skip if the div has no ID attribute

        # Stop as soon as we find the old (last known) review
        if current_id == last_known_id:
            print("Found the last known review. Stopping here.")
            break
            
        # Extract details for the new review
        try:
            # Author (Store name) - from the 'title' attribute in your HTML
            author_el = review_el.select_one('span[title]')
            author = author_el.text.strip() if author_el else "Unknown Author"
            
            # Date (Inside the review content block)
            # We look for the date inside the 'lg:tw-order-2' (content block)
            content_block = review_el.select_one('.lg\\:tw-order-2') # Colon must be escaped in CSS
            if not content_block:
                content_block = review_el # Fallback
            
            date_el = content_block.select_one('.tw-text-body-xs.tw-text-fg-tertiary')
            date = date_el.text.strip() if date_el else "Unknown Date"
            
            # Review text
            review_body_container = review_el.select_one('div[data-truncate-content-copy]')
            full_text = "N/A"
            if review_body_container:
                full_text = ' '.join(p.text.strip() for p in review_body_container.find_all('p'))
            
            link = f"https://apps.shopify.com/reviews/{current_id}"
            
            new_reviews.append({
                "id": current_id,
                "author": author,
                "date": date,
                "text": full_text,
                "link": link
            })
        except Exception as e:
            print(f"Error parsing one review (ID: {current_id}): {e}")
            continue # Skip this review and move to the next

    # Return new reviews (oldest-new first)
    # And return the new "latest ID"
    return list(reversed(new_reviews)), new_latest_id


def main():
    print("--- Shopify Review Monitor Started ---")
    state = load_state()
    print(f"Old state loaded: {state}")
    
    driver = init_driver()
    if driver is None:
        print("Driver failed to initialize. Exiting script.")
        return

    try:
        # 1. Fetch new total counts
        current_1_star_count, current_2_star_count = get_review_counts(driver, APP_URL_MAIN)
        
        if current_1_star_count is None:
            print("Could not fetch counts. Exiting script.")
            send_to_slack("🚨 ERROR: Shopify Review Monitor script could not fetch counts. Check page layout.")
            return

        print(f"Current counts: 1-star={current_1_star_count}, 2-star={current_2_star_count}")
        
        new_state = state.copy()
        new_state["1_star_count"] = current_1_star_count
        new_state["2_star_count"] = current_2_star_count
        has_new_reviews = False

        # 2. Check 1-Star reviews
        if current_1_star_count > state["1_star_count"]:
            print(f"New 1-star reviews found! ({state['1_star_count']} -> {current_1_star_count})")
            has_new_reviews = True
            
            new_reviews, new_latest_id = get_new_reviews(driver, APP_URL_1_STAR, state["last_1_star_id"])
            
            if new_reviews:
                print(f"Sending {len(new_reviews)} new 1-star reviews to Slack...")
                new_state["last_1_star_id"] = new_latest_id # Update state
                for review in new_reviews:
                    message = (
                        f"🚨 *New 1-Star Negative Review (App: Recharge Subscription)* 🚨\n\n"
                        f"*Author:* {review['author']}\n"
                        f"*Date:* {review['date']}\n"
                        f"*Link:* {review['link']}"
                    )
                    send_to_slack(message)
                    time.sleep(1) # To avoid rate limits
            else:
                 # Count increased but no review found? This can happen if a review was deleted
                 # Or if this is the first run (last_known_id was None)
                 print("Count increased but no new reviews found in list (or first run). Setting new latest ID.")
                 if state["last_1_star_id"] is None and new_latest_id:
                     new_state["last_1_star_id"] = new_latest_id


        # 3. Check 2-Star reviews
        if current_2_star_count > state["2_star_count"]:
            print(f"New 2-star reviews found! ({state['2_star_count']} -> {current_2_star_count})")
            has_new_reviews = True

            new_reviews, new_latest_id = get_new_reviews(driver, APP_URL_2_STAR, state["last_2_star_id"])
            
            if new_reviews:
                print(f"Sending {len(new_reviews)} new 2-star reviews to Slack...")
                new_state["last_2_star_id"] = new_latest_id # Update state
                for review in new_reviews:
                    message = (
                        f"⚠️ *New 2-Star Negative Review (App: Recharge Subscription)* ⚠️\n\n"
                        f"*Author:* {review['author']}\n"
                        f"*Date:* {review['date']}\n"
                        f"*Link:* {review['link']}"
                    )
                    send_to_slack(message)
                    time.sleep(1)
            else:
                 print("Count increased but no new reviews found in list (or first run). Setting new latest ID.")
                 if state["last_2_star_id"] is None and new_latest_id:
                     new_state["last_2_star_id"] = new_latest_id

        if not has_new_reviews:
            print("No new 1 or 2-star reviews found.")

        # 4. Save the new state (even if no new reviews, to update counts)
        save_state(new_state)

    except Exception as e:
        print(f"A major error occurred in the script: {e}")
        import traceback
        traceback.print_exc()
        send_to_slack(f"🚨 FATAL ERROR: Shopify Review Monitor script failed! Error: {e}")
    
    finally:
        # 5. Close the browser
        if 'driver' in locals() and driver:
            driver.quit()
        print("--- Script Finished ---")

if __name__ == "__main__":
    main()
