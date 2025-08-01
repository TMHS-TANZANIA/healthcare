// Copyright (c) 2020, earthians and contributors
// For license information, please see license.txt
// {% include "healthcare/public/js/service_request.js" %}

frappe.ui.form.on('Service Request', {
	refresh: function(frm) {
		if (!frm.is_new() && !frm.doc.insurance_policy && frm.doc.billing_status == 'Pending') {
			frm.add_custom_button(__("Create Insurance Coverage"), function() {
				var d = new frappe.ui.Dialog({
					title: __("Select Insurance Policy"),
					fields: [
						{
							'fieldname': 'Patient Insurance Policy',
							'fieldtype': 'Link',
							'label': __('Patient Insurance Policy'),
							'options': 'Patient Insurance Policy',
							"get_query": function () {
								return {
									filters: {
										'patient': frm.doc.patient,
										'docstatus': 1
									}
								};
							},
							'reqd': 1
						}
					],
				});
				d.set_primary_action(__('Create'), function() {
					d.hide();
					var data = d.get_values();
					frm.set_value('insurance_policy', data['Patient Insurance Policy'])
					frm.save("Update")
				});
				d.show();
			});
		}
		frm.set_query('order_group', function () {
			return {
				filters: {
					'docstatus': 1,
					'patient': frm.doc.patient,
					'practitioner': frm.doc.ordered_by
				}
			};
		});

		frm.set_query('template_dt', function() {
			let order_template_doctypes = [
				"Therapy Type",
				"Lab Test Template",
				"Clinical Procedure Template",
				"Appointment Type",
				"Observation Template",
				"Healthcare Activity"];
			return {
				filters: {
					name: ['in', order_template_doctypes]
				}
			};
		});

		frm.set_query("status", function () {
			return {
				"filters": {
					"code_system": "Request Status",
				}
			};
		});

		frm.set_query('patient', function () {
			return {
				filters: {
					'status': 'Active'
				}
			};
		});

		frm.set_query('staff_role', function () {
			return {
				filters: {
					'restrict_to_domain': 'Healthcare'
				}
			};
		});

		frm.set_query('insurance_policy', function() {
			return {
				filters: {
					'patient': frm.doc.patient,
					'docstatus': 1
				}
			};
		});

		frm.trigger('setup_create_buttons');
	},

	setup_create_buttons: function(frm) {
		if (frm.doc.docstatus !== 1 || frm.doc.status === 'Completed') return;

		if (frm.doc.template_dt === 'Clinical Procedure Template') {

			frm.add_custom_button(__('Clinical Procedure'), function() {
				frappe.db.get_value("Clinical Procedure", {"service_request": frm.doc.name, "docstatus":["!=", 2]}, "name")
				.then(r => {
					if (Object.keys(r.message).length == 0) {
						frm.trigger('make_clinical_procedure');
					} else {
						if (r.message && r.message.name) {
							frappe.set_route("Form", "Clinical Procedure", r.message.name);
							frappe.show_alert({
								message: __(`Clinical Procedure is already created`),
								indicator: "info",
							});
						}
					}
				})
			}, __('Create'));


		} else if (frm.doc.template_dt === 'Lab Test Template') {
			frm.add_custom_button(__('Lab Test'), function() {
				frappe.db.get_value("Lab Test", {"service_request": frm.doc.name, "docstatus":["!=", 2]}, "name")
				.then(r => {
					if (Object.keys(r.message).length == 0) {
						frm.trigger('make_lab_test');
					} else {
						if (r.message && r.message.name) {
							frappe.set_route("Form", "Lab Test", r.message.name);
							frappe.show_alert({
								message: __(`Lab Test is already created`),
								indicator: "info",
							});
						}
					}
				})
			}, __('Create'));

		} else if (frm.doc.template_dt === 'Therapy Type') {
			frm.add_custom_button(__("Therapy Session"), function() {
				frappe.db.get_list("Therapy Session", {
					filters: {
						"service_request": frm.doc.name,
						"docstatus":["!=", 2],
						"therapy_type": frm.doc.template_dn
					},
					fields: ["name"]
				}).then(response => {
					if (response.length == frm.doc.quantity) {
						frappe.set_route("List", "Therapy Session", {
							service_request: frm.doc.name,
						});
					} else {
						frappe.db.get_value("Therapy Session", {"service_request": frm.doc.name, "docstatus": 0}, "name")
						.then(r => {
							if (Object.keys(r.message).length == 0) {
								frm.trigger('make_therapy_session');
							} else {
								if (r.message && r.message.name) {
									frappe.set_route("Form", "Therapy Session", r.message.name);
									frappe.show_alert({
										message: __(`Therapy Session is already created`),
										indicator: "info",
									});
								}
							}
						})
					}
				})
			}, __('Create'));

		} else if (frm.doc.template_dt === "Observation Template") {
			frm.add_custom_button(__('Observation'), function() {
				frm.trigger('make_observation');
			}, __('Create'));

		} else if (frm.doc.template_dt === "Appointment Type") {
			frm.add_custom_button(__("Appointment"), function () {
				frappe.db.get_value("Patient Appointment", { service_request: frm.doc.name, status: ["!=", "Cancelled"] }, "name")
					.then(r => {
						if (Object.keys(r.message).length == 0) {
							frappe.model.open_mapped_doc({
								method: "healthcare.healthcare.doctype.service_request.service_request.make_appointment",
								frm: frm,
							});
						} else {
							if (r.message && r.message.name) {
								frappe.set_route("Form", "Patient Appointment", r.message.name);
								frappe.show_alert({
									message: __("Patient Appointment is already created"),
									indicator: "info",
								});
							}
						}
					})
			}, __("Create"));
		}

		frm.page.set_inner_btn_group_as_primary(__('Create'));
	},

	make_clinical_procedure: function(frm) {
		frappe.call({
			method: 'healthcare.healthcare.doctype.service_request.service_request.make_clinical_procedure',
			args: { service_request: frm.doc },
			freeze: true,
			callback: function(r) {
				var doclist = frappe.model.sync(r.message);
				frappe.set_route('Form', doclist[0].doctype, doclist[0].name);
			}
		});
	},

	make_lab_test: function(frm) {
		frappe.call({
			method: 'healthcare.healthcare.doctype.service_request.service_request.make_lab_test',
			args: { service_request: frm.doc },
			freeze: true,
			callback: function(r) {
				var doclist = frappe.model.sync(r.message);
				frappe.set_route('Form', doclist[0].doctype, doclist[0].name);
			}
		});
	},

	make_therapy_session: function(frm) {
		frappe.call({
			method: 'healthcare.healthcare.doctype.therapy_plan.therapy_plan.make_therapy_session',
			args: {
				patient: frm.doc.patient,
				therapy_type: frm.doc.template_dn,
				company: frm.doc.company,
				service_request: frm.doc.name
			},
			freeze: true,
			callback: function(r) {
				var doclist = frappe.model.sync(r.message);
				frappe.set_route('Form', doclist[0].doctype, doclist[0].name);
			}
		});
	},

	make_observation: function(frm) {
		frappe.call({
			method: 'healthcare.healthcare.doctype.service_request.service_request.make_observation',
			args: { service_request: frm.doc },
			freeze: true,
			callback: function(r) {
				if (r.message) {
					var title = "";
					var indicator =  "info";
					if (r.message[2]) {
						title = `${r.message[0]} is already created`
					} else {
						title = `${r.message[0]} is created`
						indicator = "green"
					}
					frappe.show_alert({
						message: __("{0}", [title]),
						indicator: indicator,
					});
					frappe.set_route('Form', r.message[1], r.message[0]);
				}
			}
		});
	},
});
