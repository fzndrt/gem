import streamlit as st
import pandas as pd
import feedparser
import requests
from tvDatafeed import TvDatafeed, Interval
import warnings

warnings.filterwarnings("ignore")

st.set_page_config(page_title="IDX Ultimate Hunter", layout="wide", page_icon="🦅")

# ============================================================
# 1. KONFIGURASI KEAMANAN & TELEGRAM
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
# 2. DATA ENGINES (Optimized for Speed)
# ============================================================
@st.cache_resource
def init_tv():
    try: return TvDatafeed()
    except: return None

tv = init_tv()

@st.cache_data(ttl=86400, show_spinner=False)
def get_all_idx_tickers():
    try:
        url = "https://datasets-server.huggingface.co/rows?dataset=kjhq/Indonesia-Stock-Symbols-and-Metadata&config=default&split=train&offset=0&length=1000"
        r = requests.get(url, timeout=10)
        rows = r.json()["rows"]
        tickers = [x["row"]["ticker"].upper().replace(".JK", "") for x in rows if len(x["row"]["ticker"].replace(".JK", "")) == 4]
        return list(set(tickers))
    except:
        fallback = "AALI ABMM ACES ADRO AKRA AMMN ANTM ARTO ASII BBCA BBNI BBRI BMRI BREN BRPT BUMI CUAN DCII ENRG ESSA GOTO HRUM ICBP INCO INDF INTP ITMG KLBF MDKA MEDC MGLV PANI PGAS PTBA SMGR TLKM TOWR UNTR WIKA"
        return fallback.split()

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
# 3. CORE ANALYTICS (Hanya Loloskan Saham Potensial)
# ============================================================
def process_stock(ticker, tv_instance, min_adv):
    try:
        df = tv_instance.get_hist(symbol=ticker, exchange='IDX', interval=Interval.in_daily, n_bars=250)
        if df is None or len(df) < 150: return None
            
        c, l, v = df['close'], df['low'], df['volume']
        current_price = c.iloc[-1]
        if current_price < 50: return None 
        
        ma20 = c.rolling(20).mean().iloc[-1]
        ma50 = c.rolling(50).mean().iloc[-1]
        ma200 = c.rolling(200).mean().iloc[-1]
        vol20 = v.rolling(20).mean().iloc[-1]
        
        avg_daily_value = vol20 * current_price
        if avg_daily_value < min_adv: return None 
        
        vol_spike = v.iloc[-1] / (vol20 if vol20 > 0 else 1)
        is_breakout = current_price >= (c.tail(120).max() * 0.95)
        
        # Skor Awal (Tanpa Sentimen)
        score = 0
        if current_price > ma20 and ma20 > ma50 > ma200: score += 25
        if is_breakout: score += 25
        if vol_spike > 2.5: score += 30
        
        # FILTER KETAT: Buang saham jika skor di bawah 50 (Mencegah lemot)
        if score < 50:
            return None 
            
        # Jika lolos teknikal, baru cek sentimen berita
        sentiment_label, sentiment_score = get_news_sentiment(ticker)
        if sentiment_score > 0: score += 20
        
        if score >= 80: phase = "🎯 STRONG BUY"
        else: phase = "👀 ACCUMULATE"
        
        # Risk Management
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
# 4. USER INTERFACE
# ============================================================
st.title("🦅 IDX Ultimate Hunter")
st.markdown("Hanya menampilkan saham dengan potensi **Strong Buy** atau **Accumulate**. Saham sideways/turun otomatis disembunyikan.")

with st.sidebar:
    st.header("⚙️ Pengaturan Filter")
    max_scan = st.slider("Maksimum Saham Discan (Semakin besar makin lama)", 50, 900, 300, 50)
    min_adv_input = st.number_input("Min. Nilai Transaksi (Miliar Rp)", min_value=1.0, value=2.5, step=0.5)
    min_adv = min_adv_input * 1_000_000_000
    
    st.markdown("---")
    run_scan = st.button("🚀 EKSEKUSI SCANNING", type="primary", use_container_width=True)

if run_scan:
    if tv is None:
        st.error("Koneksi TradingView Gagal. Coba lagi nanti.")
        st.stop()
        
    TICKERS = get_all_idx_tickers()[:max_scan]
    results = []
    alerts = []
    
    # Progress Bar agar tidak terlihat hang
    progress_text = "Memindai bursa... Mohon tunggu."
    my_bar = st.progress(0, text=progress_text)
    
    for i, ticker in enumerate(TICKERS):
        data = process_stock(ticker, tv, min_adv)
        if data:
            results.append(data)
            if data["Skor"] >= 80:
                msg = (f"🎯 *HIGH CONVICTION ALERT* 🎯\n\n"
                       f"Saham: *{data['Ticker']}*\n"
                       f"Harga Entry: Rp {int(data['Harga']):,}\n"
                       f"Target Profit: Rp {int(data['Target']):,} 🚀\n"
                       f"Stop Loss: Rp {int(data['Stop_Loss']):,} 🛑\n\n"
                       f"Volume Spike: {data['Vol_Spike']:.1f}x\n"
                       f"Skor Algoritma: {data['Skor']}/100")
                alerts.append(msg)
                
        my_bar.progress((i + 1) / len(TICKERS), text=f"Memindai {ticker} ({i+1}/{len(TICKERS)})")
        
    if alerts:
        send_telegram_alert("\n\n---\n\n".join(alerts))
        st.toast("Alert Terkirim ke Telegram!", icon="🔥")

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
            
        st.success(f"Ditemukan {len(results)} saham yang siap terbang dari {max_scan} saham yang discan.")
        st.dataframe(show.style.applymap(color_cells, subset=['Fase', 'Sentimen']), use_container_width=True, height=500)
    else:
        st.warning("Tidak ada satupun saham yang memenuhi kriteria Strong Buy atau Accumulate saat ini.")
