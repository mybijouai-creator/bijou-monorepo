# GOWA Bridge Expert Guide - Complete Implementation Reference

**Version:** 8.2.0  
**Target:** Multi-Device WhatsApp Business API  
**Date:** February 2026  
**Architect:** Analysis of go-whatsapp-web-multidevice official repository

---

## 🔑 Executive Summary

**CRITICAL FINDING:** Bijou's current implementation calls `/app/login` directly without device creation, which is **INCORRECT** for GOWA Bridge v8+.

**Correct Flow:**

```
1. POST /devices              → Create device slot
2. Receive device_id          → Store in database (tenant_id → device_id)
3. GET /devices/{id}/login    → Get QR code
4. User scans QR              → Device becomes logged_in
5. All API calls              → Include X-Device-Id header
```

**Key Architectural Concepts:**

- **Device ID**: User-assigned identifier (e.g., `"bijou-tenant-123"`) or auto-generated UUID
- **JID**: WhatsApp's internal identifier (e.g., `"6289605618749@s.whatsapp.net"`)
- **Device Instance**: In-memory object managing WhatsApp client lifecycle
- **Device Manager**: Registry of all active device instances

---

## 📐 Architecture Deep Dive

### 1. Multi-Device Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        GOWA Bridge Server                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  DeviceManager (Registry)                                        │
│  ├── Device Instance 1 (tenant-A)                                │
│  │   ├── WhatsApp Client                                         │
│  │   ├── Chat Storage Repository                                 │
│  │   └── Device State (disconnected/connected/logged_in)         │
│  │                                                                │
│  ├── Device Instance 2 (tenant-B)                                │
│  │   ├── WhatsApp Client                                         │
│  │   ├── Chat Storage Repository                                 │
│  │   └── Device State                                            │
│  │                                                                │
│  └── Device Instance N...                                        │
│                                                                   │
├─────────────────────────────────────────────────────────────────┤
│  REST API Layer                                                  │
│  ├── Device Middleware (resolves X-Device-Id)                    │
│  ├── Basic Auth (username:password)                              │
│  └── Endpoints (/devices, /send, /user, etc.)                    │
└─────────────────────────────────────────────────────────────────┘
```

### 2. Device Lifecycle States

```go
// From src/domains/device/device.go
type DeviceState string

const (
    DeviceStateDisconnected DeviceState = "disconnected"  // Device created but not connected
    DeviceStateConnecting   DeviceState = "connecting"    // Attempting connection
    DeviceStateConnected    DeviceState = "connected"     // Connected to WhatsApp servers
    DeviceStateLoggedIn     DeviceState = "logged_in"     // Fully authenticated and ready
)
```

**State Transitions:**

```
disconnected → (Connect) → connecting → (Auth Success) → connected → (Login Success) → logged_in
                                            ↓                            ↓
                                         (Fail)                       (Fail)
                                            ↓                            ↓
                                       disconnected                 disconnected
```

### 3. Device ID vs JID - **CRITICAL DISTINCTION**

| Concept               | Description                                                                          | Example                                                             | Usage                                            |
| --------------------- | ------------------------------------------------------------------------------------ | ------------------------------------------------------------------- | ------------------------------------------------ |
| **Device ID**         | User-assigned alias or auto-generated UUID. Stored in `DeviceManager.devices` map.   | `"bijou-tenant-abc123"` or `"550e8400-e29b-41d4-a716-446655440000"` | API routing, tenant isolation, database keys     |
| **JID (WhatsApp ID)** | WhatsApp's internal identifier. Extracted from `client.Store.ID.ToNonAD().String()`. | `"6289605618749@s.whatsapp.net"`                                    | Message routing, WhatsApp protocol, chat storage |

**Key Implementation:**

```go
// From src/infrastructure/whatsapp/device_instance.go
type DeviceInstance struct {
    id              string              // Device ID (user-assigned or UUID)
    jid             string              // WhatsApp JID (assigned after login)
    client          *whatsmeow.Client
    chatStorageRepo domainChatStorage.IChatStorageRepository
    state           domainDevice.DeviceState
    displayName     string
    phoneNumber     string
    createdAt       time.Time
}

func (d *DeviceInstance) ID() string {
    return d.id  // Returns device_id
}

