from enum import Enum
from typing import Optional, List, Dict, Literal
from pydantic import BaseModel, Field
from datetime import datetime, date, time


# ------------------ Login ------------------
class PatientLogin(BaseModel):
    uhid: str


# ------------------ Surgery ------------------
class SurgeryDetails(BaseModel):
    surgery_id: str
    surgery_type: str   # e.g., Arthritis, Knee Replacement
    video_link: Optional[str] = None
    content_link: Optional[str] = None


# ------------------ Consent Form ------------------
class BasicDetails(BaseModel):
    first_name: str
    last_name: str
    date_of_birth: date
    hospital_registration_number: str
    responsible_attender_name: Optional[str] = None
    requirements: Optional[str] = None  # Interpreter, guardian, etc.

class SurgeryDetailsSection(BaseModel):
    indication: str
    extra_procedures: Optional[str] = None
    site_and_side: Optional[str] = None
    alternatives_considered: Optional[str] = None

class RiskItem(BaseModel):
    risk_name: str
    description: str
    likelihood: str  # Expected / Common / Uncommon / Rare
    factors_increasing_risk: Optional[str] = None

class PatientSpecificRisks(BaseModel):
    patient_specific_risks: Optional[str] = None

class PatientSpecificConcerns(BaseModel):
    blood_transfusion: Optional[str] = None
    other_procedures: Optional[str] = None

class HealthProfessionalStatement(BaseModel):
    name: str
    date: date
    job_title: str
    signature: Optional[str] = None
    patient_information_leaflet_provided: Optional[bool] = None
    patient_information_leaflet_provided_details: Optional[str] = None
    copy_accepted_by_patient: Optional[bool] = None


class PatientStatement(BaseModel):
    interpreter_or_witness_name: Optional[str] = None
    interpreter_or_witness_signature: Optional[str] = None
    information_interpreted: bool

class AdditionalConsent(BaseModel):
    allows_education_research_use: bool
    allows_research_access_to_records: bool
    pregnant_risk_confirmed: Optional[bool] = None
    additional_name: str
    addittional_date: str
    caretaker_name: Optional[str] = None
    relationship_to_patient: Optional[str] = None
    reason_for_surrogate_consent: Optional[str] = None


class ConsentFormData(BaseModel):
    basic_details: BasicDetails
    surgery_details: SurgeryDetailsSection
    risks: List[RiskItem] = Field(default_factory=list)
    patient_specific_risks: Optional[PatientSpecificRisks] = None
    patient_specific_concerns: Optional[PatientSpecificConcerns] = None
    health_professional_statement: Optional[HealthProfessionalStatement] = None
    patient_statement: Optional[PatientStatement] = None
    additional_consent: Optional[AdditionalConsent] = None


class ConsentFormStatus(BaseModel):
    status: Literal[0, 1]  # 0=draft, 1=active, 2=rejected
    status_timestamp: datetime  # When T&C was accepted
    approval: Literal[0, 1, 2]  # consent approval lifecycle
    approval_timestamp: datetime
    validation: Literal[0, 1, 2]  # 1=permit, 0/2=deny
    validation_timestamp: datetime
    document_url: Optional[str] = None
    document_creation: datetime

class ConsentForm(BaseModel):
    form_data: ConsentFormData
    status: ConsentFormStatus


# ------------------ Pre-Op Checklist ------------------
class DocumentEntry(BaseModel):
    document_name: str
    document_link: str
    assigned_by: str
    assigned_timestamp: datetime
    validated_by: Optional[str] = None
    validation_timestamp: Optional[datetime] = None
    updated_by: str
    updated_timestamp: datetime


class PreOpChecklist(BaseModel):
    documents: List[DocumentEntry] = []


# ------------------ Slot Booking ------------------
class SlotBooking(BaseModel):
    date: date
    time: time
    booking_timestamp: datetime


# ------------------ Billing ------------------
class BillingInfo(BaseModel):
    invoice_number: str


# ------------------ Watch Data ------------------
class WatchDataEntry(BaseModel):
    timestamp: datetime
    sleep_time: Optional[float] = None
    heart_rate: Optional[int] = None
    step_count: Optional[int] = None


