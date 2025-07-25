# Copyright (c) 2021, healthcare and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from healthcare.healthcare.doctype.clinical_procedure.test_clinical_procedure import (
	create_procedure,
)
from healthcare.healthcare.doctype.inpatient_record.inpatient_record import (
	admit_patient,
	discharge_patient,
)
from healthcare.healthcare.doctype.inpatient_record.test_inpatient_record import (
	create_inpatient,
	get_healthcare_service_unit,
)
from healthcare.healthcare.doctype.lab_test.test_lab_test import (
	create_lab_test,
	create_lab_test_template,
)
from healthcare.healthcare.doctype.nursing_task.nursing_task import NursingTask
from healthcare.healthcare.doctype.patient_appointment.test_patient_appointment import (
	create_clinical_procedure_template,
	create_healthcare_docs,
)
from healthcare.healthcare.doctype.therapy_plan.test_therapy_plan import create_therapy_plan
from healthcare.healthcare.doctype.therapy_session.test_therapy_session import (
	create_therapy_session,
)
from healthcare.healthcare.doctype.therapy_type.test_therapy_type import create_therapy_type


class TestNursingTask(IntegrationTestCase):
	def setUp(self) -> None:
		self.activity = frappe.get_doc(self.globalTestRecords["Nursing Checklist Template"][0]).insert(
			ignore_if_duplicate=True
		)
		self.nc_template = frappe.get_doc(
			self.globalTestRecords["Nursing Checklist Template"][1]
		).insert(ignore_if_duplicate=True)

		self.settings = frappe.get_single("Healthcare Settings")
		self.settings.validate_nursing_checklists = 1
		self.settings.save()

		self.patient, self.practitioner = create_healthcare_docs()

	def test_lab_test_submission_should_validate_pending_nursing_tasks(self):
		self.lt_template = create_lab_test_template()
		self.lt_template.nursing_checklist_template = self.nc_template.name
		self.lt_template.save()

		lab_test = create_lab_test(self.lt_template)
		lab_test.descriptive_test_items[0].result_value = 12
		lab_test.descriptive_test_items[1].result_value = 1
		lab_test.descriptive_test_items[2].result_value = 2.3
		lab_test.save()

		start_nursing_tasks(lab_test)

		self.assertRaises(frappe.ValidationError, lab_test.submit)

		complete_nursing_tasks(lab_test)
		lab_test.submit()

	def test_start_clinical_procedure_should_validate_pending_nursing_tasks(self):
		procedure_template = create_clinical_procedure_template()
		procedure_template.allow_stock_consumption = 1
		procedure_template.pre_op_nursing_checklist_template = self.nc_template.name
		procedure_template.save()

		procedure = create_procedure(procedure_template, self.patient, self.practitioner)
		start_nursing_tasks(procedure)

		self.assertRaises(frappe.ValidationError, procedure.start_procedure)

		complete_nursing_tasks(procedure)
		procedure.start_procedure()

	def test_admit_discharge_inpatient_should_validate_pending_nursing_tasks(self):
		"""nursing tasks on admit and discharge of same ip_record"""
		self.settings.allow_discharge_despite_unbilled_services = 1
		self.settings.save()

		ip_record = create_inpatient(self.patient)
		ip_record.admission_nursing_checklist_template = self.nc_template.name
		ip_record.expected_length_of_stay = 0
		ip_record.save(ignore_permissions=True)
		NursingTask.create_nursing_tasks_from_template(
			ip_record.admission_nursing_checklist_template, ip_record, start_time=now_datetime()
		)
		start_nursing_tasks(ip_record)

		service_unit = get_healthcare_service_unit()
		kwargs = {
			"inpatient_record": ip_record,
			"service_unit": service_unit,
			"check_in": now_datetime(),
		}
		self.assertRaises(frappe.ValidationError, admit_patient, **kwargs)

		complete_nursing_tasks(ip_record)
		admit_patient(**kwargs)

		ip_record.discharge_nursing_checklist_template = self.nc_template.name
		ip_record.save()
		NursingTask.create_nursing_tasks_from_template(
			ip_record.admission_nursing_checklist_template, ip_record, start_time=now_datetime()
		)
		start_nursing_tasks(ip_record)

		self.assertRaises(frappe.ValidationError, discharge_patient, inpatient_record=ip_record)

		complete_nursing_tasks(ip_record)
		discharge_patient(ip_record)

	def test_submit_therapy_session_should_validate_pending_nursing_tasks(self):
		therapy_type = create_therapy_type()
		therapy_type.nursing_checklist_template = self.nc_template.name
		therapy_type.save()

		therapy_plan = create_therapy_plan()
		therapy_session = create_therapy_session(self.patient, therapy_type.name, therapy_plan.name)
		start_nursing_tasks(therapy_session)

		self.assertRaises(frappe.ValidationError, therapy_session.submit)

		complete_nursing_tasks(therapy_session)
		therapy_session.submit()


def start_nursing_tasks(document):
	filters = {
		"reference_name": document.name,
		"mandatory": 1,
		"status": ["not in", ["Completed", "Cancelled"]],
	}
	tasks = frappe.get_all("Nursing Task", filters=filters)
	for task_name in tasks:
		task = frappe.get_doc("Nursing Task", task_name)
		task.submit()
		task.status = "In Progress"  # should set task_start_time
		task.save()


def complete_nursing_tasks(document):
	filters = {
		"reference_name": document.name,
		"mandatory": 1,
		"status": ["not in", ["Completed", "Cancelled"]],
	}
	tasks = frappe.get_all("Nursing Task", filters=filters)
	for task_name in tasks:
		task = frappe.get_doc("Nursing Task", task_name)
		task.status = "Completed"
		task.task_document_name = create_vital_signs(document.patient).name
		task.save()


def create_vital_signs(patient):
	return frappe.get_doc(
		{
			"doctype": "Vital Signs",
			"patient": patient,
			"signs_date": frappe.utils.nowdate(),
			"signs_time": frappe.utils.nowtime(),
			"bp_systolic": 120,
			"bp_diastolic": 80,
		}
	).insert(ignore_if_duplicate=True)
