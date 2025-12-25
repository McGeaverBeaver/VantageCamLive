#!/bin/bash
#===============================================================================
# YouTube Live Status Redirector
# 
# Automatically redirects visitors to your YouTube live stream when you're live,
# or to a fallback URL when offline. Works reliably on all devices including iOS.
#
# Setup:
#   1. Fill in the configuration variables below
#   2. Make executable: chmod +x live-redirector.sh
#   3. Add to crontab to run every 1-2 minutes:
#      */2 * * * * /path/to/live-redirector.sh
#
#===============================================================================

#-------------------------------------------------------------------------------
# CONFIGURATION - Edit these values
#-------------------------------------------------------------------------------

# Your YouTube channel ID (found in your channel URL)
# Example: https://www.youtube.com/channel/UCwTCdAM6EAIDHKNtGaXsYAg
CHANNEL_ID="YOUR_CHANNEL_ID_HERE"

# Where to redirect when OFFLINE (your website, social media, etc.)
FALLBACK_URL="https://your-fallback-site.com"

# Where to save the generated HTML file
OUTPUT_FILE="/var/www/html/index.html"

# Button colors (hex codes)
LIVE_COLOR="#ff0000"      # Red when live
OFFLINE_COLOR="#444444"   # Gray when offline

# Page title shown in browser tab
PAGE_TITLE="Redirecting..."

#-------------------------------------------------------------------------------
# DO NOT EDIT BELOW THIS LINE
#-------------------------------------------------------------------------------

# Build URLs from channel ID
CHANNEL_URL="https://www.youtube.com/channel/${CHANNEL_ID}"
LIVE_URL="https://www.youtube.com/channel/${CHANNEL_ID}/live"

# Ensure output directory exists
mkdir -p "$(dirname "$OUTPUT_FILE")"

# Fetch YouTube channel page
CONTENT=$(curl -s -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" "$CHANNEL_URL")

# Check for live status
if echo "$CONTENT" | grep -q '"text":"LIVE"'; then
    TARGET="$LIVE_URL"
    STATUS="LIVE"
    COLOR="$LIVE_COLOR"
else
    TARGET="$FALLBACK_URL"
    STATUS="OFFLINE"
    COLOR="$OFFLINE_COLOR"
fi

# Generate HTML redirect page
cat > "$OUTPUT_FILE" <<EOF
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>${PAGE_TITLE}</title>
    <style>
        body {
            background: #111;
            color: #eee;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            margin: 0;
        }
        .status {
            font-size: 1.2em;
            margin-bottom: 10px;
        }
        .btn {
            background: ${COLOR};
            color: white;
            padding: 15px 30px;
            text-decoration: none;
            border-radius: 5px;
            margin-top: 20px;
            transition: opacity 0.2s;
        }
        .btn:hover {
            opacity: 0.9;
        }
    </style>
    <script>
        window.location.replace("${TARGET}");
    </script>
    <meta http-equiv="refresh" content="1;url=${TARGET}">
</head>
<body>
    <p class="status">Status: <strong>${STATUS}</strong></p>
    <p>Redirecting...</p>
    <a href="${TARGET}" class="btn">Click here if not redirected</a>
</body>
</html>
EOF

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Status: ${STATUS} -> ${TARGET}"