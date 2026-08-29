# Backend 500 Error Verification Script
# Run this to test all endpoints that were showing 500 errors
# Author: Bijou AI QA Team

$BASE_URL = "https://bijou-staging.fly.dev"
$DASHBOARD_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imxyd3psdWpvbXVremp5a2FmbWljIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjkwNzA2ODMsImV4cCI6MjA4NDY0NjY4M30.ZJSvmh0Oa_51rfr0TrTSjS4OdszrUCe5Fmsnfk9X-6U"

Write-Host "======================================" -ForegroundColor Cyan
Write-Host "Bijou AI Backend Fix Verification" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""

# Test 1: Google OAuth endpoints
Write-Host "Test 1: Google OAuth Auth URL" -ForegroundColor Yellow
$response = curl -s -w "\n%{http_code}" "$BASE_URL/api/dashboard/google/auth-url" `
    -H "Authorization: Bearer $DASHBOARD_TOKEN"
$status = $response[-1]
Write-Host "Status: $status" -ForegroundColor $(if ($status -eq "200") {"Green"} elseif ($status -eq "503") {"Yellow"} else {"Red"})
if ($status -eq "503") {
    Write-Host "✅ EXPECTED: 503 Service Unavailable (Google OAuth not configured)" -ForegroundColor Green
} elseif ($status -eq "200") {
    Write-Host "✅ SUCCESS: Google OAuth is configured!" -ForegroundColor Green
} else {
    Write-Host "❌ UNEXPECTED: Should be 200 or 503, got $status" -ForegroundColor Red
}
Write-Host ""

# Test 2: Takeover endpoint
Write-Host "Test 2: Conversation Takeover" -ForegroundColor Yellow
$response = curl -s -w "\n%{http_code}" "$BASE_URL/api/dashboard/takeover" `
    -X POST `
    -H "Authorization: Bearer $DASHBOARD_TOKEN" `
    -H "Content-Type: application/json" `
    -d '{"customer_jid":"60123456789@s.whatsapp.net","agent_name":"Test Agent","reason":"Testing"}'
$status = $response[-1]
Write-Host "Status: $status" -ForegroundColor $(if ($status -in @("200","403","404")) {"Green"} else {"Red"})
if ($status -eq "403" -or $status -eq "404") {
    Write-Host "✅ EXPECTED: 403/404 (Customer not found - valid error handling)" -ForegroundColor Green
} elseif ($status -eq "200") {
    Write-Host "✅ SUCCESS: Takeover worked!" -ForegroundColor Green
} elseif ($status -eq "400") {
    Write-Host "⚠️ VALIDATION ERROR: Check request payload" -ForegroundColor Yellow
} else {
    Write-Host "❌ UNEXPECTED: Got $status (should not be 500!)" -ForegroundColor Red
}
Write-Host ""

# Test 3: Return to AI endpoint
Write-Host "Test 3: Return to AI" -ForegroundColor Yellow
$response = curl -s -w "\n%{http_code}" "$BASE_URL/api/dashboard/return-to-ai/60123456789@s.whatsapp.net?agent_name=Test%20Agent" `
    -X POST `
    -H "Authorization: Bearer $DASHBOARD_TOKEN"
$status = $response[-1]
Write-Host "Status: $status" -ForegroundColor $(if ($status -in @("200","403","404")) {"Green"} else {"Red"})
if ($status -eq "403" -or $status -eq "404") {
    Write-Host "✅ EXPECTED: 403/404 (Customer not found - valid error handling)" -ForegroundColor Green
} elseif ($status -eq "200") {
    Write-Host "✅ SUCCESS: Return to AI worked!" -ForegroundColor Green
} else {
    Write-Host "❌ UNEXPECTED: Got $status (should not be 500!)" -ForegroundColor Red
}
Write-Host ""

# Test 4: Send message endpoint
Write-Host "Test 4: Send Message" -ForegroundColor Yellow
$response = curl -s -w "\n%{http_code}" "$BASE_URL/api/dashboard/send-message" `
    -X POST `
    -H "Authorization: Bearer $DASHBOARD_TOKEN" `
    -H "Content-Type: application/json" `
    -d '{"customer_jid":"60123456789@s.whatsapp.net","message":"Test message","agent_name":"Test Agent"}'
$status = $response[-1]
Write-Host "Status: $status" -ForegroundColor $(if ($status -in @("200","503")) {"Green"} else {"Red"})
if ($status -eq "503") {
    Write-Host "✅ EXPECTED: 503 (WhatsApp bridge not configured)" -ForegroundColor Green
} elseif ($status -eq "200") {
    Write-Host "✅ SUCCESS: Message sent!" -ForegroundColor Green
} else {
    Write-Host "❌ UNEXPECTED: Got $status (should not be 500!)" -ForegroundColor Red
}
Write-Host ""

# Test 5: Create agent endpoint
Write-Host "Test 5: Create Agent" -ForegroundColor Yellow
$response = curl -s -w "\n%{http_code}" "$BASE_URL/api/dashboard/agents" `
    -X POST `
    -H "Authorization: Bearer $DASHBOARD_TOKEN" `
    -H "Content-Type: application/json" `
    -d '{"agent_name":"QA Test Agent","email":"qa@bijou.ai","role":"support"}'
$status = $response[-1]
Write-Host "Status: $status" -ForegroundColor $(if ($status -in @("200","201")) {"Green"} else {"Red"})
if ($status -eq "200" -or $status -eq "201") {
    Write-Host "✅ SUCCESS: Agent created!" -ForegroundColor Green
} elseif ($status -eq "400") {
    Write-Host "⚠️ VALIDATION ERROR: Check request payload" -ForegroundColor Yellow
} else {
    Write-Host "❌ UNEXPECTED: Got $status (should not be 500!)" -ForegroundColor Red
}
Write-Host ""

# Test 6: External webhook
Write-Host "Test 6: External Webhook" -ForegroundColor Yellow
$response = curl -s -w "\n%{http_code}" "$BASE_URL/api/webhook" `
    -X POST `
    -H "Content-Type: application/json" `
    -d '{"source":"test","name":"John Doe","email":"test@example.com"}'