func (d *DeviceInstance) JID() string {
    d.mu.RLock()
    defer d.mu.RUnlock()
    return d.jid  // Returns WhatsApp JID (empty before login)
}
```

**Important:**

- Device ID is assigned when calling `POST /devices`
- JID is assigned **AFTER** successful WhatsApp login
- Database queries for `chats` and `messages` use **JID**, not device_id
- API routing uses **device_id**

---

## 🚀 Device Creation & Login Flow - COMPLETE IMPLEMENTATION

### Step 1: Create Device Placeholder

**Endpoint:** `POST /devices`

**Request:**

```bash
curl -X POST "https://bridge.example.com/devices" \
  -H "Authorization: Basic $(echo -n 'username:password' | base64)" \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "bijou-tenant-abc123"   # Optional - auto-generated if omitted
  }'
```

**Response:**

```json
{
  "status": 200,
  "code": "SUCCESS",
  "message": "Device added",
  "results": {
    "id": "bijou-tenant-abc123", // This is your device_id
    "display_name": "",
    "jid": "", // Empty until login
    "state": "disconnected",
    "created_at": "2026-02-17T10:30:00Z"
  }
}
```

**Backend Code (Go):**

```go
// From src/infrastructure/whatsapp/device_manager.go
func (m *DeviceManager) CreateDevice(ctx context.Context, requestedID string) (*DeviceInstance, error) {
    id := requestedID
    if id == "" {
        id = fiberUtils.UUID()  // Auto-generate if not provided
    }

    m.mu.Lock()
    defer m.mu.Unlock()

    if _, exists := m.devices[id]; exists {
        return nil, fmt.Errorf("device %s already exists", id)
    }

    instance := NewDeviceInstance(id, nil, newDeviceChatStorage(id, m.storage))
    m.devices[id] = instance

    // Persist in registry
    if m.storage != nil {
        _ = m.storage.SaveDeviceRecord(&domainChatStorage.DeviceRecord{
            DeviceID:    id,
            DisplayName: instance.DisplayName(),
            JID:         instance.JID(),
            CreatedAt:   instance.CreatedAt(),
            UpdatedAt:   instance.CreatedAt(),
        })
    }

    logrus.Infof("[DEVICE_MANAGER] created device placeholder %s", id)
    return instance, nil
}
```

### Step 2: Initiate Login (QR Code Method)

**Endpoint:** `GET /devices/{device_id}/login`

**Request:**

```bash
curl -X GET "https://bridge.example.com/devices/bijou-tenant-abc123/login" \
  -H "Authorization: Basic $(echo -n 'username:password' | base64)"
```

**Response:**

```json
{
  "status": 200,
  "code": "SUCCESS",
  "message": "Login started",
  "results": {
    "device_id": "bijou-tenant-abc123",
    "qr_link": "https://bridge.example.com/statics/qrcode/scan-qr-xyz.png",
    "qr_duration": 30, // Seconds until QR expires
    "code": "1@abc123xyz..." // Raw QR code data (optional)
  }
}
```

**Alternative: Pairing Code Method**

**Endpoint:** `POST /devices/{device_id}/login/code?phone=628123456789`

**Response:**

```json
{
  "status": 200,
  "code": "SUCCESS",
  "message": "Login with code started",
  "results": {
    "device_id": "bijou-tenant-abc123",
    "pair_code": "AB12-CD34" // 8-character code for manual pairing
  }
}
```

### Step 3: Check Device Status

**Endpoint:** `GET /devices/{device_id}/status`

**Response (Before Login):**

```json
{
  "status": 200,
  "code": "SUCCESS",
  "message": "Device status",
  "results": {
    "device_id": "bijou-tenant-abc123",
    "is_connected": false,
    "is_logged_in": false
  }
}
```

**Response (After Login):**

```json
{
  "status": 200,
  "code": "SUCCESS",
  "message": "Device status",
  "results": {
    "device_id": "bijou-tenant-abc123",
    "is_connected": true,
    "is_logged_in": true
  }
}
```

### Step 4: Get Device Details (After Login)

**Endpoint:** `GET /devices/{device_id}`

**Response:**

```json
{
  "status": 200,
  "code": "SUCCESS",
  "message": "Device info",
  "results": {
    "id": "bijou-tenant-abc123",
    "phone_number": "628123456789",
    "display_name": "Business Name",
    "state": "logged_in",
    "jid": "628123456789@s.whatsapp.net", // JID populated after login
    "created_at": "2026-02-17T10:30:00Z"
  }
}
```

---

## 🔐 API Patterns & Authentication

### 1. Basic Authentication

**Format:** `Authorization: Basic <base64(username:password)>`

**Example:**

> ⚠️ An earlier revision of this file hardcoded the real production password
> here, and this repo is public. Treat that credential as compromised: rotate
> `BRIDGE_PASSWORD`, and remember that removing it from the working tree does
> **not** remove it from git history.

```python
import base64
import os

