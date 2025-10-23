from typing import List
from datetime import datetime
from models import (
    PatientFullModel,
    PatientLogin,
    SurgeryDetails,
    ConsentForm,
    PreOpChecklist,
    SlotBooking,
    BillingInfo,
    WatchData,
    TabletPrescribed,
    RehabSection,
    TodaysMeal
)

FHIR_BASE_PROFILE = "http://hl7.org/fhir/StructureDefinition"

# ------------------ 1️⃣ Patient ------------------
def fhir_patient_resource(login: PatientLogin) -> dict:
    """FHIR R4 Patient inside a transaction Bundle"""

    patient_resource = {
        "resourceType": "Patient",
        "id": login.uhid,
        "identifier": [
            {"system": "https://hospital.com/uhid", "value": login.uhid}
        ],
        "active": True,
        "meta": {"profile": [f"{FHIR_BASE_PROFILE}/Patient"]}
    }

    bundle_resource = {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {
                "resource": patient_resource,
                "request": {"method": "POST", "url": "Patient"}
            }
        ]
    }
    return bundle_resource


# ------------------ 2️⃣ Surgery (Procedure) ------------------
def fhir_surgery_resources(uhid: str, surgeries: List[SurgeryDetails]) -> dict:
    """
    FHIR R4 transaction Bundle containing the Patient resource and multiple Procedure resources.
    Each entry directly contains a resource (Patient or Procedure), not a nested Bundle.
    """

    entries = []

    # Patient resource (directly as entry)
    patient_resource = {
        "resourceType": "Patient",
        "id": uhid,
        "identifier": [{"system": "https://hospital.com/uhid", "value": uhid}],
        "active": True,
        "meta": {"profile": [f"{FHIR_BASE_PROFILE}/Patient"]}
    }

    entries.append({
        "resource": patient_resource,
        "request": {"method": "POST", "url": "Patient"}
    })

    # Procedure resources
    for s in surgeries:
        procedure_resource = {
            "resourceType": "Procedure",
            "id": s.surgery_id,
            "identifier": [{"system": "https://hospital.com/uhid", "value": uhid}],
            "status": "completed",
            "category": {
                "coding": [{
                    "system": "http://snomed.info/sct",
                    "code": "387713003",
                    "display": "Surgical procedure"
                }]
            },
            "code": {"text": s.surgery_type},
            "subject": {"reference": f"Patient/{uhid}"},
            "performedDateTime": datetime.now().isoformat(),
            "note": [
                {"text": f"Video: {s.video_link or 'N/A'}"},
                {"text": f"Content: {s.content_link or 'N/A'}"}
            ],
            "meta": {"profile": [f"{FHIR_BASE_PROFILE}/Procedure"]}
        }

        entries.append({
            "resource": procedure_resource,
            "request": {"method": "POST", "url": "Procedure"}
        })

    # Return a single transaction Bundle
    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": entries
    }

# ------------------ 3️⃣ Consent ------------------
def fhir_consent_resource(uhid: str, consent: ConsentForm) -> dict:
    """Convert full ConsentForm details into a FHIR R4 Consent resource with all fields included."""
    
    consent_resource = {
        "resourceType": "Consent",
        "identifier": [{"system": "https://hospital.com/uhid", "value": uhid}],
        "status": "active" if consent.consent_form_approval == 1 else "inactive",
        "scope": {
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/consentscope",
                "code": "patient-privacy"
            }]
        },
        "category": [{"text": "Surgical Consent"}],
        "patient": {"reference": f"Patient/{uhid}"},
        "dateTime": consent.consent_form_approval_timestamp.isoformat(),
        "policyRule": {"text": "Hospital Terms & Conditions"},
        "sourceAttachment": {"url": consent.consent_form_upload_link},
        # Flatten filled_data and editable_fields as separate properties
        "filledData": consent.filled_data or {},
        "editableFields": consent.editable_fields or {},
        # Include all other consent fields as individual values
        "termsAndConditions": consent.terms_and_conditions,
        "termsAndConditionsTimestamp": consent.terms_and_conditions_timestamp.isoformat(),
        "consentFormApproval": consent.consent_form_approval,
        "consentFormApprovalTimestamp": consent.consent_form_approval_timestamp.isoformat(),
        "consentFormUploadLink": consent.consent_form_upload_link,
        "consentFormUploadLinkTimestamp": consent.consent_form_upload_link_timestamp.isoformat(),
        "consentFormValidation": consent.consent_form_validation,
        "consentFormValidationTimestamp": consent.consent_form_validation_timestamp.isoformat()
    }

    return consent_resource