class WatchData(BaseModel):
    yearly: List[WatchDataEntry] = []
    monthly: List[WatchDataEntry] = []
    weekly: List[WatchDataEntry] = []
    daily: List[WatchDataEntry] = []
    step_count_reminder: Optional[str] = None


# ------------------ Tablet Prescription ------------------
class DosePeriod(str, Enum):
    morning = "morning"
    afternoon = "afternoon"
    night = "night"


class DoseEntry(BaseModel):
    day: date
    period: DosePeriod
    taken_timestamp: Optional[datetime] = None


class TabletPrescriptionEntry(BaseModel):
    tablet_name: str
    dosage: str
    before_food: bool
    prescribed_date: date
    duration_days: int
    schedule_pattern: str  # e.g., "1-0-1"
    doses_taken: List[DoseEntry] = []
    completed: int = 0  # 0 = active, 1 = finished

class UpdateDoseRequest(BaseModel):
    tablet_name: str
    dose_day: date
    dose_period: DosePeriod
    taken_timestamp: Optional[datetime] = None

class TabletPrescribed(BaseModel):
    tablets: List[TabletPrescriptionEntry] = []


# ------------------ Rehab Section ------------------
class ExerciseEntry(BaseModel):
    name: str
    reps: int
    sets: int
    difficulty: str
    progress_percentage: float
    assigned_date: date
    assigned_time: time
    duration_days: int
    schedule: str
    period: Literal["morning", "afternoon", "night"]
    exercise_video: Optional[str] = None
    completed_timestamp: Optional[datetime] = None


class RehabInstructions(BaseModel):
    instruction_text: str
    timestamp: datetime


class RehabSection(BaseModel):
    exercises: List[ExerciseEntry] = []
    instructions: List[RehabInstructions] = []


# ------------------ Meals ------------------
class MealEntry(BaseModel):
    meal_name: str
    description: str
    period: Literal["breakfast", "lunch", "dinner", "snack"]
    assigned_date: date
    assigned_time: time
    completed_timestamp: datetime


class TodaysMeal(BaseModel):
    meals: List[MealEntry] = []


