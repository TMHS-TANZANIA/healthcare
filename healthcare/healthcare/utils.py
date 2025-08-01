# -*- coding: utf-8 -*-
# Copyright (c) 2018, earthians and contributors
# For license information, please see license.txt


import base64
import json

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.utils import cint, cstr, flt, get_link_to_form, getdate, time_diff_in_hours
from frappe.utils.formatters import format_value

from erpnext.setup.utils import insert_record

from healthcare.healthcare.doctype.fee_validity.fee_validity import (
	get_fee_validity,
	manage_fee_validity,
)
from healthcare.healthcare.doctype.healthcare_settings.healthcare_settings import (
	get_income_account,
)
from healthcare.healthcare.doctype.lab_test.lab_test import create_multiple
from healthcare.healthcare.doctype.observation.observation import add_observation
from healthcare.healthcare.doctype.observation_template.observation_template import (
	get_observation_template_details,
)
from healthcare.setup import setup_healthcare


@frappe.whitelist()
def get_healthcare_services_to_invoice(patient, customer, company, link_customer=False):
	patient = frappe.get_doc("Patient", patient)
	items_to_invoice = []
	if patient:
		# Customer validated, build a list of billable services
		items_to_invoice += get_appointments_to_invoice(patient, company)
		items_to_invoice += get_encounters_to_invoice(patient, company)
		items_to_invoice += get_lab_tests_to_invoice(patient, company)
		items_to_invoice += get_clinical_procedures_to_invoice(patient, company)
		items_to_invoice += get_inpatient_services_to_invoice(patient, company)
		items_to_invoice += get_therapy_plans_to_invoice(patient, company)
		items_to_invoice += get_therapy_sessions_to_invoice(patient, company)
		items_to_invoice += get_service_requests_to_invoice(patient, company)
		items_to_invoice += get_observations_to_invoice(patient, company)
		validate_customer_created(patient, customer, link_customer)
		return items_to_invoice


def validate_customer_created(patient, customer, link_customer):
	message = ""
	if link_customer:
		frappe.db.set_value("Patient", patient, "customer", customer)
		message = _("Customer {0} has been linked to Patient").format(customer)
	elif not frappe.db.get_value("Patient", patient.name, "customer"):
		message = _(
			"Patient <b>{0}</b> is not linked to a Customer <b><a href='/app/Form/Patient/{1}'>{1}</a></b>"
		).format(patient.patient_name, patient.name)

	if message:
		frappe.msgprint(message, alert=True)


def get_appointments_to_invoice(patient, company):
	appointments_to_invoice = []
	patient_appointments = frappe.get_list(
		"Patient Appointment",
		fields="*",
		filters={
			"patient": patient.name,
			"company": company,
			"invoiced": 0,
			"status": ["!=", "Cancelled"],
		},
		order_by="appointment_date",
	)

	for appointment in patient_appointments:
		# Procedure Appointments
		# TODO: insurance? do we need this?
		if appointment.procedure_template:
			if frappe.db.get_value(
				"Clinical Procedure Template", appointment.procedure_template, "is_billable"
			):
				appointments_to_invoice.append(
					{
						"reference_type": "Patient Appointment",
						"reference_name": appointment.name,
						"service": appointment.procedure_template,
					}
				)
		# Consultation Appointments, should check fee validity
		else:
			if appointment.practitioner:
				pract_enabled = frappe.get_cached_value(
					"Healthcare Practitioner", appointment.practitioner, "enable_free_follow_ups"
				)
				settings_enabled = frappe.db.get_single_value("Healthcare Settings", "enable_free_follow_ups")

				if pract_enabled or settings_enabled:
					if get_fee_validity(appointment.name, appointment.appointment_date, ignore_status=True):
						continue  # Skip invoicing, fee validity exists

			practitioner_charge = 0
			income_account = None
			service_item = None
			if appointment.practitioner:
				details = get_appointment_billing_item_and_rate(appointment)
				service_item = details.get("service_item")
				practitioner_charge = details.get("practitioner_charge")
				income_account = get_income_account(appointment.practitioner, appointment.company)

			# insurance
			coverage_details = None
			if appointment.insurance_coverage:
				coverage_details = frappe.get_cached_value(
					"Patient Insurance Coverage",
					appointment.insurance_coverage,
					[
						"status",
						"coverage",
						"discount",
						"price_list_rate",
						"item_code",
						"qty",
						"policy_number",
						"coverage_validity_end_date",
						"company",
						"insurance_payor",
					],
					as_dict=True,
				)

			if (
				coverage_details
				and coverage_details.status in ["Approved", "Partly Invoiced"]
				and getdate() <= coverage_details.coverage_validity_end_date
				and company == coverage_details.company
			):
				appointments_to_invoice.append(
					{
						"reference_type": "Patient Appointment",
						"reference_name": appointment.name,
						"income_account": income_account,  # TODO: can be None?
						"insurance_coverage": appointment.insurance_coverage,
						"patient_insurance_policy": coverage_details.policy_number,
						"insurance_payor": coverage_details.insurance_payor,
						"service": coverage_details.item_code,
						"rate": coverage_details.price_list_rate,
						"coverage_percentage": coverage_details.coverage,
						"discount_percentage": coverage_details.discount,
						"coverage_rate": coverage_details.price_list_rate,
						"coverage_qty": coverage_details.qty,
					}
				)
			# insurance
			else:
				# no insurance
				practitioner_charge = 0
				service_item = None
				details = get_appointment_billing_item_and_rate(appointment)
				service_item = details.get("service_item")
				practitioner_charge = details.get("practitioner_charge")
				appointments_to_invoice.append(
					{
						"reference_type": "Patient Appointment",
						"reference_name": appointment.name,
						"service": service_item,
						"rate": practitioner_charge,
						"income_account": income_account,  # TODO: can be None?
					}
				)
				# no insurance

	return appointments_to_invoice


