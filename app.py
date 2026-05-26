import streamlit as st
import json, re
from datetime import datetime

# ── страница ──────────────────────────────────────────────
st.set_page_config(page_title="Speculator AI", page_icon="📈", layout="wide")

try:
    import anthropic
except ImportError:
    st.error("❌ anthropic не установлен"); st.stop()

try:
    import yfinance as yf
    import pandas as pd
    YFINANCE_OK = True
except ImportError:
    YFINANCE_OK = False

# ════════════════════════════════════════════════════════
# localStorage BRIDGE
# Принцип:
#   1. JS читает localStorage["speculator_data"] при старте
#   2. Если данные есть — передаёт через ?_ls_loaded=1 + sessionStorage
#   3. Python при первом запуске подхватывает через JS→input компонент
# ════════════════════════════════════════════════════════

LS_KEY = "speculator_data"

def ls_load_component():
    """Рендерит невидимый JS-мост. Возвращает JSON-строку или None."""
    import streamlit.components.v1 as components
    result = components.html(f"""
<script>
(function() {{
    var data = localStorage.getItem("{LS_KEY}");
    var input = window.parent.document.querySelector('input[data-ls-bridge]');
    if (!input) {{
        input = window.parent.document.createElement('input');
        input.setAttribute('data-ls-bridge', '1');
        input.style.display = 'none';
        window.parent.document.body.appendChild(input);
    }}
    if (data) {{
        input.value = data;
        input.dispatchEvent(new Event('input', {{bubbles: true}}));
    }}
}})();
</script>
""", height=0)
    return result

def ls_save(portfolio, history):
    """Сохраняет данные в localStorage через JS."""
    import streamlit.components.v1 as components
    payload = json.dumps({
        "portfolio": portfolio,
        "history":   history,
        "next_id":   st.session_state.get("next_id", 10),
        "saved_at":  datetime.now().isoformat(),
    }, ensure_ascii=False)
    # Экранируем для вставки в JS-строку
    safe = payload.replace("\\", "\\\\").replace("`", "\\`")
    components.html(f"""
<script>
try {{
    localStorage.setItem("{LS_KEY}", `{safe}`);
}} catch(e) {{
    console.warn("localStorage save failed:", e);
}}
</script>
""", height=0)

def ls_clear():
    import streamlit.components.v1 as components
    components.html(f"""
<script>
localStorage.removeItem("{LS_KEY}");
</script>
""", height=0)

# ── DEFAULT PORTFOLIO ─────────────────────────────────────
DEFAULT_PORTFOLIO = [
    {"id":1,"ticker":"APPS","sector":"Ad Tech",
     "lots":[{"shares":50,"price":2.10},{"shares":80,"price":1.60}]},
    {"id":2,"ticker":"HUYA","sector":"China ADR",
     "lots":[{"shares":100,"price":3.20}]},
    {"id":3,"ticker":"DOYU","sector":"China ADR",
     "lots":[{"shares":200,"price":1.05},{"shares":150,"price":0.85}]},
    {"id":4,"ticker":"PBR","sector":"Energy",
     "lots":[{"shares":30,"price":13.50}]},
    {"id":5,"ticker":"ICAD","sector":"MedTech",
     "lots":[{"shares":400,"price":0.60},{"shares":300,"price":0.45}]},
    {"id":6,"ticker":"NVNO","sector":"Biotech",
     "lots":[{"shares":500,"price":0.30}]},
]

# ── session state init ────────────────────────────────────
if "ls_checked"  not in st.session_state: st.session_state.ls_checked  = False
if "ls_data"     not in st.session_state: st.session_state.ls_data     = None
if "portfolio"   not in st.session_state: st.session_state.portfolio   = None
if "next_id"     not in st.session_state: st.session_state.next_id     = 10
if "results"     not in st.session_state: st.session_state.results     = {}
if "selected"    not in st.session_state: st.session_state.selected    = None
if "history"     not in st.session_state: st.session_state.history     = {}
if "portfolio_analysis" not in st.session_state: st.session_state.portfolio_analysis = None
if "dark_mode"   not in st.session_state: st.session_state.dark_mode   = True
if "ls_dirty"    not in st.session_state: st.session_state.ls_dirty    = False

# ── читаем localStorage один раз при старте ───────────────
# Streamlit не имеет прямого JS→Python канала, поэтому используем
# st.query_params как одностороннюю шину: JS пишет, Python читает.
# Схема: JS записывает данные в sessionStorage["ls_payload"],
# потом добавляет ?_ls=1 в URL → Streamlit делает rerun → Python читает.

qp = st.query_params
if not st.session_state.ls_checked:
    ls_payload = qp.get("_ls")
    if ls_payload:
        try:
            loaded = json.loads(ls_payload)
            st.session_state.portfolio = loaded.get("portfolio", DEFAULT_PORTFOLIO)
            st.session_state.history   = {int(k): v for k, v in loaded.get("history", {}).items()}
            st.session_state.next_id   = loaded.get("next_id", 10)
            st.query_params.clear()
        except Exception:
            st.session_state.portfolio = DEFAULT_PORTFOLIO
    else:
        st.session_state.portfolio = DEFAULT_PORTFOLIO
    st.session_state.ls_checked = True