$status = $response[-1]
Write-Host "Status: $status" -ForegroundColor $(if ($status -eq "200") {"Green"} else {"Red"})
if ($status -eq "200") {
    Write-Host "✅ SUCCESS: Webhook received!" -ForegroundColor Green
} else {
    Write-Host "❌ UNEXPECTED: Got $status (should not be 500!)" -ForegroundColor Red
}
Write-Host ""

# Test 7: Message webhook (GOWA format)
Write-Host "Test 7: Message Webhook (GOWA)" -ForegroundColor Yellow
$response = curl -s -w "\n%{http_code}" "$BASE_URL/webhook/message" `
    -X POST `
    -H "Content-Type: application/json" `
    -d '{"event":"message","device_id":"test-device","payload":{"id":"msg123","chat_id":"60123456789@s.whatsapp.net","from":"60123456789@s.whatsapp.net","from_name":"Test User","body":"Test message","timestamp":1234567890,"is_from_me":false}}'
$status = $response[-1]
Write-Host "Status: $status" -ForegroundColor $(if ($status -in @("200","503")) {"Green"} else {"Red"})
if ($status -eq "503") {
    Write-Host "✅ EXPECTED: 503 (Bijou instance not ready)" -ForegroundColor Green
} elseif ($status -eq "200") {
    Write-Host "✅ SUCCESS: Message webhook processed!" -ForegroundColor Green
} else {
    Write-Host "❌ UNEXPECTED: Got $status (should not be 500!)" -ForegroundColor Red
}
Write-Host ""

# Test 8: Connection webhook
Write-Host "Test 8: Connection Webhook" -ForegroundColor Yellow
$response = curl -s -w "\n%{http_code}" "$BASE_URL/webhook/connection" `
    -X POST `
    -H "Content-Type: application/json" `
    -d '{"tenant_id":"00000000-0000-0000-0000-000000000000","whatsapp_jid":"60123456789@s.whatsapp.net","status":"connected","timestamp":"2026-02-17T10:00:00Z"}'
$status = $response[-1]
Write-Host "Status: $status" -ForegroundColor $(if ($status -in @("200","503")) {"Green"} else {"Red"})
if ($status -eq "503") {
    Write-Host "✅ EXPECTED: 503 (Database not available)" -ForegroundColor Green
} elseif ($status -eq "200") {
    Write-Host "✅ SUCCESS: Connection webhook processed!" -ForegroundColor Green
} else {
    Write-Host "❌ UNEXPECTED: Got $status (should not be 500!)" -ForegroundColor Red
}
Write-Host ""

Write-Host "======================================" -ForegroundColor Cyan
Write-Host "Verification Complete!" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Summary:" -ForegroundColor Yellow
Write-Host "- All endpoints should return 200, 400, 403, 404, or 503" -ForegroundColor White
Write-Host "- NO endpoint should return 500 (Internal Server Error)" -ForegroundColor White
Write-Host "- 503 errors are EXPECTED for unconfigured services" -ForegroundColor White
Write-Host ""