def get_encounters_to_invoice(patient, company):
	if not isinstance(patient, str):
		patient = patient.name
	encounters_to_invoice = []
	encounters = frappe.get_list(
		"Patient Encounter",
		fields=["*"],
		filters={"patient": patient, "company": company, "invoiced": False, "docstatus": 1},
	)
	if encounters:
		for encounter in encounters:
			if not encounter.appointment:  # TODO: make if not
				practitioner_charge = 0
				income_account = None
				service_item = None
				if encounter.practitioner:  # TODO:???
					if encounter.inpatient_record and frappe.db.get_single_value(
						"Healthcare Settings",
						"do_not_bill_inpatient_encounters",  # TODO: move this check before the loop?
					):
						continue

					income_account = get_income_account(encounter.practitioner, encounter.company)
				# insurance
				coverage_details = None
				if encounter.insurance_coverage:
					coverage_details = frappe.get_cached_value(
						"Patient Insurance Coverage",
						encounter.insurance_coverage,
						[
							"status",
							"coverage",
							"discount",
							"price_list_rate",
							"item_code",
							"qty",
							"policy_number",
							"coverage_validity_end_date",
							"company",
							"insurance_payor",
						],
						as_dict=True,
					)

				if (
					coverage_details
					and coverage_details.status in ["Approved", "Partly Invoiced"]
					and getdate() <= coverage_details.coverage_validity_end_date
					and company == coverage_details.company
				):
					encounters_to_invoice.append(
						{
							"reference_type": "Patient Encounter",
							"reference_name": encounter.name,
							"income_account": income_account,
							"insurance_coverage": encounter.insurance_coverage,
							"patient_insurance_policy": coverage_details.policy_number,
							"insurance_payor": coverage_details.insurance_payor,
							"service": coverage_details.item_code,
							"rate": coverage_details.price_list_rate,
							"coverage_percentage": coverage_details.coverage,
							"discount_percentage": coverage_details.discount,
							"coverage_rate": coverage_details.price_list_rate,
							"coverage_qty": coverage_details.qty,
						}
					)
				# insurance
				else:
					# no insurance
					practitioner_charge = 0
					service_item = None
					details = get_appointment_billing_item_and_rate(encounter)
					service_item = details.get("service_item")
					practitioner_charge = details.get("practitioner_charge")

					encounters_to_invoice.append(
						{
							"reference_type": "Patient Encounter",
							"reference_name": encounter.name,
							"service": service_item,
							"rate": practitioner_charge,
							"income_account": income_account,
						}
					)

	return encounters_to_invoice


def get_lab_tests_to_invoice(patient, company):
	lab_tests_to_invoice = []
	lab_tests = frappe.get_list(
		"Lab Test",
		fields=["name", "template"],
		filters={
			"patient": patient.name,
			"company": company,
			"invoiced": False,
			"docstatus": 1,
			"service_request": "",
		},
	)

	# TODO: income_account?
	for lab_test in lab_tests:
		item, is_billable = frappe.get_cached_value(
			"Lab Test Template", lab_test.template, ["item", "is_billable"]
		)
		if is_billable:
			coverage_details = None
			if lab_test.insurance_coverage:
				coverage_details = frappe.get_cached_value(
					"Patient Insurance Coverage",
					lab_test.insurance_coverage,
					[
						"status",
						"coverage",
						"discount",
						"price_list_rate",
						"item_code",
						"qty",
						"policy_number",
						"coverage_validity_end_date",
						"company",
						"insurance_payor",
					],
					as_dict=True,
				)

			if (
				coverage_details
				and coverage_details.status in ["Approved", "Partly Invoiced"]
				and getdate() <= coverage_details.coverage_validity_end_date
				and company == coverage_details.company
			):
				lab_tests_to_invoice.append(
					{
						"reference_type": "Lab Test",
						"reference_name": lab_test.name,
						"insurance_coverage": lab_test.insurance_coverage,
						"patient_insurance_policy": coverage_details.policy_number,
						"insurance_payor": coverage_details.insurance_payor,
						"service": coverage_details.item_code,
						"rate": coverage_details.price_list_rate,
						"coverage_percentage": coverage_details.coverage,
						"discount_percentage": coverage_details.discount,
						"coverage_rate": coverage_details.price_list_rate,
						"coverage_qty": coverage_details.qty,
					}
				)
			else:
				lab_tests_to_invoice.append(
					{"reference_type": "Lab Test", "reference_name": lab_test.name, "service": item}
				)

	return lab_tests_to_invoice


def get_clinical_procedures_to_invoice(patient, company):
	clinical_procedures_to_invoice = []
	procedures = frappe.get_list(
		"Clinical Procedure",
		fields="*",
		filters={
			"patient": patient.name,
			"company": company,
			"invoiced": False,
			"docstatus": 1,
			"service_request": "",
		},
	)
	for procedure in procedures:
		if procedure.appointment:
			continue

		item, is_billable = frappe.get_cached_value(
			"Clinical Procedure Template", procedure.procedure_template, ["item", "is_billable"]
		)
		if procedure.procedure_template and is_billable:
			coverage_details = None
			if procedure.insurance_coverage:
				coverage_details = frappe.get_cached_value(
					"Patient Insurance Coverage",
					procedure.insurance_coverage,
					[
						"status",
						"coverage",
						"discount",
						"price_list_rate",
						"item_code",
						"qty",
						"policy_number",
						"coverage_validity_end_date",
						"company",
						"insurance_payor",
					],
					as_dict=True,
				)

			if (
				coverage_details
				and coverage_details.status in ["Approved", "Partly Invoiced"]
				and getdate() <= coverage_details.coverage_validity_end_date
				and company == coverage_details.company
			):
				clinical_procedures_to_invoice.append(
					{
						"reference_type": "Clinical Procedure",
						"reference_name": procedure.name,
						"insurance_coverage": procedure.insurance_coverage,
						"patient_insurance_policy": coverage_details.policy_number,
						"insurance_payor": coverage_details.insurance_payor,
						"service": coverage_details.item_code,
						"rate": coverage_details.price_list_rate,
						"coverage_percentage": coverage_details.coverage,
						"discount_percentage": coverage_details.discount,
						"coverage_rate": coverage_details.price_list_rate,
						"coverage_qty": coverage_details.qty,
					}
				)
			else:
				clinical_procedures_to_invoice.append(
					{"reference_type": "Clinical Procedure", "reference_name": procedure.name, "service": item}
				)

		# consumables
		# TODO: apply insurance coverage
		if (
			procedure.invoice_separately_as_consumables
			and procedure.consume_stock
			and procedure.status == "Completed"
			and not procedure.consumption_invoiced
		):

			service_item = frappe.db.get_single_value(
				"Healthcare Settings", "clinical_procedure_consumable_item"
			)
			if not service_item:
				msg = _("Please Configure Clinical Procedure Consumable Item in {0}").format(
					get_link_to_form("Healthcare Settings", "Healthcare Settings")
				)

				frappe.throw(msg, title=_("Missing Configuration"))

			clinical_procedures_to_invoice.append(
				{
					"reference_type": "Clinical Procedure",
					"reference_name": procedure.name,
					"service": service_item,
					"rate": procedure.consumable_total_amount,
					"description": procedure.consumption_details,
				}
			)
	return clinical_procedures_to_invoice


def get_observations_to_invoice(patient, company):
	observations_to_invoice = []
	observations = frappe.get_list(
		"Observation",
		fields=["name", "observation_template"],
		filters={
			"patient": patient.name,
			"company": company,
			"invoiced": False,
			"docstatus": 1,
			"service_request": "",
			"sales_invoice": None,
			"parent_observation": None,
		},
	)
	for observation in observations:
		item, is_billable = frappe.get_cached_value(
			"Observation Template", observation.observation_template, ["item", "is_billable"]
		)
		if is_billable:
			observations_to_invoice.append(
				{"reference_type": "Observation", "reference_name": observation.name, "service": item}
			)

	return observations_to_invoice