# ------------------ 4️⃣ Pre-Op Checklist (DocumentReference) ------------------
def fhir_preop_checklist_resources(uhid: str, checklist: PreOpChecklist) -> dict:
    entries = []

    for d in checklist.documents:
        doc = {
            "resourceType": "DocumentReference",
            "identifier": [{"system": "https://hospital.com/uhid", "value": uhid}],
            "status": "current",
            "type": {"text": d.document_name},
            "subject": {"reference": f"Patient/{uhid}"},
            "author": [{"display": d.assigned_by}],
            "authenticator": {"display": d.validated_by or "N/A"},
            "custodian": {"display": d.updated_by},
            "date": d.updated_timestamp.isoformat(),
            "description": f"Validation Timestamp: {d.validation_timestamp.isoformat() if d.validation_timestamp else 'N/A'}",
            "content": [
                {
                    "attachment": {
                        "url": d.document_link,
                        "title": d.document_name,
                        "creation": d.assigned_timestamp.isoformat()
                    }
                }
            ],
            "meta": {"profile": [f"{FHIR_BASE_PROFILE}/DocumentReference"]}
        }

        entries.append({"resource": doc, "request": {"method": "POST", "url": "DocumentReference"}})

    return {"resourceType": "Bundle", "type": "transaction", "entry": entries}




# ------------------ 5️⃣ Slot Booking (Appointment) ------------------
def fhir_slot_booking_resource(uhid: str, slot: SlotBooking) -> dict:
    """FHIR R4 Appointment inside a transaction Bundle with booking timestamp."""
    
    participants = [
        {"actor": {"reference": f"Patient/{uhid}"}, "status": "accepted"}
    ]

    appointment = {
        "resourceType": "Appointment",
        "identifier": [{"system": "https://hospital.com/uhid", "value": uhid}],
        "status": "booked",
        "description": "Surgery Slot Booking",
        "start": f"{slot.date}T{slot.time}",
        # Include booking timestamp as a separate property
        "created": slot.booking_timestamp.isoformat(),
        "participant": participants
    }

    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {
                "resource": appointment,
                "request": {"method": "POST", "url": "Appointment"}
            }
        ]
    }




# ------------------ 6️⃣ Billing (Account) ------------------
def fhir_billing_resource(uhid: str, billing: BillingInfo) -> dict:
    """FHIR R4 Account resource only (no transaction Bundle)"""
    account = {
        "resourceType": "Account",
        "identifier": [
            {"system": "https://hospital.com/uhid", "value": uhid},
            {"system": "https://hospital.com/invoice", "value": billing.invoice_number}
        ],
        "status": "active",
        "name": f"Invoice {billing.invoice_number}",
        "subject": {"reference": f"Patient/{uhid}"},
        "meta": {"profile": [f"{FHIR_BASE_PROFILE}/Account"]}
    }
    return account
    


# ------------------ 7️⃣ Watch Data (Observation) ------------------
def fhir_watchdata_resources(uhid: str, watch_data: WatchData) -> dict:
    """FHIR R4 Observation inside a transaction Bundle"""
    entries = []
    for category, entries_list in {
        "yearly": watch_data.yearly,
        "monthly": watch_data.monthly,
        "weekly": watch_data.weekly,
        "daily": watch_data.daily
    }.items():
        for entry in entries_list:
            for code, value, unit in [
                ("Heart Rate", entry.heart_rate, "beats/minute"),
                ("Step Count", entry.step_count, "steps"),
                ("Sleep Duration", entry.sleep_time, "hours")
            ]:
                if value is not None:
                    obs = {
                        "resourceType": "Observation",
                        "identifier": [{"system": "https://hospital.com/uhid", "value": uhid}],
                        "status": "final",
                        "category": [{
                            "coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": category}],
                            "text": category
                        }],
                        "code": {"text": code},
                        "subject": {"reference": f"Patient/{uhid}"},
                        "effectiveDateTime": entry.timestamp.isoformat(),
                        "valueQuantity": {"value": value, "unit": unit},
                        "meta": {"profile": [f"{FHIR_BASE_PROFILE}/Observation"]}
                    }
                    entries.append({"resource": obs, "request": {"method": "POST", "url": "Observation"}})

    return {"resourceType": "Bundle", "type": "transaction", "entry": entries}