# Если портфель ещё None (не должно быть, но на всякий случай)
if st.session_state.portfolio is None:
    st.session_state.portfolio = DEFAULT_PORTFOLIO

# ── JS-загрузчик localStorage (рендерится только при первом запуске) ──
if not qp.get("_ls") and "ls_boot_done" not in st.session_state:
    st.session_state.ls_boot_done = True
    import streamlit.components.v1 as components
    components.html(f"""
<script>
(function() {{
    var raw = localStorage.getItem("{LS_KEY}");
    if (!raw) return;                       // нет данных — стандартный портфель
    try {{
        JSON.parse(raw);                    // валидируем JSON
    }} catch(e) {{
        return;
    }}
    // Передаём через query param (URL-encode)
    var encoded = encodeURIComponent(raw);
    var url = window.parent.location.origin +
              window.parent.location.pathname +
              '?_ls=' + encoded;
    window.parent.location.href = url;
}})();
</script>
""", height=0)

# ── ТЕМА ─────────────────────────────────────────────────
if st.session_state.dark_mode:
    BG, BG2, BG3      = "#080b12","#0d1520","#111927"
    BORDER             = "#1e2a3a"
    TEXT, TEXT_DIM     = "#e8eaf0","#8899aa"
    TEXT_MUTE          = "#3a5070"
    LABEL_CSS          = "color:#3a5070"
    SIDEBAR_BG         = "#0d1520"
else:
    BG, BG2, BG3      = "#f0f4f8","#ffffff","#e8eef5"
    BORDER             = "#c8d8e8"
    TEXT, TEXT_DIM     = "#0d1a2a","#3a5070"
    TEXT_MUTE          = "#8899aa"
    LABEL_CSS          = "color:#8899aa"
    SIDEBAR_BG         = "#e0e8f0"

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600;700&display=swap');
html,body,[class*="css"]{{font-family:'IBM Plex Mono',monospace;}}
.stApp{{background-color:{BG};color:{TEXT};}}
div[data-testid="stSidebar"]{{background-color:{SIDEBAR_BG};}}
.stDataFrame{{background-color:{BG2};}}
.stTabs [data-baseweb="tab-list"]{{background-color:{BG2};border-radius:8px;}}
.stTabs [data-baseweb="tab"]{{color:{TEXT_DIM};}}
.stTabs [aria-selected="true"]{{color:{TEXT};}}
.label{{{LABEL_CSS};font-size:10px;text-transform:uppercase;letter-spacing:1px;}}
p,li,span{{color:{TEXT};}}
.stAlert p{{color:inherit!important;}}
</style>
""", unsafe_allow_html=True)

# ── HELPERS ───────────────────────────────────────────────
def avg_price(lots):
    sh = sum(l["shares"] for l in lots)
    return sum(l["shares"]*l["price"] for l in lots)/sh if sh>0 else 0
def total_shares(lots): return sum(l["shares"] for l in lots)
def total_cost(lots):   return sum(l["shares"]*l["price"] for l in lots)

def save_to_ls():
    """Сохранить текущий портфель и историю в localStorage."""
    ls_save(st.session_state.portfolio, st.session_state.history)

REC_EMOJI = {"STRONG BUY":"🟢","BUY MORE":"🔵","HOLD":"🔷","REDUCE":"🟡","SELL":"🟠","URGENT SELL":"🔴"}
REC_RU    = {"STRONG BUY":"СИЛЬНАЯ ПОКУПКА","BUY MORE":"ДОКУПИТЬ","HOLD":"ДЕРЖАТЬ",
             "REDUCE":"СОКРАТИТЬ","SELL":"ПРОДАТЬ","URGENT SELL":"СРОЧНО ПРОДАТЬ"}
REC_COLOR = {"STRONG BUY":"#a8ff3e","BUY MORE":"#54a0ff","HOLD":"#00e5ff",
             "REDUCE":"#ffd700","SELL":"#ff6b35","URGENT SELL":"#ff3ea8"}
RISK_COLOR= {"LOW":"#a8ff3e","MEDIUM":"#ffd700","HIGH":"#ff6b35","VERY HIGH":"#ff3ea8","EXTREME":"#ff3ea8"}
RISK_RU   = {"LOW":"НИЗКИЙ","MEDIUM":"СРЕДНИЙ","HIGH":"ВЫСОКИЙ","VERY HIGH":"ОЧЕНЬ ВЫСОКИЙ","EXTREME":"ЭКСТРЕМАЛЬНЫЙ"}
AVD_COLOR = {"SMART":"#a8ff3e","NEUTRAL":"#ffd700","MISTAKE":"#ff3ea8"}
AVD_RU    = {"SMART":"ГРАМОТНО ✓","NEUTRAL":"НЕЙТРАЛЬНО","MISTAKE":"ОШИБКА ✗"}

# ── YAHOO FINANCE ─────────────────────────────────────────
@st.cache_data(ttl=300)
def get_market_data(ticker, period="3mo"):
    if not YFINANCE_OK: return None
    try:
        t    = yf.Ticker(ticker)
        hist = t.history(period=period)
        if hist.empty: return None
        price      = round(float(hist["Close"].iloc[-1]),4)
        prev_close = round(float(hist["Close"].iloc[-2]),4) if len(hist)>1 else price
        change_pct = round((price-prev_close)/prev_close*100,2)
        tail       = hist["Close"].tail(252)
        return {"price":price,"change_pct":change_pct,
                "high_52w":round(float(tail.max()),4),
                "low_52w":round(float(tail.min()),4),
                "volume":int(hist["Volume"].iloc[-1]),
                "history":hist[["Close","Volume"]].copy()}
    except Exception: return None

# ── AI АНАЛИЗ ─────────────────────────────────────────────
def analyze_stock(pos, mkt=None):
    avg=avg_price(pos["lots"]); sh=total_shares(pos["lots"]); cost=total_cost(pos["lots"])
    pl_pct=((mkt["price"]-avg)/avg*100) if mkt and avg>0 else None
    ad_count=len(pos["lots"])
    highest_buy=max(l["price"] for l in pos["lots"])
    avg_down_pct=((highest_buy-avg)/highest_buy*100) if ad_count>1 else 0
    market_facts=""
    if mkt:
        market_facts=f"""
