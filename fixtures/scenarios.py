"""Demo Fixtures and Scenarios for NowAware."""

from typing import Dict, Any, List
from src.schemas.monitoring import MonitoringRule, SourceType, RuleStatus


# Baseline contents
SCHOLARSHIP_BASELINE = """<!DOCTYPE html>
<html>
<head><title>STEM Global Leadership Scholarship 2026</title></head>
<body>
  <div class="nav-bar">Home | About | Contact</div>
  <h1>STEM Global Leadership Scholarship Program</h1>
  <p class="announcement">Applications are currently accepted for the upcoming academic cycle.</p>
  <div class="card">
    <h3>Eligibility Requirements</h3>
    <ul>
      <li>Undergraduate or graduate students in Computer Science or Mathematics.</li>
      <li>Minimum cumulative GPA of 3.5 on a 4.0 scale.</li>
      <li>Demonstrated leadership in university student organizations.</li>
    </ul>
    <h3>Important Dates</h3>
    <p>Application Deadline: May 15, 2026 at 11:59 PM EST</p>
    <p>Award Amount: $15,000 per recipient</p>
    <p>Award Announcement Date: July 1, 2026</p>
  </div>
  <footer>Copyright &copy; 2025 STEM Education Foundation. All rights reserved.</footer>
</body>
</html>"""

# Scenario 1: Deadline changes to earlier date (May 15 -> April 10)
SCHOLARSHIP_EARLIER_DEADLINE = """<!DOCTYPE html>
<html>
<head><title>STEM Global Leadership Scholarship 2026</title></head>
<body>
  <div class="nav-bar">Home | About | Contact</div>
  <h1>STEM Global Leadership Scholarship Program</h1>
  <p class="announcement">URGENT UPDATE: Due to high applicant volume, deadlines have been adjusted.</p>
  <div class="card">
    <h3>Eligibility Requirements</h3>
    <ul>
      <li>Undergraduate or graduate students in Computer Science or Mathematics.</li>
      <li>Minimum cumulative GPA of 3.5 on a 4.0 scale.</li>
      <li>Demonstrated leadership in university student organizations.</li>
    </ul>
    <h3>Important Dates</h3>
    <p>Application Deadline: April 10, 2026 at 11:59 PM EST</p>
    <p>Award Amount: $15,000 per recipient</p>
    <p>Award Announcement Date: July 1, 2026</p>
  </div>
  <footer>Copyright &copy; 2025 STEM Education Foundation. All rights reserved.</footer>
</body>
</html>"""

# Scenario 2: Layout and copyright changes, but substantive content unchanged
SCHOLARSHIP_LAYOUT_ONLY = """<!DOCTYPE html>
<html>
<head><title>STEM Global Leadership Scholarship 2026</title></head>
<body class="modern-theme-dark">
  <div class="redesigned-nav">Navigation Menu | Search | Portals</div>
  <div class="hero-banner"><img src="/banner_new.png" /></div>
  <h1>STEM Global Leadership Scholarship Program</h1>
  <p class="announcement">Applications are currently accepted for the upcoming academic cycle.</p>
  <section class="new-grid-layout">
    <h3>Eligibility Requirements</h3>
    <ul>
      <li>Undergraduate or graduate students in Computer Science or Mathematics.</li>
      <li>Minimum cumulative GPA of 3.5 on a 4.0 scale.</li>
      <li>Demonstrated leadership in university student organizations.</li>
    </ul>
    <h3>Important Dates</h3>
    <p>Application Deadline: May 15, 2026 at 11:59 PM EST</p>
    <p>Award Amount: $15,000 per recipient</p>
    <p>Award Announcement Date: July 1, 2026</p>
  </section>
  <footer class="cookie-notice">We use cookies to improve experience. Accept all cookies.</footer>
  <footer>Copyright &copy; 2026 STEM Education Foundation. All rights reserved. Built with v2.4.</footer>
</body>
</html>"""

