#!/usr/bin/env bash
# Usage: ./deploy/azure/grant_teammate.sh teammate@company.com
set -euo pipefail
UPN=${1:?email required}
RG=rg-fnol-team
SUB=319c1259-ef4a-4685-afd8-12ae3dc337bc
OID=$(az ad user show --id "$UPN" --query id -o tsv)
az role assignment create --assignee-object-id "$OID" --assignee-principal-type User \
  --role "CostControl Contributor" --scope "/subscriptions/$SUB/resourceGroups/$RG" -o none
az role assignment create --assignee-object-id "$OID" --assignee-principal-type User \
  --role "Storage Blob Data Contributor" \
  --scope "/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Storage/storageAccounts/fnolstcb3cssvjwszz6" -o none
az role assignment create --assignee-object-id "$OID" --assignee-principal-type User \
  --role "AcrPull" \
  --scope "/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.ContainerRegistry/registries/fnolteamacr" -o none
# SQL: Entra admin must add them as db user
echo "Granted RG + Blob + AcrPull to $UPN ($OID)"
echo "Have SQL admin run:"
echo "  CREATE USER [$UPN] FROM EXTERNAL PROVIDER;"
echo "  ALTER ROLE db_datareader ADD MEMBER [$UPN];"
echo "  ALTER ROLE db_datawriter ADD MEMBER [$UPN];"
