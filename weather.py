# -*- coding: utf-8 -*-
import requests
import json
import datetime
import os
import sys
from PIL import Image, ImageDraw, ImageFont

# ================= CONFIGURATION =================
LAT = os.getenv("WEATHER_LAT", "40.7128")    # Changed to NYC
LON = os.getenv("WEATHER_LON", "-74.0060")   # Changed to NYC
LOCATION_NAME = os.getenv("WEATHER_LOCATION", "My City")
TIMEZONE = os.getenv("WEATHER_TIMEZONE", "America/Toronto")
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# UPDATED PATH: Pointing to where you already have them
ICON_DIR = "/config/weather_icons"

# CAMERA SETTINGS
CAMERA_HEADING = 90  # 90 degrees = East

def log(message):
    print(f"[{datetime.datetime.now()}] {message}")

# --- HELPER: WMO Code to Icon Name Mapping ---
def get_icon_filename(code, is_day):
    # Determine suffix (d = day, n = night)
    suffix = 'd' if is_day == 1 else 'n'

    # Map WMO codes (OpenMeteo) to OpenWeatherMap icon names
    if code == 0: return f"01{suffix}.png"       # Clear sky
    if code in [1]: return f"02{suffix}.png"     # Mainly clear
    if code in [2]: return f"03{suffix}.png"     # Partly cloudy
    if code in [3]: return f"04{suffix}.png"     # Overcast
    if code in [45, 48]: return f"50{suffix}.png" # Fog
    if code in [51, 53, 55]: return f"09{suffix}.png" # Drizzle
    if code in [56, 57]: return f"09{suffix}.png" # Freezing Drizzle
    if code in [61, 63, 65]: return f"10{suffix}.png" # Rain
    if code in [66, 67]: return f"13{suffix}.png" # Freezing Rain
    if code in [71, 73, 75, 77]: return f"13{suffix}.png" # Snow
    if code in [80, 81, 82]: return f"09{suffix}.png" # Rain showers
    if code in [85, 86]: return f"13{suffix}.png" # Snow showers
    if code in [95, 96, 99]: return f"11{suffix}.png" # Thunderstorm

    return f"03{suffix}.png" # Default fallback

# --- FUNCTION 1: WEATHER GENERATOR ---
def get_weather():
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={LAT}&longitude={LON}&current_weather=true&"
        f"hourly=relativehumidity_2m,surface_pressure,apparent_temperature,visibility,precipitation_probability&"
        f"daily=temperature_2m_max,temperature_2m_min&"
        f"timezone={TIMEZONE}"
    )
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        log(f"API Error: {e}")
        return None

def get_wind_dir(degrees):
    dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
    ix = round(degrees / (360. / len(dirs)))
    return dirs[ix % len(dirs)]

def create_wind_arrow(degrees, size=50, color="#FFFFFF"):
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    c = size // 2
    points = [
        (c, 0),                 # Tip
        (size, size),           # Bottom Right
        (c, int(size * 0.75)),  # Inner Notch
        (0, size)               # Bottom Left
    ]
    draw.polygon(points, fill=color)
    rotation = -(degrees - CAMERA_HEADING)
    return img.rotate(rotation, resample=Image.BICUBIC, expand=False)

