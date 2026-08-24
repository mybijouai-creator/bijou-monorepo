# E2E Calendar Booking Test - Quick Start Guide

## Setup (5 minutes)

### 1. Install dependencies

```bash
pip install httpx python-dotenv supabase
```

### 2. Configure test environment

```bash
# Copy this to .env.test
TEST_TENANT_ID="your-tenant-uuid-here"
TEST_PHONE="+60123456789"  # Your WhatsApp number
BRIDGE_PASSWORD="your-bridge-password-here"  # copy from .env, never commit it
```

> ⚠️ This line previously contained the real production bridge password, and this
> repo is public. It has been removed from the working tree, but it remains in git
> history — rotating `BRIDGE_PASSWORD` is the only actual remedy.

### 3. Get your tenant ID

```bash
python scripts/check-tenants.py
# Copy your tenant UUID from output
```

## Running Tests

### Test 1: Basic Booking Flow (30 seconds)

```bash
python tests/e2e_calendar_booking.py booking
```

**What happens:**

1. Sends WhatsApp message: "I want to book a viewing tomorrow at 2pm"
2. Waits 10 seconds for AI to process
3. Checks database for new booking
4. Verifies Cal.com event created
5. Confirms reminders scheduled

**Expected output:**

```
✅ Message sent to +60123456789
✅ Booking created: abc-123-def-456
✅ Cal.com event ID: evt_xyz
✅ 2 reminder(s) scheduled
  Reminder: 24h before → pending
  Reminder: 1h before → pending
🎉 ALL TESTS PASSED!
```

### Test 2: Booking Conflict (1 minute)

```bash
python tests/e2e_calendar_booking.py conflict
```

**What happens:**

1. Books "tomorrow 2pm"
2. Tries to book same slot again
3. AI should respond with alternative times

**Manual verification:**

- Check your WhatsApp messages
- AI should say: "That slot is taken, how about 3pm or 4pm?"

### Test 3: Reminder Delivery (2 hours - OPTIONAL)

```bash
python tests/e2e_calendar_booking.py reminder
```

**Warning:** This test takes 2 hours (books slot 1.5h from now, waits for 1h reminder)

## Troubleshooting

### "No bookings found"

```bash
# Check production logs
fly logs --app bijou-production | grep -i "booking\|calendar"

# Common causes:
# - Calendar not configured for tenant
# - Cal.com API key invalid
# - AI didn't detect booking intent
```

### "Failed to send WhatsApp message"

```bash
# Verify bridge is running
curl https://bijou-bridge-production-v2.fly.dev/health

# Check bridge auth
echo -n "bijou-prod:YOUR_PASSWORD" | base64
# Should match Authorization header
```

### "No Cal.com event ID"

```bash
# Check if CAL_API_KEY is set
fly secrets list --app bijou-production | grep CAL

# Test Cal.com API directly
curl -H "Authorization: Bearer YOUR_CAL_API_KEY" \
  https://api.cal.com/v1/bookings
```

## Safe Testing Strategy

### Option 1: Test Tenant (RECOMMENDED)

```bash
# Create dedicated test tenant
curl -X POST https://app.mybijou.xyz/api/onboarding/signup \
  -H "Content-Type: application/json" \
  -d '{
    "business_name": "TEST - Calendar E2E",
    "email": "test+cal@yourdomain.com",
    "phone": "+60199999999"
  }'

# Use returned tenant_id for TEST_TENANT_ID
```

### Option 2: Staging Environment

```bash
# Deploy to staging
fly deploy --app bijou-staging --config fly.staging.toml

# Point tests to staging
export BIJOU_URL="https://bijou-staging.fly.dev"
python tests/e2e_calendar_booking.py booking
```

### Option 3: Test Mode Flag

```bash
# Add to .env.production
ENABLE_E2E_TEST_MODE=true

# In bijou.py, mock Cal.com calls when test mode enabled
# (prevents actual bookings from being created)
```

## Success Criteria

✅ **Test passes if:**

- WhatsApp message sends successfully
- Booking appears in `call_bookings` table
- Cal.com event ID is populated
- 2 reminders (24h + 1h) are scheduled

❌ **Test fails if:**

- No booking created after 10 seconds
- Cal.com event ID is null (integration broken)
- Reminders not scheduled (proactive system disabled)

## Next Steps

After tests pass:

1. Send real booking to yourself
2. Verify WhatsApp confirmation message
3. Check Cal.com dashboard for event
4. Wait for reminders (optional)
5. Mark booking as completed in dashboard

## Integration with CI/CD

```yaml
# .github/workflows/e2e-tests.yml
name: E2E Calendar Tests

on:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
      - run: pip install -r requirements.txt
      - run: |
          export TEST_TENANT_ID=${{ secrets.TEST_TENANT_ID }}
          export TEST_PHONE=${{ secrets.TEST_PHONE }}
          python tests/e2e_calendar_booking.py booking
```

## Monitoring Dashboard

```bash
# Real-time monitoring while tests run
fly logs --app bijou-production | grep -E "booking|calendar|reminder" --color=always
```

## Cost Estimation

Each test run:

- 1 WhatsApp message = RM 0.0X (bridge cost)
- 1 Cal.com API call = Free (within quota)
- 2 reminder DB writes = Free
- **Total cost per test:** < RM 0.10

Monthly (if run 100x):

- **Total:** RM 10 (acceptable)
