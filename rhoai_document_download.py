import os
import re
import time
import requests
from urllib.parse import urlparse
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

# --- Configuration ---
# We start specifically at the OpenShift AI Self-Managed 3.4 index
START_URL = "https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/3.4"
DOWNLOAD_DIR = "openshift_ai_3.4_pdfs"
# ---------------------

def setup_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)

def clean_segment(text):
    """
    Formats text for Red Hat filenames.
    Rule: Spaces -> Underscores. Everything else (like hyphens) stays.
    Example: "Self-Managed" -> "Self-Managed"
    Example: "Red Hat" -> "Red_Hat"
    """
    # Remove trademarks
    text = text.replace('®', '').replace('™', '')
    # Replace spaces with underscores
    text = text.replace(' ', '_')
    # Remove strictly invalid filename chars (keep hyphens and dots)
    text = re.sub(r'[^\w\-\.]', '', text)
    return text

def construct_pdf_url(guide_url, page_title):
    try:
        # 1. Extract Slug from URL
        # URL: .../html/monitoring_your_ai_systems/index
        parsed = urlparse(guide_url)
        path_parts = parsed.path.split('/')
        if 'html' not in path_parts:
            return None
        
        idx = path_parts.index('html')
        slug = path_parts[idx + 1]

        # 2. Parse Title
        # Title Format: "Guide Name | Product Name Version | ..."
        # Example: "Monitoring your AI systems | Red Hat OpenShift AI Self-Managed 3.4 | ..."
        parts = page_title.split('|')
        if len(parts) < 2:
            return None

        guide_name_raw = parts[0].strip()
        product_version_raw = parts[1].strip()

        # 3. Split Product and Version
        # We assume the version (3.4) is the last part of the product string
        # "Red Hat OpenShift AI Self-Managed 3.4" -> Product="...Self-Managed", Version="3.4"
        pv_parts = product_version_raw.rsplit(' ', 1)
        if len(pv_parts) == 2:
            product_raw = pv_parts[0]
            version_raw = pv_parts[1]
        else:
            product_raw = product_version_raw
            version_raw = "3.4" # Fallback

        # 4. Clean Strings
        product_clean = clean_segment(product_raw)
        version_clean = clean_segment(version_raw)
        guide_clean = clean_segment(guide_name_raw)

        # 5. Build Filename
        # Pattern: Product-Version-Guide-en-US.pdf
        filename = f"{product_clean}-{version_clean}-{guide_clean}-en-US.pdf"

        # 6. Build Full URL
        # Replace /html/[slug]/... with /pdf/[slug]/[filename]
        base_path = "/".join(path_parts[:idx])
        pdf_path = f"{base_path}/pdf/{slug}/{filename}"
        
        return f"{parsed.scheme}://{parsed.netloc}{pdf_path}"

    except Exception:
        return None

def main():
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)

    driver = setup_driver()
    try:
        print(f"Scanning: {START_URL}")
        driver.get(START_URL)
        time.sleep(5) # Wait for page to fully render

        # 1. Harvest Links
        # We strictly look for links containing the specific product path
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        links = soup.find_all('a', href=True)
        
        guide_urls = set()
        target_path = "/documentation/red_hat_openshift_ai_self-managed/3.4/html/"

        for a in links:
            href = a['href']
            # STRICT FILTER: Only include links for this specific product/version
            if target_path in href:
                # Normalize URL
                if href.startswith('/'):
                    full_url = "https://docs.redhat.com" + href
                else:
                    full_url = href
                
                clean_url = full_url.split('#')[0]
                guide_urls.add(clean_url)

        print(f"Found {len(guide_urls)} guides matching 'OpenShift AI Self-Managed 3.4'.")

        # 2. Process Guides
        for i, guide_url in enumerate(sorted(guide_urls)):
            print(f"\n[{i+1}/{len(guide_urls)}] Processing: {guide_url}")
            
            try:
                driver.get(guide_url)
                # No sleep needed if we just grab title, but safer to wait 1s
                time.sleep(1)
                
                pdf_url = construct_pdf_url(guide_url, driver.title)
                
                if pdf_url:
                    filename = os.path.basename(pdf_url)
                    local_path = os.path.join(DOWNLOAD_DIR, filename)
                    
                    if os.path.exists(local_path):
                        print(f"   [Skip] File exists: {filename}")
                        continue

                    # HEAD request to verify link before downloading
                    try:
                        h = requests.head(pdf_url)
                        if h.status_code == 200:
                            print(f"   [Found] {pdf_url}")
                            print("   [Downloading]...")
                            with requests.get(pdf_url, stream=True) as r:
                                r.raise_for_status()
                                with open(local_path, 'wb') as f:
                                    for chunk in r.iter_content(chunk_size=8192):
                                        f.write(chunk)
                            print("   [Success] Saved.")
                        else:
                            # 302/404 means our constructed name didn't match the server's file
                            print(f"   [Failed] Generated link invalid (Status {h.status_code}).")
                            print(f"            Title was: {driver.title}")
                    except Exception as e:
                        print(f"   [Error] Network error: {e}")
                else:
                    print("   [Error] Could not construct PDF URL from title.")

            except Exception as e:
                print(f"   [Error] Failed to process page: {e}")

    finally:
        driver.quit()
        print("\nDone.")

if __name__ == "__main__":
    main()