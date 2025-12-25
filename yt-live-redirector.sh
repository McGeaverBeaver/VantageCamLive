#!/bin/bash

# ==============================================================================
# SCRIPT: Universal YouTube Live Redirector
# DESCRIPTION: Checks if a YouTube channel is live. 
#              - If LIVE: Generates an HTML file redirecting to the stream.
#              - If OFFLINE: Generates an HTML file redirecting to a fallback URL.
#
# USAGE: 
#   1. Edit the "CONFIGURATION" section below.
#   2. Run script via Cron (e.g., every 5 mins) or Unraid User Scripts.
# ==============================================================================

# --- 1. CONFIGURATION (REQUIRED) ---

# Your YouTube Channel ID (Found in your URL: youtube.com/channel/UC-xxxx...)
YT_CHANNEL_ID="YOUR_CHANNEL_ID_HERE"

# The URL to send visitors to when the stream is OFFLINE
FALLBACK_URL="https://your-website.com"

# The full path where the HTML file should be saved
# Example for Unraid/Swag: "/mnt/cache/appdata/swag/config/www/live/index.html"
OUTPUT_FILE="/path/to/your/webroot/index.html"

# --- 2. CUSTOMIZATION (OPTIONAL) ---

# Title that appears in the browser tab
PAGE_TITLE="Live Stream Redirect"

# Message shown while redirecting to the stream
MSG_LIVE="Stream is LIVE! Redirecting you now..."

# Message shown while redirecting to the fallback website
MSG_OFFLINE="Stream is currently offline. Taking you to the gallery..."

# --- 3. INTERNAL LOGIC (DO NOT EDIT BELOW) ---

CHANNEL_URL="https://www.youtube.com/channel/${YT_CHANNEL_ID}"
LIVE_URL="https://www.youtube.com/channel/${YT_CHANNEL_ID}/live"

# Ensure the directory exists before writing
if ! mkdir -p "$(dirname "$OUTPUT_FILE")"; then
    echo "Error: Could not create directory for $OUTPUT_FILE"
    echo "Check your permissions or file path."
    exit 1
fi

# Fetch YouTube Channel Page
echo "Checking status for Channel ID: $YT_CHANNEL_ID..."
CONTENT=$(curl -s -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" "$CHANNEL_URL")

# Logic: Look for the specific "text":"LIVE" marker in the HTML source
if echo "$CONTENT" | grep -q '"text":"LIVE"'; then
    TARGET="$LIVE_URL"
    STATUS="LIVE"
    COLOR="#ff0000" # YouTube Red
    MESSAGE="$MSG_LIVE"
    echo " -> Channel is LIVE. Targeting: $LIVE_URL"
else
    TARGET="$FALLBACK_URL"
    STATUS="OFFLINE"
    COLOR="#666666" # Grey
    MESSAGE="$MSG_OFFLINE"
    echo " -> Channel is OFFLINE. Targeting: $FALLBACK_URL"
fi

# Generate the HTML Redirect File
cat > "$OUTPUT_FILE" <<EOF
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>${PAGE_TITLE}</title>
    <meta http-equiv="refresh" content="0;url=${TARGET}">
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{background:#111;color:#eee;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:20px}
        .status{font-size:1.2rem;margin-bottom:10px}
        .badge{display:inline-block;background:${COLOR};padding:4px 12px;border-radius:4px;font-weight:bold;font-size:0.9rem;color:#fff}
        .message{color:#aaa;margin:15px 0}
        .btn{display:inline-block;background:${COLOR};color:#fff;padding:12px 24px;text-decoration:none;border-radius:6px;font-weight:500;transition:opacity 0.2s}
        .btn:hover{opacity:0.85}
    </style>
</head>
<body>
    <p class="status">Status: <span class="badge">${STATUS}</span></p>
    <p class="message">${MESSAGE}</p>
    <a href="${TARGET}" class="btn">Click here if not redirected</a>
    <script>window.location.replace("${TARGET}");</script>
</body>
</html>
EOF

echo "Success: Updated $OUTPUT_FILE"