# Never hardcode these — they come from BRIDGE_USER / BRIDGE_PASSWORD in .env,
# which is gitignored.
username = os.environ["BRIDGE_USER"]
password = os.environ["BRIDGE_PASSWORD"]
credentials = f"{username}:{password}"
auth_token = base64.b64encode(credentials.encode()).decode()

headers = {
    "Authorization": f"Basic {auth_token}",
    "Content-Type": "application/json"
}
```

### 2. Device Scoping - **X-Device-Id Header**

**All device-scoped endpoints require:**

```bash
curl -X POST "https://bridge.example.com/send/text" \
  -H "Authorization: Basic ..." \
  -H "X-Device-Id: bijou-tenant-abc123" \    # REQUIRED for multi-device
  -H "Content-Type: application/json" \
  -d '{
    "phone": "628987654321",
    "message": "Hello from Bijou!"
  }'
```

**Middleware Logic:**

```go
// From src/ui/rest/middleware/device.go
const DeviceIDHeader = "X-Device-Id"

func DeviceMiddleware(dm *DeviceManager) fiber.Handler {
    return func(c *fiber.Ctx) error {
        // 1. Check X-Device-Id header (preferred)
        deviceID := strings.TrimSpace(c.Get(DeviceIDHeader))

        // 2. Fall back to query param
        if deviceID == "" {
            deviceID = strings.TrimSpace(c.Query("device_id"))
        }

        // 3. Resolve device (or use default if only one device exists)
        instance, resolvedID, err := dm.ResolveDevice(deviceID)
        if err != nil {
            if resolvedID != "" {
                // Device ID provided but not found
                return c.Status(404).JSON(...)
            }
            // No device ID provided and multiple devices exist
            return c.Status(400).JSON(...)
        }

        // 4. Inject into context
        c.Locals("device_id", resolvedID)
        c.Locals("device", instance)
        return c.Next()
    }
}
```

**Device Resolution Logic:**

```go
// From src/infrastructure/whatsapp/device_manager.go
func (m *DeviceManager) ResolveDevice(deviceID string) (*DeviceInstance, string, error) {
    trimmedID := strings.TrimSpace(deviceID)

    // If device_id provided, find exact match
    if trimmedID != "" {
        if inst, ok := m.GetDevice(trimmedID); ok && inst != nil {
            return inst, trimmedID, nil
        }
        return nil, trimmedID, fmt.Errorf("device %s not found", trimmedID)
    }

    // Fall back to default (only if exactly ONE device exists)
    if inst := m.DefaultDevice(); inst != nil {
        return inst, inst.ID(), nil
    }

    return nil, "", fmt.Errorf("device id is required")
}
```

### 3. WebSocket Connection (Device-Scoped)

**Connection URL:**

```javascript
const deviceId = "bijou-tenant-abc123";
const ws = new WebSocket(`wss://bridge.example.com/ws?device_id=${deviceId}`);

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log("Event:", data.event);
  console.log("Device:", data.device_id);
  console.log("Payload:", data.payload);
};
```

**Webhook Payload Structure:**

```json
{
  "event": "message",
  "device_id": "bijou-tenant-abc123", // Device that received the event
  "payload": {
    "id": "3EB0C127D7BACC83D6A1",
    "chat_id": "628987654321@s.whatsapp.net",
    "from": "628987654321@s.whatsapp.net",
    "from_name": "Customer Name",
    "timestamp": "2026-02-17T10:30:00Z",
    "is_from_me": false,
    "body": "Hello, I need help!"
  }
}
```

---

## 🛠️ Critical Endpoints Reference

### Device Management

| Endpoint                   | Method | Purpose               | Requires X-Device-Id |
| -------------------------- | ------ | --------------------- | -------------------- |
| `/devices`                 | GET    | List all devices      | No                   |
| `/devices`                 | POST   | Create new device     | No                   |
| `/devices/{id}`            | GET    | Get device info       | No (scoped by path)  |
| `/devices/{id}`            | DELETE | Remove device         | No (scoped by path)  |
| `/devices/{id}/login`      | GET    | Get QR code           | No (scoped by path)  |
| `/devices/{id}/login/code` | POST   | Get pairing code      | No (scoped by path)  |
| `/devices/{id}/logout`     | POST   | Logout device         | No (scoped by path)  |
| `/devices/{id}/reconnect`  | POST   | Reconnect device      | No (scoped by path)  |
| `/devices/{id}/status`     | GET    | Get connection status | No (scoped by path)  |

### Legacy Endpoints (Still Supported)

| Endpoint               | Method | Purpose              | Requires X-Device-Id |
| ---------------------- | ------ | -------------------- | -------------------- |
| `/app/login`           | GET    | Login (QR)           | **YES**              |
| `/app/login-with-code` | GET    | Login (pairing code) | **YES**              |
| `/app/logout`          | GET    | Logout               | **YES**              |
| `/app/reconnect`       | GET    | Reconnect            | **YES**              |
| `/app/devices`         | GET    | List devices         | No                   |
| `/app/status`          | GET    | Connection status    | **YES**              |

### Messaging Endpoints

| Endpoint         | Method | Purpose            | Requires X-Device-Id |
| ---------------- | ------ | ------------------ | -------------------- |
| `/send/text`     | POST   | Send text message  | **YES**              |
| `/send/image`    | POST   | Send image         | **YES**              |
| `/send/file`     | POST   | Send file/document | **YES**              |
| `/send/video`    | POST   | Send video         | **YES**              |
| `/send/audio`    | POST   | Send audio         | **YES**              |
| `/send/contact`  | POST   | Send contact card  | **YES**              |
| `/send/location` | POST   | Send location      | **YES**              |
| `/send/link`     | POST   | Send link preview  | **YES**              |

### User Information

| Endpoint           | Method | Purpose              | Requires X-Device-Id |
| ------------------ | ------ | -------------------- | -------------------- |
| `/user/info`       | GET    | Get user info        | **YES**              |
| `/user/avatar`     | GET    | Get user avatar      | **YES**              |
| `/user/my/privacy` | GET    | Get privacy settings | **YES**              |
| `/user/my/groups`  | GET    | List my groups       | **YES**              |

---

## ⚠️ Common Pitfalls & Solutions

### Pitfall 1: Calling `/app/login` Without Device Creation

**WRONG:**

```python
# ❌ This will fail or create unexpected behavior in v8+
response = requests.get(
    "https://bridge.example.com/app/login",
    headers={"Authorization": "Basic ..."}
)
```

**Problem:** No device context exists. Bridge doesn't know which tenant this login belongs to.

**CORRECT:**

```python
# ✅ Step 1: Create device first
device_response = requests.post(
    "https://bridge.example.com/devices",
    headers={"Authorization": "Basic ..."},
    json={"device_id": "bijou-tenant-abc123"}
)

