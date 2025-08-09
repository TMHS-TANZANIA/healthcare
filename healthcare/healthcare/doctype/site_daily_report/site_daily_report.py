# Copyright (c) 2025, earthians Health Informatics Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _
from datetime import timedelta


class Sitedailyreport(Document):
    def before_insert(self):
        self.set(
            "expired_date_time", frappe.utils.now_datetime() + timedelta(days=1)
        )


@frappe.whitelist()
def return_for_edit(docs):
    if isinstance(docs, str):
        import json

        docs = json.loads(docs)

    for name in docs:
        doc = frappe.get_doc("Site daily report", name)

        if "Site Report Manager" not in frappe.get_roles(frappe.session.user):
            frappe.throw(_("You are not authorized to perform this action."))

        doc.set(
            "expired_date_time", frappe.utils.now_datetime() + timedelta(days=1)
        )
        doc.save()
        frappe.db.commit()
