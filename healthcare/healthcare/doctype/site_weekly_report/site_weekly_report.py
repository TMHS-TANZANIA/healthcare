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
        fields=["name", "total_consultation", "medevac", "fatality", "fitted_and_back_to_work", "not_fit_hse", "others"],
    )
    if not daily_reports:
        return None
    # Aggregate fields
    total_consultation = sum(d["total_consultation"] for d in daily_reports)
    total_medevac = sum(d["medevac"] for d in daily_reports)
    total_fatality = sum(d["fatality"] for d in daily_reports)
    total_fit_and_back_to_work = sum(d["fitted_and_back_to_work"] for d in daily_reports)
    total_not_fit_hse = sum(d["not_fit_hse"] for d in daily_reports)
    # Aggregate comments
    other_activities = "\n".join([d["others"] for d in daily_reports if d.get("others")])
    # Aggregate child tables using correct fieldnames
    training_drill = []
    inspection = []
    customer_complaints = []
    for d in daily_reports:
        training_drill.extend(frappe.get_all(
            "Training",
            filters={"parent": d["name"], "parenttype": "Site daily report"},
            fields=["*"],
        ))
        inspection.extend(frappe.get_all(
            "Inspection",
            filters={"parent": d["name"], "parentfield": "table_dfbm", "parenttype": "Site daily report"},
            fields=["*"],
        ))
        customer_complaints.extend(frappe.get_all(
            "Customer complaints",
            filters={"parent": d["name"], "parenttype": "Site daily report"},
            fields=["*"],
        ))
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
        "other_activities": other_activities,
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

@frappe.whitelist()
def generate_weekly_reports_for_today():
    today = frappe.utils.getdate()
    # Find last Friday (week start)
    weekday = today.weekday()
    days_since_friday = (weekday - 4) % 7
    if days_since_friday == 0:
        # Today is Friday, so go back 7 days for last Friday
        week_start = today - timedelta(days=7)
    else:
        week_start = today - timedelta(days=days_since_friday)
    week_end = week_start + timedelta(days=6)
    sites = frappe.get_all("Site", pluck="name")
    for site in sites:
        data = aggregate_site_weekly_report(site, week_start, week_end)
        if not data:
            continue
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
        else:
            doc = frappe.get_doc({"doctype": "Site Weekly Report", **data})
            doc.insert(ignore_permissions=True) 