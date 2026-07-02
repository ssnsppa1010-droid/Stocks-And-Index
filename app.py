# ============================================================
#  Multi-Broker Stock / Index / MCX Data Downloader  (WEBSITE version)
#  - Select a broker from the dropdown
#  - Angel One  -> Stocks, Index      (fully working)
#  - Fyers      -> MCX commodities    (fully working)
#  - Other brokers = "not supported yet" message
#  - To add a broker: add an entry in the BROKERS dict below
#  Run:  streamlit run app.py
# ============================================================

import streamlit as st
import pandas as pd
import requests, pyotp, time, io, zipfile
from datetime import datetime, timedelta

st.set_page_config(page_title="Stock / Index / MCX Data Downloader",
                   page_icon="📈", layout="centered")
st.title("Stock / Index / MCX Data Downloader")
st.caption("Select broker -> enter login -> enter names -> download CSV.")

# ============================================================
#  PART A : ANGEL ONE adapter  (Stocks + Index)
# ============================================================
ANGEL_NATIVE = {
    '1min':'ONE_MINUTE', '3min':'THREE_MINUTE', '5min':'FIVE_MINUTE',
    '10min':'TEN_MINUTE', '15min':'FIFTEEN_MINUTE', '30min':'THIRTY_MINUTE',
    '1h':'ONE_HOUR', '1day':'ONE_DAY'
}
ANGEL_RESAMPLE = {
    '2h':('ONE_HOUR','2h'), '4h':('ONE_HOUR','4h'),
    '1week':('ONE_DAY','1W'), '1month':('ONE_DAY','1ME')
}
ANGEL_CHUNK = {
    'ONE_MINUTE':25, 'THREE_MINUTE':50, 'FIVE_MINUTE':90, 'TEN_MINUTE':90,
    'FIFTEEN_MINUTE':180, 'THIRTY_MINUTE':180, 'ONE_HOUR':90, 'ONE_DAY':1500
}
ANGEL_KNOWN_INDEX = {
    'NIFTY50':'99926000', 'NIFTYBANK':'99926009', 'NIFTY500':'99926004',
    'NIFTY100':'99926012', 'NIFTYNEXT50':'99926013', 'NIFTYMIDCAP100':'99926011',
    'NIFTYMIDCAP50':'99926014', 'NIFTYIT':'99926008', 'INDIAVIX':'99926017',
    'NIFTYREALTY':'99926018', 'NIFTYINFRA':'99926019',
}

def _norm(s):
    return str(s).upper().replace(' ', '').replace('-', '')

@st.cache_data(show_spinner="Loading Angel instrument list...")
def angel_instruments():
    url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
    return pd.DataFrame(requests.get(url).json())

def angel_login(creds):
    from SmartApi import SmartConnect
    obj = SmartConnect(api_key=creds['api_key'])
    data = obj.generateSession(creds['client_id'], creds['mpin'],
                               pyotp.TOTP(creds['totp_secret']).now())
    if not data.get('status'):
        raise Exception("Login failed. Please check your details.")
    return obj

def angel_get_token(session, name, data_type):
    inst = angel_instruments()
    if data_type == 'stocks':
        df = inst[(inst['name'] == name) & (inst['exch_seg'] == 'NSE') &
                  (inst['instrumenttype'] == '')]
        return df.iloc[0]['token'] if len(df) else None
    else:  # index
        key = _norm(name)
        if key in ANGEL_KNOWN_INDEX:
            return ANGEL_KNOWN_INDEX[key]
        idx = inst[(inst['exch_seg'] == 'NSE') & (inst['instrumenttype'] == 'AMXIDX')]
        for col in ['name', 'symbol']:
            if col in idx.columns:
                m = idx[idx[col].apply(_norm) == key]
                if len(m):
                    return m.iloc[0]['token']
        return None

