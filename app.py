import html
from datetime import datetime
from typing import Any, Dict, List, Optional
import streamlit as st

from parsers.climbers_sutd import parse_day_first_date
from parsers.sheet_parser import get_gym_sheet_name, normalize_gym_name
from services.analytics import calculate_member_debts, calculate_pool_summary, filter_records_by_date
from services.auth import authenticate_user, get_auth_users
from services.pricing import get_gym_pricing, get_pass_price
from services.records import commit_upload, mark_pass_as_paid, mark_passes_as_paid_bulk, process_upload, unmark_pass
from storage.base import StorageBackend
from storage.local_csv import LocalCsvStorage
from ui.charts import render_debt_chart
from ui.components import (
    inject_styles,
    render_badge,
    render_banner,
    render_metric_card,
    render_metrics_row,
    render_table,
)

CONFIGURED_GYMS = ["Boulder +", "Fitbloc", "Boulder Planet"]
DEFAULT_PRICE_PER_PASS = 16.0


@st.cache_resource
def get_storage() -> StorageBackend:
    # initialize storage backend based on configuration
    backend_type = "local_csv"
    from pathlib import Path
    import tomllib
    local_secrets = Path(".streamlit") / "secrets.toml"
    if local_secrets.exists():
        try:
            with open(local_secrets, "rb") as f:
                cfg = tomllib.load(f)
                backend_type = cfg.get("backend", "local_csv")
        except Exception:
            pass
    else:
        try:
            backend_type = st.secrets.get("backend", "local_csv")
        except Exception:
            backend_type = "local_csv"

    if backend_type == "google_sheets":
        try:
            from storage.google_sheets import GoogleSheetsStorage
            storage = GoogleSheetsStorage()
            # verify connection eagerly so errors are caught immediately
            storage._get_spreadsheet()
            return storage
        except Exception as e:
            fallback = LocalCsvStorage()
            fallback._init_error = str(e)
            return fallback
    return LocalCsvStorage()


def get_configured_pass_price(
    gym_name: str,
    tier: str = "tier_2",
    storage: Optional[StorageBackend] = None,
) -> float:
    # return pass price for member tier defaulting to tier 2 rate from pricing sheet
    if storage:
        try:
            pricing = storage.get_pricing()
            return get_pass_price(gym_name, tier=tier, pricing_matrix=pricing)
        except Exception:
            pass
    return get_pass_price(gym_name, tier=tier)


def init_session_state() -> None:
    # initialize session state variables
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if "username" not in st.session_state:
        st.session_state.username = ""
    if "available_passes" not in st.session_state:
        st.session_state.available_passes = 142
    if "available_passes_map" not in st.session_state:
        st.session_state.available_passes_map = {
            "Boulder +": 142,
            "Fitbloc": 50,
            "Boulder Planet": 18,
        }
    if "pending_upload" not in st.session_state:
        st.session_state.pending_upload = None
    if "cached_members" not in st.session_state:
        st.session_state.cached_members = []


def get_gym_available_passes(gym_name: str) -> int:
    # return available pool balance for specified gym
    defaults = {
        "Boulder +": 142,
        "Fitbloc": 50,
        "Boulder Planet": 18,
    }
    if "available_passes_map" not in st.session_state:
        st.session_state.available_passes_map = dict(defaults)
    return st.session_state.available_passes_map.get(gym_name, defaults.get(gym_name, 50))


def set_gym_available_passes(gym_name: str, val: int) -> None:
    # update available pool balance for specified gym
    if "available_passes_map" not in st.session_state:
        st.session_state.available_passes_map = {}
    st.session_state.available_passes_map[gym_name] = val
    if gym_name == "Boulder +":
        st.session_state.available_passes = val