# RSS Feed Baseline
RESEARCH_FEED_BASELINE = """<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0">
<channel>
  <title>Clean Energy Research Grants &amp; Announcements</title>
  <link>https://cleanenergy.example.gov/feed</link>
  <description>Official funding announcements and call for proposals</description>
  <item>
    <title>FY26 Community Solar Deployment Award</title>
    <link>https://cleanenergy.example.gov/grants/solar-2026</link>
    <guid>grant-solar-101</guid>
    <pubDate>Mon, 02 Feb 2026 10:00:00 GMT</pubDate>
    <description>Funding available for regional municipal solar microgrids up to $500,000.</description>
  </item>
</channel>
</rss>"""

# Scenario 3: Feed publishes new relevant entry
RESEARCH_FEED_NEW_ENTRY = """<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0">
<channel>
  <title>Clean Energy Research Grants &amp; Announcements</title>
  <link>https://cleanenergy.example.gov/feed</link>
  <description>Official funding announcements and call for proposals</description>
  <item>
    <title>NEW CALL: Next-Gen Hydrogen Storage Innovation Grant ($2,000,000)</title>
    <link>https://cleanenergy.example.gov/grants/hydrogen-2026</link>
    <guid>grant-hydrogen-102</guid>
    <pubDate>Tue, 10 Mar 2026 14:30:00 GMT</pubDate>
    <description>Open solicitation for academic and laboratory consortia developing solid-state hydrogen storage technologies.</description>
  </item>
  <item>
    <title>FY26 Community Solar Deployment Award</title>
    <link>https://cleanenergy.example.gov/grants/solar-2026</link>
    <guid>grant-solar-101</guid>
    <pubDate>Mon, 02 Feb 2026 10:00:00 GMT</pubDate>
    <description>Funding available for regional municipal solar microgrids up to $500,000.</description>
  </item>
</channel>
</rss>"""

