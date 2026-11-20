#!/usr/bin/env bash
# Deploy VíaSegura IA to Azure. Designed for Azure Cloud Shell (bash): it already has az, git and
# node, and avoids Windows quoting problems with connection strings.
#
#   git clone https://github.com/yeyson123456/Viasegura-.git && cd Viasegura-
#   export MONGODB_URI='mongodb+srv://<user>:<password>@<cluster-host>/'   # Atlas; never commit it
#   bash infra/deploy.sh                  # optional: LOCATION=eastus2 RG=rg-viasegura MIN_DEVICES=1
#
# Creates: Storage account (photos in Blob, events in Queue), Container Registry (image built in
# the cloud), Container Apps environment + API (scale to zero), two Static Web Apps (Free): the
# driver PWA and the dashboard. Prints the URLs at the end.
#
# Status: written for the prototype; not yet run end-to-end by the authors. Re-running is safe
# (existing resources are reused).
set -euo pipefail

: "${MONGODB_URI:?Set MONGODB_URI (MongoDB Atlas connection string) first}"
RG="${RG:-rg-viasegura}"
LOCATION="${LOCATION:-eastus2}"
PREFIX="${PREFIX:-viasegura}"
MIN_DEVICES="${MIN_DEVICES:-3}"
ADMIN_API_KEY="${ADMIN_API_KEY:-$(openssl rand -hex 24)}"
# Globally unique, lowercase names derived from the subscription id (stable across re-runs).
SUFFIX="$(az account show --query id -o tsv | tr -d '-' | cut -c1-6)"
STORAGE="${PREFIX}st${SUFFIX}"
ACR="${PREFIX}acr${SUFFIX}"
ENV_NAME="${PREFIX}-env"
API="${PREFIX}-api"

step() { printf '\n==> %s\n' "$*"; }

step "Resource group $RG ($LOCATION)"
az group create -n "$RG" -l "$LOCATION" -o none

step "Storage account $STORAGE (private blobs + queue)"
az storage account create -n "$STORAGE" -g "$RG" -l "$LOCATION" --sku Standard_LRS --kind StorageV2 \
  --min-tls-version TLS1_2 --allow-blob-public-access false -o none
STORAGE_CONN="$(az storage account show-connection-string -n "$STORAGE" -g "$RG" --query connectionString -o tsv)"

step "Container registry $ACR and API image (built in the cloud, no local Docker needed)"
az acr create -n "$ACR" -g "$RG" --sku Basic --admin-enabled true -o none
az acr build -r "$ACR" -t viasegura-api:latest -f services/api/Dockerfile . -o none
ACR_PASSWORD="$(az acr credential show -n "$ACR" --query 'passwords[0].value' -o tsv)"

step "Container Apps environment and API"
az extension add --name containerapp --upgrade -o none 2>/dev/null || true
az containerapp env create -n "$ENV_NAME" -g "$RG" -l "$LOCATION" -o none
if ! az containerapp show -n "$API" -g "$RG" -o none 2>/dev/null; then
  az containerapp create -n "$API" -g "$RG" --environment "$ENV_NAME" \
    --image "$ACR.azurecr.io/viasegura-api:latest" --registry-server "$ACR.azurecr.io" \
    --registry-username "$ACR" --registry-password "$ACR_PASSWORD" \
    --target-port 8000 --ingress external --min-replicas 0 --max-replicas 1 --cpu 1.0 --memory 2.0Gi \
    -o none
fi
az containerapp secret set -n "$API" -g "$RG" -o none --secrets \
  "mongodb-uri=$MONGODB_URI" "admin-key=$ADMIN_API_KEY" "storage-conn=$STORAGE_CONN"
API_HOST="$(az containerapp show -n "$API" -g "$RG" --query properties.configuration.ingress.fqdn -o tsv)"
API_URL="https://$API_HOST"

deploy_static_app() { # $1 = app folder under apps/, $2 = Static Web App name
  local folder="$1" name="$2" host token
  az staticwebapp create -n "$name" -g "$RG" -l "$LOCATION" --sku Free -o none 2>/dev/null || true
  host="$(az staticwebapp show -n "$name" -g "$RG" --query defaultHostname -o tsv)"
  token="$(az staticwebapp secrets list -n "$name" -g "$RG" --query properties.apiKey -o tsv)"
  (cd "apps/$folder" && npm ci --no-audit --no-fund && VITE_API_URL="$API_URL" npm run build \
    && cp staticwebapp.config.json dist/ \
    && npx --yes @azure/static-web-apps-cli deploy ./dist --deployment-token "$token" --env production)
  echo "https://$host"
}

step "Driver PWA (Static Web Apps, Free)"
PWA_URL="$(deploy_static_app driver-pwa "${PREFIX}-pwa" | tail -n 1)"
step "Dashboard (Static Web Apps, Free)"
DASH_URL="$(deploy_static_app dashboard "${PREFIX}-dashboard" | tail -n 1)"

step "API settings (secrets referenced, CORS limited to the two apps)"
az containerapp update -n "$API" -g "$RG" -o none --set-env-vars \
  MONGODB_URI=secretref:mongodb-uri MONGODB_DB=viasegura ADMIN_API_KEY=secretref:admin-key \
  AZURE_STORAGE_CONNECTION_STRING=secretref:storage-conn API_ENV=azure FORWARDED_ALLOW_IPS='*' \
  CONSENSUS_MIN_DEVICES="$MIN_DEVICES" API_CORS_ORIGINS="$PWA_URL,$DASH_URL"

cat <<EOF

VíaSegura IA deployed
  API        $API_URL/docs   (health: $API_URL/health)
  Driver app $PWA_URL        (HTTPS: camera and GPS work on phones)
  Dashboard  $DASH_URL
  Admin key  $ADMIN_API_KEY  (dashboard "Marcar como resuelto"; store it safely)

MongoDB Atlas: allow Azure in Network Access (0.0.0.0/0 or the Container Apps outbound IPs).
EOF
