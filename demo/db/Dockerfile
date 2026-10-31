FROM postgres:16
COPY schema.sql /schema.sql
CMD ["sh", "-c", "until psql \"$APP_DATABASE_URL\" -c 'select 1' >/dev/null 2>&1; do sleep 1; done; psql \"$APP_DATABASE_URL\" -v ON_ERROR_STOP=1 -f /schema.sql"]