def get_inpatient_services_to_invoice(patient, company):
	services_to_invoice = []

	if not frappe.db.get_single_value("Healthcare Settings", "automatically_generate_billable"):
		ip_record = DocType("Inpatient Record")
		ip_occupancy = DocType("Inpatient Occupancy")

		inpatient_services = (
			frappe.qb.from_(ip_occupancy)
			.join(ip_record)
			.on(ip_occupancy.parent == ip_record.name)
			.select(ip_occupancy.star)
			.where(
				(ip_record.patient == patient.name)
				& (ip_record.company == company)
				& (ip_occupancy.invoiced == 0)
			)
			.run(as_dict=True)
		)

		for inpatient_occupancy in inpatient_services:
			service_unit_type = frappe.db.get_value(
				"Healthcare Service Unit", inpatient_occupancy.service_unit, "service_unit_type"
			)
			service_unit_type = frappe.get_cached_doc("Healthcare Service Unit Type", service_unit_type)
			if service_unit_type and service_unit_type.is_billable:
				coverage_details = None
				if inpatient_occupancy.insurance_coverage:
					coverage_details = frappe.get_cached_value(
						"Patient Insurance Coverage",
						inpatient_occupancy.insurance_coverage,
						[
							"status",
							"coverage",
							"discount",
							"price_list_rate",
							"item_code",
							"qty",
							"policy_number",
							"coverage_validity_end_date",
							"company",
							"insurance_payor",
						],
						as_dict=True,
					)

				if (
					coverage_details
					and coverage_details.status in ["Approved", "Partly Invoiced"]
					and getdate() <= coverage_details.coverage_validity_end_date
					and company == coverage_details.company
				):
					services_to_invoice.append(
						{
							"reference_type": "Inpatient Occupancy",
							"reference_name": inpatient_occupancy.name,
							"insurance_coverage": inpatient_occupancy.insurance_coverage,
							"patient_insurance_policy": coverage_details.policy_number,
							"insurance_payor": coverage_details.insurance_payor,
							"service": coverage_details.item_code,
							"rate": coverage_details.price_list_rate,
							"coverage_percentage": coverage_details.coverage,
							"discount_percentage": coverage_details.discount,
							"coverage_rate": coverage_details.price_list_rate,
							"coverage_qty": coverage_details.qty,
							"qty": coverage_details.qty,
						}
					)
				else:
					hours_occupied = flt(
						time_diff_in_hours(inpatient_occupancy.check_out, inpatient_occupancy.check_in)
					)
					qty = 0.5
					if hours_occupied > 0:
						qty = hours_occupied / service_unit_type.no_of_hours
					if qty < service_unit_type.minimum_billable_qty:
						qty = service_unit_type.minimum_billable_qty
					services_to_invoice.append(
						{
							"reference_type": "Inpatient Occupancy",
							"reference_name": inpatient_occupancy.name,
							"service": service_unit_type.item,
							"qty": qty,
						}
					)
					inpatient_record_doc = frappe.get_doc("Inpatient Record", inpatient_occupancy.parent)
					for item in inpatient_record_doc.items:
						if item.stock_entry and not item.invoiced:
							services_to_invoice.append(
								{
									"reference_type": "Inpatient Record Item",
									"reference_name": item.name,
									"service": item.item_code,
									"qty": item.quantity,
								}
							)
					inpatient_record_doc.add_service_unit_rent_to_billable_items()

	else:  # TODO: if automatically_generate_billable is turned off, handle insurance
		ip = frappe.qb.DocType("Inpatient Record")
		iri = frappe.qb.DocType("Inpatient Record Item")

		query = (
			frappe.qb.from_(iri)
			.select(iri.name, iri.item_code, iri.quantity)
			.join(ip)
			.on(iri.parent == ip.name)
			.where((ip.patient == patient.name) & (ip.company == company) & (iri.invoiced == 0))
		)

		inpatient_services = query.run(as_dict=True)

		for inpatient_occupancy in inpatient_services:
			services_to_invoice.append(
				{
					"reference_type": "Inpatient Record Item",
					"reference_name": inpatient_occupancy.name,
					"service": inpatient_occupancy.item_code,
					"qty": inpatient_occupancy.quantity,
				}
			)

	return services_to_invoice


def get_therapy_plans_to_invoice(patient, company):
	therapy_plans_to_invoice = []
	therapy_plans = frappe.get_list(
		"Therapy Plan",
		fields=["therapy_plan_template", "name"],
		filters={
			"patient": patient.name,
			"invoiced": 0,
			"company": company,
			"therapy_plan_template": ("!=", ""),
			"docstatus": 1,
		},
	)
	for plan in therapy_plans:
		therapy_plans_to_invoice.append(
			{
				"reference_type": "Therapy Plan",
				"reference_name": plan.name,
				"service": frappe.db.get_value(
					"Therapy Plan Template", plan.therapy_plan_template, "linked_item"
				),
			}
		)

	return therapy_plans_to_invoice


def get_therapy_sessions_to_invoice(patient, company):
	therapy_sessions_to_invoice = []
	therapy_plans = frappe.db.get_all("Therapy Plan", {"therapy_plan_template": ("!=", "")})
	therapy_plans_created_from_template = []
	for entry in therapy_plans:
		therapy_plans_created_from_template.append(entry.name)

	therapy_sessions = frappe.get_list(
		"Therapy Session",
		fields="*",
		filters={
			"patient": patient.name,
			"invoiced": 0,
			"company": company,
			"therapy_plan": ("not in", therapy_plans_created_from_template),
			"docstatus": 1,
			"service_request": "",
		},
	)
	for therapy in therapy_sessions:
		if not therapy.appointment:
			if therapy.therapy_type and frappe.db.get_value(
				"Therapy Type", therapy.therapy_type, "is_billable"
			):
				# insurance
				coverage_details = None
				if therapy.insurance_coverage:
					coverage_details = frappe.get_cached_value(
						"Patient Insurance Coverage",
						therapy.insurance_coverage,
						[
							"status",
							"coverage",
							"discount",
							"price_list_rate",
							"item_code",
							"qty",
							"policy_number",
							"coverage_validity_end_date",
							"company",
							"insurance_payor",
						],
						as_dict=True,
					)

					if (
						coverage_details
						and coverage_details.status in ["Approved", "Partly Invoiced"]
						and getdate() <= coverage_details.coverage_validity_end_date
						and company == coverage_details.company
					):
						therapy_sessions_to_invoice.append(
							{
								"reference_type": "Therapy Session",
								"reference_name": therapy.name,
								"patient_insurance_policy": coverage_details.policy_number,
								"insurance_coverage": therapy.insurance_coverage,
								"insurance_payor": therapy.insurance_payor,
								"service": coverage_details.item_code,
								"rate": coverage_details.price_list_rate,
								"coverage_percentage": coverage_details.coverage,
								"discount_percentage": coverage_details.discount,
								"coverage_rate": coverage_details.price_list_rate,
								"coverage_qty": coverage_details.qty,
							}
						)
				else:
					therapy_sessions_to_invoice.append(
						{
							"reference_type": "Therapy Session",
							"reference_name": therapy.name,
							"service": frappe.db.get_value("Therapy Type", therapy.therapy_type, "item"),
						}
					)

	return therapy_sessions_to_invoice


