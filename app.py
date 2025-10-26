from datetime import date, datetime, timedelta
import hashlib
import hmac
from typing import Dict, List, Optiona
from fastapi import  BackgroundTasks, Body, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, BackgroundTasks, Query, Form, File, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
import os
import razorpay
import requests
from azure.identity import ClientSecretCredential
from models import (
    ConsentFormData,
    ConsentFormStatus,
    DocumentEntry,
    DosePeriod,
    ExerciseEntry,
    PatientLogin,
    PaymentRequest,
    RehabInstructions,
    SurgeryDetails,
    PreOpChecklist,
    SlotBooking,
    BillingInfo,
    UpdateDoseRequest,
    VerifyPaymentRequest,
    WatchData,
    TabletPrescribed,
    RehabSection,
    TodaysMeal
)
from apscheduler.schedulers.background import BackgroundScheduler
from db import fhir_consent_form_status_resources, fhir_consent_resource_structured, fhir_patient_resource,fhir_surgery_resources,fhir_preop_checklist_resources,fhir_slot_booking_resource,fhir_billing_resource,fhir_watchdata_resources,fhir_meal_resources,fhir_medication_resources
from azure.storage.blob import BlobServiceClient


# Get environment variables
FHIR_URL = os.getenv("FHIR_URL")
AZURE_TOKEN = os.getenv("AZURE_TOKEN")
TENANT_ID = os.getenv("AZURE_TENANT_ID")
CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")
# Azure Blob Storage config from .env
ACCOUNT_URL = os.getenv("AZURE_ACCOUNT_URL")
ACCOUNT_KEY = os.getenv("AZURE_ACCOUNT_KEY")
CONTAINER_NAME = os.getenv("CONTAINER_NAME", "profile-picture")

credential = ClientSecretCredential(
    tenant_id=TENANT_ID,
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET
)

FHIR_SCOPE = "https://fastapi-fhir-pes.fhir.azurehealthcareapis.com/.default"


def get_headers():
    token = credential.get_token(FHIR_SCOPE)
    return {
        "Authorization": f"Bearer {token.token}",
        "Content-Type": "application/fhir+json"
    }


app = FastAPI()
scheduler = BackgroundScheduler()

# Initialize Blob service client
blob_service_client = BlobServiceClient(account_url=ACCOUNT_URL, credential=ACCOUNT_KEY)
container_client = blob_service_client.get_container_client(CONTAINER_NAME)

# Ensure container exists
try:
    container_client.create_container()
    print(f"✅ Container '{CONTAINER_NAME}' created.")
except Exception:
    print(f"ℹ Container '{CONTAINER_NAME}' already exists.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Razorpay client
client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

@app.get("/")
def root():
    return {"Message": "use '/docs' endpoint to find all the api related docs "}

# ---------------------- PATIENT ----------------------
@app.post("/fhir/patient", response_model=dict)
async def convert_patient(login: PatientLogin):
    """Convert patient login info to FHIR Patient resource."""
    return fhir_patient_resource(login)


# ---------------------- SURGERY ----------------------
@app.post("/fhir/surgery")
def convert_surgery(uhid: str, surgeries: List[SurgeryDetails]):
    """Convert surgery details and directly post to Azure FHIR server."""
    bundle = fhir_surgery_resources(uhid, surgeries)
    headers = get_headers()

    try:
        response = requests.post(f"{FHIR_URL}/", json=bundle, headers=headers)
        if response.status_code < 400:
            return {"success": True, "message": "FHIR resources posted successfully."}
        else:
            return {
                "success": False,
                "message": f"FHIR server returned error: {response.status_code} {response.text}"
            }
    except Exception as e:
        return {"success": False, "message": f"Error posting to FHIR server: {str(e)}"}
    
@app.get("/fhir/procedures/{uhid}")
def get_procedures_by_uhid(uhid: str):
    """
    Get all Procedure resources where subject.reference = Patient/{uhid}.
    """
    headers = get_headers()

    try:
        # Directly query Procedure by subject reference
        procedure_url = f"{FHIR_URL}/Procedure?subject=Patient/{uhid}"
        response = requests.get(procedure_url, headers=headers)

        if response.status_code >= 400:
            return {"success": False, "message": f"FHIR server error: {response.text}"}

        data = response.json()
        if not data.get("entry"):
            return {"success": False, "message": f"No Procedures found for UHID {uhid}"}

        return {"success": True, "procedures": data}

    except Exception as e:
        return {"success": False, "message": str(e)}


# ---------------------- CONSENT FORM ----------------------
@app.post("/fhir/consent-form-status", response_model=Dict)
async def post_consent_status(uhid: str, consent: ConsentFormStatus):
    """Convert ConsentFormStatus to FHIR Consent and post to Azure FHIR."""
    bundle = fhir_consent_form_status_resources(uhid, consent)
    headers = get_headers()

    try:
        for entry in bundle["entry"]:
            resource = entry["resource"]
            response = requests.post(f"{FHIR_URL}/Consent", json=resource, headers=headers)
            if response.status_code >= 400:
                return {
                    "success": False,
                    "message": f"FHIR server error: {response.status_code} {response.text}"
                }

        return {"success": True, "message": "Consent form status posted successfully."}

    except Exception as e:
        return {"success": False, "message": f"Error posting to FHIR server: {str(e)}"}

@app.get("/fhir/consent-form-status/{uhid}", response_model=Dict)
async def get_consent_form_status(uhid: str):
    """
    Fetch ConsentFormStatus (FHIR Consent resource with internal tag)
    for a given UHID and return only the resource body.
    """
    headers = get_headers()

    try:
        # 1️⃣ Search by UHID only
        url = f"{FHIR_URL}/Consent?identifier=https://hospital.com/uhid|{uhid}"
        response = requests.get(url, headers=headers)

        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"FHIR server returned error: {response.text}"
            )

        data = response.json()
        entries = data.get("entry", [])

        if not entries:
            raise HTTPException(
                status_code=404,
                detail=f"No Consent found for UHID {uhid}"
            )

        # 2️⃣ Filter manually for internal ConsentFormStatus tag
        consent_form_status_entries = [
            entry["resource"]
            for entry in entries
            if "resource" in entry and
               any(tag.get("code") == "ConsentFormStatus"
                   for tag in entry["resource"].get("meta", {}).get("tag", []))
        ]

        if not consent_form_status_entries:
            raise HTTPException(
                status_code=404,
                detail=f"No ConsentFormStatus found for UHID {uhid}"
            )

        # 3️⃣ Return the latest one by dateTime
        latest = max(
            consent_form_status_entries,
            key=lambda r: r.get("dateTime", "")
        )

        return {"success": True, "data": latest}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@app.post("/fhir/consent-forms", response_model=Dict)