# ------------------ Master Model ------------------
class PatientFullModel(BaseModel):
    login: PatientLogin
    surgery: List[SurgeryDetails] = []   # <-- CHANGED TO ARRAY
    consent_form: ConsentForm
    pre_op_checklist: PreOpChecklist
    slot_booking: SlotBooking
    billing: BillingInfo
    watch_data: WatchData
    tablet_prescribed: TabletPrescribed
    rehab_section: RehabSection
    todays_meal: TodaysMeal

    class Config:
        schema_extra = {
            "example": {
                "uhid": "UHID123456",
                "surgery": [
                    {
                        "surgery_id": "SURG-001",
                        "surgery_type": "Total Knee Replacement",
                        "video_link": "https://hospital.com/videos/knee-replacement",
                        "content_link": "https://hospital.com/content/knee-replacement"
                    },
                    {
                        "surgery_id": "SURG-002",
                        "surgery_type": "Arthritis Correction",
                        "video_link": "https://hospital.com/videos/arthritis",
                        "content_link": "https://hospital.com/content/arthritis"
                    }
                ],
                "consent_form": {
                    "form_data": {
                        "basic_details": {
                        "first_name": "John",
                        "last_name": "Doe",
                        "date_of_birth": "1979-03-15",
                        "hospital_registration_number": "UHID123456",
                        "responsible_attender_name": "Jane Doe",
                        "requirements": "Interpreter"
                        },
                        "surgery_details": {
                        "procedure": "Total Knee Replacement",
                        "indication": "Osteoarthritis of the knee – to reduce pain and improve mobility",
                        "site_and_side": "Left"
                        },
                        "risks": [
                        {
                            "risk_name": "Bleeding and Haematoma",
                            "description": "Some bleeding is expected during the procedure...",
                            "likelihood": "Common"
                        }
                        ],
                        "patient_specific_risks": {
                        "concerns": "Allergy to latex",
                        "extra_procedures_if_necessary": "Blood transfusion if required"
                        },
                        "health_professional_statement": {
                        "name": "Dr. Vetri M K",
                        "date": "2025-10-26",
                        "job_title": "Consultant Surgeon"
                        },
                        "patient_statement": {
                        "understands_form": 1,
                        "agrees_treatment": 1,
                        "aware_of_alternatives": 1,
                        "understands_risks": 1,
                        "discussed_anaesthesia": 1,
                        "agrees_additional_procedures_if_necessary": 1,
                        "allows_data_collection": 1
                        },
                        "additional_consent": {
                        "allows_education_research_use": 1,
                        "allows_research_access_to_records": 1
                        }
                    },
                    "status": {
                        "terms_and_conditions": 1,
                        "terms_and_conditions_timestamp": "2025-10-26T09:30:00Z",
                        "consent_form_approval": 1,
                        "consent_form_approval_timestamp": "2025-10-26T09:35:00Z",
                        "consent_form_upload_link": "https://hospital.com/uploads/consent/UHID123456.pdf",
                        "consent_form_upload_link_timestamp": "2025-10-26T09:40:00Z",
                        "consent_form_validation": 1,
                        "consent_form_validation_timestamp": "2025-10-26T09:45:00Z"
                    }
                },
                "pre_op_checklist": {
                    "documents": [
                        {
                            "document_name": "Blood Sugar Report",
                            "document_link": "https://hospital.com/docs/blood-sugar.pdf",
                            "assigned_by": "Dr. Smith",
                            "assigned_timestamp": "2025-10-03T10:00:00",
                            "validated_by": "Nurse A",
                            "validation_timestamp": "2025-10-03T12:00:00"
                        }
                    ]
                },
                "slot_booking": {
                    "date": "2025-10-10",
                    "time": "09:30:00",
                },
                "billing": {
                    "invoice_number": "INV-2025-1001"
                },
                "watch_data": {
                    "yearly": [
                        {"timestamp": "2025-01-01T00:00:00", "sleep_time": 7.5, "heart_rate": 72, "step_count": 10000}
                    ],
                    "step_count_reminder": "5000 steps remaining today"
                },
                "tablet_prescribed": {
                    "tablets": [
                    {
                        "tablet_name": "Painkiller",
                        "dosage": "500mg",
                        "before_food": False,
                        "prescribed_date": "2025-10-03",
                        "duration_days": 30,
                        "schedule_pattern": "1-0-1",
                        "doses_taken": [
                            {
                                "day": "2025-10-03",
                                "period": "morning",
                                "taken_timestamp": "2025-10-03T08:00:00"
                            },
                            {
                                "day": "2025-10-03",
                                "period": "night",
                                "taken_timestamp": "2025-10-03T20:00:00"
                            }
                        ],
                        "completed": 0
                    },
                    {
                        "tablet_name": "Vitamin D",
                        "dosage": "1000 IU",
                        "before_food": True,
                        "prescribed_date": "2025-09-01",
                        "duration_days": 15,
                        "schedule_pattern": "1-0-0",
                        "doses_taken": [],
                        "completed": 1
                    }
                ]
                },
                "rehab_section": {
                    "exercises": [
                        {
                            "name": "Leg Raise",
                            "reps": 10,
                            "sets": 3,
                            "difficulty": "medium",
                            "progress_percentage": 40.0,
                            "assigned_date": "2025-10-03",
                            "assigned_time": "08:30:00",
                            "schedule": "daily",
                            "period": "morning",
                            "completed_timestamp": None
                        }
                    ],
                    "instructions": [
                        {
                            "instruction_text": "Do not put full weight on the operated leg.",
                            "timestamp": "2025-10-03T09:00:00"
                        }
                    ]
                },
                "todays_meal": {
                    "meals": [
                        {
                            "meal_name": "Breakfast",
                            "description": "Oats with fruits and milk",
                            "period": "breakfast",
                            "assigned_date": "2025-10-03",
                            "assigned_time": "08:00:00",
                            "completed_timestamp": None
                        }
                    ]
                }
            }
        }

# 🧾 Model for order creation
class PaymentRequest(BaseModel):
    amount: int      # amount in rupees
    currency: str = "INR"
    receipt: str

class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str