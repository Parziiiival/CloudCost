#!/usr/bin/env bash
# Render build step: install, collect static files, migrate, seed sample data once.
set -o errexit

pip install --upgrade pip
pip install -r requirements.txt

python manage.py collectstatic --noinput
python manage.py migrate --noinput

# Seed the simulated multi-cloud sample data only on the first deploy
# (when DEMO_USER_PASSWORD is set and the demo user does not exist yet).
if [ -n "${DEMO_USER_PASSWORD:-}" ]; then
  if python manage.py shell -c "import sys; from django.contrib.auth import get_user_model; sys.exit(0 if get_user_model().objects.filter(username='demo').exists() else 1)"; then
    echo "Demo user already exists - skipping seed."
  else
    python manage.py seed_demo
  fi
else
  echo "DEMO_USER_PASSWORD not set - skipping demo seed."
fi