async def post_consent_structured(uhid: str, consent: ConsentFormData):
    """Convert structured ConsentFormData to FHIR Consent Bundle and post to Azure FHIR."""
    bundle = fhir_consent_resource_structured(uhid, consent)
    headers = get_headers()

    try:
        for entry in bundle["entry"]:
            resource = entry["resource"]
            response = requests.post(f"{FHIR_URL}/Consent", json=resource, headers=headers)
            if response.status_code >= 400:
                return {
                    "success": False,
                    "message": f"FHIR server error: {response.status_code} {response.text}"
                }

        return {"success": True, "message": "Structured consent form posted successfully."}

    except Exception as e:
        return {"success": False, "message": f"Error posting to FHIR server: {str(e)}"}
    
@app.get("/fhir/consent-form/{uhid}", response_model=Dict)
async def get_consent_form_status(uhid: str):
    """
    Fetch ConsentFormStatus (FHIR Consent resource with internal tag)
    for a given UHID and return only the resource body.
    """
    headers = get_headers()

    try:
        # 1️⃣ Search by UHID only
        url = f"{FHIR_URL}/Consent?identifier=https://hospital.com/uhid|{uhid}"
        response = requests.get(url, headers=headers)

        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"FHIR server returned error: {response.text}"
            )

        data = response.json()
        entries = data.get("entry", [])

        if not entries:
            raise HTTPException(
                status_code=404,
                detail=f"No Consent found for UHID {uhid}"
            )

        # 2️⃣ Filter manually for internal ConsentFormStatus tag
        consent_form_status_entries = [
            entry["resource"]
            for entry in entries
            if "resource" in entry and
               any(tag.get("code") == "ConsentFormData"
                   for tag in entry["resource"].get("meta", {}).get("tag", []))
        ]

        if not consent_form_status_entries:
            raise HTTPException(
                status_code=404,
                detail=f"No ConsentFormStatus found for UHID {uhid}"
            )

        # 3️⃣ Return the latest one by dateTime
        latest = max(
            consent_form_status_entries,
            key=lambda r: r.get("dateTime", "")
        )

        return {"success": True, "data": latest}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------- PRE-OP CHECKLIST ----------------------
@app.post("/fhir/preop-checklist", response_model=dict)
def post_preop_checklist(uhid: str, checklist: PreOpChecklist):
    """Convert pre-operative checklist to FHIR DocumentReference and post to Azure FHIR."""
    bundle = fhir_preop_checklist_resources(uhid, checklist)
    headers = get_headers()

    try:
        # Post each DocumentReference individually
        for entry in bundle["entry"]:
            resource = entry["resource"]
            response = requests.post(f"{FHIR_URL}/DocumentReference", json=resource, headers=headers)
            if response.status_code >= 400:
                return {"success": False, "message": f"FHIR server error: {response.status_code} {response.text}"}

        return {"success": True, "message": "All DocumentReference resources posted successfully."}
    except Exception as e:
        return {"success": False, "message": f"Error posting to FHIR server: {str(e)}"}
    
