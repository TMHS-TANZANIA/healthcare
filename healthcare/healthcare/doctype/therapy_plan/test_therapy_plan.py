# -*- coding: utf-8 -*-
# Copyright (c) 2020, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt


import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt, getdate, nowdate

from healthcare.healthcare.doctype.patient_appointment.test_patient_appointment import (
	create_appointment,
	create_appointment_type,
	create_healthcare_docs,
	create_medical_department,
	create_patient,
)
from healthcare.healthcare.doctype.therapy_plan.therapy_plan import (
	make_sales_invoice,
	make_therapy_session,
)
from healthcare.healthcare.doctype.therapy_type.test_therapy_type import create_therapy_type


class TestTherapyPlan(IntegrationTestCase):
	def test_creation_on_encounter_submission(self):
		patient, practitioner = create_healthcare_docs()
		medical_department = create_medical_department()
		encounter = create_encounter(patient, medical_department, practitioner)
		self.assertTrue(
			frappe.db.exists(
				"Therapy Plan", {"source_doc": "Patient Encounter", "order_group": encounter.name}
			)
		)

	def test_status(self):
		plan = create_therapy_plan()
		self.assertEqual(plan.status, "Not Started")

		session = make_therapy_session(plan.patient, "Basic Rehab", "_Test Company", plan.name)
		frappe.get_doc(session).submit()
		self.assertEqual(frappe.db.get_value("Therapy Plan", plan.name, "status"), "In Progress")

		session = make_therapy_session(plan.patient, "Basic Rehab", "_Test Company", plan.name)
		frappe.get_doc(session).submit()
		self.assertEqual(frappe.db.get_value("Therapy Plan", plan.name, "status"), "Completed")

		patient, practitioner = create_healthcare_docs()
		appointment = create_appointment(patient, practitioner, nowdate())

		session = make_therapy_session(
			plan.patient, "Basic Rehab", "_Test Company", plan.name, appointment.name
		)
		session = frappe.get_doc(session)
		session.submit()
		self.assertEqual(
			frappe.db.get_value("Patient Appointment", appointment.name, "status"), "Closed"
		)
		session.cancel()
		self.assertEqual(frappe.db.get_value("Patient Appointment", appointment.name, "status"), "Open")

	def test_therapy_plan_from_template(self):
		patient = create_patient()
		template = create_therapy_plan_template()
		# check linked item
		self.assertTrue(frappe.db.exists("Therapy Plan Template", {"linked_item": "Complete Rehab"}))

		plan = create_therapy_plan(template)
		# invoice
		si = make_sales_invoice(plan.name, patient, "_Test Company", template)
		si.save()

		therapy_plan_template_amt = frappe.db.get_value(
			"Therapy Plan Template", template, "total_amount"
		)
		self.assertEqual(si.items[0].amount, therapy_plan_template_amt)


def create_therapy_plan(template=None, patient=None):
	if not patient:
		patient = create_patient()
	therapy_type = create_therapy_type()
	plan = frappe.new_doc("Therapy Plan")
	plan.patient = patient
	plan.start_date = getdate()

	if template:
		plan.therapy_plan_template = template
		plan = plan.set_therapy_details_from_template()
	else:
		plan.append("therapy_plan_details", {"therapy_type": therapy_type.name, "no_of_sessions": 2})

	plan.save()
	return plan


def create_encounter(patient, medical_department, practitioner, submit=True):
	encounter = frappe.new_doc("Patient Encounter")
	encounter.patient = patient
	encounter.practitioner = practitioner
	encounter.medical_department = medical_department
	encounter.appointment_type = create_appointment_type().name
	encounter.source = "Direct"
	therapy_type = create_therapy_type()
	encounter.append("therapies", {"therapy_type": therapy_type.name, "no_of_sessions": 2})
	encounter.save()
	if submit:
		encounter.submit()
	return encounter


def create_therapy_plan_template():
	template_name = frappe.db.exists("Therapy Plan Template", "Complete Rehab")
	if not template_name:
		therapy_type = create_therapy_type()
		template = frappe.new_doc("Therapy Plan Template")
		template.plan_name = template.item_code = template.item_name = "Complete Rehab"
		template.item_group = "Services"
		rate = frappe.db.get_value("Therapy Type", therapy_type.name, "rate")
		template.append(
			"therapy_types",
			{"therapy_type": therapy_type.name, "no_of_sessions": 2, "rate": rate, "amount": 2 * flt(rate)},
		)
		template.save()
		template_name = template.name

	return template_name