@st.cache_data
def get_cover_image_base64() -> str:
    # load base64 encoded cover image (cached)
    import base64
    from pathlib import Path
    cover_path = Path(__file__).resolve().parent / "data" / "cover.jpg"
    if cover_path.exists():
        try:
            with open(cover_path, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        except Exception:
            return ""
    return ""


def render_login_view() -> None:
    # render modern split-card login view with climbing cover image
    b64_cover = get_cover_image_base64()

    spacer_l, card_col, spacer_r = st.columns([0.5, 9, 0.5])

    with card_col:
        st.markdown('<div style="height: 1.5rem;"></div>', unsafe_allow_html=True)
        col_img, col_form = st.columns([5, 5], gap="large")

        with col_img:
            if b64_cover:
                st.markdown(
                    f"""
                    <div class="login-hero-pane" style="background-image: url('data:image/jpeg;base64,{b64_cover}');">
                        <div class="login-hero-overlay">
                            <div class="login-hero-badge">SUTD CLIMBERS</div>
                            <div class="login-hero-heading">Send Hard.<br>Track Easy.</div>
                            <div class="login-hero-sub">Exco Gym Pass Management & Debt Reconciliation</div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    """
                    <div class="login-hero-pane login-hero-fallback">
                        <div class="login-hero-overlay">
                            <div class="login-hero-badge">SUTD CLIMBERS</div>
                            <div class="login-hero-heading">Send Hard.<br>Track Easy.</div>
                            <div class="login-hero-sub">Exco Gym Pass Management & Debt Reconciliation</div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        with col_form:
            st.markdown(
                """
                <div class="login-form-container">
                    <div class="login-badge-pill">EXCO INTERNAL PORTAL</div>
                    <div class="login-title">Gym Pass Tracker</div>
                    <div class="login-subtitle">Sign in to manage club passes and member debts</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            # notice if accounts have not yet been configured in secrets
            users = get_auth_users()
            if not users:
                st.info("No exco accounts found. Create your login using `python tools/make_password_hash.py` in your terminal.")

            with st.form("login_form"):
                username = st.text_input("Username", placeholder="e.g. exco_admin")
                password = st.text_input("Password", type="password", placeholder="••••••••")
                submitted = st.form_submit_button("Sign In", width="stretch")

                if submitted:
                    if not username or not password:
                        st.error("Please enter both username and password.")
                    else:
                        with st.spinner("Authenticating & loading member directory..."):
                            # authenticate against secrets
                            is_valid = authenticate_user(username, password)
                            if is_valid:
                                st.session_state.authenticated = True
                                st.session_state.username = username
                                # pull a copy of the members list from the 2 spreadsheets upon login
                                try:
                                    storage = get_storage()
                                    sync_res = storage.sync_members_from_google_sheets()
                                    if sync_res.get("synced"):
                                        st.session_state.cached_members = sync_res.get("members", [])
                                except Exception:
                                    pass
                                st.rerun()
                            else:
                                st.error("Invalid username or password.")

            st.markdown(
                """
                <div class="login-footer-security">
                    <span>🔒 Secure Authentication &bull; SUTD Climbers Club</span>
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_app_header(storage: Optional[StorageBackend] = None) -> None:
    # render top bar with gym title, storage status badge, exco user badge, and logout
    cols = st.columns([6, 4, 2])
    with cols[0]:
        st.markdown(
            '<div class="app-title-group">'
            '<span class="app-title">Gym Pass Tracker</span>'
            '<span class="app-subtitle">Climbers SUTD Member Pass Usage and Debt</span>'
            "</div>",
            unsafe_allow_html=True,
        )
    with cols[1]:
        backend_name = getattr(storage, "backend_name", "local_csv")
        has_error = hasattr(storage, "_init_error")
        if backend_name == "google_sheets":
            sheet_title = getattr(storage, "spreadsheet_title", "Google Sheets")
            mode_badge = f'<span style="background: rgba(34, 197, 94, 0.15); color: #4ADE80; border: 1px solid rgba(34, 197, 94, 0.3); padding: 0.25rem 0.6rem; border-radius: 9999px; font-size: 0.75rem; font-weight: 600; margin-right: 0.5rem;" title="{sheet_title}">🟢 Live Google Sheets</span>'
        elif has_error:
            mode_badge = '<span style="background: rgba(239, 68, 68, 0.15); color: #F87171; border: 1px solid rgba(239, 68, 68, 0.3); padding: 0.25rem 0.6rem; border-radius: 9999px; font-size: 0.75rem; font-weight: 600; margin-right: 0.5rem;" title="Google Sheets connection failed. Falling back to local storage.">⚠️ Sheets Offline (Local CSV)</span>'
        else:
            mode_badge = '<span style="background: rgba(234, 179, 8, 0.15); color: #FACC15; border: 1px solid rgba(234, 179, 8, 0.3); padding: 0.25rem 0.6rem; border-radius: 9999px; font-size: 0.75rem; font-weight: 600; margin-right: 0.5rem;" title="Running in Local Mode. Changes saved to local CSV files.">🟡 Local CSV Mode</span>'

        st.markdown(
            f'<div style="text-align: right; padding-top: 0.375rem;">'
            f'{mode_badge}'
            f'<span class="user-badge">{st.session_state.username}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with cols[2]:
        if st.button("Log Out", key="logout_btn", width="stretch"):
            st.session_state.authenticated = False
            st.session_state.username = ""
            st.session_state.cached_members = []
            st.rerun()


def render_overview_tab(gym_name: str, storage: StorageBackend) -> None:
    # overview tab showing available passes and member debts
    st.markdown(f"#### {gym_name} Overview")

    if hasattr(storage, "_init_error"):
        st.error(
            f"⚠️ **Google Sheets Connection Failed**: `{storage._init_error}`\n\n"
            "The app has fallen back to **Local CSV Mode (`data/records.csv`)**. "
            "Any updates or uploaded rows will only be saved locally and **will NOT update your Google Sheet**. "
            "To connect to your live Google Sheet, ensure your `spreadsheet_id` is set in `.streamlit/secrets.toml` "
            "and that the spreadsheet is shared with `debt-tracker-bot@debt-tracker-515005.iam.gserviceaccount.com` as Editor."
        )
    elif getattr(storage, "backend_name", "") == "local_csv":
        st.info(
            "ℹ️ **Current Mode: Local CSV Storage**. New uploads and payments are saved to local files on this computer. "
            "To sync live to your Google Sheet, set `backend = 'google_sheets'` and enter your `spreadsheet_id` in `.streamlit/secrets.toml`."
        )

    try:
        records = storage.get_records(gym=gym_name)
    except Exception as e:
        st.warning(f"⚠️ Google Sheets temporarily disconnected or slow to respond: {e}. Retrying automatically on next action.")
        records = []
    pricing_matrix = storage.get_pricing()
    members = storage.get_members()
    from services.members import get_member_tier_map
    tier_map = get_member_tier_map(members, records=records)

    t1_rate = get_pass_price(gym_name, "tier_1", pricing_matrix)
    t2_rate = get_pass_price(gym_name, "tier_2", pricing_matrix)

    # retrieve latest pass date or sheet last updated date
    latest_stored_date = "-"
    if records:
        parsed_dates = [parse_day_first_date(r.get("usage_date", "")) for r in records]
        valid_dates = [d for d in parsed_dates if d is not None]
        if valid_dates:
            latest_stored_date = max(valid_dates).strftime("%d/%m/%Y")

    target_sheet_name = get_gym_sheet_name(gym_name)
    sync_col1, sync_col2, sync_col3 = st.columns([6, 3, 3])
    with sync_col1:
        st.markdown(
            f'<div style="font-size: 0.8125rem; color: #94A3B8; padding-top: 0.375rem; margin-bottom: 0.75rem;">'
            f'<span>Google Sheet: <b style="color: #F8FAFC;">{target_sheet_name}</b> (Last Updated: <b style="color: #38BDF8;">{latest_stored_date}</b>)</span> &bull; '
            f'<span>Pricing: <b style="color: #C084FC;">Tier 1 (${int(t1_rate)})</b> | <b style="color: #38BDF8;">Tier 2 (${int(t2_rate)})</b></span>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with sync_col2:
        if st.button("Sync Sheet Debt", key=f"sync_btn_{gym_name}", width="stretch"):
            with st.spinner("Synchronizing pass records with Google Sheet..."):
                res = storage.sync_from_google_sheet(gym=gym_name)
                if res.get("synced"):
                    st.toast(f"Synchronized with Google Sheet! Updated: {res.get('last_updated', '')}")
                else:
                    st.toast("Loaded Google Sheet baseline data.")
                st.rerun()
    with sync_col3:
        if st.button("Sync Members List", key=f"sync_members_{gym_name}", width="stretch"):
            with st.spinner("Fetching latest member roster from Google Sheets..."):
                res = storage.sync_members_from_google_sheets()
                if res.get("synced"):
                    st.session_state.cached_members = res.get("members", [])
                    st.toast(f"Synced {res.get('total_members', 0)} members ({res.get('tier_1_count', 0)} Tier 1, {res.get('tier_2_count', 0)} Tier 2) from Google Sheets!")
                else:
                    st.error(f"Sync members failed: {res.get('message')}")
                st.rerun()

    # filter options
    fcols = st.columns([5, 3, 2, 2])
    with fcols[0]:
        search_query = st.text_input(
            "Search Member",
            placeholder="Search member name...",
            label_visibility="collapsed",
            key=f"search_{gym_name}",
        )
    with fcols[1]:
        date_scope = st.selectbox(
            "Date Scope",
            ["All Dates", "Last 30 Days", "Current Semester"],
            label_visibility="collapsed",
            key=f"date_scope_{gym_name}",
        )
    with fcols[2]:
        tier_filter = st.selectbox(
            "Tier Filter",
            ["All Tiers", "Tier 1 Only", "Tier 2 Only"],
            label_visibility="collapsed",
            key=f"tier_filter_{gym_name}",
        )
    with fcols[3]:
        include_paid = st.checkbox(
            "Include fully paid",
            value=False,
            help="Show members with zero passes owed",
            key=f"include_paid_{gym_name}",
        )

    # calculate debts with tier pricing
    member_debts = calculate_member_debts(
        records,
        gym_name=gym_name,
        pricing_matrix=pricing_matrix,
        member_tiers=tier_map,
        canonical_members=members,
        include_paid=include_paid,
    )

    total_owed = sum(m["passes_owed"] for m in member_debts)
    members_owing = sum(1 for m in member_debts if m["passes_owed"] > 0)
    total_dollar_debt = sum(m["amount_owed"] for m in member_debts)

    t1_owed = sum(m["passes_owed"] for m in member_debts if m.get("tier") == "tier_1")
    t1_dollars = sum(m["amount_owed"] for m in member_debts if m.get("tier") == "tier_1")
    t2_owed = sum(m["passes_owed"] for m in member_debts if m.get("tier") == "tier_2")
    t2_dollars = sum(m["amount_owed"] for m in member_debts if m.get("tier") == "tier_2")

    current_avail = get_gym_available_passes(gym_name)

    # summary metrics
    cards = [
        render_metric_card(
            "Available Gym Passes",
            str(current_avail),
            "current pool balance",
            accent="primary",
        ),
        render_metric_card(
            "Total Passes Owed",
            str(total_owed),
            f"${int(total_dollar_debt)} owed total",
            accent="owes",
        ),
        render_metric_card(
            "Tier Breakdown",
            f"T1: {t1_owed} | T2: {t2_owed}",
            f"T1: ${int(t1_dollars)} (${int(t1_rate)}/p) • T2: ${int(t2_dollars)} (${int(t2_rate)}/p)",
            accent="default",
        ),
        render_metric_card(
            "Members Who Owe",
            str(members_owing),
            f"across {len(member_debts)} active records",
            accent="default",
        ),
    ]
    render_metrics_row(cards)

    # update available gym passes balance
    with st.expander("Update Available Passes Balance", expanded=False):
        st.markdown("Set the current total number of passes available in the gym pool:")
        ucols = st.columns([3, 5, 2])
        with ucols[0]:
            new_available = st.number_input(
                "Total Available Passes",
                min_value=0,
                value=int(current_avail),
                step=1,
                label_visibility="collapsed",
                key=f"avail_passes_{gym_name}",
            )
        with ucols[1]:
            update_note = st.text_input(
                "Reason / Note",
                placeholder="e.g. Purchased 50 pass package or gym audit sync",
                label_visibility="collapsed",
                key=f"avail_note_{gym_name}",
            )
        with ucols[2]:
            if st.button("Update Balance", type="primary", width="stretch", key=f"btn_update_balance_{gym_name}"):
                set_gym_available_passes(gym_name, new_available)
                st.toast(f"Updated available passes to {new_available}.")
                st.rerun()

    filtered_members = [
        m for m in member_debts
        if search_query.lower() in m["member"].lower()
        or search_query.lower() in m.get("canonical_name", "").lower()
    ]
    if tier_filter == "Tier 1 Only":
        filtered_members = [m for m in filtered_members if m.get("tier") == "tier_1"]
    elif tier_filter == "Tier 2 Only":
        filtered_members = [m for m in filtered_members if m.get("tier") == "tier_2"]

    # full-width member debt table
    st.markdown("**Members with Passes Owed**")
    headers = ["Member Name", "Tier", "Passes Owed", "Rate", "Amount Owed", "Status"]
    table_rows = []
    for m in filtered_members:
        status_badge = (
            render_badge(f"{m['passes_owed']} owed", "owes")
            if m["passes_owed"] > 0
            else render_badge("Paid", "paid")
        )
        tier_badge = (
            render_badge(f"Tier 1 (${int(m['rate_per_pass'])})", "tier1")
            if m.get("tier") == "tier_1"
            else render_badge(f"Tier 2 (${int(m['rate_per_pass'])})", "tier2")
        )
        display_name = html.escape(m["member"])
        canonical = m.get("canonical_name", "")
        if canonical and canonical.strip().lower() != m["member"].strip().lower():
            display_name = (
                f'<div class="member-name-cell">'
                f'<span class="member-primary-name">{html.escape(m["member"])}</span>'
                f'<span class="member-canonical-name">{html.escape(canonical)}</span>'
                f'</div>'
            )

        table_rows.append([
            display_name,
            tier_badge,
            str(m["passes_owed"]),
            f"${int(m['rate_per_pass'])}",
            f"${int(m['amount_owed'])}",
            status_badge,
        ])

    render_table(
        headers,
        table_rows,
        alignments=["left", "center", "center", "center", "center", "center"],
    )

    # passes owed by member chart shifted below the table
    chart_data = [
        {"member": m["member"], "passes_owed": m["passes_owed"]}
        for m in filtered_members
        if m["passes_owed"] > 0
    ]
    if chart_data:
        st.markdown('<div style="height: 0.75rem;"></div>', unsafe_allow_html=True)
        st.markdown("**Passes Owed by Member**")
        render_debt_chart(chart_data)

    # drill-down section
    st.markdown("---")
    st.markdown("**Member Pass Details**")
    member_names = [m["member"] for m in member_debts if m["passes_owed"] > 0]
    if member_names:
        selected_member = st.selectbox(
            "Select member to view pass history",
            member_names,
            index=0,
            key=f"drill_member_{gym_name}",
        )

        member_data = next((m for m in member_debts if m["member"] == selected_member), None)
        if member_data:
            m_rate = member_data.get("rate_per_pass", 16.0)
            drill_headers = ["Date", "Type", "Pass Adjustment", "Rate", "Gym Staff", "Status"]
            drill_rows = [
                [
                    r.get("usage_date", ""),
                    r.get("type", "Adj"),
                    f"{r.get('adj', -1)} pass",
                    f"${int(m_rate)}",
                    r.get("gym_staff", ""),
                    render_badge("Unpaid", "owes") if r.get("status") in ("unpaid", "not_made") else render_badge("Paid", "paid"),
                ]
                for r in member_data.get("records", [])
            ]
            render_table(
                drill_headers,
                drill_rows,
                alignments=["left", "center", "center", "center", "left", "center"],
            )


def render_upload_tab(gym_name: str, storage: StorageBackend) -> None:
    # upload view with automatic date tracking and reconciliation check
    st.markdown(f"#### Upload {gym_name} Passes Report")
    st.markdown(
        "Upload the latest PDF report. The system automatically reconciles rows, "
        "filters out previously stored entries, and updates the latest pass date."
    )

    # hints from existing storage
    stored_records = storage.get_records(gym=gym_name)
    latest_stored_date = "-"
    if stored_records:
        parsed_dates = [parse_day_first_date(r.get("usage_date", "")) for r in stored_records]
        valid_dates = [d for d in parsed_dates if d is not None]
        if valid_dates:
            latest_stored_date = max(valid_dates).strftime("%d/%m/%Y")

    render_banner(
        f"Database Status: {len(stored_records)} records currently saved. "
        f"Latest pass date recorded: {latest_stored_date}.",
        banner_type="info",
    )

    uploaded_file = st.file_uploader(
        f"Choose {gym_name} PDF Report",
        type=["pdf"],
        help="Upload the official passes history PDF",
        key=f"uploader_{gym_name}",
    )

    if uploaded_file is not None:
        file_bytes = uploaded_file.getvalue()
        filename = uploaded_file.name

        try:
            parse_res, summary = process_upload(
                file_bytes=file_bytes,
                filename=filename,
                uploaded_by=st.session_state.username or "exco_user",
                storage=storage,
                gym_name=gym_name,
            )
        except Exception as err:
            st.error(f"Error parsing upload: {err}")
            return

        if parse_res.error_message:
            st.error(parse_res.error_message)
            return

        # display reconciliation status
        if parse_res.reconciliation_passed:
            render_banner(
                f"Reconciliation Passed: {parse_res.total_dates_found} date entries "
                f"in file match {parse_res.rows_parsed_count} parsed rows exactly.",
                banner_type="success",
            )
        else:
            render_banner(
                f"Reconciliation Alert: Found {parse_res.total_dates_found} dates and "
                f"parsed {parse_res.rows_parsed_count} rows ({len(parse_res.failed_rows)} failed).",
                banner_type="warning",
            )

        # reference date banner
        ref_date = summary.get("reference_date")
        if ref_date:
            render_banner(
                f"Referencing Google Sheet 'Last Updated' date: {ref_date}. "
                f"Importing {summary['rows_added_count']} passes appearing strictly after {ref_date} (non-inclusive). "
                f"({summary['rows_prior_skipped']} historical rows on or before {ref_date} skipped).",
                banner_type="info",
            )

        # counts row
        metric_cards = [
            render_metric_card("Total Rows in File", str(summary["rows_parsed"]), "detected in PDF", accent="primary"),
            render_metric_card(
                f"New Passes (After {ref_date})" if ref_date else "New Passes to Save",
                str(summary["rows_added_count"]),
                "to be added to sheet",
                accent="owes",
            ),
            render_metric_card(
                "Historical Skipped",
                str(summary["rows_skipped_count"]),
                f"prior to {ref_date}" if ref_date else "skipped via deduplication",
                accent="paid",
            ),
        ]
        render_metrics_row(metric_cards)

        # preview of new passes
        new_rows = summary["rows_to_add"]
        if new_rows:
            st.markdown(f"**Preview of {len(new_rows)} New Rows**")
            preview_headers = ["Date", "Type", "Member Name", "Gym Staff", "Adj", "Kind"]
            preview_rows = [
                [
                    r.get("usage_date", ""),
                    r.get("type", "Adj"),
                    r.get("customer", "") or "-",
                    r.get("gym_staff", "") or "-",
                    str(r.get("adj", "")),
                    r.get("row_kind", ""),
                ]
                for r in new_rows[:50]
            ]
            render_table(preview_headers, preview_rows)

            # confirm button
            if st.button(f"Confirm and Save {len(new_rows)} New Rows", type="primary", width="stretch", key=f"btn_commit_{gym_name}"):
                with st.spinner(f"Saving {len(new_rows)} rows and syncing with Google Sheets..."):
                    try:
                        upload_id = commit_upload(summary, storage, gym_name)
                        latest_d = summary.get("latest_date", "")
                        if getattr(storage, "backend_name", "") == "google_sheets":
                            st.success(f"Saved {len(new_rows)} rows and successfully synced live Google Sheet to {latest_d} (Upload ID: {upload_id}).")
                        else:
                            st.success(f"Saved {len(new_rows)} rows to local database (Upload ID: {upload_id}).")
                            st.warning("⚠️ Running in Local Mode. Data was saved to local CSV (`data/records.csv`) and was NOT written to Google Drive.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to commit upload: {e}")
        else:
            if ref_date:
                st.info(f"All rows in this report are on or before {ref_date} or have already been saved.")
            else:
                st.info("All rows in this report have already been saved in the database.")


def render_mark_as_paid_tab(gym_name: str, storage: StorageBackend) -> None:
    # interactive mark as paid view supporting full and partial payments with tier pricing
    st.markdown(f"#### Mark {gym_name} Passes as Paid")
    st.markdown(
        "For full payments, click **Mark All Paid** on the member card. "
        "For partial payments, enter the amount of passes paid or mark individual pass rows."
    )

    records = storage.get_records(gym=gym_name)
    pricing_matrix = storage.get_pricing()
    members = storage.get_members()
    from services.members import get_member_tier_map
    tier_map = get_member_tier_map(members, records=records)

    member_debts = calculate_member_debts(
        records,
        gym_name=gym_name,
        pricing_matrix=pricing_matrix,
        member_tiers=tier_map,
        canonical_members=members,
        include_paid=False,
    )

    if not member_debts:
        st.markdown(
            '<div class="empty-state">'
            '<div class="empty-state-title">No Outstanding Debts</div>'
            '<div class="empty-state-desc">All member passes are currently settled</div>'
            "</div>",
            unsafe_allow_html=True,
        )
        return

    filter_options = ["All Members with Unpaid Passes"] + [m["member"] for m in member_debts]
    selected_filter = st.selectbox("Filter by Member", filter_options, key=f"pay_filter_{gym_name}")

    members_to_show = (
        member_debts
        if selected_filter == "All Members with Unpaid Passes"
        else [m for m in member_debts if m["member"] == selected_filter]
    )

    current_user = st.session_state.username or "exco_user"

    for member_info in members_to_show:
        member_name = member_info["member"]
        canonical_name = member_info.get("canonical_name", member_name)
        tier = member_info.get("tier", "tier_2")
        rate = member_info.get("rate_per_pass", 16.0)

        unpaid_records = [
            r for r in member_info.get("records", [])
            if r.get("status") in ("unpaid", "not_made")
        ]
        unpaid_count = len(unpaid_records)
        unpaid_dollars = int(unpaid_count * rate)

        tier_label = f"Tier 1 (${int(rate)}/p)" if tier == "tier_1" else f"Tier 2 (${int(rate)}/p)"
        expander_title = (
            f"{member_name} — {unpaid_count} Passes Owed (${unpaid_dollars}) [{tier_label}]"
            if canonical_name == member_name
            else f"{member_name} ({canonical_name}) — {unpaid_count} Passes Owed (${unpaid_dollars}) [{tier_label}]"
        )

        with st.expander(expander_title, expanded=True):
            col_info, col_custom, col_all = st.columns([4, 4, 4])

            with col_info:
                tier_badge_html = (
                    render_badge(f"Tier 1 (${int(rate)}/p)", "tier1")
                    if tier == "tier_1"
                    else render_badge(f"Tier 2 (${int(rate)}/p)", "tier2")
                )
                st.markdown(
                    f'<div style="padding-top: 0.5rem;">'
                    f'<span style="font-size: 1rem; font-weight: 600; color: #F8FAFC;">'
                    f'Owed: {unpaid_count} passes (${unpaid_dollars}) &bull; '
                    f'{tier_badge_html}'
                    f'</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

            with col_custom:
                if unpaid_count > 0:
                    sub_num, sub_btn = st.columns([1, 2])
                    with sub_num:
                        pay_amount = st.number_input(
                            "Amount",
                            min_value=1,
                            max_value=unpaid_count,
                            value=1,
                            step=1,
                            key=f"amt_{gym_name}_{member_name}",
                            label_visibility="collapsed",
                        )
                    with sub_btn:
                        pay_dollars = int(pay_amount * rate)
                        if st.button(f"Pay {pay_amount} Pass{'es' if pay_amount > 1 else ''} (${pay_dollars})", key=f"btn_pay_amt_{gym_name}_{member_name}", width="stretch"):
                            with st.spinner(f"Recording payment of {pay_amount} pass(es)..."):
                                rec_ids = [r["record_id"] for r in unpaid_records[:pay_amount]]
                                mark_passes_as_paid_bulk(storage, rec_ids, paid_by=current_user)
                                st.toast(f"Marked {pay_amount} pass(es) for {member_name} as paid.")
                                st.rerun()

            with col_all:
                if unpaid_count > 0:
                    if st.button(
                        f"Mark All Paid (${unpaid_dollars})",
                        key=f"pay_all_{gym_name}_{member_name}",
                        type="primary",
                        width="stretch",
                    ):
                        with st.spinner(f"Marking all passes for {member_name} as paid..."):
                            rec_ids = [r["record_id"] for r in unpaid_records]
                            mark_passes_as_paid_bulk(storage, rec_ids, paid_by=current_user)
                            st.toast(f"Marked all passes for {member_name} as paid.")
                            st.rerun()

            st.markdown('<div style="height: 0.5rem;"></div>', unsafe_allow_html=True)

            # individual pass rows
            for r in member_info.get("records", []):
                rec_id = r.get("record_id", "")
                is_paid = r.get("status") in ("paid", "made")
                col_date, col_staff, col_rate, col_status, col_btn = st.columns([3, 4, 2, 2, 2])
                with col_date:
                    st.markdown(
                        f'<span style="line-height: 2.2; color: #F8FAFC;">{r.get("usage_date", "")}</span>',
                        unsafe_allow_html=True,
                    )
                with col_staff:
                    st.markdown(
                        f'<span style="line-height: 2.2; color: #94A3B8;">Staff: {r.get("gym_staff", "") or "-"}</span>',
                        unsafe_allow_html=True,
                    )
                with col_rate:
                    st.markdown(
                        f'<span style="line-height: 2.2; color: #94A3B8;">${int(rate)}</span>',
                        unsafe_allow_html=True,
                    )
                with col_status:
                    if is_paid:
                        made_by = r.get("made_by", "")
                        badge_label = f"Paid ({made_by})" if made_by else "Paid"
                        st.markdown(render_badge(badge_label, "paid"), unsafe_allow_html=True)
                    else:
                        st.markdown(render_badge("Unpaid", "owes"), unsafe_allow_html=True)
                with col_btn:
                    if is_paid:
                        if st.button("Undo", key=f"undo_{gym_name}_{rec_id}", width="stretch"):
                            unmark_pass(storage, rec_id)
                            st.rerun()
                    else:
                        if st.button("Paid", key=f"pay_{gym_name}_{rec_id}", width="stretch"):
                            mark_pass_as_paid(storage, rec_id, paid_by=current_user)
                            st.rerun()


def render_history_tab(gym_name: str, storage: StorageBackend) -> None:
    # upload audit history and recent payments
    st.markdown(f"#### {gym_name} Audit History")

    # pass payment audit log
    st.markdown("**Pass Payment & Settlement Audit Log**")
    all_records = storage.get_records(gym=gym_name)
    paid_records = [
        r for r in all_records
        if r.get("status") in ("paid", "made") and r.get("made_at")
    ]
    paid_records.sort(key=lambda r: r.get("made_at", ""), reverse=True)

    if paid_records:
        pay_headers = ["Payment Timestamp", "Member Name", "Pass Date", "Marked By", "Status"]
        pay_rows = [
            [
                r.get("made_at", ""),
                r.get("person", "") or r.get("customer", ""),
                r.get("usage_date", ""),
                r.get("made_by", ""),
                render_badge("Paid", "paid"),
            ]
            for r in paid_records[:50]
        ]
        render_table(pay_headers, pay_rows, alignments=["left", "left", "center", "left", "center"])
    else:
        st.info("No pass payments have been recorded yet.")

    st.markdown("---")

    # report upload audit section
    st.markdown("**Report Upload History**")
    uploads = storage.get_uploads(gym=gym_name)
    uploads.sort(key=lambda u: u.get("uploaded_at", ""), reverse=True)

    if uploads:
        history_headers = [
            "Upload ID",
            "Filename",
            "Uploaded By",
            "Uploaded At",
            "Report Prepared",
            "Parsed",
            "Added",
            "Skipped",
            "Date Range",
        ]
        history_rows = [
            [
                u.get("upload_id", ""),
                u.get("filename", ""),
                u.get("uploaded_by", ""),
                u.get("uploaded_at", ""),
                u.get("report_prepared_at", "") or "-",
                str(u.get("rows_parsed", "")),
                str(u.get("rows_added", "")),
                str(u.get("rows_skipped", "")),
                f"{u.get('earliest_date', '')} - {u.get('latest_date', '')}",
            ]
            for u in uploads
        ]
        render_table(history_headers, history_rows)
    else:
        st.info("No report uploads recorded yet.")


def render_members_tab(storage: StorageBackend, gym_name: str = "") -> None:
    # members and tier assignments tab linked dynamically to google sheets
    st.markdown("#### Club Members & Tier Directory")
    st.markdown(
        "Members list and Tier 2 assignments are dynamically pulled upon login from your external Google Spreadsheets. "
        "Tier 1 members are automatically computed as the difference between All Members and Tier 2. "
        "*(This roster is held in memory for calculations and is never written to your main debt tracking spreadsheet).*"
    )

    members = storage.get_members()

    m_col1, m_col2 = st.columns([8, 4])
    with m_col1:
        t1_count = sum(1 for m in members if m.get("tier") == "tier_1")
        t2_count = sum(1 for m in members if m.get("tier") == "tier_2")
        st.markdown(
            f'<div style="padding-top: 0.5rem; font-size: 0.875rem; color: #94A3B8;">'
            f'<span>Total Registered Members: <b style="color: #F8FAFC;">{len(members)}</b></span> &bull; '
            f'<span>Tier 1: <b style="color: #C084FC;">{t1_count} members ($18/pass)</b></span> &bull; '
            f'<span>Tier 2: <b style="color: #38BDF8;">{t2_count} members ($16/pass)</b></span>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with m_col2:
        if st.button("Sync Members from Google Sheets", key=f"btn_sync_members_tab_{gym_name}", width="stretch"):
            with st.spinner("Fetching latest member roster from Google Sheets..."):
                res = storage.sync_members_from_google_sheets()
                if res.get("synced"):
                    st.session_state.cached_members = res.get("members", [])
                    st.toast(f"Synced {res.get('total_members', 0)} members ({res.get('tier_1_count', 0)} Tier 1, {res.get('tier_2_count', 0)} Tier 2) from Google Sheets!")
                else:
                    st.error(f"Failed to sync: {res.get('message')}")
                st.rerun()

    st.markdown('<div style="height: 0.5rem;"></div>', unsafe_allow_html=True)

    filter_cols = st.columns([8, 4])
    with filter_cols[0]:
        search_kw = st.text_input("Search Members Directory", placeholder="Search by name, email, or alias...", label_visibility="collapsed", key=f"search_members_{gym_name}")
    with filter_cols[1]:
        tier_choice = st.selectbox("Filter Tier", ["All Members", "Tier 1 Only", "Tier 2 Only"], label_visibility="collapsed", key=f"tier_choice_{gym_name}")

    filtered = members
    if search_kw:
        kw = search_kw.lower()
        filtered = [
            m for m in filtered
            if kw in m.get("canonical_name", "").lower()
            or kw in m.get("email", "").lower()
            or kw in m.get("aliases", "").lower()
        ]

    if tier_choice == "Tier 1 Only":
        filtered = [m for m in filtered if m.get("tier") == "tier_1"]
    elif tier_choice == "Tier 2 Only":
        filtered = [m for m in filtered if m.get("tier") == "tier_2"]

    headers = ["Member Name", "Tier", "Email", "Contact No.", "Recognized Aliases / PDF Names"]
    rows = []
    for m in filtered:
        tier_str = m.get("tier", "tier_2")
        tier_badge = (
            render_badge("Tier 1 ($18)", "tier1")
            if tier_str == "tier_1"
            else render_badge("Tier 2 ($16)", "tier2")
        )
        aliases = m.get("aliases", "")
        if isinstance(aliases, str):
            aliases_list = [a.strip() for a in aliases.split(";") if a.strip()]
            aliases_display = ", ".join(aliases_list[:3])
            if len(aliases_list) > 3:
                aliases_display += f" (+{len(aliases_list) - 3} more)"
        else:
            aliases_display = "-"

        rows.append([
            m.get("canonical_name", ""),
            tier_badge,
            m.get("email", "") or "-",
            m.get("contact_no", "") or "-",
            aliases_display or "-",
        ])

    render_table(headers, rows, alignments=["left", "center", "left", "left", "left"])


def render_gym_view(gym_name: str, storage: StorageBackend) -> None:
    # modular view for each gym ready for future expansion
    view_mode = st.segmented_control(
        "Section",
        options=["Overview", "Upload", "Mark as Paid", "History", "Members & Tiers"],
        default="Overview",
        label_visibility="collapsed",
        key=f"sec_ctrl_{gym_name}",
    )

    if view_mode == "Overview":
        render_overview_tab(gym_name, storage)
    elif view_mode == "Upload":
        render_upload_tab(gym_name, storage)
    elif view_mode == "Mark as Paid":
        render_mark_as_paid_tab(gym_name, storage)
    elif view_mode == "History":
        render_history_tab(gym_name, storage)
    elif view_mode == "Members & Tiers":
        render_members_tab(storage, gym_name=gym_name)


def main() -> None:
    # main application controller
    st.set_page_config(
        page_title="Gym Pass Tracker",
        page_icon=None,
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    inject_styles()
    init_session_state()

    # login gate
    if not st.session_state.authenticated:
        render_login_view()
        return

    storage = get_storage()

    # ensure member directory is in session cache if not already pulled
    if not st.session_state.get("cached_members"):
        with st.spinner("Fetching latest member roster from Google Sheets..."):
            try:
                sync_res = storage.sync_members_from_google_sheets()
                if sync_res.get("synced"):
                    st.session_state.cached_members = sync_res.get("members", [])
            except Exception:
                pass

    # application header
    render_app_header(storage)

    # gym tabs ready to expand with more gyms
    gym_tabs = st.tabs(CONFIGURED_GYMS)
    for index, gym_name in enumerate(CONFIGURED_GYMS):
        with gym_tabs[index]:
            render_gym_view(gym_name, storage)


if __name__ == "__main__":
    main()
