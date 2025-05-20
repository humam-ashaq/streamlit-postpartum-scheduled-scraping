import requests
from bs4 import BeautifulSoup
import pandas as pd
from pymongo import MongoClient
from wordcloud import WordCloud
import matplotlib.pyplot as plt
import streamlit as st
import nltk
from nltk.corpus import stopwords
import re
import time
from collections import Counter
import seaborn as sns
from dateutil import parser

dbUri = st.secrets["DB_URI"]

nltk.download('stopwords')

st.set_page_config(layout="wide")
st.title("Scraper & Visualisasi Artikel Perawatan Bayi")

# Fungsi ambil daftar link artikel
def get_article_links(base_url, max_articles=100):
    all_links = set()
    page = 1

    while len(all_links) < max_articles:
        url = base_url if page == 1 else f"{base_url}?page={page}"
        response = requests.get(url)
        soup = BeautifulSoup(response.text, "html.parser")

        new_links = [] # nyimpen link per artikel terbaru
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

# Fungsi ambil konten artikel
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

# Stopwords cleaner
def remove_stopwords(text):
    stop_words_id = set(stopwords.words("indonesian"))
    stop_words_en = set(stopwords.words("english"))
    custom_stopwords = {"retrieved", "www", "http", "https", "com", "org", "si", "hello", "n"}
    combined_stopwords = stop_words_id.union(stop_words_en).union(custom_stopwords)

    words = re.findall(r'\b\w+\b', text.lower())
    cleaned = [word for word in words if word not in combined_stopwords]
    return " ".join(cleaned)

def bersihkan_teks(teks):
    teks = re.sub(r"http\S+|www\.x\S+", "", teks)
    teks = re.sub(r"[^a-zA-Z\s]", "", teks)
    teks = teks.lower()
    return teks

# Tombol Streamlit
if st.button("Mulai Scraping & Visualisasi"):
    with st.spinner("Mengambil daftar artikel dari halaman kategori..."):
        base_url = "https://hellosehat.com/parenting/bayi/perawatan-bayi/"
        article_links = get_article_links(base_url, max_articles=100)
        st.write(f"Ditemukan {len(article_links)} artikel.")

    with st.spinner("Mengambil konten setiap artikel..."):
        data = []
        for url in article_links:
            article_data = scrape_article(url)
            data.append(article_data)
            time.sleep(1)

        df = pd.DataFrame(data)
        df["published_date"] = pd.to_datetime(df["published_date"])
        df["month_year"] = df["published_date"].dt.to_period("M").astype(str)
        df = df[df["published_date"].notna()]

        # Simpan ke MongoDB
        try:
            client = MongoClient(dbUri)
            db = client["postpartum"]
            collection = db["articles"]
            collection.insert_many(df.to_dict("records"))
            st.success("Berhasil disimpan ke MongoDB!")
        except Exception as e:
            st.error(f"Gagal menyimpan ke MongoDB: {e}")

        # Visualisasi data artikel
        st.subheader("Data Artikel")
        st.dataframe(df[["title", "url"]])

        # Wordcloud
        st.subheader("Word Cloud")
        text = " ".join(df["title"].tolist() + df["content"].tolist())
        clean_text = remove_stopwords(text)
        clean_text2 = bersihkan_teks(clean_text)
        wordcloud = WordCloud(width=1000, height=500, background_color="white").generate(clean_text2)

        fig, ax = plt.subplots(figsize=(12, 6))
        ax.imshow(wordcloud, interpolation="bilinear")
        ax.axis("off")
        st.pyplot(fig)

        # Tren kata terbanyak
        words = clean_text2.split()
        word_freq = Counter(words)
        most_common = word_freq.most_common(20)

        st.subheader("Tren Kata Terbanyak (Top 20)")
        wc_df = pd.DataFrame(most_common, columns=["Kata", "Frekuensi"])

        fig2, ax2 = plt.subplots(figsize=(12, 6))
        sns.barplot(data=wc_df, x="Frekuensi", y="Kata", ax=ax2, palette="Blues_d")
        ax2.set_title("20 Kata Paling Sering Muncul")
        ax2.set_xlabel("Frekuensi")
        ax2.set_ylabel("Kata")
        ax2.bar_label(ax2.containers[0], fmt='%d', label_type='edge', padding=5)
        st.pyplot(fig2)

        # Artikel per bulan
        st.subheader("Jumlah Artikel per Bulan")
        monthly_counts = df["month_year"].value_counts().sort_index()

        fig3, ax3 = plt.subplots(figsize=(12, 6))
        sns.barplot(x=monthly_counts.index, y=monthly_counts.values, ax=ax3, palette="viridis")
        ax3.set_title("Jumlah Artikel Diposting per Bulan")
        ax3.set_xlabel("Bulan")
        ax3.set_ylabel("Jumlah Artikel")
        plt.xticks(rotation=45)
        st.pyplot(fig3)
