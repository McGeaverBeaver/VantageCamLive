# -*- coding: utf-8 -*-
"""
VantageCam Weather & Overlay Generator
v3.0 - Strict Color Keyword Priority (Regex)
"""
import requests
import json
import datetime
import os
import sys
import asyncio
import re
import time
import xml.etree.ElementTree as ET
from PIL import Image, ImageDraw, ImageFont
from functools import lru_cache

try:
    from env_canada import ECWeather
    HAS_EC = True
except ImportError:
    HAS_EC = False

# ================= CONFIGURATION =================
LAT = float(os.getenv("WEATHER_LAT", "40.7128"))
LON = float(os.getenv("WEATHER_LON", "-74.0060"))
LOCATION_NAME = os.getenv("WEATHER_LOCATION", "My City")
TIMEZONE = os.getenv("WEATHER_TIMEZONE", "America/Toronto")
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
ICON_DIR = "/config/weather_icons"
LOG_FILE = "/config/weather_debug.log"
DEBUG_MODE = os.getenv("WEATHER_DEBUG", "false").lower() == "true"

# Cache for fonts (avoid reloading)
_font_cache = {}

def get_font(size):
    """Cache fonts to avoid repeated file I/O"""
    if size not in _font_cache:
        try:
            _font_cache[size] = ImageFont.truetype(FONT_PATH, size)
        except:
            _font_cache[size] = ImageFont.load_default()
    return _font_cache[size]

# Parse Camera Heading
def get_heading_degrees():
    val = os.getenv("CAMERA_HEADING", "90").upper().strip()
    headings = {"N": 0, "NE": 45, "E": 90, "SE": 135, "S": 180, "SW": 225, "W": 270, "NW": 315}
    if val in headings:
        return headings[val]
    try:
        return int(val)
    except:
        return 90

CAMERA_HEADING = get_heading_degrees()

def log(message):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full_msg = f"[{timestamp}] {message}"
    print(full_msg)
    if DEBUG_MODE:
        try:
            with open(LOG_FILE, "a") as f:
                f.write(full_msg + "\n")
        except: pass

def detect_country():
    if 41.0 < LAT < 83.0 and -141.0 < LON < -50.0:
        if LAT < 49.0 and -85.0 < LON < -70.0: return "CA"
        if LAT >= 49.0: return "CA"
    return "US"

@lru_cache(maxsize=32)
def get_icon_filename(code, is_day):
    if code == 0: return "clear-day.png" if is_day else "clear-night.png"
    if code in (1, 2): return "partly-cloudy-day.png" if is_day else "partly-cloudy-night.png"
    if code == 3: return "cloudy.png"
    if code in (45, 48): return "fog.png"
    if code in (51, 53, 55, 61, 63, 65, 80, 81, 82): return "rain.png"
    if code in (56, 57, 66, 67): return "sleet.png"
    if code in (71, 73, 75, 77, 85, 86): return "snow.png"
    if code in (95, 96, 99): return "thunderstorm.png"
    return "cloudy.png"

@lru_cache(maxsize=16)
def get_weather_desc(code):
    if code == 0: return "Clear Sky"
    if code in (1, 2, 3): return "Partly Cloudy"
    if code in (45, 48): return "Foggy"
    if code in (51, 53, 55, 56, 57): return "Drizzle"
    if code in (61, 63, 65, 66, 67, 80, 81, 82): return "Rain"
    if code in (71, 73, 75, 77, 85, 86): return "Snow"
    if code in (95, 96, 99): return "Thunderstorm"
    return "Unknown"

# ================= ALERT TYPE CLASSIFICATION =================