def angel_fetch(session, token, timeframe, from_date, to_date):
    if timeframe in ANGEL_NATIVE:
        interval, resample_to = ANGEL_NATIVE[timeframe], None
    else:
        interval, resample_to = ANGEL_RESAMPLE[timeframe]
    chunk_days = ANGEL_CHUNK[interval]

    all_data, current = [], from_date
    while current < to_date:
        end = min(current + timedelta(days=chunk_days), to_date)
        params = {"exchange":"NSE", "symboltoken":token, "interval":interval,
                  "fromdate":current.strftime("%Y-%m-%d %H:%M"),
                  "todate":end.strftime("%Y-%m-%d %H:%M")}
        try:
            res = session.getCandleData(params)
            if res and res.get('data'):
                all_data.extend(res['data'])
        except Exception:
            time.sleep(3)
        current = end + timedelta(days=1)
        time.sleep(1)

    if not all_data:
        return None
    df = pd.DataFrame(all_data, columns=['Date','Open','High','Low','Close','Volume'])
    df['Date'] = pd.to_datetime(df['Date'])
    df.set_index('Date', inplace=True)
    if resample_to:
        df = df.resample(resample_to).agg({'Open':'first','High':'max','Low':'min',
                                           'Close':'last','Volume':'sum'}).dropna()
    return df

# ============================================================
#  PART A2 : FYERS adapter  (Stocks + Index + MCX)
#  Login = App ID + Access Token (generate token separately, paste here).
# ============================================================
FYERS_RES = {'1min':'1', '5min':'5', '15min':'15', '30min':'30',
             '1h':'60', '4h':'240', '1day':'D'}

# Common index name -> Fyers symbol (fallback builds NSE:<NAME>-INDEX)
FYERS_INDEX_MAP = {
    'NIFTY50':'NSE:NIFTY50-INDEX', 'NIFTY':'NSE:NIFTY50-INDEX',
    'NIFTYBANK':'NSE:NIFTYBANK-INDEX', 'BANKNIFTY':'NSE:NIFTYBANK-INDEX',
    'NIFTY500':'NSE:NIFTY500-INDEX', 'NIFTY100':'NSE:NIFTY100-INDEX',
    'NIFTYNEXT50':'NSE:NIFTYNEXT50-INDEX', 'NIFTYIT':'NSE:NIFTYIT-INDEX',
    'FINNIFTY':'NSE:FINNIFTY-INDEX', 'MIDCPNIFTY':'NSE:MIDCPNIFTY-INDEX',
    'INDIAVIX':'NSE:INDIAVIX-INDEX',
}

@st.cache_data(show_spinner="Loading Fyers MCX symbol master...")
def fyers_mcx_master():
    url = "https://public.fyers.in/sym_details/MCX_COM.csv"
    return pd.read_csv(url, header=None, dtype=str)

def fyers_login(creds):
    from fyers_apiv3 import fyersModel
    fy = fyersModel.FyersModel(client_id=creds['client_id'],
                               token=creds['access_token'],
                               is_async=False, log_path="")
    prof = fy.get_profile()
    if prof.get('s') != 'ok':
        raise Exception("Fyers login failed. Access token may be expired - "
                        "generate a fresh token and paste it again.")
    return fy

def fyers_find_mcx_symbol(name):
    mcx = fyers_mcx_master()
    key = name.upper()
    for c in mcx.columns:
        col = mcx[c].astype(str)
        if col.str.startswith("MCX:").any():
            cand = mcx[col.str.upper().str.contains(f":{key}", na=False) &
                       col.str.upper().str.contains("FUT", na=False) &
                       ~col.str.upper().str.contains("OPT", na=False)]
            if len(cand):
                syms = [s for s in cand[c].tolist()
                        if s.upper().split(':')[1].startswith(key)]
                if syms:
                    return sorted(syms)[0]   # nearest active contract
    return None

def fyers_get_token(session, name, data_type):
    if data_type == 'mcx':
        # e.g. MCX:GOLDM...FUT (front-month, from the master)
        return fyers_find_mcx_symbol(name)
    elif data_type == 'stocks':
        # NSE equity: NSE:SBIN-EQ  (keep hyphens like BAJAJ-AUTO, M&M)
        key = name.strip().upper()
        return f"NSE:{key}-EQ"
    elif data_type == 'index':
        # NSE index: NSE:NIFTY50-INDEX  (map known ones, else build it)
        key = name.strip().upper().replace(' ', '')
        return FYERS_INDEX_MAP.get(key, f"NSE:{key}-INDEX")
    return None

