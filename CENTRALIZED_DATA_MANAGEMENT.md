# Centralized Data Management System

This document explains the new centralized data management system that ensures all user data, including Nirvana insurance verification data, flows properly through all components.

## Problem Solved

Previously, data like Nirvana insurance verification results could get lost between services due to:
- Variable scope issues
- Inconsistent field naming
- Data not being passed through properly
- Each service extracting data differently

## Solution

The new system provides:
- **Single source of truth** for all user data
- **Automatic data extraction** from various field formats
- **Progressive data enrichment** as users flow through stages
- **Service-specific optimization** for different APIs
- **Comprehensive audit trail** and debugging

## Architecture

```
UserDataManager (Central Store)
├── Data normalization & enrichment
├── Nirvana data extraction & structuring
├── Progressive snapshots by stage
└── Service-specific optimizations

DataFlowIntegration (Integration Layer)
├── Wrapper functions for existing services
├── Stage-based data updates
└── Fallback to legacy methods

Existing Services (Enhanced)
├── IntakeQ Forms API
├── Google Sheets Progressive Logger
├── Appointment Scheduling
└── Therapist Matching
```

## Usage Examples

### 1. Initialize User Data (Start of Flow)
```python
from src.services.data_flow_integration import ensure_user_data_initialized

# At the beginning of any user flow
response_id = "12345"
survey_data = {
    "first_name": "John",
    "last_name": "Doe",
    "email": "john@example.com",
    "insurance_verification_data": nirvana_response,  # Raw Nirvana data
    # ... other fields
}

enriched_data = ensure_user_data_initialized(response_id, survey_data)
# Now enriched_data has properly extracted nirvana_data field
```

### 2. Update Data During Flow
```python
from src.services.data_flow_integration import update_user_data_with_therapist_match

# When therapist matching completes
match_data = {
    "matched_therapist_id": "therapist_123",
    "matched_therapist_name": "Dr. Smith",
    "match_score": 95
}

updated_data = update_user_data_with_therapist_match(response_id, match_data)
```

### 3. Get Data for Specific Services
```python
from src.services.data_flow_integration import get_data_for_intakeq_creation

# Get data optimized for IntakeQ
intakeq_data = get_data_for_intakeq_creation(response_id)
# This data will have properly structured nirvana_data

# Get data optimized for Google Sheets
sheets_data = get_data_for_google_sheets_logging(response_id)
# This data will have flattened Nirvana fields for sheets columns
```

### 4. Automatic Google Sheets Logging
```python
from src.services.data_flow_integration import log_to_google_sheets_progressive

# Log to progressive logger with all data properly structured
success = log_to_google_sheets_progressive(response_id, stage=1)
```

## Migration Strategy

The system is designed for **gradual migration** with **zero breaking changes**:

1. **Phase 1** (Current): New centralized system runs alongside existing code
   - IntakeQ Forms API already updated to try centralized first, fall back to legacy
   - Existing functionality continues to work unchanged

2. **Phase 2**: Migrate other services one by one
   - Therapist matching API
   - Appointment scheduling
   - Form sending endpoints

3. **Phase 3**: Remove legacy code once all services migrated

## Key Benefits

### For Nirvana Data Specifically:
- **Automatic Extraction**: Finds Nirvana data in any field name (`insurance_verification_data`, `nirvana_response`, etc.)
- **Proper Structuring**: Normalizes the data for consistent access patterns
- **Field Availability**: Ensures fields like `plan_name`, `group_id`, `payer_id` are always available
- **Service Optimization**: Flattens nested fields for Google Sheets, keeps structured for APIs

### For All Data:
- **Data Persistence**: User data survives across all service calls
- **Progressive Enrichment**: Data gets richer as user progresses through flow
- **Audit Trail**: Complete history of what data was available when
- **Debugging**: Comprehensive logging of data flow and transformations

## Debugging Features

### Data Audit Reports
```python
from src.services.data_flow_integration import get_user_data_audit_report

audit = get_user_data_audit_report(response_id)
print(audit)
# Shows: field counts, completeness analysis, missing critical fields, etc.
```

### Enhanced Logging
The system provides detailed logs showing:
- What data is available at each stage
- Where Nirvana data was found
- Which fields are populated vs missing
- Service-specific data optimizations

## Example: Complete IntakeQ Flow

```python
# 1. User completes survey with insurance info
survey_data = {
    "first_name": "Jane",
    "last_name": "Smith",
    "email": "jane@example.com",
    "insurance_provider": "Blue Cross",
    "nirvana_response": raw_nirvana_api_response,  # Contains plan_name, payer_id, etc.
}

# 2. Initialize centralized data management
enriched_data = ensure_user_data_initialized(response_id, survey_data)
# Now enriched_data["nirvana_data"] contains normalized insurance fields

# 3. Create IntakeQ client (automatically uses centralized data)
intakeq_response = requests.post("/intakeq/create-client", json=enriched_data)

# 4. Google Sheets logging happens automatically with all Nirvana fields populated
```

## Current Status

✅ **UserDataManager**: Core centralized data store implemented
✅ **DataFlowIntegration**: Integration layer implemented
✅ **IntakeQ Forms API**: Updated to use centralized system (with legacy fallback)
✅ **Google Sheets Logger**: Enhanced debugging for Nirvana data detection

🔄 **Next Steps**:
- Monitor centralized system in production
- Migrate other endpoints one by one
- Remove legacy code after full migration

The system is **production-ready** and **backwards-compatible**. It will improve data consistency immediately while allowing for gradual migration of existing code.
