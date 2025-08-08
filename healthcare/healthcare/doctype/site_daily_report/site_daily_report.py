import frappe
from frappe.model.document import Document
from frappe import _

class SiteDailyReport(Document):
    pass

@frappe.whitelist()
def return_for_edit(docs):
    if isinstance(docs, str):
        import json
        docs = json.loads(docs)

    for name in docs:
        doc = frappe.get_doc("site daily report", name)

        # Check if user has Manager role
        if "Site Report Manager" not in frappe.get_roles(frappe.session.user):
            frappe.throw(_("You are not authorized to perform this action."))

        # Only allow if submitted
        if doc.docstatus == 1:
            doc.docstatus = 0  # Draft
            doc.save(ignore_permissions=True)
            frappe.db.commit()
        else:
            frappe.msgprint(_("Document {0} is not submitted.").format(name))