def fyers_fetch(session, symbol, timeframe, from_date, to_date):
    res = FYERS_RES[timeframe]
    chunk_days = 360 if res == 'D' else 90
    all_c, cur = [], from_date
    while cur < to_date:
        end = min(cur + timedelta(days=chunk_days), to_date)
        data = {"symbol":symbol, "resolution":res, "date_format":"1",
                "range_from":cur.strftime("%Y-%m-%d"),
                "range_to":end.strftime("%Y-%m-%d"),
                "cont_flag": "1" if "FUT" in symbol.upper() else "0"}
        try:
            r = session.history(data=data)
            if r.get('s') == 'ok' and r.get('candles'):
                all_c.extend(r['candles'])
        except Exception:
            time.sleep(2)
        cur = end + timedelta(days=1)
        time.sleep(0.4)

    if not all_c:
        return None
    df = pd.DataFrame(all_c, columns=['ts','Open','High','Low','Close','Volume'])
    df['Date'] = pd.to_datetime(df['ts'], unit='s', utc=True).dt.tz_convert('Asia/Kolkata')
    df = df.drop(columns=['ts']).set_index('Date').sort_index()
    df = df[~df.index.duplicated(keep='first')]
    return df

# ============================================================
#  PART B : BROKERS registry
# ============================================================
BROKERS = {
    "Angel One": {
        "supported": True,
        "data_types": ["stocks", "index"],
        "fields": [   # (key, label, is-password?)
            ("api_key",     "API Key",         True),
            ("client_id",   "Client ID",       False),
            ("mpin",        "MPIN / Password",  True),
            ("totp_secret", "TOTP Secret",      True),
        ],
        "timeframes": list(ANGEL_NATIVE) + list(ANGEL_RESAMPLE),
        "login":     angel_login,
        "get_token": angel_get_token,
        "fetch":     angel_fetch,
    },

    "Fyers": {
        "supported": True,
        "data_types": ["stocks", "index", "mcx"],
        "fields": [
            ("client_id",    "App ID (client_id)", False),
            ("access_token", "Access Token",       True),
        ],
        "timeframes": list(FYERS_RES),
        "login":     fyers_login,
        "get_token": fyers_get_token,
        "fetch":     fyers_fetch,
        "login_help": "Note: the Fyers access token expires (usually by the next "
                      "morning). Generate a fresh token with your auto-token method "
                      "and paste it here each time.",
    },

    # ---- not added yet (slots only) ----
    "Zerodha": {
        "supported": False,
        "note": "Zerodha uses OAuth login (click a link, get a token) and needs "
                "a ~Rs.2000/month subscription for historical data."},
    "Upstox": {
        "supported": False,
        "note": "Upstox uses OAuth login. Can be added once the account is ready."},
    "Dhan": {
        "supported": False,
        "note": "Dhan uses access-token login. Needs a ~Rs.500/month data plan."},
}

# labels + example placeholders per data type
TYPE_LABELS  = {"stocks":"Stocks", "index":"Index", "mcx":"MCX"}
PLACEHOLDERS = {"stocks":"SBIN, RELIANCE, TCS",
                "index":"NIFTY50, NIFTYBANK, NIFTY500",
                "mcx":"GOLDM, SILVERM, CRUDEOIL"}

# All 3 segments are always shown. Each broker only *supports* some of them.
ALL_SEGMENTS = ["stocks", "index", "mcx"]
# For each segment, which supported brokers can provide it (for a helpful hint)
SEGMENT_PROVIDERS = {
    seg: [n for n, b in BROKERS.items()
          if b.get("supported") and seg in b.get("data_types", [])]
    for seg in ALL_SEGMENTS
}

# ============================================================
#  PART C : UI
# ============================================================
st.subheader("1. Select your broker")
broker_name = st.selectbox("Broker", list(BROKERS.keys()))
broker = BROKERS[broker_name]

if not broker.get("supported"):
    st.warning(f"**{broker_name}** is not supported yet.\n\n{broker.get('note','')}")
    st.info("For now, please select **Angel One** (Stocks/Index) or **Fyers** (MCX).")
    st.stop()

st.subheader("2. Your login")
st.info("These details belong to your own account. We do not save anything - "
        "you enter them each time.")
if broker.get("login_help"):
    st.caption(broker["login_help"])