def get_service_requests_to_invoice(patient, company):
	orders_to_invoice = []
	service_requests = frappe.get_list(
		"Service Request",
		fields=["*"],
		filters={
			"patient": patient.name,
			"company": company,
			"billing_status": ["!=", "Invoiced"],
			"docstatus": 1,
		},
	)
	for service_request in service_requests:
		item, is_billable = frappe.get_cached_value(
			service_request.template_dt, service_request.template_dn, ["item", "is_billable"]
		)
		# price_list, price_list_currency = frappe.db.get_values(
		# 	"Price List", {"selling": 1}, ["name", "currency"]
		# )[0]
		# args = {
		# 	"doctype": "Sales Invoice",
		# 	"item_code": item,
		# 	"company": service_request.get("company"),
		# 	"customer": frappe.db.get_value("Patient", service_request.get("patient"), "customer"),
		# 	"plc_conversion_rate": 1.0,
		# 	"conversion_rate": 1.0,
		# }
		if is_billable:
			billable_order_qty = service_request.get("quantity", 1) - service_request.get("qty_invoiced", 0)

			coverage_details = None
			if service_request.insurance_coverage:
				coverage_details = frappe.get_cached_value(
					"Patient Insurance Coverage",
					service_request.insurance_coverage,
					[
						"status",
						"coverage",
						"discount",
						"price_list_rate",
						"item_code",
						"qty",
						"qty_invoiced",
						"policy_number",
						"coverage_validity_end_date",
					],
					as_dict=True,
				)

			if (
				coverage_details
				and coverage_details.status in ["Approved", "Partly Invoiced"]
				and getdate() <= coverage_details.coverage_validity_end_date
			):

				# billable qty from insurance coverage
				billable_coverage_qty = coverage_details.get("qty", 1) - coverage_details.get(
					"qty_invoiced", 0
				)

				orders_to_invoice.append(
					{
						"reference_type": "Service Request",
						"reference_name": service_request.name,
						"patient_insurance_policy": coverage_details.policy_number,
						"insurance_coverage": service_request.insurance_coverage,
						"insurance_payor": service_request.insurance_payor,
						"service": coverage_details.item_code,
						"rate": coverage_details.price_list_rate,
						"coverage_percentage": coverage_details.coverage,
						"discount_percentage": coverage_details.discount,
						"qty": min(billable_coverage_qty, billable_order_qty),
						"coverage_rate": coverage_details.price_list_rate,
						"coverage_qty": coverage_details.qty,
					}
				)
				# if order quantity is not fully billed, update billable_order_qty
				# bill remaining qty as new line without insurance
				if billable_order_qty > billable_coverage_qty:
					billable_order_qty = billable_order_qty - billable_coverage_qty
				else:
					# order qty fully billed
					continue
			else:
				orders_to_invoice.append(
					{
						"reference_type": "Service Request",
						"reference_name": service_request.name,
						"service": item,
						"qty": service_request.quantity if service_request.quantity else 1,
					}
				)
	return orders_to_invoice


@frappe.whitelist()
def get_appointment_billing_item_and_rate(doc):
	if isinstance(doc, str):
		doc = json.loads(doc)
		doc = frappe.get_doc(doc)

	service_item = None
	practitioner_charge = None
	department = doc.medical_department if doc.doctype == "Patient Encounter" else doc.department
	service_unit = doc.service_unit if doc.doctype == "Patient Appointment" else None

	is_inpatient = doc.inpatient_record

	if doc.get("practitioner"):
		service_item, practitioner_charge = get_practitioner_billing_details(
			doc.practitioner, is_inpatient
		)

	if not service_item and doc.get("appointment_type"):
		service_item, appointment_charge = get_appointment_type_billing_details(
			doc.appointment_type, department if department else service_unit, is_inpatient
		)
		if not practitioner_charge:
			practitioner_charge = appointment_charge

	if not service_item:
		service_item = get_healthcare_service_item(is_inpatient)

	if not service_item:
		throw_config_service_item(is_inpatient)

	if not practitioner_charge and doc.get("practitioner"):
		throw_config_practitioner_charge(is_inpatient, doc.practitioner)

	if not practitioner_charge and not doc.get("practitioner"):
		throw_config_appointment_type_charge(is_inpatient, doc.appointment_type)

	return {"service_item": service_item, "practitioner_charge": practitioner_charge}


def get_appointment_type_billing_details(appointment_type, dep_su, is_inpatient):
	from healthcare.healthcare.doctype.appointment_type.appointment_type import get_billing_details

	if not dep_su:
		return None, None

	item_list = get_billing_details(appointment_type, dep_su)
	service_item = None
	practitioner_charge = None

	if item_list:
		if is_inpatient:
			service_item = item_list.get("inpatient_visit_charge_item")
			practitioner_charge = item_list.get("inpatient_visit_charge")
		else:
			service_item = item_list.get("op_consulting_charge_item")
			practitioner_charge = item_list.get("op_consulting_charge")

	return service_item, practitioner_charge


def throw_config_service_item(is_inpatient):
	service_item_label = (
		_("Inpatient Visit Charge Item") if is_inpatient else _("Out Patient Consulting Charge Item")
	)

	msg = _(
		("Please Configure {0} in ").format(service_item_label)
		+ """<b><a href='/app/Form/Healthcare Settings'>Healthcare Settings</a></b>"""
	)
	frappe.throw(msg, title=_("Missing Configuration"))


def throw_config_practitioner_charge(is_inpatient, practitioner):
	charge_name = _("Inpatient Visit Charge") if is_inpatient else _("OP Consulting Charge")

	msg = _(
		("Please Configure {0} for Healthcare Practitioner").format(charge_name)
		+ """ <b><a href='/app/Form/Healthcare Practitioner/{0}'>{0}</a></b>""".format(practitioner)
	)
	frappe.throw(msg, title=_("Missing Configuration"))


def throw_config_appointment_type_charge(is_inpatient, appointment_type):
	charge_name = _("Inpatient Visit Charge") if is_inpatient else _("OP Consulting Charge")

	msg = _(
		("Please Configure {0} for Appointment Type").format(charge_name)
		+ """ <b><a href='/app/Form/Appointment type/{0}'>{0}</a></b>""".format(appointment_type)
	)
	frappe.throw(msg, title=_("Missing Configuration"))


