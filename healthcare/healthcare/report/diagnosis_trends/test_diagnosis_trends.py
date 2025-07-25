import frappe
from frappe import DuplicateEntryError
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, add_months, getdate

from healthcare.healthcare.doctype.patient_appointment.test_patient_appointment import (
	create_appointment_type,
	create_practitioner,
)
from healthcare.healthcare.doctype.therapy_plan.test_therapy_plan import create_encounter
from healthcare.healthcare.report.diagnosis_trends.diagnosis_trends import execute

months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


class TestDiagnosisTrends(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		cls.create_diagnosis()

	@classmethod
	def create_diagnosis(cls):
		medical_department = frappe.get_doc(
			{"doctype": "Medical Department", "department": "Cardiology"}
		)
		try:
			medical_department.insert()
		except DuplicateEntryError:
			pass

		patient = frappe.get_list("Patient")[0]
		practitioner_name = create_practitioner(medical_department=medical_department.name)
		encounter_cardiology = create_encounter(
			patient=patient.name,
			medical_department=medical_department,
			practitioner=practitioner_name,
			submit=False,
		)

		try:
			cls.diagnosis = frappe.get_doc(
				{
					"doctype": "Diagnosis",
					"diagnosis": "Fever",
				}
			)
			cls.diagnosis.insert()
		except DuplicateEntryError:
			pass

		try:
			cls.diagnosis_cardio = frappe.get_doc(
				{
					"doctype": "Diagnosis",
					"diagnosis": "Heart Attack",
				}
			)
			cls.diagnosis_cardio.insert()
		except DuplicateEntryError:
			pass

		encounter = frappe.get_doc("Patient Encounter", encounter_cardiology.name)
		encounter.append(
			"diagnosis",
			{
				"diagnosis": "Fever",
			},
		)
		encounter.source = "Direct"
		encounter.appointment_type = create_appointment_type().name
		encounter.save()

		encounter_cardiology.reload()
		encounter_cardiology.append(
			"diagnosis",
			{
				"diagnosis": "Heart Attack",
			},
		)
		encounter.source = "Direct"
		encounter.appointment_type = create_appointment_type().name
		encounter_cardiology.save()

	def test_report_data(self):
		filters = {
			"from_date": str(add_months(getdate(), -12)),
			"to_date": str(add_days(getdate(), 1)),
			"range": "Monthly",
		}

		report = execute(filters)
		data = [i["diagnosis"] for i in report[1]]
		self.assertIn(self.diagnosis.diagnosis, data)

	def test_report_data_with_filters(self):
		medical_department = frappe.get_doc("Medical Department", "Cardiology")

		filters = {
			"from_date": str(add_months(getdate(), -12)),
			"to_date": str(add_days(getdate(), 1)),
			"range": "Monthly",
			"department": medical_department.name,
		}
		report = execute(filters)

		data = [i["diagnosis"] for i in report[1]]

		self.assertIn(self.diagnosis_cardio.diagnosis, data)
