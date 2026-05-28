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

try:
    from streamlit_javascript import st_javascript
    JS_OK = True
except ImportError:
    JS_OK = False

LS_KEY = "speculator_v3"

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

# ── session state ─────────────────────────────────────────
def _init():
    for k,v in {
        "portfolio":None,"next_id":10,"results":{},"selected":None,
        "history":{},"portfolio_analysis":None,"dark_mode":True,"ls_loaded":False,
        "trades":{},   # {pos_id: [{"date","shares","sell_price","avg_cost","pnl","pnl_pct"}]}
    }.items():
        if k not in st.session_state:
            st.session_state[k]=v
_init()

# ── localStorage через streamlit-javascript ───────────────
def ls_read():
    """Читает localStorage. Возвращает строку или None."""
    if not JS_OK: return None
    val = st_javascript(f"localStorage.getItem('{LS_KEY}')")
    if val and isinstance(val, str) and len(val) > 5:
        return val
    return None

def ls_write(portfolio, history, next_id, trades):
    """Пишет в localStorage."""
    if not JS_OK: return
    payload = json.dumps({
        "portfolio": portfolio,
        "history":   history,
        "trades":    trades,
        "next_id":   next_id,
        "saved_at":  datetime.now().isoformat(),
    }, ensure_ascii=False)
    safe = payload.replace("\\","\\\\").replace("`","\\`").replace("'","\\'")
    st_javascript(f"localStorage.setItem('{LS_KEY}', '{safe}'); 1")

def ls_clear():
    if not JS_OK: return
    st_javascript(f"localStorage.removeItem('{LS_KEY}'); 1")

def save_to_ls():
    ls_write(
        st.session_state.portfolio,
        st.session_state.history,
        st.session_state.next_id,
        st.session_state.trades,
    )

# ── загрузка при первом запуске ───────────────────────────
if not st.session_state.ls_loaded:
    if JS_OK:
        raw = ls_read()
        if raw:
            try:
                loaded = json.loads(raw)
                port = loaded.get("portfolio")
                if port and isinstance(port, list) and len(port) > 0:
                    st.session_state.portfolio = port
                    st.session_state.history = {
                        int(k): v for k, v in loaded.get("history", {}).items()
                    }
                    st.session_state.trades = {
                        int(k): v for k, v in loaded.get("trades", {}).items()
                    }
                    st.session_state.next_id = loaded.get("next_id", 10)
            except Exception:
                pass
    if st.session_state.portfolio is None:
        st.session_state.portfolio = DEFAULT_PORTFOLIO
    st.session_state.ls_loaded = True

if st.session_state.portfolio is None:
    st.session_state.portfolio = DEFAULT_PORTFOLIO

# ── тема ─────────────────────────────────────────────────
if st.session_state.dark_mode:
    BG,BG2,BORDER = "#080b12","#0d1520","#1e2a3a"
    TEXT,TEXT_DIM  = "#e8eaf0","#8899aa"
    TEXT_MUTE      = "#3a5070"
    LABEL_CSS      = "color:#3a5070"
    SIDEBAR_BG     = "#0d1520"
