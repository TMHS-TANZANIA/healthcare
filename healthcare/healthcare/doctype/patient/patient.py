# -*- coding: utf-8 -*-
# Copyright (c) 2015, ESS LLP and contributors
# For license information, please see license.txt


import dateutil

import frappe
from frappe import _
from frappe.contacts.address_and_contact import load_address_and_contact
from frappe.contacts.doctype.contact.contact import get_default_contact
from frappe.model.document import Document
from frappe.model.naming import set_name_by_naming_series, set_name_from_naming_options
from frappe.utils import cint, cstr, getdate
from frappe.utils.nestedset import get_root_of

from erpnext import get_default_currency
from erpnext.accounts.party import get_dashboard_info
from erpnext.selling.doctype.customer.customer import make_address

from healthcare.healthcare.doctype.healthcare_settings.healthcare_settings import (
	get_income_account,
	get_receivable_account,
	send_registration_sms,
)


class Patient(Document):
	def onload(self):
		"""Load address and contacts in `__onload`"""
		load_address_and_contact(self)
		self.load_dashboard_info()

	def validate(self):
		self.set_full_name()
		self.flags.is_new_doc = self.is_new()
		self.flags.existing_customer = self.is_new() and bool(self.customer)

	def before_insert(self):
		self.set_missing_customer_details()

	def after_insert(self):
		if frappe.db.get_single_value("Healthcare Settings", "collect_registration_fee"):
			frappe.db.set_value("Patient", self.name, "status", "Disabled")
		else:
			send_registration_sms(self)
		self.reload()

	def on_update(self):
		if frappe.db.get_single_value("Healthcare Settings", "link_customer_to_patient"):
			if self.customer:
				if self.flags.existing_customer or frappe.db.exists(
					{"doctype": "Patient", "name": ["!=", self.name], "customer": self.customer}
				):
					self.update_patient_based_on_existing_customer()
				else:
					self.update_linked_customer()

			else:
				create_customer(self)

		self.set_contact()  # add or update contact

		if self.flags.is_new_doc and self.get("address_line1"):
			make_address(self)

		if not self.user_id and self.email and self.invite_user:
			self.create_website_user()

	def load_dashboard_info(self):
		if self.customer:
			info = get_dashboard_info("Customer", self.customer, None)
			self.set_onload("dashboard_info", info)

	def set_full_name(self):
		self.patient_name = " ".join(
			[name for name in [self.first_name, self.middle_name, self.last_name] if name]
		)

	def set_missing_customer_details(self):
		if not self.customer_group:
			self.customer_group = frappe.db.get_single_value(
				"Selling Settings", "customer_group"
			) or get_root_of("Customer Group")
		if not self.territory:
			self.territory = frappe.db.get_single_value("Selling Settings", "territory") or get_root_of(
				"Territory"
			)
		if not self.default_price_list:
			self.default_price_list = frappe.db.get_single_value("Selling Settings", "selling_price_list")

		if not self.customer_group or not self.territory or not self.default_price_list:
			frappe.msgprint(
				_(
					"Please set defaults for Customer Group, Territory and Selling Price List in Selling Settings"
				),
				alert=True,
			)

		if not self.default_currency:
			self.default_currency = get_default_currency()
		if not self.language:
			self.language = frappe.db.get_single_value("System Settings", "language")

	def create_website_user(self):
		filters = {"email": self.email}
		if self.mobile:
			filters["mobile_no"] = self.mobile
		users = frappe.db.get_all(
			"User",
			fields=["email", "mobile_no"],
			or_filters=filters,
		)

		if users and users[0]:
			message = _("User exists with Email {}").format(frappe.bold(users[0].email))

			if users[0].mobile_no:
				message += _(", Mobile {}").format(frappe.bold(users[0].mobile_no))

			message += _(
				"<br>Please check email / mobile or disable 'Invite as User' to skip creating User"
			)

			frappe.throw(message, frappe.DuplicateEntryError)

		user = frappe.get_doc(
			{
				"doctype": "User",
				"first_name": self.first_name,
				"last_name": self.last_name,
				"email": self.email,
				"user_type": "Website User",
				"gender": self.sex,
				"phone": self.phone,
				"mobile_no": self.mobile,
				"birth_date": self.dob,
			}
		)
		user.flags.ignore_permissions = True
		user.enabled = True
		user.send_welcome_email = True
		user.add_roles("Patient")
		self.db_set("user_id", user.name)

	def autoname(self):
		patient_name_by = frappe.db.get_single_value("Healthcare Settings", "patient_name_by")
		if patient_name_by == "Patient Name":
			self.name = self.get_patient_name()
		elif patient_name_by == "Naming Series":
			set_name_by_naming_series(self)
		else:
			set_name_from_naming_options(frappe.get_meta(self.doctype).autoname, self)

	def get_patient_name(self):
		self.set_full_name()
		name = self.patient_name
		if frappe.db.get_value("Patient", name):
			count = frappe.db.sql(
				"""select ifnull(MAX(CAST(SUBSTRING_INDEX(name, ' ', -1) AS UNSIGNED)), 0) from tabPatient
				 where name like %s""",
				"%{0} - %".format(name),
				as_list=1,
			)[0][0]
			count = cint(count) + 1
			return "{0} - {1}".format(name, cstr(count))

		return name

	@property
	def age(self):
		if not self.dob:
			return
		dob = getdate(self.dob)
		age = dateutil.relativedelta.relativedelta(getdate(), dob)
		return age

	def get_age(self):
		age = self.age
		if not age:
			return
		age_str = f'{str(age.years)} {_("Year(s)")} {str(age.months)} {_("Month(s)")} {str(age.days)} {_("Day(s)")}'
		return age_str

	@frappe.whitelist()
	def invoice_patient_registration(self):
		if frappe.db.get_single_value("Healthcare Settings", "registration_fee"):
			company = frappe.defaults.get_user_default("company")
			if not company:
				company = frappe.db.get_single_value("Global Defaults", "default_company")

			sales_invoice = make_invoice(self.name, company)
			sales_invoice.save(ignore_permissions=True)
			frappe.db.set_value("Patient", self.name, "status", "Active")
			send_registration_sms(self)

			return {"invoice": sales_invoice.name}

	def set_contact(self):
		contact = get_default_contact(self.doctype, self.name)

		if contact:
			old_doc = self.get_doc_before_save()
			if not old_doc:
				return

			if old_doc.email != self.email or old_doc.mobile != self.mobile or old_doc.phone != self.phone:
				self.update_contact(contact)
		else:
			if self.customer:
				# customer contact exists, link patient
				contact = get_default_contact("Customer", self.customer)

			if contact:
				self.update_contact(contact)
			else:
				self.reload()
				if self.email or self.mobile or self.phone:
					contact = frappe.get_doc(
						{
							"doctype": "Contact",
							"first_name": self.first_name,
							"middle_name": self.middle_name,
							"last_name": self.last_name,
							"gender": self.sex,
							"is_primary_contact": 1,
						}
					)
					contact.append("links", dict(link_doctype="Patient", link_name=self.name))
					if self.customer:
						contact.append("links", dict(link_doctype="Customer", link_name=self.customer))

					contact.insert(ignore_permissions=True)
					self.update_contact(contact.name)

	def update_contact(self, contact):
		contact = frappe.get_doc("Contact", contact)

		if not contact.has_link(self.doctype, self.name):
			contact.append("links", dict(link_doctype=self.doctype, link_name=self.name))

		if self.email and self.email != contact.email_id:
			for email in contact.email_ids:
				email.is_primary = True if email.email_id == self.email else False
			contact.add_email(self.email, is_primary=True)
			contact.set_primary_email()

		if self.mobile and self.mobile != contact.mobile_no:
			for mobile in contact.phone_nos:
				mobile.is_primary_mobile_no = True if mobile.phone == self.mobile else False
			contact.add_phone(self.mobile, is_primary_mobile_no=True)
			contact.set_primary("mobile_no")

		if self.phone and self.phone != contact.phone:
			for phone in contact.phone_nos:
				phone.is_primary_phone = True if phone.phone == self.phone else False
			contact.add_phone(self.phone, is_primary_phone=True)
			contact.set_primary("phone")

		contact.flags.skip_patient_update = True
		contact.save(ignore_permissions=True)

	def calculate_age(self, ref_date=None):
		if self.dob:
			if not ref_date:
				ref_date = frappe.utils.nowdate()
			diff = frappe.utils.date_diff(ref_date, self.dob)
			years = diff // 365
			months = (diff - (years * 365)) // 30
			days = (diff - (years * 365)) - (months * 30)
			return {
				"age_in_string": f'{str(years)} {_("Year(s)")} {str(months)} {_("Month(s)")} {str(days)} {_("Day(s)")}',
				"age_in_days": diff,
			}

	def update_linked_customer(self):
		customer = frappe.get_doc("Customer", self.customer)
		if self.customer_group:
			customer.customer_group = self.customer_group
		if self.territory:
			customer.territory = self.territory
		customer.customer_name = self.patient_name
		customer.default_price_list = self.default_price_list
		customer.default_currency = self.default_currency
		customer.language = self.language
		customer.image = self.image
		customer.ignore_mandatory = True
		customer.save(ignore_permissions=True)

		frappe.msgprint(_("Customer {0} updated").format(customer.name), alert=True)

	def update_patient_based_on_existing_customer(self):
		customer = frappe.get_doc("Customer", self.customer)
		self.db_set(
			{
				"customer_group": customer.customer_group,
				"territory": customer.territory,
				"default_price_list": customer.default_price_list,
				"default_currency": customer.default_currency,
				"language": customer.language,
			}
		)
		self.notify_update()