def generate_weather(output_path, width=900, height=350):
    data = get_weather()
    if not data: return False

    try:
        # --- PARSE DATA ---
        current = data['current_weather']
        hourly = data['hourly']
        daily = data['daily']

        temp = current['temperature']
        wind = current['windspeed']
        wind_deg = current['winddirection']
        code = current['weathercode']
        is_day = current['is_day'] # 1 = Day, 0 = Night
        api_time_str = current['time']

        wind_dir_str = get_wind_dir(wind_deg)
        dt_obj = datetime.datetime.strptime(api_time_str, "%Y-%m-%dT%H:%M")
        formatted_time = dt_obj.strftime("%H:%M")

        feel = hourly['apparent_temperature'][0] if hourly else temp
        hum = hourly['relativehumidity_2m'][0] if hourly else 0
        press = hourly['surface_pressure'][0] if hourly else 0
        precip_prob = hourly['precipitation_probability'][0] if hourly else 0
        vis_meters = hourly['visibility'][0] if hourly else 10000
        vis_km = vis_meters / 1000.0
        high = daily['temperature_2m_max'][0] if daily else temp
        low = daily['temperature_2m_min'][0] if daily else temp

        # --- TEXT ---
        def get_desc(c):
            if c == 0: return "Clear Sky"
            if c in [1, 2, 3]: return "Partly Cloudy"
            if c in [45, 48]: return "Foggy"
            if c in [51, 53, 55, 56, 57]: return "Drizzle"
            if c in [61, 63, 65, 66, 67, 80, 81, 82]: return "Rain"
            if c in [71, 73, 75, 77, 85, 86]: return "Snow"
            if c in [95, 96, 99]: return "Thunderstorm"
            return "Unknown"

        desc_txt = get_desc(code)
        temp_txt = u"{:.1f}\u00b0".format(temp)
        loc_txt = LOCATION_NAME.upper()
        time_txt = f"UPDATED: {formatted_time}"

        hl_txt = u"H:{:.0f}\u00b0 L:{:.0f}\u00b0".format(high, low)
        feel_txt = u"Feels: {:.0f}\u00b0".format(feel)
        precip_txt = u"Rain: {}%".format(precip_prob)

        vis_txt = f"{vis_km:.1f}km"
        stats_txt = u"{}km/h {}   {}%   {}hPa   Vis:{}".format(
            wind, wind_dir_str, hum, int(press), vis_txt
        )

        # --- DRAWING ---
        img = Image.new('RGBA', (int(width), int(height)), (0, 0, 0, 180))
        draw = ImageDraw.Draw(img)

        try:
            f_huge = ImageFont.truetype(FONT_PATH, 110)
            f_large = ImageFont.truetype(FONT_PATH, 40)
            f_med = ImageFont.truetype(FONT_PATH, 26)
            f_head = ImageFont.truetype(FONT_PATH, 28)
        except:
            f_huge = ImageFont.load_default()
            f_large = ImageFont.load_default()
            f_med = ImageFont.load_default()
            f_head = ImageFont.load_default()

        # 1. HEADER
        draw.text((30, 20), loc_txt, font=f_head, fill="#CCCCCC")
        draw.text((int(width) - 260, 20), time_txt, font=f_head, fill="#CCCCCC")

        # 2. MAIN TEMP
        draw.text((30, 70), temp_txt, font=f_huge, fill="white")
        draw.text((35, 195), desc_txt, font=f_large, fill="#E6E6E6")

        # 3. WEATHER ICON
        icon_file = get_icon_filename(code, is_day)
        icon_path = os.path.join(ICON_DIR, icon_file)

        if os.path.exists(icon_path):
            try:
                with Image.open(icon_path) as icon_img:
                    icon_img = icon_img.convert("RGBA")
                    # Resize to fit nicely (160x160)
                    icon_img = icon_img.resize((160, 160), Image.Resampling.LANCZOS)
                    # Positioned at 300, 40 (Center of the empty space)
                    img.paste(icon_img, (300, 40), icon_img)
            except Exception as e:
                log(f"Icon Load Error: {e}")
        else:
            log(f"Icon missing: {icon_path}")

        # 4. DETAILS (Right Side)
        detail_x = 520
        draw.text((detail_x, 80), hl_txt, font=f_large, fill="#DDDDDD")
        draw.text((detail_x, 130), feel_txt, font=f_large, fill="#DDDDDD")
        draw.text((detail_x, 180), precip_txt, font=f_large, fill="#AACCFF")

        # 5. STATS ROW
        arrow_size = 45
        arrow_x = 30
        arrow_y = 270
        arrow_icon = create_wind_arrow(wind_deg, size=arrow_size, color="#FFFFFF")
        img.paste(arrow_icon, (arrow_x, arrow_y), arrow_icon)
        draw.text((arrow_x + 60, arrow_y + 10), stats_txt, font=f_med, fill="#EEEEEE")

        img.save(output_path, "PNG")
        log(f"Weather generated at {output_path}")
        return True
    except Exception as e:
        log(f"Weather Error: {e}")
        return False

# --- FUNCTION 2: BLANK GENERATOR ---
def generate_blank(output_path, width, height):
    try:
        img = Image.new('RGBA', (int(width), int(height)), (0, 0, 0, 0))
        img.save(output_path, "PNG")
        log(f"Blank generated at {output_path}")
        return True
    except Exception as e:
        log(f"Blank Error: {e}")
        return False

# --- FUNCTION 3: AD PROCESSOR ---
def process_ad(input_path, output_path, target_w, target_h):
    try:
        target_w = int(target_w)
        target_h = int(target_h)
        with Image.open(input_path) as im:
            im = im.convert("RGBA")
            ratio = min(target_w / im.width, target_h / im.height)
            new_w = int(im.width * ratio)
            new_h = int(im.height * ratio)
            im_resized = im.resize((new_w, new_h), Image.Resampling.LANCZOS)
            new_im = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
            x = (target_w - new_w) // 2
            y = 0
            new_im.paste(im_resized, (x, y))
            new_im.save(output_path, "PNG")
            return True
    except Exception as e:
        log(f"Ad Error: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python weather.py [mode] [output] [arg1] [arg2]")
        sys.exit(1)

    mode = sys.argv[1]
    output = sys.argv[2]

    if mode == "weather":
        if generate_weather(output): sys.exit(0)
        else: sys.exit(1)

    elif mode == "blank":
        w = sys.argv[3]
        h = sys.argv[4]
        if generate_blank(output, w, h): sys.exit(0)
        else: sys.exit(1)

    elif mode == "ad":
        inp = sys.argv[3]
        w = sys.argv[4]
        h = sys.argv[5]
        if process_ad(inp, output, w, h): sys.exit(0)
        else: sys.exit(1)