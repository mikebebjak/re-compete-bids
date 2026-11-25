# Re-Compete Bids

A lightweight Streamlit app for tracking expiring U.S. and Canadian government contracts 6-18 months before the re-compete RFP drops.

## Features
- **USAspending.gov (U.S. Federal):** Filter expiring prime contracts by NAICS industry code, keywords, contract value, and expiry window.
- **CanadaBuys (Canadian Federal):** Scans live fiscal-year federal contract history CSVs with hourly caching.
- **Pluggable Source Architecture:** Easily add new procurement portals via the SOURCES registry in app.py.
- **CSV Export:** One-click export of filtered re-compete targets.

## Run Locally
    python3 -m pip install -r requirements.txt
    python3 -m streamlit run app.py
