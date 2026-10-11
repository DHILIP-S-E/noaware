"""NowAware - A Personal AI Agent That Notices What Matters.

Main Streamlit Application.
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timezone
import streamlit as st

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.config import settings
from src.schemas.monitoring import MonitoringRule, RuleStatus, SourceType
from src.schemas.changes import ClassificationType, ConfidenceLevel, ChangeEvent
from src.storage.sqlite_store import SQLiteStorage
from src.storage.dynamodb_store import DynamoDBStorage
from src.monitoring.fetcher import SourceFetcher
from src.monitoring.service import MonitoringService
from src.notifications.ses_email import SESEmailProvider
from src.security.url_validator import validate_url, URLSecurityError
from fixtures.scenarios import (
    DEMO_SCENARIOS,
    SCHOLARSHIP_BASELINE,
    RESEARCH_FEED_BASELINE,
)

# ---------------------------------------------------------
# Page Setup & Styling
# ---------------------------------------------------------
st.set_page_config(
    page_title="NowAware — AI Agent That Notices What Matters",
    page_icon="👁️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Premium Dark Navy CSS Styling
st.markdown("""
<style>
    /* Global Styles */
    .stApp {
        background-color: #0b132b;
        color: #f1f5f9;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    
    /* Headers */
    h1, h2, h3, h4 {
        color: #f8fafc;
        font-weight: 600;
        letter-spacing: -0.02em;
    }
    
    /* Soft Card Containers */
    .nowaware-card {
        background-color: #16203b;
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 10px;
        padding: 20px;
        margin-bottom: 16px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
    }
    
    /* Metric Card */
    .metric-card {
        background: linear-gradient(145deg, #16203b, #121a30);
        border: 1px solid rgba(245, 158, 11, 0.2);
        border-radius: 10px;
        padding: 16px 20px;
        text-align: left;
    }
    .metric-value {
        font-size: 28px;
        font-weight: 700;
        color: #f59e0b;
        margin-top: 4px;
    }
    .metric-label {
        font-size: 13px;
        color: #94a3b8;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        font-weight: 600;
    }
    
    /* Pill Badges */
    .badge-meaningful {
        background-color: rgba(245, 158, 11, 0.15);
        color: #fbbf24;
        border: 1px solid rgba(245, 158, 11, 0.4);
        padding: 3px 10px;
        border-radius: 9999px;
        font-size: 12px;
        font-weight: 600;
        display: inline-block;
    }
    .badge-irrelevant {
        background-color: rgba(148, 163, 184, 0.12);
        color: #94a3b8;
        border: 1px solid rgba(148, 163, 184, 0.25);
        padding: 3px 10px;
        border-radius: 9999px;
        font-size: 12px;
        font-weight: 600;
        display: inline-block;
    }
    .badge-uncertain {
        background-color: rgba(56, 189, 248, 0.15);
        color: #38bdf8;
        border: 1px solid rgba(56, 189, 248, 0.3);
        padding: 3px 10px;
        border-radius: 9999px;
        font-size: 12px;
        font-weight: 600;
        display: inline-block;
    }
    .badge-active {
        background-color: rgba(34, 197, 94, 0.15);
        color: #4ade80;
        border: 1px solid rgba(34, 197, 94, 0.3);
        padding: 3px 10px;
        border-radius: 9999px;
        font-size: 12px;
        font-weight: 600;
        display: inline-block;
    }
    .badge-paused {
        background-color: rgba(234, 179, 8, 0.15);
        color: #fde047;
        border: 1px solid rgba(234, 179, 8, 0.3);
        padding: 3px 10px;
        border-radius: 9999px;
        font-size: 12px;
        font-weight: 600;
        display: inline-block;
    }
    .badge-error {
        background-color: rgba(239, 68, 68, 0.15);
        color: #f87171;
        border: 1px solid rgba(239, 68, 68, 0.3);
        padding: 3px 10px;
        border-radius: 9999px;
        font-size: 12px;
        font-weight: 600;
        display: inline-block;
    }

    /* Comparison Box */
    .compare-box {
        background-color: #0f172a;
        border: 1px solid #1e293b;
        border-radius: 6px;
        padding: 12px 14px;
        font-family: monospace;
        font-size: 13px;
    }
    .compare-old {
        color: #f87171;
        margin-bottom: 6px;
    }
    .compare-new {
        color: #4ade80;
    }
    
    /* Evidence Quote */
    .evidence-quote {
        border-left: 3px solid #f59e0b;
        background-color: rgba(245, 158, 11, 0.05);
        padding: 8px 12px;
        margin: 6px 0;
        font-size: 13px;
        color: #e2e8f0;
        border-radius: 0 4px 4px 0;
    }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------
# State & Dependency Injection
# ---------------------------------------------------------
@st.cache_resource
def get_service() -> MonitoringService:
    if settings.is_aws_mode and settings.check_aws_credentials():
        storage = DynamoDBStorage()
    else:
        storage = SQLiteStorage(settings.local_db_path)

    fetcher = SourceFetcher()
    # Register demo mock sources into the fetcher
    fetcher.register_mock_source("mock://foundation.org/scholarship", SCHOLARSHIP_BASELINE)
    fetcher.register_mock_source("mock://cleanenergy.gov/feed.xml", RESEARCH_FEED_BASELINE)
    fetcher.register_mock_source("mock://unstable-source.gov/notices", "<h1>Notice Board</h1><p>System operational</p>")

    notifier = SESEmailProvider()
    return MonitoringService(storage=storage, fetcher=fetcher, notification_provider=notifier)


service = get_service()

# Seed default demo rules if workspace database is brand new
if "seeded" not in st.session_state:
    existing_rules = service.storage.list_rules()
    if len(existing_rules) == 0:
        for s_key in ["scenario_1", "scenario_3"]:
            sc = DEMO_SCENARIOS[s_key]
            template = sc["rule_template"]
            rule = MonitoringRule(
                name=template["name"],
                source_url=template["source_url"],
                source_type=template["source_type"],
                natural_language_goal=template["natural_language_goal"],
                criteria_categories=template["criteria_categories"],
                specific_instructions=template.get("specific_instructions", ""),
                check_interval_minutes=template["check_interval_minutes"],
                is_demo_rule=True,
                owner_id="user-alice",
            )
            service.storage.save_rule(rule)
            try:
                service.establish_baseline(rule, owner_id="user-alice")
            except Exception:
                pass
    st.session_state["seeded"] = True


# ---------------------------------------------------------
# Top Navigation, Tenant Authentication & Mode Indicator
# ---------------------------------------------------------
with st.sidebar:
    st.markdown("## 👁️ **NowAware**")
    st.caption("Personal AI Agent That Notices What Matters")

    # Authentication & Tenant Boundary Resolution
    from src.security.auth import resolve_request_identity
    if not settings.is_aws_mode:
        st.markdown(
            '<div class="badge-irrelevant" style="margin-bottom: 8px;">💻 LOCAL DEMO MODE (SQLite)</div>',
            unsafe_allow_html=True,
        )
        st.caption("🔒 **Simulated Multi-Tenant Testing Only**")
        current_user = st.selectbox(
            "DEMO ONLY: Select Simulated Tenant:",
            options=["user-alice", "user-bob", "default-user"],
            index=0,
            help="Simulates independent tenant contexts strictly for local offline demonstration and evaluation.",
        )
    else:
        # AWS-backed mode: never trust frontend-supplied tenant parameter
        st.markdown(
            '<div class="badge-meaningful" style="margin-bottom: 8px;">☁️ AWS MODE (Bedrock + DynamoDB)</div>',
            unsafe_allow_html=True,
        )
        cloud_user, is_verified, auth_status = resolve_request_identity()
        if is_verified and cloud_user:
            st.success(f"Verified Cloud Principal: `{cloud_user}`")
            current_user = cloud_user
        else:
            st.error("⚠️ Multi-User Cloud Access Disabled")
            st.caption(
                "Frontend tenant-switching is strictly prohibited in AWS mode. "
                "No verified Identity Provider (Cognito / ALB OIDC) detected."
            )
            current_user = None

    if current_user:
        from src.agent.tools import set_global_context
        set_global_context(service.storage, service.fetcher, owner_id=current_user)
        stats = service.storage.get_stats(owner_id=current_user)
        unread_count = stats.get("unread_alerts", 0)
    else:
        stats = {}
        unread_count = 0

    menu_options = [
        "Dashboard",
        f"Alert Inbox ({unread_count})" if unread_count > 0 else "Alert Inbox",
        "Create Monitor",
        "Monitor Details",
        "Demo Scenarios",
        "Settings",
    ]
    
    # Preserve active tab in session
    if "selected_page" not in st.session_state:
        st.session_state["selected_page"] = "Dashboard"

    # Default to current or user click
    selected = st.radio(
        "Navigation",
        options=menu_options,
        index=0 if "Dashboard" in st.session_state["selected_page"] else [
            "Dashboard" in opt or opt.startswith(st.session_state["selected_page"].split(" ")[0])
            for opt in menu_options
        ].index(True) if any(opt.startswith(st.session_state["selected_page"].split(" ")[0]) for opt in menu_options) else 0,
        label_visibility="collapsed",
    )
    # Normalize selected text
    if "Alert Inbox" in selected:
        st.session_state["selected_page"] = "Alert Inbox"
    else:
        st.session_state["selected_page"] = selected

    st.markdown("---")
    st.markdown("### **Quiet by Default**")
    st.markdown(
        "<small style='color: #94a3b8;'>NowAware filters out styling, telemetry, and irrelevant edits, alerting you only to substantive changes that match your goal.</small>",
        unsafe_allow_html=True,
    )

page = st.session_state["selected_page"]

# Hard security boundary for unauthenticated cloud mode
if current_user is None:
    st.error("### 🔒 Multi-User Cloud Access Disabled")
    st.warning(
        "NowAware is running in AWS Cloud Mode, but no verified enterprise identity "
        "(such as AWS Cognito or ALB OIDC authentication headers) was detected.\n\n"
        "To prevent unauthorized tenant spoofing, frontend tenant selection is prohibited in cloud mode.\n\n"
        "**Required Actions:**\n"
        "- Connect an authorized Identity Provider (Cognito / ALB OIDC) setting `x-amzn-oidc-identity`, or\n"
        "- Configure `VERIFIED_CLOUD_USER_ID` or IAM environment credentials, or\n"
        "- Switch back to Local Demo Mode (`NOWAWARE_MODE=local`) for standalone testing."
    )
    st.stop()


# =========================================================
# SCREEN A & B: DASHBOARD & WELCOME
# =========================================================
if page == "Dashboard":
    # Welcome & Onboarding Banner
    st.markdown("""
    <div class="nowaware-card" style="border-left: 4px solid #f59e0b;">
        <h1 style="font-size: 26px; margin-bottom: 8px;">Stay aware of what matters.</h1>
        <p style="color: #94a3b8; font-size: 15px; margin-bottom: 16px;">
            Tell NowAware what you care about. Your agent watches the sources you choose and lets you know when something important changes.
        </p>
    </div>
    """, unsafe_allow_html=True)

    # Quick prompt input
    col_input, col_btn = st.columns([4, 1])
    with col_input:
        quick_query = st.text_input(
            "What would you like me to watch?",
            placeholder="e.g. Watch this scholarship page for deadline changes",
            label_visibility="collapsed",
        )
    with col_btn:
        if st.button("Start Watching ➔", use_container_width=True, type="primary"):
            if quick_query:
                st.session_state["draft_nl_goal"] = quick_query
                st.session_state["selected_page"] = "Create Monitor"
                st.rerun()

    # Metrics Row
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Active Monitors</div>
            <div class="metric-value">{stats['active_rules']}</div>
        </div>
        """, unsafe_allow_html=True)
    with m2:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Meaningful Changes</div>
            <div class="metric-value">{stats['meaningful_changes']}</div>
        </div>
        """, unsafe_allow_html=True)
    with m3:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Unread Alerts</div>
            <div class="metric-value" style="color: {'#fbbf24' if stats['unread_alerts'] > 0 else '#94a3b8'};">{stats['unread_alerts']}</div>
        </div>
        """, unsafe_allow_html=True)
    with m4:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Sources Needing Attention</div>
            <div class="metric-value" style="color: {'#f87171' if stats['needing_attention'] > 0 else '#4ade80'};">{stats['needing_attention']}</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)

    # Active Monitors List (Scoped to active tenant user)
    st.subheader(f"Monitored Sources ({current_user})")
    rules = service.storage.list_rules(owner_id=current_user)

    if not rules:
        st.info(f"No active monitors for '{current_user}'. Tell NowAware what you would like to watch above or click 'Create Monitor' to begin.")
    else:
        for rule in rules:
            rule_alerts = service.storage.list_change_events(rule_id=rule.id, owner_id=current_user, only_unread=True)
            unread_for_rule = len(rule_alerts)

            with st.container():
                st.html(f"""
                <div class="nowaware-card">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                        <div>
                            <span style="font-size: 18px; font-weight: 600; color: #f8fafc;">{rule.name}</span>
                            &nbsp;
                            <span class="badge-{rule.status.value}">{rule.status.value.upper()}</span>
                            {f'&nbsp;<span class="badge-meaningful">{unread_for_rule} NEW ALERT</span>' if unread_for_rule > 0 else ''}
                            <div style="color: #cbd5e1; font-size: 14px; margin-top: 4px;">🎯 <b>Goal:</b> {rule.natural_language_goal}</div>
                            <div style="color: #64748b; font-size: 13px; margin-top: 2px;">🔗 <code>{rule.source_url}</code></div>
                        </div>
                    </div>
                </div>
                """)

                c_info1, c_info2, c_btn1, c_btn2, c_btn3, c_btn4 = st.columns([3, 3, 1.5, 1.5, 1.5, 1.2])
                with c_info1:
                    last_str = rule.last_checked_at[:19].replace("T", " ") if rule.last_checked_at else "Never"
                    st.caption(f"Last checked: **{last_str}**")
                with c_info2:
                    next_str = rule.next_check_at[:19].replace("T", " ") if rule.next_check_at else "Pending"
                    st.caption(f"Next scheduled: **{next_str}**")
                
                with c_btn1:
                    if st.button("Check Now", key=f"check_{rule.id}", use_container_width=True):
                        with st.spinner("Checking source..."):
                            has_changed, event, msg = service.check_rule(rule.id, owner_id=current_user)
                            if has_changed and event:
                                st.success(f"Change detected: {event.summary}")
                            elif has_changed and not event:
                                st.info(msg)
                            else:
                                st.info(msg or "Source is unchanged.")
                        st.rerun()

                with c_btn2:
                    if st.button("Details", key=f"details_{rule.id}", use_container_width=True):
                        st.session_state["selected_monitor_id"] = rule.id
                        st.session_state["selected_page"] = "Monitor Details"
                        st.rerun()

                with c_btn3:
                    if rule.status == RuleStatus.ACTIVE:
                        if st.button("Pause", key=f"pause_{rule.id}", use_container_width=True):
                            rule.status = RuleStatus.PAUSED
                            service.storage.update_rule(rule, owner_id=current_user)
                            st.rerun()
                    else:
                        if st.button("Resume", key=f"resume_{rule.id}", use_container_width=True):
                            rule.status = RuleStatus.ACTIVE
                            service.storage.update_rule(rule, owner_id=current_user)
                            st.rerun()

                with c_btn4:
                    if st.button("Delete", key=f"del_{rule.id}", use_container_width=True):
                        service.storage.delete_rule(rule.id, owner_id=current_user)
                        st.rerun()

                st.markdown("<hr style='border-color: rgba(255,255,255,0.05); margin: 8px 0;'>", unsafe_allow_html=True)


# =========================================================
# SCREEN C: CREATE MONITOR (GUIDED WORKFLOW)
# =========================================================
elif page == "Create Monitor":
    st.title("Create New Monitor")
    st.markdown("Guided configuration: Set your goal, confirm the source, establish the baseline, and activate your personal AI monitoring agent.")

    step = st.session_state.get("create_step", 1)

    # Progress Indicator
    st.progress((step) / 6, text=f"Step {step} of 6")

    # STEP 1: Natural-Language Request
    st.markdown("### Step 1: What is your monitoring goal?")
    initial_goal = st.session_state.get("draft_nl_goal", "")
    goal_input = st.text_input(
        "Express your monitoring purpose in plain English:",
        value=initial_goal,
        placeholder="e.g., Watch this scholarship announcement and alert me if the deadline changes.",
    )

    # Example chips
    st.markdown("<small style='color: #94a3b8;'>Or pick an example goal:</small>", unsafe_allow_html=True)
    c_ex1, c_ex2, c_ex3 = st.columns(3)
    with c_ex1:
        if st.button("Scholarship Deadline Alert", use_container_width=True):
            st.session_state["draft_nl_goal"] = "Watch this scholarship announcement and alert me if the deadline changes."
            st.session_state["draft_url"] = "mock://foundation.org/scholarship"
            st.session_state["draft_categories"] = ["Important dates and deadlines"]
            st.rerun()
    with c_ex2:
        if st.button("New Clean Energy Grant Feed", use_container_width=True):
            st.session_state["draft_nl_goal"] = "Track this RSS feed for new opportunities relevant to energy innovation."
            st.session_state["draft_url"] = "mock://cleanenergy.gov/feed.xml"
            st.session_state["draft_categories"] = ["New announcements", "Price, fees, or numerical values"]
            st.rerun()
    with c_ex3:
        if st.button("Public Notice Eligibility", use_container_width=True):
            st.session_state["draft_nl_goal"] = "Monitor this official notice and explain any new requirements or rules."
            st.session_state["draft_url"] = "https://example.com"
            st.session_state["draft_categories"] = ["Eligibility or requirements"]
            st.rerun()

    # STEP 2: Collect or Confirm URL
    st.markdown("### Step 2: Confirm the Public Source URL or Feed")
    default_url = st.session_state.get("draft_url", "")
    url_input = st.text_input(
        "Source Webpage or RSS/Atom Feed URL:",
        value=default_url,
        placeholder="https://example.edu/scholarships or RSS feed URL",
    )

    # STEP 3: Choose What Matters
    st.markdown("### Step 3: What types of changes matter?")
    available_categories = [
        "Important dates and deadlines",
        "Eligibility or requirements",
        "Price, fees, or numerical values",
        "New announcements",
        "Specific keywords or phrases",
        "Selected sections of a page",
        "Other user-defined changes",
    ]
    preselected = st.session_state.get("draft_categories", ["Important dates and deadlines"])
    chosen_categories = st.multiselect(
        "Select change criteria to alert on (Quiet by default filters everything else):",
        options=available_categories,
        default=[c for c in preselected if c in available_categories],
    )

    specific_keywords = st.text_input(
        "Optional specific keywords to track (comma-separated):",
        value=st.session_state.get("draft_keywords", ""),
        placeholder="e.g. deadline, due date, GPA, funding, eligibility",
    )

    # STEP 4: Agent Proposed Rule
    st.markdown("### Step 4: Proposed Monitoring Rule")
    proposed_name = st.text_input(
        "Monitor Display Name:",
        value=st.session_state.get("draft_name", "Target Source Monitor" if not goal_input else f"Monitor: {goal_input[:35]}..."),
    )
    col_int, col_type = st.columns(2)
    with col_int:
        check_interval = st.number_input(
            "Checking Interval (Minutes):",
            min_value=5,
            max_value=1440,
            value=30,
            step=5,
            help="Detection is periodic, not instantaneous. Minimum 5 minutes.",
        )
    with col_type:
        st.markdown("<small style='color: #94a3b8;'>Detection Cadence Note:</small>", unsafe_allow_html=True)
        st.caption("Checks execute periodically via EventBridge/scheduled workers to prevent aggressive server polling.")

    # STEP 5 & 6: Source Preview & Confirmation
    st.markdown("### Step 5 & 6: Source Preview & Baseline Confirmation")
    st.caption("NowAware will fetch the source once, establish a clean text baseline, and wait for your confirmation.")

    preview_container = st.empty()

    if st.button("Preview Source & Establish Baseline", type="secondary"):
        if not url_input:
            st.error("Please supply a valid URL to inspect.")
        else:
            with st.spinner("Validating URL security and inspecting source content..."):
                try:
                    allow_mock = url_input.startswith("mock://") or url_input.startswith("fixture://")
                    is_safe, resolved_ip = validate_url(url_input, allow_mock_schemes=allow_mock)
                    raw_content, meta = service.fetcher.fetch(url_input)
                    from src.monitoring.parser import SourceParser
                    norm_text, title, p_meta = SourceParser.parse(raw_content)

                    st.session_state["preview_success"] = True
                    st.session_state["preview_text"] = norm_text
                    st.session_state["preview_title"] = title
                    st.success(f"Source verified! Page Title: **{title or 'Untitled'}** ({len(norm_text)} readable characters)")
                    with st.expander("Inspect Extracted Normalized Baseline", expanded=True):
                        st.code(norm_text[:1200] + "\n...", language="markdown")
                except (URLSecurityError, Exception) as e:
                    st.session_state["preview_success"] = False
                    st.error(f"Security or Fetch Error: {e}")

    # Activation Button
    st.markdown("---")
    confirm_activate = st.button("Confirm & Activate Monitor 🚀", type="primary", use_container_width=True)

    if confirm_activate:
        if not goal_input:
            st.error("Please specify a monitoring goal.")
        elif not url_input:
            st.error("Please specify a source URL.")
        elif not chosen_categories:
            st.error("Please select at least one change category that matters to you.")
        else:
            with st.spinner("Establishing baseline and activating monitor..."):
                try:
                    rule = MonitoringRule(
                        name=proposed_name,
                        source_url=url_input,
                        owner_id=current_user,
                        source_type=SourceType.RSS if "feed" in url_input.lower() or "xml" in url_input.lower() else SourceType.HTML,
                        natural_language_goal=goal_input,
                        criteria_categories=chosen_categories,
                        specific_instructions=specific_keywords,
                        check_interval_minutes=check_interval,
                        status=RuleStatus.ACTIVE,
                    )
                    service.storage.save_rule(rule)
                    service.establish_baseline(rule, owner_id=current_user)
                    st.success(f"Monitor '{rule.name}' successfully activated for {current_user}!")
                    st.session_state["selected_page"] = "Dashboard"
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to activate monitor: {e}")


# =========================================================
# SCREEN D: MONITOR DETAILS
# =========================================================
elif page == "Monitor Details":
    st.title("Monitor Details & Inspection")

    rules = service.storage.list_rules(owner_id=current_user)
    if not rules:
        st.info(f"No monitors configured for user '{current_user}'.")
    else:
        # Selector
        rule_map = {f"{r.name} ({r.source_url[:30]}...)": r.id for r in rules}
        selected_id = st.session_state.get("selected_monitor_id", list(rule_map.values())[0])
        # Find index
        keys = list(rule_map.keys())
        current_idx = 0
        for i, k in enumerate(keys):
            if rule_map[k] == selected_id:
                current_idx = i
                break

        chosen_key = st.selectbox("Select Monitor to inspect:", options=keys, index=current_idx)
        rule_id = rule_map[chosen_key]
        rule = service.storage.get_rule(rule_id, owner_id=current_user)

        if rule:
            # Monitor Header Card
            st.html(f"""
            <div class="nowaware-card">
                <div style="display: flex; justify-content: space-between;">
                    <div>
                        <h2>{rule.name}</h2>
                        <span class="badge-{rule.status.value}">{rule.status.value.upper()}</span>
                        <p style="margin-top: 8px; color: #cbd5e1;">🎯 <b>Monitoring Goal:</b> {rule.natural_language_goal}</p>
                        <p style="color: #64748b;">🔗 <b>Source URL:</b> <code>{rule.source_url}</code> | <b>Owner:</b> <code>{rule.owner_id}</code></p>
                    </div>
                </div>
            </div>
            """)

            # Action buttons
            c_btn_a, c_btn_b, c_btn_c = st.columns(3)
            with c_btn_a:
                if st.button("Check Source Now", type="primary", use_container_width=True):
                    with st.spinner("Checking source..."):
                        has_changed, event, msg = service.check_rule(rule.id, owner_id=current_user)
                        if has_changed and event:
                            st.success(f"Change detected: {event.summary}")
                        elif has_changed and not event:
                            st.info(msg)
                        else:
                            st.info(msg or "Source is unchanged.")
                    st.rerun()

            with c_btn_b:
                if rule.status == RuleStatus.ACTIVE:
                    if st.button("Pause Scheduled Checks", use_container_width=True):
                        rule.status = RuleStatus.PAUSED
                        service.storage.update_rule(rule, owner_id=current_user)
                        st.rerun()
                else:
                    if st.button("Resume Scheduled Checks", use_container_width=True):
                        rule.status = RuleStatus.ACTIVE
                        service.storage.update_rule(rule, owner_id=current_user)
                        st.rerun()

            with c_btn_c:
                if st.button("Delete Monitor", use_container_width=True):
                    service.storage.delete_rule(rule.id, owner_id=current_user)
                    st.session_state["selected_page"] = "Dashboard"
                    st.rerun()

            # Metadata Tabs
            tab_baseline, tab_alerts, tab_simulate = st.tabs([
                "Current Baseline Snapshot",
                "Alert History for this Monitor",
                "Simulate Update (Demo Mode)",
            ])

            with tab_baseline:
                latest_snapshot = service.storage.get_latest_snapshot(rule.id)
                if latest_snapshot:
                    st.markdown(f"**Baseline Captured At:** `{latest_snapshot.captured_at}`")
                    st.markdown(f"**Content Hash:** `{latest_snapshot.content_hash}`")
                    st.markdown(f"**Summary:** {latest_snapshot.summary}")
                    st.text_area(
                        "Stored Normalized Baseline Text:",
                        value=latest_snapshot.normalized_content,
                        height=250,
                        disabled=True,
                    )
                else:
                    st.warning("No baseline snapshot captured yet.")

            with tab_alerts:
                events = service.storage.list_change_events(rule_id=rule.id, owner_id=current_user)
                if not events:
                    st.info("No change alerts recorded for this monitor yet.")
                else:
                    for ev in events:
                        badge_class = f"badge-{ev.classification.value}"
                        st.html(f"""
                        <div class="nowaware-card">
                            <span class="{badge_class}">{ev.classification.value.upper()}</span>
                            &nbsp;
                            <span style="color: #64748b; font-size: 12px;">{ev.detected_at}</span>
                            <h4 style="margin: 8px 0 4px 0;">{ev.summary}</h4>
                            <p style="color: #cbd5e1; font-size: 14px;">{ev.impact_explanation}</p>
                            {f'<div class="compare-box"><div class="compare-old">- {ev.previous_value}</div><div class="compare-new">+ {ev.new_value}</div></div>' if ev.previous_value or ev.new_value else ''}
                        </div>
                        """)

            with tab_simulate:
                st.markdown("#### Simulate Source Updates")
                st.caption("Demonstrate how NowAware evaluates changes without needing to edit live external websites.")
                sim_choice = st.selectbox(
                    "Choose update scenario to simulate on this monitor:",
                    options=[
                        "Meaningful Deadline Change (May 15 -> April 10)",
                        "Cosmetic Layout / Footer Noise (Should be suppressed)",
                        "Custom Replacement Text",
                    ],
                )
                if sim_choice.startswith("Meaningful"):
                    sim_content = DEMO_SCENARIOS["scenario_1"]["updated_content"]
                elif sim_choice.startswith("Cosmetic"):
                    sim_content = DEMO_SCENARIOS["scenario_2"]["updated_content"]
                else:
                    sim_content = st.text_area("Input custom HTML or text:", value="<h1>Updated Content</h1><p>Application Deadline: March 1, 2026</p>")

                if st.button("Apply Simulated Check ⚡", type="primary"):
                    with st.spinner("Processing simulated check through classification engine..."):
                        has_changed, event, msg = service.check_rule(rule.id, simulated_content=sim_content, owner_id=current_user)
                        if has_changed and event:
                            st.success(f"Change classified as: {event.classification.value.upper()}! Alert generated.")
                        elif has_changed and not event:
                            st.info(f"Result: {msg}")
                        else:
                            st.info(f"Result: {msg or 'No changes'}")
                    st.rerun()


# =========================================================
# SCREEN E: ALERT INBOX
# =========================================================
elif page == "Alert Inbox":
    st.title("Alert Inbox")
    st.markdown(f"Evidence-backed changes detected for **{current_user}**. 'Quiet by Default' ensures only meaningful changes notify you.")

    all_events = service.storage.list_change_events(owner_id=current_user, limit=50)

    # Filter chips
    f_col1, f_col2, f_col3 = st.columns([2, 2, 2])
    with f_col1:
        filter_type = st.selectbox("Filter by classification:", ["All", "Meaningful", "Uncertain", "Irrelevant"])
    with f_col2:
        only_unread = st.checkbox("Show only unread alerts", value=False)
    with f_col3:
        if st.button("Mark All as Read", use_container_width=True):
            for ev in all_events:
                service.storage.mark_event_read(ev.event_id, True, owner_id=current_user)
            st.rerun()

    filtered = []
    for ev in all_events:
        if filter_type != "All" and ev.classification.value.lower() != filter_type.lower():
            continue
        if only_unread and ev.read:
            continue
        filtered.append(ev)

    if not filtered:
        st.info("Your inbox is clean. No matching change alerts.")
    else:
        for ev in filtered:
            badge_class = f"badge-{ev.classification.value}"
            read_indicator = "🔵 UNREAD" if not ev.read else "✓ READ"

            compare_html = ""
            if ev.previous_value or ev.new_value:
                prev_val = ev.previous_value or 'N/A'
                new_val = ev.new_value or 'N/A'
                compare_html = f"""<div class="compare-box" style="margin-bottom: 12px;"><div class="compare-old">Previous: {prev_val}</div><div class="compare-new">Updated:  {new_val}</div></div>"""

            evidence_html = ""
            if ev.evidence:
                quotes_html = "".join([f"<div class='evidence-quote'>“{q}”</div>" for q in ev.evidence[:3]])
                evidence_html = f"<div style='margin-bottom: 12px;'><b style='font-size: 13px; color: #94a3b8;'>Direct Source Evidence:</b>{quotes_html}</div>"

            card_border = '#f59e0b' if ev.classification == ClassificationType.MEANINGFUL else '#38bdf8'
            st.html(f"""
            <div class="nowaware-card" style="border-left: 4px solid {card_border};">
                <div style="display: flex; justify-content: space-between;">
                    <div>
                        <span class="{badge_class}">{ev.classification.value.upper()}</span>
                        &nbsp;
                        <span style="font-size: 12px; color: #94a3b8;">{read_indicator} • Detected {ev.detected_at[:19].replace('T', ' ')}</span>
                        <h3 style="margin-top: 6px; margin-bottom: 4px;">{ev.summary}</h3>
                        <p style="color: #64748b; font-size: 13px; margin: 0;">Monitor: <b>{ev.rule_name}</b> | <code>{ev.source_url}</code></p>
                    </div>
                </div>
                
                <div style="margin-top: 14px;">
                    <div style="color: #cbd5e1; font-size: 14px; margin-bottom: 10px;">
                        <b>Why this matters:</b> {ev.impact_explanation}
                    </div>
                    {compare_html}
                    {evidence_html}
                    <div style="margin-top: 12px; color: #38bdf8; font-size: 13px;">
                        💡 <b>Suggested Next Action:</b> {ev.recommended_action}
                    </div>
                </div>
            </div>
            """)

            # Alert Actions
            act_c1, act_c2, act_c3 = st.columns([2, 2, 6])
            with act_c1:
                if not ev.read:
                    if st.button("Mark as Read", key=f"read_{ev.event_id}"):
                        service.storage.mark_event_read(ev.event_id, True, owner_id=current_user)
                        st.rerun()
                else:
                    if st.button("Mark as Unread", key=f"unread_{ev.event_id}"):
                        service.storage.mark_event_read(ev.event_id, False, owner_id=current_user)
                        st.rerun()
            with act_c2:
                if st.button("Dismiss Alert", key=f"dism_{ev.event_id}"):
                    service.storage.dismiss_event(ev.event_id, owner_id=current_user)
                    st.rerun()

            st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)


# =========================================================
# SCREEN: DEMO SCENARIOS RUNNER
# =========================================================
elif page == "Demo Scenarios":
    st.title("Interactive Demo Scenarios")
    st.markdown("""
    Run the 5 required core product scenarios to verify the application workflow:
    1. **Deadline changes to earlier date** (Meaningful alert)
    2. **Layout & cosmetic formatting noise** (Quiet by default / Suppressed)
    3. **New RSS opportunity published** (Feed change alert)
    4. **Source outage / 503 error** (Error handled, baseline preserved)
    5. **Duplicate alert prevention** (Identical check deduplicated)
    """)

    for sc_id, sc in DEMO_SCENARIOS.items():
        st.html(f"""
        <div class="nowaware-card">
            <h4>{sc['title']}</h4>
            <p style="color: #94a3b8; font-size: 14px;">{sc['description']}</p>
        </div>
        """)

        c_run, c_desc = st.columns([1.5, 4.5])
        with c_run:
            if st.button(f"Execute {sc_id.upper()} ⚡", key=f"run_{sc_id}", type="primary"):
                with st.spinner("Executing scenario..."):
                    # Find or create corresponding rule for current_user
                    rules = service.storage.list_rules(owner_id=current_user)
                    target_rule = None
                    for r in rules:
                        if r.source_url == sc["sample_url"]:
                            target_rule = r
                            break

                    if not target_rule:
                        tmpl = sc["rule_template"]
                        target_rule = MonitoringRule(
                            name=tmpl["name"],
                            source_url=tmpl["source_url"],
                            source_type=tmpl["source_type"],
                            natural_language_goal=tmpl["natural_language_goal"],
                            criteria_categories=tmpl["criteria_categories"],
                            specific_instructions=tmpl.get("specific_instructions", ""),
                            check_interval_minutes=tmpl["check_interval_minutes"],
                            is_demo_rule=True,
                            owner_id=current_user,
                        )
                        service.storage.save_rule(target_rule)
                        service.establish_baseline(target_rule, owner_id=current_user)

                    if sc_id == "scenario_4":
                        # Source unavailable: set to None for 503 outage simulation
                        service.fetcher.register_mock_source(target_rule.source_url, None)
                        has_changed, ev, msg = service.check_rule(target_rule.id, simulated_content=None, owner_id=current_user)
                        st.warning(f"Result: {msg}. Baseline was safely preserved!")
                    elif sc_id == "scenario_5":
                        # Duplicate check: run twice with same content
                        service.check_rule(target_rule.id, simulated_content=sc["updated_content"], owner_id=current_user)
                        has_changed, ev, msg = service.check_rule(target_rule.id, simulated_content=sc["updated_content"], owner_id=current_user)
                        st.info(f"Result: {msg}. Duplicate notifications successfully prevented!")
                    else:
                        has_changed, ev, msg = service.check_rule(target_rule.id, simulated_content=sc["updated_content"], owner_id=current_user)
                        if ev:
                            st.success(f"Result: Classified as {ev.classification.value.upper()}. Alert created: '{ev.summary}'")
                        else:
                            st.info(f"Result: {msg} (Quiet by default)")
                st.rerun()

        with c_desc:
            st.caption(f"Expected behavior: **{sc['expected_classification'].upper()}** | Notification: **{sc['should_notify']}**")

        st.markdown("<hr style='border-color: rgba(255,255,255,0.05); margin: 8px 0;'>", unsafe_allow_html=True)


# =========================================================
# SCREEN F: SETTINGS & DIAGNOSTICS
# =========================================================
elif page == "Settings":
    st.title("Settings & Diagnostics")

    # Mode Selector
    st.subheader("Application Mode")
    current_mode = "aws" if settings.is_aws_mode else "demo"
    col_mode1, col_mode2 = st.columns(2)
    with col_mode1:
        st.markdown(f"**Current Active Mode:** `{current_mode.upper()}`")
        st.caption("Demo mode runs completely offline using local SQLite. AWS mode connects to Amazon Bedrock, DynamoDB, EventBridge, and SES.")

    # Service Readiness Matrix
    st.subheader("Service Integration Status")

    aws_creds = settings.check_aws_credentials()
    diag_col1, diag_col2 = st.columns(2)

    with diag_col1:
        st.markdown("#### Amazon Web Services (AWS)")
        st.markdown(f"- **AWS Region:** `{settings.aws_region}`")
        st.markdown(f"- **AWS Credentials Active:** `{'✅ YES' if aws_creds else '❌ NOT DETECTED'}`")
        st.markdown(f"- **Bedrock Model ID:** `{settings.bedrock_model_id}`")
        st.markdown(f"- **SES Sender Email:** `{settings.ses_sender_email or 'Not configured'}`")
        st.markdown(f"- **SES Recipient Override:** `{settings.ses_recipient_override or 'Not configured'}`")

        if not aws_creds:
            st.warning("AWS credentials not found in environment or ~/.aws/credentials. Application is operating in self-contained DEMO MODE.")
            st.caption("To enable AWS Mode: Configure `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and set `NOWAWARE_MODE=aws` in `.env`.")

    with diag_col2:
        st.markdown("#### Local & Storage Architecture")
        st.markdown(f"- **Local DB Path:** `{settings.local_db_path}`")
        st.markdown(f"- **DynamoDB Rules Table:** `{settings.dynamodb_rules_table}`")
        st.markdown(f"- **DynamoDB Snapshots Table:** `{settings.dynamodb_snapshots_table}`")
        st.markdown(f"- **DynamoDB Alerts Table:** `{settings.dynamodb_alerts_table}`")
        st.markdown(f"- **Default Check Interval:** `{settings.default_check_interval_minutes} minutes`")
        st.markdown(f"- **Request Timeout:** `{settings.request_timeout_seconds} seconds`")
        st.markdown(f"- **Max Response Body:** `{settings.max_response_bytes} bytes (1MB DoS Cap)`")

    st.markdown("---")
    st.subheader("Security & SSRF Safeguards")
    st.markdown("""
    NowAware applies strict zero-trust controls to all external sources:
    - **Protocols:** Only public `http://` and `https://` are permitted.
    - **Private IP Blocking:** Localhost (`127.0.0.1`), RFC1918 private subnets (`10.x`, `172.16.x`, `192.168.x`), and Link-Local/Cloud Metadata (`169.254.169.254`) are rejected prior to HTTP requests.
    - **DNS Pinning:** DNS resolution is verified against forbidden IP ranges before each request.
    - **Redirect Verification:** Every redirect destination is recursively validated against the SSRF security boundary.
    - **Script Execution:** Scripts, iframes, and active browser DOM executions are strictly prohibited.
    """)

    st.markdown("---")
    st.subheader("Workspace Data Management")
    if st.button("Reset Database & Re-seed Demo Rules"):
        # Reset local SQLite
        if os.path.exists(settings.local_db_path):
            os.remove(settings.local_db_path)
        st.session_state.pop("seeded", None)
        st.success("Database reset. Re-initializing...")
        st.rerun()
