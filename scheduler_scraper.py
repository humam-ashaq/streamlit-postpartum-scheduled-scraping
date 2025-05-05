# scheduler_scraper.py
import requests
from bs4 import BeautifulSoup
import pandas as pd
from pymongo import MongoClient
from dateutil import parser
import time
import schedule
from dotenv import load_dotenv
import os

dbUri = os.getenv("DB_URI")

# === Fungsi scraping ===
def get_article_links(base_url, max_articles=100):
    all_links = set()
    page = 1

    while len(all_links) < max_articles:
        url = base_url if page == 1 else f"{base_url}?page={page}"
        response = requests.get(url)
        soup = BeautifulSoup(response.text, "html.parser")

        new_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/parenting/bayi/perawatan-bayi/" in href and not href.endswith("/perawatan-bayi/"):
                full_url = href if href.startswith("http") else f"https://hellosehat.com{href}"
                if full_url not in all_links:
                    new_links.append(full_url)

        if not new_links:
            break

        all_links.update(new_links)
        if len(all_links) >= max_articles:
            break

        page += 1
        time.sleep(1)

    return list(all_links)[:max_articles]

def scrape_article(url):
    try:
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')

        title = soup.find("h1")
        paragraphs = soup.find_all("p")
        date_tag = soup.find("meta", {"property": "article:published_time"})
        pub_date = parser.parse(date_tag["content"]) if date_tag and date_tag.get("content") else None

        return {
            "url": url,
            "title": title.get_text(strip=True) if title else "No Title",
            "content": " ".join(p.get_text(strip=True) for p in paragraphs),
            "published_date": pub_date
        }
    except Exception as e:
        return {"url": url, "title": "Error", "content": str(e), "published_date": None}

# === Fungsi utama scheduler ===
def run_scraper():
    print("📡 Menjalankan scraping otomatis...")
    base_url = "https://hellosehat.com/parenting/bayi/perawatan-bayi/"
    article_links = get_article_links(base_url, max_articles=100)
    print(f"✅ Ditemukan {len(article_links)} artikel.")

    data = []
    for url in article_links:
        article_data = scrape_article(url)
        data.append(article_data)
        time.sleep(1)

    df = pd.DataFrame(data)
    df["published_date"] = pd.to_datetime(df["published_date"])
    df = df[df["published_date"].notna()]
    df["month_year"] = df["published_date"].dt.to_period("M").astype(str)

    try:
        client = MongoClient(dbUri)
        db = client["postpartum"]
        collection = db["articles"]
        collection.insert_many(df.to_dict("records"))
        print("✅ Data berhasil disimpan ke MongoDB!")
    except Exception as e:
        print(f"❌ Gagal menyimpan ke MongoDB: {e}")

# === Jalankan schedule ===
if __name__ == "__main__":
    schedule.every().day.at("06:00").do(run_scraper)
    print("⏳ Scheduler aktif. Menunggu waktu eksekusi...")

    while True:
        schedule.run_pending()
        time.sleep(60)
