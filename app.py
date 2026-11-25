import streamlit as st
import requests
import pandas as pd
from datetime import date, timedelta

st.set_page_config(page_title="Re-Compete Bids", page_icon="🎯", layout="wide")

# --- PLUGGABLE SOURCE FUNCTIONS ---

def fetch_usaspending(keywords, naics_codes, win_start, win_end, min_val):
    url = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
    payload = {
        "filters": {
            "award_type_codes": ["A", "B", "C", "D"],
            "time_period": [{"start_date": "2022-01-01", "end_date": str(win_end)}],
            **({"naics_codes": naics_codes} if naics_codes else {}),
            **({"keywords": keywords} if keywords else {}),
        },
        "fields": [
            "Award ID", "Recipient Name", "Award Amount", "End Date",
            "Awarding Agency", "Awarding Sub Agency", "Description", "generated_internal_id",
        ],
        "limit": 100, "page": 1, "sort": "Award Amount", "order": "desc",
    }
    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    rows = []
    for r in resp.json().get("results", []):
        end_str = r.get("End Date")
        amt = r.get("Award Amount") or 0
        if not end_str or amt < min_val:
            continue
        end_dt = date.fromisoformat(end_str[:10])
        if win_start <= end_dt <= win_end:
            rows.append({
                "Source": "USAspending.gov (US)",
                "Incumbent": r.get("Recipient Name"),
                "Agency": f"{r.get('Awarding Agency')} ({r.get('Awarding Sub Agency')})",
                "Value ($)": amt,
                "Expires": end_str[:10],
                "Days Left": (end_dt - date.today()).days,
                "Summary": (r.get("Description") or "").strip()[:160],
                "Link": f"https://www.usaspending.gov/award/{r.get('generated_internal_id')}",
            })
    return rows


@st.cache_data(ttl=3600, show_spinner=False)
def _load_canadabuys_csv():
    pkg_url = "https://open.canada.ca/data/api/3/action/package_show"
    resp = requests.get(pkg_url, params={"id": "4fe645a1-ffcd-40c1-9385-2c771be956a4"}, timeout=30)
    resp.raise_for_status()
    resources = resp.json()["result"]["resources"]

    # Grab the latest 2 fiscal-year CSVs (e.g., 2026-2027 & 2025-2026)
    csv_urls = [
        r["url"] for r in resources
        if r.get("format", "").upper() == "CSV"
        and any(yr in r.get("name", "") for yr in ("2026-2027", "2025-2026"))
    ]
    frames = [pd.read_csv(u, low_memory=False) for u in csv_urls[:2]]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _find_col(cols, candidates):
    for cand in candidates:
        for c in cols:
            if cand.lower() in c.lower():
                return c
    return None


def fetch_open_canada(keywords, naics_codes, win_start, win_end, min_val):
    df = _load_canadabuys_csv()
    if df.empty:
        return []

    cols = list(df.columns)
    c_end = _find_col(cols, ["expiryDate", "endDate", "contractEnd", "delivery_date"])
    c_val = _find_col(cols, ["contractAmount", "totalContractValue", "contract_value", "value"])
    c_vnd = _find_col(cols, ["supplierLegalName", "vendorName", "supplier", "vendor"])
    c_org = _find_col(cols, ["contractingEntityName-nomEntitContractante-eng", "endUserEntitiesName-nomEntitesUtilisatrices-eng", "organization", "owner_org"])
    c_dsc = _find_col(cols, ["title-titre-eng", "description-eng", "commodityDescription-eng", "description"])
    c_ref = _find_col(cols, ["contractNumber", "referenceNumber", "amendmentNumber"])

    if not c_end or not c_dsc:
        raise RuntimeError(f"Unexpected CSV columns: {cols[:10]}")

    # Filter by keywords first (fast vectorized string match)
    pattern = "|".join([k for k in keywords if k])
    mask = df[c_dsc].astype(str).str.contains(pattern, case=False, na=False)
    sub = df[mask]

    rows = []
    for _, r in sub.iterrows():
        end_str = str(r.get(c_end, ""))[:10]
        try:
            end_dt = date.fromisoformat(end_str)
            amt = float(str(r.get(c_val, 0)).replace(",", "").replace("$", "") or 0)
        except ValueError:
            continue

        if amt >= min_val and win_start <= end_dt <= win_end:
            ref = str(r.get(c_ref, "")) if c_ref else ""
            rows.append({
                "Source": "CanadaBuys (CA)",
                "Incumbent": str(r.get(c_vnd, "Unknown")) if c_vnd else "Unknown",
                "Agency": str(r.get(c_org, "Gov of Canada")) if c_org else "Gov of Canada",
                "Value ($)": amt,
                "Expires": end_str,
                "Days Left": (end_dt - date.today()).days,
                "Summary": str(r.get(c_dsc, "")).strip()[:160],
                "Link": f"https://canadabuys.canada.ca/en/tender-opportunities?search_api_fulltext={ref}",
            })
    return rows


