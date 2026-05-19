import streamlit as st
import json
import re

try:
    import anthropic
    ANTHROPIC_OK = True
except ImportError:
    ANTHROPIC_OK = False

try:
    import yfinance as yf
    import pandas as pd
    YFINANCE_OK = True
except ImportError:
    YFINANCE_OK = False

# ── page config ──────────────────────────────────────────
st.set_page_config(page_title="Speculator AI", page_icon="📈", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600;700&display=swap');
html, body, [class*="css"] { font-family: 'IBM Plex Mono', monospace; }
.stApp { background-color: #080b12; color: #e8eaf0; }
div[data-testid="stSidebar"] { background-color: #0d1520; }
.label { color: #2a4060; font-size: 10px; text-transform: uppercase; letter-spacing: 1px; }
</style>
""", unsafe_allow_html=True)

# ── helpers ──────────────────────────────────────────────
def avg_price(lots):
    sh = sum(l["shares"] for l in lots)
    return sum(l["shares"] * l["price"] for l in lots) / sh if sh > 0 else 0

def total_shares(lots): return sum(l["shares"] for l in lots)
def total_cost(lots):   return sum(l["shares"] * l["price"] for l in lots)

REC_EMOJI = {"STRONG BUY":"🟢","BUY MORE":"🔵","HOLD":"🔷","REDUCE":"🟡","SELL":"🟠","URGENT SELL":"🔴"}
REC_RU    = {"STRONG BUY":"СИЛЬНАЯ ПОКУПКА","BUY MORE":"ДОКУПИТЬ","HOLD":"ДЕРЖАТЬ","REDUCE":"СОКРАТИТЬ","SELL":"ПРОДАТЬ","URGENT SELL":"СРОЧНО ПРОДАТЬ"}
REC_COLOR = {"STRONG BUY":"#a8ff3e","BUY MORE":"#54a0ff","HOLD":"#00e5ff","REDUCE":"#ffd700","SELL":"#ff6b35","URGENT SELL":"#ff3ea8"}
RISK_COLOR= {"LOW":"#a8ff3e","MEDIUM":"#ffd700","HIGH":"#ff6b35","VERY HIGH":"#ff3ea8","EXTREME":"#ff3ea8"}
RISK_RU   = {"LOW":"НИЗКИЙ","MEDIUM":"СРЕДНИЙ","HIGH":"ВЫСОКИЙ","VERY HIGH":"ОЧЕНЬ ВЫСОКИЙ","EXTREME":"ЭКСТРЕМАЛЬНЫЙ"}
AVD_COLOR = {"SMART":"#a8ff3e","NEUTRAL":"#ffd700","MISTAKE":"#ff3ea8"}
AVD_RU    = {"SMART":"ГРАМОТНО ✓","NEUTRAL":"НЕЙТРАЛЬНО","MISTAKE":"ОШИБКА ✗"}

# ── Yahoo Finance (кэш 5 минут) ──────────────────────────
@st.cache_data(ttl=300)
def get_market_data(ticker: str, period: str = "3mo"):
    if not YFINANCE_OK:
        return None
    try:
        t    = yf.Ticker(ticker)
        hist = t.history(period=period)
        if hist.empty:
            return None
        price      = round(float(hist["Close"].iloc[-1]), 4)
        prev_close = round(float(hist["Close"].iloc[-2]), 4) if len(hist) > 1 else price
        change_pct = round((price - prev_close) / prev_close * 100, 2)
        tail       = hist["Close"].tail(252)
        return {
            "price":      price,
            "change_pct": change_pct,
            "high_52w":   round(float(tail.max()), 4),
            "low_52w":    round(float(tail.min()), 4),
            "volume":     int(hist["Volume"].iloc[-1]),
            "history":    hist[["Close","Volume"]].copy(),
        }
    except Exception:
        return None

# ── session state ─────────────────────────────────────────
if "portfolio" not in st.session_state:
    st.session_state.portfolio = [
        {"id":1,"ticker":"APPS","sector":"Ad Tech",   "lots":[{"shares":50,"price":2.10},{"shares":80,"price":1.60}]},
        {"id":2,"ticker":"HUYA","sector":"China ADR", "lots":[{"shares":100,"price":3.20}]},
        {"id":3,"ticker":"DOYU","sector":"China ADR", "lots":[{"shares":200,"price":1.05},{"shares":150,"price":0.85}]},
        {"id":4,"ticker":"PBR", "sector":"Energy",    "lots":[{"shares":30,"price":13.50}]},
        {"id":5,"ticker":"ICAD","sector":"MedTech",   "lots":[{"shares":400,"price":0.60},{"shares":300,"price":0.45}]},
        {"id":6,"ticker":"NVNO","sector":"Biotech",   "lots":[{"shares":500,"price":0.30}]},
    ]
if "next_id"  not in st.session_state: st.session_state.next_id  = 10
if "results"  not in st.session_state: st.session_state.results  = {}
if "selected" not in st.session_state: st.session_state.selected = None

# ── AI analysis ───────────────────────────────────────────
def analyze_stock(pos, mkt=None):
    avg  = avg_price(pos["lots"])
    sh   = total_shares(pos["lots"])
    cost = total_cost(pos["lots"])
    lots_str = ", ".join(f"Lot{i+1}: {l['shares']}sh@${l['price']}" for i,l in enumerate(pos["lots"]))
    ad_note  = f"Averaged down {len(pos['lots'])} times." if len(pos["lots"]) > 1 else ""
    real_note = (
        f"\nREAL DATA from Yahoo Finance: price=${mkt['price']}, "
        f"change={mkt['change_pct']:+.2f}%, 52wH=${mkt['high_52w']}, 52wL=${mkt['low_52w']}. "
        f"Use these exact numbers in JSON."
    ) if mkt else ""

    prompt = f"""You are a professional stock trader analyzing a speculative position.
STOCK: {pos["ticker"]} [{pos.get("sector","Unknown")}]
Position: {sh} shares | Avg cost: ${avg:.4f} | Invested: ${cost:.2f}
{lots_str} {ad_note}{real_note}

Return ONLY valid JSON, no markdown:
{{"ticker":"{pos["ticker"]}","currentPrice":0.00,"weekHigh52":0.00,"weekLow52":0.00,"marketCap":"...","shortInterest":"n/a","recommendation":"HOLD","risk":"HIGH","confidence":55,"delistingRisk":false,"dilutionRisk":"MEDIUM","avgDownVerdict":"NEUTRAL","avgDownReason":"one sentence","context":"2-3 sentences about company and recent news","speculatorTip":"exact trade plan with entry, exit and stop","catalysts":["catalyst 1","catalyst 2"],"risks":["risk 1","risk 2"],"targetLow":0.00,"targetBase":0.00,"targetHigh":0.00,"stopLoss":0.00,"psychNote":"one behavioral observation"}}
Rules: recommendation=STRONG BUY|BUY MORE|HOLD|REDUCE|SELL|URGENT SELL, risk=LOW|MEDIUM|HIGH|VERY HIGH|EXTREME, avgDownVerdict=SMART|NEUTRAL|MISTAKE, prices=numbers"""

    client = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
    msg    = client.messages.create(model="claude-haiku-4-5-20251001", max_tokens=1500,
                                    messages=[{"role":"user","content":prompt}])
    m = re.search(r'\{[\s\S]*\}', msg.content[0].text)
    if not m: raise ValueError("JSON не найден")
    result = json.loads(m.group())

    # перезаписать реальными ценами
    if mkt:
        result["currentPrice"] = mkt["price"]
        result["weekHigh52"]   = mkt["high_52w"]
        result["weekLow52"]    = mkt["low_52w"]
        result["changeToday"]  = mkt["change_pct"]
    return result

# ════════════════════════════════════════════════════════
# SIDEBAR
# ════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("## 📊 Портфель")
    grand = sum(total_cost(p["lots"]) for p in st.session_state.portfolio)
    st.caption(f"{len(st.session_state.portfolio)} позиций · ${grand:.2f} вложено")
    st.divider()

    with st.expander("➕ Новая акция"):
        nt = st.text_input("Тикер", key="nt", placeholder="GME").upper().strip()
        ns = st.text_input("Сектор", key="ns", placeholder="Gaming")
        if st.button("Добавить", use_container_width=True, key="btn_add"):
            if nt:
                st.session_state.portfolio.append({"id":st.session_state.next_id,"ticker":nt,"sector":ns,"lots":[]})
                st.session_state.next_id += 1
                st.rerun()

    st.divider()

    for pos in st.session_state.portfolio:
        avg  = avg_price(pos["lots"])
        sh   = total_shares(pos["lots"])
        res  = st.session_state.results.get(pos["id"])
        mkt  = get_market_data(pos["ticker"]) if YFINANCE_OK else None
        live = mkt["price"] if mkt else (res["currentPrice"] if res else None)
        is_sel = st.session_state.selected == pos["id"]

        pl_html    = ""
        price_html = f'<span style="color:#00e5ff"> ${live}</span>' if live else ""
        if live and avg > 0:
            pl  = (live - avg) / avg * 100
            clr = "#a8ff3e" if pl >= 0 else "#ff3ea8"
            pl_html = f' <span style="color:{clr}">{"+" if pl>=0 else ""}{pl:.1f}%</span>'
        rec_html = ""
        if res:
            rc  = REC_COLOR.get(res.get("recommendation","HOLD"),"#00e5ff")
            rru = REC_RU.get(res.get("recommendation","HOLD"),"")
            rec_html = f'<br><span style="color:{rc};font-size:10px">{rru}</span>'

        border = "2px solid #00e5ff" if is_sel else "1px solid #1e2a3a"
        st.markdown(
            f'<div style="background:#0d1520;border:{border};border-radius:8px;padding:10px 12px;margin-bottom:4px">'
            f'<span style="color:#00e5ff;font-weight:700;font-size:15px">{pos["ticker"]}</span>'
            f'{price_html} <span style="color:#3a5070;font-size:10px">{pos.get("sector","")}</span>'
            f'{rec_html}<br>'
            f'<span style="color:#3a5070;font-size:11px">{sh}шт · ср.${avg:.4f}</span>{pl_html}</div>',
            unsafe_allow_html=True
        )

        for i, lot in enumerate(pos["lots"]):
            c1, c2 = st.columns([5,1])
            lpl_html = ""
            if live:
                lpl = (live - lot["price"]) / lot["price"] * 100
                lc  = "#a8ff3e" if lpl >= 0 else "#ff3ea8"
                lpl_html = f' <span style="color:{lc}">{"+" if lpl>=0 else ""}{lpl:.1f}%</span>'
            c1.markdown(f'<span style="font-size:11px;color:#4a6080">л{i+1}: {lot["shares"]}шт×${lot["price"]}</span>{lpl_html}', unsafe_allow_html=True)
            if c2.button("✕", key=f"rm_{pos['id']}_{i}"):
                pos["lots"].pop(i); st.rerun()

        with st.expander(f"+ лот к {pos['ticker']}"):
            ca,cb = st.columns(2)
            lsh = ca.number_input("Кол-во", min_value=0.0, step=1.0,  key=f"lsh_{pos['id']}")
            lpr = cb.number_input("Цена $",  min_value=0.0, step=0.01, key=f"lpr_{pos['id']}")
            if st.button("Добавить лот", key=f"al_{pos['id']}", use_container_width=True):
                if lsh > 0 and lpr > 0:
                    pos["lots"].append({"shares":lsh,"price":lpr}); st.rerun()

        b1,b2 = st.columns([3,1])
        if b1.button(f"▶ Анализ {pos['ticker']}", key=f"an_{pos['id']}", use_container_width=True):
            if not pos["lots"]:
                st.error("Добавьте лот")
            else:
                st.session_state.selected = pos["id"]
                with st.spinner(f"Анализирую {pos['ticker']}..."):
                    try:
                        mkt_data = get_market_data(pos["ticker"]) if YFINANCE_OK else None
                        st.session_state.results[pos["id"]] = analyze_stock(pos, mkt_data)
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))
        if b2.button("🗑", key=f"del_{pos['id']}", use_container_width=True):
            st.session_state.portfolio = [p for p in st.session_state.portfolio if p["id"] != pos["id"]]
            st.session_state.results.pop(pos["id"], None)
            if st.session_state.selected == pos["id"]: st.session_state.selected = None
            st.rerun()

        st.markdown("<hr style='border-color:#1e2a3a;margin:6px 0'>", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════
# MAIN AREA
# ════════════════════════════════════════════════════════
sel_id  = st.session_state.selected
sel_pos = next((p for p in st.session_state.portfolio if p["id"] == sel_id), None)
sel_res = st.session_state.results.get(sel_id) if sel_id else None

if not sel_res:
    st.markdown("# 📈 Speculator AI")
    st.markdown('<p style="color:#3a5070">← Выбери акцию и нажми ▶ Анализ</p>', unsafe_allow_html=True)
    rows = []
    for p in st.session_state.portfolio:
        r   = st.session_state.results.get(p["id"])
        mkt = get_market_data(p["ticker"]) if YFINANCE_OK else None
        lp  = mkt["price"] if mkt else (r["currentPrice"] if r else None)
        avg = avg_price(p["lots"])
        pl  = f'{"+" if lp and (lp-avg)/avg*100>=0 else ""}{(lp-avg)/avg*100:.1f}%' if lp and avg else "—"
        chg = f'{mkt["change_pct"]:+.2f}%' if mkt else "—"
        rows.append({"Тикер":p["ticker"],"Сектор":p.get("sector",""),"Кол-во":int(total_shares(p["lots"])),
                     "Ср.цена":f'${avg:.4f}',"Тек.цена":f'${lp}' if lp else "—",
                     "Сегодня":chg,"P&L":pl,"Вложено":f'${total_cost(p["lots"]):.2f}',
                     "Анализ":REC_RU.get(r.get("recommendation",""),"—") if r else "—"})
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    st.stop()

# ── result page ──────────────────────────────────────────
r   = sel_res
pos = sel_pos
avg = avg_price(pos["lots"])
rec  = r.get("recommendation","HOLD")
risk = r.get("risk","HIGH")
avd  = r.get("avgDownVerdict","NEUTRAL")
rc   = REC_COLOR.get(rec,"#00e5ff")
rkc  = RISK_COLOR.get(risk,"#ffd700")
avdc = AVD_COLOR.get(avd,"#ffd700")
pl   = (r["currentPrice"] - avg) / avg * 100 if avg > 0 else 0
plc  = "#a8ff3e" if pl >= 0 else "#ff3ea8"

# header
st.markdown(f'<h1><span style="color:#00e5ff">{r["ticker"]}</span> <span style="font-size:16px;color:#3a5070">{pos.get("sector","")}</span></h1>', unsafe_allow_html=True)

c1,c2,c3,c4 = st.columns(4)
c1.markdown(f'<div style="background:#0d1520;border:1px solid {rc}33;border-radius:8px;padding:14px;text-align:center"><div class="label">Рекомендация</div><div style="color:{rc};font-size:17px;font-weight:700;margin-top:4px">{REC_EMOJI.get(rec,"")} {REC_RU.get(rec,rec)}</div><div style="color:{rc};font-size:11px">уверенность {r.get("confidence",0)}%</div></div>', unsafe_allow_html=True)

today_html = ""
if "changeToday" in r:
    ct  = r["changeToday"]
    ctc = "#a8ff3e" if ct >= 0 else "#ff3ea8"
    today_html = f'<div style="color:{ctc};font-size:12px">{"+" if ct>=0 else ""}{ct:.2f}% сегодня</div>'
c2.markdown(f'<div style="background:#0d1520;border:1px solid #1e2a3a;border-radius:8px;padding:14px;text-align:center"><div class="label">Цена (реальная)</div><div style="font-size:26px;font-weight:700">${r.get("currentPrice","—")}</div>{today_html}</div>', unsafe_allow_html=True)

c3.markdown(f'<div style="background:#0d1520;border:1px solid {rkc}33;border-radius:8px;padding:14px;text-align:center"><div class="label">Риск</div><div style="color:{rkc};font-size:17px;font-weight:700">{RISK_RU.get(risk,risk)}</div><div style="color:#3a5070;font-size:11px">стоп ${r.get("stopLoss","—")}</div></div>', unsafe_allow_html=True)

c4.markdown(f'<div style="background:#0d1520;border:1px solid {plc}33;border-radius:8px;padding:14px;text-align:center"><div class="label">P&L позиции</div><div style="color:{plc};font-size:26px;font-weight:700">{"+" if pl>=0 else ""}{pl:.1f}%</div><div style="color:#3a5070;font-size:11px">ср.вход ${avg:.4f}</div></div>', unsafe_allow_html=True)

if r.get("delistingRisk"):
    st.error("🚨 Высокий риск делистинга!")

st.divider()

# ── CHART ────────────────────────────────────────────────
st.markdown("#### 📈 График цены")

PERIODS = {"1 нед":"5d","1 мес":"1mo","3 мес":"3mo","6 мес":"6mo","1 год":"1y","2 года":"2y"}
period_choice = st.radio("Период:", list(PERIODS.keys()), index=2, horizontal=True, label_visibility="collapsed")
mkt_chart = get_market_data(pos["ticker"], period=PERIODS[period_choice]) if YFINANCE_OK else None

if mkt_chart:
    import pandas as pd
    hist = mkt_chart["history"].copy()
    hist.index = pd.to_datetime(hist.index).tz_localize(None)
    hist["Ср. цена входа"] = avg
    hist = hist.rename(columns={"Close": pos["ticker"]})
    st.line_chart(hist[[pos["ticker"],"Ср. цена входа"]], color=["#00e5ff","#ff3ea8"], height=300)

    # Отметить лоты на графике (как таблицу под графиком)
    st.markdown("**Твои покупки:**")
    lot_cols = st.columns(len(pos["lots"]))
    for i, (lot, col) in enumerate(zip(pos["lots"], lot_cols)):
        lpl = (r["currentPrice"] - lot["price"]) / lot["price"] * 100 if r.get("currentPrice") else None
        lc  = "#a8ff3e" if lpl and lpl>=0 else "#ff3ea8"
        col.markdown(
            f'<div style="background:#0d1520;border:1px solid #1e2a3a;border-radius:6px;padding:8px;text-align:center">'
            f'<div style="color:#3a5070;font-size:9px">ЛОТ {i+1}</div>'
            f'<div style="font-weight:700">${lot["price"]}</div>'
            f'<div style="color:{lc};font-size:11px">{"+" if lpl and lpl>=0 else ""}{lpl:.1f}%</div>'
            f'</div>' if lpl else
            f'<div style="background:#0d1520;border:1px solid #1e2a3a;border-radius:6px;padding:8px;text-align:center">'
            f'<div style="color:#3a5070;font-size:9px">ЛОТ {i+1}</div>'
            f'<div style="font-weight:700">${lot["price"]}</div></div>',
            unsafe_allow_html=True
        )

    with st.expander("📊 Объём торгов"):
        vol = hist[["Volume"]] if "Volume" in hist.columns else None
        if vol is not None:
            st.bar_chart(vol, height=150, color="#1e3a2a")
else:
    st.info("📡 График появится после деплоя на Streamlit Cloud — Yahoo Finance недоступен в этой среде")

st.divider()

# ── stats ────────────────────────────────────────────────
m1,m2,m3,m4,m5 = st.columns(5)
m1.metric("52н Макс",   f'${r.get("weekHigh52","—")}')
m2.metric("52н Мин",    f'${r.get("weekLow52","—")}')
m3.metric("Кап.",        r.get("marketCap","—"))
m4.metric("Шорт %",     r.get("shortInterest","—"))
m5.metric("Разводнение", r.get("dilutionRisk","—"))

st.divider()

# ── tabs ─────────────────────────────────────────────────
tab1,tab2,tab3,tab4 = st.tabs(["📰 Обзор","🎯 Торговый план","🧾 Покупки","🧠 Психология"])

with tab1:
    st.markdown("#### Ситуация")
    st.info(r.get("context",""))
    if len(pos["lots"]) > 1:
        st.markdown("#### Усреднение")
        st.markdown(f'<div style="background:#0d1520;border-left:3px solid {avdc};border-radius:6px;padding:12px"><span style="color:{avdc};font-weight:700">{AVD_RU.get(avd,avd)}</span> — <span style="color:#8899aa">{r.get("avgDownReason","")}</span></div>', unsafe_allow_html=True)
    col1,col2 = st.columns(2)
    with col1:
        st.markdown("#### ◈ Катализаторы")
        for c in r.get("catalysts",[]): st.markdown(f"• {c}")
    with col2:
        st.markdown("#### ▲ Риски")
        for rv in r.get("risks",[]): st.markdown(f"• {rv}")

with tab2:
    t1,t2,t3 = st.columns(3)
    t1.markdown(f'<div style="background:#0d1520;border:1px solid #ff3ea833;border-radius:8px;padding:16px;text-align:center"><div class="label">МЕДВЕДЬ</div><div style="color:#ff3ea8;font-size:28px;font-weight:700">${r.get("targetLow","—")}</div></div>', unsafe_allow_html=True)
    t2.markdown(f'<div style="background:#0d1520;border:1px solid #ffd70033;border-radius:8px;padding:16px;text-align:center"><div class="label">БАЗА</div><div style="color:#ffd700;font-size:28px;font-weight:700">${r.get("targetBase","—")}</div></div>', unsafe_allow_html=True)
    t3.markdown(f'<div style="background:#0d1520;border:1px solid {rc}33;border-radius:8px;padding:16px;text-align:center"><div class="label">БЫК</div><div style="color:{rc};font-size:28px;font-weight:700">${r.get("targetHigh","—")}</div></div>', unsafe_allow_html=True)

    if r.get("currentPrice") and r.get("stopLoss") and r.get("targetBase"):
        risk_a = r["currentPrice"] - r["stopLoss"]
        rew_a  = r["targetBase"]   - r["currentPrice"]
        if risk_a > 0 and rew_a > 0:
            rr  = rew_a / risk_a
            rrc = "#a8ff3e" if rr >= 2 else "#ffd700" if rr >= 1 else "#ff3ea8"
            st.markdown(f'**R/R:** <span style="color:#ff3ea8">-{risk_a/r["currentPrice"]*100:.1f}%</span> / <span style="color:#a8ff3e">+{rew_a/r["currentPrice"]*100:.1f}%</span> · <span style="color:{rrc};font-weight:700">{rr:.1f}:1</span>', unsafe_allow_html=True)

    st.markdown("#### 💡 Торговый план")
    st.markdown(f'<div style="background:rgba(199,125,255,.08);border:1px solid #c77dff33;border-radius:8px;padding:16px;color:#c77dff;line-height:1.8">{r.get("speculatorTip","")}</div>', unsafe_allow_html=True)
    st.markdown(f"**Стоп-лосс:** :red[${r.get('stopLoss','—')}]")

with tab3:
    live_p = r.get("currentPrice")
    total_pnl = 0
    for i, lot in enumerate(pos["lots"]):
        lpl    = (live_p - lot["price"]) / lot["price"] * 100 if live_p else None
        lc     = "#a8ff3e" if lpl and lpl >= 0 else "#ff3ea8"
        pnl_u  = (live_p - lot["price"]) * lot["shares"] if live_p else None
        if pnl_u: total_pnl += pnl_u
        st.markdown(
            f'<div style="background:#0d1520;border:1px solid #1e2a3a;border-radius:6px;padding:10px 14px;margin-bottom:6px">'
            f'Лот {i+1}: <b>{lot["shares"]}шт × ${lot["price"]}</b> = ${lot["shares"]*lot["price"]:.2f}'
            f'<span style="color:{lc};font-weight:700;float:right">'
            f'{"+" if lpl and lpl>=0 else ""}{lpl:.1f}%  {"+" if pnl_u and pnl_u>=0 else ""}{"${:.2f}".format(pnl_u) if pnl_u else ""}'
            f'</span></div>', unsafe_allow_html=True
        )
    if live_p:
        tplc = "#a8ff3e" if total_pnl >= 0 else "#ff3ea8"
        st.markdown(f'<div style="background:#0d1520;border-left:3px solid {tplc};border-radius:6px;padding:12px 14px"><span style="color:#8899aa">Итого P&L: </span><span style="color:{tplc};font-weight:700;font-size:18px">{"+" if total_pnl>=0 else ""}${total_pnl:.2f} ({"+" if pl>=0 else ""}{pl:.1f}%)</span></div>', unsafe_allow_html=True)

with tab4:
    if r.get("psychNote"):
        st.markdown(f'<div style="background:rgba(255,215,0,.05);border:1px solid #ffd70033;border-radius:8px;padding:16px;color:#ffd700;line-height:1.8">🧠 {r["psychNote"]}</div>', unsafe_allow_html=True)
    if len(pos["lots"]) >= 3:
        st.warning("⚠ Усреднение 3+ раз — часто признак 'надежды вместо стратегии'.")
    if rec in ("SELL","URGENT SELL"):
        st.error("🚨 AI рекомендует продавать — классическая ловушка якоря.")
    if avg > r.get("currentPrice", avg):
        st.markdown('<div style="background:rgba(255,107,53,.07);border:1px solid #ff6b3533;border-radius:8px;padding:12px;color:#ff6b35aa;margin-top:8px">💡 Спроси себя: «Купил бы я эту акцию сегодня по текущей цене?» Если нет — возможно, стоит пересмотреть.</div>', unsafe_allow_html=True)

st.divider()
st.caption("⚠ Не является инвестиционной рекомендацией.")