def create_customer(doc):
	customer = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": doc.patient_name,
			"customer_group": doc.customer_group
			or frappe.db.get_single_value("Selling Settings", "customer_group"),
			"territory": doc.territory or frappe.db.get_single_value("Selling Settings", "territory"),
			"customer_type": "Individual",
			"default_currency": doc.default_currency,
			"default_price_list": doc.default_price_list,
			"language": doc.language,
			"image": doc.image,
		}
	).insert(ignore_permissions=True, ignore_mandatory=True)

	frappe.db.set_value("Patient", doc.name, "customer", customer.name)
	frappe.msgprint(_("Customer {0} created and linked to Patient").format(customer.name), alert=True)


def make_invoice(patient, company):
	uom = frappe.db.exists("UOM", "Nos") or frappe.db.get_single_value("Stock Settings", "stock_uom")
	sales_invoice = frappe.new_doc("Sales Invoice")
	sales_invoice.customer = frappe.db.get_value("Patient", patient, "customer")
	sales_invoice.patient = patient
	sales_invoice.due_date = getdate()
	sales_invoice.company = company
	sales_invoice.is_pos = 0
	sales_invoice.debit_to = get_receivable_account(company)

	item_line = sales_invoice.append("items")
	item_line.item_name = "Registration Fee"
	item_line.description = "Registration Fee"
	item_line.qty = 1
	item_line.uom = uom
	item_line.conversion_factor = 1
	item_line.income_account = get_income_account(None, company)
	item_line.rate = frappe.db.get_single_value("Healthcare Settings", "registration_fee")
	item_line.amount = item_line.rate
	sales_invoice.set_missing_values()
	return sales_invoice


@frappe.whitelist()
def get_patient_detail(patient):
	patient_dict = frappe.db.sql("""select * from tabPatient where name=%s""", (patient), as_dict=1)
	if not patient_dict:
		frappe.throw(_("Patient not found"))
	vital_sign = frappe.db.sql(
		"""select * from `tabVital Signs` where patient=%s
		order by signs_date desc limit 1""",
		(patient),
		as_dict=1,
	)

	details = patient_dict[0]
	if vital_sign:
		vital_sign[0].pop("inpatient_record")
		details.update(vital_sign[0])
	return details
