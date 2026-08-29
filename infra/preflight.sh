#!/usr/bin/env bash
# Checks everything deploy.sh assumes, before it starts changing your project.
# Read-only: creates nothing, costs nothing. Run it the moment you are authenticated.
set -uo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:-}"
REGION="${GOOGLE_CLOUD_LOCATION:-asia-south1}"
ok=0; bad=0
pass () { echo "  ✓ $1"; ok=$((ok+1)); }
fail () { echo "  ✗ $1"; bad=$((bad+1)); }

echo "── identity"
ACCOUNT=$(gcloud config get-value account 2>/dev/null)
[ -n "$ACCOUNT" ] && [ "$ACCOUNT" != "(unset)" ] && pass "logged in as $ACCOUNT" \
  || fail "not logged in — run: gcloud auth login"
gcloud auth application-default print-access-token >/dev/null 2>&1 \
  && pass "application-default credentials present (local Gemini + Firestore will work)" \
  || fail "no ADC — run: gcloud auth application-default login"

echo "── project"
[ -n "$PROJECT" ] || PROJECT=$(gcloud config get-value project 2>/dev/null)
if [ -z "$PROJECT" ] || [ "$PROJECT" = "(unset)" ]; then
  fail "no project set — export GOOGLE_CLOUD_PROJECT=your-id"
else
  pass "project $PROJECT"
  BILL=$(gcloud billing projects describe "$PROJECT" \
         --format='value(billingEnabled)' 2>/dev/null)
  [ "$BILL" = "True" ] && pass "billing enabled" \
    || fail "billing NOT enabled — Cloud Run, Vertex AI and Scheduler will all refuse"
fi

echo "── the model the agents will actually call"
MODEL="${GEMINI_MODEL:-gemini-3.5-flash}"
MODEL_FAST="${GEMINI_MODEL_FAST:-gemini-3.5-flash-lite}"
# The one unknown worth catching before deploy: an alias that resolves on AI
# Studio may not resolve on Vertex in this region.
if gcloud ai models list --region="$REGION" --project="$PROJECT" \
     --format='value(displayName)' 2>/dev/null | grep -qi "gemini"; then
  pass "Vertex AI reachable in $REGION"
else
  echo "  ? could not list Vertex models in $REGION (may need the API enabled first)"
fi
echo "  → confirm '$MODEL' resolves by running, after deploy.sh enables the APIs:"
echo "    python -c \"from google import genai; c=genai.Client(vertexai=True, project='$PROJECT', location='$REGION'); print(c.models.get(model='$MODEL'))\""

echo "── quota-sensitive prerequisites"
for API in run.googleapis.com aiplatform.googleapis.com firestore.googleapis.com \
           pubsub.googleapis.com cloudscheduler.googleapis.com; do
  gcloud services list --enabled --project="$PROJECT" 2>/dev/null | grep -q "$API" \
    && pass "$API already enabled" || echo "  · $API will be enabled by deploy.sh"
done
gcloud app describe --project="$PROJECT" >/dev/null 2>&1 \
  && pass "App Engine app exists (Cloud Scheduler needs one in some projects)" \
  || echo "  · no App Engine app — if 'scheduler jobs create' fails, run: gcloud app create --region=$REGION"

echo
echo "── local toolchain"
command -v docker >/dev/null && docker info >/dev/null 2>&1 \
  && pass "docker daemon reachable" || fail "docker daemon not running"
# firebase-tools is usually installed under a version-managed node, which a
# plain login shell cannot see.
[ -s "$HOME/.nvm/nvm.sh" ] && . "$HOME/.nvm/nvm.sh" >/dev/null 2>&1 && nvm use 20 >/dev/null 2>&1
command -v firebase >/dev/null && pass "firebase CLI $(firebase --version 2>/dev/null)" \
  || echo "  · firebase CLI not on PATH (only needed to publish firestore.rules;"
command -v firebase >/dev/null || echo "    if you installed it under nvm, run 'nvm use 20' first)"

echo
echo "$ok checks passed, $bad blocking."
[ "$bad" -eq 0 ] && echo "Ready: bash infra/deploy.sh" || echo "Fix the ✗ items first."
exit "$bad"
