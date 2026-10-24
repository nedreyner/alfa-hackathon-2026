#!/bin/sh
# Том data/runtime на хосте обычно принадлежит root: отдаём его пользователю app и сбрасываем права.
set -e
if [ "$(id -u)" = "0" ]; then
  chown -R app:app /app/data/runtime
  exec setpriv --reuid=app --regid=app --init-groups "$@"
fi
exec "$@"
