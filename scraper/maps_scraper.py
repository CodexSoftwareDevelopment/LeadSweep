# from sys import executable
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import NoSuchElementException
import time
import urllib.parse
import pandas as pd
import os

def scrape_google_maps(business_type, location, driver_path="chromedriver.exe", output_path="output/leads.csv"):
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
    time.sleep(5) # will replace with smarter wait later

    business_names = []
    addresses = []
    websites = []
    phones = []

    # Scroll to load more results
    scroll_box = driver.find_element(By.XPATH, '//div[@role="feed"]')
    for _ in range(5):
        scroll_box.send_keys(Keys.PAGE_DOWN)
        time.sleep(2)

    # Grab result cards
    results = driver.find_elements(By.CLASS_NAME, "Nv2PK")
    print(f"[DEBUG] Found {len(results)} business cards.")
    for result in results:
        try:
            name = result.find_element(By.CLASS_NAME, "qBF1Pd").text
        except NoSuchElementException:
            name = ""
        business_names.append(name)

        # More fields can be scraped by clicking into listings later (future step)
        addresses.append("")
        websites.append("")
        phones.append("")

    # Build DataFrame
    data = pd.DataFrame({
        "Business Name": business_names,
        "Address": addresses,
        "Website": websites,
        "Phone": phones
    })

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    data.to_csv(output_path, index=True)

    print(f"Scraped {len(business_names)} results.")
    driver.quit()