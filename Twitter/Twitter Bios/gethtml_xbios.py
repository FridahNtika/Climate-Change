import os
import time
import json
import re
from datetime import datetime, timezone
from selenium import webdriver
from seleniumbase import SB
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
    ElementClickInterceptedException,
)
from selenium import webdriver  # (kept for type hints; not used to create the browser)

# === CONFIGURATION ===
INPUT_FILE = 'xAccounts.txt'  # one username per line
OUTPUT_DIR = 'profiles_html'
BASE_URL = 'https://twitter.com/'


def setup_driver():
    options = Options()
    # Keep visible like gethtml_SB.py (not headless)
    options.add_argument('--disable-blink-features=AutomationControlled')
    service = Service()
    driver = webdriver.Chrome(service=service, options=options)
    return driver

# ===============================
# human-like sleep & backoff
# ===============================
import random
import functools

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

# ===============================
# NEW: heartbeat sleeper (keeps session alive)
# ===============================
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

# ===============================
# Login helpers
# ===============================
from secrets2 import EMAIL, USERNAME, PASSWORD

def save_cookies(driver, filename):
    cookies = driver.get_cookies()
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(cookies, f, indent=2)
    print(f" Saved cookies to {filename}")

def load_cookies(driver, filename):
    driver.get("https://twitter.com/?lang=und")
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
    print(" Cookies loaded.")

def perform_login(driver):
    driver.get("https://twitter.com/login?lang=und")

    email_input = WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.NAME, "text"))
    )
    email_input.send_keys(EMAIL)
    email_input.send_keys(Keys.RETURN)

    try:
        verification_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.NAME, "text"))
        )
        print("Entering username for verification...")
        verification_input.send_keys(USERNAME)
        verification_input.send_keys(Keys.RETURN)
    except Exception:
        print("No extra verification step.")

    password_input = WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.NAME, "password"))
    )
    password_input.send_keys(PASSWORD)
    password_input.send_keys(Keys.RETURN)
    print(" Login successful!")
    sleep_with_heartbeat(driver, 5, tick=2)

    # ---------- account-aware helpers ----------
def clear_twitter_site_data(driver):
    """Fully clear session so we don't get auto-logged into a previous account."""
    try:
        driver.get("https://twitter.com/?lang=und")
    except Exception:
        pass
    try:
        driver.delete_all_cookies()
    except Exception:
        pass
    try:
        driver.execute_script("""
            try { window.localStorage.clear(); } catch (e) {}
            try { window.sessionStorage.clear(); } catch (e) {}
            try {
                if (window.indexedDB && indexedDB.databases) {
                    indexedDB.databases().then(dbs => dbs.forEach(db => {
                        try { indexedDB.deleteDatabase(db.name); } catch(e){}
                    }));
                }
            } catch (e) {}
        """)
    except Exception:
        pass
    try:
        driver.refresh()
    except Exception:
        pass
    sleep_with_heartbeat(driver, 2, tick=1)

def get_logged_in_handle(driver):
    """
    Try to read the current @handle from the 'Profile' link in the left rail.
    Returns lowercased handle without '@', or None if unknown/not logged in.
    """
    try:
        driver.get("https://twitter.com/home?lang=und")
        sleep_with_heartbeat(driver, 3, tick=1)
        a = driver.find_element(By.XPATH, "//a[@aria-label='Profile']")
        href = a.get_attribute("href") or ""
        handle = href.rstrip("/").split("/")[-1]
        if handle:
            return handle.lower()
    except Exception:
        pass
    return None

def is_logged_in_as(driver, expected_handle: str) -> bool:
    """
    True iff an account is logged in and the handle matches expected_handle (case-insensitive).
    expected_handle should be without '@'.
    """
    actual = get_logged_in_handle(driver)
    if actual:
        print(f"Detected logged-in handle: @{actual}")
    return (actual == (expected_handle or "").lower())

def fetch_profiles():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        usernames = [line.strip() for line in f if line.strip()]

    driver = setup_driver()

    for username in usernames:
        outfile = os.path.join(OUTPUT_DIR, f"{username}.html")
        if os.path.exists(outfile):
            print(f"[SKIP] {username} already downloaded.")
            continue

        url = f"{BASE_URL}{username}"
        print(f"[FETCHING] {url}")
        driver.get(url)
        time.sleep(5)  # wait for page to load

        html = driver.page_source
        with open(outfile, 'w', encoding='utf-8') as f:
            f.write(html)

        print(f"[SAVED] {outfile}")
        time.sleep(2)

    driver.quit()


if __name__ == '__main__':
    fetch_profiles()