def classify_alert(title):
    """
    Classify an alert by type and severity.

    LOGIC V3.0 (STRICT COLOR):
    1. Detect Alert Type (Watch vs Warning) for the pattern (dashed vs solid).
    2. Detect Color explicit keywords (Red/Orange/Yellow).
    3. If Color keyword found -> USE IT.
    4. If no Color keyword -> Guess based on keywords like "Severe", "Tornado".
    """
    title_upper = title.upper()

    # --- STEP 1: Determine Pattern (Watch vs Warning) ---
    if "ENDED" in title_upper or "END OF" in title_upper:
        return "ENDED", "low", "grey"

    if "WATCH" in title_upper:
        alert_type = "WATCH"
    elif "STATEMENT" in title_upper:
        alert_type = "STATEMENT"
    elif "ADVISORY" in title_upper:
        alert_type = "ADVISORY"
    else:
        # Default to Warning (Solid color) if undefined (e.g. "RED BANNANAS")
        alert_type = "WARNING"

    # --- STEP 2: Strict Color Lookup (Regex) ---
    # We use regex \bWORD\b to ensure "REDUCED" doesn't trigger "RED"

    if re.search(r'\bRED\b', title_upper):
        return alert_type, "extreme", "red"

    if re.search(r'\bORANGE\b', title_upper):
        return alert_type, "moderate", "orange"

    if re.search(r'\bYELLOW\b', title_upper):
        return alert_type, "minor", "yellow"

    if re.search(r'\bGREY\b', title_upper) or re.search(r'\bGRAY\b', title_upper):
        return alert_type, "low", "grey"

    # --- STEP 3: Fallback (If no color word exists) ---
    # This runs for US alerts or generic Canadian alerts without color in title

    # Default Color
    color = "orange"
    severity = "moderate"

    if alert_type == "STATEMENT":
        return "STATEMENT", "low", "grey"

    if alert_type == "ADVISORY":
        return "ADVISORY", "minor", "yellow"

    # Keywords for guessing color
    red_keywords = ["TORNADO", "SEVERE THUNDERSTORM", "HURRICANE", "BLIZZARD", "EXTREME COLD", "HEAT", "TSUNAMI"]

    for kw in red_keywords:
        if kw in title_upper:
            return alert_type, "extreme", "red"

    if alert_type == "WATCH":
        # Watches that are usually Orange
        orange_watches = ["WINTER STORM", "SNOW SQUALL", "FLASH FLOOD"]
        for kw in orange_watches:
            if kw in title_upper:
                return "WATCH", "moderate", "orange"
        # Remaining watches default to Yellow
        return "WATCH", "minor", "yellow"

    # Default fall-through
    return alert_type, severity, color


def get_alert_colors(alert_type, severity, base_color):
    """
    Get the RGBA colors for an alert based on type and severity.
    """
    colors = {
        # Official Red: Approx #D02B2B
        "red": (220, 38, 38, 255),

        # Official Orange: #F97316 (Standard Safety Orange)
        "orange": (255, 120, 0, 255),

        # Official Yellow: #FACC15 (Standard Warning Yellow)
        "yellow": (255, 215, 0, 255),

        # Grey
        "grey": (107, 114, 128, 255),
    }

    bg_rgba = colors.get(base_color, colors["orange"])

    # Text color
    if base_color in ["yellow", "orange"]:
        text_fill = "black"
    else:
        text_fill = "white"

    is_watch_pattern = alert_type == "WATCH"
    border_color = "white" if base_color == "red" else "black"

    return bg_rgba, text_fill, border_color, is_watch_pattern


# ================= WEATHER GENERATION =================
def get_weather_openmeteo():
    # Use 'current' for real-time observations instead of hourly forecast data
    # This ensures visibility reflects actual conditions during rapidly changing weather
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={LAT}&longitude={LON}"
        f"&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,"
        f"surface_pressure,wind_speed_10m,wind_direction_10m,is_day,visibility,precipitation"
        f"&hourly=precipitation_probability"
        f"&daily=temperature_2m_max,temperature_2m_min"
        f"&timezone={TIMEZONE}"
    )
    try:
        if DEBUG_MODE: log(f"[Right-Weather] API URL: {url}")
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log(f"[Right-Weather] Error: {e}")
        return None

def create_wind_arrow(degrees, size=50, color="#FFFFFF"):
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    c = size // 2
    points = [(c, 0), (size, size), (c, int(size * 0.75)), (0, size)]
    draw.polygon(points, fill=color)
    rotation = -(degrees + 180 - CAMERA_HEADING)
    return img.rotate(rotation, resample=Image.BICUBIC, expand=False)

_icon_cache = {}

