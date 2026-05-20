import streamlit as st
import json
import re

# ── импорты с проверкой ───────────────────────────────────
try:
    import anthropic
except ImportError:
    st.error("❌ anthropic не установлен. Проверьте requirements.txt")
    st.stop()

try:
    import yfinance as yf
    import pandas as pd
    YFINANCE_OK = True
except ImportError:
    YFINANCE_OK = False

# ── настройки страницы ────────────────────────────────────
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

# ── helpers ───────────────────────────────────────────────
def avg_price(lots):
    sh = sum(l["shares"] for l in lots)
    return sum(l["shares"] * l["price"] for l in lots) / sh if sh > 0 else 0

def total_shares(lots): return sum(l["shares"] for l in lots)
def total_cost(lots):   return sum(l["shares"] * l["price"] for l in lots)

REC_EMOJI = {"STRONG BUY":"🟢","BUY MORE":"🔵","HOLD":"🔷","REDUCE":"🟡","SELL":"🟠","URGENT SELL":"🔴"}
REC_RU    = {"STRONG BUY":"СИЛЬНАЯ ПОКУПКА","BUY MORE":"ДОКУПИТЬ","HOLD":"ДЕРЖАТЬ",
             "REDUCE":"СОКРАТИТЬ","SELL":"ПРОДАТЬ","URGENT SELL":"СРОЧНО ПРОДАТЬ"}
REC_COLOR = {"STRONG BUY":"#a8ff3e","BUY MORE":"#54a0ff","HOLD":"#00e5ff",
             "REDUCE":"#ffd700","SELL":"#ff6b35","URGENT SELL":"#ff3ea8"}
RISK_COLOR= {"LOW":"#a8ff3e","MEDIUM":"#ffd700","HIGH":"#ff6b35","VERY HIGH":"#ff3ea8","EXTREME":"#ff3ea8"}
RISK_RU   = {"LOW":"НИЗКИЙ","MEDIUM":"СРЕДНИЙ","HIGH":"ВЫСОКИЙ","VERY HIGH":"ОЧЕНЬ ВЫСОКИЙ","EXTREME":"ЭКСТРЕМАЛЬНЫЙ"}
AVD_COLOR = {"SMART":"#a8ff3e","NEUTRAL":"#ffd700","MISTAKE":"#ff3ea8"}
AVD_RU    = {"SMART":"ГРАМОТНО ✓","NEUTRAL":"НЕЙТРАЛЬНО","MISTAKE":"ОШИБКА ✗"}

# ── Yahoo Finance ─────────────────────────────────────────
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
    except Exception as e:
        return None