device_id = device_response.json()["results"]["id"]

# ✅ Step 2: Login with device_id
qr_response = requests.get(
    f"https://bridge.example.com/devices/{device_id}/login",
    headers={"Authorization": "Basic ..."}
)
```

### Pitfall 2: Missing X-Device-Id Header

**WRONG:**

```python
# ❌ Missing X-Device-Id header with multiple devices
response = requests.post(
    "https://bridge.example.com/send/text",
    headers={"Authorization": "Basic ..."},
    json={"phone": "628987654321", "message": "Hello"}
)
# Returns: 400 "device_id is required"
```

**CORRECT:**

```python
# ✅ Include X-Device-Id header
response = requests.post(
    "https://bridge.example.com/send/text",
    headers={
        "Authorization": "Basic ...",
        "X-Device-Id": "bijou-tenant-abc123"
    },
    json={"phone": "628987654321", "message": "Hello"}
)
```

### Pitfall 3: Confusing Device ID with JID

**WRONG:**

```python
# ❌ Using JID as device_id in API calls
device_jid = "628123456789@s.whatsapp.net"
requests.post(
    "https://bridge.example.com/send/text",
    headers={"X-Device-Id": device_jid},  # This might work but is not recommended
    ...
)
```

**CORRECT:**

```python
# ✅ Use device_id (tenant identifier)
device_id = "bijou-tenant-abc123"
requests.post(
    "https://bridge.example.com/send/text",
    headers={"X-Device-Id": device_id},
    ...
)
```

### Pitfall 4: Not Checking Device State Before Sending

**WRONG:**

```python
# ❌ Sending without verifying login status
send_message(device_id, phone, message)  # May fail if not logged in
```

**CORRECT:**

```python
# ✅ Check status first
status = requests.get(
    f"https://bridge.example.com/devices/{device_id}/status",
    headers={"Authorization": "Basic ..."}
).json()

if not status["results"]["is_logged_in"]:
    raise Exception("Device not logged in. Please complete WhatsApp login first.")

# Now safe to send
send_message(device_id, phone, message)
```

### Pitfall 5: Single API Call Expecting Full Setup

**WRONG:**

```python
# ❌ Expecting single call to create + login device
response = magic_setup_device()  # No such endpoint exists
```

**CORRECT:**

```python
# ✅ Multi-step process
# 1. Create device
device = create_device("bijou-tenant-abc123")

