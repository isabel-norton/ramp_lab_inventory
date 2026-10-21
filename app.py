"""Lab Inventory — a cabinet-first, phone-friendly Streamlit application."""
from __future__ import annotations

import csv
import hmac
import html
import io
import time
import uuid
from pathlib import Path

import streamlit as st

from config import load_settings
from inventory import InventoryError, Store, quantity, units_for
from notifications import dispatch_pending
from qr_labels import cabinet_url, printable_labels, qr_png, validate_url

st.set_page_config(page_title="Lab Inventory", page_icon="🧪", layout="wide", initial_sidebar_state="auto")

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@400;500;600;700;800&display=swap');

:root {
    --forest: #214f42;
    --muted: #46574b;
    --text: #24352a;
    --secondary: #4f5e52;
    --border: #d5dfd1;
}

html, body, [class*="css"], .stApp {
    font-family: 'DM Sans', sans-serif;
    color: var(--text);
}

.stApp {
    background: #f7f8f4;
    color: var(--text);
}

/* Headings */
h1, h2, h3 {
    font-family: 'Manrope', sans-serif !important;
    letter-spacing: -.045em !important;
    color: #243b2e !important;
}

h1 {
    font-weight: 800 !important;
    font-size: 2.65rem !important;
    line-height: 1.13 !important;
}

h2 { font-size: 1.6rem !important; }
h3 { font-size: 1.15rem !important; }

.block-container {
    max-width: 1290px;
    padding-top: 2.4rem;
    padding-bottom: 3rem;
}

/* Sidebar */
[data-testid="stSidebar"] {
    background: #edf1e9;
    border-right: 1px solid #dce3d7;
    color: #24352a;
}

[data-testid="stSidebar"] .block-container {
    padding-top: 2rem;
}

[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] li,
[data-testid="stSidebar"] small {
    color: #34483a;
}

/* Metrics */
[data-testid="stMetric"] {
    background: #fff;
    border: 1px solid #e1e7dc;
    border-radius: 14px;
    padding: 17px 20px;
    color: #24352a;
}

[data-testid="stMetricLabel"],
[data-testid="stMetricLabel"] p {
    color: #46574b !important;
    font-size: .78rem;
}

[data-testid="stMetricValue"],
[data-testid="stMetricValue"] div {
    font-family: 'Manrope', sans-serif;
    color: #214f42 !important;
    font-size: 1.9rem;
}

[data-testid="stMetricDelta"] {
    color: #46574b !important;
}

/* Containers */
[data-testid="stVerticalBlockBorderWrapper"] > div {
    border-color: #d5dfd1 !important;
    border-radius: 15px !important;
}

/* General text and captions */
p, li, label, .stMarkdown, .stCaption, small {
    color: #34483a;
}

[data-testid="stCaptionContainer"],
[data-testid="stCaptionContainer"] p {
    color: #4f5e52 !important;
}

.eyebrow {
    font-size: .72rem;
    font-weight: 700;
    letter-spacing: .17em;
    color: #465b46;
    margin: 0 0 12px;
}

.brand {
    font-family: 'Manrope', sans-serif;
    font-size: 1.25rem;
    font-weight: 800;
    letter-spacing: -.04em;
    margin: 0 0 4px;
    color: #243b2e;
}

.brand-icon {
    display: inline-block;
    background: #214f42;
    color: #fff !important;
    border-radius: 10px;
    padding: 5px 11px;
    margin-right: 8px;
    font-size: 22px;
}

/* Hero section */
.hero {
    background: #e8eee1;
    border: 1px solid #dce5d3;
    padding: 27px 30px;
    border-radius: 18px;
    margin-bottom: 25px;
}

.hero h1 {
    margin: 0 0 14px;
    max-width: 650px;
    color: #234d3e !important;
}

.hero p {
    color: #46574b !important;
    font-size: .98rem;
    margin: 0;
    max-width: 650px;
    line-height: 1.6;
}

.hero .eyebrow {
    font-size: .68rem;
    margin-bottom: 12px;
    color: #465b46;
}

.steps {
    font-size: .73rem;
    letter-spacing: .04em;
    color: #46574b;
    margin-top: 25px;
    display: flex;
    gap: 22px;
    flex-wrap: wrap;
}

