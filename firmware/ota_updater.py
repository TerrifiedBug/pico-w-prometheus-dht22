"""
Minimal GitHub OTA Updater for Pico W - Ultra-lightweight for memory-constrained updates
"""

import urequests
import ujson
import os
import gc
import time
import machine
from logger import log_info, log_warn, log_error, log_debug


class GitHubOTAUpdater:
    def __init__(self):
        log_info("Initializing minimal OTA updater", "OTA")

        # Hardcoded configuration for minimal size
        self.repo_owner = "TerrifiedBug"
        self.repo_name = "pico-w-prometheus-dht22"
        self.branch = "main"

        # GitHub URLs
        self.api_base = f"https://api.github.com/repos/{self.repo_owner}/{self.repo_name}"
        self.raw_base = f"https://raw.githubusercontent.com/{self.repo_owner}/{self.repo_name}"

        # Local directories
        self.temp_dir = "temp"
        self.update_files = []

        # Ensure temp directory exists
        try:
            os.mkdir(self.temp_dir)
        except OSError:
            pass

        log_info(f"Minimal OTA ready: {self.repo_owner}/{self.repo_name}", "OTA")

    def get_current_version(self):
        try:
            with open("version.txt", "r") as f:
                return f.read().strip()
        except OSError:
            return "unknown"

    def set_current_version(self, version):
        with open("version.txt", "w") as f:
            f.write(version)

    def _get_headers(self):
        return {
            'User-Agent': 'Pico-W-OTA/1.0',
            'Accept': 'application/vnd.github.v3+json',
            'Accept-Encoding': 'identity'
        }

    def _make_request(self, url, headers=None, timeout=30, retries=3):
        if headers is None:
            headers = self._get_headers()

        for attempt in range(retries):
            try:
                log_debug(f"Request {attempt + 1}/{retries}: {url}", "OTA")

                gc.collect()
                response = urequests.get(url, headers=headers)

                if response.status_code == 200:
                    return True, response
                else:
                    log_error(f"HTTP {response.status_code}", "OTA")
                    response.close()

                    if 400 <= response.status_code < 500:
                        return False, f"HTTP {response.status_code}"

                    if attempt < retries - 1:
                        time.sleep(2)
                        continue
                    else:
                        return False, f"HTTP {response.status_code}"

            except Exception as e:
                log_error(f"Request failed: {e}", "OTA")
                if attempt < retries - 1:
                    time.sleep(2)
                    continue
                else:
                    return False, str(e)

        return False, "All retries failed"

    def check_for_updates(self):
        try:
            log_info("Checking for updates", "OTA")
            current_version = self.get_current_version()

            url = f"{self.api_base}/releases/latest"
            success, response_or_error = self._make_request(url)

            if not success:
                log_error(f"Update check failed: {response_or_error}", "OTA")
                return False, None, None

            try:
                release_data = response_or_error.json()
                response_or_error.close()
            except Exception as e:
                log_error(f"JSON parse failed: {e}", "OTA")
                response_or_error.close()
                return False, None, None

            latest_version = release_data["tag_name"]
            has_update = latest_version != current_version

            if has_update:
                log_info(f"Update available: {current_version} -> {latest_version}", "OTA")
            else:
                log_info("No update needed", "OTA")

            return has_update, latest_version, release_data

        except Exception as e:
            log_error(f"Update check failed: {e}", "OTA")
            return False, None, None

    def _download_file_ultra_minimal(self, url, filename, target_dir=""):
        try:
            # Ultra-aggressive memory management
            gc.collect()
            initial_mem = gc.mem_free()
            log_debug(f"Ultra-minimal download {filename}, mem: {initial_mem}", "OTA")

            success, response_or_error = self._make_request(url)
            if not success:
                log_error(f"Download failed: {response_or_error}", "OTA")
                return False

            try:
                target_path = f"{target_dir}/{filename}" if target_dir else filename
                temp_path = f"{target_path}.tmp"

                # ULTRA-SMALL chunks - 256 bytes to prevent allocation failures
                chunk_size = 256
                total_bytes = 0

                content = response_or_error.text
                content_size = len(content)

                # Quick validation
                if content_size == 0:
                    log_error(f"{filename} is empty", "OTA")
                    response_or_error.close()
                    return False

                if content.strip().startswith('<!DOCTYPE html>'):
                    log_error(f"{filename} is error page", "OTA")
                    response_or_error.close()
                    return False

                response_or_error.close()
                gc.collect()

                # Write in ultra-small chunks with aggressive GC
                with open(temp_path, "w") as f:
                    for i in range(0, content_size, chunk_size):
                        gc.collect()  # GC before each chunk

                        chunk = content[i:i + chunk_size]
                        f.write(chunk)
                        total_bytes += len(chunk)

                        del chunk  # Clear immediately

                        # GC every 512 bytes
                        if i % (chunk_size * 2) == 0:
                            gc.collect()

                # Clear content and GC
                del content
                gc.collect()

                # Atomic rename
                try:
                    os.rename(temp_path, target_path)
                except OSError:
                    try:
                        os.remove(target_path)
                    except OSError:
                        pass
                    os.rename(temp_path, target_path)

                # Verify file exists
                try:
                    os.stat(target_path)
                except OSError:
                    log_error(f"{target_path} not created", "OTA")
                    return False

                gc.collect()
                final_mem = gc.mem_free()
                log_info(f"Downloaded {filename} ({total_bytes} bytes, mem: {final_mem})", "OTA")
                return True

            except Exception as e:
                log_error(f"Write failed {filename}: {e}", "OTA")

                # Cleanup
                temp_path = f"{target_dir}/{filename}.tmp" if target_dir else f"{filename}.tmp"
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
                return False

        except Exception as e:
            log_error(f"Ultra-minimal download failed {filename}: {e}", "OTA")
            return False

    def download_file(self, filename, target_dir=""):
        # Construct URL for firmware files
        if filename in ["main.py", "config.py", "ota_updater.py", "device_config.py", "logger.py", "version.txt", "web_interface.py"]:
            url = f"{self.raw_base}/{self.branch}/firmware/{filename}"
        else:
            url = f"{self.raw_base}/{self.branch}/{filename}"

        log_info(f"Downloading {filename}", "OTA")

        # Always use ultra-minimal streaming
        return self._download_file_ultra_minimal(url, filename, target_dir)

    def _discover_firmware_files(self):
        try:
            contents_url = f"{self.api_base}/contents/firmware"
            success, response_or_error = self._make_request(contents_url)

            if not success:
                # Fallback to essential files
                return ["main.py", "config.py", "ota_updater.py", "device_config.py", "logger.py", "web_interface.py", "version.txt"]

            try:
                contents_data = response_or_error.json()
                response_or_error.close()
            except Exception as e:
                response_or_error.close()
                return ["main.py", "config.py", "ota_updater.py", "device_config.py", "logger.py", "web_interface.py", "version.txt"]

            # Extract firmware files (exclude secrets.py)
            firmware_files = []
            for item in contents_data:
                if item["type"] == "file":
                    filename = item["name"]
                    if (filename.endswith(".py") or filename == "version.txt") and filename != "secrets.py":
                        firmware_files.append(filename)

            log_info(f"Discovered {len(firmware_files)} files", "OTA")
            return firmware_files

        except Exception as e:
            log_error(f"File discovery failed: {e}", "OTA")
            return ["main.py", "config.py", "ota_updater.py", "device_config.py", "logger.py", "web_interface.py", "version.txt"]

    def download_update(self, version, release_info=None):
        try:
            log_info(f"Starting download for {version}", "OTA")

            # Clean temp directory
            try:
                for filename in os.listdir(self.temp_dir):
                    filepath = f"{self.temp_dir}/{filename}"
                    os.remove(filepath)
            except OSError:
                pass

            # Get files to download
            files_to_download = self._discover_firmware_files()
            self.update_files = files_to_download

            log_info(f"Downloading {len(files_to_download)} files", "OTA")

            # Download each file
            for i, filename in enumerate(files_to_download, 1):
                log_info(f"Downloading {i}/{len(files_to_download)}: {filename}", "OTA")

                gc.collect()
                if not self.download_file(filename, self.temp_dir):
                    log_error(f"Failed to download {filename}", "OTA")
                    return False

                log_info(f"Downloaded {filename} ({i}/{len(files_to_download)})", "OTA")
                time.sleep(0.5)  # Brief delay

            log_info(f"Downloaded all {len(files_to_download)} files", "OTA")
            return True

        except Exception as e:
            log_error(f"Download failed: {e}", "OTA")
            return False

    def apply_update(self, version):
        try:
            log_info(f"Applying update to {version}", "OTA")

            # Move temp files to main location (no backup - direct overwrite)
            for filename in self.update_files:
                temp_path = f"{self.temp_dir}/{filename}"
                try:
                    os.stat(temp_path)  # Check if file exists

                    # Copy file content
                    with open(temp_path, "r") as src:
                        content = src.read()
                    with open(filename, "w") as dst:
                        dst.write(content)

                    log_info(f"Updated {filename}", "OTA")
                except OSError:
                    log_warn(f"Skipping missing {filename}", "OTA")

            # Update version
            self.set_current_version(version)

            # Clean temp directory
            try:
                for filename in os.listdir(self.temp_dir):
                    filepath = f"{self.temp_dir}/{filename}"
                    os.remove(filepath)
            except OSError:
                pass

            log_info(f"Update to {version} completed", "OTA")
            return True

        except Exception as e:
            log_error(f"Apply failed: {e}", "OTA")
            return False

    def perform_update(self):
        try:
            # Check for updates
            has_update, new_version, release_info = self.check_for_updates()

            if not has_update:
                log_info("No updates available", "OTA")
                return False

            log_info(f"Update available: {new_version}", "OTA")

            # Download update
            if not self.download_update(new_version):
                log_error("Download failed", "OTA")
                return False

            # Apply update
            if not self.apply_update(new_version):
                log_error("Apply failed", "OTA")
                return False

            log_info("Update completed, restarting...", "OTA")
            gc.collect()
            machine.reset()

        except Exception as e:
            log_error(f"Update failed: {e}", "OTA")
            return False

    def get_update_status(self):
        try:
            from device_config import get_ota_config
            ota_config = get_ota_config()
            ota_enabled = ota_config.get("enabled", True)
            auto_check = ota_config.get("auto_update", True)
        except Exception:
            ota_enabled = True
            auto_check = True

        return {
            "current_version": self.get_current_version(),
            "ota_enabled": ota_enabled,
            "auto_check": auto_check,
            "repo": f"{self.repo_owner}/{self.repo_name}",
            "branch": self.branch,
            "update_files": self.update_files
        }
