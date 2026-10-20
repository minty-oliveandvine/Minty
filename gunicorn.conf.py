# Read by gunicorn from the working directory - the repo root for Render's `gunicorn app:app` and
# docker/Dockerfile's `gunicorn ... main:app`. Only the logger: bind, workers and the rest stay on
# the command line and GUNICORN_CMD_ARGS. Why: services/app_runtime/gunicorn_logging.py.
logger_class = "services.app_runtime.gunicorn_logging.NoAccessLogger"