def get_icon(code, is_day, size=(160, 160)):
    cache_key = (code, is_day, size)
    if cache_key not in _icon_cache:
        icon_path = os.path.join(ICON_DIR, get_icon_filename(code, is_day))
        if os.path.exists(icon_path):
            try:
                with Image.open(icon_path) as icon:
                    _icon_cache[cache_key] = icon.convert("RGBA").resize(size, Image.Resampling.LANCZOS).copy()
            except:
                _icon_cache[cache_key] = None
        else:
            _icon_cache[cache_key] = None
    return _icon_cache.get(cache_key)

def generate_weather_layer(width=900, height=350):
    data = get_weather_openmeteo()
    if not data:
        return None

    try:
        current = data.get('current', {})
        hourly = data.get('hourly', {})
        daily = data.get('daily', {})

        # Current observations (real-time data)
        temp = current.get('temperature_2m', 0)
        wind = current.get('wind_speed_10m', 0)
        wind_deg = current.get('wind_direction_10m', 0)
        code = current.get('weather_code', 0)
        is_day = current.get('is_day', 1)

        # Parse time from current data
        time_str = current.get('time', '')
        try:
            dt_obj = datetime.datetime.fromisoformat(time_str)
        except:
            dt_obj = datetime.datetime.now()

        dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
        wind_dir_str = dirs[round(wind_deg / 45) % 8]

        # Use CURRENT observations for real-time accuracy (especially visibility!)
        feel = current.get('apparent_temperature', temp)
        hum = current.get('relative_humidity_2m', 0)
        press = current.get('surface_pressure', 0)

        # Visibility from CURRENT data - converts meters to km
        # This reflects actual current conditions, not forecast
        vis_meters = current.get('visibility', 10000)
        vis = vis_meters / 1000  # Convert to km

        # Precipitation probability still from hourly (forecast)
        curr_hr = dt_obj.hour
        precip = 0
        if hourly and 'precipitation_probability' in hourly:
            hourly_times = hourly.get('time', [])
            for i, t in enumerate(hourly_times):
                try:
                    if datetime.datetime.fromisoformat(t).hour == curr_hr:
                        precip = hourly['precipitation_probability'][i]
                        break
                except:
                    pass

        high = daily['temperature_2m_max'][0] if daily and 'temperature_2m_max' in daily else temp
        low = daily['temperature_2m_min'][0] if daily and 'temperature_2m_min' in daily else temp

        if DEBUG_MODE:
            log(f"[Right-Weather] Temp={temp}C | Rain={precip}% | Wind={wind}km/h | Vis={vis:.1f}km | Heading={CAMERA_HEADING}")

        img = Image.new('RGBA', (int(width), int(height)), (0, 0, 0, 180))
        draw = ImageDraw.Draw(img)

        f_huge = get_font(110)
        f_large = get_font(40)
        f_med = get_font(26)
        f_head = get_font(28)

        draw.text((30, 20), LOCATION_NAME.upper(), font=f_head, fill="#CCCCCC")
        draw.text((int(width) - 260, 20), f"UPDATED: {dt_obj.strftime('%H:%M')}", font=f_head, fill="#CCCCCC")
        draw.text((30, 70), "{:.1f}\u00b0".format(temp), font=f_huge, fill="white")
        draw.text((35, 195), get_weather_desc(code), font=f_large, fill="#E6E6E6")

        icon = get_icon(code, is_day)
        if icon:
            img.paste(icon, (300, 40), icon)

        draw.text((520, 80), "H:{:.0f}\u00b0 L:{:.0f}\u00b0".format(high, low), font=f_large, fill="#DDDDDD")
        draw.text((520, 130), "Feels: {:.0f}\u00b0".format(feel), font=f_large, fill="#DDDDDD")
        draw.text((520, 180), f"Rain: {precip}%", font=f_large, fill="#AACCFF")

        arrow = create_wind_arrow(wind_deg, 45, "#FFFFFF")
        img.paste(arrow, (30, 270), arrow)
        draw.text((90, 280), f"{wind}km/h {wind_dir_str}   {hum}%   {int(press)}hPa   Vis:{vis:.1f}km", font=f_med, fill="#EEEEEE")

        if DEBUG_MODE: log(f"[Right-Weather] Generated successfully.")
        return img
    except Exception as e:
        log(f"[Right-Weather] Error: {e}")
        return None