REAL MARKET DATA:
- Current price: ${mkt["price"]}
- Change today: {mkt["change_pct"]:+.2f}%
- 52w High: ${mkt["high_52w"]} | 52w Low: ${mkt["low_52w"]}
- Volume today: {mkt["volume"]:,}
- Trader P&L vs avg: {pl_pct:+.1f}%"""
    prompt=f"""You are a prop-desk trader. Analyze this speculative position.
STOCK: {pos["ticker"]} [{pos.get("sector","Unknown")}]
POSITION: {sh} shares | Avg entry: ${avg:.4f} | Total invested: ${cost:.2f}
LOTS: {", ".join(f"Lot{i+1}: {l['shares']}sh@${l['price']}" for i,l in enumerate(pos["lots"]))}
{f"Averaged down {ad_count} times, reduced avg by {avg_down_pct:.1f}%" if ad_count>1 else "Single entry."}
{market_facts}
Return ONLY valid JSON, no markdown:
{{"recommendation":"HOLD","risk":"HIGH","confidence":55,"delistingRisk":false,"dilutionRisk":"MEDIUM","avgDownVerdict":"NEUTRAL","avgDownReason":"one sentence","context":"2-3 sentences","speculatorTip":"specific trade plan","catalysts":["c1","c2"],"risks":["r1","r2"],"targetLow":0.00,"targetBase":0.00,"targetHigh":0.00,"stopLoss":0.00,"psychNote":"bias note"}}
Rules: recommendation=STRONG BUY|BUY MORE|HOLD|REDUCE|SELL|URGENT SELL, risk=LOW|MEDIUM|HIGH|VERY HIGH|EXTREME, avgDownVerdict=SMART|NEUTRAL|MISTAKE"""
    client=anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
    msg=client.messages.create(model="claude-haiku-4-5-20251001",max_tokens=1000,
                               messages=[{"role":"user","content":prompt}])
    text=msg.content[0].text
    m=re.search(r'\{[\s\S]*\}',text)
    if not m: raise ValueError("JSON не найден")
    result=json.loads(m.group())
    if mkt:
        result["currentPrice"]=mkt["price"]; result["weekHigh52"]=mkt["high_52w"]
        result["weekLow52"]=mkt["low_52w"]; result["changeToday"]=mkt["change_pct"]
        result["volume"]=mkt["volume"]
    else:
        result.setdefault("currentPrice",avg)
    return result

def analyze_portfolio_summary():
    rows=[]
    for p in st.session_state.portfolio:
        if not p["lots"]: continue
        avg=avg_price(p["lots"]); cost=total_cost(p["lots"])
        mkt=get_market_data(p["ticker"]) if YFINANCE_OK else None
        pl=((mkt["price"]-avg)/avg*100) if mkt and avg>0 else None
        rows.append(f"{p['ticker']} [{p.get('sector','')}]: avg ${avg:.3f}, invested ${cost:.0f}"
                    +(f", current ${mkt['price']}, P&L {pl:+.1f}%" if pl is not None else ""))
    prompt=f"""Portfolio risk manager. Brief assessment in Russian (3-4 sentences max).
