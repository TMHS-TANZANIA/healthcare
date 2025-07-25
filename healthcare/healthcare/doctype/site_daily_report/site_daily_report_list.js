frappe.listview_settings['Site daily report'] = {
    onload: function(listview) {
        listview.page.add_inner_button(__('Generate Weekly Reports (All Sites)'), function() {
            frappe.call({
                method: 'healthcare.healthcare.doctype.site_weekly_report.site_weekly_report.generate_weekly_reports_for_today',
                callback: function(r) {
                    frappe.set_route('List', 'Site Weekly Report');
                    frappe.msgprint(__('Weekly reports generated/updated for all sites.'));
                }
            });
        });
    }
}; 