def generate_weather(output_path, width=900, height=350):
    img = generate_weather_layer(width, height)
    if img:
        img.save(output_path, "PNG")
        return True
    return False

# ================= ALERT GENERATION =================
def fetch_all_alerts_from_xml(zone_code):
    """
    Fetch ALL alerts from Environment Canada XML feed.
    Returns list of (title, summary/issued_text) tuples.
    """
    xml_url = f"https://weather.gc.ca/rss/battleboard/{zone_code}_e.xml"
    if DEBUG_MODE: log(f"[EC-Alert] Fetching XML: {xml_url}")
    try:
        r = requests.get(xml_url, timeout=5)
        if r.status_code != 200:
            return []
        root = ET.fromstring(r.content)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}

        alerts = []
        for entry in root.findall('atom:entry', ns):
            title_elem = entry.find('atom:title', ns)
            summary_elem = entry.find('atom:summary', ns)

            if title_elem is not None:
                title = title_elem.text
                summary = summary_elem.text if summary_elem is not None else None

                if title and "No watches or warnings" not in title:
                    alerts.append((title, summary))

        return alerts
    except Exception as e:
        if DEBUG_MODE: log(f"[EC-Alert] XML fetch error: {e}")
        return []

def fetch_title_and_time_from_xml(zone_code):
    """Legacy function - returns only first alert for backward compatibility"""
    alerts = fetch_all_alerts_from_xml(zone_code)
    if alerts:
        return alerts[0]
    return None, None

async def fetch_ec_alerts():
    """
    Fetch ALL Environment Canada alerts for the location.
    Returns list of tuples: [(title, color, issued_text, alert_type, severity), ...]
    """
    if not HAS_EC:
        return []
    try:
        ec = ECWeather(coordinates=(LAT, LON))
        await ec.update()

        if not ec.alerts:
            return []

        zone_code = None
        # First, find the zone code from any alert URL
        for a_id, a_data in ec.alerts.items():
            if 'value' in a_data and isinstance(a_data['value'], list) and len(a_data['value']) > 0:
                alert_url = a_data['value'][0].get('url', '')
                match = re.search(r'([a-z]{2}rm\d+)', alert_url)
                if match:
                    zone_code = match.group(1)
                    break

        if not zone_code:
            if DEBUG_MODE: log("[EC-Alert] No zone code found in alerts")
            return []

        if DEBUG_MODE: log(f"[EC-Alert] Detected Zone: {zone_code}")

        # Fetch ALL alerts from XML (authoritative source with proper titles/times)
        xml_alerts = fetch_all_alerts_from_xml(zone_code)

        if not xml_alerts:
            if DEBUG_MODE: log("[EC-Alert] No alerts in XML feed")
            return []

        # Process each alert
        processed_alerts = []
        for title, issued_text in xml_alerts:
            alert_type, severity, base_color = classify_alert(title)

            if DEBUG_MODE:
                log(f"[EC-Alert] Title: {title} -> Type={alert_type}, Color={base_color}")

            processed_alerts.append((
                title.upper(),
                base_color,
                issued_text,
                alert_type,
                severity
            ))

        return processed_alerts

    except Exception as e:
        if DEBUG_MODE: log(f"[EC-Alert] Error: {e}")
        return []

async def fetch_ec_alert():
    """Legacy function - returns only first alert for backward compatibility"""
    alerts = await fetch_ec_alerts()
    if alerts:
        return alerts[0]
    return None, None, None, None, None

def fetch_nws_alert():
    try:
        url = f"https://api.weather.gov/alerts/active?point={LAT},{LON}"
        headers = {'User-Agent': 'VantageCamLive/3.0'}
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()
        if 'features' in data and len(data['features']) > 0:
            props = data['features'][0]['properties']
            title = props.get('event', 'WEATHER ALERT').upper()
            nws_severity = props.get('severity', 'Severe')

            alert_type, severity, base_color = classify_alert(title)

            if nws_severity == 'Extreme':
                base_color = 'red'
                severity = 'extreme'
            elif nws_severity == 'Severe' and base_color not in ['red']:
                base_color = 'orange'
                severity = 'moderate'

            issued_text = None
            onset = props.get('onset')
            if onset:
                try:
                    dt = datetime.datetime.fromisoformat(onset.replace('Z', '+00:00'))
                    issued_text = f"Issued: {dt.strftime('%I:%M %p %Z %A')}"
                except:
                    pass

            return title, base_color, issued_text, alert_type, severity
        return None, None, None, None, None
    except Exception as e:
        if DEBUG_MODE: log(f"[NWS-Alert] Error: {e}")
        return None, None, None, None, None

