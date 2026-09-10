import streamlit as st
import pandas as pd
import feedparser
import requests
from tvDatafeed import TvDatafeed, Interval
import warnings

warnings.filterwarnings("ignore")

st.set_page_config(page_title="IDX Full Market Hunter", layout="wide", page_icon="🎯")

# ============================================================
# KONFIGURASI KEAMANAN & TELEGRAM
# ============================================================
try:
    TELEGRAM_TOKEN = st.secrets["TELEGRAM_TOKEN"]
    TELEGRAM_CHAT_ID = st.secrets["TELEGRAM_CHAT_ID"]
except:
    TELEGRAM_TOKEN = ""
    TELEGRAM_CHAT_ID = ""

def send_telegram_alert(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=5)
    except:
        pass

# ============================================================
# DATA ENGINES (Otomatis Tarik Seluruh Saham BEI)
# ============================================================
@st.cache_resource
def init_tv():
    try: return TvDatafeed()
    except: return None

tv = init_tv()

@st.cache_data(ttl=86400, show_spinner=False)
def get_all_idx_tickers():
    """Mengambil 900+ kode saham BEI dari database publik"""
    tickers = []
    # Jalur 1: HuggingFace API
    try:
        url = "https://datasets-server.huggingface.co/rows?dataset=kjhq/Indonesia-Stock-Symbols-and-Metadata&config=default&split=train&offset=0&length=1000"
        r = requests.get(url, timeout=10)
        rows = r.json()["rows"]
        tickers = [x["row"]["ticker"].upper().replace(".JK", "") for x in rows if len(x["row"]["ticker"].replace(".JK", "")) == 4]
    except:
        pass

    # Jalur 2: Fallback GitHub Public CSV jika API di atas sibuk
    if len(tickers) < 500:
        try:
            url_backup = "https://raw.githubusercontent.com/yunanp/id-stock-ticker/main/tickers.csv"
            df = pd.read_csv(url_backup)
            tickers = [str(t).upper().replace(".JK", "") for t in df.iloc[:, 0].tolist() if len(str(t).replace(".JK", "")) == 4]
        except:
            pass
            
    return list(set(tickers))

def get_news_sentiment(ticker):
    url = f"https://news.google.com/rss/search?q={ticker}+saham+OR+BEI&hl=id&gl=ID&ceid=ID:id"
    try:
        feed = feedparser.parse(url)
        if not feed.entries: return "Netral", 0
        pos_words = ['laba', 'naik', 'akuisisi', 'dividen', 'meroket', 'ekspansi', 'investasi', 'lonjak']
        neg_words = ['rugi', 'turun', 'anjlok', 'suspen', 'gugat', 'utang', 'bangkrut', 'pidana', 'pkpu']
        pos_score = sum(1 for entry in feed.entries[:5] for word in pos_words if word in entry.title.lower())
        neg_score = sum(1 for entry in feed.entries[:5] for word in neg_words if word in entry.title.lower())
        if pos_score > neg_score: return "🔥 Bullish", pos_score
        elif neg_score > pos_score: return "⚠️ Bearish", -neg_score
        return "Netral", 0
    except:
        return "Netral", 0

# ============================================================
# CORE ANALYTICS (Hanya Loloskan Saham Potensial)
# ============================================================
def process_stock(ticker, tv_instance, min_adv):
    try:
        df = tv_instance.get_hist(symbol=ticker, exchange='IDX', interval=Interval.in_daily, n_bars=250)
        if df is None or len(df) < 150: return None
            
        c, l, v = df['close'], df['low'], df['volume']
        current_price = c.iloc[-1]
        
        # Filter Saham Suspend / Gocap Murni
        if current_price < 50: return None 
        
        ma20 = c.rolling(20).mean().iloc[-1]
        ma50 = c.rolling(50).mean().iloc[-1]
        ma200 = c.rolling(200).mean().iloc[-1]
        vol20 = v.rolling(20).mean().iloc[-1]
        
        # Filter Uang Riil (Anti-Gorengan)
        avg_daily_value = vol20 * current_price
        if avg_daily_value < min_adv: return None 
        
        vol_spike = v.iloc[-1] / (vol20 if vol20 > 0 else 1)
        is_breakout = current_price >= (c.tail(120).max() * 0.95)
        
        # Skor Awal (Teknikal & Volume)
        score = 0
        if current_price > ma20 and ma20 > ma50 > ma200: score += 25
        if is_breakout: score += 25
        if vol_spike > 2.5: score += 30
        
        # PEMOTONGAN CEPAT: Jika skor teknikal < 50, langsung buang (Hemat waktu scan)
        if score < 50:
            return None 
            
        # Cek sentimen berita hanya untuk saham yang secara grafik sudah siap terbang
        sentiment_label, sentiment_score = get_news_sentiment(ticker)
        if sentiment_score > 0: score += 20
        
        if score >= 80: phase = "🎯 STRONG BUY"
        else: phase = "👀 ACCUMULATE"
        
        # Risk Management (SL Terukur & Target Profit)
        stop_loss = l.tail(5).min() * 0.98 
        if current_price - stop_loss > (current_price * 0.15):
            stop_loss = current_price * 0.90 
        target_price = current_price + ((current_price - stop_loss) * 2.5) 
        
        return {
            "Ticker": ticker,
            "Harga": current_price,
            "ADV_Miliar": avg_daily_value / 1e9,
            "Vol_Spike": vol_spike,
            "Sentimen": sentiment_label,
            "Skor": score,
            "Fase": phase,
            "Stop_Loss": stop_loss,
            "Target": target_price
        }
    except:
        return None

