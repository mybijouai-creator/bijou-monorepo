# Run on the Coolify host (169.58.147.169) as root
# This loads the agentops-backend image from the local Windows file system

# 1. Get the image tar from this Windows machine
#    - via SCP from Windows: scp USER@WINDOWS_IP:path/to/agentops-backend-v0.4.6.tar .
#    - via shared folder / network mount
#    - via USB / any other transfer

# 2. Once the tar is on the Coolify host:
docker load -i agentops-backend-v0.4.6.tar

# 3. Tag it so the Coolify service can find it (Coolify looks up image by name)
docker tag bijour-local/agentops-backend:v0.4.6 agentops-backend:v0.4.6

# 4. Verify
docker images | grep agentops-backend

# 5. Update the Coolify service to use the image
#    Option A (API):
#    PATCH /api/v1/services/hhtakgqeqasqciidtoy4napa/docker_compose_raw
#    with new compose that has image: 'agentops-backend:v0.4.6'
#
#    Option B (UI): Edit the service in Coolify, change image to 'agentops-backend:v0.4.6'

# 6. Restart the service
curl -X POST https://coolify.getbijou.xyz/api/v1/services/hhtakgqeqasqciidtoy4napa/start \
  -H "Authorization: Bearer 1|inxuyFzhxjO0jasJoLFC9eS7T8ZDAXKtw4ITrmdb3fd0ec34"