def get_practitioner_billing_details(practitioner, is_inpatient):
	service_item = None
	practitioner_charge = None

	if is_inpatient:
		fields = ["inpatient_visit_charge_item", "inpatient_visit_charge"]
	else:
		fields = ["op_consulting_charge_item", "op_consulting_charge"]

	if practitioner:
		service_item, practitioner_charge = frappe.db.get_value(
			"Healthcare Practitioner", practitioner, fields
		)

	return service_item, practitioner_charge


def get_healthcare_service_item(is_inpatient):
	service_item = None

	if is_inpatient:
		service_item = frappe.db.get_single_value("Healthcare Settings", "inpatient_visit_charge_item")
	else:
		service_item = frappe.db.get_single_value("Healthcare Settings", "op_consulting_charge_item")

	return service_item


def manage_invoice_validate(doc, method):
	if doc.service_unit and len(doc.items):
		for item in doc.items:
			if not item.service_unit:
				item.service_unit = doc.service_unit


def manage_invoice_submit_cancel(doc, method):
	if not doc.patient:
		return

	if doc.items:
		for item in doc.items:
			if item.get("reference_dt") and item.get("reference_dn"):
				# TODO check
				# if frappe.get_meta(item.reference_dt).has_field("invoiced"):
				set_invoiced(item, method, doc.name)

				# update Fee validity with Sales Invoice Reference if exists
				if item.reference_dt == "Patient Appointment":
					manage_fee_validity(frappe.get_doc("Patient Appointment", item.reference_dn))

		if method == "on_submit" and frappe.db.get_single_value(
			"Healthcare Settings", "create_observation_on_si_submit"
		):
			create_sample_collection_and_observation(doc)

	if method == "on_submit":
		if frappe.db.get_single_value("Healthcare Settings", "create_lab_test_on_si_submit"):
			create_multiple("Sales Invoice", doc.name)

		# handle insurance
		post_transfer_journal_entry_and_update_coverage(doc)
		doc.reload()

	elif method == "on_cancel":
		if doc.items and (doc.additional_discount_percentage or doc.discount_amount):
			for item in doc.items:
				if (
					item.get("reference_dt")
					and item.get("reference_dn")
					and item.get("reference_dt") == "Patient Appointment"
				):
					frappe.db.set_value(
						item.get("reference_dt"),
						item.get("reference_dn"),
						{
							"paid_amount": item.amount,
							"ref_sales_invoice": None,
						},
					)
		# handle insurance
		update_insurance_coverage(doc)


def update_insurance_coverage(sales_invoice):
	"""
	Updates Insurance coverage invoice details
	NOTE: Journal entries should be cancelled by now via Cancel All
	"""
	for item in sales_invoice.items:
		if item.insurance_coverage:
			coverage = frappe.get_doc("Patient Insurance Coverage", item.insurance_coverage)
			coverage.update_invoice_details(item.qty * -1, item.insurance_coverage_amount * -1)


def post_transfer_journal_entry_and_update_coverage(sales_invoice):
	"""
	1 - Post Journal Entry to Transfer Patient balance for each coverage
	2 - Update Insurance Coverage
	TODO: Posting Journal Entries based on Insurance Payor will reduce number of journal entries,
	but won't be able allow coverage cancel after invoicing. Fix based on feedback
	"""
	for item in sales_invoice.items:
		if not item.insurance_coverage:
			continue

		from healthcare.healthcare.doctype.insurance_payor.insurance_payor import (
			get_insurance_payor_details,
		)

		insurance_payor_details = get_insurance_payor_details(
			item.insurance_payor, sales_invoice.company
		)

		if (
			not insurance_payor_details
			or not insurance_payor_details.get("receivable_account")
			or not insurance_payor_details.get("party")
		):
			frappe.throw(
				_("Receivable Account not configured for Insurance Payor").format(item.insurance_payor)
			)

		jv_accounts = []

		jv_accounts.append(
			{
				"account": insurance_payor_details.get("receivable_account"),
				"debit_in_account_currency": item.insurance_coverage_amount,
				"party_type": "Customer",
				"party": insurance_payor_details.get("party"),
				"cost_center": item.cost_center,
			}
		)

		# Post Journal Entry
		jv_accounts.append(
			{
				"account": sales_invoice.debit_to,
				"credit_in_account_currency": item.insurance_coverage_amount,
				"party_type": "Customer",
				"party": sales_invoice.customer,
				"reference_type": "Sales Invoice",
				"reference_name": sales_invoice.name,
				"reference_detail_no": item.name,
				"cost_center": item.cost_center,
			}
		)

		journal_entry = frappe.new_doc("Journal Entry")

		jv_naming_series = frappe.db.get_single_value(
			"Healthcare Settings", "naming_series_for_journal_entry"
		)
		if jv_naming_series:
			journal_entry.naming_series = jv_naming_series

		journal_entry.company = sales_invoice.company
		journal_entry.posting_date = sales_invoice.posting_date

		for account in jv_accounts:
			journal_entry.append("accounts", account)

		journal_entry.flags.ignore_permissions = True
		journal_entry.submit()

		# Update Insurance Coverage
		coverage = frappe.get_doc("Patient Insurance Coverage", item.insurance_coverage)
		coverage.update_invoice_details(item.qty, item.insurance_coverage_amount)


def set_invoiced(item, method, ref_invoice=None):
	invoiced = False
	if method == "on_submit":
		validate_invoiced_on_submit(item)
		invoiced = True

	if item.reference_dt == "Clinical Procedure":
		service_item = frappe.db.get_single_value(
			"Healthcare Settings", "clinical_procedure_consumable_item"
		)
		if service_item == item.item_code:
			frappe.db.set_value(item.reference_dt, item.reference_dn, "consumption_invoiced", invoiced)
		else:
			frappe.db.set_value(item.reference_dt, item.reference_dn, "invoiced", invoiced)
	else:
		if item.reference_dt not in ["Service Request", "Medication Request"]:
			frappe.db.set_value(item.reference_dt, item.reference_dn, "invoiced", invoiced)

	if item.reference_dt == "Patient Appointment":
		if frappe.db.get_value("Patient Appointment", item.reference_dn, "procedure_template"):
			dt_from_appointment = "Clinical Procedure"
		else:
			dt_from_appointment = "Patient Encounter"
		manage_doc_for_appointment(dt_from_appointment, item.reference_dn, invoiced)
		frappe.db.set_value("Patient Appointment", item.reference_dn, "ref_sales_invoice", ref_invoice)

	elif item.reference_dt == "Lab Prescription":
		manage_prescriptions(
			invoiced, item.reference_dt, item.reference_dn, "Lab Test", "lab_test_created"
		)

	elif item.reference_dt == "Procedure Prescription":
		manage_prescriptions(
			invoiced, item.reference_dt, item.reference_dn, "Clinical Procedure", "procedure_created"
		)
	elif item.reference_dt in ["Service Request", "Medication Request"]:
		# if order is invoiced, set both order and service transaction as invoiced
		hso = frappe.get_doc(item.reference_dt, item.reference_dn)
		if invoiced:
			hso.update_invoice_details(item.qty)
		else:
			hso.update_invoice_details(item.qty * -1)

		# service transaction linking to HSO
		if item.reference_dt == "Service Request":
			template_map = {
				"Clinical Procedure Template": "Clinical Procedure",
				"Therapy Type": "Therapy Session",
				"Lab Test Template": "Lab Test"
				# "Healthcare Service Unit": "Inpatient Occupancy"
			}


