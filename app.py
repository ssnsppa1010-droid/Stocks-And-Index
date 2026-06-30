# ============================================================
#  Multi-Broker Stock & Index Data Downloader  (WEBSITE version)
#  - Broker-a dropdown la select pannalaam
#  - Angel One = full velai seyyum
#  - Mathi broker = "ippo support illa" nu nallaa kaattum
#  - Puthu broker serkka:  keezha BROKERS dict la oru entry add pannunga
#  Run panna:  streamlit run app.py
# ============================================================

import streamlit as st
import pandas as pd
import requests, pyotp, time, io, zipfile
from datetime import datetime, timedelta

st.set_page_config(page_title="Stock & Index Data Downloader",
                   page_icon="📈", layout="centered")
st.title("Stock & Index Data Downloader")
st.caption("Broker select pannunga -> login podunga -> peyar podunga -> CSV download.")

# ============================================================
#  PART A : ANGEL ONE adapter  (idhu full velai seyyum)
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

@st.cache_data(show_spinner="Angel instrument list load aaguthu...")
def angel_instruments():
    url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
    return pd.DataFrame(requests.get(url).json())

def angel_login(creds):
    """creds = dict. Login aagi session obj-a return pannum. Fail aana Exception."""
    from SmartApi import SmartConnect
    obj = SmartConnect(api_key=creds['api_key'])
    data = obj.generateSession(creds['client_id'], creds['mpin'],
                               pyotp.TOTP(creds['totp_secret']).now())
    if not data.get('status'):
        raise Exception("Login fail aaiduchu. Details check pannunga.")
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
#  Puthu broker serkka -> inga oru entry add pannunga.
#  "supported": True  -> login/get_token/fetch function venum
#  "supported": False -> "ippo support illa" nu kaattum (note sollalaam)
# ============================================================
BROKERS = {
    "Angel One": {
        "supported": True,
        "fields": [   # (key, label, password-aa?)
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

    # ---- keezha ellam innum serkkala (slot mattum) ----
    "Zerodha": {
        "supported": False,
        "note": "Zerodha OAuth login venum (login link click panni token vaanganum) "
                "+ historical data ku ~Rs.2000/month subscription. Tani setup venum."},
    "Upstox": {
        "supported": False,
        "note": "Upstox OAuth login venum. Account ready aana add pannalaam."},
    "Fyers": {
        "supported": False,
        "note": "Fyers OAuth login venum. Historical data free (1-2 varusham)."},
    "Dhan": {
        "supported": False,
        "note": "Dhan access-token login. Data ku ~Rs.500/month plan venum."},
}

# ============================================================
#  PART C : UI
# ============================================================
st.subheader("1. Broker select pannunga")
broker_name = st.selectbox("Broker", list(BROKERS.keys()))
broker = BROKERS[broker_name]

# ---- broker support illana, inga-eye nikkanum (neenga ketta "not allowed" message) ----
if not broker.get("supported"):
    st.warning(f"**{broker_name}** -- ippo support illa.\n\n{broker.get('note','')}")
    st.info("Ippothaiku **Angel One** select panni use pannunga. "
            "Vera broker venum-na, andha account ready aana sollunga - add panren.")
    st.stop()

# ---- support irukkra broker ku login fields kaattu ----
st.subheader("2. Unga login")
st.info("Indha details unga account-oda. Naanga save pannala - ovvoru thadava-um "
        "neenga thaan podanum.")

creds = {}
field_list = broker["fields"]
for j in range(0, len(field_list), 2):       # 2-2 column-a kaattu
    cols = st.columns(2)
    for col, (key, label, is_pw) in zip(cols, field_list[j:j+2]):
        creds[key] = col.text_input(label, type="password" if is_pw else "default")

st.subheader("3. Enna data venum?")
data_type = st.radio("Vagai", ["stocks", "index"], horizontal=True,
                     format_func=lambda x: "Stocks" if x=="stocks" else "Index")
placeholder = "SBIN, RELIANCE, TCS" if data_type=="stocks" else "NIFTY50, NIFTYBANK, NIFTY500"
names_raw = st.text_area("Peyar (comma vachi pirikkavum)", placeholder=placeholder)

timeframe = st.selectbox("Timeframe", broker["timeframes"],
                         index=broker["timeframes"].index('4h')
                         if '4h' in broker["timeframes"] else 0)
d1, d2 = st.columns(2)
from_date = d1.date_input("From date", value=datetime(2016, 9, 1))
to_date   = d2.date_input("To date",   value=datetime(2025, 12, 31))

st.divider()
run = st.button("Data eduthu kudu", type="primary", use_container_width=True)

# ============================================================
#  PART D : RUN
# ============================================================
if run:
    if not all(creds.values()):
        st.error("Login details ellam podunga."); st.stop()
    names = [n.strip() for n in names_raw.replace("\n", ",").split(",") if n.strip()]
    if not names:
        st.error("Konjam peyar podunga."); st.stop()
    if from_date >= to_date:
        st.error("From date, To date-ku munnadi irukkanum."); st.stop()

    f_date = datetime.combine(from_date, datetime.min.time())
    t_date = datetime.combine(to_date, datetime.min.time())

    # --- login ---
    try:
        with st.spinner("Login aaguthu..."):
            session = broker["login"](creds)
        st.success("Login Successful!")
    except Exception as e:
        st.error(f"Login error: {e}"); st.stop()

    # --- token + fetch ovvoru peyar-ku-um ---
    results, not_found, no_data = {}, [], []
    prog = st.progress(0.0, text="Data eduthuttu iruken...")
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
    prog.progress(1.0, text="Mudinjiduchu!")

    # --- message-a thelivaa pirichu kaattu (peyar thappa? data illa?) ---
    if not_found:
        st.warning("Peyar match aagala (spelling paarunga): " + ", ".join(not_found))
    if no_data:
        st.warning("Data varala (broker plan / date range paarunga): " + ", ".join(no_data))
    if not results:
        st.error("Onnum data varala."); st.stop()

    # --- download ---
    st.success(f"{len(results)} file ready!")
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
        st.download_button("Ella file-um onnaa (ZIP)", buf.getvalue(),
                           file_name=f"{broker_name}_{timeframe}.zip",
                           mime="application/zip", type="primary",
                           use_container_width=True)
