import os
import time
import json
import random
import functools
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    StaleElementReferenceException,
)

# === CONFIGURATION ===
INPUT_FILE = 'profiles.txt'  # one username per line
OUTPUT_DIR = 'fb_profiles_html'
BASE_URL = 'https://www.facebook.com/'

# === CREDENTIALS ===
# secrets.py file with your Facebook credentials:
from secrets import FB_EMAIL, FB_PASSWORD


def setup_driver():
    options = Options()
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    service = Service()
    driver = webdriver.Chrome(service=service, options=options)
    return driver


def human_sleep(base: float = 5.0, jitter: float = 2.0):
    """Sleep for base ± jitter seconds (minimum 0.5s)."""
    delay = base + random.uniform(-jitter, jitter)
    if delay < 0.5:
        delay = 0.5
    time.sleep(delay)


def retry_with_backoff(max_tries=5, base_delay=2.0, max_delay=60.0):
    """Decorator for exponential backoff with jitter."""
    def deco(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            attempt = 0
            while True:
                try:
                    return f(*args, **kwargs)
                except Exception as e:
                    attempt += 1
                    if attempt >= max_tries:
                        raise
                    jitter = random.uniform(0, 1.0)
                    delay = min(max_delay, base_delay * (2 ** (attempt - 1)) + jitter)
                    print(f"[backoff] attempt {attempt}/{max_tries} failed: {e}. sleeping {delay:.1f}s")
                    time.sleep(delay)
        return wrapper
    return deco


@retry_with_backoff(max_tries=4, base_delay=3.0, max_delay=45.0)
def safe_get(driver, url: str):
    """driver.get with retries/backoff."""
    driver.get(url)


def sleep_with_heartbeat(driver, total_seconds: int, tick: int = 15):
    """
    Sleep in short chunks while pinging the browser to prevent teardown
    by any watchdogs / inactivity timeouts.
    """
    remaining = max(0, int(total_seconds))
    while remaining > 0:
        chunk = min(tick, remaining)
        time.sleep(chunk)
        remaining -= chunk
        try:
            driver.execute_script("return 1")  # harmless ping
        except Exception:
            pass


def save_cookies(driver, filename):
    cookies = driver.get_cookies()
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(cookies, f, indent=2)
    print(f"✓ Saved cookies to {filename}")


def load_cookies(driver, filename):
    driver.get("https://www.facebook.com")
    try:
        driver.delete_all_cookies()
    except Exception:
        pass
    with open(filename, "r", encoding="utf-8") as f:
        cookies = json.load(f)
    for cookie in cookies:
        if cookie.get("domain", "").startswith("."):
            cookie["domain"] = cookie["domain"].lstrip(".")
        try:
            driver.add_cookie(cookie)
        except Exception:
            continue
    driver.refresh()
    sleep_with_heartbeat(driver, 5, tick=2)
    print("✓ Cookies loaded.")


def perform_login(driver):
    """
    Logs into Facebook and waits for manual CAPTCHA completion.
    """
    driver.get("https://www.facebook.com/login")
    time.sleep(3)

    try:
        # Enter email
        email_input = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.ID, "email"))
        )
        email_input.clear()
        email_input.send_keys(FB_EMAIL)
        time.sleep(1)

        # Enter password
        password_input = driver.find_element(By.ID, "pass")
        password_input.clear()
        password_input.send_keys(FB_PASSWORD)
        time.sleep(1)

        # Click login button
        login_button = driver.find_element(By.NAME, "login")
        login_button.click()
        
        print("✓ Login credentials submitted.")
        print("⏳ Waiting 30 seconds for you to complete any CAPTCHA manually...")
        print("   Please solve the CAPTCHA in the browser window if it appears.")
        
        # Wait for manual CAPTCHA completion
        time.sleep(30)
        
        print("✓ Login process complete!")
        sleep_with_heartbeat(driver, 5, tick=2)
        
    except Exception as e:
        print(f"[ERROR] Login failed: {e}")
        raise