def validate_invoiced_on_submit(item):
	if (
		item.reference_dt == "Clinical Procedure"
		and frappe.db.get_single_value("Healthcare Settings", "clinical_procedure_consumable_item")
		== item.item_code
	):
		is_invoiced = frappe.db.get_value(item.reference_dt, item.reference_dn, "consumption_invoiced")

	elif item.reference_dt in ["Service Request", "Medication Request"]:
		billing_status = frappe.db.get_value(item.reference_dt, item.reference_dn, "billing_status")
		is_invoiced = True if billing_status == "Invoiced" else False

	else:
		is_invoiced = frappe.db.get_value(item.reference_dt, item.reference_dn, "invoiced")
	if is_invoiced:
		frappe.throw(
			_("The item referenced by {0} - {1} is already invoiced").format(
				item.reference_dt, item.reference_dn
			)
		)


def manage_prescriptions(invoiced, ref_dt, ref_dn, dt, created_check_field):
	created = frappe.db.get_value(ref_dt, ref_dn, created_check_field)
	if created:
		# Fetch the doc created for the prescription
		doc_created = frappe.db.get_value(dt, {"prescription": ref_dn})
		frappe.db.set_value(dt, doc_created, "invoiced", invoiced)


def manage_doc_for_appointment(dt_from_appointment, appointment, invoiced):
	dn_from_appointment = frappe.db.get_value(
		dt_from_appointment, filters={"appointment": appointment}
	)
	if dn_from_appointment:
		frappe.db.set_value(dt_from_appointment, dn_from_appointment, "invoiced", invoiced)


@frappe.whitelist()
def get_drugs_to_invoice(encounter, customer, link_customer=False):
	encounter = frappe.get_doc("Patient Encounter", encounter)
	if link_customer:
		frappe.db.set_value("Patient", encounter.patient, "customer", customer)
	if encounter:
		patient = frappe.get_doc("Patient", encounter.patient)
		if patient:
			orders_to_invoice = []
			medication_requests = frappe.get_list(
				"Medication Request",
				fields=["*"],
				filters={
					"patient": patient.name,
					"order_group": encounter.name,
					"billing_status": ["in", ["Pending", "Partly Invoiced"]],
					"docstatus": 1,
				},
			)
			for medication_request in medication_requests:
				if medication_request.medication:
					is_billable = frappe.get_cached_value(
						"Medication", medication_request.medication, ["is_billable"]
					)
				else:
					is_billable = frappe.db.exists(
						"Item", {"name": medication_request.medication_item, "disabled": False}
					)

				description = ""
				if medication_request.dosage and medication_request.period:
					description = _("{0} for {1}").format(medication_request.dosage, medication_request.period)

				if medication_request.medication_item and is_billable:
					billable_order_qty = medication_request.get("quantity", 1) - medication_request.get(
						"qty_invoiced", 0
					)
					if medication_request.number_of_repeats_allowed:
						if (
							medication_request.total_dispensable_quantity
							>= medication_request.quantity + medication_request.qty_invoiced
						):
							billable_order_qty = medication_request.get("quantity", 1)
						else:
							billable_order_qty = (
								medication_request.total_dispensable_quantity - medication_request.get("qty_invoiced", 0)
							)

					orders_to_invoice.append(
						{
							"reference_type": "Medication Request",
							"reference_name": medication_request.name,
							"drug_code": medication_request.medication_item,
							"quantity": billable_order_qty,
							"description": description,
						}
					)
			return orders_to_invoice


@frappe.whitelist()
def get_children(doctype, parent=None, company=None, is_root=False):
	parent_fieldname = "parent_" + doctype.lower().replace(" ", "_")
	fields = ["name as value", "is_group as expandable", "lft", "rgt"]

	filters = [["ifnull(`{0}`,'')".format(parent_fieldname), "=", "" if is_root else parent]]

	if is_root:
		fields += ["service_unit_type"] if doctype == "Healthcare Service Unit" else []
		filters.append(["company", "=", company])
	else:
		fields += (
			["service_unit_type", "allow_appointments", "inpatient_occupancy", "occupancy_status"]
			if doctype == "Healthcare Service Unit"
			else []
		)
		fields += [parent_fieldname + " as parent"]

	service_units = frappe.get_list(doctype, fields=fields, filters=filters)
	for each in service_units:
		if each["expandable"] != 1 or each["value"].startswith("All Healthcare Service Units"):
			continue

		available_count = frappe.db.count(
			"Healthcare Service Unit",
			filters={"parent_healthcare_service_unit": each["value"], "inpatient_occupancy": 1},
		)

		if available_count > 0:
			occupied_count = frappe.db.count(
				"Healthcare Service Unit",
				filters={
					"parent_healthcare_service_unit": each["value"],
					"inpatient_occupancy": 1,
					"occupancy_status": "Occupied",
				},
			)
			# set occupancy status of group node
			each["occupied_of_available"] = f"{str(occupied_count)} Occupied of {str(available_count)}"

	return service_units


@frappe.whitelist()
def get_patient_vitals(patient, from_date=None, to_date=None):
	if not patient:
		return

	vitals = frappe.db.get_all(
		"Vital Signs",
		filters={"docstatus": 1, "patient": patient},
		order_by="signs_date, signs_time",
		fields=["*"],
	)

	if len(vitals):
		return vitals
	return False


@frappe.whitelist()
def render_docs_as_html(docs):
	# docs key value pair {doctype: docname}
	docs_html = "<div class='col-md-12 col-sm-12 text-muted'>"
	for doc in docs:
		docs_html += render_doc_as_html(doc["doctype"], doc["docname"])["html"] + "<br/>"
		return {"html": docs_html}