# 2. Initiate login
qr_data = get_qr_code(device["id"])

# 3. Present QR to user
display_qr_code(qr_data["qr_link"])

# 4. Poll for status (or use WebSocket)
while not is_logged_in(device["id"]):
    time.sleep(2)

# 5. Device ready
send_message(device["id"], phone, message)
```

---

## 🔧 Bijou Integration Fix - Exact Code Changes

### Current Implementation (INCORRECT)

**File:** `packages/backend/src/saas/onboarding_complete.py`

```python
async def provision_whatsapp_device(tenant_id: str, business_name: str):
    """Background task: Create WhatsApp device on bridge"""
    try:
        bridge_url = os.getenv("BRIDGE_URL", "https://bijou-bridge-production.fly.dev")
        # No default. A hardcoded fallback silently authenticates with a baked-in
        # credential whenever the env var is missing — fail loudly instead.
        bridge_user = os.environ["BRIDGE_USER"]
        bridge_pass = os.environ["BRIDGE_PASSWORD"]

        bridge_client = WhatsAppBridgeClient(
            base_url=bridge_url,
            api_key=f"{bridge_user}:{bridge_pass}"
        )

        # ❌ WRONG: This calls /app/login without creating device
        device_response = bridge_client.create_device(device_name=business_name)

        if device_response.get("code") == "SUCCESS":
            device_id = device_response["results"]["id"]
            # ...
```

### Fixed Implementation (CORRECT)

**File:** `packages/backend/src/saas/onboarding_complete.py`

```python
async def provision_whatsapp_device(tenant_id: str, business_name: str):
    """
    Background task: Create WhatsApp device on GOWA bridge (v8+)

    FLOW:
    1. POST /devices → Create device placeholder
    2. Store device_id in database
    3. Device ready for login (user will scan QR later)
    """
    try:
        bridge_url = os.getenv("BRIDGE_URL", "https://bijou-bridge-production.fly.dev")
        # No default. A hardcoded fallback silently authenticates with a baked-in
        # credential whenever the env var is missing — fail loudly instead.
        bridge_user = os.environ["BRIDGE_USER"]
        bridge_pass = os.environ["BRIDGE_PASSWORD"]

        # Use tenant_id as device_id for 1:1 mapping
        device_id = f"bijou-{tenant_id}"

        # ✅ CORRECT: Call POST /devices to create device placeholder
        headers = {
            "Authorization": f"Basic {base64.b64encode(f'{bridge_user}:{bridge_pass}'.encode()).decode()}",
            "Content-Type": "application/json"
        }

        response = httpx.post(
            f"{bridge_url}/devices",
            headers=headers,
            json={"device_id": device_id},  # Optional - can omit for auto-generation
            timeout=30.0
        )
        response.raise_for_status()
        device_data = response.json()

        if device_data.get("code") == "SUCCESS":
            created_device_id = device_data["results"]["id"]

            # Store device mapping in Supabase
            supabase = get_supabase()
            supabase.table("whatsapp_devices").insert({
                "tenant_id": tenant_id,
                "device_id": created_device_id,
                "device_name": business_name,
                "device_state": "disconnected",  # Initial state
                "created_at": datetime.now(timezone.utc).isoformat()
            }).execute()

            logger.info(f"✅ WhatsApp device created for tenant {tenant_id}: {created_device_id}")
            logger.info(f"📱 Device state: disconnected (awaiting QR scan)")

        else:
            logger.error(f"❌ Bridge API error: {device_data.get('message')}")

    except Exception as e:
        logger.error(f"❌ Failed to provision device for {tenant_id}: {e}")