.steps b {
    color: #214f42;
    margin-right: 6px;
}

/* Chemical stock cards */
.stock-row {
    background: #fff;
    border: 1px solid #d5dfd1;
    border-radius: 12px;
    padding: 18px 19px;
    margin-bottom: 10px;
}

.stock-top {
    display: flex;
    align-items: start;
    justify-content: space-between;
    gap: 12px;
}

.stock-title {
    font-weight: 700;
    font-size: 1rem;
    color: #243b2e;
}

.stock-detail {
    font-size: .78rem;
    color: #4f5e52;
    margin-top: 3px;
}

.stock-amount {
    font-family: 'Manrope', sans-serif;
    font-size: 1.4rem;
    font-weight: 800;
    color: #214f42;
    margin-top: 12px;
    letter-spacing: -.03em;
}

.stock-amount small {
    font-family: 'DM Sans', sans-serif;
    font-size: .8rem;
    font-weight: 500;
    color: #4f5e52;
}

.stock-track {
    height: 5px;
    background: #edf1e9;
    border-radius: 6px;
    margin: 12px 0 8px;
    overflow: hidden;
}

.stock-track div {
    height: 100%;
    border-radius: 6px;
    background: #6a8e69;
}

.stock-foot {
    font-size: .7rem;
    color: #4f5e52;
}

/* Status badges */
.badge {
    display: inline-block;
    border-radius: 30px;
    background: #eaf2e5;
    color: #35572f !important;
    font-size: .65rem;
    font-weight: 700;
    padding: 4px 9px;
    white-space: nowrap;
}

.badge.low {
    background: #fff0da;
    color: #824700 !important;
}

.badge.empty {
    background: #fbe8e1;
    color: #8c2e20 !important;
}

/* Cabinet and footer */
.cabinet-icon {
    font-size: 1.3rem;
    color: #36543a;
    background: #e9efdf;
    padding: 9px 13px;
    display: inline-block;
    border-radius: 10px;
    margin-bottom: 10px;
}

.footer {
    font-size: .7rem;
    color: #4f5e52;
    margin-top: 30px;
    padding-top: 15px;
    border-top: 1px solid #d5dfd1;
}

/* Buttons */
.stButton button,
.stFormSubmitButton button,
.stDownloadButton button {
    border-radius: 9px;
    min-height: 44px;
    color: #fff;
    background: #214f42;
    border: 1px solid #214f42;
    font-weight: 600;
}

.stButton button p,
.stFormSubmitButton button p,
.stDownloadButton button p {
    color: inherit !important;
}

.stButton button:hover,
.stFormSubmitButton button:hover,
.stDownloadButton button:hover {
    background: #173c31;
    border-color: #173c31;
    color: #fff;
}

/* Forms and inputs */
[data-testid="stForm"] {
    background: #fff;
    border-radius: 15px;
    border: 1px solid #d5dfd1;
    padding: 21px;
}

/* Input labels */
[data-testid="stWidgetLabel"] p,
[data-testid="stWidgetLabel"] label,
.stTextInput label,
.stNumberInput label,
.stSelectbox label,
.stMultiSelect label,
.stTextArea label,
.stDateInput label,
.stTimeInput label,
.stRadio label,
.stCheckbox label,
.stSlider label {
    color: #34483a !important;
}

/* Typed text */
.stTextInput input,
.stNumberInput input,
.stTextArea textarea,
.stDateInput input,
.stTimeInput input {
    color: #24352a !important;
    background: #fff !important;
    -webkit-text-fill-color: #24352a !important;
    border-color: #b8c7b5 !important;
}

/* Select boxes and dropdowns */
[data-testid="stSelectbox"] [data-baseweb="select"],
[data-testid="stMultiSelect"] [data-baseweb="select"] {
    background: #fff !important;
    border-color: #b8c7b5 !important;
}

[data-testid="stSelectbox"] [data-baseweb="select"] *,
[data-testid="stMultiSelect"] [data-baseweb="select"] * {
    color: #24352a !important;
}

[data-baseweb="popover"],
[data-baseweb="menu"],
[data-baseweb="select"] ul,
[role="listbox"],
[role="option"] {
    background-color: #fff !important;
    color: #24352a !important;
}

