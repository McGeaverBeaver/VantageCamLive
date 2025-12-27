# -*- coding: utf-8 -*-
import requests
import json
import datetime
import os
import sys
import asyncio
import re
import xml.etree.ElementTree as ET
from PIL import Image, ImageDraw, ImageFont

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

# Parse Camera Heading (Handle N, E, S, W or Degrees)
def get_heading_degrees():
    val = os.getenv("CAMERA_HEADING", "90").upper().strip()
    if val == "N": return 0
    if val == "NE": return 45
    if val == "E": return 90
    if val == "SE": return 135
    if val == "S": return 180
    if val == "SW": return 225
    if val == "W": return 270
    if val == "NW": return 315
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

def get_icon_filename(code, is_day):
    if code == 0: return "clear-day.png" if is_day else "clear-night.png"
    if code in [1, 2]: return "partly-cloudy-day.png" if is_day else "partly-cloudy-night.png"
    if code == 3: return "cloudy.png"
    if code in [45, 48]: return "fog.png"
    if code in [51, 53, 55, 61, 63, 65, 80, 81, 82]: return "rain.png"
    if code in [56, 57, 66, 67]: return "sleet.png"
    if code in [71, 73, 75, 77, 85, 86]: return "snow.png"
    if code in [95, 96, 99]: return "thunderstorm.png"
    return "cloudy.png"

# ================= WEATHER GENERATION =================
def get_weather_openmeteo():
    url = f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}&current_weather=true&hourly=relativehumidity_2m,surface_pressure,apparent_temperature,visibility,precipitation_probability&daily=temperature_2m_max,temperature_2m_min&timezone={TIMEZONE}"
    try:
        if DEBUG_MODE: log(f"[Right-Weather] API URL: {url}")
        return requests.get(url, timeout=10).json()
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

def generate_weather(output_path, width=900, height=350):
    data = get_weather_openmeteo()
    if not data: return False
    
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

        def get_desc(c):
            if c == 0: return "Clear Sky"
            if c in [1, 2, 3]: return "Partly Cloudy"
            if c in [45, 48]: return "Foggy"
            if c in [51, 53, 55, 56, 57]: return "Drizzle"
            if c in [61, 63, 65, 66, 67, 80, 81, 82]: return "Rain"
            if c in [71, 73, 75, 77, 85, 86]: return "Snow"
            if c in [95, 96, 99]: return "Thunderstorm"
            return "Unknown"

        img = Image.new('RGBA', (int(width), int(height)), (0, 0, 0, 180))
        draw = ImageDraw.Draw(img)
        
        try:
            f_huge = ImageFont.truetype(FONT_PATH, 110)
            f_large = ImageFont.truetype(FONT_PATH, 40)
            f_med = ImageFont.truetype(FONT_PATH, 26)
            f_head = ImageFont.truetype(FONT_PATH, 28)
        except:
            f_huge = f_large = f_med = f_head = ImageFont.load_default()

        draw.text((30, 20), LOCATION_NAME.upper(), font=f_head, fill="#CCCCCC")
        draw.text((int(width) - 260, 20), f"UPDATED: {dt_obj.strftime('%H:%M')}", font=f_head, fill="#CCCCCC")
        draw.text((30, 70), "{:.1f}\u00b0".format(temp), font=f_huge, fill="white")
        draw.text((35, 195), get_desc(code), font=f_large, fill="#E6E6E6")

        icon_path = os.path.join(ICON_DIR, get_icon_filename(code, is_day))
        if os.path.exists(icon_path):
            with Image.open(icon_path) as icon:
                icon = icon.convert("RGBA").resize((160, 160), Image.Resampling.LANCZOS)
                img.paste(icon, (300, 40), icon)
        
        draw.text((520, 80), "H:{:.0f}\u00b0 L:{:.0f}\u00b0".format(high, low), font=f_large, fill="#DDDDDD")
        draw.text((520, 130), "Feels: {:.0f}\u00b0".format(feel), font=f_large, fill="#DDDDDD")
        draw.text((520, 180), f"Rain: {precip}%", font=f_large, fill="#AACCFF")
        
        arrow = create_wind_arrow(wind_deg, 45, "#FFFFFF")
        img.paste(arrow, (30, 270), arrow)
        draw.text((90, 280), f"{wind}km/h {wind_dir_str}   {hum}%   {int(press)}hPa   Vis:{vis:.1f}km", font=f_med, fill="#EEEEEE")
        
        img.save(output_path, "PNG")
        if DEBUG_MODE: log(f"[Right-Weather] Generated successfully.")
        return True
    except Exception as e:
        log(f"[Right-Weather] Error: {e}")
        return False

# ================= ALERT GENERATION =================
def fetch_title_from_xml(zone_code):
    xml_url = f"https://weather.gc.ca/rss/battleboard/{zone_code}_e.xml"
    if DEBUG_MODE: log(f"[EC-Alert] Fetching XML: {xml_url}")
    try:
        r = requests.get(xml_url, timeout=5)
        if r.status_code != 200: return None
        root = ET.fromstring(r.content)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        for entry in root.findall('atom:entry', ns):
            title = entry.find('atom:title', ns).text
            if title and "No watches or warnings" not in title:
                return title
        return None
    except: return None

