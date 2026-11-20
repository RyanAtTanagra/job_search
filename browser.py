import os
import resource
import logging
from time import sleep
from urllib.parse import urlparse

from seleniumbase import Driver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.actions.wheel_input import ScrollOrigin
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException


def setup_ulimits(limit=2048):
    """Increase file descriptor limit for sites that return many jobs."""
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE, (limit, hard))


def _clean_profile_locks(user_data_dir):
    """Remove stale Chrome lock files that prevent the browser from navigating."""
    expanded = os.path.expanduser(user_data_dir)
    for lock_file in ["SingletonLock", "SingletonSocket", "SingletonCookie"]:
        path = os.path.join(expanded, lock_file)
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


class BrowserSession:
    """Owns one undetected Chrome driver, reused across page loads for a board.

    Launching Chrome is by far the slowest part of a run, so a session is
    created once per board and shared by the scrape pagination loop and every
    job description fetch. If a navigation fails, the driver is restarted once
    before giving up on that page.
    """

    def __init__(self, headless=True, debug=False, user_data_dir=None,
                 reconnect_seconds=10):
        self.headless = headless
        self.debug = debug
        self.user_data_dir = os.path.expanduser(
            user_data_dir or "~/Library/Application Support/Google/Chrome/Python"
        )
        self.reconnect_seconds = reconnect_seconds
        self.driver = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.quit()

    def _ensure_driver(self):
        if self.driver is None:
            _clean_profile_locks(self.user_data_dir)
            self.driver = Driver(
                uc=True,
                headless=self.headless,
                user_data_dir=self.user_data_dir
            )
        return self.driver

    def quit(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

    def load_page(self, url, skip_cloudflare_detection=False, load_more=False):
        """Load a page in the session's browser and return the driver.

        Returns None if the page can't be loaded even after restarting the
        browser once.
        """
        try:
            return self._load(url, skip_cloudflare_detection, load_more)
        except Exception as e:
            logging.warning(f"Error loading page, restarting browser: {e}")
            self._dump_error_html(url)
            self.quit()
        try:
            return self._load(url, skip_cloudflare_detection, load_more)
        except Exception as e:
            logging.warning(f"Error loading page after browser restart: {e}")
            self._dump_error_html(url)
            self.quit()
            return None

    def _load(self, url, skip_cloudflare_detection, load_more):
        driver = self._ensure_driver()

        # Chrome 147+ with shared profiles opens internal chrome:// popup tabs
        # that can't be closed, breaking uc_open_with_reconnect. Instead:
        # 1. Switch to the real browsable tab
        # 2. Navigate directly, then disconnect/reconnect to evade bot detection
        for handle in driver.window_handles:
            driver.switch_to.window(handle)
            if not driver.current_url.startswith("chrome://omnibox"):
                break
        driver.get(url)
        driver.reconnect(self.reconnect_seconds)
        # Ensure we're on the right tab after reconnect
        for handle in driver.window_handles:
            driver.switch_to.window(handle)
            if not driver.current_url.startswith("chrome://"):
                break
        wait = WebDriverWait(driver, 15)

        if not skip_cloudflare_detection:
            _handle_cloudflare(driver)

        if load_more:
            _scroll_and_load_more(driver, wait)

        _wait_for_job_content(driver, wait)

        if self.debug:
            domain = urlparse(url).netloc.replace('www.', '')
            with open(f"{domain}_debug.html", "w", encoding="utf-8") as file:
                file.write(driver.page_source)
        return driver

    def _dump_error_html(self, url):
        if self.debug and self.driver:
            domain = urlparse(url).netloc.replace('www.', '')
            try:
                with open(f"{domain}_error.html", "w", encoding="utf-8") as file:
                    file.write(self.driver.page_source)
            except Exception:
                pass


VERIFICATION_INDICATORS = [
    "Just a moment...",
    "Additional Verification Required",
    "challenge-form",
    "/cdn-cgi/challenge-platform"
]


def _handle_cloudflare(driver):
    """Attempt to solve Cloudflare verification challenges."""
    logging.info("Checking for verification indicators")
    is_verification_page = any(
        indicator in driver.page_source for indicator in VERIFICATION_INDICATORS
    )

    if not is_verification_page:
        return

    logging.info("Cloudflare verification detected. Attempting to solve...")

    # Try captcha iframe approach
    try:
        iframe_selectors = [
            'iframe[src*="captcha"]',
            'iframe[src*="challenge"]',
            'iframe[title*="Cloudflare"]',
            'iframe[name*="cfcaptcha"]',
            'iframe[src*="turnstile"]',
            'iframe[src*="cloudflare"]'
        ]

        for selector in iframe_selectors:
            try:
                iframes = driver.find_elements(By.CSS_SELECTOR, selector)
                if iframes:
                    logging.info(f"Found captcha iframe with selector: {selector}")
                    for iframe in iframes:
                        try:
                            driver.switch_to.frame(iframe)
                            checkbox_selectors = [
                                ".mark",
                                ".recaptcha-checkbox",
                                ".recaptcha-checkbox-border",
                                "[role='checkbox']",
                                "input[type='checkbox']"
                            ]
                            for checkbox_selector in checkbox_selectors:
                                try:
                                    checkboxes = driver.find_elements(By.CSS_SELECTOR, checkbox_selector)
                                    for checkbox in checkboxes:
                                        if checkbox.is_displayed():
                                            logging.info(f"Clicking checkbox with selector: {checkbox_selector}")
                                            driver.execute_script("arguments[0].click();", checkbox)
                                            break
                                except Exception:
                                    continue
                            driver.switch_to.default_content()
                        except Exception:
                            driver.switch_to.default_content()
                            continue
            except Exception:
                continue

        # Wait for verification to complete
        for _ in range(5):
            if not any(indicator in driver.page_source for indicator in VERIFICATION_INDICATORS):
                logging.info("Successfully passed Cloudflare verification")
                return
            sleep(1)

    except Exception as e:
        logging.info(f"Error clicking captcha: {e}")

    # Fallback: try clicking any visible element in iframes
    if any(indicator in driver.page_source for indicator in VERIFICATION_INDICATORS):
        try:
            iframes = driver.find_elements(By.TAG_NAME, "iframe")
            for iframe in iframes:
                try:
                    if iframe.is_displayed():
                        driver.switch_to.frame(iframe)
                        clickable_elements = driver.find_elements(
                            By.CSS_SELECTOR,
                            "button, input[type='checkbox'], div[role='checkbox']"
                        )
                        for element in clickable_elements:
                            try:
                                if element.is_displayed():
                                    driver.execute_script("arguments[0].click();", element)
                                    logging.info("Clicked on a potential captcha element")
                                    break
                            except Exception:
                                continue
                        driver.switch_to.default_content()
                except Exception:
                    driver.switch_to.default_content()
                    continue
        except Exception as e:
            logging.info(f"Error with alternate captcha clicking: {e}")


# Selectors checked (in order) for a load-more control on each scroll pass.
# NOTE: Monster's "svx-see-more-results-link" is NOT a load-more button — it
# navigates to a different (related) search. Do not add it here.
LOAD_MORE_BUTTONS = [
    (By.CLASS_NAME, "btn-line-darkCerulean"),   # Kforce
    (By.ID, "job-search-load-more"),            # Monster (pre-2026 layout)
]

# Anything that looks like a job card on the boards that lazy-load
_CARD_SELECTOR = "article, ul.data-jobs li"

# Find a card currently in the viewport to anchor a trusted wheel scroll on
_VISIBLE_CARD_JS = f"""
const cards = [...document.querySelectorAll("{_CARD_SELECTOR}")];
const vh = window.innerHeight;
return cards.find(c => {{
  const r = c.getBoundingClientRect();
  return r.top >= 0 && r.top < vh - 150 && r.height > 0;
}}) || null;
"""

_REALIGN_JS = f"""
const c = document.querySelectorAll("{_CARD_SELECTOR}");
if (c.length) c[c.length - 1].scrollIntoView({{block: "center"}});
"""

_CARD_COUNT_JS = f'return document.querySelectorAll("{_CARD_SELECTOR}").length;'


def _scroll_and_load_more(driver, wait, max_iterations=80):
    """Reveal all jobs on lazy-loading boards.

    Monster only loads more results on TRUSTED scroll input (real wheel
    events via the browser input pipeline) — synthetic JS scrolls are
    ignored — so scrolling goes through ActionChains anchored on a visible
    card. Load-more buttons (Kforce) are clicked when present.
    """
    stagnant = 0
    last_count = -1
    try:
        for _ in range(max_iterations):
            button_clicked = False
            for by, value in LOAD_MORE_BUTTONS:
                for button in driver.find_elements(by, value):
                    try:
                        if button.is_displayed():
                            driver.execute_script("arguments[0].scrollIntoView();", button)
                            # JS click — overlays can block real clicks
                            driver.execute_script("arguments[0].click();", button)
                            button_clicked = True
                            break
                    except Exception:
                        continue
                if button_clicked:
                    break

            card = driver.execute_script(_VISIBLE_CARD_JS)
            if card is None:
                # Landed on a spinner/ad — re-align on the last card
                # (synthetic scroll is fine for positioning) and retry
                driver.execute_script(_REALIGN_JS)
                sleep(1)
                card = driver.execute_script(_VISIBLE_CARD_JS)

            if card is not None:
                try:
                    origin = ScrollOrigin.from_element(card)
                    ActionChains(driver).scroll_from_origin(origin, 0, 5000).perform()
                except Exception:
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            else:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

            sleep(2)  # give lazy-load fetches time to land

            count = driver.execute_script(_CARD_COUNT_JS)
            if count == last_count and not button_clicked:
                # Allow a few quiet passes before concluding we're done
                stagnant += 1
                if stagnant >= 5:
                    break
            else:
                stagnant = 0
                logging.info(f"Load-more: {count} cards loaded")
            last_count = count
    except Exception as e:
        logging.info(f"Load-more loop stopped: {e}")


# CSS selectors that indicate job content has loaded
JOB_CONTENT_SELECTORS = [
    ".job_seen_beacon",
    "article.job-tile",
    ".paging-container",
    "div.job_result_two_pane",
    ".result-box",
    "dhi-search-card",
    "section.jobs article ul",
    ".job-details-description",
    "article[data-testid='JobCard']",
    "#__NEXT_DATA__",
    "ul.data-jobs li",
    ".data-job-desc",
    "#react-job-wrapper",
    "div.page-meta",
    "h1.col-xs-12.col-sm-8",
    ".page-box-shadow.fake-tab-content",
    ".result",
    ".detailpage-desc",
    ".job_result_two_pane",
    ".job_result_two_pane_v2",
    "div.job_description",
    "article.job-tile",
    "div[data-test='job-description']",
    ".visitor-page-container",
    "dhi-search-card",
    "div[data-cy='payDetails'] span",
    "#jobDescriptionText",
    "div#job-listing-show-container",
    "li.new-listing-container",
    "div[data-id]",
    "a[data-testid='job-search-job-detail-link']",
    "div[data-testid='jobSearchResultsContainer']",
    "#react-serp-root"
]


def _wait_for_job_content(driver, wait):
    """Wait for job-related content to appear on the page."""
    try:
        wait.until(
            EC.presence_of_element_located((
                By.CSS_SELECTOR, ", ".join(JOB_CONTENT_SELECTORS)
            ))
        )
    except Exception:
        logging.info("Page loaded but job info not found!")
