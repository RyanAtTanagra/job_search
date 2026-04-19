import os
import resource
import logging
from time import sleep
from urllib.parse import urlparse

from seleniumbase import Driver
from selenium.webdriver.common.by import By
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


def load_page(url, headless=True, debug=False, skip_cloudflare_detection=False,
              load_more=False, user_data_dir=None):
    """Load a page using an undetected Chrome browser and return the driver."""
    domain = urlparse(url).netloc.replace('www.', '')
    profile_dir = user_data_dir or "~/Library/Application Support/Google/Chrome/Python"
    _clean_profile_locks(profile_dir)
    driver = Driver(
        uc=True,
        headless=headless,
        user_data_dir=profile_dir
    )

    try:
        # Chrome 147+ with shared profiles opens internal chrome:// popup tabs
        # that can't be closed, breaking uc_open_with_reconnect. Instead:
        # 1. Switch to the real browsable tab
        # 2. Navigate directly, then disconnect/reconnect to evade bot detection
        for handle in driver.window_handles:
            driver.switch_to.window(handle)
            if not driver.current_url.startswith("chrome://omnibox"):
                break
        driver.get(url)
        driver.reconnect(10)
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

        if debug:
            with open(f"{domain}_debug.html", "w", encoding="utf-8") as file:
                file.write(driver.page_source)
        return driver

    except Exception as e:
        logging.error(f"Error loading page: {e}")
        if debug:
            try:
                with open(f"{domain}_error.html", "w", encoding="utf-8") as file:
                    file.write(driver.page_source)
            except Exception:
                pass
        driver.quit()
        return None


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


def _scroll_and_load_more(driver, wait):
    """Scroll down and click load-more buttons to reveal all jobs."""
    try:
        while True:
            last_height = driver.execute_script("return document.body.scrollHeight")
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            sleep(1)

            button_clicked = False
            load_more_buttons = [
                (By.CLASS_NAME, "btn-line-darkCerulean"),  # Kforce
                (By.ID, "job-search-load-more")            # Monster
            ]
            for by, value in load_more_buttons:
                try:
                    load_more_button = wait.until(
                        EC.element_to_be_clickable((by, value))
                    )
                    driver.execute_script("arguments[0].scrollIntoView();", load_more_button)
                    load_more_button.click()
                    sleep(1)
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    sleep(1)
                    button_clicked = True
                    break
                except (TimeoutException, NoSuchElementException):
                    continue

            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height and not button_clicked:
                break

            logging.info(f"Scrolling from {last_height} to {new_height}")
    except Exception:
        logging.info("Couldn't find load more buttons")


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
