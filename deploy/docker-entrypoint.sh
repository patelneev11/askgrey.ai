#!/bin/sh
# Migrate before serving. The app does not create its own schema outside development, so a
# failed migration has to stop the release rather than boot a server against an old schema —
# ECS then keeps the previous task serving traffic.
set -eu

alembic upgrade head

# No --proxy-headers: the app reads the visitor's address from X-Forwarded-For itself, counting
# back TRUSTED_PROXY_HOPS entries (1 behind the load balancer). Letting uvicorn rewrite
# request.client as well would trust the whole header.
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
