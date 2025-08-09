// Copyright (c) 2025, earthians Health Informatics Pvt. Ltd. and contributors
// For license information, please see license.txt

// frappe.ui.form.on("", {
// 	refresh(frm) {

// 	},
// });
frappe.listview_settings['Site General Weekly Report'] = {
    onload: function (listview) {
        listview.page.add_inner_button(__('Generate for this Week'), function () {
            frappe.call({
                method: 'healthcare.healthcare.doctype.site_general_weekly_report.site_general_weekly_report.generate_weekly_reports_for_today',
                callback: function (r) {
                    let promptValue = r.message.prompt;
                    let week_start = r.message.week_start;
                    let week_end = r.message.week_end;
                    console.log(promptValue);
                    if (promptValue) {
                        frappe.prompt({
                            fieldname: 'generate_for_last_week',
                            label: __('Generate for Last Week'),
                            fieldtype: 'Check',
                            default: 1,
                            description: __(`Do you want to generate the report for last week? (${week_start} to ${week_end})`,),
                        }, function (values) {
                            frappe.call({
                                method: 'healthcare.healthcare.doctype.site_general_weekly_report.site_general_weekly_report.generate_weekly_reports_for_today',
                                args: {
                                    generate_for_last_week: values.generate_for_last_week
                                },
                                callback: function (response) {
                                    frappe.show_alert({
                                        message: __('Weekly reports generated successfully.'),
                                        indicator: 'green'
                                    });

                                }
                            });
                        });
                    } else {
                        frappe.show_alert({
                            message: __('Weekly reports generated successfully.'),
                            indicator: 'green'
                        });
                    }
                }
            });
        });
    }
}; 