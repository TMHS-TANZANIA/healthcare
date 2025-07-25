// Copyright (c) 2025, earthians Health Informatics Pvt. Ltd. and contributors
// For license information, please see license.txt

// frappe.ui.form.on("Site daily report", {
// 	refresh(frm) {

// 	},
// });

frappe.ui.form.on("Site daily report", {
    refresh(frm) {
        if (frm.doc.docstatus === 1 && frm.doc.site_name && frm.doc.date) {
            frm.add_custom_button(
                __("Generate Weekly Report"),
                function () {
                    frappe.call({
                        method: "healthcare.healthcare.doctype.site_weekly_report.site_weekly_report.generate_weekly_report_for_site_and_date",
                        args: {
                            site: frm.doc.site_name,
                            date: frm.doc.date
                        },
                        callback: function(r) {
                            if (r.message) {
                                frappe.set_route("Form", "Site Weekly Report", r.message);
                            } else {
                                frappe.msgprint(__("Weekly report generated/updated."));
                            }
                        }
                    });
                },
                __("Actions")
            );
        }
    }
});