creds = {}
field_list = broker["fields"]
for j in range(0, len(field_list), 2):       # 2 fields per row
    cols = st.columns(2)
    for col, (key, label, is_pw) in zip(cols, field_list[j:j+2]):
        creds[key] = col.text_input(label, type="password" if is_pw else "default")

st.subheader("3. What data do you want?")
# Always show all 3 segments. Default to one this broker actually supports.
default_seg = broker["data_types"][0] if broker.get("data_types") else "stocks"
data_type = st.radio("Type", ALL_SEGMENTS,
                     index=ALL_SEGMENTS.index(default_seg),
                     horizontal=True,
                     format_func=lambda x: TYPE_LABELS.get(x, x.capitalize()))

# Is this segment available on the chosen broker?
segment_ok = data_type in broker.get("data_types", [])
if not segment_ok:
    providers = SEGMENT_PROVIDERS.get(data_type, [])
    hint = f" For {TYPE_LABELS[data_type]}, please use: {', '.join(providers)}." if providers else ""
    st.warning(f"{broker_name}'s API cannot provide {TYPE_LABELS[data_type]} data.{hint}")

names_raw = st.text_area("Names (separate with commas)",
                         placeholder=PLACEHOLDERS.get(data_type, ""))

timeframe = st.selectbox("Timeframe", broker["timeframes"],
                         index=broker["timeframes"].index('4h')
                         if '4h' in broker["timeframes"] else 0)
d1, d2 = st.columns(2)
from_date = d1.date_input("From date", value=datetime(2016, 1, 1))
to_date   = d2.date_input("To date",   value=datetime(2025, 12, 31))

st.divider()
run = st.button("Download data", type="primary", use_container_width=True)

# ============================================================
#  PART D : RUN
# ============================================================
if run:
    # segment supported by this broker?
    if not segment_ok:
        providers = SEGMENT_PROVIDERS.get(data_type, [])
        hint = f" Please select: {', '.join(providers)}." if providers else ""
        st.error(f"This API is not able to give {TYPE_LABELS[data_type]} data "
                 f"({broker_name}).{hint}")
        st.stop()
    if not all(creds.values()):
        st.error("Please fill in all login details."); st.stop()
    names = [n.strip() for n in names_raw.replace("\n", ",").split(",") if n.strip()]
    if not names:
        st.error("Please enter at least one name."); st.stop()
    if from_date >= to_date:
        st.error("From date must be before To date."); st.stop()

    f_date = datetime.combine(from_date, datetime.min.time())
    t_date = datetime.combine(to_date, datetime.min.time())

    try:
        with st.spinner("Logging in..."):
            session = broker["login"](creds)
        st.success("Login successful!")
    except Exception as e:
        st.error(f"Login error: {e}"); st.stop()

    results, not_found, no_data = {}, [], []
    prog = st.progress(0.0, text="Fetching data...")
    for i, nm in enumerate(names, 1):
        prog.progress((i-1)/len(names), text=f"{nm} ...")
        try:
            tok = broker["get_token"](session, nm, data_type)
            if not tok:
                not_found.append(nm); continue
            df = broker["fetch"](session, tok, timeframe, f_date, t_date)
            if df is None or df.empty:
                no_data.append(nm); continue
            results[nm] = df
        except Exception as e:
            no_data.append(f"{nm} ({e})")
    prog.progress(1.0, text="Done!")

    if not_found:
        st.warning("Name/symbol not matched (check spelling): " + ", ".join(not_found))
    if no_data:
        st.warning("No data (check broker plan / date range / token): " + ", ".join(no_data))
    if not results:
        st.error("No data returned."); st.stop()

    st.success(f"{len(results)} file(s) ready!")
    for name, df in results.items():
        with st.expander(f"{name}_{timeframe}.csv -- {len(df)} rows"):
            st.dataframe(df.head(10), use_container_width=True)
            st.download_button(f"Download {name}_{timeframe}.csv",
                               df.to_csv().encode("utf-8"),
                               file_name=f"{name}_{timeframe}.csv",
                               mime="text/csv", key=f"dl_{name}")
    if len(results) > 1:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, df in results.items():
                zf.writestr(f"{name}_{timeframe}.csv", df.to_csv())
        st.download_button("Download all as ZIP", buf.getvalue(),
                           file_name=f"{broker_name}_{timeframe}.zip",
                           mime="application/zip", type="primary",
                           use_container_width=True)
