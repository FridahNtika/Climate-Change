# Logging in from different accounts after editing secrets2.py
#Gets more tweets from the DOM
#Uses the datetime mode 

from seleniumbase import SB

from builtins import Exception, float
import re
import os
import time
import json
from datetime import datetime, timezone
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    StaleElementReferenceException,
    ElementClickInterceptedException,
)
from selenium import webdriver  # (kept for type hints; not used to create the browser)

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
# Transient error recovery
# ===============================
def try_recover_transient_error(driver, profile_url: str, wait_timeout: int = 10) -> bool:
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text.lower()
    except Exception:
        body_text = ""

    if ("something went wrong" in body_text) or ("try reloading" in body_text):
        print(" Detected 'Something went wrong'. Attempting recovery...")

        # 1) Click 'Retry' if present (doesn't reset scroll)
        try:
            retry_btn = driver.find_element(
                By.XPATH, '//span[normalize-space()="Retry"]/ancestor::div[@role="button"]'
            )
            retry_btn.click()
            human_sleep(4, 2)
            WebDriverWait(driver, wait_timeout).until(
                EC.presence_of_element_located((By.XPATH, '//div[@data-testid="primaryColumn"]'))
            )
            return True
        except NoSuchElementException:
            pass
        except Exception:
            pass

        # 2) Gentle wiggle instead of refresh (keeps position)
        try:
            driver.execute_script("window.scrollBy(0, -400);")
            human_sleep(2, 1)
            driver.execute_script("window.scrollBy(0, 800);")
            human_sleep(3, 1)
            return True
        except Exception:
            pass

        # 3) Last resort: refresh (may reset position)
        try:
            driver.refresh()
            human_sleep(5, 2)
            WebDriverWait(driver, wait_timeout).until(
                EC.presence_of_element_located((By.XPATH, '//div[@data-testid="primaryColumn"]'))
            )
            return True
        except Exception:
            return False

    return False

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

# ===============================
# Scraping helpers
# ===============================
_ABBREV_RE = re.compile(r"^\s*([\d.,]+)\s*([kKmM]?)\s+(posts|tweets)\s*$")

def _parse_abbrev_count(text: str) -> int:
    m = _ABBREV_RE.match(text.strip())
    if not m:
        raise ValueError(f"Unrecognized count text: {text!r}")
    num, suffix, _ = m.groups()
    num = float(num.replace(",", ""))
    if suffix.lower() == "k":
        num *= 1_000
    elif suffix.lower() == "m":
        num *= 1_000_000
    return int(num)

def get_total_posts_from_profile(driver, timeout=20):
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.XPATH, '//div[@data-testid="primaryColumn"]'))
    )

    candidates = driver.find_elements(
        By.XPATH,
        "//*[self::div or self::span]"
        "[contains(translate(normalize-space(.), 'POSTS', 'posts'), ' posts') "
        " or contains(translate(normalize-space(.), 'TWEETS', 'tweets'), ' tweets')]"
    )

    for el in candidates:
        txt = el.text.strip()
        if "See new posts" in txt:
            continue
        if _ABBREV_RE.match(txt):
            try:
                count = _parse_abbrev_count(txt)
                print(f"Detected total posts: {count} (from {txt!r})")
                return count
            except ValueError:
                continue

    doc_text = driver.find_element(By.TAG_NAME, "body").text
    for line in doc_text.splitlines():
        if _ABBREV_RE.match(line.strip()):
            return _parse_abbrev_count(line.strip())

    print("Could not determine total posts from profile header.")
    return None

# ===============================
# ORIGINAL language helpers
# ===============================
def _js_click(driver, el):
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    try:
        el.click()
    except Exception:
        driver.execute_script("arguments[0].click();", el)

