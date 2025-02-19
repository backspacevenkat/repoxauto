import time
import random
import requests
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import boto3

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ----- Storj S3 Setup -----
S3_BUCKET = "profilepics"
s3 = boto3.client(
    "s3",
    endpoint_url="https://gateway.storjshare.io",
    aws_access_key_id="jxg3mqqf5omqb5yu763l6ou4qg5a",
    aws_secret_access_key="j35rx7qujtwwe6wxv2ovvjycvjde45ahvlwhoozruewuyttw4y6uq"
)

def download_and_store(src_url, filename, metadata):
    """Downloads the image from src_url and uploads to Storj."""
    try:
        resp = requests.get(src_url, timeout=10)
        resp.raise_for_status()
        s3.put_object(Bucket=S3_BUCKET, Key=filename, Body=resp.content, Metadata=metadata)
        logging.info(f"Uploaded {filename} to Storj.")
    except Exception as e:
        logging.error(f"Failed to download/store {filename} from {src_url}: {e}")

def scrape_faces(gender="M", start_index=0, total_images=2000, batch_size=8):
    """
    gender: 'M' for male, 'F' for female
    start_index: starting index for file naming
    total_images: how many images this thread should collect
    batch_size: how many images each 'load_faces()' call provides
    """
    loops = (total_images + batch_size - 1) // batch_size
    current_index = start_index

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        context.set_default_timeout(30000)

        page = context.new_page()
        logging.info(f"[{gender}-{start_index}] Navigating to site...")
        page.goto("https://thispersonnotexist.org/")
        time.sleep(2)

        try:
            if gender == "M":
                logging.info(f"[{gender}-{start_index}] Calling load_faces('M')")
                page.evaluate("load_faces('M')")
            else:
                logging.info(f"[{gender}-{start_index}] Calling load_faces('F')")
                page.evaluate("load_faces('F')")
        except Exception as e:
            logging.error(f"Error calling load_faces for gender={gender}: {e}")

        images_downloaded = 0
        for loop_idx in range(loops):
            if images_downloaded >= total_images:
                break

            logging.info(f"[{gender}-{start_index}] Loop {loop_idx+1}/{loops}")
            try:
                page.wait_for_selector("img.ximg", timeout=15000)
            except TimeoutError:
                continue
            
            img_elements = page.query_selector_all("img.ximg")
            if not img_elements:
                continue

            for i, img_elem in enumerate(img_elements):
                if images_downloaded >= total_images:
                    break

                src = img_elem.get_attribute("src")
                if src:
                    filename = f"{gender}_{start_index}_{images_downloaded}.jpg"
                    meta = {"gender": "male" if gender == "M" else "female", "index": str(current_index)}
                    logging.info(f"[{gender}-{start_index}] Downloading {src[:40]} => {filename}")
                    download_and_store(src, filename, meta)
                    images_downloaded += 1
                    current_index += 1

            time.sleep(2)
            page.evaluate(f"load_faces('{gender}')")
            time.sleep(3)

        context.close()
        browser.close()
        
    return images_downloaded

def main():
    total_male = 10000
    total_female = 10000
    threads_per_gender = 6
    
    male_per_thread = total_male // threads_per_gender
    female_per_thread = total_female // threads_per_gender

    logging.info(f"Starting download with {threads_per_gender * 2} threads")
    total_downloaded = 0
    
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = []
        
        # Male threads
        for i in range(threads_per_gender):
            start_index = i * male_per_thread
            futures.append(executor.submit(
                scrape_faces,
                gender="M",
                start_index=start_index,
                total_images=male_per_thread,
                batch_size=8
            ))
        
        # Female threads
        for i in range(threads_per_gender):
            start_index = i * female_per_thread
            futures.append(executor.submit(
                scrape_faces,
                gender="F",
                start_index=start_index,
                total_images=female_per_thread,
                batch_size=8
            ))
        
        for future in as_completed(futures):
            try:
                count = future.result()
                total_downloaded += count
                logging.info(f"Thread completed: {count} images. Total: {total_downloaded}")
            except Exception as e:
                logging.error(f"Thread error: {e}")
    
    logging.info(f"Download complete. Total images: {total_downloaded}")

if __name__ == "__main__":
    main()