Focus: overall risk, sector concentration, biggest concerns, one actionable suggestion.
PORTFOLIO:\n{chr(10).join(rows)}\nRespond in Russian, plain text, no JSON, no markdown."""
    client=anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
    msg=client.messages.create(model="claude-haiku-4-5-20251001",max_tokens=300,
                               messages=[{"role":"user","content":prompt}])
    return msg.content[0].text

# ════════════════════════════════════════════════════════
# SIDEBAR
# ════════════════════════════════════════════════════════
with st.sidebar:
    col_logo,col_theme=st.columns([3,1])
    with col_logo:
        st.markdown("## 📊 Портфель")
    with col_theme:
        if st.button("☀️" if st.session_state.dark_mode else "🌙",key="theme_toggle"):
            st.session_state.dark_mode=not st.session_state.dark_mode
            st.rerun()

    grand=sum(total_cost(p["lots"]) for p in st.session_state.portfolio)
    st.caption(f"{len(st.session_state.portfolio)} позиций · ${grand:.2f} вложено")

    if st.session_state.selected is not None:
        if st.button("← Сводка",use_container_width=True,key="back"):
            st.session_state.selected=None; st.rerun()

    if not YFINANCE_OK: st.warning("⚠ yfinance не установлен")

    # ── статус сохранения ──
    st.markdown(
        f'<div style="background:{BG2};border:1px solid {"#a8ff3e33" if not st.session_state.ls_dirty else "#ffd70033"};'
        f'border-radius:6px;padding:6px 10px;font-size:11px;color:{"#a8ff3e" if not st.session_state.ls_dirty else "#ffd700"};margin-bottom:8px">'
        f'{"💾 Данные сохранены в браузере" if not st.session_state.ls_dirty else "⚠ Несохранённые изменения"}'
        f'</div>',
        unsafe_allow_html=True
    )
    if st.session_state.ls_dirty:
        if st.button("💾 Сохранить сейчас",use_container_width=True,key="save_now"):
            save_to_ls()
            st.session_state.ls_dirty=False
            st.rerun()

    if st.button("🗑 Очистить localStorage",use_container_width=True,key="clear_ls",
                 help="Сбросить сохранённые данные из браузера"):
        ls_clear()
        st.session_state.ls_checked=False
        st.session_state.portfolio=DEFAULT_PORTFOLIO
        st.session_state.history={}
        st.session_state.ls_dirty=False
        st.rerun()

    st.divider()

    with st.expander("➕ Новая акция"):
        nt=st.text_input("Тикер",key="nt",placeholder="GME").upper().strip()
        ns=st.text_input("Сектор",key="ns",placeholder="Gaming")
        if st.button("Добавить",use_container_width=True,key="btn_add"):
            if nt:
                st.session_state.portfolio.append(
                    {"id":st.session_state.next_id,"ticker":nt,"sector":ns,"lots":[]})
                st.session_state.next_id+=1
                save_to_ls(); st.session_state.ls_dirty=False
                st.rerun()

    st.divider()

    for pos in st.session_state.portfolio:
        avg=avg_price(pos["lots"]); sh=total_shares(pos["lots"])
        res=st.session_state.results.get(pos["id"])
        mkt=get_market_data(pos["ticker"]) if YFINANCE_OK else None
        live=mkt["price"] if mkt else (res["currentPrice"] if res else None)
        is_sel=st.session_state.selected==pos["id"]

        pl_html=""; price_html=f'<span style="color:#00e5ff;font-weight:700"> ${live}</span>' if live else ""
        if live and avg>0:
            pl=(live-avg)/avg*100; clr="#a8ff3e" if pl>=0 else "#ff3ea8"
            pl_html=f'<span style="color:{clr}"> {"+" if pl>=0 else ""}{pl:.1f}%</span>'
        chg_html=""
        if mkt and "change_pct" in mkt:
            ct=mkt["change_pct"]; ctc="#a8ff3e" if ct>=0 else "#ff3ea8"
            chg_html=f'<span style="color:{ctc};font-size:10px"> {"+" if ct>=0 else ""}{ct:.2f}%</span>'
        rec_html=""
        if res:
            rc=REC_COLOR.get(res.get("recommendation","HOLD"),"#00e5ff")
            rru=REC_RU.get(res.get("recommendation","HOLD"),"")
            rec_html=f'<br><span style="color:{rc};font-size:10px">{rru}</span>'

        bc="#00e5ff" if is_sel else BORDER; bw="2px" if is_sel else "1px"
        st.markdown(
            f'<div style="background:{BG2};border:{bw} solid {bc};border-radius:8px;'
            f'padding:10px 12px;margin-bottom:4px;color:{TEXT}">'
            f'<span style="color:#00e5ff;font-weight:700;font-size:15px">{pos["ticker"]}</span>'
            f'{price_html}{chg_html}'
            f'<span style="color:{TEXT_MUTE};font-size:10px"> {pos.get("sector","")}</span>'
            f'{rec_html}<br>'
            f'<span style="color:{TEXT_MUTE};font-size:11px">{sh}шт · ср.${avg:.4f}</span>'
            f'{pl_html}</div>',unsafe_allow_html=True)

        for i,lot in enumerate(pos["lots"]):
            c1,c2=st.columns([5,1])
            lpl_html=""
            if live:
                lpl=(live-lot["price"])/lot["price"]*100; lc="#a8ff3e" if lpl>=0 else "#ff3ea8"
                lpl_html=f'<span style="color:{lc}"> {"+" if lpl>=0 else ""}{lpl:.1f}%</span>'
            c1.markdown(f'<span style="font-size:11px;color:{TEXT_DIM}">л{i+1}: {lot["shares"]}шт×${lot["price"]}</span>{lpl_html}',unsafe_allow_html=True)
            if c2.button("✕",key=f"rm_{pos['id']}_{i}"):
                pos["lots"].pop(i); save_to_ls(); st.session_state.ls_dirty=False; st.rerun()

        with st.expander(f"+ лот к {pos['ticker']}"):
            ca,cb=st.columns(2)
            lsh=ca.number_input("Кол-во",min_value=0.0,step=1.0, key=f"lsh_{pos['id']}")
            lpr=cb.number_input("Цена $", min_value=0.0,step=0.01,key=f"lpr_{pos['id']}")
            if st.button("Добавить лот",key=f"al_{pos['id']}",use_container_width=True):
                if lsh>0 and lpr>0:
                    pos["lots"].append({"shares":lsh,"price":lpr})
                    save_to_ls(); st.session_state.ls_dirty=False; st.rerun()

        b1,b2=st.columns([3,1])
        if b1.button(f"▶ Анализ {pos['ticker']}",key=f"an_{pos['id']}",use_container_width=True):
            if not pos["lots"]: st.error("Добавьте лот")
            else:
                st.session_state.selected=pos["id"]
                with st.spinner(f"Анализирую {pos['ticker']}..."):
                    try:
                        mkt_data=get_market_data(pos["ticker"]) if YFINANCE_OK else None
                        result=analyze_stock(pos,mkt_data)
                        st.session_state.results[pos["id"]]=result
                        hist_entry={"date":datetime.now().strftime("%d.%m %H:%M"),
                                    "recommendation":result.get("recommendation","HOLD"),
                                    "price":result.get("currentPrice"),
                                    "pl_pct":None}
                        avg_pos=avg_price(pos["lots"])
                        if result.get("currentPrice") and avg_pos>0:
                            hist_entry["pl_pct"]=(result["currentPrice"]-avg_pos)/avg_pos*100
                        if pos["id"] not in st.session_state.history:
                            st.session_state.history[pos["id"]]=[]
                        st.session_state.history[pos["id"]].insert(0,hist_entry)
                        st.session_state.history[pos["id"]]=st.session_state.history[pos["id"]][:10]
                        save_to_ls(); st.session_state.ls_dirty=False
                        st.rerun()
                    except Exception as e: st.error(f"Ошибка: {e}")

        if b2.button("🗑",key=f"del_{pos['id']}",use_container_width=True):
            st.session_state.portfolio=[p for p in st.session_state.portfolio if p["id"]!=pos["id"]]
            st.session_state.results.pop(pos["id"],None)
            st.session_state.history.pop(pos["id"],None)
            if st.session_state.selected==pos["id"]: st.session_state.selected=None
            save_to_ls(); st.session_state.ls_dirty=False; st.rerun()

        st.markdown(f"<hr style='border-color:{BORDER};margin:6px 0'>",unsafe_allow_html=True)

# ════════════════════════════════════════════════════════
# ГЛАВНАЯ ОБЛАСТЬ
# ════════════════════════════════════════════════════════
sel_id  = st.session_state.selected
sel_pos = next((p for p in st.session_state.portfolio if p["id"]==sel_id),None)
sel_res = st.session_state.results.get(sel_id) if sel_id else None

# ── СВОДКА ───────────────────────────────────────────────
if not sel_res:
    st.markdown(f'<h1 style="color:{TEXT}">📈 Speculator AI</h1>',unsafe_allow_html=True)
    st.markdown(f'<p style="color:{TEXT_MUTE}">← Выбери акцию и нажми ▶ Анализ</p>',unsafe_allow_html=True)

    rows=[]
    for p in st.session_state.portfolio:
        r=st.session_state.results.get(p["id"])
        mkt=get_market_data(p["ticker"]) if YFINANCE_OK else None
        lp=mkt["price"] if mkt else (r.get("currentPrice") if r else None)
        avg=avg_price(p["lots"])
        pl=f'{"+" if lp and (lp-avg)/avg*100>=0 else ""}{(lp-avg)/avg*100:.1f}%' if lp and avg else "—"
        chg=f'{mkt["change_pct"]:+.2f}%' if mkt else "—"
        rec=REC_RU.get(r.get("recommendation",""),"") if r else "—"
        rows.append({"Тикер":p["ticker"],"Сектор":p.get("sector",""),
                     "Кол-во":int(total_shares(p["lots"])),"Ср.цена":f'${avg:.4f}',
                     "Тек.цена":f'${lp}' if lp else "—","Сегодня":chg,
                     "P&L":pl,"Вложено":f'${total_cost(p["lots"]):.2f}',"AI":rec})
    if rows:
        st.dataframe(rows,use_container_width=True,hide_index=True)

    st.divider()

    col_ai1,col_ai2=st.columns([3,1])
    with col_ai1:
        st.markdown(f'<h3 style="color:{TEXT}">🤖 Сводный AI анализ портфеля</h3>',unsafe_allow_html=True)
        st.caption("~$0.0003 · max 300 токенов · 3-4 предложения")
    with col_ai2:
        if st.button("▶ Анализировать",use_container_width=True,key="portfolio_analyze"):
            with st.spinner("Анализирую портфель..."):
                try:
                    st.session_state.portfolio_analysis={"text":analyze_portfolio_summary(),
                                                          "date":datetime.now().strftime("%d.%m.%Y %H:%M")}
                except Exception as e: st.error(f"Ошибка: {e}")

    if st.session_state.portfolio_analysis:
        pa=st.session_state.portfolio_analysis
        st.markdown(
            f'<div style="background:{BG2};border:1px solid #c77dff33;border-radius:8px;'
            f'padding:16px;color:{TEXT};line-height:1.8;margin-top:8px">'
            f'<div style="color:#c77dff;font-size:10px;margin-bottom:8px">AI · {pa["date"]}</div>'
            f'{pa["text"]}</div>',unsafe_allow_html=True)

    st.divider()

    has_history=any(st.session_state.history.get(p["id"]) for p in st.session_state.portfolio)
    if has_history:
        st.markdown(f'<h3 style="color:{TEXT}">📋 История анализов</h3>',unsafe_allow_html=True)
        for p in st.session_state.portfolio:
            hist=st.session_state.history.get(p["id"],[])
            if not hist: continue
            st.markdown(f'<span style="color:#00e5ff;font-weight:700">{p["ticker"]}</span>',unsafe_allow_html=True)
            for entry in hist:
                rec=entry.get("recommendation","HOLD"); rc=REC_COLOR.get(rec,"#00e5ff"); rru=REC_RU.get(rec,rec)
                price=f'${entry["price"]}' if entry.get("price") else "—"
                pl=entry.get("pl_pct"); plc="#a8ff3e" if pl and pl>=0 else "#ff3ea8"
                pl_s=f'{"+" if pl and pl>=0 else ""}{pl:.1f}%' if pl is not None else "—"
                st.markdown(
                    f'<div style="background:{BG2};border-left:3px solid {rc};border-radius:4px;'
                    f'padding:6px 12px;margin:3px 0;font-size:12px;color:{TEXT_DIM}">'
                    f'<span style="color:{TEXT_MUTE}">{entry["date"]}</span>'
                    f'  <span style="color:{rc};font-weight:700">{rru}</span>'
                    f'  <span style="color:{TEXT}">{price}</span>'
                    f'  <span style="color:{plc}">{pl_s}</span></div>',
                    unsafe_allow_html=True)
            st.markdown("<div style='margin-bottom:8px'></div>",unsafe_allow_html=True)

    st.stop()

# ════════════════════════════════════════════════════════
# РЕЗУЛЬТАТ АНАЛИЗА
# ════════════════════════════════════════════════════════
r=sel_res; pos=sel_pos; avg=avg_price(pos["lots"])
rec=r.get("recommendation","HOLD"); risk=r.get("risk","HIGH"); avd=r.get("avgDownVerdict","NEUTRAL")
rc=REC_COLOR.get(rec,"#00e5ff"); rkc=RISK_COLOR.get(risk,"#ffd700"); avdc=AVD_COLOR.get(avd,"#ffd700")
pl=(r.get("currentPrice",avg)-avg)/avg*100 if avg>0 else 0; plc="#a8ff3e" if pl>=0 else "#ff3ea8"

st.markdown(f'<h1><span style="color:#00e5ff">{pos["ticker"]}</span> '
            f'<span style="font-size:16px;color:{TEXT_MUTE}">{pos.get("sector","")}</span></h1>',
            unsafe_allow_html=True)

c1,c2,c3,c4=st.columns(4)
c1.markdown(
    f'<div style="background:{BG2};border:1px solid {rc}33;border-radius:8px;padding:14px;text-align:center">'
    f'<div class="label">Рекомендация</div>'
    f'<div style="color:{rc};font-size:16px;font-weight:700">{REC_EMOJI.get(rec,"")} {REC_RU.get(rec,rec)}</div>'
    f'<div style="color:{rc};font-size:11px">уверенность {r.get("confidence",0)}%</div></div>',
    unsafe_allow_html=True)

today_html=""
if "changeToday" in r:
    ct=r["changeToday"]; ctc="#a8ff3e" if ct>=0 else "#ff3ea8"
    today_html=f'<div style="color:{ctc};font-size:12px">{"+" if ct>=0 else ""}{ct:.2f}% сегодня</div>'
c2.markdown(
    f'<div style="background:{BG2};border:1px solid {BORDER};border-radius:8px;padding:14px;text-align:center">'
    f'<div class="label">Цена (реальная)</div>'
    f'<div style="color:{TEXT};font-size:26px;font-weight:700">${r.get("currentPrice","—")}</div>'
    f'{today_html}</div>',unsafe_allow_html=True)
c3.markdown(
    f'<div style="background:{BG2};border:1px solid {rkc}33;border-radius:8px;padding:14px;text-align:center">'
    f'<div class="label">Риск</div>'
    f'<div style="color:{rkc};font-size:16px;font-weight:700">{RISK_RU.get(risk,risk)}</div>'
    f'<div style="color:{TEXT_MUTE};font-size:11px">стоп ${r.get("stopLoss","—")}</div></div>',
    unsafe_allow_html=True)
c4.markdown(
    f'<div style="background:{BG2};border:1px solid {plc}33;border-radius:8px;padding:14px;text-align:center">'
    f'<div class="label">P&L позиции</div>'
    f'<div style="color:{plc};font-size:26px;font-weight:700">{"+" if pl>=0 else ""}{pl:.1f}%</div>'
    f'<div style="color:{TEXT_MUTE};font-size:11px">ср.вход ${avg:.4f}</div></div>',
    unsafe_allow_html=True)

if r.get("delistingRisk"): st.error("🚨 Высокий риск делистинга!")
st.divider()

# ── ГРАФИК ────────────────────────────────────────────────
st.markdown(f'<h4 style="color:{TEXT}">📈 График цены</h4>',unsafe_allow_html=True)
PERIODS={"1 нед":"5d","1 мес":"1mo","3 мес":"3mo","6 мес":"6mo","1 год":"1y","2 года":"2y"}
period_choice=st.radio("Период:",list(PERIODS.keys()),index=2,horizontal=True,label_visibility="collapsed")
mkt_chart=get_market_data(pos["ticker"],period=PERIODS[period_choice]) if YFINANCE_OK else None

if mkt_chart and mkt_chart.get("history") is not None:
    hist=mkt_chart["history"].copy()
    hist.index=pd.to_datetime(hist.index).tz_localize(None)
    hist["Ср. цена входа"]=avg
    hist=hist.rename(columns={"Close":pos["ticker"]})
    st.line_chart(hist[[pos["ticker"],"Ср. цена входа"]],color=["#00e5ff","#ff3ea8"],height=300)
    lot_cols=st.columns(len(pos["lots"]))
    for i,(lot,col) in enumerate(zip(pos["lots"],lot_cols)):
        lpl=(r["currentPrice"]-lot["price"])/lot["price"]*100 if r.get("currentPrice") else None
        lc="#a8ff3e" if lpl and lpl>=0 else "#ff3ea8"
        col.markdown(
            f'<div style="background:{BG2};border:1px solid {BORDER};border-radius:6px;'
            f'padding:8px;text-align:center">'
            f'<div style="color:{TEXT_MUTE};font-size:9px">ЛОТ {i+1}</div>'
            f'<div style="color:{TEXT};font-weight:700">${lot["price"]}</div>'
            f'{"<div style=color:"+lc+";font-size:11px>"+("+0" if lpl and lpl>=0 else "")+f"{lpl:.1f}%</div>" if lpl is not None else ""}'
            f'</div>',unsafe_allow_html=True)
    with st.expander("📊 Объём"):
        if "Volume" in hist.columns:
            st.bar_chart(hist[["Volume"]],height=120,color="#1e3a2a")
else:
    st.info("📡 График недоступен" if not YFINANCE_OK else "⚠ Нет данных для этого тикера")

st.divider()
m1,m2,m3,m4,m5=st.columns(5)
m1.metric("52н Макс",f'${r.get("weekHigh52","—")}')
m2.metric("52н Мин",f'${r.get("weekLow52","—")}')
m3.metric("Кап.",r.get("marketCap","—"))
m4.metric("Шорт %",r.get("shortInterest","—"))
m5.metric("Разводнение",r.get("dilutionRisk","—"))
st.divider()

tab1,tab2,tab3,tab4,tab5=st.tabs(["📰 Обзор","🎯 Торговый план","🧾 Покупки","🧠 Психология","📋 История"])

with tab1:
    st.markdown(f'<h4 style="color:{TEXT}">Ситуация</h4>',unsafe_allow_html=True)
    st.info(r.get("context",""))
    if len(pos["lots"])>1:
        st.markdown(f'<h4 style="color:{TEXT}">Усреднение</h4>',unsafe_allow_html=True)
        st.markdown(
            f'<div style="background:{BG2};border-left:3px solid {avdc};border-radius:6px;padding:12px">'
            f'<span style="color:{avdc};font-weight:700">{AVD_RU.get(avd,avd)}</span> — '
            f'<span style="color:{TEXT_DIM}">{r.get("avgDownReason","")}</span></div>',
            unsafe_allow_html=True)
    col1,col2=st.columns(2)
    with col1:
        st.markdown(f'<h4 style="color:{TEXT}">◈ Катализаторы</h4>',unsafe_allow_html=True)
        for c in r.get("catalysts",[]): st.markdown(f"• {c}")
    with col2:
        st.markdown(f'<h4 style="color:{TEXT}">▲ Риски</h4>',unsafe_allow_html=True)
        for rv in r.get("risks",[]): st.markdown(f"• {rv}")

with tab2:
    t1,t2,t3=st.columns(3)
    t1.markdown(
        f'<div style="background:{BG2};border:1px solid #ff3ea833;border-radius:8px;padding:16px;text-align:center">'
        f'<div class="label">МЕДВЕДЬ</div>'
        f'<div style="color:#ff3ea8;font-size:28px;font-weight:700">${r.get("targetLow","—")}</div></div>',
        unsafe_allow_html=True)
    t2.markdown(
        f'<div style="background:{BG2};border:1px solid #ffd70033;border-radius:8px;padding:16px;text-align:center">'
        f'<div class="label">БАЗА</div>'
        f'<div style="color:#ffd700;font-size:28px;font-weight:700">${r.get("targetBase","—")}</div></div>',
        unsafe_allow_html=True)
    t3.markdown(
        f'<div style="background:{BG2};border:1px solid {rc}33;border-radius:8px;padding:16px;text-align:center">'
        f'<div class="label">БЫК</div>'
        f'<div style="color:{rc};font-size:28px;font-weight:700">${r.get("targetHigh","—")}</div></div>',
        unsafe_allow_html=True)
    if r.get("currentPrice") and r.get("stopLoss") and r.get("targetBase"):
        risk_a=r.get("currentPrice",0)-r.get("stopLoss",0); rew_a=r.get("targetBase",0)-r.get("currentPrice",0)
        if risk_a>0 and rew_a>0:
            rr=rew_a/risk_a; rrc="#a8ff3e" if rr>=2 else "#ffd700" if rr>=1 else "#ff3ea8"
            st.markdown(
                f'**R/R:** <span style="color:#ff3ea8">-{risk_a/r.get("currentPrice",1)*100:.1f}%</span> / '
                f'<span style="color:#a8ff3e">+{rew_a/r.get("currentPrice",1)*100:.1f}%</span> · '
                f'<span style="color:{rrc};font-weight:700">{rr:.1f}:1</span>',
                unsafe_allow_html=True)
    st.markdown(f'<h4 style="color:{TEXT}">💡 Торговый план</h4>',unsafe_allow_html=True)
    st.markdown(
        f'<div style="background:rgba(199,125,255,.08);border:1px solid #c77dff33;'
        f'border-radius:8px;padding:16px;color:#c77dff;line-height:1.8">'
        f'{r.get("speculatorTip","")}</div>',unsafe_allow_html=True)
    st.markdown(f"**Стоп-лосс:** :red[${r.get('stopLoss','—')}]")

with tab3:
    live_p=r.get("currentPrice"); total_pnl=0
    for i,lot in enumerate(pos["lots"]):
        lpl=(live_p-lot["price"])/lot["price"]*100 if live_p else None
        lc="#a8ff3e" if lpl and lpl>=0 else "#ff3ea8"
        pnl_u=(live_p-lot["price"])*lot["shares"] if live_p else None
        if pnl_u: total_pnl+=pnl_u
        st.markdown(
            f'<div style="background:{BG2};border:1px solid {BORDER};border-radius:6px;'
            f'padding:10px 14px;margin-bottom:6px;color:{TEXT}">'
            f'Лот {i+1}: <b>{lot["shares"]}шт × ${lot["price"]}</b> = ${lot["shares"]*lot["price"]:.2f}'
            f'<span style="color:{lc};font-weight:700;float:right">'
            f'{"+" if lpl and lpl>=0 else ""}{lpl:.1f}%  '
            f'{"+" if pnl_u and pnl_u>=0 else ""}{"${:.2f}".format(pnl_u) if pnl_u else ""}'
            f'</span></div>',unsafe_allow_html=True)
    if live_p and avg>0:
        tplc="#a8ff3e" if total_pnl>=0 else "#ff3ea8"; tpp=(live_p-avg)/avg*100
        st.markdown(
            f'<div style="background:{BG2};border-left:3px solid {tplc};border-radius:6px;padding:12px 14px">'
            f'<span style="color:{TEXT_DIM}">Итого P&L: </span>'
            f'<span style="color:{tplc};font-weight:700;font-size:18px">'
            f'{"+" if total_pnl>=0 else ""}${total_pnl:.2f} ({"+" if tpp>=0 else ""}{tpp:.1f}%)'
            f'</span></div>',unsafe_allow_html=True)

with tab4:
    if r.get("psychNote"):
        st.markdown(
            f'<div style="background:rgba(255,215,0,.05);border:1px solid #ffd70033;'
            f'border-radius:8px;padding:16px;color:#ffd700;line-height:1.8">'
            f'🧠 {r["psychNote"]}</div>',unsafe_allow_html=True)
    if len(pos["lots"])>=3: st.warning("⚠ Усреднение 3+ раз — часто признак 'надежды вместо стратегии'.")
    if rec in ("SELL","URGENT SELL"): st.error("🚨 AI рекомендует продавать — проверь свой тезис.")
    if avg>r.get("currentPrice",avg):
        st.markdown(
            f'<div style="background:rgba(255,107,53,.07);border:1px solid #ff6b3533;'
            f'border-radius:8px;padding:12px;color:#ff6b35;margin-top:8px">'
            f'💡 Спроси себя: «Купил бы я эту акцию сегодня по текущей цене?» '
            f'Если нет — возможно стоит пересмотреть позицию.</div>',unsafe_allow_html=True)

with tab5:
    hist_data=st.session_state.history.get(pos["id"],[])
    if not hist_data:
        st.markdown(f'<p style="color:{TEXT_MUTE}">История пока пуста.</p>',unsafe_allow_html=True)
    else:
        st.markdown(f'<p style="color:{TEXT_MUTE}">Последние {len(hist_data)} анализов:</p>',unsafe_allow_html=True)
        for entry in hist_data:
            rec_h=entry.get("recommendation","HOLD"); rc_h=REC_COLOR.get(rec_h,"#00e5ff"); rru_h=REC_RU.get(rec_h,rec_h)
            price_h=f'${entry["price"]}' if entry.get("price") else "—"
            pl_h=entry.get("pl_pct"); plc_h="#a8ff3e" if pl_h and pl_h>=0 else "#ff3ea8"
            pl_s_h=f'{"+" if pl_h and pl_h>=0 else ""}{pl_h:.1f}%' if pl_h is not None else "—"
            st.markdown(
                f'<div style="background:{BG2};border-left:4px solid {rc_h};border-radius:6px;'
                f'padding:10px 14px;margin-bottom:6px">'
                f'<div style="color:{TEXT_MUTE};font-size:11px">{entry["date"]}</div>'
                f'<div style="margin-top:4px">'
                f'<span style="color:{rc_h};font-weight:700;font-size:14px">{rru_h}</span>'
                f'  <span style="color:{TEXT}"> {price_h}</span>'
                f'  <span style="color:{plc_h}"> {pl_s_h}</span>'
                f'</div></div>',unsafe_allow_html=True)

st.divider()
st.caption("⚠ Не является инвестиционной рекомендацией.")