```

### Updated WhatsAppBridgeClient

**File:** `packages/backend/src/core/whatsapp_bridge_client.py`

```python
def create_device(self, device_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Create a new device placeholder for multi-tenant support (GOWA v8+)

    Args:
        device_id: Optional custom device ID (e.g., "bijou-tenant-abc123")
                   If omitted, bridge will auto-generate UUID

    Returns:
        dict: Response with device_id and metadata
            {
                "status": 200,
                "code": "SUCCESS",
                "message": "Device added",
                "results": {
                    "id": "bijou-tenant-abc123",
                    "state": "disconnected",
                    "jid": "",
                    "display_name": "",
                    "created_at": "2026-02-17T10:30:00Z"
                }
            }
    """
    try:
        url = f"{self.base_url}/devices"
        payload = {}
        if device_id:
            payload["device_id"] = device_id

        response = self.client.post(
            url,
            headers=self.headers,
            json=payload
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"Failed to create device: HTTP {e.response.status_code} - {e.response.text}")
        return {"status": e.response.status_code, "code": "ERROR", "message": str(e)}
    except Exception as e:
        logger.error(f"Failed to create device: {e}")
        return {"status": 500, "code": "ERROR", "message": str(e)}


def get_device_login_qr(self, device_id: str) -> Dict[str, Any]:
    """
    Initiate QR code login for a specific device (GOWA v8+)

    Args:
        device_id: Device ID to login

    Returns:
        dict: Response with QR code data
            {
                "status": 200,
                "code": "SUCCESS",
                "message": "Login started",
                "results": {
                    "device_id": "bijou-tenant-abc123",
                    "qr_link": "https://bridge.example.com/statics/qrcode/scan-qr-xyz.png",
                    "qr_duration": 30,
                    "code": "1@abc123..."
                }
            }
    """
    try:
        url = f"{self.base_url}/devices/{device_id}/login"
        response = self.client.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Failed to get QR code for device {device_id}: {e}")
        return {"code": "ERROR", "message": str(e)}


def get_device_status(self, device_id: str) -> Dict[str, Any]:
    """
    Get connection status for a specific device (GOWA v8+)

    Args:
        device_id: Device ID to check

    Returns:
        dict: Response with connection status
            {
                "status": 200,
                "code": "SUCCESS",
                "message": "Device status",
                "results": {
                    "device_id": "bijou-tenant-abc123",
                    "is_connected": true,
                    "is_logged_in": true
                }
            }
    """
    try:
        url = f"{self.base_url}/devices/{device_id}/status"
        response = self.client.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Failed to get status for device {device_id}: {e}")
        return {"code": "ERROR", "message": str(e)}
```

### Database Schema Update

**File:** `packages/backend/migrations-py/add_device_session_schema.sql` (the pre-monorepo `database/013_device_state_tracking.sql` no longer exists — verify this is the migration you mean before relying on it)

```sql
-- Add device_state column to track lifecycle
ALTER TABLE whatsapp_devices
ADD COLUMN IF NOT EXISTS device_state TEXT DEFAULT 'disconnected'
    CHECK (device_state IN ('disconnected', 'connecting', 'connected', 'logged_in'));

-- Add jid column to store WhatsApp JID after login
ALTER TABLE whatsapp_devices
ADD COLUMN IF NOT EXISTS jid TEXT;

-- Add last_seen timestamp
ALTER TABLE whatsapp_devices
ADD COLUMN IF NOT EXISTS last_seen TIMESTAMPTZ;

-- Create index for state queries
CREATE INDEX IF NOT EXISTS idx_device_state ON whatsapp_devices(device_state);

-- Create unique constraint on device_id
ALTER TABLE whatsapp_devices
ADD CONSTRAINT unique_device_id UNIQUE (device_id);

COMMENT ON COLUMN whatsapp_devices.device_state IS 'Device lifecycle: disconnected → connecting → connected → logged_in';
COMMENT ON COLUMN whatsapp_devices.jid IS 'WhatsApp JID (e.g., 628123456789@s.whatsapp.net) - populated after login';
COMMENT ON COLUMN whatsapp_devices.device_id IS 'GOWA bridge device_id (e.g., bijou-tenant-abc123)';
```

---

## 📋 Integration Checklist for Bijou

### Phase 1: Device Provisioning (Onboarding)

- [ ] Update `provision_whatsapp_device()` to call `POST /devices`
- [ ] Store `device_id` in `whatsapp_devices` table
- [ ] Store initial `device_state = 'disconnected'`
- [ ] Update `WhatsAppBridgeClient.create_device()` to match new API
- [ ] Add `get_device_login_qr()` method to client
- [ ] Add `get_device_status()` method to client

### Phase 2: QR Code Display (Dashboard)

- [ ] Create endpoint `GET /api/onboarding/qr/{tenant_id}`
- [ ] Call `GET /devices/{device_id}/login` from bridge
- [ ] Display QR code image to user
- [ ] Add countdown timer for QR expiration (30s default)
- [ ] Implement QR refresh button

### Phase 3: Device Status Polling

- [ ] Create polling endpoint `GET /api/devices/status/{tenant_id}`
- [ ] Poll every 2 seconds during onboarding
- [ ] Update database when `is_logged_in` becomes `true`
- [ ] Store `jid` from device info after login
- [ ] Transition device_state: `disconnected` → `logged_in`

### Phase 4: Message Sending

- [ ] Update all message sending functions to include `X-Device-Id` header
- [ ] Retrieve `device_id` from database using `tenant_id`
- [ ] Add error handling for device not logged in
- [ ] Add automatic reconnect logic on connection loss

### Phase 5: Webhook Processing

- [ ] Update webhook handler to extract `device_id` from payload
- [ ] Map `device_id` to `tenant_id` using database lookup
- [ ] Process messages with tenant context
- [ ] Handle webhook signature verification (HMAC SHA256)

### Phase 6: Device Management

- [ ] Add `GET /api/devices/info/{tenant_id}` endpoint
- [ ] Add `POST /api/devices/reconnect/{tenant_id}` endpoint
- [ ] Add `POST /api/devices/logout/{tenant_id}` endpoint
- [ ] Add device health monitoring

---

## 📚 Code Examples - Production Ready

### Complete Device Provisioning Flow

```python
import httpx
import base64
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any

async def provision_tenant_whatsapp(
    tenant_id: str,
    business_name: str,
    bridge_url: str,
    bridge_user: str,
    bridge_pass: str
) -> Dict[str, Any]:
    """
    Complete WhatsApp device provisioning for a tenant

    Returns:
        {
            "success": True,
            "device_id": "bijou-tenant-abc123",
            "state": "disconnected",
            "qr_link": "https://...",
            "message": "Device created. Present QR code to user."
        }
    """
    # Step 1: Create device on bridge
    device_id = f"bijou-{tenant_id}"
    auth_token = base64.b64encode(f"{bridge_user}:{bridge_pass}".encode()).decode()

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Create device
        response = await client.post(
            f"{bridge_url}/devices",
            headers={
                "Authorization": f"Basic {auth_token}",
                "Content-Type": "application/json"
            },
            json={"device_id": device_id}
        )
        response.raise_for_status()
        device_data = response.json()

        if device_data.get("code") != "SUCCESS":
            return {
                "success": False,
                "error": device_data.get("message", "Unknown error")
            }

        created_device_id = device_data["results"]["id"]

        # Step 2: Store in database
        supabase = get_supabase()
        supabase.table("whatsapp_devices").insert({
            "tenant_id": tenant_id,
            "device_id": created_device_id,
            "device_name": business_name,
            "device_state": "disconnected",
            "created_at": datetime.now(timezone.utc).isoformat()
        }).execute()

        # Step 3: Get QR code (optional - can be done later on demand)
        qr_response = await client.get(
            f"{bridge_url}/devices/{created_device_id}/login",
            headers={"Authorization": f"Basic {auth_token}"}
        )
        qr_response.raise_for_status()
        qr_data = qr_response.json()

        return {
            "success": True,
            "device_id": created_device_id,
            "state": "disconnected",
            "qr_link": qr_data.get("results", {}).get("qr_link"),
            "qr_duration": qr_data.get("results", {}).get("qr_duration", 30),
            "message": "Device created successfully. User must scan QR code."
        }
```

### Device Status Polling

```python
async def poll_device_login_status(
    device_id: str,
    bridge_url: str,
    auth_token: str,
    max_attempts: int = 90,  # 3 minutes @ 2s intervals
    interval: int = 2
) -> bool:
    """
    Poll device status until logged in or timeout

    Returns:
        True if device logged in successfully, False on timeout
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        for attempt in range(max_attempts):
            try:
                response = await client.get(
                    f"{bridge_url}/devices/{device_id}/status",
                    headers={"Authorization": f"Basic {auth_token}"}
                )

                if response.status_code == 200:
                    data = response.json()
                    if data.get("results", {}).get("is_logged_in"):
                        # Update database
                        supabase = get_supabase()
                        supabase.table("whatsapp_devices") \
                            .update({"device_state": "logged_in"}) \
                            .eq("device_id", device_id) \
                            .execute()

                        logger.info(f"✅ Device {device_id} logged in successfully")
                        return True

            except Exception as e:
                logger.warning(f"Poll attempt {attempt + 1} failed: {e}")

            await asyncio.sleep(interval)

    logger.error(f"❌ Device {device_id} login timeout after {max_attempts * interval}s")
    return False
```

### Send Message with Device Context

```python
async def send_whatsapp_message(
    tenant_id: str,
    recipient_phone: str,
    message: str,
    bridge_url: str,
    auth_token: str
) -> Dict[str, Any]:
    """
    Send WhatsApp message with proper device scoping

    Args:
        tenant_id: Bijou tenant ID
        recipient_phone: Phone number (e.g., "628987654321")
        message: Message text
        bridge_url: Bridge URL
        auth_token: Basic auth token

    Returns:
        Response from bridge API
    """
    # Step 1: Lookup device_id for tenant
    supabase = get_supabase()
    device_record = supabase.table("whatsapp_devices") \
        .select("device_id, device_state") \
        .eq("tenant_id", tenant_id) \
        .single() \
        .execute()

    if not device_record.data:
        raise ValueError(f"No WhatsApp device found for tenant {tenant_id}")

    device_id = device_record.data["device_id"]
    device_state = device_record.data["device_state"]

    # Step 2: Verify device is logged in
    if device_state != "logged_in":
        raise ValueError(f"Device {device_id} not logged in (state: {device_state})")

    # Step 3: Send message with X-Device-Id header
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{bridge_url}/send/text",
            headers={
                "Authorization": f"Basic {auth_token}",
                "X-Device-Id": device_id,  # CRITICAL: Device scoping
                "Content-Type": "application/json"
            },
            json={
                "phone": recipient_phone,
                "message": message
            }
        )
        response.raise_for_status()
        return response.json()