def ensure_original_language(driver, tweet_article, timeout=0.6) -> bool:
    clicked = False
    try:
        btns = tweet_article.find_elements(By.XPATH, ".//span[normalize-space()='Show original']")
        if btns:
            btn = btns[0].find_element(By.XPATH, "./ancestor::*[@role='button' or @role='link'][1]")
            _js_click(driver, btn)
            time.sleep(0.15)
            clicked = True

        banner = tweet_article.find_elements(
            By.XPATH, ".//*[contains(., 'Auto-translated') or contains(., 'translated')]"
        )
        if banner:
            btns2 = tweet_article.find_elements(By.XPATH, ".//span[normalize-space()='Show original']")
            if btns2:
                btn2 = btns2[0].find_element(By.XPATH, "./ancestor::*[@role='button' or @role='link'][1]")
                _js_click(driver, btn2)
                time.sleep(0.1)
                clicked = True
    except Exception:
        pass
    return clicked

def expand_show_more(driver, tweet_article):
    try:
        btns = tweet_article.find_elements(
            By.XPATH, ".//span[normalize-space()='Show more']/ancestor::*[@role='button']"
        )
        if btns:
            _js_click(driver, btns[0])
            time.sleep(0.05)
    except Exception:
        pass

# ===============================
# NEW (Fix #1): Get the card's own permalink via the time anchor
# ===============================
def get_own_tweet_url(tweet_article):
    """
    Return this card's own permalink: the <a> that wraps <time>.
    This avoids grabbing quoted/embedded tweet links.
    """
    try:
        a = tweet_article.find_element(
            By.XPATH, './/a[contains(@href, "/status/") and .//time]'
        )
        return a.get_attribute("href")
    except NoSuchElementException:
        return None

# ===============================
# Disk resume
# ===============================
def _load_seen_from_disk(folder: str) -> set:
    seen = set()
    if not os.path.isdir(folder):
        return seen
    for name in os.listdir(folder):
        if name.startswith("tweet_") and name.endswith(".meta.json"):
            try:
                with open(os.path.join(folder, name), "r", encoding="utf-8") as f:
                    meta = json.load(f)
                    url = meta.get("tweet_url")
                    if url:
                        seen.add(url)
            except Exception:
                continue
    return seen