# ============================================================
# USER INTERFACE
# ============================================================
st.title("🎯 IDX Full Market Scanner")
st.markdown("Algoritma ini memindai **seluruh emiten BEI** secara buta dan hanya memunculkan yang siap meledak berdasarkan *Price Action*, Volume, dan Sentimen.")

with st.sidebar:
    st.header("⚙️ Pengaturan Dana Riil")
    
    # Mengambil total saham asli dari BEI
    semua_saham = get_all_idx_tickers()
    total_saham = len(semua_saham) if len(semua_saham) > 0 else 920
    
    max_scan = st.slider("Jumlah Saham Discan", 100, total_saham, total_saham, 50)
    min_adv_input = st.number_input("Min. Transaksi Harian (Miliar Rp)", min_value=0.5, max_value=50.0, value=2.0, step=0.5)
    min_adv = min_adv_input * 1_000_000_000
    
    st.markdown("---")
    run_scan = st.button("🚀 MULAI SCAN SELURUH PASAR", type="primary", use_container_width=True)

if run_scan:
    if tv is None:
        st.error("Koneksi ke penyedia data grafik gagal. Silakan coba lagi.")
        st.stop()
        
    if total_saham == 0:
        st.error("Gagal menarik daftar saham BEI dari database publik. Cek koneksi internet server.")
        st.stop()

    TICKERS = semua_saham[:max_scan]
    results = []
    alerts = []
    
    progress_text = f"Memindai {max_scan} saham BEI... Saham stagnan otomatis dibuang."
    my_bar = st.progress(0, text=progress_text)
    
    for i, ticker in enumerate(TICKERS):
        data = process_stock(ticker, tv, min_adv)
        if data:
            results.append(data)
            # Notifikasi Telegram HANYA untuk Strong Buy agar tidak spam
            if data["Skor"] >= 80:
                msg = (f"🎯 *FULL MARKET ALERT* 🎯\n\n"
                       f"Saham: *{data['Ticker']}*\n"
                       f"Harga Entry: Rp {int(data['Harga']):,}\n"
                       f"Target Profit: Rp {int(data['Target']):,} 🚀\n"
                       f"Stop Loss: Rp {int(data['Stop_Loss']):,} 🛑\n\n"
                       f"Ledakan Volume: {data['Vol_Spike']:.1f}x\n"
                       f"Katalis Berita: {data['Sentimen']}\n"
                       f"Skor Algoritma: {data['Skor']}/100")
                alerts.append(msg)
                
        my_bar.progress((i + 1) / len(TICKERS), text=f"Sedang menganalisis: {ticker} ({i+1}/{len(TICKERS)})")
        
    if alerts:
        send_telegram_alert("\n\n---\n\n".join(alerts))
        st.toast(f"Berhasil mendeteksi {len(alerts)} saham Strong Buy! Alert dikirim ke Telegram.", icon="🚀")

    if results:
        df = pd.DataFrame(results).sort_values(by="Skor", ascending=False).reset_index(drop=True)
        
        show = df.copy()
        show["Harga"] = show["Harga"].apply(lambda x: f"Rp {int(x):,}")
        show["Target"] = show["Target"].apply(lambda x: f"Rp {int(x):,}")
        show["Stop_Loss"] = show["Stop_Loss"].apply(lambda x: f"Rp {int(x):,}")
        show["ADV_Miliar"] = show["ADV_Miliar"].apply(lambda x: f"Rp {x:.1f} M")
        show["Vol_Spike"] = show["Vol_Spike"].apply(lambda x: f"{x:.1f}x")
        
        cols = ["Ticker", "Fase", "Skor", "Harga", "Stop_Loss", "Target", "Vol_Spike", "Sentimen", "ADV_Miliar"]
        show = show[cols]
        
        def color_cells(val):
            if "STRONG BUY" in str(val): return 'background-color: #006600; color: white; font-weight:bold;'
            elif "ACCUMULATE" in str(val): return 'background-color: #997300; color: white;'
            elif "Bullish" in str(val): return 'color: #00cc00; font-weight:bold;'
            elif "Bearish" in str(val): return 'color: #cc0000; font-weight:bold;'
            return ''
            
        st.success(f"Analisis Selesai! Dari {max_scan} saham, hanya {len(results)} saham ini yang terdeteksi sedang diakumulasi bandar dan siap terbang.")
        st.dataframe(show.style.applymap(color_cells, subset=['Fase', 'Sentimen']), use_container_width=True, height=600)
    else:
        st.warning(f"Analisis selesai. Dari {max_scan} saham yang discan, tidak ada satupun yang memenuhi syarat teknikal (Semua sedang turun/stagnan).")
