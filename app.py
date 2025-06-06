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

# Fungsi ambil konten artikel dengan gambar sampul
def scrape_article(url):
    try:
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')

        # Ambil title
        title = soup.find("h1")
        
        # Ambil paragraf
        paragraphs = soup.find_all("p")
        
        # Ambil tanggal publish
        date_tag = soup.find("meta", {"property": "article:published_time"})
        pub_date = parser.parse(date_tag["content"]) if date_tag and date_tag.get("content") else None

        # Ambil gambar sampul - beberapa kemungkinan selector
        image_url = None
        
        # Metode 1: Cari meta tag Open Graph image
        og_image = soup.find("meta", {"property": "og:image"})
        if og_image and og_image.get("content"):
            image_url = og_image["content"]
        
        # Metode 2: Jika tidak ada OG image, cari meta tag Twitter image
        if not image_url:
            twitter_image = soup.find("meta", {"name": "twitter:image"})
            if twitter_image and twitter_image.get("content"):
                image_url = twitter_image["content"]
        
        # Metode 3: Cari gambar pertama dalam artikel
        if not image_url:
            first_img = soup.find("img")
            if first_img and first_img.get("src"):
                img_src = first_img["src"]
                # Pastikan URL lengkap
                if img_src.startswith("//"):
                    image_url = f"https:{img_src}"
                elif img_src.startswith("/"):
                    image_url = f"https://hellosehat.com{img_src}"
                elif img_src.startswith("http"):
                    image_url = img_src
        
        # Metode 4: Cari dalam figure atau div dengan class tertentu
        if not image_url:
            figure_img = soup.find("figure")
            if figure_img:
                img_tag = figure_img.find("img")
                if img_tag and img_tag.get("src"):
                    img_src = img_tag["src"]
                    if img_src.startswith("//"):
                        image_url = f"https:{img_src}"
                    elif img_src.startswith("/"):
                        image_url = f"https://hellosehat.com{img_src}"
                    elif img_src.startswith("http"):
                        image_url = img_src

        return {
            "url": url,
            "title": title.get_text(strip=True) if title else "No Title",
            "content": " ".join(p.get_text(strip=True) for p in paragraphs),
            "published_date": pub_date,
            "image_url": image_url if image_url else "No Image"
        }
    except Exception as e:
        return {
            "url": url, 
            "title": "Error", 
            "content": str(e), 
            "published_date": None,
            "image_url": "Error"
        }

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

def save_to_mongodb(df):
    try:
        client = MongoClient(dbUri)
        db = client["momstretch"]
        collection = db["articles"]
        existing_urls = set(doc["url"] for doc in collection.find({}, {"url": 1, "_id": 0}))
        new_docs = [row for row in df.to_dict("records") if row["url"] not in existing_urls]

        if new_docs:
            # Debug: cek data yang akan diinsert
            st.write(f"Sample dokumen yang akan disimpan:")
            if new_docs:
                sample_doc = new_docs[0]
                st.json(sample_doc)
            
            collection.insert_many(new_docs)
            return len(new_docs), True
        else:
            return 0, False
    except Exception as e:
        st.error(f"Database Error: {e}")
        return 0, False

def load_data_from_db():
    try:
        client = MongoClient(dbUri)
        db = client["momstretch"]
        collection = db["articles"]
        articles = list(collection.find({}, {"_id": 0}))
        return pd.DataFrame(articles)
    except Exception as e:
        st.error(f"Gagal mengambil data dari MongoDB: {e}")
        return pd.DataFrame()

# Main process
if st.button("Mulai Scraping & Visualisasi"):
    with st.spinner("Mengambil daftar artikel dari halaman kategori..."):
        base_url = "https://hellosehat.com/parenting/bayi/perawatan-bayi/"
        article_links = get_article_links(base_url, max_articles=100)
        st.write(f"Ditemukan {len(article_links)} artikel.")

    with st.spinner("Mengambil konten setiap artikel..."):
        scraped_data = []
        for i, url in enumerate(article_links):
            result = scrape_article(url)
            scraped_data.append(result)
            # Debug: tampilkan progress dan cek image_url
            if i < 3:  # Tampilkan 3 artikel pertama untuk debug
                st.write(f"Debug - Artikel {i+1}: {result['title'][:50]}...")
                st.write(f"Image URL: {result['image_url']}")
            time.sleep(1)

        df = pd.DataFrame(scraped_data)
        
        # Debug: cek kolom yang ada
        st.write("Kolom dalam DataFrame:", df.columns.tolist())
        st.write("Sample data (5 baris pertama):")
        st.dataframe(df.head())
        
        df["published_date"] = pd.to_datetime(df["published_date"])
        df = df[df["published_date"].notna()]
        df["month_year"] = df["published_date"].dt.to_period("M").astype(str)

    with st.spinner("Menyimpan ke MongoDB..."):
        # Debug: cek data sebelum disimpan
        st.write("Data yang akan disimpan ke MongoDB:")
        st.write(f"Jumlah baris: {len(df)}")
        st.write(f"Kolom: {df.columns.tolist()}")
        
        inserted_count, inserted = save_to_mongodb(df)
        if inserted:
            st.success(f"Berhasil menyimpan {inserted_count} artikel baru ke MongoDB!")
        else:
            st.warning("Tidak ada artikel baru yang disimpan. Semua data sudah ada.")

    st.markdown("---")