# ── session state ─────────────────────────────────────────
if "portfolio" not in st.session_state:
    st.session_state.portfolio = [
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
if "next_id"  not in st.session_state: st.session_state.next_id  = 10
if "results"  not in st.session_state: st.session_state.results  = {}
if "selected" not in st.session_state: st.session_state.selected = None

# ── AI анализ ─────────────────────────────────────────────
def analyze_stock(pos, mkt=None):
    avg  = avg_price(pos["lots"])
    sh   = total_shares(pos["lots"])
    cost = total_cost(pos["lots"])

    # P&L считаем сами — не тратим токены
    pl_pct = ((mkt["price"] - avg) / avg * 100) if mkt and avg > 0 else None

    # усреднение — считаем сами
    ad_count = len(pos["lots"])
    highest_buy = max(l["price"] for l in pos["lots"])
    avg_down_pct = ((highest_buy - avg) / highest_buy * 100) if ad_count > 1 else 0

    # все данные которые есть из Yahoo — передаём AI как факты
    market_facts = ""
    if mkt:
        market_facts = f"""
REAL MARKET DATA (from Yahoo Finance, do NOT recalculate):
- Current price: ${mkt["price"]}
- Change today: {mkt["change_pct"]:+.2f}%
- 52w High: ${mkt["high_52w"]} | 52w Low: ${mkt["low_52w"]}
- Volume today: {mkt["volume"]:,}
- Trader P&L vs avg: {pl_pct:+.1f}%"""

    # что AI должен придумать сам — только аналитика
    prompt = f"""You are a prop-desk trader and risk manager. Your job: analyze this speculative position and give trading advice. Do NOT guess prices — they are provided.

STOCK: {pos["ticker"]} [{pos.get("sector","Unknown")}]
POSITION: {sh} shares | Avg entry: ${avg:.4f} | Total invested: ${cost:.2f}
LOTS: {", ".join(f"Lot{i+1}: {l["shares"]}sh@${l["price"]}" for i,l in enumerate(pos["lots"]))}
{f"Averaged down {ad_count} times, reduced avg by {avg_down_pct:.1f}%" if ad_count > 1 else "Single entry."}
{market_facts}

YOUR JOB — provide ONLY what requires expertise:
1. recommendation & reasoning (what should trader do NOW)
2. risk assessment (company-specific risks, not price)
3. catalysts (upcoming events that could move price)
4. speculator trade plan (specific levels, triggers)
5. target prices (6-month bear/base/bull case)
6. stop loss level
7. psychology note (behavioral bias you detect)
8. averaging down verdict (was it smart given company fundamentals?)

Return ONLY valid JSON, no markdown:
{{"recommendation":"HOLD","risk":"HIGH","confidence":55,"delistingRisk":false,"dilutionRisk":"MEDIUM","avgDownVerdict":"NEUTRAL","avgDownReason":"one sentence on fundamentals","context":"2-3 sentences: recent news, catalysts, company health","speculatorTip":"specific trade plan: what event triggers buy/sell, exact exit plan","catalysts":["specific catalyst 1","specific catalyst 2"],"risks":["specific risk 1","specific risk 2"],"targetLow":0.00,"targetBase":0.00,"targetHigh":0.00,"stopLoss":0.00,"psychNote":"specific behavioral bias observed"}}
Rules: recommendation=STRONG BUY|BUY MORE|HOLD|REDUCE|SELL|URGENT SELL, risk=LOW|MEDIUM|HIGH|VERY HIGH|EXTREME, avgDownVerdict=SMART|NEUTRAL|MISTAKE, target prices=numbers"""

    client = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
    msg    = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )

    text = msg.content[0].text
    m    = re.search(r'\{[\s\S]*\}', text)
    if not m:
        raise ValueError("JSON не найден в ответе AI")
    result = json.loads(m.group())

    # все цифры берём из Yahoo — не от AI
    if mkt:
        result["currentPrice"] = mkt["price"]
        result["weekHigh52"]   = mkt["high_52w"]
        result["weekLow52"]    = mkt["low_52w"]
        result["changeToday"]  = mkt["change_pct"]
        result["volume"]       = mkt["volume"]
    elif not mkt:
        # если нет Yahoo — ставим заглушку
        result.setdefault("currentPrice", avg)

    return result

