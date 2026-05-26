import streamlit as st
import json, re
from datetime import datetime

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
# localStorage ↔ Python через st.text_area (скрытый)
#
# Как работает:
#  1. st.text_area с key="ls_bridge" рендерится СКРЫТЫМ через CSS
#  2. JS при загрузке читает localStorage и ВСТАВЛЯЕТ значение в этот textarea
#  3. Streamlit видит изменение виджета → делает rerun → Python читает значение
#  4. При сохранении Python кладёт JSON в session_state["ls_write"]
#     → JS polling раз в 500мс видит флаг → пишет в localStorage
# ════════════════════════════════════════════════════════

LS_KEY = "speculator_v2"

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

# ── инициализация session state ───────────────────────
def _init():
    defs = {
        "portfolio":          None,
        "next_id":            10,
        "results":            {},
        "selected":           None,
        "history":            {},
        "portfolio_analysis": None,
        "dark_mode":          True,
        "ls_loaded":          False,   # флаг: данные из LS уже прочитаны
        "ls_write_pending":   None,    # JSON-строка ожидающая записи в LS
    }
    for k, v in defs.items():
        if k not in st.session_state:
            st.session_state[k] = v
_init()

# ── скрытый CSS для textarea-моста ───────────────────
st.markdown("""
<style>
/* скрываем textarea-мост, но оставляем его в DOM */
div[data-testid="stTextArea"][aria-label="ls_bridge_area"] {
    position: absolute !important;
    width: 1px !important;
    height: 1px !important;
    overflow: hidden !important;
    opacity: 0 !important;
    pointer-events: none !important;
    top: -9999px !important;
}
</style>
""", unsafe_allow_html=True)

# ── textarea-мост (ДОЛЖЕН быть до любого st.stop()) ──
raw_ls = st.text_area("ls_bridge_area", key="ls_bridge", label_visibility="hidden")

# ── читаем localStorage при первом запуске ────────────
if not st.session_state.ls_loaded:
    if raw_ls and raw_ls.strip():
        try:
            loaded = json.loads(raw_ls)
            port   = loaded.get("portfolio")
            hist   = loaded.get("history", {})
            nid    = loaded.get("next_id", 10)
            if port and isinstance(port, list) and len(port) > 0:
                st.session_state.portfolio = port
                st.session_state.history   = {int(k): v for k, v in hist.items()}
                st.session_state.next_id   = nid
        except Exception:
            pass
    if st.session_state.portfolio is None:
        st.session_state.portfolio = DEFAULT_PORTFOLIO
    st.session_state.ls_loaded = True

if st.session_state.portfolio is None:
    st.session_state.portfolio = DEFAULT_PORTFOLIO

# ── JS: читает localStorage → вставляет в textarea ───
# и слушает флаг ls_write_pending → пишет в localStorage
write_payload = ""
if st.session_state.ls_write_pending:
    safe = st.session_state.ls_write_pending.replace("\\", "\\\\").replace("`", "\\`")
    write_payload = f"localStorage.setItem('{LS_KEY}', `{safe}`);"
    st.session_state.ls_write_pending = None

st.components.v1.html(f"""
<script>
(function() {{
    var KEY = '{LS_KEY}';

    // ── запись (если Python положил данные) ──
    {write_payload}

    // ── чтение при первом запуске ──
    var stored = localStorage.getItem(KEY);
    if (!stored) return;

    // Ждём пока textarea появится в DOM родительского окна
    function injectValue(attempt) {{
        if (attempt > 40) return;
        // Ищем textarea в родительском фрейме
        var textareas = window.parent.document.querySelectorAll('textarea');
        var target = null;
        for (var i = 0; i < textareas.length; i++) {{
            // Streamlit рендерит label рядом с textarea
            var label = window.parent.document.querySelector('label[for="' + textareas[i].id + '"]');
            if (label && label.textContent.trim() === 'ls_bridge_area') {{
                target = textareas[i]; break;
            }}
        }}
        if (!target) {{
            // Запасной вариант: ищем по data-testid
            var block = window.parent.document.querySelector('[aria-label="ls_bridge_area"] textarea');
            if (block) target = block;
        }}
        if (!target) {{
            setTimeout(function() {{ injectValue(attempt + 1); }}, 150);
            return;
        }}
        // Проверяем — уже заполнен?
        if (target.value && target.value.trim().length > 5) return;

        // Вставляем значение через React synthetic event
        var nativeInputValueSetter = Object.getOwnPropertyDescriptor(
            window.HTMLTextAreaElement.prototype, 'value').set;
        nativeInputValueSetter.call(target, stored);
        target.dispatchEvent(new Event('input', {{ bubbles: true }}));
    }}

    injectValue(0);
}})();
</script>
""", height=0)