# ===============================
# Core: save tweets for one profile
# ===============================
def save_tweets_for_profile(
    driver,
    profile_url,
    profile_name,
    expected_total_tweets=None,
    target_fraction=2/3,
    stall_limit=8,
    pause_seconds_on_stall=20,
    base_run_dir="tweets_html",  # parent directory for this run (date-stamped)
    run_stamp="unknown"          # included in meta
):
    print(f"Navigating to profile: {profile_url}")
    safe_get(driver, profile_url)

    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.XPATH, '//div[@data-testid="primaryColumn"]'))
    )

    try_recover_transient_error(driver, profile_url)

    # date-stamped folder structure
    folder = os.path.join(base_run_dir, profile_name)
    os.makedirs(folder, exist_ok=True)

    seen_tweet_urls = _load_seen_from_disk(folder)
    if seen_tweet_urls:
        print(f" Preloaded {len(seen_tweet_urls)} previously saved tweets for resume.")

    target_count = None
    if expected_total_tweets:
        target_count = max(1, int(expected_total_tweets * target_fraction))
        print(f" Targeting {target_count} tweets (~{int(target_fraction*100)}% of {expected_total_tweets}).")

    # ====== Fix #2: stronger anti-stall / scrolling ======
    max_scroll_attempts = 300                      # was 100
    effective_stall_limit = max(stall_limit, 12)   # was 8
    effective_pause_on_stall = max(pause_seconds_on_stall, 30)
    step_pixels = 1800

    scroll_attempts = 0
    consecutive_stalls = 0
    last_bottom_url = None

    while True:
        time.sleep(4)

        if try_recover_transient_error(driver, profile_url):
            human_sleep(3, 1)

        # login wall guard
        try:
            driver.find_element(By.XPATH, "//span[contains(text(), \"Don’t miss what’s happening\")]")
            print(" Hit the signup/login wall. Stopping scrolling.")
            break
        except NoSuchElementException:
            pass

        # collect currently loaded tweets
        try:
            tweet_elements = driver.find_elements(By.XPATH, '//article[@data-testid="tweet"]')
        except Exception:
            tweet_elements = []
        print(f"FOUND {len(tweet_elements)} tweets currently loaded in DOM.")

        new_tweets_found = False

        for tweet in tweet_elements:
            try:
                # Skip sponsored
                try:
                    ad_label = tweet.find_element(By.XPATH, ".//span[text()='Ad']")
                    if ad_label:
                        continue
                except NoSuchElementException:
                    pass

                # ORIGINAL language patches
                try:
                    ensure_original_language(driver, tweet)
                    expand_show_more(driver, tweet)
                except Exception:
                    pass

                # ====== Fix #1: use the card's own permalink ======
                tweet_url = get_own_tweet_url(tweet)

                # Fallback (rare)
                if not tweet_url:
                    try:
                        tweet_url = tweet.find_element(
                            By.XPATH,
                            f'.//a[contains(@href, "/{profile_name}/status/")]'
                        ).get_attribute("href")
                    except Exception:
                        continue

                if tweet_url and tweet_url not in seen_tweet_urls:
                    seen_tweet_urls.add(tweet_url)

                    tweet_id = tweet_url.split("/")[-1]
                    html_path = os.path.join(folder, f"tweet_{tweet_id}.html")
                    meta_path = os.path.join(folder, f"tweet_{tweet_id}.meta.json")

                    html = tweet.get_attribute("outerHTML")

                    with open(html_path, "w", encoding="utf-8") as f:
                        f.write(html)

                    # richer meta with timestamp + run stamp
                    meta = {
                        "tweet_url": tweet_url,
                        "collected_at": datetime.now(timezone.utc).isoformat(),
                        "run_stamp": run_stamp
                    }
                    with open(meta_path, "w", encoding="utf-8") as f:
                        json.dump(meta, f, indent=2)

                    print(f"SAVED: {tweet_url}")
                    new_tweets_found = True

            except Exception:
                continue

        if target_count and len(seen_tweet_urls) >= target_count:
            print(f" Reached target of {target_count} tweets for {profile_name}.")
            break

        # compute the bottom-most tweet url to detect movement
        bottom_links = []
        for t in tweet_elements:
            try:
                u = get_own_tweet_url(t)
                if u:
                    bottom_links.append(u)
            except Exception:
                pass
        current_bottom = bottom_links[-1] if bottom_links else None

        if new_tweets_found:
            scroll_attempts = 0
            consecutive_stalls = 0
        else:
            scroll_attempts += 1
            consecutive_stalls += 1

        if consecutive_stalls >= effective_stall_limit:
            print(f" Stalled {consecutive_stalls} cycles — pausing {effective_pause_on_stall}s to let new content load...")
            sleep_with_heartbeat(driver, effective_pause_on_stall, tick=10)
            try:
                driver.execute_script("window.scrollBy(0, -600);")
                human_sleep(2, 1)
                driver.execute_script("window.scrollBy(0, 1200);")
            except Exception:
                pass
            consecutive_stalls = 0
            last_bottom_url = None  # reset bottom-tracking after stall pause
            continue

        if scroll_attempts >= max_scroll_attempts:
            print(f" No new tweets after {max_scroll_attempts} scroll attempts. Stopping.")
            break

        # ====== smarter scroll & movement detection ======
        try:
            prev_h = driver.execute_script("return document.documentElement.scrollHeight")
        except Exception:
            prev_h = None

        try:
            driver.execute_script("window.scrollBy(0, arguments[0]);", step_pixels)
        except Exception:
            pass

        human_sleep(1.2, 0.6)

        try:
            new_h = driver.execute_script("return document.documentElement.scrollHeight")
        except Exception:
            new_h = None

        height_changed = (prev_h is not None and new_h is not None and new_h > prev_h)
        bottom_changed = (current_bottom is not None and current_bottom != last_bottom_url)

        if not height_changed and not bottom_changed:
            # stronger nudge
            try:
                driver.find_element(By.TAG_NAME, "body").send_keys(Keys.END)
            except Exception:
                pass
            human_sleep(1.2, 0.6)

        last_bottom_url = current_bottom

        # end-of-timeline detection
        try:
            driver.find_element(By.XPATH, '//div[@data-testid="emptyState"]')
            print(" Reached end of timeline.")
            break
        except NoSuchElementException:
            pass

    print(f" SCRAPED {len(seen_tweet_urls)} TWEETS FOR {profile_name}")

