#!/usr/bin/env bash
# EN: Start command for the public demo (Render). Rebuilds the demo data, serves the app with
#     gunicorn until 3 a.m. São Paulo time, then rebuilds and starts again, every day.
# PT: Comando de início da demonstração pública (Render). Recria os dados da demo, serve o app
#     com o gunicorn até as 3h no horário de São Paulo, e então recria e recomeça, todo dia.
set -u

while true; do
    python -m flask --app app init-db --reset
    DEMO_MODE= python seed.py   # EN: the seed signs up through /register | PT: o seed se cadastra pelo /register

    # EN: seconds until the next 3 a.m. in São Paulo | PT: segundos até as próximas 3h em São Paulo
    SECONDS_LEFT=$(python -c "
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
now = datetime.now(ZoneInfo('America/Sao_Paulo'))
target = now.replace(hour=3, minute=0, second=0, microsecond=0)
if target <= now:
    target += timedelta(days=1)
print(int((target - now).total_seconds()))
")

    timeout "$SECONDS_LEFT" gunicorn app:app --bind "0.0.0.0:${PORT:-5000}" --workers 1 --threads 4 || true
done