# ── функция сохранения ────────────────────────────────
def save_to_ls():
    payload = json.dumps({
        "portfolio": st.session_state.portfolio,
        "history":   st.session_state.history,
        "next_id":   st.session_state.next_id,
        "saved_at":  datetime.now().isoformat(),
    }, ensure_ascii=False)
    st.session_state.ls_write_pending = payload

def clear_ls():
    st.components.v1.html(f"""
<script>localStorage.removeItem('{LS_KEY}');</script>
""", height=0)

# ════════════════════════════════════════════════════════
# ТЕМА
# ════════════════════════════════════════════════════════
if st.session_state.dark_mode:
    BG,BG2,BORDER   = "#080b12","#0d1520","#1e2a3a"
    TEXT,TEXT_DIM   = "#e8eaf0","#8899aa"
    TEXT_MUTE       = "#3a5070"
    LABEL_CSS       = "color:#3a5070"
    SIDEBAR_BG      = "#0d1520"
else:
    BG,BG2,BORDER   = "#f0f4f8","#ffffff","#c8d8e8"
    TEXT,TEXT_DIM   = "#0d1a2a","#3a5070"
    TEXT_MUTE       = "#8899aa"
    LABEL_CSS       = "color:#8899aa"
    SIDEBAR_BG      = "#e0e8f0"

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600;700&display=swap');
html,body,[class*="css"]{{font-family:'IBM Plex Mono',monospace;}}
.stApp{{background-color:{BG};color:{TEXT};}}
section[data-testid="stSidebar"]{{background-color:{SIDEBAR_BG};}}
.stTabs [data-baseweb="tab-list"]{{background-color:{BG2};border-radius:8px;}}
.stTabs [data-baseweb="tab"]{{color:{TEXT_DIM};}}
.stTabs [aria-selected="true"]{{color:{TEXT};}}
.label{{{LABEL_CSS};font-size:10px;text-transform:uppercase;letter-spacing:1px;}}
p,li,span{{color:{TEXT};}}
.stAlert p{{color:inherit!important;}}
</style>
""", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════
def avg_price(lots):
    sh=sum(l["shares"] for l in lots)
    return sum(l["shares"]*l["price"] for l in lots)/sh if sh>0 else 0
def total_shares(lots): return sum(l["shares"] for l in lots)
def total_cost(lots):   return sum(l["shares"]*l["price"] for l in lots)

REC_EMOJI = {"STRONG BUY":"🟢","BUY MORE":"🔵","HOLD":"🔷","REDUCE":"🟡","SELL":"🟠","URGENT SELL":"🔴"}
REC_RU    = {"STRONG BUY":"СИЛЬНАЯ ПОКУПКА","BUY MORE":"ДОКУПИТЬ","HOLD":"ДЕРЖАТЬ",
             "REDUCE":"СОКРАТИТЬ","SELL":"ПРОДАТЬ","URGENT SELL":"СРОЧНО ПРОДАТЬ"}
REC_COLOR = {"STRONG BUY":"#a8ff3e","BUY MORE":"#54a0ff","HOLD":"#00e5ff",
             "REDUCE":"#ffd700","SELL":"#ff6b35","URGENT SELL":"#ff3ea8"}
RISK_COLOR= {"LOW":"#a8ff3e","MEDIUM":"#ffd700","HIGH":"#ff6b35","VERY HIGH":"#ff3ea8","EXTREME":"#ff3ea8"}
RISK_RU   = {"LOW":"НИЗКИЙ","MEDIUM":"СРЕДНИЙ","HIGH":"ВЫСОКИЙ","VERY HIGH":"ОЧЕНЬ ВЫСОКИЙ","EXTREME":"ЭКСТРЕМАЛЬНЫЙ"}
AVD_COLOR = {"SMART":"#a8ff3e","NEUTRAL":"#ffd700","MISTAKE":"#ff3ea8"}
AVD_RU    = {"SMART":"ГРАМОТНО ✓","NEUTRAL":"НЕЙТРАЛЬНО","MISTAKE":"ОШИБКА ✗"}

@st.cache_data(ttl=300)
def get_market_data(ticker, period="3mo"):
    if not YFINANCE_OK: return None
    try:
        t=yf.Ticker(ticker); hist=t.history(period=period)
        if hist.empty: return None
        price=round(float(hist["Close"].iloc[-1]),4)
        prev=round(float(hist["Close"].iloc[-2]),4) if len(hist)>1 else price
        tail=hist["Close"].tail(252)
        return {"price":price,"change_pct":round((price-prev)/prev*100,2),
                "high_52w":round(float(tail.max()),4),"low_52w":round(float(tail.min()),4),
                "volume":int(hist["Volume"].iloc[-1]),"history":hist[["Close","Volume"]].copy()}
    except Exception: return None

def analyze_stock(pos, mkt=None):
    avg=avg_price(pos["lots"]); sh=total_shares(pos["lots"]); cost=total_cost(pos["lots"])
    pl_pct=((mkt["price"]-avg)/avg*100) if mkt and avg>0 else None
    ad_count=len(pos["lots"])
    highest_buy=max(l["price"] for l in pos["lots"])
    avg_down_pct=((highest_buy-avg)/highest_buy*100) if ad_count>1 else 0
    mf=""
    if mkt:
        mf=f"\nREAL MARKET DATA:\n- Current price: ${mkt['price']}\n- Change today: {mkt['change_pct']:+.2f}%\n- 52w High: ${mkt['high_52w']} | 52w Low: ${mkt['low_52w']}\n- Volume: {mkt['volume']:,}\n- P&L vs avg: {pl_pct:+.1f}%"
    prompt=f"""Prop-desk trader. Analyze speculative position.
