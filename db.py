import base64
from typing import Any, Dict, List
from datetime import datetime
from models import (
    ConsentFormData,
    ConsentFormStatus,
    PatientFullModel,
    PatientLogin,
    SurgeryDetails,
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

# ------------------ 3️⃣ Consent form ------------------
def fhir_consent_resource_structured(uhid: str, consent: "ConsentFormData") -> Dict[str, Any]:
    """Convert ConsentFormData into a FHIR-valid Consent Bundle using structured codes for every field."""

    # --- BasicDetails mapping ---
    bd = consent.basic_details
    basic_details_codes = [
        {"coding": [{"system": "http://hospital.com/patient", "code": "first-name", "display": bd.first_name}]},
        {"coding": [{"system": "http://hospital.com/patient", "code": "last-name", "display": bd.last_name}]},
        {"coding": [{"system": "http://hospital.com/patient", "code": "date-of-birth", "display": bd.date_of_birth.isoformat()}]},
        {"coding": [{"system": "http://hospital.com/patient", "code": "hospital-registration-number", "display": bd.hospital_registration_number}]}
    ]
    if bd.responsible_attender_name:
        basic_details_codes.append({"coding": [{"system": "http://hospital.com/patient", "code": "responsible-attender", "display": bd.responsible_attender_name}]})
    if bd.requirements:
        basic_details_codes.append({"coding": [{"system": "http://hospital.com/patient", "code": "requirements", "display": bd.requirements}]})


    # --- SurgeryDetails mapping ---
    sd = consent.surgery_details
    surgery_codes = [
        {"coding": [{"system": "http://hospital.com/surgery", "code": "indication", "display": sd.indication}]}
    ]
    if sd.extra_procedures:
        surgery_codes.append({"coding": [{"system": "http://hospital.com/surgery", "code": "extra-procedures", "display": sd.extra_procedures}]})
    if sd.site_and_side:
        surgery_codes.append({"coding": [{"system": "http://hospital.com/surgery", "code": "site-and-side", "display": sd.site_and_side}]})
    if sd.alternatives_considered:
        surgery_codes.append({"coding": [{"system": "http://hospital.com/surgery", "code": "alternatives-considered", "display": sd.alternatives_considered}]})


    # --- Risks mapping ---
    risk_codings = []
    for r in consent.risks:
        risk_codings.append({
            "coding": [{"system": "http://hospital.com/risks", "code": r.risk_name.lower().replace(" ", "-"), "display": r.description}],
            "text": r.factors_increasing_risk or ""
        })


    # --- Patient Specific Risks/Concerns mapping ---
    patient_risks_codes = []
    if consent.patient_specific_risks and consent.patient_specific_risks.patient_specific_risks:
        patient_risks_codes.append({
            "coding": [{"system": "http://hospital.com/patient-specific-risks", "code": "patient-specific-risks", "display": consent.patient_specific_risks.patient_specific_risks}]
        })
    patient_concerns_codes = []
    if consent.patient_specific_concerns:
        if consent.patient_specific_concerns.blood_transfusion:
            patient_concerns_codes.append({"coding": [{"system": "http://hospital.com/patient-specific-concerns", "code": "blood-transfusion", "display": consent.patient_specific_concerns.blood_transfusion}]})
        if consent.patient_specific_concerns.other_procedures:
            patient_concerns_codes.append({"coding": [{"system": "http://hospital.com/patient-specific-concerns", "code": "other-procedures", "display": consent.patient_specific_concerns.other_procedures}]})


    # --- Additional Consent mapping ---
    additional_codes = []
    if consent.additional_consent:
        ac = consent.additional_consent
        additional_codes.extend([
            {"coding": [{"system": "http://hospital.com/additional-consent", "code": "allows-education-research-use", "display": str(ac.allows_education_research_use)}]},
            {"coding": [{"system": "http://hospital.com/additional-consent", "code": "allows-research-access-to-records", "display": str(ac.allows_research_access_to_records)}]}
        ])
        if ac.pregnant_risk_confirmed is not None:
            additional_codes.append({"coding": [{"system": "http://hospital.com/additional-consent", "code": "pregnant-risk-confirmed", "display": str(ac.pregnant_risk_confirmed)}]})
        additional_codes.append({"coding": [{"system": "http://hospital.com/additional-consent", "code": "additional-name", "display": ac.additional_name}]})
        additional_codes.append({"coding": [{"system": "http://hospital.com/additional-consent", "code": "additional-date", "display": ac.addittional_date}]})
        if ac.caretaker_name:
            additional_codes.append({"coding": [{"system": "http://hospital.com/additional-consent", "code": "caretaker-name", "display": ac.caretaker_name}]})
        if ac.relationship_to_patient:
            additional_codes.append({"coding": [{"system": "http://hospital.com/additional-consent", "code": "relationship-to-patient", "display": ac.relationship_to_patient}]})
        if ac.reason_for_surrogate_consent:
            additional_codes.append({"coding": [{"system": "http://hospital.com/additional-consent", "code": "reason-for-surrogate-consent", "display": ac.reason_for_surrogate_consent}]})


    # --- Combine all codes into provision_codes ---
    provision_codes = basic_details_codes + surgery_codes + patient_risks_codes + patient_concerns_codes + risk_codings + additional_codes

    # --- Health Professional Statement mapping (all fields) ---
    verification_entries = []
    if consent.health_professional_statement:
        hps = consent.health_professional_statement
        verification_entries.append({
            "verified": True,
            "verifiedWith": {"display": hps.name},
            "verificationDate": hps.date.isoformat() if hps.date else None
        })
        provision_codes.extend([
            {"coding": [{"system": "http://hospital.com/health-professional", "code": "job-title", "display": hps.job_title}]}
        ])
        if hps.signature:
            provision_codes.append({"coding": [{"system": "http://hospital.com/health-professional", "code": "signature", "display": hps.signature}]})
        if hps.patient_information_leaflet_provided is not None:
            provision_codes.append({"coding": [{"system": "http://hospital.com/health-professional", "code": "patient-info-leaflet-provided", "display": str(hps.patient_information_leaflet_provided)}]})
        if hps.patient_information_leaflet_provided_details:
            provision_codes.append({"coding": [{"system": "http://hospital.com/health-professional", "code": "patient-info-leaflet-details", "display": hps.patient_information_leaflet_provided_details}]})
        if hps.copy_accepted_by_patient is not None:
            provision_codes.append({"coding": [{"system": "http://hospital.com/health-professional", "code": "copy-accepted-by-patient", "display": str(hps.copy_accepted_by_patient)}]})

    # --- Patient Statement mapping (all fields) ---
    if consent.patient_statement:
        ps = consent.patient_statement
        verification_entries.append({
            "verified": True,
            "verifiedWith": {"display": ps.interpreter_or_witness_name or "Patient/Interpreter"}
        })
        provision_codes.extend([
            {"coding": [{"system": "http://hospital.com/patient-statement", "code": "interpreter-or-witness-name", "display": ps.interpreter_or_witness_name or ""}]}
        ])
        if ps.interpreter_or_witness_signature:
            provision_codes.append({"coding": [{"system": "http://hospital.com/patient-statement", "code": "interpreter-or-witness-signature", "display": ps.interpreter_or_witness_signature}]})
        provision_codes.append({"coding": [{"system": "http://hospital.com/patient-statement", "code": "information-interpreted", "display": str(ps.information_interpreted)}]})


    # --- Construct Consent resource ---
    consent_resource = {
        "resourceType": "Consent",
        "identifier": [{"system": "https://hospital.com/uhid", "value": uhid}],
        "status": "active",
        "scope": {
            "coding": [{"system": "http://terminology.hl7.org/CodeSystem/consentscope", "code": "treatment", "display": "Treatment"}]
        },
        "category": [{"coding": [{"system": "http://loinc.org", "code": "57016-8", "display": "Consent for surgical procedure"}]}],
        "patient": {"reference": f"Patient/{uhid}"},
        "policy": [],
        "verification": verification_entries,
        "provision": {
            "type": "permit",
            "actor": [{"role": {"text": "Patient"}, "reference": {"reference": f"Patient/{uhid}"}}],
            "code": provision_codes
        },
        "meta": {
        "profile": [f"{FHIR_BASE_PROFILE}/Consent"],
        "tag": [
            {
                "system": "https://hospital.com/internal",
                "code": "ConsentFormData",
                "display": "Internal ConsentFormData resource"
            }
        ]
    }
    }

    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [{"resource": consent_resource, "request": {"method": "POST", "url": "Consent"}}]
    }

