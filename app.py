# ============================================================
#  Multi-Broker Stock & Index Data Downloader  (WEBSITE version)
#  - Select a broker from the dropdown
#  - Angel One = fully working
#  - Other brokers = shows a clean "not supported yet" message
#  - To add a new broker: add an entry in the BROKERS dict below
#  Run:  streamlit run app.py
# ============================================================

import streamlit as st
import pandas as pd
import requests, pyotp, time, io, zipfile
from datetime import datetime, timedelta

st.set_page_config(page_title="Stock & Index Data Downloader",
                   page_icon="📈", layout="centered")
st.title("Stock & Index Data Downloader")
st.caption("Select broker -> enter login -> enter names -> download CSV.")

# ============================================================
#  PART A : ANGEL ONE adapter  (this one fully works)
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
    """Logs in and returns a session object. Raises Exception on failure."""
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
    else:
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
    # timeframe -> Angel interval
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
#  PART B : BROKERS registry
#  To add a new broker -> add an entry here.
#  "supported": True  -> needs login/get_token/fetch + data_types
#  "supported": False -> shows "not supported yet" (with a note)
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

    # ---- not added yet (slots only) ----
    "Fyers": {
        "supported": False,
        "note": "Fyers uses OAuth login. Free historical data (1-2 years). "
                "Needed for MCX commodities. Setup in progress."},
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

# ============================================================
#  PART C : UI
# ============================================================
st.subheader("1. Select your broker")
broker_name = st.selectbox("Broker", list(BROKERS.keys()))
broker = BROKERS[broker_name]

# ---- if broker not supported, stop here with a clean message ----
if not broker.get("supported"):
    st.warning(f"**{broker_name}** is not supported yet.\n\n{broker.get('note','')}")
    st.info("For now, please select **Angel One**. "
            "Want another broker? Tell me once the account is ready and it can be added.")
    st.stop()

# ---- supported broker: show login fields ----
st.subheader("2. Your login")
st.info("These details belong to your own account. We do not save anything - "
        "you enter them each time.")

creds = {}
field_list = broker["fields"]
for j in range(0, len(field_list), 2):       # show 2 per row
    cols = st.columns(2)
    for col, (key, label, is_pw) in zip(cols, field_list[j:j+2]):
        creds[key] = col.text_input(label, type="password" if is_pw else "default")

st.subheader("3. What data do you want?")
data_types = broker["data_types"]
data_type = st.radio("Type", data_types, horizontal=True,
                     format_func=lambda x: x.capitalize())
placeholder = "SBIN, RELIANCE, TCS" if data_type=="stocks" else "NIFTY50, NIFTYBANK, NIFTY500"
names_raw = st.text_area("Names (separate with commas)", placeholder=placeholder)

timeframe = st.selectbox("Timeframe", broker["timeframes"],
                         index=broker["timeframes"].index('4h')
                         if '4h' in broker["timeframes"] else 0)
d1, d2 = st.columns(2)
from_date = d1.date_input("From date", value=datetime(2016, 9, 1))
to_date   = d2.date_input("To date",   value=datetime(2025, 12, 31))

st.divider()
run = st.button("Download data", type="primary", use_container_width=True)

# ============================================================
#  PART D : RUN
# ============================================================
if run:
    if not all(creds.values()):
        st.error("Please fill in all login details."); st.stop()
    names = [n.strip() for n in names_raw.replace("\n", ",").split(",") if n.strip()]
    if not names:
        st.error("Please enter at least one name."); st.stop()
    if from_date >= to_date:
        st.error("From date must be before To date."); st.stop()

    f_date = datetime.combine(from_date, datetime.min.time())
    t_date = datetime.combine(to_date, datetime.min.time())

    # --- login ---
    try:
        with st.spinner("Logging in..."):
            session = broker["login"](creds)
        st.success("Login successful!")
    except Exception as e:
        st.error(f"Login error: {e}"); st.stop()

    # --- resolve token + fetch for each name ---
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

    # --- show clear messages (wrong name? no data?) ---
    if not_found:
        st.warning("Name not matched (check spelling): " + ", ".join(not_found))
    if no_data:
        st.warning("No data (check broker plan / date range): " + ", ".join(no_data))
    if not results:
        st.error("No data returned."); st.stop()

    # --- download ---
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