@frappe.whitelist()
def render_doc_as_html(doctype, docname, exclude_fields=None):
	"""
	Render document as HTML
	"""
	exclude_fields = exclude_fields or []
	doc = frappe.get_doc(doctype, docname)
	meta = frappe.get_meta(doctype)
	doc_html = section_html = section_label = html = ""
	sec_on = has_data = False
	col_on = 0

	for df in meta.fields:
		# on section break append previous section and html to doc html
		if df.fieldtype == "Section Break":
			if has_data and col_on and sec_on:
				doc_html += section_html + html + "</div>"

			elif has_data and not col_on and sec_on:
				doc_html += """
					<br>
					<div class='row'>
						<div class='col-md-12 col-sm-12'>
							<b>{0}</b>
						</div>
					</div>
					<div class='row'>
						<div class='col-md-12 col-sm-12'>
							{1} {2}
						</div>
					</div>
				""".format(
					section_label, section_html, html
				)

			# close divs for columns
			while col_on:
				doc_html += "</div>"
				col_on -= 1

			sec_on = True
			has_data = False
			col_on = 0
			section_html = html = ""

			if df.label:
				section_label = df.label
			continue

		# on column break append html to section html or doc html
		if df.fieldtype == "Column Break":
			if sec_on and not col_on and has_data:
				section_html += """
					<br>
					<div class='row'>
						<div class='col-md-12 col-sm-12'>
							<b>{0}</b>
						</div>
					</div>
					<div class='row'>
						<div class='col-md-4 col-sm-4'>
							{1}
						</div>
				""".format(
					section_label, html
				)
			elif col_on == 1 and has_data:
				section_html += "<div class='col-md-4 col-sm-4'>" + html + "</div>"
			elif col_on > 1 and has_data:
				doc_html += "<div class='col-md-4 col-sm-4'>" + html + "</div>"
			else:
				doc_html += """
					<div class='row'>
						<div class='col-md-12 col-sm-12'>
							{0}
						</div>
					</div>
				""".format(
					html
				)

			html = ""
			col_on += 1

			if df.label:
				html += "<br>" + df.label
			continue

		# on table iterate through items and create table
		# based on the in_list_view property
		# append to section html or doc html
		if df.fieldtype == "Table":
			items = doc.get(df.fieldname)
			if not items:
				continue
			child_meta = frappe.get_meta(df.options)

			if not has_data:
				has_data = True
			table_head = table_row = ""
			create_head = True

			for item in items:
				table_row += "<tr>"
				for cdf in child_meta.fields:
					if cdf.in_list_view:
						if create_head:
							table_head += "<th class='text-muted'>" + cdf.label + "</th>"
						if item.get(cdf.fieldname):
							table_row += "<td>" + cstr(item.get(cdf.fieldname)) + "</td>"
						else:
							table_row += "<td></td>"

				create_head = False
				table_row += "</tr>"

			if sec_on:
				section_html += """
					<table class='table table-condensed bordered'>
						{0} {1}
					</table>
				""".format(
					table_head, table_row
				)
			else:
				html += """
					<table class='table table-condensed table-bordered'>
						{0} {1}
					</table>
				""".format(
					table_head, table_row
				)
			continue

		# on any other field type add label and value to html
		if (
			not df.hidden
			and not df.print_hide
			and doc.get(df.fieldname)
			and df.fieldname not in exclude_fields
		):
			formatted_value = format_value(doc.get(df.fieldname), meta.get_field(df.fieldname), doc)
			html += "<br>{0} : {1}".format(df.label or df.fieldname, formatted_value)

			if not has_data:
				has_data = True

	if sec_on and col_on and has_data:
		doc_html += section_html + html + "</div></div>"
	elif sec_on and not col_on and has_data:
		doc_html += """
			<div class='col-md-12 col-sm-12'>
				<div class='col-md-12 col-sm-12'>
					{0} {1}
				</div>
			</div>
		""".format(
			section_html, html
		)
	return {"html": doc_html}


def update_address_links(address, method):
	"""
	Hook validate Address
	If Patient is linked in Address, also link the associated Customer
	"""
	if "Healthcare" not in frappe.get_active_domains():
		return

	patient_links = list(filter(lambda link: link.get("link_doctype") == "Patient", address.links))

	for link in patient_links:
		customer = frappe.db.get_value("Patient", link.get("link_name"), "customer")
		if customer and not address.has_link("Customer", customer):
			address.append("links", dict(link_doctype="Customer", link_name=customer))


def update_patient_email_and_phone_numbers(contact, method):
	"""
	Hook validate Contact
	Update linked Patients' primary mobile and phone numbers
	"""
	if "Healthcare" not in frappe.get_active_domains() or contact.flags.skip_patient_update:
		return

	if contact.is_primary_contact and (contact.email_id or contact.mobile_no or contact.phone):
		patient_links = list(filter(lambda link: link.get("link_doctype") == "Patient", contact.links))

		for link in patient_links:
			contact_details = frappe.db.get_value(
				"Patient", link.get("link_name"), ["email", "mobile", "phone"], as_dict=1
			)
			if contact.email_id and contact.email_id != contact_details.get("email"):
				frappe.db.set_value("Patient", link.get("link_name"), "email", contact.email_id)
			if contact.mobile_no and contact.mobile_no != contact_details.get("mobile"):
				frappe.db.set_value("Patient", link.get("link_name"), "mobile", contact.mobile_no)
			if contact.phone and contact.phone != contact_details.get("phone"):
				frappe.db.set_value("Patient", link.get("link_name"), "phone", contact.phone)


def before_tests():
	# complete setup if missing
	from frappe.desk.page.setup_wizard.setup_wizard import setup_complete

	current_year = frappe.utils.now_datetime().year

	if not frappe.get_list("Company"):
		setup_complete(
			{
				"currency": "INR",
				"full_name": "Test User",
				"company_name": "Frappe Care LLC",
				"timezone": "America/New_York",
				"company_abbr": "WP",
				"industry": "Healthcare",
				"country": "United States",
				"fy_start_date": f"{current_year}-01-01",
				"fy_end_date": f"{current_year}-12-31",
				"language": "english",
				"company_tagline": "Testing",
				"email": "test@erpnext.com",
				"password": "test",
				"chart_of_accounts": "Standard",
				"domains": ["Healthcare"],
			}
		)

		setup_healthcare()


def create_healthcare_service_unit_tree_root(doc, method=None):
	record = [
		{
			"doctype": "Healthcare Service Unit",
			"healthcare_service_unit_name": "All Healthcare Service Units",
			"is_group": 1,
			"company": doc.name,
		}
	]
	insert_record(record)


def validate_nursing_tasks(document):
	if not frappe.db.get_single_value("Healthcare Settings", "validate_nursing_checklists"):
		return True

	filters = {
		"reference_name": document.name,
		"mandatory": 1,
		"status": ["not in", ["Completed", "Cancelled"]],
	}
	tasks = frappe.get_all("Nursing Task", filters=filters)
	if not tasks:
		return True

	frappe.throw(
		_("Please complete linked Nursing Tasks before submission: {}").format(
			", ".join(get_link_to_form("Nursing Task", task.name) for task in tasks)
		)
	)


@frappe.whitelist()
def get_medical_codes(template_dt, template_dn, code_standard=None):
	"""returns codification table from templates"""
	filters = {"parent": template_dn, "parenttype": template_dt}

	if code_standard:
		filters["code_system"] = code_standard

	return frappe.db.get_all(
		"Codification Table",
		filters=filters,
		fields=[
			"code_value",
			"code",
			"system",
			"display",
			"definition",
			"code_system",
		],
	)


