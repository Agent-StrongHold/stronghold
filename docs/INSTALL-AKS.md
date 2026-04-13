# Deploying Stronghold on Azure AKS

Azure Kubernetes Service (AKS) is a Tier-1 supported platform per
[ADR-K8S-007](adr/ADR-K8S-007-distro-compatibility-matrix.md). This guide
walks through a production-ready deployment using Entra ID authentication,
Azure Workload Identity, and the Stronghold Helm chart.

## Prerequisites

| Requirement | Minimum | Notes |
|---|---|---|
| AKS cluster | 1.29+ | OIDC issuer + Workload Identity enabled |
| Azure CLI | 2.61+ | `az aks` commands below require it |
| Helm | 3.14+ | Chart uses `kubeVersion: >=1.29.0-0` |
| kubectl | matching cluster version | |
| CNI | Azure CNI | Calico or Cilium network policy enforcement |
| DNS | A record for ingress | Or use nip.io for testing |

### Azure services used

- **AKS** — Kubernetes runtime
- **Azure Container Registry (ACR)** — container image storage
- **Azure Disk CSI** — persistent volumes (enabled by default on AKS 1.29+)
- **Application Gateway Ingress Controller (AGIC)** — L7 ingress (or nginx)
- **Entra ID (Azure AD)** — user authentication via OIDC/JWT
- **Azure Key Vault** — secrets (optional, via External Secrets Operator)

## 1. Provision the AKS cluster

The default profile uses burstable B-series nodes with cluster autoscaler.
Pods start tiny and HPA scales them out; the cluster autoscaler adds nodes
when pods are unschedulable and removes them when idle.

```bash
RESOURCE_GROUP=stronghold-rg
CLUSTER_NAME=stronghold-aks
LOCATION=eastus2

# Create resource group
az group create --name $RESOURCE_GROUP --location $LOCATION

# Create AKS cluster — B4ms (4 vCPU / 16GB, burstable) with autoscaler
az aks create \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER_NAME \
  --node-count 1 \
  --min-count 1 \
  --max-count 5 \
  --node-vm-size Standard_B4ms \
  --enable-cluster-autoscaler \
  --network-plugin azure \
  --network-policy calico \
  --enable-oidc-issuer \
  --enable-workload-identity \
  --enable-managed-identity \
  --generate-ssh-keys

# Tune autoscaler for aggressive response
az aks update \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER_NAME \
  --cluster-autoscaler-profile \
    scale-down-delay-after-add=5m \
    scale-down-unneeded-time=5m \
    scan-interval=10s \
    max-graceful-termination-sec=30

# Get credentials
az aks get-credentials --resource-group $RESOURCE_GROUP --name $CLUSTER_NAME
```

For larger teams or sustained high load, use `Standard_D4s_v5` (dedicated
compute) instead of B-series burstable.

### Install nginx-ingress

The default `values-aks.yaml` uses nginx-ingress (cheap — backed by a
Standard Load Balancer at ~$18/mo):

```bash
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx --create-namespace
```

If you need WAF or L7 path routing, use AGIC instead:

```bash
az aks enable-addons \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER_NAME \
  --addons ingress-appgw \
  --appgw-subnet-cidr "10.225.0.0/16"
# Then override: --set ingressRoutes.className=azure-application-gateway
```

## 2. Set up Azure Container Registry

```bash
ACR_NAME=strongholdacr  # Must be globally unique

az acr create --resource-group $RESOURCE_GROUP --name $ACR_NAME --sku Standard

# Attach ACR to AKS (grants AcrPull to the kubelet identity)
az aks update \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER_NAME \
  --attach-acr $ACR_NAME

# Build and push the Stronghold image
az acr build --registry $ACR_NAME --image stronghold/stronghold-api:latest .
```

## 3. Register the Entra ID application

Stronghold validates JWTs issued by Entra ID. You need an app registration:

```bash
# Create app registration
az ad app create --display-name stronghold-api \
  --sign-in-audience AzureADMyOrg

# Note the appId (this is your CLIENT_ID)
CLIENT_ID=$(az ad app list --display-name stronghold-api --query '[0].appId' -o tsv)

TENANT_ID=$(az account show --query tenantId -o tsv)

echo "ENTRA_TENANT_ID=$TENANT_ID"
echo "ENTRA_CLIENT_ID=$CLIENT_ID"
```

### Define app roles

Add Stronghold RBAC roles to the app registration (Admin, Engineer, Operator,
Viewer) via the Azure Portal under **App registrations > stronghold-api > App
roles**, or via the manifest:

| Role value | Description |
|---|---|
| `Stronghold.Admin` | Full platform administration |
| `Stronghold.Engineer` | Code agents, tool creation |
| `Stronghold.Operator` | Device control, runbooks |
| `Stronghold.Viewer` | Read-only search and observation |

