# -*- coding: utf-8 -*-
"""
VantageCam Weather & Overlay Generator
v2.7 - Extended EC Alert Support with Flashing Warnings
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

# Parse Camera Heading (Handle N, E, S, W or Degrees)
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
    """Cached icon filename lookup"""
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
    """Cached weather description lookup"""
    if code == 0: return "Clear Sky"
    if code in (1, 2, 3): return "Partly Cloudy"
    if code in (45, 48): return "Foggy"
    if code in (51, 53, 55, 56, 57): return "Drizzle"
    if code in (61, 63, 65, 66, 67, 80, 81, 82): return "Rain"
    if code in (71, 73, 75, 77, 85, 86): return "Snow"
    if code in (95, 96, 99): return "Thunderstorm"
    return "Unknown"

# ================= ALERT TYPE CLASSIFICATION =================
# Environment Canada Alert Types and their severity mapping
# Based on: https://www.canada.ca/en/environment-climate-change/services/types-weather-forecasts-use/public/criteria-alerts.html

def classify_alert(title):
    """
    Classify an alert by type and severity based on Environment Canada conventions.
    Returns: (alert_type, severity, base_color)
    
    Alert Types:
    - WARNING: Imminent or occurring hazardous weather
    - WATCH: Conditions favorable for hazardous weather
    - ADVISORY: Weather conditions that may cause inconvenience
    - STATEMENT: General information, no immediate hazard
    - ENDED: Alert has ended
    """
    title_upper = title.upper()
    
    # Check if alert has ended
    if "ENDED" in title_upper or "END OF" in title_upper:
        return "ENDED", "low", "grey"
    
    # STATEMENTS - Always grey, half size
    statement_keywords = [
        "SPECIAL WEATHER STATEMENT",
        "SPECIAL AIR QUALITY STATEMENT", 
        "PUBLIC INFORMATION STATEMENT",
        "STATEMENT",
    ]
    for kw in statement_keywords:
        if kw in title_upper and "WARNING" not in title_upper and "WATCH" not in title_upper:
            return "STATEMENT", "low", "grey"
    
    # WARNINGS - Check severity by specific type
    if "WARNING" in title_upper:
        # RED (Severe/Extreme) Warnings
        red_warnings = [
            "TORNADO WARNING",
            "SEVERE THUNDERSTORM WARNING", 
            "HURRICANE WARNING",
            "TROPICAL STORM WARNING",
            "BLIZZARD WARNING",
            "WINTER STORM WARNING",
            "ICE STORM WARNING",
            "EXTREME COLD WARNING",
            "HEAT WARNING",
            "STORM SURGE WARNING",
            "TSUNAMI WARNING",
            "FLASH FLOOD WARNING",
            "FLOOD WARNING",
            "DUST STORM WARNING",
            "AVALANCHE WARNING",
            "ARCTIC OUTFLOW WARNING",
        ]
        for rw in red_warnings:
            if rw in title_upper:
                return "WARNING", "extreme", "red"
        
        # ORANGE (Moderate) Warnings  
        orange_warnings = [
            "FREEZING RAIN WARNING",
            "FREEZING DRIZZLE WARNING",
            "FOG WARNING",
            "WIND WARNING",
            "RAINFALL WARNING",
            "SNOWFALL WARNING",
            "FROST WARNING",
            "SNOW SQUALL WARNING",
            "LAKE EFFECT SNOW WARNING",
        ]
        for ow in orange_warnings:
            if ow in title_upper:
                return "WARNING", "moderate", "orange"
        
        # YELLOW (Minor) Warnings - catch-all for other warnings
        return "WARNING", "minor", "yellow"
    
    # WATCHES - Check severity by specific type
    if "WATCH" in title_upper:
        # RED Watches
        red_watches = [
            "TORNADO WATCH",
            "SEVERE THUNDERSTORM WATCH",
            "HURRICANE WATCH",
            "TROPICAL STORM WATCH",
            "TSUNAMI WATCH",
        ]
        for rw in red_watches:
            if rw in title_upper:
                return "WATCH", "extreme", "red"
        
        # ORANGE Watches
        orange_watches = [
            "WINTER STORM WATCH",
            "BLIZZARD WATCH",
            "ICE STORM WATCH",
            "FLASH FLOOD WATCH",
            "FLOOD WATCH",
            "EXTREME COLD WATCH",
        ]
        for ow in orange_watches:
            if ow in title_upper:
                return "WATCH", "moderate", "orange"
        
        # YELLOW Watches - catch-all
        return "WATCH", "minor", "yellow"
    
    # ADVISORIES
    if "ADVISORY" in title_upper:
        # Orange advisories
        if any(x in title_upper for x in ["WIND", "FROST", "FREEZE", "FOG", "HEAT"]):
            return "ADVISORY", "moderate", "orange"
        return "ADVISORY", "minor", "yellow"
    
    # Default fallback - treat unknown as moderate warning
    return "WARNING", "moderate", "orange"


def get_alert_colors(alert_type, severity, base_color):
    """
    Get the RGBA colors for an alert based on type and severity.
    
    Returns: (bg_rgba, text_fill, border_color, is_watch_pattern)
    
    Per the Environment Canada chart:
    - Warnings/Advisories: Solid color fill
    - Watches: Checkered/hatched pattern (we use dashed border)
    - Statements: Grey with dashed pattern
    """
    # Color definitions matching EC chart
    colors = {
        "red": (220, 38, 38, 255),      # Bright red for visibility
        "orange": (249, 115, 22, 255),  # Orange
        "yellow": (250, 204, 21, 255),  # Yellow
        "grey": (107, 114, 128, 255),   # Grey for statements
    }
    
    bg_rgba = colors.get(base_color, colors["orange"])
    
    # Text color: black on yellow/orange for readability, white on red/grey
    if base_color in ["yellow", "orange"]:
        text_fill = "black"
    else:
        text_fill = "white"
    
    # Border for watches (to distinguish from warnings)
    is_watch_pattern = alert_type == "WATCH"
    border_color = "white" if base_color == "red" else "black"
    
    return bg_rgba, text_fill, border_color, is_watch_pattern


# ================= WEATHER GENERATION =================
def get_weather_openmeteo():
    url = f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}&current_weather=true&hourly=relativehumidity_2m,surface_pressure,apparent_temperature,visibility,precipitation_probability&daily=temperature_2m_max,temperature_2m_min&timezone={TIMEZONE}"
    try:
        if DEBUG_MODE: log(f"[Right-Weather] API URL: {url}")
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log(f"[Right-Weather] Error: {e}")
        return None

def create_wind_arrow(degrees, size=50, color="#FFFFFF"):
    """Optimized wind arrow generation"""
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    c = size // 2
    points = [(c, 0), (size, size), (c, int(size * 0.75)), (0, size)]
    draw.polygon(points, fill=color)
    rotation = -(degrees + 180 - CAMERA_HEADING)
    return img.rotate(rotation, resample=Image.BICUBIC, expand=False)

# Icon cache to avoid repeated disk reads
_icon_cache = {}

def get_icon(code, is_day, size=(160, 160)):
    """Load and cache weather icons"""
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
    """Generate weather overlay as PIL Image (not saved to disk)"""
    data = get_weather_openmeteo()
    if not data: 
        return None
    
    try:
        current = data['current_weather']
        hourly = data['hourly']
        daily = data['daily']
        temp = current['temperature']
        wind = current['windspeed']
        wind_deg = current['winddirection']
        code = current['weathercode']
        is_day = current['is_day']
        dt_obj = datetime.datetime.strptime(current['time'], "%Y-%m-%dT%H:%M")
        
        dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
        wind_dir_str = dirs[round(wind_deg / 45) % 8]
        
        curr_hr = dt_obj.hour
        feel = hourly['apparent_temperature'][curr_hr] if hourly else temp
        hum = hourly['relativehumidity_2m'][curr_hr] if hourly else 0
        press = hourly['surface_pressure'][curr_hr] if hourly else 0
        precip = hourly['precipitation_probability'][curr_hr] if hourly else 0
        vis = hourly['visibility'][curr_hr]/1000 if hourly else 10
        high = daily['temperature_2m_max'][0] if daily else temp
        low = daily['temperature_2m_min'][0] if daily else temp

        if DEBUG_MODE:
            log(f"[Right-Weather] Temp={temp}C | Rain={precip}% | Wind={wind}km/h | Heading={CAMERA_HEADING}")

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
    """Legacy function for standalone weather generation"""
    img = generate_weather_layer(width, height)
    if img:
        img.save(output_path, "PNG")
        return True
    return False

# ================= ALERT GENERATION =================
def fetch_title_and_time_from_xml(zone_code):
    """Fetch Title AND Issued Time from XML feed"""
    xml_url = f"https://weather.gc.ca/rss/battleboard/{zone_code}_e.xml"
    if DEBUG_MODE: log(f"[EC-Alert] Fetching XML: {xml_url}")
    try:
        r = requests.get(xml_url, timeout=5)
        if r.status_code != 200: return None, None
        root = ET.fromstring(r.content)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        for entry in root.findall('atom:entry', ns):
            title = entry.find('atom:title', ns).text
            # Extract summary which contains "Issued: ..."
            summary = entry.find('atom:summary', ns).text
            if title and "No watches or warnings" not in title:
                # Return both title and summary (issued time)
                return title, summary
        return None, None
    except: return None, None

async def fetch_ec_alert():
    """Fetch Environment Canada alerts with extended classification"""
    if not HAS_EC: return None, None, None, None, None
    try:
        ec = ECWeather(coordinates=(LAT, LON))
        await ec.update()
        if ec.alerts:
            for a_id, a_data in ec.alerts.items():
                if 'value' in a_data and isinstance(a_data['value'], list) and len(a_data['value']) > 0:
                    alert_item = a_data['value'][0]
                    title = alert_item.get('title', 'ALERT')
                    ec_color = alert_item.get('alertColourLevel', 'red')
                    alert_url = alert_item.get('url', 'N/A')
                    issued_text = None
                    
                    match = re.search(r'([a-z]{2}rm\d+)', alert_url)
                    if match:
                        zone_code = match.group(1)
                        if DEBUG_MODE: log(f"[EC-Alert] Detected Zone: {zone_code}")
                        better_title, better_summary = fetch_title_and_time_from_xml(zone_code)
                        if better_title: title = better_title
                        if better_summary: issued_text = better_summary
                    
                    # Classify the alert
                    alert_type, severity, base_color = classify_alert(title)
                    
                    # Override with EC color if more severe
                    if ec_color == 'red' and base_color != 'red':
                        base_color = 'red'
                        severity = 'extreme'
                    
                    if DEBUG_MODE:
                        log(f"[EC-Alert] Type={alert_type}, Severity={severity}, Color={base_color}")
                    
                    return title.upper(), base_color, issued_text, alert_type, severity
        return None, None, None, None, None
    except Exception as e:
        if DEBUG_MODE: log(f"[EC-Alert] Error: {e}")
        return None, None, None, None, None

def fetch_nws_alert():
    """Fetch NWS alerts with extended classification"""
    try:
        url = f"https://api.weather.gov/alerts/active?point={LAT},{LON}"
        headers = {'User-Agent': 'VantageCamLive/2.7'}
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()
        if 'features' in data and len(data['features']) > 0:
            props = data['features'][0]['properties']
            title = props.get('event', 'WEATHER ALERT').upper()
            nws_severity = props.get('severity', 'Severe')
            
            # Classify using our system
            alert_type, severity, base_color = classify_alert(title)
            
            # Override with NWS severity if more severe
            if nws_severity == 'Extreme':
                base_color = 'red'
                severity = 'extreme'
            elif nws_severity == 'Severe' and base_color not in ['red']:
                base_color = 'orange'
                severity = 'moderate'
            
            # Get issued time if available
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


def draw_watch_pattern(draw, width, height, border_color, line_width=3):
    """Draw a dashed border pattern to indicate a WATCH (vs WARNING)"""
    dash_length = 15
    gap_length = 10
    
    # Top border
    x = 0
    while x < width:
        draw.line([(x, 2), (min(x + dash_length, width), 2)], fill=border_color, width=line_width)
        x += dash_length + gap_length
    
    # Bottom border
    x = 0
    while x < width:
        draw.line([(x, height - 3), (min(x + dash_length, width), height - 3)], fill=border_color, width=line_width)
        x += dash_length + gap_length
    
    # Left border
    y = 0
    while y < height:
        draw.line([(2, y), (2, min(y + dash_length, height))], fill=border_color, width=line_width)
        y += dash_length + gap_length
    
    # Right border
    y = 0
    while y < height:
        draw.line([(width - 3, y), (width - 3, min(y + dash_length, height))], fill=border_color, width=line_width)
        y += dash_length + gap_length


def generate_alert_layer(width=900, height=150, flash_state="on"):
    """
    Generate alert overlay as PIL Image (not saved to disk)
    
    IMPORTANT: Always returns full height image to prevent FFmpeg filter chain issues.
    Statements are rendered in upper portion with transparency below.
    
    Args:
        width: Overlay width
        height: Full height (always used - statements render smaller content but same canvas)
        flash_state: "on" or "off" for flashing red warnings
    
    Returns: (PIL Image, height, needs_flash, is_statement)
    """
    country = detect_country()
    if country == "CA":
        result = asyncio.run(fetch_ec_alert()) if HAS_EC else (None, None, None, None, None)
    else:
        result = fetch_nws_alert()
    
    if result is None or len(result) < 5:
        alert_text, alert_color, issued_text, alert_type, severity = None, None, None, None, None
    else:
        alert_text, alert_color, issued_text, alert_type, severity = result
    
    if not alert_text:
        # Return transparent image, standard height, no flash
        return Image.new('RGBA', (int(width), int(height)), (0, 0, 0, 0)), height, False, False

    try:
        is_statement = (alert_type == "STATEMENT")
        
        # ALWAYS create full-height canvas to keep FFmpeg happy
        # Statements just render smaller content in the top portion
        img = Image.new('RGBA', (int(width), int(height)), (0, 0, 0, 0))
        
        # Get colors based on classification
        bg_rgba, text_fill, border_color, is_watch = get_alert_colors(alert_type, severity, alert_color)
        
        # Check if this is a red warning that needs flashing
        needs_flash = (alert_type == "WARNING" and alert_color == "red")
        
        # For flash "off" state, dim the background
        if needs_flash and flash_state == "off":
            bg_rgba = (80, 15, 15, 255)  # Dark red
        
        # Determine content height (what we actually draw)
        if is_statement:
            content_height = height // 2  # 75px for statements
        else:
            content_height = height  # Full 150px for warnings/watches
        
        # Draw background for content area only
        draw = ImageDraw.Draw(img)
        draw.rectangle([(0, 0), (width, content_height)], fill=bg_rgba)
        
        # Draw watch pattern (dashed border) if it's a WATCH
        if is_watch:
            draw_watch_pattern(draw, width, content_height, border_color)
        
        # Parse region from title
        if ',' in alert_text:
            parts = alert_text.split(',', 1)
            warning_text = parts[0].strip()
            region_text = parts[1].strip()
        else:
            warning_text = alert_text
            region_text = ""

        # Layout depends on alert type
        if is_statement:
            # Compact layout for statements (draws in top half)
            f_icon = get_font(35)
            draw.text((15, 20), "\u26A0", font=f_icon, fill=text_fill)
            
            max_w = width - 80
            font_size = 32
            f_warn = get_font(font_size)
            
            while f_warn.getlength(warning_text) > max_w and font_size > 16:
                font_size -= 2
                f_warn = get_font(font_size)
            
            warn_bbox = draw.textbbox((0, 0), warning_text, font=f_warn)
            warn_w = warn_bbox[2] - warn_bbox[0]
            warn_x = max(60, 450 - (warn_w / 2))
            warn_y = (content_height - (warn_bbox[3] - warn_bbox[1])) // 2
            draw.text((warn_x, warn_y), warning_text, font=f_warn, fill=text_fill)
            
        else:
            # Full layout for warnings/watches
            f_icon = get_font(55)
            draw.text((25, 45), "\u26A0", font=f_icon, fill=text_fill)

            # 1. Region Text (Top)
            if region_text:
                f_region = get_font(24)
                reg_bbox = draw.textbbox((0, 0), region_text, font=f_region)
                reg_w = reg_bbox[2] - reg_bbox[0]
                reg_x = max(90, 490 - (reg_w / 2))
                draw.text((reg_x, 10), region_text, font=f_region, fill=text_fill)

            # 2. Main Warning Text (Middle)
            max_w = width - 110 
            font_size = 55
            f_warn = get_font(font_size)
            
            while f_warn.getlength(warning_text) > max_w and font_size > 20:
                font_size -= 2
                f_warn = get_font(font_size)
                
            warn_bbox = draw.textbbox((0, 0), warning_text, font=f_warn)
            warn_w = warn_bbox[2] - warn_bbox[0]
            warn_x = max(90, 490 - (warn_w / 2))
            warn_y = 45 if region_text else 35
            draw.text((warn_x, warn_y), warning_text, font=f_warn, fill=text_fill)
            
            # 3. Issued Timestamp (Bottom)
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
                draw.text((ts_x, 110), issued_text, font=f_ts, fill=text_fill)

        if DEBUG_MODE: 
            log(f"[Alerts] Generated: Type={alert_type}, Color={alert_color}, Flash={needs_flash}, Statement={is_statement}")
        
        # Always return full height - content is just smaller for statements
        return img, height, needs_flash, is_statement
    
    except Exception as e:
        log(f"[Alerts] Gen Error: {e}")
        return Image.new('RGBA', (int(width), int(height)), (0, 0, 0, 0)), height, False, False

def generate_alerts(output_path, width=900, height=150):
    """Legacy function for standalone alert generation"""
    img, _, _, _ = generate_alert_layer(width, height)
    img.save(output_path, "PNG")
    return True

# ================= COMBINED OVERLAY (UPDATED) =================
def generate_combined(output_path, width=900, weather_height=350, alert_height=150):
    """
    Generate combined weather + alerts overlay as single image.
    
    IMPORTANT: Always outputs fixed-size overlay (500px).
    This prevents FFmpeg filter chain crashes from dynamic resolution changes.
    
    Layout:
    - Full alerts: Alert (150px) + Weather (350px) = 500px
    - Statements: Alert content (75px) + Weather (350px) + padding (75px) = 500px
      The padding is at the bottom so weather sits directly under the statement.
    
    For red warnings, generates two files:
    - output_path: Normal "on" state
    - output_path.replace('.png', '_flash.png'): Dimmed "off" state
    
    Returns: True on success
    """
    # Fixed total height - never changes
    total_height = weather_height + alert_height  # Always 500px
    
    # Generate alert layer (always full height canvas)
    alert_img_on, _, needs_flash, is_statement = generate_alert_layer(width, alert_height, flash_state="on")
    
    # Generate weather layer
    weather_img = generate_weather_layer(width, weather_height)
    
    # Determine where to place weather based on alert type
    if is_statement:
        # Statement has compact content (~75px), place weather right below it
        weather_y = alert_height // 2  # 75px
        # Only use the top portion of the alert image (the actual content)
        content_height = alert_height // 2
    else:
        # Full alert or no alert - weather goes at standard position
        weather_y = alert_height  # 150px
        content_height = alert_height
    
    # Create combined image (ON state)
    combined_on = Image.new('RGBA', (int(width), int(total_height)), (0, 0, 0, 0))
    
    if alert_img_on:
        if is_statement:
            # For statements, crop to just the content area (top 75px)
            alert_content = alert_img_on.crop((0, 0, int(width), content_height))
            combined_on.paste(alert_content, (0, 0), alert_content)
        else:
            combined_on.paste(alert_img_on, (0, 0), alert_img_on)
    
    if weather_img:
        combined_on.paste(weather_img, (0, weather_y), weather_img)
    
    combined_on.save(output_path, "PNG", optimize=True)
    
    # If this is a red warning, generate the flash "off" frame
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
    
    if DEBUG_MODE: 
        log(f"[Combined] Generated {width}x{total_height} overlay (Statement={is_statement}, Weather@y={weather_y}, Flash={needs_flash})")
    
    # Write metadata file for start.sh to read
    meta_path = output_path.replace('.png', '_meta.txt')
    with open(meta_path, 'w') as f:
        f.write(f"height={total_height}\n")
        f.write(f"alert_height={alert_height}\n")
        f.write(f"needs_flash={1 if needs_flash else 0}\n")
        f.write(f"is_statement={1 if is_statement else 0}\n")
    
    return True

# ================= UTILS =================
def generate_blank(output_path, width, height):
    try:
        Image.new('RGBA', (int(width), int(height)), (0, 0, 0, 0)).save(output_path, "PNG")
        return True
    except: return False

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