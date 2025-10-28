# Progressive Logger Enhancement - Deployment Guide

## Implementation Summary

Successfully implemented Google Sheets progressive logger enhancement with 3-stage tracking system and therapist selection analytics.

---

## ⚠️ IMPORTANT: AUTO_MIGRATE System (Not Alembic!)

**Your system uses AUTO_MIGRATE, not traditional Alembic migrations.**

When your Flask app starts on Railway, it automatically:
1. ✅ Detects new columns in your models
2. ✅ Runs `ALTER TABLE ADD COLUMN IF NOT EXISTS` for each missing column
3. ✅ Creates indexes defined in `ensure_indexes_and_constraints()`
4. ✅ All changes happen automatically on first startup after deploy

**You don't need to run any migration commands manually!**

---

## What Changed

### 1. Database Schema (`src/db/models.py`)
Added 9 new columns to `ClientResponse` model:
- `therapist_gender_preference` - User's therapist gender preference
- `browser_timezone` - User's browser timezone
- `insurance_provider_corrected` - Boolean flag for Nirvana corrections (default: FALSE)
- `algorithm_suggested_therapist_id` - Algorithm's #1 pick
- `algorithm_suggested_therapist_name` - Name of suggested therapist
- `algorithm_suggested_therapist_score` - Match score
- `alternative_therapists_offered` - JSON with all matches {count, names, ids, scores}
- `user_chose_alternative` - Boolean if user picked different than suggested (default: FALSE)
- `therapist_selection_timestamp` - When user made their selection

### 2. AUTO_MIGRATE Enhancement (`src/db/__init__.py`)
Enhanced `reconcile_schema()` to handle:
- ✅ Boolean columns with default values (FALSE)
- ✅ JSON/JSONB columns
- ✅ All standard SQL types

Added 3 new indexes to `ensure_indexes_and_constraints()`:
- `ix_client_responses_algorithm_suggested`
- `ix_client_responses_user_chose_alternative`
- `ix_client_responses_selection_timestamp`

### 3. Progressive Logger Stages (RESTRUCTURED)
**NEW 3-Stage System:**
- **Stage 1**: Email capture (partial submission) - NEW!
  - Trigger: User enters email and starts survey
  - Captures: email, first_name, session_id, UTM params, technical metadata

- **Stage 2**: Survey completion + therapist match (with optional Nirvana)
  - Trigger: User completes survey (PHQ-9, GAD-7, preferences)
  - Captures: All survey data, preferences, algorithm matches, optional Nirvana data
  - **Key Change**: Nirvana is now OPTIONAL (only for insurance users, skipped for cash-pay)

- **Stage 3**: Appointment booked
  - Trigger: User books appointment
  - Captures: Selected therapist (vs suggested), appointment details, IntakeQ IDs
  - **Key Addition**: Tracks if user chose different therapist than algorithm suggested

**Removed**: Old Stage 0 (Nirvana-only) - merged into Stage 2

### 4. Google Sheets Headers
Added 15+ new columns including:
- Algorithm suggested vs selected therapist tracking
- Alternative therapists count and names
- Insurance correction tracking fields
- Technical metadata (screen_resolution, browser_timezone)

### 5. API Endpoints Updated
- **`/clients_signup`**: Auto-detects partial vs complete submissions, logs Stage 1 or Stage 2
- **`/therapists/match`**: Stores algorithm suggestions and alternatives in database
- **`/appointments`**: Tracks therapist selection, compares selected vs suggested, logs Stage 3

---

## Deployment Steps for Railway

### Step 1: Commit and Push Changes

```bash
cd /Users/renogra/solHealthBackend

# Stage all changes
git add .

# Commit with descriptive message
git commit -m "feat: Progressive logger enhancement - 3-stage system with therapist selection tracking

- Add 9 new database columns for therapist selection analytics
- Enhanced AUTO_MIGRATE to handle boolean defaults
- Restructure to 3-stage system (email, survey+match, booking)
- Track algorithm suggested vs user selected therapist
- Store alternatives for analytics
- Update all endpoints to support new flow"

# Push to main branch (Railway auto-deploys from main)
git push origin main
```

