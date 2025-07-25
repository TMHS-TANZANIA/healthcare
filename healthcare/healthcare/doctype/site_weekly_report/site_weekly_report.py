# Copyright (c) 2025, earthians Health Informatics Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from datetime import timedelta
from frappe import _

class SiteWeeklyReport(Document):
    pass

def get_week_range(reference_date):
    # Friday=4, so find the most recent Friday
    weekday = reference_date.weekday()
    days_since_friday = (weekday - 4) % 7
    week_start = reference_date - timedelta(days=days_since_friday)
    week_end = week_start + timedelta(days=6)
    return week_start, week_end

def aggregate_site_weekly_report(site, week_start, week_end):
    daily_reports = frappe.get_all(
        "Site daily report",
        filters={
            "site_name": site,
            "date": ["between", [week_start, week_end]]
        },
        fields=["name", "total_consultation", "medevac", "fatality", "fitted_and_back_to_work", "not_fit_hse"],
    )
    if not daily_reports:
        return None
    # Aggregate fields
    total_consultation = sum(d["total_consultation"] for d in daily_reports)
    total_medevac = sum(d["medevac"] for d in daily_reports)
    total_fatality = sum(d["fatality"] for d in daily_reports)
    total_fit_and_back_to_work = sum(d["fitted_and_back_to_work"] for d in daily_reports)
    total_not_fit_hse = sum(d["not_fit_hse"] for d in daily_reports)

    # Aggregate child tables
    training_drill = []
    inspection = []
    customer_complaints = []
    team_on_site = []
    for d in daily_reports:
        doc = frappe.get_doc("Site daily report", d["name"])
        training_drill.extend([row.as_dict() for row in doc.training_drill])
        if hasattr(doc, "table_dfbm"):
            inspection.extend([row.as_dict() for row in doc.table_dfbm])
        if hasattr(doc, "customer_complaints"):
            customer_complaints.extend([row.as_dict() for row in doc.customer_complaints])
        if hasattr(doc, "team_on_site"):
            team_on_site.extend([row.as_dict() for row in doc.team_on_site])

    return {
        "site": site,
        "week_start_date": week_start,
        "week_end_date": week_end,
        "total_consultation": total_consultation,
        "total_medevac": total_medevac,
        "total_fatality": total_fatality,
        "total_fit_and_back_to_work": total_fit_and_back_to_work,
        "total_not_fit_hse": total_not_fit_hse,
        "training_drill": training_drill,
        "inspection": inspection,
        "customer_complaints": customer_complaints,
        "team_on_site": team_on_site,
    }

def generate_weekly_reports():
    today = frappe.utils.getdate()
    week_start, week_end = get_week_range(today - timedelta(days=1))
    sites = frappe.get_all("Site", pluck="name")
    for site in sites:
        data = aggregate_site_weekly_report(site, week_start, week_end)
        if not data:
            continue
        # Create or update the weekly report
        doc = frappe.get_doc({"doctype": "Site Weekly Report", **data})
        doc.save(ignore_permissions=True)

@frappe.whitelist()
def generate_weekly_report_for_site_and_date(site, date):
    import datetime
    date = frappe.utils.getdate(date)
    week_start, week_end = get_week_range(date)
    data = aggregate_site_weekly_report(site, week_start, week_end)
    if not data:
        frappe.throw(_("No daily reports found for this site and week."))
    # Check if a weekly report already exists
    existing = frappe.db.exists("Site Weekly Report", {
        "site": site,
        "week_start_date": week_start,
        "week_end_date": week_end
    })
    if existing:
        doc = frappe.get_doc("Site Weekly Report", existing)
        for k, v in data.items():
            doc.set(k, v)
        doc.save(ignore_permissions=True)
        return doc.name
    else:
        doc = frappe.get_doc({"doctype": "Site Weekly Report", **data})
        doc.insert(ignore_permissions=True)
        return doc.name 