# ------------------ 3️⃣ Consent form status ------------------
def fhir_consent_form_status_resources(
    uhid: str, consent_status: ConsentFormStatus
) -> Dict:
    """Create a clean FHIR R4 Bundle for ConsentFormStatus using all fields, no practitioner."""

    status_map = {0: "draft", 1: "active"}
    approval_map = {0: "draft", 1: "active", 2: "rejected"}

    consent_resource = {
        "resourceType": "Consent",
        "identifier": [{"system": "https://hospital.com/uhid", "value": uhid}],
        "status": status_map.get(consent_status.status, "draft"),
        "scope": {
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/consentscope",
                "code": "treatment",
                "display": "Treatment"
            }]
        },
        "category": [{
            "coding": [{
                "system": "http://loinc.org",
                "code": "57016-8",
                "display": "Consent for surgical procedure"
            }]
        }],
        "patient": {"reference": f"Patient/{uhid}"},
        "dateTime": consent_status.status_timestamp.isoformat(),
        "policy": [
            {"authority": "https://ndhm.gov.in", "uri": "https://ndhm.gov.in/consent"},
            {"authority": "https://hhs.gov/hipaa", "uri": "https://hhs.gov/hipaa/consent"}
        ],
        "sourceAttachment": {
            "contentType": "application/pdf",
            "url": consent_status.document_url,
            "title": "Signed Consent Form",
            "creation": consent_status.document_creation.isoformat()
        },
        "provision": {
            "type": "permit" if consent_status.validation == 1 else "deny",
            "period": {
                "start": consent_status.approval_timestamp.isoformat(),
                "end": consent_status.validation_timestamp.isoformat()
            },
            "actor": [
                {"role": {"text": f"Patient (Approval: {approval_map.get(consent_status.approval, 'draft')})"},
                 "reference": {"reference": f"Patient/{uhid}"}}
            ]
        },
        # Add a tag to indicate this is your internal ConsentFormStatus
        "meta": {
            "profile": [f"{FHIR_BASE_PROFILE}/Consent"],
            "tag": [
                {
                    "system": "https://hospital.com/internal",
                    "code": "ConsentFormStatus",
                    "display": "Internal ConsentFormStatus resource"
                }
            ]
        }
    }

    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [{"resource": consent_resource, "request": {"method": "POST", "url": "Consent"}}]
    }





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
    """Create a FHIR R4 NutritionOrder Bundle representing all meals for a patient."""
    entries = []

    for m in meals.meals:
        nutrition = {
            "resourceType": "NutritionOrder",
            "identifier": [
                {"system": "https://hospital.com/uhid", "value": uhid},
                {"system": "https://hospital.com/meal-id", "value": m.meal_name},
            ],
            "status": "completed" if m.completed_timestamp else "active",
            "intent": "order",
            "patient": {"reference": f"Patient/{uhid}"},
            "dateTime": f"{m.assigned_date}T{m.assigned_time}",
            "oralDiet": {
                "type": [{"text": m.period}],
                "instruction": m.description,
            },
            "note": [
                {"text": f"Meal: {m.meal_name}"},
                {"text": f"Assigned date: {m.assigned_date}"},
                {"text": f"Assigned time: {m.assigned_time}"},
            ],
            "meta": {
                "profile": [f"{FHIR_BASE_PROFILE}/NutritionOrder"]
            },
        }

        # ✅ Add completion info only if available
        if m.completed_timestamp is not None:
            nutrition["note"].append(
                {"text": f"Completed at {m.completed_timestamp.isoformat()}"}
            )

        entries.append({
            "resource": nutrition,
            "request": {
                "method": "POST",
                "url": "NutritionOrder"
            },
        })

    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": entries,
    }

