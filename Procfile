web: gunicorn app:app \
  --bind 0.0.0.0:${PORT:-8010} \
  --workers 2 \
  --threads 4 \
  --timeout 120 \
  --keepalive 120 \
  --access-logfile - \
  --error-logfile -
