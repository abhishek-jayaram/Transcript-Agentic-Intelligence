# Run it in Docker and Kubernetes (local first)

This packages the web UI as a container image and runs it on a Kubernetes cluster on your own laptop.
Neo4j Aura and Microsoft Foundry stay where they are; the container only needs internet access to reach them.

**Read this first.** The UI has **no login**. Everything below keeps it private: Docker publishes the port on `127.0.0.1` only, and the Kubernetes
Service is `ClusterIP` (you reach it with `kubectl port-forward`). Do not change that to a public address without putting authentication in front.

**Status:** I wrote these files but could not build or run them in my environment (no Docker daemon there). The YAML parses and the code
changes are unit-tested, but treat your first build as the real test and paste any error back to me.

## What you need
- Docker Desktop, running. For Kubernetes: Docker Desktop > Settings > Kubernetes > **Enable Kubernetes**, wait until it says running.
- `kubectl` (Docker Desktop installs it). Check: `kubectl config current-context` should print `docker-desktop`.
- Azure CLI, signed in (`az login`), and permission to create a service principal and assign a role on your Foundry resource.
- Your working `.env` (Neo4j and Foundry values), with the Neo4j password you rotated.

## 1. Create a service principal (the container's Azure identity)
Your own `az login` does not exist inside a container, so the container signs in with a dedicated app identity. PowerShell:
```powershell
az cognitiveservices account list --query "[].{name:name, rg:resourceGroup, kind:kind}" -o table    # find your Foundry resource
$scope = az cognitiveservices account show -n <foundry-resource-name> -g <resource-group> --query id -o tsv
az ad sp create-for-rbac --name ti-demo-sp --role "Azure AI User" --scopes $scope
```
It prints `appId`, `password` and `tenant`. **The password is shown once**; copy it now. They map to:

| Output | Setting |
|---|---|
| `tenant` | `AZURE_TENANT_ID` |
| `appId` | `AZURE_CLIENT_ID` |
| `password` | `AZURE_CLIENT_SECRET` |

Role assignments can take a few minutes to take effect. If answers later fail with a 401/403, also grant **Cognitive Services OpenAI User**
on the same scope (the embedding call uses the Azure OpenAI path) and wait a few minutes.

## 2. Try plain Docker first (recommended)
Add the three `AZURE_*` lines from step 1 to your `.env` (see `.env.example`). Then, from the project root:
```powershell
docker compose up --build
```
Open http://127.0.0.1:8000 and ask a question. The log should show `Telemetry: ...` and `Transcript Intelligence UI -> ...`. Stop with Ctrl+C.
Quick health check from a second terminal: `curl http://127.0.0.1:8000/healthz` returns `{"status":"ok"}`.

Note: with the `AZURE_*` values in `.env`, a normal `python -m ti.web` also uses that service principal instead of your `az login`. That is fine; remove the lines to go back.

## 3. Kubernetes
**a. Build the image** (skip if `docker compose up --build` already built `ti-web:local`):
```powershell
docker build -t ti-web:local .
```
Docker Desktop's Kubernetes uses your local images directly. With kind use `kind load docker-image ti-web:local`; with minikube use `minikube image load ti-web:local`.

**b. Edit `k8s/configmap.yaml`**: put your Neo4j URI and Foundry endpoint in (same values as your `.env`, not secrets).

**c. Create `k8s/secrets.env`** (git-ignored; never share it) with one `KEY=value` per line:
```
NEO4J_PASSWORD=...
AZURE_TENANT_ID=...
AZURE_CLIENT_ID=...
AZURE_CLIENT_SECRET=...
APPLICATIONINSIGHTS_CONNECTION_STRING=...
```
(Leave out the last line if you do not use Azure tracing.)

**d. Apply, in this order:**
```powershell
kubectl apply -f k8s/namespace.yaml
kubectl -n transcript-intelligence create secret generic ti-secrets --from-env-file=k8s/secrets.env
kubectl apply -k k8s/
```

**e. Check it came up, then open it:**
```powershell
kubectl -n transcript-intelligence get pods                    # wait for 1/1 Running
kubectl -n transcript-intelligence logs deploy/ti-web          # should show the Telemetry and UI lines
kubectl -n transcript-intelligence port-forward svc/ti-web 8000:80
```
Open http://127.0.0.1:8000 (keep the port-forward window open).

**f. After you change the code:**
```powershell
docker build -t ti-web:local .
kubectl -n transcript-intelligence rollout restart deploy/ti-web
```
To change the secret: delete it (`kubectl -n transcript-intelligence delete secret ti-secrets`), create it again as in step d, then restart the deployment.

## 4. Clean up
```powershell
kubectl delete namespace transcript-intelligence
az ad sp delete --id <appId>          # removes the service principal when you are done with the demo
```

## What is in the box
| File | Purpose |
|---|---|
| `Dockerfile`, `.dockerignore` | The image: Python 3.11, non-root user, only `src/` (no `.env`, data or tests) |
| `docker-compose.yml` | One-command local run, port published on `127.0.0.1` only |
| `k8s/namespace.yaml`, `configmap.yaml`, `deployment.yaml`, `service.yaml`, `kustomization.yaml` | The cluster objects (the secret is created by you, see 3c-d) |
| `k8s/secret.example.yaml` | Template showing which secret keys exist; contains no real values |

Design choices: **one replica** (conversations live in memory and the app answers one question at a time, so more replicas would lose context and add nothing),
health probes on `/healthz` (which does not touch Neo4j or Azure, so a database hiccup does not restart the pod), read-only root filesystem, no root, no extra Linux capabilities.

## Troubleshooting
| Symptom | Likely cause and fix |
|---|---|
| Pod `ErrImageNeverPull` / `ImagePullBackOff` | The cluster cannot see `ti-web:local`. Docker Desktop: rebuild with `docker build`; kind/minikube: load the image (3a) |
| Pod `CreateContainerConfigError` | The secret `ti-secrets` does not exist yet: run step 3d's create-secret command |
| Pod `CrashLoopBackOff` | `kubectl -n transcript-intelligence logs deploy/ti-web --previous` shows why (often a missing setting, e.g. "Missing NEO4J_URI") |
| UI answer: "Azure sign-in problem" | Wrong `AZURE_*` value, expired/mistyped client secret, or the service principal lacks the role (step 1) |
| UI answer: "Could not reach Neo4j" | Aura paused, wrong URI in the ConfigMap, or wrong `NEO4J_PASSWORD` in the secret |
| Browser cannot connect | The `port-forward` window was closed; start it again |

## Moving to Azure Kubernetes Service (AKS) later
The same manifests work with three changes: push the image to Azure Container Registry and set `image:` (and `imagePullPolicy`) accordingly; replace the
service principal secret with workload identity (no secret to store; this needs a small code change to pick `WorkloadIdentityCredential`);
and put real authentication (for example an ingress with Entra ID sign-in) in front, because the app itself has none.