### Step 2: Wait for Railway Deployment + AUTO_MIGRATE

**Railway will automatically:**
1. Deploy your new code
2. Start the Flask application
3. Run `run_schema_bootstrap(engine)` on startup
4. Execute `reconcile_schema()` which adds all 9 new columns
5. Execute `ensure_indexes_and_constraints()` which creates 3 new indexes

**You'll see these log messages in Railway:**
```
🧩 Adding missing column: client_responses.therapist_gender_preference (VARCHAR)
🧩 Adding missing column: client_responses.browser_timezone (VARCHAR)
🧩 Adding missing column: client_responses.insurance_provider_corrected (BOOLEAN)
🧩 Adding missing column: client_responses.algorithm_suggested_therapist_id (VARCHAR)
🧩 Adding missing column: client_responses.algorithm_suggested_therapist_name (VARCHAR)
🧩 Adding missing column: client_responses.algorithm_suggested_therapist_score (FLOAT)
🧩 Adding missing column: client_responses.alternative_therapists_offered (JSONB)
🧩 Adding missing column: client_responses.user_chose_alternative (BOOLEAN)
🧩 Adding missing column: client_responses.therapist_selection_timestamp (TIMESTAMPTZ)
✅ Schema reconciliation complete
✅ Indexes/constraints ensured
```

**Timeline:**
- Push to GitHub: ~10 seconds
- Railway build: ~2-3 minutes
- Deploy + AUTO_MIGRATE: ~30 seconds
- **Total: ~3-4 minutes from push to live**

---

## Step 3: Verify Migration Success

After Railway deploys (watch the logs), verify columns were added:

### Option A: Using Railway CLI
```bash
# Install Railway CLI if not already
npm install -g @railway/cli

# Login and link
railway login
railway link

# Check the schema
railway run psql $DATABASE_URL -c "\d client_responses" | grep -E "therapist_gender|browser_timezone|insurance_provider_corrected|algorithm_suggested|alternative_therapists|user_chose_alternative|therapist_selection"
```

### Option B: Using Railway Dashboard
1. Go to your Railway project
2. Click on your Postgres database service
3. Click "Data" tab
4. Run this query:
```sql
SELECT column_name, data_type, column_default
FROM information_schema.columns
WHERE table_name = 'client_responses'
AND column_name IN (
    'therapist_gender_preference',
    'browser_timezone',
    'insurance_provider_corrected',
    'algorithm_suggested_therapist_id',
    'user_chose_alternative'
)
ORDER BY column_name;
```

**Expected output:**
| column_name | data_type | column_default |
|-------------|-----------|----------------|
| algorithm_suggested_therapist_id | character varying | |
| browser_timezone | character varying | |
| insurance_provider_corrected | boolean | false |
| therapist_gender_preference | character varying | |
| user_chose_alternative | boolean | false |

---

## Step 4: Run Super-Sync Command

Once deployment is complete and columns are verified, sync existing data:

```bash
# Replace YOUR_RAILWAY_URL with your actual Railway backend URL
curl -X POST https://YOUR_RAILWAY_URL/super-sync

# Example:
# curl -X POST https://solhealthbackend-production.up.railway.app/super-sync
```

Expected response:
```json
{
  "success": true,
  "message": "Super sync completed",
  "airtable_synced": 150,
  "google_sheets_synced": 150
}
```

---

## Step 5: Verify Google Sheets Data

1. Open your "All Journeys" Google Sheet
2. Check for new columns in the header row:
   - `algorithm_suggested_therapist_id`
   - `algorithm_suggested_therapist_name`
   - `algorithm_suggested_therapist_score`
   - `alternative_therapists_count`
   - `alternative_therapists_names`
   - `selected_therapist_id`
   - `selected_therapist_name`
   - `user_chose_alternative`
   - `insurance_provider_corrected`