STOCK: {pos["ticker"]} [{pos.get("sector","Unknown")}]
POSITION: {sh} shares | Avg: ${avg:.4f} | Invested: ${cost:.2f}
LOTS: {", ".join(f"Lot{i+1}: {l['shares']}sh@${l['price']}" for i,l in enumerate(pos["lots"]))}
{f"Averaged down {ad_count}x, reduced avg by {avg_down_pct:.1f}%" if ad_count>1 else "Single entry."}{mf}
Return ONLY valid JSON:
{{"recommendation":"HOLD","risk":"HIGH","confidence":55,"delistingRisk":false,"dilutionRisk":"MEDIUM","avgDownVerdict":"NEUTRAL","avgDownReason":"one sentence","context":"2-3 sentences","speculatorTip":"trade plan","catalysts":["c1","c2"],"risks":["r1","r2"],"targetLow":0.00,"targetBase":0.00,"targetHigh":0.00,"stopLoss":0.00,"psychNote":"bias"}}
recommendation=STRONG BUY|BUY MORE|HOLD|REDUCE|SELL|URGENT SELL, risk=LOW|MEDIUM|HIGH|VERY HIGH|EXTREME, avgDownVerdict=SMART|NEUTRAL|MISTAKE"""
    client=anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
    msg=client.messages.create(model="claude-haiku-4-5-20251001",max_tokens=1000,
                               messages=[{"role":"user","content":prompt}])
    m=re.search(r'\{[\s\S]*\}',msg.content[0].text)
    if not m: raise ValueError("JSON не найден")
    r=json.loads(m.group())
    if mkt:
        r.update({"currentPrice":mkt["price"],"weekHigh52":mkt["high_52w"],
                  "weekLow52":mkt["low_52w"],"changeToday":mkt["change_pct"],"volume":mkt["volume"]})
    else:
        r.setdefault("currentPrice",avg)
    return r

def analyze_portfolio_summary():
    rows=[]
    for p in st.session_state.portfolio:
        if not p["lots"]: continue
        avg=avg_price(p["lots"]); cost=total_cost(p["lots"])
        mkt=get_market_data(p["ticker"]) if YFINANCE_OK else None
        pl=((mkt["price"]-avg)/avg*100) if mkt and avg>0 else None
        rows.append(f"{p['ticker']} [{p.get('sector','')}]: avg ${avg:.3f}, invested ${cost:.0f}"
                    +(f", current ${mkt['price']}, P&L {pl:+.1f}%" if pl is not None else ""))
    prompt=f"Portfolio risk manager. 3-4 sentences in Russian. Focus: overall risk, sector concentration, biggest concerns, one actionable suggestion.\nPORTFOLIO:\n{chr(10).join(rows)}\nRussian only, plain text."
    client=anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
    msg=client.messages.create(model="claude-haiku-4-5-20251001",max_tokens=300,
                               messages=[{"role":"user","content":prompt}])
    return msg.content[0].text

# ════════════════════════════════════════════════════════
# SIDEBAR
# ════════════════════════════════════════════════════════
with st.sidebar:
    c_logo,c_theme=st.columns([3,1])
    with c_logo: st.markdown("## 📊 Портфель")
    with c_theme:
        if st.button("☀️" if st.session_state.dark_mode else "🌙",key="theme_btn"):
            st.session_state.dark_mode=not st.session_state.dark_mode; st.rerun()

    grand=sum(total_cost(p["lots"]) for p in st.session_state.portfolio)
    st.caption(f"{len(st.session_state.portfolio)} позиций · ${grand:.2f} вложено")

    if st.session_state.selected is not None:
        if st.button("← Сводка",use_container_width=True,key="back_btn"):
            st.session_state.selected=None; st.rerun()

    # ── статус ──
    saved_ok = st.session_state.ls_write_pending is None
    st.markdown(
        f'<div style="background:{BG2};border:1px solid {"#a8ff3e44" if saved_ok else "#ffd70044"};'
        f'border-radius:6px;padding:5px 10px;font-size:11px;'
        f'color:{"#a8ff3e" if saved_ok else "#ffd700"};margin:4px 0">'
        f'{"💾 Сохранено в браузере" if saved_ok else "⏳ Сохраняется..."}'
        f'</div>', unsafe_allow_html=True)

    if st.button("🗑 Сбросить данные браузера",use_container_width=True,key="clear_btn",
                 help="Вернуть дефолтный портфель"):
        clear_ls()
        for k in ["portfolio","history","results","selected","portfolio_analysis"]:
            st.session_state.pop(k,None)
        st.session_state.ls_loaded=False
        st.rerun()

    st.divider()

    with st.expander("➕ Новая акция"):
        nt=st.text_input("Тикер",key="new_t",placeholder="GME").upper().strip()
        ns=st.text_input("Сектор",key="new_s",placeholder="Gaming")
        if st.button("Добавить",use_container_width=True,key="add_pos_btn"):
            if nt:
                st.session_state.portfolio.append(
                    {"id":st.session_state.next_id,"ticker":nt,"sector":ns,"lots":[]})
                st.session_state.next_id+=1
                save_to_ls(); st.rerun()

    st.divider()

    for pos in st.session_state.portfolio:
        avg=avg_price(pos["lots"]); sh=int(total_shares(pos["lots"]))
        res=st.session_state.results.get(pos["id"])
        mkt=get_market_data(pos["ticker"]) if YFINANCE_OK else None
        live=mkt["price"] if mkt else (res.get("currentPrice") if res else None)
        is_sel=st.session_state.selected==pos["id"]

        pl_html=""
        if live and avg>0:
            pl=(live-avg)/avg*100; clr="#a8ff3e" if pl>=0 else "#ff3ea8"
            pl_html=f'<span style="color:{clr}"> {"+" if pl>=0 else ""}{pl:.1f}%</span>'
        chg_html=""
        if mkt:
            ct=mkt["change_pct"]; ctc="#a8ff3e" if ct>=0 else "#ff3ea8"
            chg_html=f'<span style="color:{ctc};font-size:10px"> {"+" if ct>=0 else ""}{ct:.2f}%</span>'
        rec_html=""
        if res:
            rc2=REC_COLOR.get(res.get("recommendation","HOLD"),"#00e5ff")
            rec_html=f'<br><span style="color:{rc2};font-size:10px">{REC_RU.get(res.get("recommendation",""),"")}</span>'

        bc="#00e5ff" if is_sel else BORDER; bw="2px" if is_sel else "1px"
        pr_html=f'<span style="color:#00e5ff;font-weight:700"> ${live}</span>' if live else ""
        st.markdown(
            f'<div style="background:{BG2};border:{bw} solid {bc};border-radius:8px;'
            f'padding:10px 12px;margin-bottom:4px">'
            f'<span style="color:#00e5ff;font-weight:700;font-size:15px">{pos["ticker"]}</span>'
            f'{pr_html}{chg_html} <span style="color:{TEXT_MUTE};font-size:10px">{pos.get("sector","")}</span>'
            f'{rec_html}<br>'
            f'<span style="color:{TEXT_MUTE};font-size:11px">{sh}шт · ср.${avg:.4f}</span>'
            f'{pl_html}</div>', unsafe_allow_html=True)

        for i,lot in enumerate(pos["lots"]):
            c1,c2=st.columns([5,1])
            lpl_html=""
            if live:
                lpl=(live-lot["price"])/lot["price"]*100; lc="#a8ff3e" if lpl>=0 else "#ff3ea8"
                lpl_html=f'<span style="color:{lc}"> {"+" if lpl>=0 else ""}{lpl:.1f}%</span>'
            c1.markdown(f'<span style="font-size:11px;color:{TEXT_DIM}">л{i+1}: {lot["shares"]}шт×${lot["price"]}</span>{lpl_html}',
                        unsafe_allow_html=True)
            if c2.button("✕",key=f"rm_{pos['id']}_{i}"):
                pos["lots"].pop(i); save_to_ls(); st.rerun()

        with st.expander(f"+ лот к {pos['ticker']}"):
            ca,cb=st.columns(2)
            lsh=ca.number_input("Кол-во",min_value=0.0,step=1.0,key=f"lsh_{pos['id']}")
            lpr=cb.number_input("Цена $",min_value=0.0,step=0.01,key=f"lpr_{pos['id']}")
            if st.button("Добавить лот",key=f"al_{pos['id']}",use_container_width=True):
                if lsh>0 and lpr>0:
                    pos["lots"].append({"shares":lsh,"price":lpr})
                    save_to_ls(); st.rerun()

        b1,b2=st.columns([3,1])
        if b1.button(f"▶ Анализ {pos['ticker']}",key=f"an_{pos['id']}",use_container_width=True):
            if not pos["lots"]: st.error("Добавьте лот")
            else:
                st.session_state.selected=pos["id"]
                with st.spinner(f"Анализирую {pos['ticker']}..."):
                    try:
                        mkt_d=get_market_data(pos["ticker"]) if YFINANCE_OK else None
                        result=analyze_stock(pos,mkt_d)
                        st.session_state.results[pos["id"]]=result
                        avg_p=avg_price(pos["lots"])
                        entry={"date":datetime.now().strftime("%d.%m %H:%M"),
                               "recommendation":result.get("recommendation","HOLD"),
                               "price":result.get("currentPrice"),
                               "pl_pct":(result["currentPrice"]-avg_p)/avg_p*100 if result.get("currentPrice") and avg_p>0 else None}
                        if pos["id"] not in st.session_state.history:
                            st.session_state.history[pos["id"]]=[]
                        st.session_state.history[pos["id"]].insert(0,entry)
                        st.session_state.history[pos["id"]]=st.session_state.history[pos["id"]][:10]
                        save_to_ls(); st.rerun()
                    except Exception as e: st.error(f"Ошибка: {e}")

        if b2.button("🗑",key=f"del_{pos['id']}",use_container_width=True):
            st.session_state.portfolio=[p for p in st.session_state.portfolio if p["id"]!=pos["id"]]
            st.session_state.results.pop(pos["id"],None)
            st.session_state.history.pop(pos["id"],None)
            if st.session_state.selected==pos["id"]: st.session_state.selected=None
            save_to_ls(); st.rerun()

        st.markdown(f"<hr style='border-color:{BORDER};margin:6px 0'>",unsafe_allow_html=True)

# ════════════════════════════════════════════════════════
# ОСНОВНОЙ ЭКРАН
# ════════════════════════════════════════════════════════
sel_id  = st.session_state.selected
sel_pos = next((p for p in st.session_state.portfolio if p["id"]==sel_id),None)
sel_res = st.session_state.results.get(sel_id) if sel_id else None

# ── СВОДКА ───────────────────────────────────────────────
if not sel_res:
    st.markdown(f'<h1 style="color:{TEXT}">📈 Speculator AI</h1>',unsafe_allow_html=True)
    st.markdown(f'<p style="color:{TEXT_MUTE}">← Выбери акцию и нажми ▶ Анализ</p>',unsafe_allow_html=True)

    tbl=[]
    for p in st.session_state.portfolio:
        r2=st.session_state.results.get(p["id"])
        mkt=get_market_data(p["ticker"]) if YFINANCE_OK else None
        lp=mkt["price"] if mkt else (r2.get("currentPrice") if r2 else None)
        avg=avg_price(p["lots"])
        pl=f'{"+" if lp and (lp-avg)/avg*100>=0 else ""}{(lp-avg)/avg*100:.1f}%' if lp and avg else "—"
        tbl.append({"Тикер":p["ticker"],"Сектор":p.get("sector",""),
                    "Кол-во":int(total_shares(p["lots"])),"Ср.цена":f'${avg:.4f}',
                    "Тек.цена":f'${lp}' if lp else "—",
                    "Сегодня":f'{mkt["change_pct"]:+.2f}%' if mkt else "—",
                    "P&L":pl,"Вложено":f'${total_cost(p["lots"]):.2f}',
                    "AI":REC_RU.get(r2.get("recommendation",""),"") if r2 else "—"})
    if tbl: st.dataframe(tbl,use_container_width=True,hide_index=True)

    st.divider()
    ca1,ca2=st.columns([3,1])
    with ca1:
        st.markdown(f'<h3 style="color:{TEXT}">🤖 Сводный AI анализ</h3>',unsafe_allow_html=True)
        st.caption("~$0.0003 · max 300 токенов")
    with ca2:
        if st.button("▶ Анализировать",use_container_width=True,key="pa_btn"):
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
            f'<div style="color:#c77dff;font-size:10px;margin-bottom:6px">AI · {pa["date"]}</div>'
            f'{pa["text"]}</div>', unsafe_allow_html=True)

    st.divider()
    if any(st.session_state.history.get(p["id"]) for p in st.session_state.portfolio):
        st.markdown(f'<h3 style="color:{TEXT}">📋 История анализов</h3>',unsafe_allow_html=True)
        for p in st.session_state.portfolio:
            hist=st.session_state.history.get(p["id"],[])
            if not hist: continue
            st.markdown(f'<span style="color:#00e5ff;font-weight:700">{p["ticker"]}</span>',unsafe_allow_html=True)
            for e in hist:
                rc2=REC_COLOR.get(e.get("recommendation","HOLD"),"#00e5ff")
                rru=REC_RU.get(e.get("recommendation","HOLD"),e.get("recommendation",""))
                pl2=e.get("pl_pct"); plc="#a8ff3e" if pl2 and pl2>=0 else "#ff3ea8"
                pl_s=f'{"+" if pl2 and pl2>=0 else ""}{pl2:.1f}%' if pl2 is not None else "—"
                st.markdown(
                    f'<div style="background:{BG2};border-left:3px solid {rc2};border-radius:4px;'
                    f'padding:6px 12px;margin:3px 0;font-size:12px">'
                    f'<span style="color:{TEXT_MUTE}">{e["date"]}</span>  '
                    f'<span style="color:{rc2};font-weight:700">{rru}</span>  '
                    f'<span style="color:{TEXT}">${e["price"] if e.get("price") else "—"}</span>  '
                    f'<span style="color:{plc}">{pl_s}</span></div>', unsafe_allow_html=True)
            st.markdown("<div style='margin-bottom:8px'></div>",unsafe_allow_html=True)
    st.stop()

# ════════════════════════════════════════════════════════
# СТРАНИЦА АНАЛИЗА
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
    f'<div style="color:{rc};font-size:15px;font-weight:700">{REC_EMOJI.get(rec,"")} {REC_RU.get(rec,rec)}</div>'
    f'<div style="color:{rc};font-size:11px">уверенность {r.get("confidence",0)}%</div></div>',
    unsafe_allow_html=True)
th=""
if "changeToday" in r:
    ct=r["changeToday"]; ctc="#a8ff3e" if ct>=0 else "#ff3ea8"
    th=f'<div style="color:{ctc};font-size:12px">{"+" if ct>=0 else ""}{ct:.2f}% сегодня</div>'
c2.markdown(
    f'<div style="background:{BG2};border:1px solid {BORDER};border-radius:8px;padding:14px;text-align:center">'
    f'<div class="label">Цена</div>'
    f'<div style="color:{TEXT};font-size:26px;font-weight:700">${r.get("currentPrice","—")}</div>{th}</div>',
    unsafe_allow_html=True)
c3.markdown(
    f'<div style="background:{BG2};border:1px solid {rkc}33;border-radius:8px;padding:14px;text-align:center">'
    f'<div class="label">Риск</div>'
    f'<div style="color:{rkc};font-size:15px;font-weight:700">{RISK_RU.get(risk,risk)}</div>'
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

st.markdown(f'<h4 style="color:{TEXT}">📈 График</h4>',unsafe_allow_html=True)
PERIODS={"1 нед":"5d","1 мес":"1mo","3 мес":"3mo","6 мес":"6mo","1 год":"1y","2 года":"2y"}
pc=st.radio("П:",list(PERIODS.keys()),index=2,horizontal=True,label_visibility="collapsed")
mc=get_market_data(pos["ticker"],period=PERIODS[pc]) if YFINANCE_OK else None
if mc and mc.get("history") is not None:
    h=mc["history"].copy(); h.index=pd.to_datetime(h.index).tz_localize(None)
    h["Ср.вход"]=avg; h=h.rename(columns={"Close":pos["ticker"]})
    st.line_chart(h[[pos["ticker"],"Ср.вход"]],color=["#00e5ff","#ff3ea8"],height=280)
    lcols=st.columns(len(pos["lots"]))
    for i,(lot,col) in enumerate(zip(pos["lots"],lcols)):
        lpl=(r["currentPrice"]-lot["price"])/lot["price"]*100 if r.get("currentPrice") else None
        lc="#a8ff3e" if lpl and lpl>=0 else "#ff3ea8"
        col.markdown(
            f'<div style="background:{BG2};border:1px solid {BORDER};border-radius:6px;padding:8px;text-align:center">'
            f'<div style="color:{TEXT_MUTE};font-size:9px">ЛОТ {i+1}</div>'
            f'<div style="color:{TEXT};font-weight:700">${lot["price"]}</div>'
            f'{"<div style=color:"+lc+";font-size:11px>"+("+0" if lpl and lpl>=0 else "")+f"{lpl:.1f}%</div>" if lpl is not None else ""}'
            f'</div>', unsafe_allow_html=True)
else:
    st.info("График недоступен")

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
    st.info(r.get("context",""))
    if len(pos["lots"])>1:
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
    for col,key,clr,lbl in [(t1,"targetLow","#ff3ea8","МЕДВЕДЬ"),(t2,"targetBase","#ffd700","БАЗА"),(t3,"targetHigh",rc,"БЫК")]:
        col.markdown(
            f'<div style="background:{BG2};border:1px solid {clr}33;border-radius:8px;padding:16px;text-align:center">'
            f'<div class="label">{lbl}</div>'
            f'<div style="color:{clr};font-size:28px;font-weight:700">${r.get(key,"—")}</div></div>',
            unsafe_allow_html=True)
    if r.get("currentPrice") and r.get("stopLoss") and r.get("targetBase"):
        ra=r["currentPrice"]-r["stopLoss"]; rw=r["targetBase"]-r["currentPrice"]
        if ra>0 and rw>0:
            rr=rw/ra; rrc="#a8ff3e" if rr>=2 else "#ffd700" if rr>=1 else "#ff3ea8"
            st.markdown(f'R/R: <span style="color:#ff3ea8">-{ra/r["currentPrice"]*100:.1f}%</span> / '
                        f'<span style="color:#a8ff3e">+{rw/r["currentPrice"]*100:.1f}%</span> · '
                        f'<span style="color:{rrc};font-weight:700">{rr:.1f}:1</span>',unsafe_allow_html=True)
    st.markdown(
        f'<div style="background:rgba(199,125,255,.08);border:1px solid #c77dff33;'
        f'border-radius:8px;padding:16px;color:#c77dff;line-height:1.8">'
        f'{r.get("speculatorTip","")}</div>',unsafe_allow_html=True)
    st.markdown(f"**Стоп-лосс:** :red[${r.get('stopLoss','—')}]")

with tab3:
    lp2=r.get("currentPrice"); tot=0
    for i,lot in enumerate(pos["lots"]):
        lpl=(lp2-lot["price"])/lot["price"]*100 if lp2 else None
        lc="#a8ff3e" if lpl and lpl>=0 else "#ff3ea8"
        pu=(lp2-lot["price"])*lot["shares"] if lp2 else None
        if pu: tot+=pu
        st.markdown(
            f'<div style="background:{BG2};border:1px solid {BORDER};border-radius:6px;'
            f'padding:10px 14px;margin-bottom:6px">'
            f'Лот {i+1}: <b>{lot["shares"]}шт × ${lot["price"]}</b> = ${lot["shares"]*lot["price"]:.2f}'
            f'<span style="color:{lc};font-weight:700;float:right">'
            f'{"+" if lpl and lpl>=0 else ""}{lpl:.1f}%  '
            f'{"+" if pu and pu>=0 else ""}{"${:.2f}".format(pu) if pu else ""}</span></div>',
            unsafe_allow_html=True)
    if lp2 and avg>0:
        tc="#a8ff3e" if tot>=0 else "#ff3ea8"; tp=(lp2-avg)/avg*100
        st.markdown(
            f'<div style="background:{BG2};border-left:3px solid {tc};border-radius:6px;padding:12px 14px">'
            f'Итого P&L: <span style="color:{tc};font-weight:700;font-size:18px">'
            f'{"+" if tot>=0 else ""}${tot:.2f} ({"+" if tp>=0 else ""}{tp:.1f}%)</span></div>',
            unsafe_allow_html=True)

with tab4:
    if r.get("psychNote"):
        st.markdown(
            f'<div style="background:rgba(255,215,0,.05);border:1px solid #ffd70033;'
            f'border-radius:8px;padding:16px;color:#ffd700;line-height:1.8">'
            f'🧠 {r["psychNote"]}</div>',unsafe_allow_html=True)
    if len(pos["lots"])>=3: st.warning("⚠ Усреднение 3+ раз — признак 'надежды вместо стратегии'.")
    if rec in ("SELL","URGENT SELL"): st.error("🚨 AI рекомендует продавать — проверь тезис.")
    if avg>r.get("currentPrice",avg):
        st.markdown(
            f'<div style="background:rgba(255,107,53,.07);border:1px solid #ff6b3533;'
            f'border-radius:8px;padding:12px;color:#ff6b35;margin-top:8px">'
            f'💡 Купил бы я эту акцию сегодня по текущей цене? Если нет — пересмотри позицию.</div>',
            unsafe_allow_html=True)

with tab5:
    hd=st.session_state.history.get(pos["id"],[])
    if not hd:
        st.markdown(f'<p style="color:{TEXT_MUTE}">История пуста — запусти анализ.</p>',unsafe_allow_html=True)
    else:
        for e in hd:
            rc2=REC_COLOR.get(e.get("recommendation","HOLD"),"#00e5ff")
            rru=REC_RU.get(e.get("recommendation","HOLD"),"")
            pl2=e.get("pl_pct"); plc="#a8ff3e" if pl2 and pl2>=0 else "#ff3ea8"
            pl_s=f'{"+" if pl2 and pl2>=0 else ""}{pl2:.1f}%' if pl2 is not None else "—"
            st.markdown(
                f'<div style="background:{BG2};border-left:4px solid {rc2};border-radius:6px;'
                f'padding:10px 14px;margin-bottom:6px">'
                f'<div style="color:{TEXT_MUTE};font-size:11px">{e["date"]}</div>'
                f'<span style="color:{rc2};font-weight:700">{rru}</span>  '
                f'<span style="color:{TEXT}">${e["price"] if e.get("price") else "—"}</span>  '
                f'<span style="color:{plc}">{pl_s}</span></div>',unsafe_allow_html=True)

st.divider()
st.caption("⚠ Не является инвестиционной рекомендацией.")
