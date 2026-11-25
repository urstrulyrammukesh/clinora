#!/bin/bash
# Saves the Anthropic API key that is currently COPIED (on your clipboard) into .env.
# The key is never shown on screen. Afterwards the clipboard is cleared for safety.
cd "$(dirname "$0")" || exit 1
KEY="$(pbpaste | tr -d '[:space:]')"
if [ -z "$KEY" ]; then
  echo "NOT SAVED: nothing is copied. Copy the key first (Copy key button), then run this again."; exit 1
fi
case "$KEY" in
  *...*|*…*) echo "NOT SAVED: the copied key is the shortened one (it has '...'). Copy the FULL key."; exit 1 ;;
  sk-ant-*) ;;
  *) echo "NOT SAVED: what's copied doesn't start with sk-ant-. Copy the API key and run this again."; exit 1 ;;
esac
if [ ${#KEY} -lt 60 ]; then
  echo "NOT SAVED: the copied text is too short (${#KEY} characters). A full key is about 100 characters."; exit 1
fi
umask 077
printf 'ANTHROPIC_API_KEY=%s\n' "$KEY" > .env
chmod 600 .env
unset KEY
printf '' | pbcopy
echo "Saved. (Clipboard cleared for safety.) Go back to the chat and say 'saved'."