# Registry of available sources — adding a new portal is just 1 function + 1 line here
SOURCES = {
    "USAspending.gov (U.S. Federal)": fetch_usaspending,
    "Open Canada (Canadian Federal)": fetch_open_canada,
}

# --- SIDEBAR CONTROLS ---
st.sidebar.title("🎯 Search Settings")
selected_sources = st.sidebar.multiselect("Active Marketplaces", list(SOURCES.keys()), default=list(SOURCES.keys()))
kw_input = st.sidebar.text_input("Keywords (comma-separated)", "radar, drone, UAS, surveillance")
NAICS_PRESETS = {
    "541512 — Computer Systems Design / IT": "541512",
    "334511 — Radar, Detection & Navigation": "334511",
    "541330 — Engineering Services": "541330",
    "561621 — Security Systems Services": "561621",
    "236220 — Commercial Construction": "236220",
    "All Industries (No NAICS Filter)": "",
    "Custom NAICS Code(s)...": "CUSTOM",
}
naics_choice = st.sidebar.selectbox("U.S. NAICS Industry", list(NAICS_PRESETS.keys()), index=1)
if NAICS_PRESETS[naics_choice] == "CUSTOM":
    naics_input = st.sidebar.text_input("Enter Custom NAICS Code(s) (comma-separated)", "")
else:
    naics_input = NAICS_PRESETS[naics_choice]
min_months, max_months = st.sidebar.slider("Expiry Window (Months from Today)", 1, 36, (6, 18))
min_val = st.sidebar.number_input("Minimum Contract Value ($)", value=100000, step=50000)

run_btn = st.sidebar.button("Scan Marketplaces", type="primary", use_container_width=True)

# --- MAIN DASHBOARD ---
st.title("🎯 Re-Compete Bids")
st.caption("Track expiring U.S. & Canadian government contracts 6–18 months before the RFP drops.")

if run_btn or "df" not in st.session_state:
    keywords = [k.strip() for k in kw_input.split(",") if k.strip()]
    naics = [n.strip() for n in naics_input.split(",") if n.strip()]
    win_start = date.today() + timedelta(days=min_months * 30)
    win_end = date.today() + timedelta(days=max_months * 30)

    all_rows = []
    with st.spinner("Scanning selected procurement portals..."):
        for src_name in selected_sources:
            try:
                all_rows.extend(SOURCES[src_name](keywords, naics, win_start, win_end, min_val))
            except Exception as e:
                st.error(f"Error fetching {src_name}: {e}")
    st.session_state["df"] = pd.DataFrame(all_rows)

df = st.session_state["df"]

if df.empty:
    st.warning("No expiring contracts matched your current filters. Try widening the expiry window or lowering the minimum value.")
else:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Expiring Contracts", len(df))
    c2.metric("Total Pipeline Value", f"${df['Value ($)'].sum():,.0f}")
    c3.metric("Active Portals", df["Source"].nunique())
    c4.metric("Top Incumbent", df["Incumbent"].value_counts().idxmax())

    st.dataframe(
        df.sort_values("Days Left"),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Value ($)": st.column_config.NumberColumn(format="$%d"),
            "Link": st.column_config.LinkColumn("Award Link", display_text="View Award"),
        },
    )
    st.download_button("Export CSV for Sales Team", df.to_csv(index=False), "expiring_contracts.csv", "text/csv")
