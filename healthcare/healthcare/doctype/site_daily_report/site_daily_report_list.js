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
        listview.page.add_actions_menu_item(__('Return for Edit'), function() {
            let selected = listview.get_checked_items();

            if (!selected.length) {
                frappe.msgprint(__('Please select at least one document.'));
                return;
            }

            frappe.confirm(
                __('Are you sure you want to return the selected documents to Draft?'),
                function() {
                    frappe.call({
                        method: 'healthcare.healthcare.doctype.site_daily_report.site_daily_report.return_for_edit',
                        args: {
                            docs: selected.map(d => d.name)
                        },
                        callback: function(r) {
                            if (!r.exc) {
                                frappe.msgprint(__('Selected documents have been returned to Draft.'));
                                listview.refresh();
                            }
                        }
                    });
                }
            );
        });
    },
};