# ------------------ 8️⃣ Tablet Prescribed (MedicationRequest) ------------------
def fhir_medication_resources(uhid: str, tablet_prescribed: TabletPrescribed) -> dict:
    """FHIR R4 MedicationRequest Bundle — store only doses_taken in note.text."""
    entries = []

    for t in tablet_prescribed.tablets:
        med_request = {
            "resourceType": "MedicationRequest",
            "identifier": [{"system": "https://hospital.com/uhid", "value": uhid}],
            "status": "active" if t.completed == 0 else "completed",
            "intent": "order",
            "subject": {"reference": f"Patient/{uhid}"},
            "authoredOn": datetime.combine(t.prescribed_date, datetime.min.time()).isoformat(),
            "medicationCodeableConcept": {"text": t.tablet_name},
            "dosageInstruction": [
                {
                    "text": f"{t.dosage}, Schedule: {t.schedule_pattern}, {'before food' if t.before_food else 'after food'}",
                    "timing": {
                        "repeat": {
                            "boundsDuration": {
                                "value": t.duration_days,
                                "unit": "days",
                                "system": "http://unitsofmeasure.org",
                                "code": "d"
                            }
                        }
                    }
                }
            ],
            # store only doses_taken as JSON
            "note": [
                {
                    "text": str([
                        {
                            "day": d.day.isoformat(),
                            "period": d.period,
                            "taken_timestamp": d.taken_timestamp.isoformat() if d.taken_timestamp else None
                        }
                        for d in t.doses_taken
                    ])
                }
            ],
            "meta": {"profile": [f"{FHIR_BASE_PROFILE}/MedicationRequest"]}
        }

        entries.append({
            "resource": med_request,
            "request": {"method": "POST", "url": "MedicationRequest"}
        })

    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": entries
    }




# ------------------ 9️⃣ Rehab Section (Task + Observation) ------------------
def fhir_exercise_resources(uhid: str, rehab: RehabSection) -> dict:
    """FHIR R4 Task resources (exercises) inside a transaction Bundle"""
    entries = []

    for ex in rehab.exercises:
        task = {
            "resourceType": "Task",
            "identifier": [{"system": "https://hospital.com/uhid", "value": uhid}],
            "status": "in-progress" if not ex.completed_timestamp else "completed",
            "intent": "order",
            "description": f"{ex.name} - {ex.reps} reps x {ex.sets} sets ({ex.difficulty})",
            "for": {"reference": f"Patient/{uhid}"},
            "executionPeriod": {
                "start": f"{ex.assigned_date}T{ex.assigned_time}",
                "end": ex.completed_timestamp.isoformat() if ex.completed_timestamp else None
            },
            # ✅ Include progress and duration_days
            "note": [
                {"text": f"Progress: {ex.progress_percentage}%"},
                {"text": f"Duration Days: {ex.duration_days}"}
            ],
            "meta": {"profile": [f"{FHIR_BASE_PROFILE}/Task"]}
        }

        # Add exercise video if available
        if ex.exercise_video:
            task["input"] = [
                {
                    "type": {"text": "Exercise Video"},
                    "valueUrl": ex.exercise_video
                }
            ]

        entries.append({"resource": task, "request": {"method": "POST", "url": "Task"}})

    return {"resourceType": "Bundle", "type": "transaction", "entry": entries}



def fhir_instruction_resources(uhid: str, rehab: RehabSection) -> dict:
    """FHIR R4 Observation resources (instructions) inside a transaction Bundle"""
    entries = []

    for instr in rehab.instructions:
        obs = {
            "resourceType": "Observation",
            "identifier": [{"system": "https://hospital.com/uhid", "value": uhid}],
            "status": "final",
            "code": {"text": "Rehabilitation Instruction"},
            "subject": {"reference": f"Patient/{uhid}"},
            "valueString": instr.instruction_text,
            "effectiveDateTime": instr.timestamp.isoformat(),
            "meta": {"profile": [f"{FHIR_BASE_PROFILE}/Observation"]}
        }
        entries.append({"resource": obs, "request": {"method": "POST", "url": "Observation"}})

    return {"resourceType": "Bundle", "type": "transaction", "entry": entries}




# ------------------ 🔟 Today's Meal (NutritionOrder) ------------------
def fhir_meal_resources(uhid: str, meals: TodaysMeal) -> dict:
    """FHIR R4 NutritionOrder inside a transaction Bundle"""
    entries = []
    for m in meals.meals:
        nutrition = {
            "resourceType": "NutritionOrder",
            "identifier": [{"system": "https://hospital.com/uhid", "value": uhid}],
            "status": "active",
            "intent": "order",  # Required field
            "patient": {"reference": f"Patient/{uhid}"},
            "dateTime": f"{m.assigned_date}T{m.assigned_time}",
            "oralDiet": {"type": [{"text": m.period}], "instruction": m.description},
            "meta": {"profile": [f"{FHIR_BASE_PROFILE}/NutritionOrder"]}
        }
        entries.append({"resource": nutrition, "request": {"method": "POST", "url": "NutritionOrder"}})

    return {"resourceType": "Bundle", "type": "transaction", "entry": entries}