else:
    BG,BG2,BORDER = "#f0f4f8","#ffffff","#c8d8e8"
    TEXT,TEXT_DIM  = "#0d1a2a","#3a5070"
    TEXT_MUTE      = "#8899aa"
    LABEL_CSS      = "color:#8899aa"
    SIDEBAR_BG     = "#e0e8f0"

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
/* скрываем все iframes от st_javascript */
iframe[height="0"]{{display:none!important;}}
</style>
""", unsafe_allow_html=True)

# ── helpers ───────────────────────────────────────────────
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
    ad=len(pos["lots"]); hb=max(l["price"] for l in pos["lots"])
    adp=((hb-avg)/hb*100) if ad>1 else 0
    mf=""
    if mkt:
        mf=(f"\nREAL MARKET DATA:\n- Price: ${mkt['price']}\n- Change: {mkt['change_pct']:+.2f}%\n"
            f"- 52w H/L: ${mkt['high_52w']}/${mkt['low_52w']}\n- P&L: {pl_pct:+.1f}%")
    lots_str = ", ".join(
        "L" + str(i+1) + ":" + str(l["shares"]) + "@$" + str(l["price"])
        for i, l in enumerate(pos["lots"])
    )
    avg_note = f"Averaged {ad}x, avg down {adp:.1f}%" if ad > 1 else "Single entry."
    json_schema = (
        '{"recommendation":"HOLD","risk":"HIGH","confidence":55,"delistingRisk":false,'
        '"dilutionRisk":"MEDIUM","avgDownVerdict":"NEUTRAL","avgDownReason":"one sentence",'
        '"context":"2-3 sentences","speculatorTip":"trade plan","catalysts":["c1","c2"],'
        '"risks":["r1","r2"],"targetLow":0.00,"targetBase":0.00,"targetHigh":0.00,'
        '"stopLoss":0.00,"psychNote":"bias"}'
    )
    prompt = (
        f"Prop trader. Analyze position.\n"
        f"STOCK: {pos['ticker']} [{pos.get('sector','')}]\n"
        f"POSITION: {sh}sh avg ${avg:.4f} invested ${cost:.2f}\n"
        f"LOTS: {lots_str}\n"
        f"{avg_note}{mf}\n"
        f"Return ONLY JSON:\n{json_schema}\n"
        f"recommendation=STRONG BUY|BUY MORE|HOLD|REDUCE|SELL|URGENT SELL "
        f"risk=LOW|MEDIUM|HIGH|VERY HIGH|EXTREME avgDownVerdict=SMART|NEUTRAL|MISTAKE"
    )
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
        rows.append(f"{p['ticker']} [{p.get('sector','')}]: avg ${avg:.3f}, ${cost:.0f}"
                    +(f", now ${mkt['price']}, P&L {pl:+.1f}%" if pl is not None else ""))
    prompt=(f"Portfolio risk manager. 3-4 sentences in Russian. "
            f"Overall risk, sector concentration, main concern, one action.\n"
            f"PORTFOLIO:\n{chr(10).join(rows)}\nRussian only, plain text.")
    client=anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
    msg=client.messages.create(model="claude-haiku-4-5-20251001",max_tokens=300,
                               messages=[{"role":"user","content":prompt}])
    return msg.content[0].text

# ════════════════════════════════════════════════════════
# SIDEBAR
# ════════════════════════════════════════════════════════
with st.sidebar:
    cl,ct=st.columns([3,1])
    with cl: st.markdown("## 📊 Портфель")
    with ct:
        if st.button("☀️" if st.session_state.dark_mode else "🌙",key="theme_btn"):
            st.session_state.dark_mode=not st.session_state.dark_mode; st.rerun()

    grand=sum(total_cost(p["lots"]) for p in st.session_state.portfolio)
    st.caption(f"{len(st.session_state.portfolio)} позиций · ${grand:.2f} вложено")

    if JS_OK:
        st.markdown(
            f'<div style="background:{BG2};border:1px solid #a8ff3e44;border-radius:6px;'
            f'padding:5px 10px;font-size:11px;color:#a8ff3e;margin:4px 0">'
            f'💾 Данные сохраняются в браузере</div>', unsafe_allow_html=True)
    else:
        st.warning("⚠ streamlit-javascript не установлен — данные не сохраняются")

    if st.session_state.selected is not None:
        if st.button("← Сводка",use_container_width=True,key="back_btn"):
            st.session_state.selected=None; st.rerun()

    if st.button("🗑 Сбросить данные",use_container_width=True,key="clear_btn"):
        ls_clear()
        for k in ["portfolio","history","results","selected","portfolio_analysis","ls_loaded"]:
            st.session_state.pop(k,None)
        st.rerun()

    st.divider()

    with st.expander("➕ Новая акция"):
        nt=st.text_input("Тикер",key="new_t",placeholder="GME").upper().strip()
        ns=st.text_input("Сектор",key="new_s",placeholder="Gaming")
        if st.button("Добавить",use_container_width=True,key="add_btn"):
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
            ct2=mkt["change_pct"]; ctc="#a8ff3e" if ct2>=0 else "#ff3ea8"
            chg_html=f'<span style="color:{ctc};font-size:10px"> {"+" if ct2>=0 else ""}{ct2:.2f}%</span>'
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

        # ── продажа ──
        if pos["lots"]:
            with st.expander(f"💰 Продать {pos['ticker']}"):
                avg_now = avg_price(pos["lots"])
                max_sh  = int(total_shares(pos["lots"]))
                sa,sb   = st.columns(2)
                sell_sh = sa.number_input("Кол-во",min_value=0.0,max_value=float(max_sh),
                                          step=1.0,key=f"ssh_{pos['id']}")
                sell_pr = sb.number_input("Цена $",min_value=0.0,step=0.01,
                                          key=f"spr_{pos['id']}")
                if sell_sh > 0 and sell_pr > 0:
                    trade_pnl = (sell_pr - avg_now) * sell_sh
                    pnl_c = "#a8ff3e" if trade_pnl >= 0 else "#ff3ea8"
                    st.markdown(
                        f'<div style="text-align:center;font-size:13px">'
                        f'P&L этой продажи: <span style="color:{pnl_c};font-weight:700">'
                        f'{"+" if trade_pnl>=0 else ""}${trade_pnl:.2f}</span></div>',
                        unsafe_allow_html=True)
                if st.button(f"✅ Продать",key=f"sell_{pos['id']}",use_container_width=True):
                    if sell_sh > 0 and sell_pr > 0 and sell_sh <= max_sh:
                        # считаем P&L по средней цене входа
                        trade_pnl     = (sell_pr - avg_now) * sell_sh
                        trade_pnl_pct = (sell_pr - avg_now) / avg_now * 100 if avg_now > 0 else 0
                        # сохраняем сделку
                        trade_entry = {
                            "date":      datetime.now().strftime("%d.%m.%Y %H:%M"),
                            "ticker":    pos["ticker"],
                            "shares":    sell_sh,
                            "sell_price":sell_pr,
                            "avg_cost":  round(avg_now, 4),
                            "pnl":       round(trade_pnl, 2),
                            "pnl_pct":   round(trade_pnl_pct, 2),
                        }
                        pid = pos["id"]
                        if pid not in st.session_state.trades:
                            st.session_state.trades[pid] = []
                        st.session_state.trades[pid].insert(0, trade_entry)
                        # списываем акции из лотов (FIFO)
                        remaining = sell_sh
                        new_lots  = []
                        for lot in pos["lots"]:
                            if remaining <= 0:
                                new_lots.append(lot)
                            elif lot["shares"] <= remaining:
                                remaining -= lot["shares"]
                            else:
                                new_lots.append({"shares": lot["shares"] - remaining,
                                                 "price":  lot["price"]})
                                remaining = 0
                        pos["lots"] = new_lots
                        # если все акции проданы — удаляем позицию
                        if not pos["lots"]:
                            st.session_state.portfolio = [
                                p for p in st.session_state.portfolio if p["id"] != pid]
                            if st.session_state.selected == pid:
                                st.session_state.selected = None
                        save_to_ls(); st.rerun()
                    else:
                        st.error("Проверь количество и цену")

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
# ГЛАВНАЯ ОБЛАСТЬ
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

    # ── БАЛАНС ───────────────────────────────────────────────
    realized_pnl   = sum(t["pnl"] for trades in st.session_state.trades.values() for t in trades)
    unrealized_pnl = 0.0
    total_invested = 0.0
    for p in st.session_state.portfolio:
        if not p["lots"]: continue
        avg = avg_price(p["lots"])
        cost= total_cost(p["lots"])
        total_invested += cost
        mkt = get_market_data(p["ticker"]) if YFINANCE_OK else None
        r2  = st.session_state.results.get(p["id"])
        lp  = mkt["price"] if mkt else (r2.get("currentPrice") if r2 else None)
        if lp and avg > 0:
            unrealized_pnl += (lp - avg) * total_shares(p["lots"])

    total_pnl = realized_pnl + unrealized_pnl
    tc = "#a8ff3e" if total_pnl >= 0 else "#ff3ea8"
    rc2= "#a8ff3e" if realized_pnl >= 0 else "#ff3ea8"
    uc = "#a8ff3e" if unrealized_pnl >= 0 else "#ff3ea8"

    st.markdown(f'<h3 style="color:{TEXT}">💼 Баланс</h3>', unsafe_allow_html=True)
    b1,b2,b3,b4 = st.columns(4)
    b1.markdown(
        f'<div style="background:{BG2};border:1px solid {tc}33;border-radius:8px;padding:14px;text-align:center">'
        f'<div class="label">Итог (реал.+нереал.)</div>'
        f'<div style="color:{tc};font-size:22px;font-weight:700">{"+" if total_pnl>=0 else ""}${total_pnl:.2f}</div>'
        f'</div>', unsafe_allow_html=True)
    b2.markdown(
        f'<div style="background:{BG2};border:1px solid {rc2}33;border-radius:8px;padding:14px;text-align:center">'
        f'<div class="label">Реализовано (продажи)</div>'
        f'<div style="color:{rc2};font-size:22px;font-weight:700">{"+" if realized_pnl>=0 else ""}${realized_pnl:.2f}</div>'
        f'</div>', unsafe_allow_html=True)
    b3.markdown(
        f'<div style="background:{BG2};border:1px solid {uc}33;border-radius:8px;padding:14px;text-align:center">'
        f'<div class="label">Нереализовано (сейчас)</div>'
        f'<div style="color:{uc};font-size:22px;font-weight:700">{"+" if unrealized_pnl>=0 else ""}${unrealized_pnl:.2f}</div>'
        f'</div>', unsafe_allow_html=True)
    b4.markdown(
        f'<div style="background:{BG2};border:1px solid {BORDER};border-radius:8px;padding:14px;text-align:center">'
        f'<div class="label">Вложено сейчас</div>'
        f'<div style="color:{TEXT};font-size:22px;font-weight:700">${total_invested:.2f}</div>'
        f'</div>', unsafe_allow_html=True)

    # ── история продаж ────────────────────────────────────────
    all_trades = []
    for pid, tlist in st.session_state.trades.items():
        for t in tlist:
            all_trades.append(t)
    all_trades.sort(key=lambda x: x["date"], reverse=True)

    if all_trades:
        st.markdown(f'<h3 style="color:{TEXT}">📤 История продаж</h3>', unsafe_allow_html=True)
        for t in all_trades:
            pc = "#a8ff3e" if t["pnl"] >= 0 else "#ff3ea8"
            st.markdown(
                f'<div style="background:{BG2};border-left:4px solid {pc};border-radius:6px;'
                f'padding:8px 14px;margin:4px 0;font-size:12px">'
                f'<span style="color:{TEXT_MUTE}">{t["date"]}</span>  '
                f'<span style="color:#00e5ff;font-weight:700">{t["ticker"]}</span>  '
                f'<span style="color:{TEXT}">{int(t["shares"])}шт × ${t["sell_price"]}</span>  '
                f'<span style="color:{TEXT_MUTE}">вход ${t["avg_cost"]}</span>  '
                f'<span style="color:{pc};font-weight:700">{"+" if t["pnl"]>=0 else ""}${t["pnl"]:.2f} '
                f'({"+" if t["pnl_pct"]>=0 else ""}{t["pnl_pct"]:.1f}%)</span>'
                f'</div>', unsafe_allow_html=True)

    st.divider()
    ca1,ca2=st.columns([3,1])
    with ca1:
        st.markdown(f'<h3 style="color:{TEXT}">🤖 Сводный AI анализ</h3>',unsafe_allow_html=True)
        st.caption("~$0.0003 · max 300 токенов")
    with ca2:
        if st.button("▶ Анализировать",use_container_width=True,key="pa_btn"):
            with st.spinner("Анализирую..."):
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
                rru=REC_RU.get(e.get("recommendation","HOLD"),"")
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
    ct2=r["changeToday"]; ctc="#a8ff3e" if ct2>=0 else "#ff3ea8"
    th=f'<div style="color:{ctc};font-size:12px">{"+" if ct2>=0 else ""}{ct2:.2f}% сегодня</div>'
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
                        f'<span style="color:{rrc};font-weight:700">{rr:.1f}:1</span>',
                        unsafe_allow_html=True)
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
        st.markdown(f'<p style="color:{TEXT_MUTE}">История пуста.</p>',unsafe_allow_html=True)
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
