#!/bin/bash
# Saves your Anthropic API key into .env. The key is hidden while you type/paste it.
cd "$(dirname "$0")" || exit 1
echo ""
echo "Paste your Anthropic API key (it starts with sk-ant-), then press Enter."
echo "Nothing will appear while you paste - that's normal."
read -r -s -p "Key: " KEY
echo ""
KEY="$(printf '%s' "$KEY" | tr -d '[:space:]')"
if [ -z "$KEY" ]; then
  echo "No key entered. Nothing was changed."
  exit 1
fi
case "$KEY" in
  *...*|*…*)
    echo "NOT SAVED: this is the shortened key (it has '...' in it). Copy the FULL key, shown only right after you create it."
    exit 1 ;;
  sk-ant-*) ;;
  *)
    echo "NOT SAVED: an Anthropic API key starts with sk-ant-. What you pasted is something else."
    exit 1 ;;
esac
if [ ${#KEY} -lt 60 ]; then
  echo "NOT SAVED: this is too short (${#KEY} characters). A full key is about 100 characters."
  exit 1
fi
umask 077
printf 'ANTHROPIC_API_KEY=%s\n' "$KEY" > .env
chmod 600 .env
unset KEY
echo "Saved. You can go back to the chat and say 'done'."