def draw_watch_pattern(draw, x_offset, y_offset, width, height, border_color, line_width=3):
    """Draw dashed border for WATCH alerts within a specific region"""
    dash_length = 15
    gap_length = 10

    # Top border
    x = x_offset
    while x < x_offset + width:
        draw.line([(x, y_offset + 2), (min(x + dash_length, x_offset + width), y_offset + 2)],
                  fill=border_color, width=line_width)
        x += dash_length + gap_length

    # Bottom border
    x = x_offset
    while x < x_offset + width:
        draw.line([(x, y_offset + height - 3), (min(x + dash_length, x_offset + width), y_offset + height - 3)],
                  fill=border_color, width=line_width)
        x += dash_length + gap_length

    # Left border
    y = y_offset
    while y < y_offset + height:
        draw.line([(x_offset + 2, y), (x_offset + 2, min(y + dash_length, y_offset + height))],
                  fill=border_color, width=line_width)
        y += dash_length + gap_length

    # Right border
    y = y_offset
    while y < y_offset + height:
        draw.line([(x_offset + width - 3, y), (x_offset + width - 3, min(y + dash_length, y_offset + height))],
                  fill=border_color, width=line_width)
        y += dash_length + gap_length

def draw_single_alert(draw, img, alert_data, y_offset, width, row_height, flash_state="on", show_region=True):
    """
    Draw a single alert row.
    Returns: needs_flash (bool)
    """
    alert_text, alert_color, issued_text, alert_type, severity = alert_data

    bg_rgba, text_fill, border_color, is_watch = get_alert_colors(alert_type, severity, alert_color)
    needs_flash = (alert_type == "WARNING" and alert_color == "red")

    if needs_flash and flash_state == "off":
        bg_rgba = (80, 15, 15, 255)

    # Parse alert text for warning type and region
    if ',' in alert_text:
        parts = alert_text.split(',', 1)
        warning_text = parts[0].strip()
        region_text = parts[1].strip()
    else:
        warning_text = alert_text
        region_text = ""

    # Draw background rectangle
    draw.rectangle([(0, y_offset), (width, y_offset + row_height)], fill=bg_rgba)

    # Draw watch pattern if needed
    if is_watch:
        draw_watch_pattern(draw, 0, y_offset, width, row_height, border_color)

    # Determine layout based on row height
    is_compact = (row_height < 100)  # Half-height mode

    if is_compact:
        # COMPACT LAYOUT (for stacked alerts)
        # Icon on left, warning text centered, issued time on right
        f_icon = get_font(35)
        draw.text((15, y_offset + (row_height - 35) // 2), "\u26A0", font=f_icon, fill=text_fill)

        # Warning text (centered)
        max_w = width - 200  # Leave room for icon and timestamp
        font_size = 32
        f_warn = get_font(font_size)

        while f_warn.getlength(warning_text) > max_w and font_size > 18:
            font_size -= 2
            f_warn = get_font(font_size)

        warn_bbox = draw.textbbox((0, 0), warning_text, font=f_warn)
        warn_w = warn_bbox[2] - warn_bbox[0]
        warn_x = max(60, (width - warn_w) // 2)
        warn_y = y_offset + (row_height - font_size) // 2
        draw.text((warn_x, warn_y), warning_text, font=f_warn, fill=text_fill)

        # Issued time (right side, smaller)
        if issued_text:
            issued_text = re.sub(r'<[^>]+>', '', issued_text).strip()
            time_match = re.search(r'(\d{1,2}:\d{2}\s*(?:AM|PM)?)', issued_text, re.IGNORECASE)
            if time_match:
                short_time = time_match.group(1)
            else:
                short_time = ""

            if short_time:
                f_ts = get_font(18)
                ts_bbox = draw.textbbox((0, 0), short_time, font=f_ts)
                ts_w = ts_bbox[2] - ts_bbox[0]
                draw.text((width - ts_w - 15, y_offset + (row_height - 18) // 2),
                          short_time, font=f_ts, fill=text_fill)
    else:
        # FULL LAYOUT (single alert, original style)
        f_icon = get_font(55)
        draw.text((25, y_offset + 45), "\u26A0", font=f_icon, fill=text_fill)

        if show_region and region_text:
            f_region = get_font(24)
            reg_bbox = draw.textbbox((0, 0), region_text, font=f_region)
            reg_w = reg_bbox[2] - reg_bbox[0]
            reg_x = max(90, 490 - (reg_w / 2))
            draw.text((reg_x, y_offset + 10), region_text, font=f_region, fill=text_fill)

        max_w = width - 110
        font_size = 55
        f_warn = get_font(font_size)

        while f_warn.getlength(warning_text) > max_w and font_size > 20:
            font_size -= 2
            f_warn = get_font(font_size)

        warn_bbox = draw.textbbox((0, 0), warning_text, font=f_warn)
        warn_w = warn_bbox[2] - warn_bbox[0]
        warn_x = max(90, 490 - (warn_w / 2))
        warn_y = y_offset + (45 if (show_region and region_text) else 35)
        draw.text((warn_x, warn_y), warning_text, font=f_warn, fill=text_fill)

        if issued_text:
            issued_text = re.sub(r'<[^>]+>', '', issued_text).strip()
            ts_size = 24
            f_ts = get_font(ts_size)
            while f_ts.getlength(issued_text) > max_w and ts_size > 14:
                ts_size -= 2
                f_ts = get_font(ts_size)

            ts_bbox = draw.textbbox((0, 0), issued_text, font=f_ts)
            ts_w = ts_bbox[2] - ts_bbox[0]
            ts_x = max(90, 490 - (ts_w / 2))
            draw.text((ts_x, y_offset + 110), issued_text, font=f_ts, fill=text_fill)

    return needs_flash

def generate_alert_layer(width=900, height=150, flash_state="on"):
    """
    Generate alert overlay supporting multiple stacked alerts.

    Single alert: Full height display
    Multiple alerts:
      - Region header (shared) at top
      - Half-height alert rows stacked below
    """
    country = detect_country()

    # Fetch ALL alerts
    if country == "CA":
        alerts = asyncio.run(fetch_ec_alerts()) if HAS_EC else []
    else:
        # NWS single alert (legacy) - wrap in list
        single_result = fetch_nws_alert()
        if single_result and single_result[0]:
            alerts = [single_result]
        else:
            alerts = []

    # No alerts - return transparent image
    if not alerts:
        return Image.new('RGBA', (int(width), int(height)), (0, 0, 0, 0)), height, False, False

    try:
        # Check if any alert is a statement (compact display)
        has_statement = any(a[3] == "STATEMENT" for a in alerts)

        # Single alert - use original full layout
        if len(alerts) == 1:
            alert_data = alerts[0]
            alert_text, alert_color, issued_text, alert_type, severity = alert_data

            is_statement = (alert_type == "STATEMENT")
            content_height = height // 2 if is_statement else height

            img = Image.new('RGBA', (int(width), int(height)), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)

            needs_flash = draw_single_alert(draw, img, alert_data, 0, width, content_height,
                                            flash_state, show_region=True)

            if DEBUG_MODE:
                log(f"[Alerts] Single alert: Type={alert_type}, Color={alert_color}, Flash={needs_flash}")

            return img, height, needs_flash, is_statement

        # MULTIPLE ALERTS - Stack them!
        # Layout: Region header (30px) + alert rows (remaining space split evenly)

        img = Image.new('RGBA', (int(width), int(height)), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Extract shared region from first alert
        first_alert_text = alerts[0][0]
        if ',' in first_alert_text:
            region_text = first_alert_text.split(',', 1)[1].strip()
        else:
            region_text = ""

        # Draw region header bar (dark semi-transparent)
        header_height = 30
        draw.rectangle([(0, 0), (width, header_height)], fill=(30, 30, 30, 220))

        if region_text:
            f_region = get_font(22)
            reg_bbox = draw.textbbox((0, 0), region_text, font=f_region)
            reg_w = reg_bbox[2] - reg_bbox[0]
            reg_x = (width - reg_w) // 2
            draw.text((reg_x, 4), region_text, font=f_region, fill="white")

        # Calculate row height for alert panels
        remaining_height = height - header_height
        num_alerts = min(len(alerts), 3)  # Cap at 3 alerts max to keep readable
        row_height = remaining_height // num_alerts

        # Track if any alert needs flash
        any_needs_flash = False

        # Draw each alert row
        for i, alert_data in enumerate(alerts[:num_alerts]):
            y_offset = header_height + (i * row_height)
            needs_flash = draw_single_alert(draw, img, alert_data, y_offset, width, row_height,
                                            flash_state, show_region=False)
            if needs_flash:
                any_needs_flash = True

            if DEBUG_MODE:
                log(f"[Alerts] Stacked alert {i+1}: {alert_data[0][:30]}... Color={alert_data[1]}")

        if DEBUG_MODE:
            log(f"[Alerts] Generated {num_alerts} stacked alerts, Flash={any_needs_flash}")

        return img, height, any_needs_flash, False

    except Exception as e:
        log(f"[Alerts] Gen Error: {e}")
        import traceback
        traceback.print_exc()
        return Image.new('RGBA', (int(width), int(height)), (0, 0, 0, 0)), height, False, False

def generate_alerts(output_path, width=900, height=150):
    img, _, _, _ = generate_alert_layer(width, height)
    img.save(output_path, "PNG")
    return True

def generate_combined(output_path, width=900, weather_height=350, alert_height=150):
    total_height = weather_height + alert_height
    alert_img_on, _, needs_flash, is_statement = generate_alert_layer(width, alert_height, flash_state="on")
    weather_img = generate_weather_layer(width, weather_height)

    if is_statement:
        weather_y = alert_height // 2
        content_height = alert_height // 2
    else:
        weather_y = alert_height
        content_height = alert_height

    combined_on = Image.new('RGBA', (int(width), int(total_height)), (0, 0, 0, 0))

    if alert_img_on:
        if is_statement:
            alert_content = alert_img_on.crop((0, 0, int(width), content_height))
            combined_on.paste(alert_content, (0, 0), alert_content)
        else:
            combined_on.paste(alert_img_on, (0, 0), alert_img_on)

    if weather_img:
        combined_on.paste(weather_img, (0, weather_y), weather_img)

    combined_on.save(output_path, "PNG", optimize=True)

    if needs_flash:
        alert_img_off, _, _, _ = generate_alert_layer(width, alert_height, flash_state="off")
        combined_off = Image.new('RGBA', (int(width), int(total_height)), (0, 0, 0, 0))
        if alert_img_off:
            combined_off.paste(alert_img_off, (0, 0), alert_img_off)
        if weather_img:
            combined_off.paste(weather_img, (0, alert_height), weather_img)

        flash_path = output_path.replace('.png', '_flash.png')
        combined_off.save(flash_path, "PNG", optimize=True)
        if DEBUG_MODE: log(f"[Combined] Generated flash frame: {flash_path}")

    meta_path = output_path.replace('.png', '_meta.txt')
    with open(meta_path, 'w') as f:
        f.write(f"height={total_height}\n")
        f.write(f"alert_height={alert_height}\n")
        f.write(f"needs_flash={1 if needs_flash else 0}\n")
        f.write(f"is_statement={1 if is_statement else 0}\n")

    return True

def generate_blank(output_path, width, height):
    try:
        Image.new('RGBA', (int(width), int(height)), (0, 0, 0, 0)).save(output_path, "PNG")
        return True
    except: return False

def generate_fallback(output_path, width=2560, height=1440, message="We'll Be Right Back"):
    """
    Generate a professional "We'll be right back" screen.
    Used when RTSP source is unavailable to keep YouTube stream alive.
    """
    try:
        width, height = int(width), int(height)

        # Dark gradient background
        img = Image.new('RGB', (width, height), (20, 20, 30))
        draw = ImageDraw.Draw(img)

        # Add subtle gradient effect (darker at edges)
        for i in range(height // 2):
            alpha = int(30 * (1 - i / (height // 2)))
            draw.rectangle([0, i, width, i+1], fill=(20 - alpha//2, 20 - alpha//2, 30 - alpha//2))
            draw.rectangle([0, height-i-1, width, height-i], fill=(20 - alpha//2, 20 - alpha//2, 30 - alpha//2))

        # Main message
        try:
            font_large = ImageFont.truetype(FONT_PATH, 120)
            font_small = ImageFont.truetype(FONT_PATH, 48)
        except:
            font_large = ImageFont.load_default()
            font_small = ImageFont.load_default()

        # Center the main message
        bbox = draw.textbbox((0, 0), message, font=font_large)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x = (width - text_w) // 2
        y = (height - text_h) // 2 - 50

        # Draw shadow
        draw.text((x + 4, y + 4), message, font=font_large, fill=(0, 0, 0))
        # Draw main text
        draw.text((x, y), message, font=font_large, fill=(255, 255, 255))

        # Subtitle
        subtitle = "Experiencing technical difficulties - stream will resume shortly"
        bbox_sub = draw.textbbox((0, 0), subtitle, font=font_small)
        sub_w = bbox_sub[2] - bbox_sub[0]
        x_sub = (width - sub_w) // 2
        y_sub = y + text_h + 60

        draw.text((x_sub + 2, y_sub + 2), subtitle, font=font_small, fill=(0, 0, 0))
        draw.text((x_sub, y_sub), subtitle, font=font_small, fill=(180, 180, 180))

        # Add location name if available
        if LOCATION_NAME:
            bbox_loc = draw.textbbox((0, 0), LOCATION_NAME, font=font_small)
            loc_w = bbox_loc[2] - bbox_loc[0]
            x_loc = (width - loc_w) // 2
            y_loc = y - 100
            draw.text((x_loc, y_loc), LOCATION_NAME, font=font_small, fill=(100, 150, 255))

        # Add timestamp
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        bbox_time = draw.textbbox((0, 0), timestamp, font=font_small)
        time_w = bbox_time[2] - bbox_time[0]
        draw.text((width - time_w - 40, height - 80), timestamp, font=font_small, fill=(100, 100, 100))

        img.save(output_path, "PNG", optimize=True)
        return True
    except Exception as e:
        log(f"[Fallback] Error generating fallback image: {e}")
        # Create a simple black image as ultimate fallback
        try:
            Image.new('RGB', (int(width), int(height)), (20, 20, 30)).save(output_path, "PNG")
            return True
        except:
            return False

def process_ad(input_path, output_path, target_w, target_h):
    try:
        with Image.open(input_path) as im:
            target_w, target_h = int(target_w), int(target_h)
            im = im.convert("RGBA")
            ratio = min(target_w / im.width, target_h / im.height)
            new_w, new_h = int(im.width * ratio), int(im.height * ratio)
            im_resized = im.resize((new_w, new_h), Image.Resampling.LANCZOS)
            new_im = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
            new_im.paste(im_resized, ((target_w - new_w) // 2, 0))
            new_im.save(output_path, "PNG", optimize=True)
            return True
    except Exception as e:
        log(f"[Ad] Error processing {input_path}: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) < 3: sys.exit(1)
    mode = sys.argv[1]
    output = sys.argv[2]

    if mode == "weather":
        generate_weather(output)
    elif mode == "alerts":
        generate_alerts(output)
    elif mode == "combined":
        generate_combined(output)
    elif mode == "blank":
        generate_blank(output, sys.argv[3], sys.argv[4])
    elif mode == "ad":
        process_ad(sys.argv[3], output, sys.argv[4], sys.argv[5])
    elif mode == "fallback":
        # Generate "We'll be right back" screen
        # Usage: python weather.py fallback /path/to/output.png [width] [height] [message]
        width = int(sys.argv[3]) if len(sys.argv) > 3 else 2560
        height = int(sys.argv[4]) if len(sys.argv) > 4 else 1440
        message = sys.argv[5] if len(sys.argv) > 5 else "We'll Be Right Back"
        generate_fallback(output, width, height, message)
