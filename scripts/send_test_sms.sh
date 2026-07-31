#!/bin/bash
# Send a test SMS using the Twilio credentials in .env.
#
# Usage:
#   ./scripts/send_test_sms.sh [recipient] [message]
#
#   recipient  E.164 number, e.g. +393311194199.
#              Defaults to the first SendSMSTo entry in config.yaml.
#   message    Message body. Defaults to a canned test message.
#
# Uses API-key auth (TWILIO_API_KEY_SID/SECRET + TWILIO_ACCOUNT_SID) when present,
# otherwise falls back to account-SID/auth-token auth — same as src/sms.py.

set -eu

ScriptDir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HomeDir="$(cd "$ScriptDir/.." && pwd)"
EnvFile="$HomeDir/.env"
ConfigFile="$HomeDir/config.yaml"

if [ ! -f "$EnvFile" ]; then
  echo "Error: $EnvFile not found." >&2
  exit 1
fi

# Load .env into the environment.
set -a
# shellcheck disable=SC1090
. "$EnvFile"
set +a

# Recipient: CLI arg, else first +E.164 number under SendSMSTo in config.yaml.
TO="${1:-}"
if [ -z "$TO" ] && [ -f "$ConfigFile" ]; then
  TO="$(grep -A10 'SendSMSTo:' "$ConfigFile" | grep -oE '\+[0-9]+' | head -1 || true)"
fi
if [ -z "$TO" ]; then
  echo "Error: no recipient given and none found in config.yaml. Pass one, e.g.:" >&2
  echo "  ./scripts/send_test_sms.sh +393311194199" >&2
  exit 1
fi

MSG="${2:-Water Information Display test message — if you received this, Twilio SMS is working.}"

FROM="${TWILIO_FROM_NUMBER:-}"
ACCOUNT_SID="${TWILIO_ACCOUNT_SID:-}"
if [ -z "$FROM" ] || [ -z "$ACCOUNT_SID" ]; then
  echo "Error: TWILIO_FROM_NUMBER and TWILIO_ACCOUNT_SID must be set in .env." >&2
  exit 1
fi
case "$ACCOUNT_SID" in
  AC*) : ;;
  *) echo "Error: TWILIO_ACCOUNT_SID must be your account SID (starts with 'AC'), not an API key." >&2; exit 1 ;;
esac

# Choose auth: API key (SK sid + secret) if present, else account SID + auth token.
if [ -n "${TWILIO_API_KEY_SID:-}" ] && [ -n "${TWILIO_API_KEY_SECRET:-}" ]; then
  AUTH="${TWILIO_API_KEY_SID}:${TWILIO_API_KEY_SECRET}"
  echo "Auth: API key ${TWILIO_API_KEY_SID}"
elif [ -n "${TWILIO_AUTH_TOKEN:-}" ]; then
  AUTH="${ACCOUNT_SID}:${TWILIO_AUTH_TOKEN}"
  echo "Auth: account SID + auth token"
else
  echo "Error: set TWILIO_API_KEY_SID/TWILIO_API_KEY_SECRET or TWILIO_AUTH_TOKEN in .env." >&2
  exit 1
fi

echo "Sending SMS from '${FROM}' to '${TO}' ..."

resp="$(curl -sS -w $'\n%{http_code}' -X POST \
  "https://api.twilio.com/2010-04-01/Accounts/${ACCOUNT_SID}/Messages.json" \
  --data-urlencode "To=${TO}" \
  --data-urlencode "From=${FROM}" \
  --data-urlencode "Body=${MSG}" \
  -u "${AUTH}")"

code="$(printf '%s' "$resp" | tail -n1)"
body="$(printf '%s' "$resp" | sed '$d')"

echo "--- Twilio response (HTTP ${code}) ---"
echo "$body"
echo "--------------------------------------"

if [ "$code" = "201" ]; then
  echo "✅ Message accepted by Twilio."
else
  echo "❌ Send failed (HTTP ${code}). See the message above and https://www.twilio.com/docs/errors" >&2
  exit 1
fi