3. Verify data is populating correctly for new submissions

---

## Testing the New Flow

### Test 1: Partial Submission (Stage 1)
```bash
curl -X POST https://YOUR_RAILWAY_URL/clients_signup \
  -H "Content-Type: application/json" \
  -d '{
    "response_id": "test-partial-123",
    "email": "test@example.com",
    "first_name": "Test",
    "utm_source": "test",
    "session_id": "sess-123"
  }'
```

**Expected**: Stage 1 row created in Google Sheets with email and UTM data only.

### Test 2: Complete Submission (Stage 2) - Cash Pay
```bash
curl -X POST https://YOUR_RAILWAY_URL/clients_signup \
  -H "Content-Type: application/json" \
  -d '{
    "response_id": "test-cashpay-456",
    "email": "test2@example.com",
    "first_name": "Test",
    "last_name": "User",
    "payment_type": "cash_pay",
    "pleasure_doing_things": 2,
    "feeling_down": 1,
    "trouble_falling": 1,
    "feeling_tired": 2,
    "poor_appetite": 1,
    "feeling_bad_about_yourself": 0,
    "trouble_concentrating": 1,
    "moving_or_speaking_so_slowly": 0,
    "suicidal_thoughts": 0,
    "feeling_nervous": 2,
    "not_control_worrying": 1,
    "worrying_too_much": 2,
    "trouble_relaxing": 1,
    "being_so_restless": 1,
    "easily_annoyed": 0,
    "feeling_afraid": 1
  }'
```

**Expected**: Stage 2 row created with full survey data, Nirvana skipped.

### Test 3: Therapist Match
```bash
curl "https://YOUR_RAILWAY_URL/therapists/match?response_id=test-cashpay-456"
```

**Expected**:
- Database updated with `algorithm_suggested_therapist_id` and `alternative_therapists_offered`
- Google Sheets updated with match data
- Response shows matched therapists

### Test 4: Appointment Booking (Stage 3)
```bash
curl -X POST https://YOUR_RAILWAY_URL/appointments \
  -H "Content-Type: application/json" \
  -d '{
    "client_response_id": "test-cashpay-456",
    "therapist_email": "therapist@example.com",
    "therapist_name": "Jane Smith",
    "start_date_iso": "2025-10-30T14:00:00Z",
    "duration_minutes": 45
  }'
```

**Expected**:
- Database updated with `user_chose_alternative` (TRUE if different from suggested)
- Stage 3 logged to Google Sheets with selection tracking
- Log message: "✅ User chose algorithm's #1 suggestion" or "🔄 User chose alternative therapist"

---

## Troubleshooting

### Issue: Columns Not Added Automatically

**Check AUTO_MIGRATE is enabled:**
```bash
railway run env | grep AUTO_MIGRATE
```

Should show: `AUTO_MIGRATE=true` (or not set, defaults to true)

**If disabled, enable it:**
```bash
railway variables set AUTO_MIGRATE=true
```

Then redeploy.

### Issue: "Column already exists" Errors

This is **expected and safe**. The system uses `ADD COLUMN IF NOT EXISTS` which is idempotent.

### Issue: Boolean Columns Show NULL Instead of FALSE

Run this manual fix:
```sql
UPDATE client_responses
SET insurance_provider_corrected = FALSE
WHERE insurance_provider_corrected IS NULL;

UPDATE client_responses
SET user_chose_alternative = FALSE
WHERE user_chose_alternative IS NULL;
```

### Manual Migration (Last Resort)

If AUTO_MIGRATE fails for any reason, you can run the manual SQL:

```bash
# Using Railway CLI
railway run psql $DATABASE_URL < manual_migration.sql

# Or via Railway Dashboard Data tab - paste contents of manual_migration.sql
```

---

## Rollback Plan (If Needed)

