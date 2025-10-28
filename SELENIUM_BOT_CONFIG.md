# Selenium Bot Configuration & Troubleshooting

## Overview

The IntakeQ Selenium bot (`intakeq_selenium_bot.py`) is used to automatically assign practitioners to clients in the IntakeQ system. It runs **only during the booking flow**, not at application startup.

## When Does the Bot Run?

The selenium bot is triggered **ONLY** when:
1. A client completes the entire booking flow
2. An IntakeQ client profile is successfully created
3. The async post-booking task processor executes

**It does NOT run:**
- ❌ At application startup
- ❌ During health checks
- ❌ During blueprint registration
- ❌ During database initialization

## Architecture

### Import Strategy (Lazy Loading)
```python
# ✅ GOOD: Imports are inside functions, not at module level
def book_appointment():
    try:
        from intakeq_selenium_bot import assign_intakeq_practitioner
        selenium_available = True
    except ImportError:
        selenium_available = False
        # App continues without selenium
```

### Execution Flow
```
1. User completes booking
2. IntakeQ client created
3. Appointment saved to database
4. Response returned to user (booking confirmed)
   ↓
5. [ASYNC] Background thread starts
6. [ASYNC] Wait 10 seconds for IntakeQ to process
7. [ASYNC] Import selenium bot (lazy)
8. [ASYNC] Execute practitioner assignment
9. [ASYNC] Update database status
```

## Configuration

### Environment Variables

#### Required for Selenium Bot
```bash
# Selenium Grid URL (Railway deployment)
SELENIUM_GRID_URL=http://selenium-grid:4444/wd/hub

# IntakeQ Credentials
CASH_PAY_INTAKEQ_USR=your_username
CASH_PAY_INTAKEQ_PAS=your_password
INSURANCE_INTAKEQ_USR=your_username
INSURANCE_INTAKEQ_PAS=your_password
```

#### Optional - Disable Selenium Completely
```bash
# Set this to completely disable selenium bot (for testing/debugging)
DISABLE_SELENIUM_BOT=true
```

When disabled:
- Booking flow continues normally
- Practitioner assignment is skipped
- Status set to "disabled" in database
- No errors thrown

## Troubleshooting

### Issue: Slow First Booking Request

**Symptom**: First booking after deployment takes 3-5 seconds longer

**Cause**: Selenium module imports for the first time during request

**Solution**: This is expected behavior. Subsequent bookings will be fast.

**Workaround**: Use a warmup request after deployment:
```bash
curl -X POST https://your-api.com/railway/assign-practitioner \
  -H "Content-Type: application/json" \
  -d '{"account_type":"insurance","client_id":"test","therapist_full_name":"Test User"}'
```

### Issue: Selenium Grid Not Available

**Symptom**: Logs show "Selenium Grid not available"

**Impact**: Booking succeeds, but practitioner not assigned automatically

**Solution**:
1. Check Selenium Grid is deployed and running
2. Verify `SELENIUM_GRID_URL` environment variable
3. Check network connectivity between services

**Graceful Degradation**: The app continues to work without selenium

### Issue: Import Errors at Startup

**Symptom**: App fails to start with selenium-related errors

**Diagnosis Steps**:
1. Check if selenium is in requirements.txt:
   ```bash
   grep selenium requirements.txt
   ```

2. Verify imports are lazy (inside functions):
   ```bash
   grep -n "^from intakeq_selenium_bot" src/**/*.py
   # Should return: (empty) - no top-level imports
   ```

3. Check blueprint registration doesn't trigger import:
   ```bash
   grep -A5 "from .railway_practitioner import" src/api/__init__.py
   # Should only import the blueprint, not selenium
   ```

**Fix**: All selenium imports must be inside functions with try/except

### Issue: Deployment Timeout

**Symptom**: Railway/Heroku deployment times out during startup