def extract_username_from_url(url_or_username):
    """
    Extract username from Facebook URL or return as-is if already a username.
    Examples:
        'https://www.facebook.com/ndaba.gaolathe' -> 'ndaba.gaolathe'
        'facebook.com/wynter.mmolotsi' -> 'wynter.mmolotsi'
        'dumelangsaleshandoHE' -> 'dumelangsaleshandoHE'
    """
    text = url_or_username.strip()
    
    # Remove protocol
    if text.startswith('http://') or text.startswith('https://'):
        text = text.split('://', 1)[1]
    
    # Remove facebook.com domain
    if text.startswith('www.facebook.com/'):
        text = text.replace('www.facebook.com/', '', 1)
    elif text.startswith('facebook.com/'):
        text = text.replace('facebook.com/', '', 1)
    elif text.startswith('m.facebook.com/'):
        text = text.replace('m.facebook.com/', '', 1)
    
    # Remove trailing slashes and query parameters
    text = text.rstrip('/')
    if '?' in text:
        text = text.split('?')[0]
    
    return text


def fetch_profiles():
    """
    Main function to fetch Facebook profile HTMLs.
    """
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    # Read URLs/usernames from file
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        lines = [line.strip() for line in f if line.strip()]
    
    # Extract usernames from URLs
    usernames = [extract_username_from_url(line) for line in lines]

    print(f"[INFO] Found {len(usernames)} profiles to fetch.")

    driver = setup_driver()
    
    try:
        # Check if cookies exist
        cookie_file = 'fb_cookies.json'
        if os.path.exists(cookie_file):
            print("[INFO] Loading saved cookies...")
            try:
                load_cookies(driver, cookie_file)
                # Verify we're still logged in
                driver.get("https://www.facebook.com")
                time.sleep(3)
                # Quick check if logged in (look for home page elements)
                if "login" in driver.current_url.lower():
                    raise Exception("Cookies expired, need to re-login")
                print("✓ Successfully logged in with cookies")
            except Exception as e:
                print(f"[INFO] Cookies invalid or expired: {e}")
                print("[INFO] Performing fresh login...")
                perform_login(driver)
                save_cookies(driver, cookie_file)
        else:
            print("[INFO] No saved cookies found. Performing login...")
            perform_login(driver)
            save_cookies(driver, cookie_file)

        # Fetch each profile
        for idx, username in enumerate(usernames, 1):
            print(f"\n[{idx}/{len(usernames)}] Processing: {username}")
            
            # Create user-specific directory
            user_dir = os.path.join(OUTPUT_DIR, username)
            if not os.path.exists(user_dir):
                os.makedirs(user_dir)
            
            outfile = os.path.join(user_dir, f"{username}.html")
            
            if os.path.exists(outfile):
                print(f"  [SKIP] {username} already downloaded.")
                continue

            url = f"{BASE_URL}{username}"
            print(f"  [FETCHING] {url}")
            
            try:
                safe_get(driver, url)
                
                # Wait for page to load
                time.sleep(5)
                
                # Scroll to load dynamic content
                driver.execute_script("window.scrollTo(0, 800);")
                time.sleep(2)
                driver.execute_script("window.scrollTo(0, 0);")
                time.sleep(2)

                # Save HTML
                html = driver.page_source
                with open(outfile, 'w', encoding='utf-8') as f:
                    f.write(html)

                print(f"  ✓ [SAVED] {outfile}")
                
                # Random delay between profiles to avoid rate limiting
                human_sleep(base=3.0, jitter=2.0)
                
            except Exception as e:
                print(f"  [ERROR] Failed to fetch {username}: {e}")
                continue

    finally:
        print("\n[INFO] Closing browser...")
        driver.quit()
        print("✓ Done!")


if __name__ == '__main__':
    fetch_profiles()