@app.get("/fhir/preop-checklist", response_model=dict)
def get_preop_checklist(uhid: str):
    """Fetch complete Pre-Op Checklist (DocumentReference) details for a given patient UHID."""
    headers = get_headers()
    params = {"subject": f"Patient/{uhid}"}

    try:
        resp = requests.get(f"{FHIR_URL}/DocumentReference", headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()
        documents = []

        # helper: find extension value by exact URL or suffix, return first matching value field
        def _ext_value(resource: dict, url_exact: str = None, url_suffix: str = None):
            for ext in resource.get("extension", []) or []:
                url = ext.get("url", "")
                if (url_exact and url == url_exact) or (url_suffix and url.endswith(url_suffix)):
                    for key in ("valueDateTime", "valueInstant", "valueString", "valueDate", "valueTime", "valueUri"):
                        if key in ext:
                            return ext[key]
            return None

        for entry in data.get("entry", []):
            res = entry.get("resource", {})

            # common attachment fields (assigned timestamp usually in attachment.creation)
            attachment = (res.get("content") or [{}])[0].get("attachment", {}) or {}
            assigned_ts = (
                attachment.get("creation")
                or attachment.get("created")
                or attachment.get("date")
            )

            # Try extensions first (the generator used these URLs), then fallbacks
            validation_timestamp = (
                _ext_value(res, url_exact="http://example.org/fhir/StructureDefinition/validation-timestamp")
                or _ext_value(res, url_suffix="validation-timestamp")
                or res.get("context", {}).get("period", {}).get("end")
                or res.get("meta", {}).get("lastUpdated")
                or None
            )

            validated_by = (
                _ext_value(res, url_exact="http://example.org/fhir/StructureDefinition/validated-by")
                or _ext_value(res, url_suffix="validated-by")
                or (res.get("authenticator") or {}).get("display")
                or (res.get("author") or [{}])[0].get("display")
                or None
            )

            doc_info = {
                "document_name": (res.get("type") or {}).get("text") or (res.get("description") or None),
                "document_link": attachment.get("url"),
                "assigned_by": (res.get("author") or [{}])[0].get("display"),
                "assigned_timestamp": assigned_ts,
                "validated_by": validated_by,
                "validation_timestamp": validation_timestamp,
                "updated_by": (res.get("custodian") or {}).get("display"),
                "updated_timestamp": res.get("date") or res.get("meta", {}).get("lastUpdated")
            }

            documents.append(doc_info)

        return {"success": True, "documents": documents}

    except requests.HTTPError as e:
        return {"success": False, "message": f"FHIR server error: {resp.status_code} {resp.text}"}
    except Exception as e:
        return {"success": False, "message": f"Error fetching from FHIR server: {str(e)}"}


@app.delete("/fhir/preop-checklist/delete", response_model=dict)
def delete_preop_document(uhid: str, document_name: str):
    """
    Delete a specific DocumentReference resource by UHID and document name.
    """
    headers = get_headers()
    params = {
        "subject": f"Patient/{uhid}",
        "type:text": document_name  # FHIR search parameter for matching document type text
    }

    try:
        # Step 1: Search for the document
        search_resp = requests.get(f"{FHIR_URL}/DocumentReference", headers=headers, params=params)
        if search_resp.status_code >= 400:
            return {
                "success": False,
                "message": f"FHIR search error: {search_resp.status_code} {search_resp.text}"
            }

        data = search_resp.json()
        entries = data.get("entry", [])

        if not entries:
            return {"success": False, "message": f"No document found for '{document_name}' and UHID '{uhid}'."}

        deleted_docs = []
        for entry in entries:
            resource = entry.get("resource", {})
            doc_id = resource.get("id")
            doc_type = resource.get("type", {}).get("text")

            if not doc_id:
                continue

            # Step 2: Delete the resource
            delete_resp = requests.delete(f"{FHIR_URL}/DocumentReference/{doc_id}", headers=headers)
            if delete_resp.status_code in (200, 204):
                deleted_docs.append({"document_name": doc_type, "document_id": doc_id})
            else:
                return {
                    "success": False,
                    "message": f"Failed to delete document {doc_id}: {delete_resp.status_code} {delete_resp.text}"
                }

        return {
            "success": True,
            "message": f"Deleted {len(deleted_docs)} document(s) successfully.",
            "deleted": deleted_docs
        }

    except Exception as e:
        return {"success": False, "message": f"Error during deletion: {str(e)}"}

@app.put("/fhir/preop-checklist/update-single", response_model=dict)
def update_single_document(uhid: str = Query(..., description="Patient UHID"),
                           doc_entry: DocumentEntry = ...):
    """
    Update a single DocumentReference for a given UHID using full DocumentEntry.
    All fields are controlled via Swagger UI.
    """
    headers = get_headers()

    # Search for the document by UHID and document_name
    params = {"subject": f"Patient/{uhid}", "type:text": doc_entry.document_name}
    search_resp = requests.get(f"{FHIR_URL}/DocumentReference", headers=headers, params=params)

    if search_resp.status_code >= 400:
        return {"success": False, "message": f"FHIR search error: {search_resp.status_code} {search_resp.text}"}

    data = search_resp.json()
    entries = data.get("entry", [])
    if not entries:
        return {"success": False, "message": f"No document found for '{doc_entry.document_name}' and UHID '{uhid}'."}

    # Take the first matching document
    resource = entries[0]["resource"]
    doc_id = resource.get("id")

    updated_doc = {
        "resourceType": "DocumentReference",
        "id": doc_id,
        "identifier": [{"system": "https://hospital.com/uhid", "value": uhid}],
        "status": "current",
        "type": {"text": doc_entry.document_name},
        "subject": {"reference": f"Patient/{uhid}"},
        "author": [{"display": doc_entry.assigned_by}],
        "authenticator": {"display": doc_entry.validated_by or "N/A"},
        "custodian": {"display": doc_entry.updated_by},
        "date": doc_entry.updated_timestamp.isoformat() if doc_entry.updated_timestamp else None,
        "description": f"Validation Timestamp: {doc_entry.validation_timestamp.isoformat() if doc_entry.validation_timestamp else 'N/A'}",
        "content": [
            {
                "attachment": {
                    "title": doc_entry.document_name,
                    "creation": doc_entry.assigned_timestamp.isoformat(),
                    "url": doc_entry.document_link or "N/A"
                }
            }
        ]
    }

    # PUT update to FHIR
    update_resp = requests.put(f"{FHIR_URL}/DocumentReference/{doc_id}", headers=headers, json=updated_doc)
    if update_resp.status_code not in (200, 201):
        return {"success": False, "message": f"Failed to update document {doc_id}: {update_resp.status_code} {update_resp.text}"}

    return {
        "success": True,
        "message": f"Document '{doc_entry.document_name}' updated successfully.",
        "document_id": doc_id
    }

# ---------------------- SLOT BOOKING ----------------------
@app.post("/fhir/slot-booking", response_model=dict)
def post_slot_booking(uhid: str, slot: SlotBooking):
    """Convert slot booking to FHIR Appointment and post to Azure FHIR."""
    bundle = fhir_slot_booking_resource(uhid, slot)
    headers = get_headers()

    try:
        # Post each Appointment individually
        for entry in bundle["entry"]:
            resource = entry["resource"]
            response = requests.post(f"{FHIR_URL}/Appointment", json=resource, headers=headers)
            if response.status_code >= 400:
                return {
                    "success": False,
                    "message": f"FHIR server error: {response.status_code} {response.text}"
                }

        return {"success": True, "message": "Appointment booked successfully."}
    except Exception as e:
        return {"success": False, "message": f"Error posting to FHIR server: {str(e)}"}

@app.get("/fhir/slot-booking", response_model=dict)
def get_slot_booking(uhid: str):
    """Fetch Appointment resources for a given patient UHID using identifier."""
    headers = get_headers()
    # Filter using the identifier system and value
    params = {"identifier": f"https://hospital.com/uhid|{uhid}"}

    try:
        response = requests.get(f"{FHIR_URL}/Appointment", headers=headers, params=params)
        data = response.json()
        appointments = []

        for entry in data.get("entry", []):
            res = entry.get("resource", {})
            # skip incomplete appointments
            if not res.get("start") or not res.get("description"):
                continue

            participants = [
                p.get("actor", {}).get("display") or p.get("actor", {}).get("reference")
                for p in res.get("participant", [])
            ]

            appointments.append({
                "start": res.get("start"),
                "description": res.get("description"),
                "created": res.get("created"),  # booking timestamp
                "participants": participants
            })

        return {"appointments": appointments}

    except Exception as e:
        return {"appointments": [], "error": str(e)}

# ---------------------- BILLING ----------------------
@app.post("/fhir/billing", response_model=dict)
def convert_billing(uhid: str, billing: BillingInfo):
    """Convert billing info and post to Azure FHIR."""
    account_resource = fhir_billing_resource(uhid, billing)
    headers = get_headers()

    try:
        response = requests.post(f"{FHIR_URL}/Account", json=account_resource, headers=headers)
        if response.status_code < 400:
            return {"success": True, "message": "Billing Account posted successfully."}
        else:
            return {"success": False, "message": f"FHIR server returned error: {response.status_code} {response.text}"}
    except Exception as e:
        return {"success": False, "message": f"Error posting to FHIR server: {str(e)}"}
    

@app.get("/fhir/billing", response_model=dict)
def get_billing(uhid: str):
    """Fetch only invoice numbers for a given patient UHID."""
    headers = get_headers()
    params = {"patient": f"Patient/{uhid}"}

    try:
        response = requests.get(f"{FHIR_URL}/Account", headers=headers, params=params)
        data = response.json()
        invoices = []

        if data.get("resourceType") == "Bundle" and "entry" in data:
            entries = data["entry"]
        else:
            entries = []

        for entry in entries:
            res = entry.get("resource", {})
            if not res:
                continue

            # Extract invoice number from identifier
            for ident in res.get("identifier", []):
                if ident.get("system") == "https://hospital.com/invoice":
                    invoices.append(ident.get("value"))

        return {"invoices": invoices}

    except Exception as e:
        return {"invoices": [], "error": str(e)}


# ---------------------- WATCH DATA ----------------------
@app.post("/fhir/watch-data", response_model=dict)
async def convert_watch(uhid: str, watch_data: WatchData):
    """Convert watch metrics (heart rate, steps, sleep) to FHIR Observations and post to FHIR server."""
    entries = fhir_watchdata_resources(uhid, watch_data)["entry"]
    headers = get_headers()

    try:
        # Post each Observation individually to avoid bundle errors
        for entry in entries:
            obs = entry["resource"]
            response = requests.post(f"{FHIR_URL}/Observation", json=obs, headers=headers)
            if response.status_code >= 400:
                return {
                    "success": False,
                    "message": f"Error posting Observation: {response.status_code} {response.text}"
                }

        return {"success": True, "message": f"{len(entries)} Observations posted successfully."}

    except Exception as e:
        return {"success": False, "message": str(e)}
    

@app.get("/fhir/watch-data", response_model=dict)
def get_watch_data(uhid: str):
    """Fetch WatchData Observations for a given patient UHID."""
    headers = get_headers()
    params = {"subject": f"Patient/{uhid}"}

    try:
        response = requests.get(f"{FHIR_URL}/Observation", headers=headers, params=params)
        data = response.json()
        observations = []

        for entry in data.get("entry", []):
            res = entry.get("resource", {})
            observations.append({
                "code": res.get("code", {}).get("text"),
                "value": res.get("valueQuantity", {}).get("value"),
                "unit": res.get("valueQuantity", {}).get("unit"),
                "category": [c.get("text") for c in res.get("category", [])],
                "timestamp": res.get("effectiveDateTime")
            })

        return {"success": True, "observations": observations}

    except Exception as e:
        return {"success": False, "observations": [], "error": str(e)}


# ---------------------- MEDICATION ----------------------
@app.post("/fhir/convert-medications", response_model=dict)
async def convert_medications_to_fhir(uhid: str, tablets: TabletPrescribed):
    """
    Convert prescribed tablets (Pydantic model) to FHIR MedicationRequest Bundle
    and return it.
    """
    bundle = fhir_medication_resources(uhid, tablets)
    return {"success": True, "fhir_bundle": bundle}


@app.post("/fhir/medications", response_model=dict)
async def post_medications(uhid: str, tablets: TabletPrescribed):
    """Convert prescribed tablets to FHIR MedicationRequest and post to FHIR server"""
    try:
        entries = fhir_medication_resources(uhid, tablets)["entry"]
        headers = get_headers()

        # Only post active medications
        posted_count = 0
        for entry in entries:
            med = entry["resource"]
            if med["status"] == "active":
                response = requests.post(f"{FHIR_URL}/MedicationRequest", json=med, headers=headers)
                if response.status_code >= 400:
                    return {"success": False, "message": f"Error posting MedicationRequest: {response.status_code} {response.text}"}
                posted_count += 1

        return {"success": True, "message": f"{posted_count} active MedicationRequest(s) posted successfully."}

    except Exception as e:
        return {"success": False, "message": str(e)}

# --- GET Endpoint ---

@app.get("/fhir/medications", response_model=dict)
def get_medications(uhid: str):
    """Fetch all MedicationRequest resources for a patient UHID (all pages)"""
    try:
        headers = get_headers()
        url = f"{FHIR_URL}/MedicationRequest?subject=Patient/{uhid}"
        all_medications = []

        while url:
            response = requests.get(url, headers=headers)
            data = response.json()

            # Add all entries to the list
            for entry in data.get("entry", []):
                res = entry.get("resource", {})
                all_medications.append(res)

            # Pagination: look for next page link
            next_link = None
            for link in data.get("link", []):
                if link.get("relation") == "next":
                    next_link = link.get("url")
                    break
            url = next_link

        return {"success": True, "medications": all_medications}

    except Exception as e:
        return {"success": False, "medications": [], "error": str(e)}
    
@app.get("/fhir/medications/active/{uhid}", response_model=dict)
def get_active_medications(uhid: str):
    """
    Fetch all active medications for a given patient UHID.
    Returns medication name, status, dosage, authored date, duration_days, and doses taken.
    """
    try:
        headers = get_headers()
        url = f"{FHIR_URL}/MedicationRequest?subject=Patient/{uhid}&status=active"
        all_active_meds = []

        while url:
            response = requests.get(url, headers=headers)
            data = response.json()

            for entry in data.get("entry", []):
                res = entry.get("resource", {})

                med_name = res.get("medicationCodeableConcept", {}).get("text", "Unknown")
                status = res.get("status", "unknown")
                authored_on = res.get("authoredOn", "")
                dosage = res.get("dosageInstruction", [{}])[0].get("text", "")
                note_text = res.get("note", [{}])[0].get("text", "[]")

                # ✅ Parse doses_taken JSON safely
                import json
                try:
                    doses_taken = json.loads(note_text)
                except Exception:
                    doses_taken = [note_text]

                # ✅ Extract duration_days from dosageInstruction.repeat.boundsDuration
                duration_days = None
                dosage_instr = res.get("dosageInstruction", [])
                if dosage_instr:
                    timing = dosage_instr[0].get("timing", {})
                    repeat = timing.get("repeat", {})
                    bounds = repeat.get("boundsDuration", {})
                    duration_days = bounds.get("value")

                all_active_meds.append({
                    "id": res.get("id"),
                    "tablet_name": med_name,
                    "status": status,
                    "dosage": dosage,
                    "authoredOn": authored_on,
                    "duration_days": duration_days,
                    "doses_taken": doses_taken
                })

            # Handle pagination
            next_link = next(
                (link.get("url") for link in data.get("link", []) if link.get("relation") == "next"),
                None
            )
            url = next_link

        return {
            "success": True,
            "count": len(all_active_meds),
            "active_medications": all_active_meds
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@app.delete("/fhir/delete-active-medicine")
def delete_active_medicine(uhid: str, tablet_name: str):
    """
    Delete MedicationRequest for given UHID and tablet_name if status=active
    """
    headers = get_headers()

    try:
        # Search by UHID identifier and active status
        search_url = f"{FHIR_URL}/MedicationRequest"
        params = {
            "identifier": f"https://hospital.com/uhid|{uhid}",
            "status": "active"
        }

        response = requests.get(search_url, headers=headers, params=params)
        if response.status_code >= 400:
            raise HTTPException(status_code=response.status_code, detail=f"FHIR search failed: {response.text}")

        data = response.json()
        entries = data.get("entry", [])
        if not entries:
            return {"success": False, "message": "No active medicines found for this UHID."}

        deleted = []
        skipped = []

        for entry in entries:
            resource = entry.get("resource", {})
            med_id = resource.get("id")
            med_name = resource.get("medicationCodeableConcept", {}).get("text", "")
            status = resource.get("status", "")

            # Case-insensitive match on medicine name and only delete active
            if med_name.lower() == tablet_name.lower() and status == "active":
                del_url = f"{FHIR_URL}/MedicationRequest/{med_id}"
                del_res = requests.delete(del_url, headers=headers)
                if del_res.status_code in [200, 204]:
                    deleted.append(med_name)
                else:
                    skipped.append({
                        "id": med_id,
                        "error": del_res.text
                    })

        if not deleted:
            return {
                "success": False,
                "message": f"No active medicine named '{tablet_name}' found for UHID {uhid}.",
                "skipped": skipped
            }

        return {
            "success": True,
            "message": f"Deleted {len(deleted)} record(s) successfully.",
            "deleted_medicines": deleted
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/fhir/medications/update-dose/{uhid}", response_model=dict)
def update_dose_taken(uhid: str, body: UpdateDoseRequest):
    """
    Update dose taken for a particular tablet on a given day for a patient.
    Appends doses_taken JSON to existing notes without replacing them.
    """
    try:
        headers = get_headers()
        url = f"{FHIR_URL}/MedicationRequest?subject=Patient/{uhid}"
        all_medications = []

        # Fetch all MedicationRequests with pagination
        while url:
            resp = requests.get(url, headers=headers)
            data = resp.json()
            all_medications.extend(data.get("entry", []))
            next_link = next((l.get("url") for l in data.get("link", []) if l.get("relation") == "next"), None)
            url = next_link

        updated_count = 0

        for entry in all_medications:
            res = entry.get("resource", {})
            if res.get("medicationCodeableConcept", {}).get("text") != body.tablet_name:
                continue

            # Extract existing doses_taken from note.text if exists
            import json
            doses_taken = []
            # Find note that contains doses_taken JSON
            for note in res.get("note", []):
                try:
                    loaded = json.loads(note.get("text", "[]"))
                    if isinstance(loaded, list):
                        doses_taken = loaded
                        break
                except json.JSONDecodeError:
                    continue  # skip other notes

            # Update or append new dose
            exists = False
            for d in doses_taken:
                if d["day"] == str(body.dose_day) and d["period"] == body.dose_period:
                    d["taken_timestamp"] = (
                        body.taken_timestamp.isoformat() if body.taken_timestamp else datetime.now().isoformat()
                    )
                    exists = True
                    break
            if not exists:
                doses_taken.append({
                    "day": str(body.dose_day),
                    "period": body.dose_period,
                    "taken_timestamp": body.taken_timestamp.isoformat() if body.taken_timestamp else datetime.now().isoformat()
                })

            # Store doses_taken as JSON string in a new note entry (append)
            updated_note_entry = {"text": json.dumps(doses_taken)}
            updated_notes = res.get("note", []) + [updated_note_entry]

            # FHIR-compliant update payload
            update_payload = {
                "resourceType": "MedicationRequest",
                "id": res["id"],
                "status": res.get("status", "active"),
                "intent": res.get("intent", "order"),
                "subject": res.get("subject"),
                "medicationCodeableConcept": res.get("medicationCodeableConcept"),
                "dosageInstruction": res.get("dosageInstruction", []),
                "note": updated_notes
            }

            patch_resp = requests.put(f"{FHIR_URL}/MedicationRequest/{res['id']}", json=update_payload, headers=headers)
            if patch_resp.status_code >= 400:
                return {"success": False, "message": f"Failed to update {res['id']}: {patch_resp.text}"}

            updated_count += 1

        return {"success": True, "message": f"{updated_count} medication(s) updated for tablet '{body.tablet_name}'."}

    except Exception as e:
        return {"success": False, "error": str(e)}

    
def auto_complete_all_medications():
    """Mark all medications whose duration has passed as completed."""
    try:
        print(f"[{datetime.now()}] Running medication auto-complete job...")
        url = f"{FHIR_URL}/MedicationRequest"
        today = datetime.now().date()

        while url:
            response = requests.get(url, headers=get_headers())
            data = response.json()

            for entry in data.get("entry", []):
                res = entry.get("resource", {})
                authored_on = datetime.fromisoformat(res["authoredOn"]).date()

                # Extract planned duration from note
                note_text = res.get("note", [{}])[0].get("text", "")
                if "Planned duration:" in note_text:
                    planned_duration = int(note_text.split(":")[1].strip().split()[0])
                else:
                    planned_duration = 1

                last_day = authored_on + timedelta(days=planned_duration - 1)

                # Only mark as completed if status is active and duration has passed
                if today > last_day and res.get("status") != "completed":
                    # FHIR requires status, intent, subject, and medicationCodeableConcept
                    update_payload = {
                        "resourceType": "MedicationRequest",
                        "id": res.get("id"),
                        "status": "completed",
                        "intent": res.get("intent", "order"),
                        "subject": res.get("subject"),
                        "medicationCodeableConcept": res.get("medicationCodeableConcept"),
                        "dosageInstruction": res.get("dosageInstruction", []),
                        "note": res.get("note", [])
                    }

                    patch_response = requests.put(
                        f"{FHIR_URL}/MedicationRequest/{res.get('id')}",
                        json=update_payload,
                        headers=get_headers()
                    )
                    if patch_response.status_code < 400:
                        print(f"MedicationRequest {res.get('id')} marked as completed.")
                    else:
                        print(f"Error updating {res.get('id')}: {patch_response.text}")

            # Pagination
            next_link = next((link.get("url") for link in data.get("link", []) if link.get("relation") == "next"), None)
            url = next_link

        print(f"[{datetime.now()}] Medication auto-complete job finished.")

    except Exception as e:
        print(f"Error in auto_complete_all_medications: {e}")

# Schedule job daily
scheduler = BackgroundScheduler()
scheduler.add_job(auto_complete_all_medications, "cron", hour=0, minute=5)
scheduler.start()

# ---------------------- REHAB ----------------------
@app.post("/rehab/exercises", response_model=dict)
async def post_exercises(uhid: str, exercises: List[ExerciseEntry]):
    """Post exercises separately to Azure FHIR as Task resources."""
    headers = get_headers()
    try:
        for ex in exercises:
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
                # ✅ Include both progress and duration_days
                "note": [
                    {"text": f"Progress: {ex.progress_percentage}%"},
                    {"text": f"Duration Days: {ex.duration_days}"}
                ]
            }

            # Add exercise video in a FHIR-compliant way
            if ex.exercise_video:
                task["input"] = [
                    {
                        "type": {
                            "coding": [
                                {
                                    "system": "http://terminology.hl7.org/CodeSystem/task-input-type",
                                    "code": "attachment",
                                    "display": "Exercise Video"
                                }
                            ],
                            "text": "Exercise Video URL"
                        },
                        "valueUrl": ex.exercise_video
                    }
                ]

            response = requests.post(f"{FHIR_URL}/Task", json=task, headers=headers)
            if response.status_code >= 400:
                return {
                    "success": False,
                    "message": f"Error posting Task: {response.status_code} {response.text}"
                }

        return {"success": True, "message": f"{len(exercises)} exercise(s) posted successfully."}

    except Exception as e:
        return {"success": False, "message": str(e)}



@app.post("/rehab/instructions", response_model=dict)
async def post_instructions(uhid: str, instructions: List[RehabInstructions]):
    """Post rehab instructions separately."""
    headers = get_headers()
    try:
        for instr in instructions:
            obs = {
                "resourceType": "Observation",
                "identifier": [{"system": "https://hospital.com/uhid", "value": uhid}],
                "status": "final",
                "code": {"text": "Rehabilitation Instruction"},
                "subject": {"reference": f"Patient/{uhid}"},
                "valueString": instr.instruction_text,
                "effectiveDateTime": instr.timestamp.isoformat()
            }
            response = requests.post(f"{FHIR_URL}/Observation", json=obs, headers=headers)
            if response.status_code >= 400:
                return {"success": False, "message": f"Error posting Observation: {response.status_code} {response.text}"}

        return {"success": True, "message": f"{len(instructions)} instruction(s) posted successfully."}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.get("/rehab/exercises", response_model=dict)
def get_exercises(uhid: str):
    """Fetch exercises for a patient from Azure FHIR."""
    headers = get_headers()
    exercises = []

    try:
        response = requests.get(
            f"{FHIR_URL}/Task",
            headers=headers,
            params={"subject": f"Patient/{uhid}"}
        )
        data = response.json()

        for entry in data.get("entry", []):
            res = entry.get("resource", {})
            if res.get("resourceType") != "Task":
                continue

            # Extract exercise video URL if present
            video_url = None
            for inp in res.get("input", []):
                if inp.get("valueUrl"):
                    video_url = inp["valueUrl"]

            # Extract progress percentage and duration_days from notes
            progress_percentage = None
            duration_days = None
            progress_notes = []

            for note in res.get("note", []):
                text = note.get("text")
                if not text:
                    continue

                progress_notes.append(text)

                if text.startswith("Progress:"):
                    try:
                        progress_percentage = float(text.split("Progress:")[1].replace("%", "").strip())
                    except ValueError:
                        progress_percentage = None

                elif text.startswith("Duration Days:"):
                    try:
                        duration_days = int(text.split("Duration Days:")[1].strip())
                    except ValueError:
                        duration_days = None

            exercises.append({
                "id": res.get("id"),
                "name": res.get("description"),
                "status": res.get("status"),
                "execution_period": res.get("executionPeriod"),
                "progress_percentage": progress_percentage,
                "exercise_video": video_url,
                "duration_days": duration_days,
                "completed_timestamp": res.get("executionPeriod", {}).get("end"),
                "progress_notes": progress_notes
            })

        return {"success": True, "exercises": exercises}

    except Exception as e:
        return {"success": False, "exercises": [], "error": str(e)}




@app.get("/rehab/instructions", response_model=dict)
def get_rehab_instructions(uhid: str):
    """
    Fetch only rehabilitation instructions for a patient by UHID.
    """
    headers = get_headers()  # your function to generate FHIR Authorization headers
    instructions = []

    try:
        # Fetch Observation resources from FHIR server
        response = requests.get(
            f"{FHIR_URL}/Observation",
            headers=headers,
            params={"_count": 1000, "subject": f"Patient/{uhid}"}
        )
        response.raise_for_status()
        data = response.json()

        for entry in data.get("entry", []):
            res = entry.get("resource", {})
            # Filter only Rehabilitation Instructions for this UHID
            if res.get("resourceType") == "Observation" \
               and res.get("code", {}).get("text") == "Rehabilitation Instruction" \
               and any(identifier.get("value") == uhid for identifier in res.get("identifier", [])):
                instructions.append({
                    "id": res.get("id"),
                    "instruction_text": res.get("valueString"),
                    "timestamp": res.get("effectiveDateTime")
                })

        return {"success": True, "instructions": instructions}

    except Exception as e:
        return {"success": False, "instructions": [], "error": str(e)}
    
@app.get("/rehab/exercises/in-progress", response_model=dict)
def get_in_progress_exercises(uhid: str):
    """Fetch all in-progress exercises for a patient by UHID."""
    headers = get_headers()
    exercises = []

    try:
        response = requests.get(
            f"{FHIR_URL}/Task",
            headers=headers,
            params={"subject": f"Patient/{uhid}"}
        )

        if response.status_code != 200:
            return {
                "success": False,
                "message": f"FHIR fetch error: {response.status_code} {response.text}"
            }

        data = response.json()

        for entry in data.get("entry", []):
            res = entry.get("resource", {})
            if res.get("resourceType") == "Task" and res.get("status") == "in-progress":
                
                # ✅ Extract exercise video URL (same as in /rehab/exercises)
                video_url = None
                for inp in res.get("input", []):
                    if inp.get("valueUrl"):
                        video_url = inp["valueUrl"]

                # ✅ Extract progress_percentage and duration_days from notes
                progress_percentage = None
                duration_days = None
                progress_notes = []

                for note in res.get("note", []):
                    text = note.get("text")
                    if not text:
                        continue

                    progress_notes.append(text)

                    if text.startswith("Progress:"):
                        try:
                            progress_percentage = float(
                                text.split("Progress:")[1].replace("%", "").strip()
                            )
                        except ValueError:
                            progress_percentage = None

                    elif text.startswith("Duration Days:"):
                        try:
                            duration_days = int(
                                text.split("Duration Days:")[1].strip()
                            )
                        except ValueError:
                            duration_days = None

                exercises.append({
                    "id": res.get("id"),
                    "name": res.get("description"),
                    "status": res.get("status"),
                    "execution_period": res.get("executionPeriod"),
                    "progress_percentage": progress_percentage,
                    "duration_days": duration_days,
                    "exercise_video": video_url,  # ✅ Added here
                    "progress_notes": progress_notes,
                })

        return {"success": True, "in_progress_exercises": exercises}

    except Exception as e:
        return {
            "success": False,
            "in_progress_exercises": [],
            "error": str(e)
        }

    
@app.delete("/rehab/exercises", response_model=dict)
def delete_exercise(uhid: str, exercise_name: str):
    """
    Delete a Task (exercise) for a given UHID and exercise name 
    only if it is not completed (status = 'in-progress').
    """
    headers = get_headers()
    try:
        # 1️⃣ Fetch all tasks for the patient
        response = requests.get(
            f"{FHIR_URL}/Task",
            headers=headers,
            params={"subject": f"Patient/{uhid}"}
        )
        if response.status_code >= 400:
            return {
                "success": False,
                "message": f"Error fetching Tasks: {response.status_code} {response.text}"
            }

        data = response.json()
        deleted_count = 0

        # 2️⃣ Filter and delete tasks matching criteria
        for entry in data.get("entry", []):
            res = entry.get("resource", {})
            if res.get("resourceType") != "Task":
                continue

            task_id = res.get("id")
            task_name = res.get("description", "")
            task_status = res.get("status")

            if (
                task_status == "in-progress"
                and exercise_name.lower() in task_name.lower()
            ):
                delete_url = f"{FHIR_URL}/Task/{task_id}"
                del_response = requests.delete(delete_url, headers=headers)

                if del_response.status_code in (200, 204):
                    deleted_count += 1
                else:
                    return {
                        "success": False,
                        "message": f"Error deleting Task {task_id}: {del_response.text}"
                    }

        if deleted_count == 0:
            return {
                "success": False,
                "message": f"No in-progress exercise named '{exercise_name}' found for UHID {uhid}."
            }

        return {
            "success": True,
            "message": f"Deleted {deleted_count} exercise(s) named '{exercise_name}' for UHID {uhid}."
        }

    except Exception as e:
        return {"success": False, "message": str(e)}

    
# ---------------------- MEALS ----------------------
@app.post("/fhir/meals", response_model=dict)
async def post_meals(uhid: str, meals: TodaysMeal):
    """
    Post daily meal plan as FHIR NutritionOrder resources.
    """
    headers = get_headers()  # Your function to generate FHIR headers
    bundle = fhir_meal_resources(uhid, meals)

    try:
        for entry in bundle.get("entry", []):
            res = entry["resource"]
            response = requests.post(f"{FHIR_URL}/{res['resourceType']}", json=res, headers=headers)
            if response.status_code >= 400:
                return {"success": False, "message": f"Error posting {res['resourceType']}: {response.status_code} {response.text}"}

        return {"success": True, "message": f"{len(bundle.get('entry', []))} meal(s) posted successfully."}

    except Exception as e:
        return {"success": False, "message": str(e)}

@app.get("/fhir/meals", response_model=dict)
def get_meals(uhid: str):
    """
    Fetch all NutritionOrder resources for a patient.
    """
    headers = get_headers()
    meals_list = []

    try:
        response = requests.get(
            f"{FHIR_URL}/NutritionOrder",
            headers=headers,
            params={"subject": f"Patient/{uhid}", "_count": 1000}
        )
        response.raise_for_status()
        data = response.json()

        for entry in data.get("entry", []):
            res = entry.get("resource", {})
            if res.get("resourceType") == "NutritionOrder" and any(
                identifier.get("value") == uhid for identifier in res.get("identifier", [])
            ):
                meals_list.append({
                    "id": res.get("id"),
                    "period": res.get("oralDiet", {}).get("type", [{}])[0].get("text"),
                    "description": res.get("oralDiet", {}).get("instruction"),
                    "dateTime": res.get("dateTime")
                })

        return {"success": True, "meals": meals_list}

    except Exception as e:
        return {"success": False, "meals": [], "error": str(e)}

# -------------------- CREATE ORDER --------------------
@app.post("/create-order")
def create_order(payment: PaymentRequest):
    try:
        order_data = {
            "amount": payment.amount * 100,
            "currency": payment.currency,
            "receipt": payment.receipt,
            "payment_capture": 1
        }
        order = client.order.create(data=order_data)
        return {
            "success": True,
            "order_id": order["id"],
            "amount": payment.amount,
            "currency": payment.currency
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/verify-payment")
def verify_payment(request: VerifyPaymentRequest):
    try:
        client.utility.verify_payment_signature({
            "razorpay_order_id": request.razorpay_order_id,
            "razorpay_payment_id": request.razorpay_payment_id,
            "razorpay_signature": request.razorpay_signature,
        })
        return {"success": True, "message": "Payment verified successfully"}
    except razorpay.errors.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid payment signature")
    
@app.post("/upload-image", response_model=dict)
async def upload_image(file: UploadFile = File(...)):
    """
    Upload an image file to Azure Blob Storage.
    Returns the URL of the uploaded blob.
    """
    try:
        blob_name = file.filename
        blob_client = blob_service_client.get_blob_client(container=CONTAINER_NAME, blob=blob_name)

        # Read file contents and upload
        file_data = await file.read()
        blob_client.upload_blob(file_data, overwrite=True)

        blob_url = f"{ACCOUNT_URL}{CONTAINER_NAME}/{blob_name}"
        return {"success": True, "blob_url": blob_url, "file_name": blob_name}

    except Exception as e:
        return {"success": False, "error": str(e)}
    
@app.get("/list-blobs", response_model=dict)
def list_blobs():
    """
    List all blobs in the container and return their URLs.
    """
    try:
        blobs = []
        for blob in container_client.list_blobs():
            blob_url = f"{ACCOUNT_URL}{CONTAINER_NAME}/{blob.name}"
            blobs.append({
                "name": blob.name,
                "url": blob_url
            })

        return {"success": True, "blobs": blobs}

    except Exception as e:

        return {"success": False, "error": str(e)}