## 4. Configure Azure Workload Identity

Workload Identity lets pods authenticate to Azure services without storing
credentials. This replaces the deprecated pod-managed identity (aad-pod-identity).

```bash
AKS_OIDC_ISSUER=$(az aks show \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER_NAME \
  --query "oidcIssuerProfile.issuerUrl" -o tsv)

# Create a managed identity for Stronghold workloads
az identity create \
  --name stronghold-identity \
  --resource-group $RESOURCE_GROUP \
  --location $LOCATION

IDENTITY_CLIENT_ID=$(az identity show \
  --name stronghold-identity \
  --resource-group $RESOURCE_GROUP \
  --query clientId -o tsv)

# Create federated credential for the stronghold-api service account
az identity federated-credential create \
  --name stronghold-api-fc \
  --identity-name stronghold-identity \
  --resource-group $RESOURCE_GROUP \
  --issuer "$AKS_OIDC_ISSUER" \
  --subject "system:serviceaccount:stronghold-platform:stronghold-stronghold-api" \
  --audience "api://AzureADTokenExchange"

# Create federated credential for LiteLLM (if it needs Azure OpenAI access)
az identity federated-credential create \
  --name litellm-fc \
  --identity-name stronghold-identity \
  --resource-group $RESOURCE_GROUP \
  --issuer "$AKS_OIDC_ISSUER" \
  --subject "system:serviceaccount:stronghold-platform:stronghold-stronghold-litellm" \
  --audience "api://AzureADTokenExchange"
```

### Grant permissions to the managed identity

If using Azure Key Vault for secrets:

```bash
KV_NAME=stronghold-kv

az keyvault set-policy --name $KV_NAME \
  --secret-permissions get list \
  --object-id $(az identity show --name stronghold-identity \
    --resource-group $RESOURCE_GROUP --query principalId -o tsv)
```

If using Azure OpenAI:

```bash
AOAI_RESOURCE_ID=$(az cognitiveservices account show \
  --name <your-aoai-resource> \
  --resource-group <your-rg> \
  --query id -o tsv)

az role assignment create \
  --assignee-object-id $(az identity show --name stronghold-identity \
    --resource-group $RESOURCE_GROUP --query principalId -o tsv) \
  --role "Cognitive Services OpenAI User" \
  --scope "$AOAI_RESOURCE_ID"
```

## 5. Deploy with Helm

```bash
helm upgrade --install stronghold deploy/helm/stronghold \
  --namespace stronghold-platform --create-namespace \
  -f deploy/helm/stronghold/values-vanilla-k8s.yaml \
  -f deploy/helm/stronghold/values-aks.yaml \
  --set auth.entraId.tenantId="$TENANT_ID" \
  --set auth.entraId.clientId="$CLIENT_ID" \
  --set serviceAccounts.strongholdApi.annotations."azure\.workload\.identity/client-id"="$IDENTITY_CLIENT_ID" \
  --set serviceAccounts.litellm.annotations."azure\.workload\.identity/client-id"="$IDENTITY_CLIENT_ID" \
  --set strongholdApi.image.registry="${ACR_NAME}.azurecr.io" \
  --set strongholdApi.image.tag="latest" \
  --set ingressRoutes.stronghold.host="stronghold.yourdomain.com"
```

### Using nginx-ingress instead of AGIC

If you installed nginx-ingress instead of AGIC, override the ingress class:

```bash
--set ingressRoutes.className=nginx
```

## 6. Verify the deployment

```bash
# Wait for pods
kubectl -n stronghold-platform get pods -w

# Check health
kubectl -n stronghold-platform port-forward svc/stronghold-stronghold-api 8100:8100
curl http://localhost:8100/health

# Verify Workload Identity injection (pods should have AZURE_* env vars)
kubectl -n stronghold-platform exec deploy/stronghold-stronghold-api \
  -- env | grep AZURE_

# Test network policies
kubectl run netpol-test --image=busybox --rm -it --restart=Never \
  -n default -- wget -qO- --timeout=3 \
  http://stronghold-stronghold-api.stronghold-platform:8100/health
# ^ Should timeout/fail (default namespace blocked by network policy)
```

## 7. Azure Key Vault integration (optional)

For production, use External Secrets Operator (ESO) to pull secrets from
Azure Key Vault instead of Kubernetes Secrets:

```bash
# Install ESO
helm repo add external-secrets https://charts.external-secrets.io
helm install external-secrets external-secrets/external-secrets \
  --namespace external-secrets --create-namespace

# Create a SecretStore pointing to Azure Key Vault
cat <<EOF | kubectl apply -f -
apiVersion: external-secrets.io/v1beta1
kind: SecretStore
metadata:
  name: azure-kv
  namespace: stronghold-platform
spec:
  provider:
    azurekv:
      authType: WorkloadIdentity
      vaultUrl: "https://${KV_NAME}.vault.azure.net"
      serviceAccountRef:
        name: stronghold-stronghold-api
EOF

# Create ExternalSecret for Stronghold secrets
cat <<EOF | kubectl apply -f -
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: stronghold-secrets
  namespace: stronghold-platform
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: azure-kv
    kind: SecretStore
  target:
    name: stronghold-secrets
  data:
    - secretKey: ROUTER_API_KEY
      remoteRef:
        key: stronghold-router-api-key
    - secretKey: LITELLM_MASTER_KEY
      remoteRef:
        key: stronghold-litellm-master-key
EOF
```

## 8. Azure OpenAI with LiteLLM

To route through Azure OpenAI instead of (or alongside) other providers,
add models to the LiteLLM config. The Helm chart mounts the config from
`deploy/helm/stronghold/files/litellm_config.yaml`.

Example Azure OpenAI model entry:

```yaml
model_list:
  - model_name: gpt-4o
    litellm_params:
      model: azure/gpt-4o
      api_base: https://<your-resource>.openai.azure.com/
      api_version: "2024-08-01-preview"
      # With Workload Identity, no API key needed:
      # LiteLLM uses DefaultAzureCredential automatically
```

## Architecture on AKS

```
                    Internet
                       |
                  nginx-ingress
              (Standard Load Balancer)
                       |
          +------------+------------+
          |                         |
   stronghold-api (1→8)     litellm (1→6)     ← HPA-managed
          |                    |
          +--------+-----------+
                   |
            postgres (StatefulSet)
            Azure Managed Disk (CSI)
                   |
            phoenix (observability)

Auth: Entra ID (JWT) ──> stronghold-api
Secrets: Azure Key Vault ──> ESO ──> K8s Secrets
Identity: Azure Workload Identity (no stored credentials)
Scaling: HPA (pods) + cluster autoscaler (nodes, 1→5 B4ms)
```

At idle, everything fits on a single B4ms node. Under load, HPA adds pods
and the cluster autoscaler adds nodes within ~30s.

## Cost estimates

### Minimal / startup (1-node idle, autoscales to 5)

| Resource | SKU | Estimated monthly cost |
|---|---|---|
| AKS node at idle (1x B4ms) | Pay-as-you-go | ~$120 |
| Azure Load Balancer | Standard (nginx-ingress) | ~$18 |
| Azure Disk (8Gi) | managed-csi | ~$1 |
| ACR | Standard | ~$5 |
| Azure Key Vault | Standard | ~$1 |
| **Total at idle** | | **~$145/month** |

Under sustained load with 3 nodes active: ~$385/month. Nodes scale back
to 1 after 5 minutes of low utilization.

### Production (dedicated compute, AGIC)

| Resource | SKU | Estimated monthly cost |
|---|---|---|
| AKS cluster (3x D4s_v5) | Pay-as-you-go | ~$400 |
| Application Gateway (v2) | Standard_v2 | ~$250 |
| Azure Disk (32Gi) | managed-csi-premium | ~$5 |
| ACR | Standard | ~$5 |
| Azure Key Vault | Standard | ~$1 |
| **Total** | | **~$660/month** |

For production, use dedicated D-series VMs (no CPU throttling) and
Application Gateway for WAF. Override in Helm:
`--set ingressRoutes.className=azure-application-gateway`.

## Troubleshooting

**Pods stuck in `CrashLoopBackOff`:** Check logs with
`kubectl -n stronghold-platform logs deploy/stronghold-stronghold-api`. Common
causes: missing `ENTRA_TENANT_ID`/`ENTRA_CLIENT_ID`, database not ready.

**Workload Identity not injecting:** Verify the federated credential subject
matches `system:serviceaccount:<namespace>:<sa-name>` exactly. Check with
`az identity federated-credential list --identity-name stronghold-identity --resource-group <rg>`.

**NetworkPolicy blocking legitimate traffic:** Ensure your ingress controller
namespace has the label `networking.k8s.io/ingress=true`, or set
`networkPolicy.ingressOpen=true` for testing.

**AGIC not picking up Ingress:** Ensure the AGIC addon is enabled and the
`ingressClassName` is `azure-application-gateway`. Check AGIC logs:
`kubectl logs -n kube-system -l app=ingress-appgw`.

**PostgreSQL PVC pending:** Verify the `managed-csi` StorageClass exists:
`kubectl get sc`. On older AKS clusters, create it manually or use
`managed-csi-premium`.