def company_on_trash(doc, method):
	for su in frappe.get_all("Healthcare Service Unit", {"company": doc.name}):
		service_unit_doc = frappe.get_doc("Healthcare Service Unit", su.get("name"))
		service_unit_doc.flags.on_trash_company = True
		service_unit_doc.delete()


def create_sample_collection_and_observation(doc):
	meta = frappe.get_meta("Sales Invoice Item", cached=True)
	diag_report_required = False
	data = []
	for item in doc.items:
		# to set patient in item table if not set
		if meta.has_field("patient") and not item.patient:
			item.patient = doc.patient

		# ignore if already created from service request
		if item.get("reference_dt") == "Service Request" and item.get("reference_dn"):
			if (
				frappe.db.exists(
					"Observation Sample Collection", {"service_request": item.get("reference_dn")}
				)
				or frappe.db.exists("Sample Collection", {"service_request": item.get("reference_dn")})
				or frappe.db.exists("Observation", {"service_request": item.get("reference_dn")})
			):
				continue

		template_id = frappe.db.exists("Observation Template", {"item": item.item_code})
		if template_id:
			temp_dict = {}
			temp_dict["name"] = template_id
			if meta.has_field("patient") and item.get("patient"):
				temp_dict["patient"] = item.get("patient")
				temp_dict["child"] = item.get("name")
			data.append(temp_dict)

	out_data = []
	for d in data:
		observation_template = frappe.get_value(
			"Observation Template",
			d.get("name"),
			[
				"sample_type",
				"sample",
				"medical_department",
				"container_closure_color",
				"name",
				"sample_qty",
				"has_component",
				"sample_collection_required",
			],
			as_dict=True,
		)
		if observation_template:
			observation_template["patient"] = d.get("patient")
			observation_template["child"] = d.get("child")
			out_data.append(observation_template)
	if not meta.has_field("patient"):
		sample_collection = create_sample_collection(doc, doc.patient)
	else:
		grouped = {}
		for grp in out_data:
			grouped.setdefault(grp.patient, []).append(grp)
		if grouped:
			out_data = grouped

	for grp in out_data:
		patient = doc.patient
		if meta.has_field("patient") and grp:
			patient = grp
		if meta.has_field("patient"):
			sample_collection = create_sample_collection(doc, patient)
			for obs in out_data[grp]:
				(sample_collection, diag_report_required,) = insert_observation_and_sample_collection(
					doc, patient, obs, sample_collection, obs.get("child")
				)
			if sample_collection and len(sample_collection.get("observation_sample_collection")) > 0:
				sample_collection.save(ignore_permissions=True)

			if diag_report_required:
				insert_diagnostic_report(doc, patient, sample_collection.name)
		else:
			sample_collection, diag_report_required = insert_observation_and_sample_collection(
				doc, patient, grp, sample_collection
			)

	if not meta.has_field("patient"):
		if sample_collection and len(sample_collection.get("observation_sample_collection")) > 0:
			sample_collection.save(ignore_permissions=True)

		if diag_report_required:
			insert_diagnostic_report(doc, patient, sample_collection.name)


def create_sample_collection(doc, patient):
	patient = frappe.get_doc("Patient", patient)
	sample_collection = frappe.new_doc("Sample Collection")
	sample_collection.patient = patient.name
	sample_collection.patient_age = patient.get_age()
	sample_collection.patient_sex = patient.sex
	sample_collection.company = doc.company
	sample_collection.referring_practitioner = doc.ref_practitioner
	sample_collection.reference_doc = doc.doctype
	sample_collection.reference_name = doc.name
	return sample_collection


def insert_diagnostic_report(doc, patient, sample_collection=None):
	if not frappe.db.exists("Diagnostic Report", {"docname": doc.name}):
		diagnostic_report = frappe.new_doc("Diagnostic Report")
		diagnostic_report.company = doc.company
		diagnostic_report.patient = patient
		diagnostic_report.ref_doctype = doc.doctype
		diagnostic_report.docname = doc.name
		diagnostic_report.practitioner = doc.ref_practitioner
		diagnostic_report.sample_collection = sample_collection
		diagnostic_report.save(ignore_permissions=True)


def insert_observation_and_sample_collection(doc, patient, grp, sample_collection, child=None):
	diag_report_required = False
	if grp.get("has_component"):
		diag_report_required = True
		# parent observation
		parent_observation = add_observation(
			patient=patient,
			template=grp.get("name"),
			practitioner=doc.ref_practitioner,
			invoice=doc.name,
			child=child if child else "",
		)

		sample_reqd_component_obs, non_sample_reqd_component_obs = get_observation_template_details(
			grp.get("name")
		)
		# create observation for non sample_collection_reqd grouped templates

		if len(non_sample_reqd_component_obs) > 0:
			for comp in non_sample_reqd_component_obs:
				add_observation(
					patient=patient,
					template=comp,
					practitioner=doc.ref_practitioner,
					parent=parent_observation,
					invoice=doc.name,
					child=child if child else "",
				)
		# create sample_collection child row for  sample_collection_reqd grouped templates
		if len(sample_reqd_component_obs) > 0:
			sample_collection.append(
				"observation_sample_collection",
				{
					"observation_template": grp.get("name"),
					"container_closure_color": grp.get("color"),
					"sample": grp.get("sample"),
					"sample_type": grp.get("sample_type"),
					"component_observation_parent": parent_observation,
					"reference_child": child if child else "",
				},
			)

	else:
		diag_report_required = True
		# create observation for non sample_collection_reqd individual templates
		if not grp.get("sample_collection_required"):
			add_observation(
				patient=patient,
				template=grp.get("name"),
				practitioner=doc.ref_practitioner,
				invoice=doc.name,
				child=child if child else "",
			)
		else:
			# create sample_collection child row for  sample_collection_reqd individual templates
			sample_collection.append(
				"observation_sample_collection",
				{
					"observation_template": grp.get("name"),
					"container_closure_color": grp.get("color"),
					"sample": grp.get("sample"),
					"sample_type": grp.get("sample_type"),
					"reference_child": child if child else "",
				},
			)
	return sample_collection, diag_report_required


@frappe.whitelist()
def generate_barcodes(in_val):
	from io import BytesIO

	from barcode import Code128
	from barcode.writer import ImageWriter

	stream = BytesIO()
	Code128(str(in_val), writer=ImageWriter()).write(
		stream,
		{
			"module_height": 3,
			"text_distance": 0.9,
			"write_text": False,
		},
	)
	barcode_base64 = base64.b64encode(stream.getbuffer()).decode()
	stream.close()

	return barcode_base64


@frappe.whitelist()
def add_node():
	from frappe.desk.treeview import make_tree_args

	args = make_tree_args(**frappe.form_dict)

	if cint(args.is_root):
		args.parent_healthcare_service_unit = None

	frappe.get_doc(args).insert()