[role="option"] *,
[role="listbox"] * {
    color: #24352a !important;
}

/* Radio buttons and checkboxes */
[data-testid="stRadio"] label,
[data-testid="stCheckbox"] label {
    color: #34483a !important;
    font-size: .9rem;
}

[data-testid="stRadio"] p,
[data-testid="stCheckbox"] p {
    color: #34483a !important;
}

/* Placeholders */
input::placeholder,
textarea::placeholder {
    color: #667469 !important;
    -webkit-text-fill-color: #667469 !important;
    opacity: 1 !important;
}

/* Links */
a {
    color: #215b48;
}

a:hover {
    color: #143c2f;
}

/* Mobile layout */
@media(max-width:640px) {
    .block-container {
        padding: 1.4rem 1rem 2rem;
    }

    h1 {
        font-size: 2rem !important;
    }

    .hero {
        padding: 24px 20px;
    }

    .steps {
        gap: 12px;
        font-size: .65rem;
    }

    [data-testid="stMetric"] {
        padding: 12px;
    }

    [data-testid="stMetricValue"] {
        font-size: 1.5rem;
    }

    [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) {
        flex-wrap: nowrap !important;
        gap: .5rem !important;
    }

    [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > [data-testid="stColumn"] {
        min-width: 0 !important;
        flex: 1 1 0 !important;
        width: 0 !important;
    }
}
</style>
"""

st.markdown(CSS, unsafe_allow_html=True)


def esc(value):
    return html.escape(str(value))


def csv_bytes(rows):
    if not rows:
        return b""
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    # Prevent spreadsheet formula interpretation in exported user-entered text.
    for row in rows:
        writer.writerow({key: ("'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")) else value)
                         for key, value in row.items()})
    return stream.getvalue().encode("utf-8-sig")


def flash(message):
    st.session_state["flash"] = message
    st.rerun()


def password_gate(expected, prefix, title, text):
    if st.session_state.get(prefix + "_authenticated"):
        return True
    st.subheader(title)
    st.caption(text)
    with st.form(prefix + "_login"):
        password = st.text_input("Lab access code" if prefix == "member" else "Administrator password", type="password")
        submitted = st.form_submit_button("Continue", type="primary", width="stretch")
    if submitted:
        deadline = st.session_state.get(prefix + "_retry_after", 0)
        if time.monotonic() < deadline:
            st.error("Please wait a few seconds before trying again.")
        elif hmac.compare_digest(password.encode(), expected.encode()):
            st.session_state[prefix + "_authenticated"] = True
            st.rerun()
        else:
            st.session_state[prefix + "_retry_after"] = time.monotonic() + 3
            st.error("That code did not match. Please try again.")
    return False


def stock_card(item):
    low = item["quantity"] <= item["threshold"]
    empty = item["quantity"] == 0
    status = "Out of stock" if empty else ("Low stock" if low else "In stock")
    badge = "empty" if empty else ("low" if low else "")
    pct = min(100, max(0, item["quantity"] / item["target"] * 100))
    color = "#c49b4e" if low else "#71936e"
    st.markdown(f'''<div class="stock-row"><div class="stock-top"><div>
      <div class="stock-title">{esc(item['name'])}</div><div class="stock-detail">{esc(item['detail'] or 'Lab stock')}</div>
      </div><span class="badge {badge}">{status}</span></div>
      <div class="stock-amount">{quantity(item['quantity'])} <small>{esc(item['unit'])} remaining</small></div>
      <div class="stock-track"><div style="width:{pct}%;background:{color}"></div></div>
      <div class="stock-foot">Low-stock alert at {quantity(item['threshold'])} {esc(item['unit'])} · Reference stock {quantity(item['target'])} {esc(item['unit'])}</div></div>''', unsafe_allow_html=True)


def mail_status(settings, demo):
    if demo:
        return "Demo · emails are disabled"
    return "Email delivery configured" if settings.mail_ready else "Email delivery needs setup"


def landing(store, cabinets):
    def open_cabinet(cabinet_id):
        st.query_params["cabinet"] = cabinet_id
        st.session_state["cabinet_select"] = cabinet_id

    st.markdown('''<div class="hero"><div class="eyebrow">LESS ADMIN. MORE DISCOVERY.</div>
      <h1>Everything in its place.</h1><p>A shared view of your lab's stock. Find a cabinet, log what you use,
      and keep the next experiment moving.</p><div class="steps"><span><b>01</b> CHOOSE A CABINET</span>
      <span><b>02</b> LOG A CHANGE</span><span><b>03</b> STAY STOCKED</span></div></div>''', unsafe_allow_html=True)
    cols = st.columns(3)
    cols[0].metric("Cabinets", len(cabinets))
    cols[1].metric("Stock items", sum(c["item_count"] for c in cabinets))
    cols[2].metric("Need a refill", sum(c["low_count"] for c in cabinets))
    st.write("")
    st.subheader("Which cabinet are you using?")
    st.caption("Choose below, or scan a cabinet's QR label to come straight to its inventory.")
    if not cabinets:
        st.info("Your lab is ready for its first cabinet. Open Manage lab to add cabinets and solutions.")
    for offset in range(0, len(cabinets), 3):
        for col, cabinet in zip(st.columns(3), cabinets[offset:offset+3]):
            with col, st.container(border=True):
                st.markdown('<div class="cabinet-icon">▤</div>', unsafe_allow_html=True)
                st.subheader(cabinet["name"])
                st.caption(cabinet["location"])
                st.write(cabinet["notes"] or "Shared lab inventory")
                st.caption(f"{cabinet['item_count']} stock items · {cabinet['low_count']} low")
                st.button("Open inventory →", key="open_"+cabinet["id"], width="stretch",
                          on_click=open_cabinet, args=(cabinet["id"],))


def log_change(store, items, settings, demo):
    if not items:
        return
    st.session_state.setdefault("request_id", uuid.uuid4().hex)
    item_map = {item["id"]: item for item in items}
    st.markdown('<p class="eyebrow">A QUICK UPDATE</p>', unsafe_allow_html=True)
    st.subheader("What changed?")
    # Outside the form so stock units and availability update on selection.
    item_id = st.selectbox("Solution / item", list(item_map), format_func=lambda key: item_map[key]["name"] + (" · "+item_map[key]["detail"] if item_map[key]["detail"] else ""), key="log_item")
    item = item_map[item_id]
    st.caption(f"Available now: {quantity(item['quantity'])} {item['unit']}")
    with st.form("stock_change", clear_on_submit=False):
        action = st.radio("I…", ["Used", "Added"], horizontal=True, key="movement_kind")
        a, b = st.columns([1.5, 1])
        amount = a.number_input("Amount", min_value=0.0, value=50.0 if item["unit"] == "mL" else 1.0,
                                step=1.0 if item["unit"] == "each" else 0.001, format="%.3f", key="amount_"+str(item_id))
        unit = b.selectbox("Unit", units_for(item["unit"]), key="unit_"+str(item_id))
        actor = st.text_input("Your name", placeholder="e.g. Alex Chen", max_chars=100, key="actor")
        note = st.text_input("Note (optional)", placeholder="Experiment, batch, or refill details", max_chars=500)
        st.caption("This updates the shared inventory immediately.")
        submit = st.form_submit_button("Save change", type="primary", width="stretch")
    if submit:
        try:
            movement = store.record(item_id, "use" if action == "Used" else "add", amount, unit, actor, note,
                                    request_id=st.session_state["request_id"])
        except InventoryError as exc:
            st.error(str(exc))
        else:
            st.session_state["request_id"] = uuid.uuid4().hex
            result = dispatch_pending(store, settings, limit=5) if not demo else {"sent": 0, "failed": 0, "disabled": True}
            current = store.item(item_id)
            receipt = (f"{action} {quantity(movement['amount'])} {item['unit']} of {item['name']}. "
                       f"{quantity(movement['after_qty'])} {item['unit']} remaining. Saved for {actor.strip()}.")
            if current["quantity"] <= current["threshold"]:
                receipt += " This item is low on stock."
                if demo:
                    receipt += " Demo mode: no email was sent."
                elif result["sent"]:
                    receipt += f" {result['sent']} queued email alert(s) sent."
                elif any(r["active"] and r["cabinet_id"] in (None, item["cabinet_id"]) for r in store.recipients()):
                    receipt += " Alerts are recorded in the email queue; delivery details are in Manage lab."
                else:
                    receipt += " No email recipients are configured for this cabinet yet."
            st.session_state["receipt"] = receipt
            st.rerun()


def inventory_page(store, cabinets, settings, demo):
    ids = [c["id"] for c in cabinets]
    cabinet_map = {c["id"]: c for c in cabinets}
    query_id = st.query_params.get("cabinet")
    if "cabinet_select" not in st.session_state:
        st.session_state["cabinet_select"] = query_id if query_id in ids else None
    if st.session_state.get("cabinet_select") not in [None, *ids]:
        st.session_state["cabinet_select"] = None
    if query_id and query_id not in ids:
        st.warning("This cabinet link was not found. Choose a cabinet below.")
    def change_cabinet():
        selected = st.session_state["cabinet_select"]
        if selected:
            st.query_params["cabinet"] = selected
        elif "cabinet" in st.query_params:
            del st.query_params["cabinet"]
        st.session_state.pop("receipt", None)
        st.session_state["request_id"] = uuid.uuid4().hex
    cabinet_id = st.selectbox("Your cabinet", ids, index=None, placeholder="Choose a cabinet…", key="cabinet_select",
                              format_func=lambda key: cabinet_map[key]["name"]+" · "+cabinet_map[key]["location"], on_change=change_cabinet)
    if not cabinet_id:
        landing(store, cabinets)
        return
    cabinet = cabinet_map[cabinet_id]
    st.markdown('<p class="eyebrow">YOUR SHARED INVENTORY</p>', unsafe_allow_html=True)
    st.title(cabinet["name"])
    st.caption(cabinet["location"] + (" · "+cabinet["notes"] if cabinet["notes"] else ""))
    if st.session_state.get("receipt"):
        st.success(st.session_state.pop("receipt"))
    items = store.items(cabinet_id)
    metrics = st.columns(3)
    metrics[0].metric("Stock items", len(items))
    metrics[1].metric("In stock", sum(i["quantity"] > i["threshold"] for i in items))
    metrics[2].metric("Need a refill", sum(i["quantity"] <= i["threshold"] for i in items))
    if items:
        st.markdown("[Log a change ↓](#what-changed)")
    st.write("")
    left, right = st.columns([1.45, 1], gap="large")
    with left:
        st.subheader("On the shelf")
        search = st.text_input("Find a solution", placeholder="Search name or concentration…", key="search", label_visibility="collapsed")
        low_only = st.toggle("Show low stock only", value=False)
        visible = [i for i in items if search.casefold() in (i["name"]+" "+i["detail"]).casefold() and (not low_only or i["quantity"] <= i["threshold"])]
        for item in visible:
            stock_card(item)
        if not visible:
            st.info("No matching items." if items else "This cabinet has no stock items yet. Add a solution in Manage lab.")
        if st.button("↻ Refresh inventory", width="stretch"):
            st.rerun()
        st.caption("Stock is checked again when you save, including changes from other phones.")
    with right:
        log_change(store, items, settings, demo)


def history_page(store, cabinets):
    st.markdown('<p class="eyebrow">THE SHARED LAB NOTEBOOK</p>', unsafe_allow_html=True)
    st.title("Every change, accounted for.")
    st.caption("Who used what, what came in, and what remains. Times are recorded in UTC.")
    options = {None: "All cabinets", **{c["id"]: c["name"] for c in cabinets}}
    cabinet_id = st.selectbox("Filter by cabinet", list(options), format_func=options.get)
    rows = store.history(cabinet_id, limit=500)
    records = [{"Time (UTC)": r["created_at"], "Cabinet": r["cabinet_name"], "Item": r["item_name"],
                "Description": r["detail"], "Action": "Used" if r["kind"] == "use" else "Added",
                "Amount": quantity(r["amount"]), "Unit": r["unit"], "Remaining": quantity(r["after_qty"]),
                "Name": r["actor"], "Note": r["note"]} for r in rows]
    if records:
        st.dataframe(records, hide_index=True, width="stretch")
        st.download_button("Download activity CSV", csv_bytes(records), "lab-activity.csv", "text/csv")
        st.caption("Showing the latest 500 changes. The full audit history is retained in the database backup.")
    else:
        st.info("No changes recorded yet. Your first stock update will appear here.")


def qr_page(cabinets, settings):
    st.markdown('<p class="eyebrow">FROM CABINET TO PHONE</p>', unsafe_allow_html=True)
    st.title("One scan. You're in.")
    st.caption("Print a label for the lab entrance or give each cabinet its own direct link.")
    base = st.text_input("App address that phones can reach", value=settings.base_url, placeholder="https://inventory.your-lab.org", key="qr_base")
    st.caption("For a local server, use its Wi-Fi IP, such as http://192.168.1.25:8501. Phones must be on the same network.")
    if not base:
        st.info("Enter your hosted app URL or the server's Wi-Fi address to generate QR labels.")
        return
    try:
        base = validate_url(base)
        choices = {None: "Lab entrance · choose a cabinet", **{c["id"]: c["name"] for c in cabinets}}
        selected = st.selectbox("Label for", list(choices), format_func=choices.get)
        url = cabinet_url(base, selected)
        left, right = st.columns([1, 1.6], gap="large")
        with left, st.container(border=True):
            st.subheader(choices[selected])
            image = qr_png(url)
            st.image(image, width=260)
            st.caption("Scan with your phone camera")
        with right:
            st.subheader("Ready for the cabinet door")
            st.write("Scanning opens the app in your phone's browser. Cabinet labels open that cabinet's inventory automatically.")
            st.link_button("Open this inventory link", url)
            st.code(url, language=None)
            st.download_button("Download QR image", image, f"lab-qr-{selected or 'entrance'}.png", "image/png", width="stretch")
            st.download_button("Download all printable labels", printable_labels(base, cabinets), "lab-qr-labels.html", "text/html", width="stretch")
            st.caption("Open the downloaded labels file in a browser and choose Print. For consistent email links, also set LAB_PUBLIC_URL in the server settings.")
    except ValueError as exc:
        st.error(str(exc))


def manage_page(store, cabinets, settings, demo):
    st.markdown('<p class="eyebrow">A PLACE FOR EVERYTHING</p>', unsafe_allow_html=True)
    st.title("Manage your lab")
    if not demo and not password_gate(settings.admin_password, "admin", "Administrator access", "Manage cabinets, solutions, recipients, and delivery settings."):
        return
    if demo:
        st.caption("Demo administration is open for exploring. Real mode requires an administrator password.")
    elif st.button("Lock administration"):
        st.session_state["admin_authenticated"] = False
        st.rerun()
    tabs = st.tabs(["Cabinets & items", "Email alerts", "Data & setup"])
    choices = {c["id"]: c["name"] for c in cabinets}
    with tabs[0]:
        with st.expander("Add a cabinet", expanded=not cabinets):
            with st.form("new_cabinet", clear_on_submit=True):
                name = st.text_input("Cabinet name", placeholder="e.g. Cabinet C", max_chars=80)
                location = st.text_input("Location", placeholder="Room and shelf location", max_chars=150)
                notes = st.text_input("Cabinet description (optional)", max_chars=500)
                if st.form_submit_button("Create cabinet", type="primary"):
                    try:
                        store.add_cabinet(name, location, notes)
                        flash("Cabinet created. You can now add its stock items.")
                    except InventoryError as exc:
                        st.error(str(exc))
        if cabinets:
            st.subheader("Add a stock item")
            st.caption("Use a separate item for each concentration, formulation, or batch you need to track.")
            with st.form("new_item", clear_on_submit=True):
                cabinet_id = st.selectbox("Cabinet", list(choices), format_func=choices.get, key="new_item_cabinet")
                name = st.text_input("Solution / item name", placeholder="e.g. PBS buffer", max_chars=100)
                detail = st.text_input("Concentration / description", placeholder="e.g. 1× · pH 7.4", max_chars=200)
                unit = st.selectbox("Stock unit", ["mL", "g", "each"])
                st.caption("Enter the next three values in the stock unit selected above.")
                c1, c2, c3 = st.columns(3)
                opening = c1.number_input("Opening quantity", min_value=0.0, value=500.0, step=1.0, format="%.3f")
                threshold = c2.number_input("Low-stock threshold", min_value=0.0, value=100.0, step=1.0, format="%.3f")
                target = c3.number_input("Reference stock level", min_value=0.001, value=1000.0, step=1.0, format="%.3f")
                actor = st.text_input("Recorded by", max_chars=100, placeholder="Your name")
                if st.form_submit_button("Add stock item", type="primary"):
                    try:
                        store.add_item(cabinet_id, name, detail, unit, opening, threshold, target, actor)
                        flash("Stock item created. Opening stock has been recorded in the activity log.")
                    except InventoryError as exc:
                        st.error(str(exc))
            with st.expander("Change an item's low-stock threshold"):
                all_items = store.items()
                if all_items:
                    by_id = {i["id"]: i for i in all_items}
                    selected = st.selectbox("Item to configure", list(by_id), format_func=lambda key: by_id[key]["cabinet_name"]+" · "+by_id[key]["name"]+" · "+by_id[key]["detail"])
                    item = by_id[selected]
                    with st.form("threshold_form"):
                        low = st.number_input(f"Low-stock threshold ({item['unit']})", min_value=0.0, value=item["threshold"]/1000, format="%.3f", key="low_"+str(selected))
                        full = st.number_input(f"Reference stock level ({item['unit']})", min_value=0.001, value=item["target"]/1000, format="%.3f", key="full_"+str(selected))
                        if st.form_submit_button("Save threshold"):
                            try:
                                store.update_threshold(selected, low, full)
                                flash("Threshold updated. Current stock has been checked against the new threshold.")
                            except InventoryError as exc:
                                st.error(str(exc))
    with tabs[1]:
        st.subheader("Let the right people know")
        st.write("An alert is queued at or below the low-stock threshold. Refill above the threshold to start a new alert cycle.")
        if demo:
            st.info("Email is disabled in demo mode. You can explore recipients and the queue without sending messages.")
        elif settings.mail_ready:
            st.success("SMTP is configured. Stock changes attempt delivery immediately; run the email worker for unattended retries.")
        else:
            st.warning("SMTP needs setup. Stock changes are saved and alerts stay queued until delivery is configured.")
        with st.form("new_recipient", clear_on_submit=True):
            name = st.text_input("Recipient name", max_chars=100)
            email = st.text_input("Email address", placeholder="colleague@your-lab.org", max_chars=254)
            scopes = {None: "All cabinets", **choices}
            scope = st.selectbox("Receive alerts for", list(scopes), format_func=scopes.get)
            if st.form_submit_button("Save recipient", type="primary"):
                try:
                    store.save_recipient(name, email, scope)
                    flash("Recipient saved. Any currently low items in their cabinets are also included in the alert queue.")
                except InventoryError as exc:
                    st.error(str(exc))
        active = [r for r in store.recipients() if r["active"]]
        if active:
            st.dataframe([{"Name": r["name"], "Email": r["email"], "Cabinets": r["cabinet_name"] or "All cabinets"} for r in active], hide_index=True, width="stretch")
            with st.expander("Remove a recipient"):
                ids = {r["id"]: r["email"] for r in active}
                selected = st.selectbox("Recipient to remove", list(ids), format_func=ids.get)
                if st.button("Stop alerts for this recipient"):
                    store.disable_recipient(selected)
                    flash("Recipient disabled. Unsent alerts for them have been cancelled.")
        st.subheader("Email delivery log")
        if st.button("Send pending alerts", disabled=demo or not settings.mail_ready):
            result = dispatch_pending(store, settings, limit=20)
            flash(f"Delivery attempt complete: {result['sent']} sent, {result['failed']} failed. Failed alerts remain queued for retry.")
        alerts = store.alerts()
        if alerts:
            st.dataframe([{"Item": a["item_name"], "Cabinet": a["cabinet_name"], "Recipient": a["email"],
                           "Status": a["status"], "Attempts": a["attempts"], "Sent (UTC)": a["sent_at"] or "—",
                           "Next attempt (UTC)": a["next_attempt"] if a["status"] == "pending" else "—",
                           "Last error": a["last_error"] or ""} for a in alerts], hide_index=True, width="stretch")
        else:
            st.caption("No outgoing alerts yet. Add recipients, then log a change that reaches a threshold.")
    with tabs[2]:
        st.subheader("Your lab's data")
        st.caption("Download a consistent database backup, including all stock changes, recipients, and alert history.")
        if st.button("Prepare database backup"):
            st.session_state["backup_bytes"] = store.backup()
        if st.session_state.get("backup_bytes"):
            st.download_button("Download database backup", st.session_state["backup_bytes"], "lab-inventory-backup.sqlite3", "application/vnd.sqlite3")
        items = store.items()
        if items:
            records = [{"Cabinet": i["cabinet_name"], "Item": i["name"], "Description": i["detail"],
                        "Quantity": quantity(i["quantity"]), "Unit": i["unit"], "Low threshold": quantity(i["threshold"]),
                        "Reference stock": quantity(i["target"])} for i in items]
            st.download_button("Download inventory CSV", csv_bytes(records), "lab-inventory.csv", "text/csv")
        st.subheader("Connection checklist")
        st.write("1. Keep this Streamlit server running on your lab network or a host with a persistent disk.\n"
                 "2. Set LAB_PUBLIC_URL to an address phones can reach, then download QR labels.\n"
                 "3. Set LAB_DEMO=false, an administrator password, and your SMTP settings.\n"
                 "4. Start the email worker so failed messages can retry while the app is idle.")
        st.caption("The included README explains phone access, email configuration, deployment, and backups.")


def main():
    try:
        settings = load_settings()
    except (ValueError, OSError) as exc:
        st.error(f"Server settings need attention: {type(exc).__name__}. Check .streamlit/secrets.toml and LAB_SMTP_PORT.")
        st.stop()
    if not settings.demo and len(settings.admin_password) < 12:
        st.title("Set up your lab")
        st.info("Set LAB_ADMIN_PASSWORD to at least 12 characters in the server environment or .streamlit/secrets.toml, then restart. The README includes an example.")
        st.stop()
    if settings.access_code and not password_gate(settings.access_code, "member", "Welcome to your lab", "Enter your shared lab access code to open the inventory."):
        st.stop()
    store = Store(settings.db_path)
    if settings.demo:
        store.seed_demo()
    demo = settings.demo or store.metadata("demo") == "1"
    if not settings.demo and demo:
        st.error("This is a sample database. Set LAB_DB_PATH to a new database for real lab use.")
        st.stop()
    cabinets = store.cabinets()
    with st.sidebar:
        st.markdown('<div class="brand"><span class="brand-icon">⚗</span>Lab Inventory</div>', unsafe_allow_html=True)
        st.caption("A place for every solution.")
        st.write("")
        page = st.radio("Workspace", ["Inventory", "Activity", "QR labels", "Manage lab"], label_visibility="collapsed", key="page")
        st.write("")
        st.divider()
        st.caption("LAB AT A GLANCE")
        st.write(f"**{len(cabinets)}** cabinets · **{sum(c['item_count'] for c in cabinets)}** items")
        low = sum(c["low_count"] for c in cabinets)
        if low:
            st.markdown(f'<span class="badge low">{low} item(s) need a refill</span>', unsafe_allow_html=True)
        else:
            st.markdown('<span class="badge">Stock looks good</span>', unsafe_allow_html=True)
        st.write("")
        st.caption(mail_status(settings, demo))
        if settings.access_code and st.button("Lock lab"):
            st.session_state.clear()
            st.rerun()
    if demo:
        st.caption("● DEMO WORKSPACE  ·  Sample quantities  ·  Emails disabled")
    if "flash" in st.session_state:
        st.success(st.session_state.pop("flash"))
    if page == "Inventory":
        inventory_page(store, cabinets, settings, demo)
    elif page == "Activity":
        history_page(store, cabinets)
    elif page == "QR labels":
        qr_page(cabinets, settings)
    else:
        manage_page(store, cabinets, settings, demo)
    st.markdown('<div class="footer">LAB INVENTORY &nbsp; / &nbsp; Made for the moments between experiments.</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    main()
