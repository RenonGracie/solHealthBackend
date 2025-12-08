---
  

  ---
  2) INTAKEQ PROFILE CREATION PAYLOAD

  File: solHealthBackend/src/api/intakeq_forms.py:1142
  Endpoint: POST https://intakeq.com/api/v1/clients

  {
    // === CORE IDENTIFICATION ===
    "Name": "Jane Smith",
    "FirstName": "Jane",
    "LastName": "Smith",
    "MiddleName": "",
    "Email": "jane.smith@example.com",

    // === CONTACT INFORMATION ===
    "Phone": "5551234567",
    "MobilePhone": "5551234567",
    "HomePhone": "",
    "WorkPhone": "",

    // === DEMOGRAPHICS ===
    "Gender": "Female",
    "MaritalStatus": "",
    "DateOfBirth": 826847400000,  // Unix timestamp in milliseconds

    // === ADDRESS INFORMATION (Enhanced with Nirvana) ===
    "StreetAddress": "123 Main St",
    "UnitNumber": "",
    "City": "New York",
    "StateShort": "NY",
    "PostalCode": "10001",
    "Country": "USA",
    "Address1": "123 Main St",
    "Address2": "",
    "State": "NY",
    "Zip": "10001",

    // === INSURANCE INFORMATION (for insurance clients) ===
    "PrimaryInsuranceCompany": "Aetna Better Health",
    "PrimaryInsurancePayerId": "60054",
    "PrimaryInsurancePolicyNumber": "ABC123456789",
    "PrimaryInsuranceGroupNumber": "GRP12345",
    "PrimaryInsurancePlan": "Aetna Better Health",
    "PrimaryInsuranceHolderName": "John Smith",
    "PrimaryInsuranceHolderDateOfBirth": 643248000000,
    "PrimaryInsuranceRelationship": "child",
    "PrimaryRelationshipToInsured": "Child",

    // === INSURED/SUBSCRIBER DEMOGRAPHICS (if parent-child relationship) ===
    "PrimaryInsuredGender": "Male",
    "PrimaryInsuredCity": "New York",
    "PrimaryInsuredState": "NY",
    "PrimaryInsuredStreetAddress": "123 Main St",
    "PrimaryInsuredZipCode": "10001",

    // === SYSTEM FIELDS ===
    "Archived": false,
    "DateCreated": 1737811800000,
    "LastActivityDate": 1737811800000,
    "LastActivityName": "Client Added",

    // === CUSTOM FIELDS (therapy-specific data) ===
    "CustomFields": [
      {
        "FieldId": "cf_phq9_total",
        "Value": "10"
      },
      {
        "FieldId": "cf_gad7_total",
        "Value": "9"
      },
      {
        "FieldId": "cf_what_brings_you",
        "Value": "I've been feeling anxious and stressed about work and relationships."
      },
      {
        "FieldId": "cf_therapist_specialization",
        "Value": "Anxiety, Stress & burnout, Dating & relationships"
      },
      {
        "FieldId": "cf_lived_experiences",
        "Value": "First-generation college student, LGBTQ+ identity"
      }
    ]
  }

  ---
  2) INTAKEQ APPOINTMENT CREATION PAYLOAD

  File: solHealthBackend/src/utils/intakeq/booking.py:235
  Endpoint: POST https://intakeq.com/api/v1/appointments

  {
    "PractitionerId": "prac_xyz789",
    "ClientId": "client_abc123",
    "LocationId": "1",
    "UtcDateTime": 1737990000000,  // Unix timestamp in milliseconds (UTC)
    "ServiceId": "serv_initial_session_60min",
    "SendClientEmailNotification": true,
    "ReminderType": "email",
    "Status": "Confirmed",  // or "AwaitingConfirmation"
    "ClientTimeZone": "America/New_York",  // For associate therapists
    "Notes": "Join your session: https://meet.google.com/abc-defg-hij"
  }