print("Sleeping 10 seconds before next account...")
def _startup_pause(driver):
    sleep_with_heartbeat(driver, 10, tick=5)

# ===============================
# MAIN
# ===============================
def save_tweet_htmls():
    # Read accounts to scrape (targets)
    with open("accounts3.txt", encoding="utf-8") as f:
        accounts = [line.strip() for line in f if line.strip()]
        print("Accounts to scrape:", accounts)

    # --- date-stamped run directory ---
    # You can override the stamp with:  RUN_STAMP=2025-10-19 python gethtml_SB_minimal.py
    RUN_STAMP = os.environ.get("RUN_STAMP") or time.strftime("%Y-%m-%d")
    RUN_DIR = os.path.join("tweets_html", RUN_STAMP)
    os.makedirs(RUN_DIR, exist_ok=True)
    print(f"Run directory: {RUN_DIR}")

    # ========= Launch the browser with SeleniumBase =========
    with SB(uc=True, headless=False, locale_code="en") as sb:
        driver = sb.driver
        sb.set_window_size(1280, 900)

        # --- derive per-account cookie file from secrets2 ---
        account_handle = USERNAME.strip().lstrip("@").lower()
        cookies_file = f"twitter_cookies_{account_handle}.json"  # per-account cookie jar
        print(f"Using cookie jar: {cookies_file}")

        # --- cookie / login flow (account-aware) ---
        try:
            if os.path.exists(cookies_file):
                load_cookies(driver, cookies_file)
                if is_logged_in_as(driver, account_handle):
                    print(f"Proceeding with cookies for @{account_handle}.")
                else:
                    print("Cookie account mismatch or not logged in. Clearing and logging in fresh...")
                    clear_twitter_site_data(driver)
                    perform_login(driver)
                    if not is_logged_in_as(driver, account_handle):
                        raise RuntimeError("Logged into a different account than secrets2.USERNAME.")
                    save_cookies(driver, cookies_file)
            else:
                print("No cookies found for this account. Logging in automatically...")
                clear_twitter_site_data(driver)  # start clean
                perform_login(driver)
                if not is_logged_in_as(driver, account_handle):
                    raise RuntimeError("Logged into a different account than secrets2.USERNAME.")
                save_cookies(driver, cookies_file)
        except Exception as e:
            print(f"[login] error: {e}. Will attempt a fresh login once more.")
            try:
                clear_twitter_site_data(driver)
                perform_login(driver)
                if not is_logged_in_as(driver, account_handle):
                    raise RuntimeError("Logged into a different account than secrets2.USERNAME.")
                save_cookies(driver, cookies_file)
            except Exception as ee:
                print(f"[login] failed again: {ee}. Exiting early to avoid loop.")
                return

        # --- scrape accounts (robust loop) ---
        for account in accounts:
            print("\n==========")
            print(f"Starting to scrape account: {account}")
            profile_url = f"https://twitter.com/{account}?lang=und"

            _startup_pause(driver)

            try:
                safe_get(driver, profile_url)
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, '//div[@data-testid="primaryColumn"]'))
                )

                total_posts = get_total_posts_from_profile(driver)

                save_tweets_for_profile(
                    driver,
                    profile_url,
                    account,
                    expected_total_tweets=total_posts,
                    target_fraction=2/3,
                    stall_limit=8,               # original input; function ups this to >=12 internally
                    pause_seconds_on_stall=20,   # original input; function ups this to >=30 internally
                    base_run_dir=RUN_DIR,        # date-stamped parent dir
                    run_stamp=RUN_STAMP          # stamp into meta
                )

            except Exception as e:
                print(f"[{account}] encountered error: {e}")
                print(" Pausing 60s (heartbeat) and then resuming with next attempt/account...")
                sleep_with_heartbeat(driver, 60, tick=10)

        print(" All accounts processed. (Browser will close now when exiting the 'with' block.)")

if __name__ == "__main__":
    save_tweet_htmls()






















































































































