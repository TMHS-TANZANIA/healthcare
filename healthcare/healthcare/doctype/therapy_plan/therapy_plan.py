# -*- coding: utf-8 -*-
# Copyright (c) 2020, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, today

from erpnext.stock.get_item_details import ItemDetailsCtx, get_item_details

from healthcare.healthcare.utils import validate_nursing_tasks


class TherapyPlan(Document):
	def validate(self):
		self.set_totals()
		self.set_status()

	def on_submit(self):
		validate_nursing_tasks(self)

	def set_status(self):
		if not self.total_sessions_completed:
			self.status = "Not Started"
		else:
			if self.total_sessions_completed < self.total_sessions:
				self.status = "In Progress"
			elif self.total_sessions_completed == self.total_sessions:
				self.status = "Completed"

	def set_totals(self):
		total_sessions = 0
		total_sessions_completed = 0
		for entry in self.therapy_plan_details:
			if entry.no_of_sessions:
				total_sessions += entry.no_of_sessions
			if entry.sessions_completed:
				total_sessions_completed += entry.sessions_completed

		self.db_set("total_sessions", total_sessions)
		self.db_set("total_sessions_completed", total_sessions_completed)

	@frappe.whitelist()
	def set_therapy_details_from_template(self):
		# Add therapy types in the child table
		self.set("therapy_plan_details", [])
		therapy_plan_template = frappe.get_doc("Therapy Plan Template", self.therapy_plan_template)

		for data in therapy_plan_template.therapy_types:
			self.append(
				"therapy_plan_details",
				{
					"therapy_type": data.therapy_type,
					"no_of_sessions": data.no_of_sessions,
					"interval": data.interval,
				},
			)
		return self


@frappe.whitelist()
def make_therapy_session(
	patient, therapy_type, company, therapy_plan=None, appointment=None, service_request=None
):
	sr_doc = None
	if service_request:
		if (
			frappe.db.get_single_value("Healthcare Settings", "process_service_request_only_if_paid")
			and frappe.get_cached_value("Service Request", service_request, "billing_status") != "Invoiced"
		):
			frappe.throw(
				_("Service Request need to be invoiced before proceeding"),
				title=_("Payment Required"),
			)

		sr_doc = frappe.get_cached_doc("Service Request", service_request)

	if not therapy_plan and sr_doc:
		therapy_plan = frappe.db.exists(
			"Therapy Plan", {"source_doc": sr_doc.source_doc, "order_group": sr_doc.order_group}
		)

	if not therapy_plan:
		frappe.throw(
			_("Therapy Plan is required to create Therapy Session"),
			title=_("Therapy Plan Required"),
		)

	therapy_type = frappe.get_doc("Therapy Type", therapy_type)

	therapy_session = frappe.new_doc("Therapy Session")
	therapy_session.therapy_plan = therapy_plan
	therapy_session.company = company
	therapy_session.patient = patient
	therapy_session.therapy_type = therapy_type.name
	therapy_session.duration = therapy_type.default_duration
	therapy_session.rate = therapy_type.rate
	if not therapy_session.exercises and therapy_type.exercises:
		for exercise in therapy_type.exercises:
			therapy_session.append(
				"exercises",
				(frappe.copy_doc(exercise)).as_dict(),
			)
	if not therapy_session.codification_table and therapy_type.codification_table:
		for code in therapy_type.codification_table:
			therapy_session.append(
				"codification_table",
				(frappe.copy_doc(code)).as_dict(),
			)
	therapy_session.appointment = appointment
	therapy_session.service_request = service_request
	if sr_doc:
		therapy_session.invoiced = 1 if sr_doc.billing_status == "Invoiced" else 0
		therapy_session.insurance_policy = sr_doc.insurance_policy
		therapy_session.insurance_payor = sr_doc.insurance_payor
		therapy_session.insurance_coverage = sr_doc.insurance_coverage
		therapy_session.coverage_status = sr_doc.coverage_status

	if frappe.flags.in_test:
		therapy_session.start_date = today()
	return therapy_session.as_dict()


@frappe.whitelist()
def make_sales_invoice(reference_name, patient, company, therapy_plan_template):
	si = frappe.new_doc("Sales Invoice")
	si.company = company
	si.patient = patient
	si.customer = frappe.db.get_value("Patient", patient, "customer")

	item = frappe.db.get_value("Therapy Plan Template", therapy_plan_template, "linked_item")
	price_list, price_list_currency = frappe.db.get_values(
		"Price List", {"selling": 1}, ["name", "currency"]
	)[0]
	ctx: ItemDetailsCtx = ItemDetailsCtx(
		{
			"doctype": "Sales Invoice",
			"item_code": item,
			"company": company,
			"customer": si.customer,
			"selling_price_list": price_list,
			"price_list_currency": price_list_currency,
			"plc_conversion_rate": 1.0,
			"conversion_rate": 1.0,
		}
	)

	item_line = si.append("items", {})
	item_details = get_item_details(ctx)
	item_line.item_code = item
	item_line.qty = 1
	item_line.rate = item_details.price_list_rate
	item_line.amount = flt(item_line.rate) * flt(item_line.qty)
	item_line.reference_dt = "Therapy Plan"
	item_line.reference_dn = reference_name
	item_line.description = item_details.description

	si.set_missing_values(for_validate=True)
	return si