```

### Webhook Handler with Device Mapping

```python
import hmac
import hashlib
from fastapi import Request, HTTPException

async def handle_whatsapp_webhook(request: Request):
    """
    Process incoming WhatsApp webhook with device context

    Webhook payload structure:
    {
        "event": "message",
        "device_id": "bijou-tenant-abc123",
        "payload": { ... }
    }
    """
    # Step 1: Verify HMAC signature
    signature = request.headers.get("X-Hub-Signature-256", "")
    webhook_secret = os.getenv("WEBHOOK_SECRET", "secret")

    body = await request.body()
    expected_signature = "sha256=" + hmac.new(
        webhook_secret.encode(),
        body,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(signature, expected_signature):
        raise HTTPException(status_code=403, detail="Invalid signature")

    # Step 2: Parse payload
    data = await request.json()
    event_type = data.get("event")
    device_id = data.get("device_id")
    payload = data.get("payload", {})

    # Step 3: Map device_id to tenant_id
    supabase = get_supabase()
    device_record = supabase.table("whatsapp_devices") \
        .select("tenant_id") \
        .eq("device_id", device_id) \
        .single() \
        .execute()

    if not device_record.data:
        logger.error(f"Unknown device_id: {device_id}")
        raise HTTPException(status_code=404, detail="Device not found")

    tenant_id = device_record.data["tenant_id"]

    # Step 4: Process event with tenant context
    if event_type == "message":
        await process_incoming_message(
            tenant_id=tenant_id,
            chat_id=payload.get("chat_id"),
            message_id=payload.get("id"),
            from_jid=payload.get("from"),
            from_name=payload.get("from_name"),
            body=payload.get("body"),
            timestamp=payload.get("timestamp")
        )

    return {"status": "ok"}
```

---

## 🎓 Summary - Key Takeaways

### Critical Fixes for Bijou

1. **Device Creation First**: Always call `POST /devices` before attempting login
2. **Store device_id**: Maintain `tenant_id → device_id` mapping in database
3. **Use X-Device-Id**: Include header in all API calls after device creation
4. **Check Status**: Verify `is_logged_in` before sending messages
5. **Webhook Mapping**: Extract `device_id` from webhook payload and map to tenant

### Architecture Principles

1. **Device ID ≠ JID**: Device ID is for routing, JID is WhatsApp's identifier
2. **Device States**: Track lifecycle (disconnected → connecting → connected → logged_in)
3. **Multi-Device Support**: One bridge instance serves multiple tenants
4. **Middleware Pattern**: Device resolution happens at middleware layer
5. **Persistence**: Devices survive server restarts via registry storage

### Implementation Patterns

1. **Two-Step Login**: Create device → Initiate login (separate API calls)
2. **Status Polling**: Poll `/devices/{id}/status` during onboarding
3. **Error Handling**: Check device state before operations
4. **WebSocket Scoping**: Connect to `/ws?device_id=xxx`
5. **Webhook Processing**: Map device_id to tenant_id for routing

---

## 📖 Further Reading

- **GOWA Bridge OpenAPI Spec**: `docs/openapi.yaml` (complete API reference)
- **Webhook Payload Guide**: `docs/webhook-payload.md` (event structures)
- **Device Manager Source**: `src/infrastructure/whatsapp/device_manager.go`
- **Device Instance Source**: `src/infrastructure/whatsapp/device_instance.go`
- **REST API Handlers**: `src/ui/rest/device.go` and `src/ui/rest/app.go`

---

**Document Version:** 1.0  
**Last Updated:** February 17, 2026  
**Author:** AI Analysis of go-whatsapp-web-multidevice v8.2.0