async def fetch_ec_alert():
    if not HAS_EC: return None, None
    try:
        ec = ECWeather(coordinates=(LAT, LON))
        await ec.update()
        if ec.alerts:
            for a_id, a_data in ec.alerts.items():
                if 'value' in a_data and isinstance(a_data['value'], list) and len(a_data['value']) > 0:
                    alert_item = a_data['value'][0]
                    title = alert_item.get('title', 'ALERT')
                    color = alert_item.get('alertColourLevel', 'red')
                    alert_url = alert_item.get('url', 'N/A')
                    
                    # Try to get better title from XML
                    match = re.search(r'(onrm\d+)', alert_url)
                    if match:
                        zone_code = match.group(1)
                        if DEBUG_MODE: log(f"[EC-Alert] Detected Zone: {zone_code}")
                        better_title = fetch_title_from_xml(zone_code)
                        if better_title: title = better_title
                    
                    return title.upper(), color
        return None, None
    except: return None, None

def fetch_nws_alert():
    try:
        url = f"https://api.weather.gov/alerts/active?point={LAT},{LON}"
        headers = {'User-Agent': 'VantageCamLive/1.0'}
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()
        if 'features' in data and len(data['features']) > 0:
            props = data['features'][0]['properties']
            title = props.get('event', 'WEATHER ALERT').upper()
            severity = props.get('severity', 'Severe')
            color = 'red'
            if severity in ['Minor', 'Moderate']: color = 'yellow'
            return title, color
        return None, None
    except: return None, None

def generate_alerts(output_path, width=900, height=150):
    country = detect_country()
    if country == "CA":
        result = asyncio.run(fetch_ec_alert()) if HAS_EC else (None, None)
    else:
        result = fetch_nws_alert()
        
    alert_text, alert_color = result if result else (None, None)
    
    if not alert_text:
        img = Image.new('RGBA', (int(width), int(height)), (0, 0, 0, 0))
        img.save(output_path, "PNG")
        return True

    try:
        # High Contrast Colors
        bg_rgba = (200, 0, 0, 255) # Red
        text_fill = "white"
        
        if alert_color == 'yellow':
            bg_rgba = (255, 215, 0, 255) # Bright Yellow
            text_fill = "black" # Black text on Yellow
        elif alert_color == 'grey':
            bg_rgba = (128, 128, 128, 255) # Grey
            text_fill = "white"

        img = Image.new('RGBA', (int(width), int(height)), bg_rgba)
        draw = ImageDraw.Draw(img)
        
        # Split text: "WARNING, REGION"
        # Example: "YELLOW WARNING - SNOWFALL, INNISFIL - NEW TECUMSETH - ANGUS"
        if ',' in alert_text:
            parts = alert_text.split(',', 1)
            warning_text = parts[0].strip() # "YELLOW WARNING - SNOWFALL"
            region_text = parts[1].strip()  # "INNISFIL..."
        else:
            warning_text = alert_text
            region_text = ""

        # Draw Warning Icon (Left)
        try:
            f_icon = ImageFont.truetype(FONT_PATH, 55)
        except:
            f_icon = ImageFont.load_default()
        
        draw.text((25, 45), "\u26A0", font=f_icon, fill=text_fill)

        # Draw Region (Top Line)
        if region_text:
            try:
                f_region = ImageFont.truetype(FONT_PATH, 24)
            except: f_region = ImageFont.load_default()
            
            # Center the region text relative to the box
            # Box width available = 900 - 80 (icon space) = 820
            # Center of available space = 80 + 410 = 490
            reg_bbox = draw.textbbox((0, 0), region_text, font=f_region)
            reg_w = reg_bbox[2] - reg_bbox[0]
            reg_x = 490 - (reg_w / 2)
            if reg_x < 90: reg_x = 90 # Minimum margin
            
            draw.text((reg_x, 20), region_text, font=f_region, fill=text_fill)

        # Draw Warning (Bottom Line) - Auto Fit
        # Max width = Total Width (900) - Icon Margin (90) - Right Padding (20)
        max_w = width - 110 
        font_size = 55
        
        try:
            f_warn = ImageFont.truetype(FONT_PATH, font_size)
            # Shrink loop: Reduce font size until text fits
            while f_warn.getlength(warning_text) > max_w and font_size > 20:
                font_size -= 2
                f_warn = ImageFont.truetype(FONT_PATH, font_size)
        except:
            f_warn = ImageFont.load_default()
            
        # Center the warning text
        warn_bbox = draw.textbbox((0, 0), warning_text, font=f_warn)
        warn_w = warn_bbox[2] - warn_bbox[0]
        warn_x = 490 - (warn_w / 2)
        if warn_x < 90: warn_x = 90
        
        # Y position: If region exists, push warning down. If not, center it.
        warn_y = 65 if region_text else 45
        
        draw.text((warn_x, warn_y), warning_text, font=f_warn, fill=text_fill)
        
        img.save(output_path, "PNG")
        if DEBUG_MODE: log(f"[Alerts] Generated: {alert_text}")
        return True
    except Exception as e:
        log(f"[Alerts] Gen Error: {e}")
        return False

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
            new_im.save(output_path, "PNG")
            return True
    except: return False

if __name__ == "__main__":
    if len(sys.argv) < 3: sys.exit(1)
    mode = sys.argv[1]
    output = sys.argv[2]
    
    if mode == "weather": generate_weather(output)
    elif mode == "alerts": generate_alerts(output)
    elif mode == "blank": generate_blank(output, sys.argv[3], sys.argv[4])
    elif mode == "ad": process_ad(sys.argv[3], output, sys.argv[4], sys.argv[5])