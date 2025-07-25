frappe.listview_settings['Site daily report'] = {
    onload: function(listview) {
        listview.page.add_inner_button(__('Generate Weekly Report'), function() {
            frappe.prompt([
                {
                    fieldname: 'site',
                    label: __('Site'),
                    fieldtype: 'Link',
                    options: 'Site',
                    reqd: 1
                },
                {
                    fieldname: 'date',
                    label: __('Reference Date (any day in week)'),
                    fieldtype: 'Date',
                    reqd: 1,
                    default: frappe.datetime.get_today()
                }
            ], function(values) {
                frappe.call({
                    method: 'healthcare.healthcare.doctype.site_weekly_report.site_weekly_report.generate_weekly_report_for_site_and_date',
                    args: {
                        site: values.site,
                        date: values.date
                    },
                    callback: function(r) {
                        if (r.message) {
                            frappe.set_route('Form', 'Site Weekly Report', r.message);
                        } else {
                            frappe.msgprint(__('Weekly report generated/updated.'));
                        }
                    }
                });
            }, __('Generate Weekly Report'), __('Generate'));
        });
    }
}; 