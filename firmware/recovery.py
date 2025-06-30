"""
Ultra-minimal recovery mode for Pico W - Emergency firmware recovery
Only loads when main modules fail to import. ~2KB footprint.
"""

import socket
import time
import network
from secrets import secrets

# Initialize WiFi for recovery
wlan = network.WLAN(network.STA_IF)
wlan.active(True)

# Emergency WiFi connection
def emergency_connect():
    """Connect to WiFi in emergency mode."""
    print("RECOVERY MODE: Connecting to WiFi...")
    wlan.connect(secrets["ssid"], secrets["pw"])

    max_wait = 20
    while max_wait > 0:
        if wlan.status() == 3:
            print(f"RECOVERY: WiFi connected, IP: {wlan.ifconfig()[0]}")
            return True
        max_wait -= 1
        time.sleep(1)

    print("RECOVERY: WiFi connection failed")
    return False

# Minimal HTTP server for recovery
def recovery_server():
    """Ultra-minimal HTTP server for emergency recovery."""
    if not emergency_connect():
        return

    addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr)
    s.listen(1)

    print("RECOVERY: Emergency server running on port 80")

    recovery_html = """<!DOCTYPE html>
<html><head><title>RECOVERY MODE</title></head><body>
<h1 style="color:red">PICO W RECOVERY MODE</h1>
<p><strong>System failed to boot normally. Emergency recovery active.</strong></p>
<h2>Recovery Options</h2>
<form method="POST" action="/recover">
<p><input type="submit" name="action" value="Download Latest Firmware" style="padding:10px;background:green;color:white;border:none"></p>
<p><input type="submit" name="action" value="Restore Backup" style="padding:10px;background:blue;color:white;border:none"></p>
<p><input type="submit" name="action" value="Restart Device" style="padding:10px;background:orange;color:white;border:none"></p>
</form>
<h3>Status</h3>
<p>IP Address: """ + wlan.ifconfig()[0] + """</p>
<p>Recovery Mode Active - Normal modules failed to load</p>
</body></html>"""

    while True:
        try:
            cl, addr = s.accept()
            request = cl.recv(1024).decode('utf-8')

            if 'POST /recover' in request:
                # Parse form data
                if 'Download+Latest+Firmware' in request:
                    response = handle_firmware_download()
                elif 'Restore+Backup' in request:
                    response = handle_restore_backup()
                elif 'Restart+Device' in request:
                    cl.send("HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n<h1>Restarting...</h1>")
                    cl.close()
                    time.sleep(1)
                    import machine
                    machine.reset()
                else:
                    response = "HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n" + recovery_html
            else:
                response = "HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n" + recovery_html

            cl.send(response)
            cl.close()

        except Exception as e:
            print(f"RECOVERY: Server error: {e}")
            try:
                cl.close()
            except:
                pass

def handle_firmware_download():
    """Download fresh firmware from GitHub - dynamically discovers all firmware files."""
    try:
        print("RECOVERY: Downloading firmware...")

        # Try to get branch from config, fallback to main
        try:
            import ujson
            with open('device_config.json', 'r') as f:
                config = ujson.load(f)
            branch = config.get('ota', {}).get('github_repo', {}).get('branch', 'main')
            print(f"RECOVERY: Using branch: {branch}")
        except:
            branch = 'main'
            print("RECOVERY: Using default branch: main")

        import urequests

        # Step 1: Discover all firmware files using GitHub API
        print("RECOVERY: Discovering firmware files...")
        contents_url = f"https://api.github.com/repos/TerrifiedBug/pico-w-prometheus-dht22/contents/firmware?ref={branch}"

        try:
            response = urequests.get(contents_url)
            if response.status_code != 200:
                print(f"RECOVERY: API request failed: {response.status_code}")
                response.close()
                # Fallback to essential files
                files = ["main.py", "web_interface.py", "ota_updater.py", "device_config.py", "logger.py", "config.py", "recovery.py", "version.txt"]
            else:
                contents_data = response.json()
                response.close()

                # Extract all firmware files (exclude secrets.py)
                files = []
                for item in contents_data:
                    if item["type"] == "file":
                        filename = item["name"]
                        if (filename.endswith(".py") or filename == "version.txt") and filename != "secrets.py":
                            files.append(filename)

                print(f"RECOVERY: Discovered {len(files)} files: {files}")
        except Exception as e:
            print(f"RECOVERY: File discovery failed: {e}")
            # Fallback to essential files
            files = ["main.py", "web_interface.py", "ota_updater.py", "device_config.py", "logger.py", "config.py", "recovery.py", "version.txt"]

        # Step 2: Download all discovered files
        base_url = f"https://raw.githubusercontent.com/TerrifiedBug/pico-w-prometheus-dht22/{branch}/firmware/"
        success_count = 0
        failed_files = []

        for filename in files:
            try:
                print(f"RECOVERY: Downloading {filename}")
                response = urequests.get(base_url + filename)
                if response.status_code == 200:
                    with open(filename, 'w') as f:
                        f.write(response.text)
                    success_count += 1
                    print(f"RECOVERY: Downloaded {filename}")
                else:
                    failed_files.append(f"{filename} (HTTP {response.status_code})")
                response.close()
            except Exception as e:
                failed_files.append(f"{filename} ({e})")
                print(f"RECOVERY: Failed to download {filename}: {e}")

        # Step 3: Report results
        if success_count > 0:
            result_msg = f"Downloaded {success_count}/{len(files)} files from {branch} branch."
            if failed_files:
                result_msg += f" Failed: {', '.join(failed_files[:3])}" + ("..." if len(failed_files) > 3 else "")

            return f"HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n<h1>Recovery Complete</h1><p>{result_msg}</p><p><a href='/'>Restart device</a> to apply changes.</p>"
        else:
            return f"HTTP/1.0 500 Internal Server Error\r\nContent-Type: text/html\r\n\r\n<h1>Download Failed</h1><p>Could not download any firmware files. Errors: {', '.join(failed_files[:5])}</p>"

    except Exception as e:
        return f"HTTP/1.0 500 Internal Server Error\r\nContent-Type: text/html\r\n\r\n<h1>Error</h1><p>Recovery failed: {e}</p>"

def handle_restore_backup():
    """Restore from backup files."""
    try:
        import os
        restored = 0

        # Check for backup files
        for filename in os.listdir():
            if filename.endswith('.bak'):
                original = filename[:-4]  # Remove .bak extension
                try:
                    os.rename(filename, original)
                    restored += 1
                    print(f"RECOVERY: Restored {original}")
                except:
                    pass

        if restored > 0:
            return f"HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n<h1>Backup Restored</h1><p>Restored {restored} files from backup. <a href='/'>Restart device</a> to apply changes.</p>"
        else:
            return "HTTP/1.0 404 Not Found\r\nContent-Type: text/html\r\n\r\n<h1>No Backups Found</h1><p>No backup files available to restore.</p>"

    except Exception as e:
        return f"HTTP/1.0 500 Internal Server Error\r\nContent-Type: text/html\r\n\r\n<h1>Error</h1><p>Restore failed: {e}</p>"

# Start recovery server
print("EMERGENCY RECOVERY MODE ACTIVATED")
recovery_server()
