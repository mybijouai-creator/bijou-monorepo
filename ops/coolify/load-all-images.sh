#!/bin/bash
# Run on the Coolify host (169.58.147.169) as root
# Load all 3 Bijou/agentops Docker images and tag them for Coolify services

set -e
cd /tmp

echo "=== Loading Bijou backend (optimized, CPU-only) ==="
docker load -i bijou-backend-optimized-v0.4.6.tar
docker tag bijour-local/bijou-backend-optimized:v0.4.6 bijou-backend:v0.4.6

echo "=== Loading agentops backend ==="
docker load -i agentops-backend-v0.4.6.tar
docker tag bijour-local/agentops-backend:v0.4.6 agentops-backend:v0.4.6

echo "=== Loading WhatsApp bridge ==="
docker load -i bijou-bridge-v1.0.0.tar
docker tag bijour-local/bijou-bridge:v1.0.0 bijou-bridge:v1.0.0

echo "=== Verification ==="
docker images | grep -E "bijou-backend|agentops-backend|bijou-bridge"

echo "=== Done! ==="
echo "Update Coolify services to use these image names:"
echo "  - bijou-backend:v0.4.6"
echo "  - agentops-backend:v0.4.6"
echo "  - bijou-bridge:v1.0.0"