# ════════════════════════════════════════════════════════
# SIDEBAR
# ════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("## 📊 Портфель")
    grand = sum(total_cost(p["lots"]) for p in st.session_state.portfolio)
    st.caption(f"{len(st.session_state.portfolio)} позиций · ${grand:.2f} вложено")

    if not YFINANCE_OK:
        st.warning("⚠ yfinance не установлен — цены будут от AI")

    st.divider()

    # добавить позицию
    with st.expander("➕ Новая акция"):
        nt = st.text_input("Тикер", key="nt", placeholder="GME").upper().strip()
        ns = st.text_input("Сектор", key="ns", placeholder="Gaming")
        if st.button("Добавить", use_container_width=True, key="btn_add"):
            if nt:
                st.session_state.portfolio.append(
                    {"id": st.session_state.next_id, "ticker": nt, "sector": ns, "lots": []}
                )
                st.session_state.next_id += 1
                st.rerun()

    st.divider()

    # список позиций
    for pos in st.session_state.portfolio:
        avg    = avg_price(pos["lots"])
        sh     = total_shares(pos["lots"])
        res    = st.session_state.results.get(pos["id"])
        mkt    = get_market_data(pos["ticker"]) if YFINANCE_OK else None
        live   = mkt["price"] if mkt else (res["currentPrice"] if res else None)
        is_sel = st.session_state.selected == pos["id"]

        # P&L и цена
        pl_html    = ""
        price_html = f'<span style="color:#00e5ff;font-weight:700"> ${live}</span>' if live else ""
        if live and avg > 0:
            pl  = (live - avg) / avg * 100
            clr = "#a8ff3e" if pl >= 0 else "#ff3ea8"
            pl_html = f'<span style="color:{clr}"> {"+" if pl>=0 else ""}{pl:.1f}%</span>'

        # изменение за день
        chg_html = ""
        if mkt and "change_pct" in mkt:
            ct  = mkt["change_pct"]
            ctc = "#a8ff3e" if ct >= 0 else "#ff3ea8"
            chg_html = f'<span style="color:{ctc};font-size:10px"> {"+" if ct>=0 else ""}{ct:.2f}%</span>'

        rec_html = ""
        if res:
            rc  = REC_COLOR.get(res.get("recommendation","HOLD"),"#00e5ff")
            rru = REC_RU.get(res.get("recommendation","HOLD"),"")
            rec_html = f'<br><span style="color:{rc};font-size:10px">{rru}</span>'

        border = "2px solid #00e5ff" if is_sel else "1px solid #1e2a3a"
        st.markdown(
            f'<div style="background:#0d1520;border:{border};border-radius:8px;padding:10px 12px;margin-bottom:4px">'
            f'<span style="color:#00e5ff;font-weight:700;font-size:15px">{pos["ticker"]}</span>'
            f'{price_html}{chg_html}'
            f'<span style="color:#3a5070;font-size:10px"> {pos.get("sector","")}</span>'
            f'{rec_html}<br>'
            f'<span style="color:#3a5070;font-size:11px">{sh}шт · ср.${avg:.4f}</span>'
            f'{pl_html}</div>',
            unsafe_allow_html=True
        )

        # лоты
        for i, lot in enumerate(pos["lots"]):
            c1, c2 = st.columns([5, 1])
            lpl_html = ""
            if live:
                lpl = (live - lot["price"]) / lot["price"] * 100
                lc  = "#a8ff3e" if lpl >= 0 else "#ff3ea8"
                lpl_html = f'<span style="color:{lc}"> {"+" if lpl>=0 else ""}{lpl:.1f}%</span>'
            c1.markdown(
                f'<span style="font-size:11px;color:#4a6080">л{i+1}: {lot["shares"]}шт×${lot["price"]}</span>{lpl_html}',
                unsafe_allow_html=True
            )
            if c2.button("✕", key=f"rm_{pos['id']}_{i}"):
                pos["lots"].pop(i)
                st.rerun()

        # добавить лот
        with st.expander(f"+ лот к {pos['ticker']}"):
            ca, cb = st.columns(2)
            lsh = ca.number_input("Кол-во", min_value=0.0, step=1.0,  key=f"lsh_{pos['id']}")
            lpr = cb.number_input("Цена $",  min_value=0.0, step=0.01, key=f"lpr_{pos['id']}")
            if st.button("Добавить лот", key=f"al_{pos['id']}", use_container_width=True):
                if lsh > 0 and lpr > 0:
                    pos["lots"].append({"shares": lsh, "price": lpr})
                    st.rerun()

        # кнопки анализ / удалить
        b1, b2 = st.columns([3, 1])
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
                        st.error(f"Ошибка: {str(e)}")

        if b2.button("🗑", key=f"del_{pos['id']}", use_container_width=True):
            st.session_state.portfolio = [
                p for p in st.session_state.portfolio if p["id"] != pos["id"]
            ]
            st.session_state.results.pop(pos["id"], None)
            if st.session_state.selected == pos["id"]:
                st.session_state.selected = None
            st.rerun()

        st.markdown("<hr style='border-color:#1e2a3a;margin:6px 0'>", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════
# ГЛАВНАЯ ОБЛАСТЬ
# ════════════════════════════════════════════════════════
sel_id  = st.session_state.selected
sel_pos = next((p for p in st.session_state.portfolio if p["id"] == sel_id), None)
sel_res = st.session_state.results.get(sel_id) if sel_id else None

if not sel_res:
    st.markdown("# 📈 Speculator AI")
    st.markdown('<p style="color:#3a5070">← Выбери акцию и нажми ▶ Анализ</p>', unsafe_allow_html=True)

    # таблица портфеля с реальными ценами
    rows = []
    for p in st.session_state.portfolio:
        r   = st.session_state.results.get(p["id"])
        mkt = get_market_data(p["ticker"]) if YFINANCE_OK else None
        lp  = mkt["price"] if mkt else (r["currentPrice"] if r else None)
        avg = avg_price(p["lots"])
        pl  = f'{"+" if lp and (lp-avg)/avg*100>=0 else ""}{(lp-avg)/avg*100:.1f}%' if lp and avg else "—"
        chg = f'{mkt["change_pct"]:+.2f}%' if mkt else "—"
        rows.append({
            "Тикер":    p["ticker"],
            "Сектор":   p.get("sector",""),
            "Кол-во":   int(total_shares(p["lots"])),
            "Ср.цена":  f'${avg:.4f}',
            "Тек.цена": f'${lp}' if lp else "—",
            "Сегодня":  chg,
            "P&L":      pl,
            "Вложено":  f'${total_cost(p["lots"]):.2f}',
        })
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    st.stop()

# ── страница результата ───────────────────────────────────
r   = sel_res
pos = sel_pos
avg = avg_price(pos["lots"])

rec  = r.get("recommendation", "HOLD")
risk = r.get("risk", "HIGH")
avd  = r.get("avgDownVerdict", "NEUTRAL")
rc   = REC_COLOR.get(rec,  "#00e5ff")
rkc  = RISK_COLOR.get(risk, "#ffd700")
avdc = AVD_COLOR.get(avd,  "#ffd700")
pl   = (r["currentPrice"] - avg) / avg * 100 if avg > 0 else 0
plc  = "#a8ff3e" if pl >= 0 else "#ff3ea8"

# заголовок
st.markdown(
    f'<h1><span style="color:#00e5ff">{r["ticker"]}</span> '
    f'<span style="font-size:16px;color:#3a5070">{pos.get("sector","")}</span></h1>',
    unsafe_allow_html=True
)

c1, c2, c3, c4 = st.columns(4)

c1.markdown(
    f'<div style="background:#0d1520;border:1px solid {rc}33;border-radius:8px;padding:14px;text-align:center">'
    f'<div class="label">Рекомендация</div>'
    f'<div style="color:{rc};font-size:16px;font-weight:700;margin-top:4px">'
    f'{REC_EMOJI.get(rec,"")} {REC_RU.get(rec,rec)}</div>'
    f'<div style="color:{rc};font-size:11px">уверенность {r.get("confidence",0)}%</div>'
    f'</div>', unsafe_allow_html=True
)

today_html = ""
if "changeToday" in r:
    ct  = r["changeToday"]
    ctc = "#a8ff3e" if ct >= 0 else "#ff3ea8"
    today_html = f'<div style="color:{ctc};font-size:12px">{"+" if ct>=0 else ""}{ct:.2f}% сегодня</div>'

c2.markdown(
    f'<div style="background:#0d1520;border:1px solid #1e2a3a;border-radius:8px;padding:14px;text-align:center">'
    f'<div class="label">Цена (реальная)</div>'
    f'<div style="font-size:26px;font-weight:700">${r.get("currentPrice","—")}</div>'
    f'{today_html}</div>', unsafe_allow_html=True
)

c3.markdown(
    f'<div style="background:#0d1520;border:1px solid {rkc}33;border-radius:8px;padding:14px;text-align:center">'
    f'<div class="label">Риск</div>'
    f'<div style="color:{rkc};font-size:16px;font-weight:700">{RISK_RU.get(risk,risk)}</div>'
    f'<div style="color:#3a5070;font-size:11px">стоп ${r.get("stopLoss","—")}</div>'
    f'</div>', unsafe_allow_html=True
)

c4.markdown(
    f'<div style="background:#0d1520;border:1px solid {plc}33;border-radius:8px;padding:14px;text-align:center">'
    f'<div class="label">P&L позиции</div>'
    f'<div style="color:{plc};font-size:26px;font-weight:700">{"+" if pl>=0 else ""}{pl:.1f}%</div>'
    f'<div style="color:#3a5070;font-size:11px">ср.вход ${avg:.4f}</div>'
    f'</div>', unsafe_allow_html=True
)

if r.get("delistingRisk"):
    st.error("🚨 Высокий риск делистинга!")

st.divider()

# ── ГРАФИК ────────────────────────────────────────────────
st.markdown("#### 📈 График цены")

PERIODS = {"1 нед":"5d","1 мес":"1mo","3 мес":"3mo","6 мес":"6mo","1 год":"1y","2 года":"2y"}
period_choice = st.radio(
    "Период:", list(PERIODS.keys()), index=2,
    horizontal=True, label_visibility="collapsed"
)
mkt_chart = get_market_data(pos["ticker"], period=PERIODS[period_choice]) if YFINANCE_OK else None

if mkt_chart and mkt_chart.get("history") is not None:
    hist = mkt_chart["history"].copy()
    hist.index = pd.to_datetime(hist.index).tz_localize(None)
    hist["Ср. цена входа"] = avg
    hist = hist.rename(columns={"Close": pos["ticker"]})
    st.line_chart(
        hist[[pos["ticker"], "Ср. цена входа"]],
        color=["#00e5ff", "#ff3ea8"],
        height=300,
    )
    # лоты под графиком
    lot_cols = st.columns(len(pos["lots"]))
    for i, (lot, col) in enumerate(zip(pos["lots"], lot_cols)):
        lpl = (r["currentPrice"] - lot["price"]) / lot["price"] * 100 if r.get("currentPrice") else None
        lc  = "#a8ff3e" if lpl and lpl >= 0 else "#ff3ea8"
        col.markdown(
            f'<div style="background:#0d1520;border:1px solid #1e2a3a;border-radius:6px;'
            f'padding:8px;text-align:center">'
            f'<div style="color:#3a5070;font-size:9px">ЛОТ {i+1}</div>'
            f'<div style="font-weight:700">${lot["price"]}</div>'
            f'{"<div style=color:" + lc + ";font-size:11px>" + ("+" if lpl>=0 else "") + f"{lpl:.1f}%" + "</div>" if lpl is not None else ""}'
            f'</div>', unsafe_allow_html=True
        )
    with st.expander("📊 Объём"):
        if "Volume" in hist.columns:
            st.bar_chart(hist[["Volume"]], height=120, color="#1e3a2a")
else:
    st.info("📡 Реальный график недоступен" if not YFINANCE_OK else "⚠ Нет данных для этого тикера")

st.divider()

# ── метрики ───────────────────────────────────────────────
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("52н Макс",   f'${r.get("weekHigh52","—")}')
m2.metric("52н Мин",    f'${r.get("weekLow52","—")}')
m3.metric("Кап.",        r.get("marketCap","—"))
m4.metric("Шорт %",     r.get("shortInterest","—"))
m5.metric("Разводнение", r.get("dilutionRisk","—"))

st.divider()

# ── вкладки ───────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs(["📰 Обзор","🎯 Торговый план","🧾 Покупки","🧠 Психология"])

with tab1:
    st.markdown("#### Ситуация")
    st.info(r.get("context",""))

    if len(pos["lots"]) > 1:
        st.markdown("#### Усреднение")
        st.markdown(
            f'<div style="background:#0d1520;border-left:3px solid {avdc};border-radius:6px;padding:12px">'
            f'<span style="color:{avdc};font-weight:700">{AVD_RU.get(avd,avd)}</span> — '
            f'<span style="color:#8899aa">{r.get("avgDownReason","")}</span></div>',
            unsafe_allow_html=True
        )

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### ◈ Катализаторы")
        for c in r.get("catalysts", []): st.markdown(f"• {c}")
    with col2:
        st.markdown("#### ▲ Риски")
        for rv in r.get("risks", []): st.markdown(f"• {rv}")

with tab2:
    t1, t2, t3 = st.columns(3)
    t1.markdown(
        f'<div style="background:#0d1520;border:1px solid #ff3ea833;border-radius:8px;padding:16px;text-align:center">'
        f'<div class="label">МЕДВЕДЬ</div>'
        f'<div style="color:#ff3ea8;font-size:28px;font-weight:700">${r.get("targetLow","—")}</div></div>',
        unsafe_allow_html=True
    )
    t2.markdown(
        f'<div style="background:#0d1520;border:1px solid #ffd70033;border-radius:8px;padding:16px;text-align:center">'
        f'<div class="label">БАЗА</div>'
        f'<div style="color:#ffd700;font-size:28px;font-weight:700">${r.get("targetBase","—")}</div></div>',
        unsafe_allow_html=True
    )
    t3.markdown(
        f'<div style="background:#0d1520;border:1px solid {rc}33;border-radius:8px;padding:16px;text-align:center">'
        f'<div class="label">БЫК</div>'
        f'<div style="color:{rc};font-size:28px;font-weight:700">${r.get("targetHigh","—")}</div></div>',
        unsafe_allow_html=True
    )

    if r.get("currentPrice") and r.get("stopLoss") and r.get("targetBase"):
        risk_a = r["currentPrice"] - r["stopLoss"]
        rew_a  = r["targetBase"]   - r["currentPrice"]
        if risk_a > 0 and rew_a > 0:
            rr  = rew_a / risk_a
            rrc = "#a8ff3e" if rr >= 2 else "#ffd700" if rr >= 1 else "#ff3ea8"
            st.markdown(
                f'**R/R:** <span style="color:#ff3ea8">-{risk_a/r["currentPrice"]*100:.1f}%</span> / '
                f'<span style="color:#a8ff3e">+{rew_a/r["currentPrice"]*100:.1f}%</span> · '
                f'<span style="color:{rrc};font-weight:700">{rr:.1f}:1</span>',
                unsafe_allow_html=True
            )

    st.markdown("#### 💡 Торговый план")
    st.markdown(
        f'<div style="background:rgba(199,125,255,.08);border:1px solid #c77dff33;'
        f'border-radius:8px;padding:16px;color:#c77dff;line-height:1.8">'
        f'{r.get("speculatorTip","")}</div>',
        unsafe_allow_html=True
    )
    st.markdown(f"**Стоп-лосс:** :red[${r.get('stopLoss','—')}]")

with tab3:
    live_p    = r.get("currentPrice")
    total_pnl = 0
    for i, lot in enumerate(pos["lots"]):
        lpl   = (live_p - lot["price"]) / lot["price"] * 100 if live_p else None
        lc    = "#a8ff3e" if lpl and lpl >= 0 else "#ff3ea8"
        pnl_u = (live_p - lot["price"]) * lot["shares"] if live_p else None
        if pnl_u:
            total_pnl += pnl_u
        st.markdown(
            f'<div style="background:#0d1520;border:1px solid #1e2a3a;border-radius:6px;'
            f'padding:10px 14px;margin-bottom:6px">'
            f'Лот {i+1}: <b>{lot["shares"]}шт × ${lot["price"]}</b> = ${lot["shares"]*lot["price"]:.2f}'
            f'<span style="color:{lc};font-weight:700;float:right">'
            f'{"+" if lpl and lpl>=0 else ""}{lpl:.1f}%  '
            f'{"+" if pnl_u and pnl_u>=0 else ""}{"${:.2f}".format(pnl_u) if pnl_u else ""}'
            f'</span></div>',
            unsafe_allow_html=True
        )
    if live_p:
        tplc = "#a8ff3e" if total_pnl >= 0 else "#ff3ea8"
        st.markdown(
            f'<div style="background:#0d1520;border-left:3px solid {tplc};border-radius:6px;padding:12px 14px">'
            f'<span style="color:#8899aa">Итого P&L: </span>'
            f'<span style="color:{tplc};font-weight:700;font-size:18px">'
            f'{"+" if total_pnl>=0 else ""}${total_pnl:.2f} ({"+" if pl>=0 else ""}{pl:.1f}%)'
            f'</span></div>',
            unsafe_allow_html=True
        )

with tab4:
    if r.get("psychNote"):
        st.markdown(
            f'<div style="background:rgba(255,215,0,.05);border:1px solid #ffd70033;'
            f'border-radius:8px;padding:16px;color:#ffd700;line-height:1.8">'
            f'🧠 {r["psychNote"]}</div>',
            unsafe_allow_html=True
        )
    if len(pos["lots"]) >= 3:
        st.warning("⚠ Усреднение 3+ раз — часто признак 'надежды вместо стратегии'.")
    if rec in ("SELL","URGENT SELL"):
        st.error("🚨 AI рекомендует продавать — проверь свой тезис.")
    if avg > r.get("currentPrice", avg):
        st.markdown(
            '<div style="background:rgba(255,107,53,.07);border:1px solid #ff6b3533;'
            'border-radius:8px;padding:12px;color:#ff6b35aa;margin-top:8px">'
            '💡 Спроси себя: «Купил бы я эту акцию сегодня по текущей цене?» '
            'Если нет — возможно стоит пересмотреть позицию.'
            '</div>',
            unsafe_allow_html=True
        )

st.divider()
st.caption("⚠ Не является инвестиционной рекомендацией.")
