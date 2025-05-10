from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.ie.webdriver import WebDriver
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import ElementClickInterceptedException, StaleElementReferenceException, TimeoutException
from collections import defaultdict, Counter
import time
import urllib.parse
import pandas as pd
import random
import os

def scrape_google_maps(business_type, location, target_lead_count = 100, driver_path="chromedriver.exe", output_path="output/leads.csv"):
    # Set up the driver
    options = webdriver.ChromeOptions()
    # options.add_argument("--headless")
    service = Service(driver_path)
    driver = webdriver.Chrome(service=service, options=options)

    # Build the search query
    search_query = f"{business_type} in {location}"
    encoded_query = urllib.parse.quote(search_query)
    search_url = f"https://www.google.com/maps/search/{encoded_query}"
    driver.get(search_url)

    business_names = []
    addresses = []
    websites = []
    phones = []

    # Scroll to load more results
    wait = WebDriverWait(driver, 1)
    scroll_box = wait.until(EC.presence_of_element_located((By.XPATH, '//div[@role="feed"]')))

    max_scroll_attempts = 100
    scroll_attempts = 0
    failed_scrolls = 0
    max_failed_scrolls = 5

    while scroll_attempts < max_scroll_attempts:
        cards = driver.find_elements(By.CLASS_NAME, "Nv2PK")
        if len(cards) >= target_lead_count:
            print(f"[INFO] Reached target of {target_lead_count} listings.")
            break

        # Scroll down
        driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", scroll_box)
        time.sleep(1)  # Give time for loading

        # Check for "end of list" message
        try:
            end_marker = driver.find_element(By.XPATH, '//span[contains(@class, "HlvSq") and contains(text(), "You\'ve reached the end of the list.")]')
            print("[INFO] Reached actual end of the list.")
            break
        except NoSuchElementException:
            pass

        # Check if new cards have loaded
        new_cards = driver.find_elements(By.CLASS_NAME, "Nv2PK")
        if len(new_cards) > len(cards):
            failed_scrolls = 0
        else:
            failed_scrolls += 1
            print(f"[INFO] No new listings found (failed scrolls: {failed_scrolls})")
            if failed_scrolls >= max_failed_scrolls:
                print("[INFO] Giving up scrolling due to repeated failures.")
                break

    scroll_attempts += 1

    # After scrolling is complete, re-fetch the result cards to avoid stale references
    result_cards = driver.find_elements(By.CLASS_NAME, "Nv2PK")
    print(f"[DEBUG] Found {len(result_cards)} result cards in Google Maps UI")

    previous_business_name = None

    # For tracking failure reasons per card
    failure_log = {}
    unscraped_cards = set()

    # Iterate using index instead of storing stale references
    for i, card in enumerate(result_cards):
        try:
            fresh_cards = driver.find_elements(By.CLASS_NAME, "Nv2PK")
            card = fresh_cards[i]

            # Scroll into view
            driver.execute_script("arguments[0].scrollIntoView(true);", card)

            def click_and_wait_for_panel_change(max_attempts=3):
                nonlocal previous_business_name
                for attempt in range(max_attempts):
                    try:
                        card.click()
                        time.sleep(0.2)
                        card.click()
                        print(f"[DEBUG] Clicked card {i + 1} (attempt {attempt + 1})")

                        def panel_loaded_and_changed(driver_inner):
                            try:
                                panel_element = driver_inner.find_element(By.XPATH, '//div[@role="main" and @aria-label]')
                                business_name = panel_element.get_attribute("aria-label")
                                if business_name and business_name != previous_business_name:
                                    return business_name
                            except NoSuchElementException:
                                print(f"[DIAGNOSTIC] NoSuchElementException while waiting for panel.")
                                return False
                            except Exception as exc:
                                print(f"[DIAGNOSTIC] Exception in panel_loaded_and_changed: {type(exc).__name__}: {exc}")
                                return False
                            return False

                        new_name = WebDriverWait(driver, 0.75).until(panel_loaded_and_changed)
                        print(f"[DEBUG] Business name from aria-label: {new_name}")
                        previous_business_name = new_name
                        return True  # ✅ Success! Stop retrying.

                    except (TimeoutException, StaleElementReferenceException, ElementClickInterceptedException,
                            NoSuchElementException, Exception):
                        # 🛑 Don’t log anything here — let retries happen silently.
                        pass

                # 🧨 All attempts failed — now we log
                print(f"[TIMEOUT] Business details panel did not load or change for result {i + 1}")
                failure_log[i + 1].append("[GIVEUP] Panel never updated after all attempts")
                return False


            success = click_and_wait_for_panel_change()
            if not success:
                unscraped_cards.add(i + 1)
                continue

            # Scrape name
            try:
                main_panel = driver.find_element(By.XPATH, '//div[@role="main" and @aria-label]')
                name = main_panel.get_attribute("aria-label")
            except Exception as e:
                print(f"[ERROR] Failed to extract business name from aria-label: {e}")
                name = ""

            # Scrape address
            try:
                address = driver.find_element(By.XPATH, '//button[@data-item-id="address"]//div[contains(@class, "Io6YTe")]').text
            except NoSuchElementException:
                address = ""

            # Scrape phone
            try:
                phone_button = driver.find_element(By.XPATH, '//button[starts-with(@aria-label, "Phone:")]')
                phone = phone_button.get_attribute("aria-label").replace("Phone: ", "").strip()
                print(f"[SCRAPE] Phone: {phone}")
            except NoSuchElementException:
                phone = ""

            # Scrape website
            try:
                website_button = driver.find_element(By.XPATH, '//a[starts-with(@aria-label, "Website:")]')
                website = website_button.get_attribute("aria-label").replace("Website: ", "").strip()
                print(f"[SCRAPE] Website: {website}")
            except NoSuchElementException:
                website = ""

            business_names.append(name)
            addresses.append(address)
            phones.append(phone)
            websites.append(website)

        except Exception as e:
            print(f"[ERROR] Failed to process result {i +1}: {type(e).__name__}: {e}")
        continue

    # Build DataFrame
    data = pd.DataFrame({
        "Business Name": business_names,
        "Address": addresses,
        "Website": websites,
        "Phone": phones
    })

    print(f"[SUMMARY] Scraped {len(business_names)} businesses total")
    print(f"  - With phone numbers: {sum(1 for p in phones if p)}")
    print(f"  - With websites: {sum(1 for w in websites if w)}")

    all_tags = [entry.split(']')[0] + ']' for failures in failure_log.values() for entry in failures if ']' in entry]
    tag_counts = Counter(all_tags)

    print("\n[FAILURE TAG SUMMARY]")
    for tag, count in tag_counts.items():
        print(f"  - {tag}: {count}")


    if unscraped_cards:
        print("\n[FAILURE DIAGNOSTICS - UNSCRAPED CARDS ONLY]")
        for card_num in sorted(unscraped_cards):
            last_reason = failure_log[card_num][-1] if failure_log[card_num] else "Unknown reason"
            print(f"  - Card {card_num}: {last_reason}")
    else:
        print("\n[FAILURE DIAGNOSTICS] All cards scraped successfully.")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    data.to_csv(output_path, index=True)

    driver.quit()