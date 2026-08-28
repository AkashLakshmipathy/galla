#!/usr/bin/env bash
# Galla — one-shot GCP setup + deploy. Run from the repo root.
#
# One Cloud Run service serves the FastAPI backend and the built PWA, scaled to
# zero. The Pub/Sub push subscription and the Cloud Scheduler job are what make
# the agent fleet asynchronous rather than request-scoped.
set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:-galla-hackathon}"
REGION="${GOOGLE_CLOUD_LOCATION:-asia-south1}"
SVC="galla"
TOPIC="${PUBSUB_TOPIC:-shop-events}"
BUCKET="${GCS_BUCKET:-galla-media}"
SA="galla-agents"
MODEL="${GEMINI_MODEL:-gemini-flash-latest}"

echo "→ project $PROJECT · region $REGION"
gcloud config set project "$PROJECT" >/dev/null

echo "→ enabling APIs"
gcloud services enable run.googleapis.com pubsub.googleapis.com \
  firestore.googleapis.com aiplatform.googleapis.com \
  cloudscheduler.googleapis.com storage.googleapis.com \
  secretmanager.googleapis.com logging.googleapis.com \
  cloudbuild.googleapis.com

echo "→ data stores"
gcloud firestore databases create --location="$REGION" 2>/dev/null || echo "  firestore exists"
gcloud storage buckets create "gs://$BUCKET" --location="$REGION" 2>/dev/null || echo "  bucket exists"
gcloud pubsub topics create "$TOPIC" 2>/dev/null || echo "  topic exists"

echo "→ service account (least privilege: no project-wide editor)"
gcloud iam service-accounts create "$SA" --display-name="Galla agents" 2>/dev/null \
  || echo "  service account exists"
SA_EMAIL="$SA@$PROJECT.iam.gserviceaccount.com"
for ROLE in roles/datastore.user roles/storage.objectAdmin \
            roles/aiplatform.user roles/pubsub.publisher roles/logging.logWriter \
            roles/run.invoker roles/iam.serviceAccountTokenCreator; do
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:$SA_EMAIL" --role="$ROLE" \
    --condition=None >/dev/null
done

echo "→ deploying (scale to zero — the credits have to last to demo day)"
gcloud run deploy "$SVC" --source . --region "$REGION" \
  --service-account "$SA_EMAIL" \
  --allow-unauthenticated --min-instances=0 --max-instances=3 \
  --memory=1Gi --cpu=1 --timeout=300 \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT,GOOGLE_CLOUD_LOCATION=$REGION,GCS_BUCKET=$BUCKET,PUBSUB_TOPIC=$TOPIC,GEMINI_MODEL=$MODEL,GOOGLE_GENAI_USE_VERTEXAI=true,GALLA_STORE=firestore,DEMO_MODE=true"

URL=$(gcloud run services describe "$SVC" --region "$REGION" --format='value(status.url)')
echo "→ service: $URL"

echo "→ pub/sub push subscription (this is what makes the fleet asynchronous)"
# The push subscription and the scheduler both present an OIDC token as $SA_EMAIL.
# The service only checks it when REQUIRE_OIDC=true (see core/authz.py), but the
# identity is wired here either way so turning the check on needs no redeploy.
gcloud pubsub subscriptions create shop-events-push \
  --topic="$TOPIC" --push-endpoint="$URL/pubsub/push" --ack-deadline=120 \
  --push-auth-service-account="$SA_EMAIL" --push-auth-token-audience="$URL" \
  2>/dev/null || gcloud pubsub subscriptions update shop-events-push \
  --push-endpoint="$URL/pubsub/push" \
  --push-auth-service-account="$SA_EMAIL" --push-auth-token-audience="$URL"

echo "→ monthly GST compile — the agent nobody triggers"
gcloud scheduler jobs create http gst-compile \
  --schedule="0 6 1 * *" --time-zone="Asia/Kolkata" --location="$REGION" \
  --uri="$URL/jobs/gst-compile" --http-method=POST \
  --headers="Content-Type=application/json" --message-body='{}' \
  --oidc-service-account-email="$SA_EMAIL" --oidc-token-audience="$URL" \
  2>/dev/null || echo "  scheduler job exists"

echo "→ firestore indexes"
gcloud firestore indexes composite create --file=infra/firestore.indexes.json 2>/dev/null \
  || echo "  indexes exist or are already building"

cat <<EOF

Done.  $URL

Next:
  1. Seed the demo shop:
       gcloud run jobs create galla-seed --image \$(gcloud run services describe $SVC \\
         --region $REGION --format='value(spec.template.spec.containers[0].image)') \\
         --region $REGION --service-account $SA_EMAIL \\
         --set-env-vars GOOGLE_CLOUD_PROJECT=$PROJECT,GALLA_STORE=firestore \\
         --command python --args -m,seed.seed_data
       gcloud run jobs execute galla-seed --region $REGION --wait
  2. Publish the rules:  firebase deploy --only firestore:rules
  3. Fire the scheduler once so it has an execution in its history:
       gcloud scheduler jobs run gst-compile --location $REGION
  4. Once the two async paths are confirmed working, lock them down:
       gcloud run services update $SVC --region $REGION \
         --update-env-vars REQUIRE_OIDC=true,OIDC_SERVICE_ACCOUNT=$SA_EMAIL,OIDC_AUDIENCE=$URL
EOF