# Scenario Definitions
DEMO_SCENARIOS = {
    "scenario_1": {
        "id": "scenario_1",
        "title": "Scenario 1: Critical Deadline Change (May 15 → April 10)",
        "description": "The foundation moves up the application deadline. NowAware detects this meaningful change, cites direct before/after evidence, and creates a high-priority alert.",
        "expected_classification": "meaningful",
        "should_notify": True,
        "sample_url": "mock://foundation.org/scholarship",
        "baseline_content": SCHOLARSHIP_BASELINE,
        "updated_content": SCHOLARSHIP_EARLIER_DEADLINE,
        "rule_template": {
            "name": "STEM Scholarship Deadline",
            "source_url": "mock://foundation.org/scholarship",
            "source_type": SourceType.HTML,
            "natural_language_goal": "Watch this scholarship announcement and alert me if the deadline changes.",
            "criteria_categories": ["Important dates and deadlines"],
            "specific_instructions": "deadline, due date, submission cutoff",
            "check_interval_minutes": 30,
        },
    },
    "scenario_2": {
        "id": "scenario_2",
        "title": "Scenario 2: Cosmetic Layout & Footer Noise (Suppressed)",
        "description": "The webpage changes its layout framework, CSS classes, cookie disclaimer, and copyright year (2025 to 2026). Substantive deadlines remain untouched. NowAware suppresses alerts ('Quiet by Default').",
        "expected_classification": "irrelevant",
        "should_notify": False,
        "sample_url": "mock://foundation.org/scholarship",
        "baseline_content": SCHOLARSHIP_BASELINE,
        "updated_content": SCHOLARSHIP_LAYOUT_ONLY,
        "rule_template": {
            "name": "STEM Scholarship Deadline",
            "source_url": "mock://foundation.org/scholarship",
            "source_type": SourceType.HTML,
            "natural_language_goal": "Watch this scholarship announcement and alert me if the deadline changes.",
            "criteria_categories": ["Important dates and deadlines"],
            "specific_instructions": "deadline",
            "check_interval_minutes": 30,
        },
    },
    "scenario_3": {
        "id": "scenario_3",
        "title": "Scenario 3: New RSS Grant Announcement Published",
        "description": "An official agency RSS feed releases a brand new $2M hydrogen grant opportunity. NowAware detects the new entry, parses the title and grant summary, and notifies the user.",
        "expected_classification": "meaningful",
        "should_notify": True,
        "sample_url": "mock://cleanenergy.gov/feed.xml",
        "baseline_content": RESEARCH_FEED_BASELINE,
        "updated_content": RESEARCH_FEED_NEW_ENTRY,
        "rule_template": {
            "name": "Clean Energy Funding Feed",
            "source_url": "mock://cleanenergy.gov/feed.xml",
            "source_type": SourceType.RSS,
            "natural_language_goal": "Track this RSS feed for new opportunities and grants relevant to energy innovation.",
            "criteria_categories": ["New announcements", "Price, fees, or numerical values"],
            "specific_instructions": "hydrogen, grant, funding, solicitation",
            "check_interval_minutes": 15,
        },
    },
    "scenario_4": {
        "id": "scenario_4",
        "title": "Scenario 4: Source Unavailability / HTTP 503 Outage",
        "description": "A public website crashes with an HTTP 503 error. NowAware records a retrieval error, increments consecutive failures, and preserves the previous baseline without falsely claiming the source was unchanged.",
        "expected_classification": "error",
        "should_notify": False,
        "sample_url": "mock://unstable-source.gov/notices",
        "baseline_content": "<h1>Notice Board</h1><p>System operational</p>",
        "updated_content": None,  # Simulates network/HTTP failure
        "rule_template": {
            "name": "Public Notice Board",
            "source_url": "mock://unstable-source.gov/notices",
            "source_type": SourceType.HTML,
            "natural_language_goal": "Monitor this notice board for regulation changes.",
            "criteria_categories": ["Eligibility or requirements"],
            "check_interval_minutes": 30,
        },
    },
    "scenario_5": {
        "id": "scenario_5",
        "title": "Scenario 5: Duplicate Alert Prevention / Deduplication",
        "description": "Two consecutive checks detect the exact same modified content. NowAware recognizes the change fingerprint, preserves data integrity, and prevents sending repeat notifications to the user.",
        "expected_classification": "duplicate_suppressed",
        "should_notify": False,
        "sample_url": "mock://foundation.org/scholarship",
        "baseline_content": SCHOLARSHIP_BASELINE,
        "updated_content": SCHOLARSHIP_EARLIER_DEADLINE,
        "rule_template": {
            "name": "STEM Scholarship Deadline",
            "source_url": "mock://foundation.org/scholarship",
            "source_type": SourceType.HTML,
            "natural_language_goal": "Watch this scholarship announcement and alert me if the deadline changes.",
            "criteria_categories": ["Important dates and deadlines"],
            "check_interval_minutes": 30,
        },
    },
    "scenario_6_eligibility": {
        "id": "scenario_6_eligibility",
        "title": "Scenario 6: Meaningful Eligibility Criteria Change (GPA 3.5 -> 3.8)",
        "description": "The foundation raises the minimum cumulative GPA requirement from 3.5 to 3.8. Directly impacts qualification.",
        "expected_classification": "meaningful",
        "should_notify": True,
        "sample_url": "mock://foundation.org/scholarship",
        "baseline_content": SCHOLARSHIP_BASELINE,
        "updated_content": """<!DOCTYPE html>
<html>
<head><title>STEM Global Leadership Scholarship 2026</title></head>
<body>
  <h1>STEM Global Leadership Scholarship Program</h1>
  <div class="card">
    <h3>Eligibility Requirements</h3>
    <ul>
      <li>Undergraduate or graduate students in Computer Science or Mathematics.</li>
      <li>Minimum cumulative GPA of 3.8 on a 4.0 scale.</li>
      <li>Demonstrated leadership in university student organizations.</li>
    </ul>
    <h3>Important Dates</h3>
    <p>Application Deadline: May 15, 2026 at 11:59 PM EST</p>
    <p>Award Amount: $15,000 per recipient</p>
  </div>
  <footer>Copyright &copy; 2025 STEM Education Foundation.</footer>
</body>
</html>""",
        "rule_template": {
            "name": "STEM Scholarship Requirements",
            "source_url": "mock://foundation.org/scholarship",
            "source_type": SourceType.HTML,
            "natural_language_goal": "Alert me if eligibility requirements or minimum GPA change.",
            "criteria_categories": ["Eligibility or requirements"],
            "specific_instructions": "gpa, minimum, eligibility, requirements",
            "check_interval_minutes": 30,
        },
    },
    "scenario_7_ambiguous": {
        "id": "scenario_7_ambiguous",
        "title": "Scenario 7: Ambiguous Policy Phrasing without Specific Values",
        "description": "Vague mention of handbook schedule restructuring without explicit dates or fee values. Classified as UNCERTAIN, quiet by default.",
        "expected_classification": "uncertain",
        "should_notify": False,
        "sample_url": "mock://university.edu/guidelines",
        "baseline_content": "<h1>Student Guidelines</h1><p>General administrative policy remains standard.</p>",
        "updated_content": "<h1>Student Guidelines</h1><p>General administrative policy: The academic council reserves the right to amend handbook timing and restructuring schedule as deemed necessary.</p>",
        "rule_template": {
            "name": "Academic Guidelines Monitor",
            "source_url": "mock://university.edu/guidelines",
            "source_type": SourceType.HTML,
            "natural_language_goal": "Watch for substantive changes to calendar dates.",
            "criteria_categories": ["Important dates and deadlines"],
            "check_interval_minutes": 30,
        },
    },
    "scenario_8_misleading": {
        "id": "scenario_8_misleading",
        "title": "Scenario 8: Misleading Ad / Promotional Content Injection",
        "description": "An unrelated sponsored loan advertisement mentioning 'March 1 loan deadline' is injected into a sidebar, while the scholarship dates are unchanged. NowAware must not falsely trigger an alert on the scholarship.",
        "expected_classification": "irrelevant",
        "should_notify": False,
        "sample_url": "mock://foundation.org/scholarship",
        "baseline_content": SCHOLARSHIP_BASELINE,
        "updated_content": """<!DOCTYPE html>
<html>
<head><title>STEM Global Leadership Scholarship 2026</title></head>
<body>
  <div class="sponsored-sidebar">
    <p>Sponsored Promotion: Get Student Loans Today! Urgent deadline for loan discounts ends March 1!</p>
  </div>
  <div class="nav-bar">Home | About | Contact</div>
  <h1>STEM Global Leadership Scholarship Program</h1>
  <p class="announcement">Applications are currently accepted for the upcoming academic cycle.</p>
  <div class="card">
    <h3>Eligibility Requirements</h3>
    <ul>
      <li>Undergraduate or graduate students in Computer Science or Mathematics.</li>
      <li>Minimum cumulative GPA of 3.5 on a 4.0 scale.</li>
      <li>Demonstrated leadership in university student organizations.</li>
    </ul>
    <h3>Important Dates</h3>
    <p>Application Deadline: May 15, 2026 at 11:59 PM EST</p>
    <p>Award Amount: $15,000 per recipient</p>
    <p>Award Announcement Date: July 1, 2026</p>
  </div>
  <footer>Copyright &copy; 2025 STEM Education Foundation. All rights reserved.</footer>
</body>
</html>""",
        "rule_template": {
            "name": "STEM Scholarship Deadline",
            "source_url": "mock://foundation.org/scholarship",
            "source_type": SourceType.HTML,
            "natural_language_goal": "Watch this scholarship announcement and alert me if the application deadline changes.",
            "criteria_categories": ["Important dates and deadlines"],
            "specific_instructions": "application deadline",
            "check_interval_minutes": 30,
        },
    },
}