# Load & visualize
df = load_data_from_db()

if not df.empty:
    # Debug: cek data yang dimuat dari DB
    st.write("Data yang dimuat dari MongoDB:")
    st.write(f"Jumlah baris: {len(df)}")
    st.write(f"Kolom: {df.columns.tolist()}")
    
    st.subheader("Data Artikel")
    # Cek apakah kolom image_url ada
    if 'image_url' in df.columns:
        display_df = df[["title", "url", "image_url"]].copy()
        st.dataframe(display_df)
        
        # Hitung statistik gambar
        images_count = len(df[df["image_url"] != "No Image"])
        st.write(f"Artikel dengan gambar: {images_count}/{len(df)}")
    else:
        st.warning("Kolom 'image_url' tidak ditemukan dalam data!")
        display_df = df[["title", "url"]].copy()
        st.dataframe(display_df)

    # Tambahan: Preview gambar sampul
    st.subheader("Preview Gambar Sampul Artikel")
    
    # Filter artikel yang memiliki gambar
    articles_with_images = df[df["image_url"] != "No Image"].head(10)
    
    if not articles_with_images.empty:
        cols = st.columns(2)
        for idx, (_, row) in enumerate(articles_with_images.iterrows()):
            with cols[idx % 2]:
                st.write(f"**{row['title'][:50]}...**")
                try:
                    st.image(row['image_url'], width=300)
                except:
                    st.write("❌ Gambar tidak dapat dimuat")
                st.write(f"[Baca artikel]({row['url']})")
                st.markdown("---")
    else:
        st.warning("Tidak ada artikel dengan gambar yang ditemukan.")

    st.subheader("Word Cloud")
    all_text = " ".join(df["title"].tolist() + df["content"].tolist())
    clean_text = remove_stopwords(all_text)
    clean_text2 = bersihkan_teks(clean_text)
    wordcloud = WordCloud(width=1000, height=500, background_color="white").generate(clean_text2)

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.imshow(wordcloud, interpolation="bilinear")
    ax.axis("off")
    st.pyplot(fig)

    st.subheader("Tren Kata Terbanyak (Top 20)")
    word_freq = Counter(clean_text2.split())
    top_words = word_freq.most_common(20)
    wc_df = pd.DataFrame(top_words, columns=["Kata", "Frekuensi"])

    fig2, ax2 = plt.subplots(figsize=(12, 6))
    sns.barplot(data=wc_df, x="Frekuensi", y="Kata", ax=ax2, palette="Blues_d")
    ax2.set_title("20 Kata Paling Sering Muncul")
    ax2.bar_label(ax2.containers[0], fmt="%d")
    st.pyplot(fig2)

    st.subheader("Jumlah Artikel per Bulan")
    monthly_counts = df["month_year"].value_counts().sort_index()
    fig3, ax3 = plt.subplots(figsize=(12, 6))
    sns.barplot(x=monthly_counts.index, y=monthly_counts.values, ax=ax3, palette="viridis")
    ax3.set_title("Jumlah Artikel Diposting per Bulan")
    ax3.set_xlabel("Bulan")
    ax3.set_ylabel("Jumlah Artikel")
    plt.xticks(rotation=45)
    st.pyplot(fig3)

    # Statistik gambar
    st.subheader("Statistik Gambar")
    total_articles = len(df)
    articles_with_images = len(df[df["image_url"] != "No Image"])
    st.metric("Total Artikel", total_articles)
    st.metric("Artikel dengan Gambar", articles_with_images)
    st.metric("Persentase Artikel dengan Gambar", f"{(articles_with_images/total_articles*100):.1f}%")

else:
    st.info("Belum ada data untuk ditampilkan. Silakan jalankan scraping terlebih dahulu.")