If you encounter critical issues:

### 1. Rollback Code Changes
```bash
# Find the commit hash before this change
git log --oneline | head -10

# Revert to previous commit
git revert <commit-hash>

# Push to trigger Railway redeploy
git push origin main
```

### 2. Remove Columns (if needed)
```sql
-- Only do this if absolutely necessary!
ALTER TABLE client_responses DROP COLUMN IF EXISTS therapist_gender_preference;
ALTER TABLE client_responses DROP COLUMN IF EXISTS browser_timezone;
ALTER TABLE client_responses DROP COLUMN IF EXISTS insurance_provider_corrected;
ALTER TABLE client_responses DROP COLUMN IF EXISTS algorithm_suggested_therapist_id;
ALTER TABLE client_responses DROP COLUMN IF EXISTS algorithm_suggested_therapist_name;
ALTER TABLE client_responses DROP COLUMN IF EXISTS algorithm_suggested_therapist_score;
ALTER TABLE client_responses DROP COLUMN IF EXISTS alternative_therapists_offered;
ALTER TABLE client_responses DROP COLUMN IF EXISTS user_chose_alternative;
ALTER TABLE client_responses DROP COLUMN IF EXISTS therapist_selection_timestamp;
```

---

## Monitoring

### Check Railway Logs

**Success indicators:**
- `✅ Stored algorithm suggestions: #1=<therapist_name>, total=<count>`
- `📊 [STAGE 1] Partial submission detected`
- `📊 [STAGE 2] Complete submission detected`
- `✅ User chose algorithm's #1 suggestion`
- `🔄 User chose alternative therapist`
- `🧩 Adding missing column: client_responses.*`
- `✅ Schema reconciliation complete`

**Error indicators:**
- `❌ Failed to store algorithm suggestions`
- `❌ [STAGE X] Error logging`
- `Failed to log to Google Sheets`
- `Schema reconciliation error`

---

## Environment Variables Required

Ensure these are set in Railway:
- `DATABASE_URL` - PostgreSQL connection string (auto-set by Railway)
- `AUTO_MIGRATE` - Should be `true` or unset (defaults to true)
- `GOOGLE_SHEETS_ID` - Your Google Sheets spreadsheet ID
- `GOOGLE_CREDENTIALS_JSON` or `GOOGLE_CREDENTIALS_JSON_B64` - Service account credentials

---

## Summary of Benefits

After deployment, you'll have:
1. ✅ **Automatic schema updates** - No manual migrations needed!
2. ✅ **Partial submission tracking** - Never lose early-stage users
3. ✅ **Algorithm performance metrics** - See how often users choose alternatives
4. ✅ **Complete user journey** - Track every step from email to booking
5. ✅ **Insurance correction tracking** - Monitor Nirvana validation accuracy
6. ✅ **Better analytics** - Understand user behavior and algorithm effectiveness

---

## FAQ

**Q: Do I need to run Alembic migrations?**
A: **NO!** Your system uses AUTO_MIGRATE. Just push and deploy. Columns are added automatically on startup.

**Q: What if I push and the columns don't appear?**
A: Check Railway logs for `reconcile_schema` messages. If AUTO_MIGRATE is disabled, enable it with `railway variables set AUTO_MIGRATE=true`.

**Q: Will this affect existing data?**
A: No, new columns are added as nullable. Existing data is preserved.

**Q: Can I deploy during business hours?**
A: Yes! The schema update happens in seconds during startup. Zero downtime.

**Q: What if something goes wrong?**
A: Rollback via git revert. The old code works fine without the new columns (they're optional).

---

**✅ Ready to Deploy!**

Your system is configured to automatically handle the schema changes. Just:
1. `git push origin main`
2. Wait ~4 minutes for Railway to deploy
3. Verify in logs: `✅ Schema reconciliation complete`
4. Run `/super-sync`
5. Check Google Sheets for new columns

That's it! 🚀
