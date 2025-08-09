# Copyright (c) 2025, earthians Health Informatics Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document
import frappe
from frappe import _
from datetime import timedelta


class SiteGeneralWeeklyReport(Document):
    pass


def aggregate_site_weekly_report(week_start, week_end):
    daily_reports = frappe.get_all(
        "Site daily report",
        filters={"date": ["between", [week_start, week_end]]},
        fields=["*"],
    )
    if not daily_reports:
        frappe.logger().info(
            f"No daily reports found for week between {week_start} and {week_end}"
        )
        return None
    # Aggregate child tables using correct fieldnames
    total_consultation = 0
    total_medevac = 0
    total_fatality = 0
    total_fit_and_back_to_work = 0
    total_not_fit_hse = 0
    other_activities = ""
    training_drill = []
    inspection = []
    customer_complaints = []
    sites = ""

    for d in daily_reports:
        total_consultation += d["total_consultation"]
        total_medevac += d["medevac"]
        total_fatality += d["fatality"]
        total_fit_and_back_to_work += d["fitted_and_back_to_work"]
        total_not_fit_hse += d["not_fit_hse"]
        if not other_activities:
            other_activities = "<h4>Comments for daily report on {0} for site {1}</h4>".format(
                d["date"], d["site_name"]
            )
        else:
            other_activities += "<h4>Comments for daily report on {0} for site {1}</h4>".format(
                d["date"], d["site_name"]
            )
        other_activities += d["others"]

        if sites == "":
            sites = d.get("site_name")
        else:
            sites += ", " + d.get("site_name")
        t_rows = frappe.get_all(
            "Training",
            filters={"parent": d["name"], "parenttype": "Site daily report"},
            fields=["*"],
        )
        i_rows = frappe.get_all(
            "Inspection",
            filters={
                "parent": d["name"],
                "parentfield": "table_dfbm",
                "parenttype": "Site daily report",
            },
            fields=["*"],
        )
        c_rows = frappe.get_all(
            "Customer complaints",
            filters={"parent": d["name"], "parenttype": "Site daily report"},
            fields=["*"],
        )
        frappe.logger().info(
            f"Aggregating for daily report {d['name']}: Training={t_rows}, Inspection={i_rows}, CustomerComplaints={c_rows}"
        )
        training_drill.extend(t_rows)
        inspection.extend(i_rows)
        customer_complaints.extend(c_rows)
    return {
        "site": sites,
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


def day_of_last_week(today=None, day_of_week=4):
    if today is None:
        today = frappe.utils.getdate()
    weekday = today.weekday()

    if weekday >= 5:
        days_since_friday = weekday - day_of_week + 7
    else:
        days_since_friday = (weekday - day_of_week) % 7 or 7

    return today - timedelta(days=days_since_friday)


@frappe.whitelist()
def generate_weekly_reports_for_today(generate_for_last_week=False):
    if generate_for_last_week:
        # If the user wants to generate for last week, we assume they are running this on a Friday
        # and we will generate the report for the week ending today (last Friday)
        today = frappe.utils.getdate()
        weekday = today.weekday()
    today = frappe.utils.getdate()
    # Find last Friday (week start)
    weekday = today.weekday()
    # is it friday?
    if weekday != 4 and not generate_for_last_week:
        # If today is not Friday, we cannot generate a weekly report
        frappe.msgprint(
            _(
                "Today is not Friday. Please run this on Friday at 12:00 PM to generate weekly reports."
            ),
            alert=True,
            indicator="yellow",
        )
        # Return True so as to prompt the user to run this for last week
        return {
            "prompt": True,
            "week_start": day_of_last_week(day_of_week=4, today=today),
            "week_end": day_of_last_week(day_of_week=4, today=today)
            + timedelta(days=6),
        }
    week_start = day_of_last_week(day_of_week=4, today=today)
    week_end = week_start + timedelta(days=6)
    data = aggregate_site_weekly_report(week_start, week_end)
    if not data:
        frappe.msgprint(
            _("No daily reports found between {0} and {1}").format(
                week_start, week_end
            ),
            alert=True,
            indicator="red",
        )
        return
    existing = frappe.db.exists(
        "Site General Weekly Report",
        {"week_start_date": week_start, "week_end_date": week_end},
    )
    if existing:
        frappe.msgprint(
            _(
                "Weekly report already exists for week starting {0} and end at {1}"
            ).format(week_start, week_end),
            alert=True,
            indicator="orange",
        )
        return
    else:
        doc = frappe.get_doc({"doctype": "Site General Weekly Report", **data})
        try:
            doc.insert(ignore_permissions=True)
        except Exception as e:
            frappe.msgprint(
                _("Error creating weekly report: {0}").format(str(e)),
                alert=True,
                indicator="red",
            )
            return
        if doc.docstatus == 0:
            doc.submit()