**Causes**:
- ❌ Database schema bootstrap taking too long
- ❌ Sync-on-startup blocking
- ✅ NOT selenium (it doesn't run at startup)

**Solutions**:
1. Disable SYNC_ON_STARTUP (already done in src/__init__.py)
2. Reduce schema bootstrap lock timeout (already set to 3s)
3. Use gunicorn with proper timeouts (see Procfile)

## Performance

### Import Costs (First Time Only)
- Standard imports: ~10ms
- Selenium import: ~1-3 seconds
- Total first booking: +2-4 seconds

### Subsequent Requests
- Import cached: ~0ms
- Selenium execution: 15-30 seconds (async, doesn't block)

## Dependencies

### Required Python Packages
```
selenium==4.15.2
webdriver-manager==4.0.1
```

### Runtime Requirements
- Chrome/Chromium browser (via Selenium Grid)
- ChromeDriver (managed by Selenium Grid)
- Network access to IntakeQ

### Optional for Development
```bash
# Local development without Selenium Grid
SELENIUM_GRID_URL=http://localhost:4444/wd/hub
```

## Testing Without Selenium

### Option 1: Disable via Environment Variable
```bash
export DISABLE_SELENIUM_BOT=true
gunicorn app:app
```

### Option 2: Mock in Tests
```python
import pytest
from unittest.mock import patch

@patch('src.api.railway_practitioner.assign_intakeq_practitioner')
def test_booking(mock_selenium):
    mock_selenium.return_value = (True, "https://intakeq.com/client/123")
    # Your test code
```

### Option 3: Remove from requirements.txt (Not Recommended)
This will cause import errors unless you also disable the bot.

## Deployment Checklist

- [ ] Selenium Grid service deployed and healthy
- [ ] `SELENIUM_GRID_URL` set correctly
- [ ] IntakeQ credentials configured
- [ ] Test booking end-to-end
- [ ] Check logs for selenium initialization
- [ ] Verify practitioner assignment works
- [ ] Monitor first-request latency

## Monitoring

### Key Log Messages

**Successful Flow:**
```
🤖 [ASYNC] Running Selenium practitioner assignment...
⏳ [ASYNC] Waiting 10 seconds for IntakeQ to process new client...
✅ [ASYNC] Delay complete, proceeding with Selenium assignment
🚀 Direct Railway assignment: 5781 → Catherine Burnett (insurance)
[SELENIUM] [HEALTH CHECK] Checking Selenium Grid at http://...
[SELENIUM] [HEALTH CHECK] [SUCCESS] Selenium Grid is available
[SELENIUM] [SUCCESS] Assigned Therapist-CB to Client-***5781 on attempt 1
🎉 [ASYNC] Successfully assigned Catherine Burnett to client 5781 via Selenium
```

**Graceful Degradation:**
```
⚠️ [ASYNC] Selenium bot disabled via DISABLE_SELENIUM_BOT env var
```

**Import Error (Non-Fatal):**
```
❌ Selenium bot not available: ModuleNotFoundError: No module named 'selenium'
⚠️ [ASYNC] Selenium practitioner assignment failed, but booking succeeded
```

### Database Status Field

Check `client_responses.practitioner_assignment_status`:
- `null` - Not yet attempted
- `async_pending` - Queued for async execution
- `completed` - Successfully assigned
- `failed` - Assignment failed
- `disabled` - Selenium disabled via env var

## Security

### PII Protection
All logs sanitize sensitive information:
- Client IDs: `Client-***5781` (last 4 digits only)
- Therapist names: `Therapist-CB` (initials only)
- Full details never logged

### Credentials
- Stored in environment variables only
- Never logged or exposed in errors
- Separate credentials for cash-pay vs insurance accounts

## Related Files

- `intakeq_selenium_bot.py` - Main bot implementation
- `src/api/railway_practitioner.py` - Railway endpoint
- `src/api/appointments.py` - Booking flow integration (line ~682)
- `src/services/async_tasks.py` - Async execution handler

## FAQ

**Q: Can I deploy without Selenium?**
A: Yes, set `DISABLE_SELENIUM_BOT=true`. Bookings work, practitioner assignment manual.

**Q: Why is it called "railway_practitioner"?**
A: Named for Railway deployment platform, distinguishes from Lambda version.

**Q: Does this slow down booking response time?**
A: No, selenium runs asynchronously after response is sent to user.

**Q: What if Selenium Grid crashes mid-booking?**
A: Booking succeeds, assignment fails gracefully, can retry manually.

**Q: How do I test locally without Selenium Grid?**
A: Set `DISABLE_SELENIUM_BOT=true` or run local Selenium Grid with Docker.
