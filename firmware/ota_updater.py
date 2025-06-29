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

        # Load configuration from device config instead of hardcoding
        try:
            from device_config import get_ota_config
            ota_config = get_ota_config()
            github_repo = ota_config.get("github_repo", {})

            self.repo_owner = github_repo.get("owner", "TerrifiedBug")
            self.repo_name = github_repo.get("name", "pico-w-prometheus-dht22")
            self.branch = github_repo.get("branch", "main")

            log_info(f"OTA config loaded: {self.repo_owner}/{self.repo_name} (branch: {self.branch})", "OTA")
        except Exception as e:
            # Fallback to hardcoded values if config fails
            log_warn(f"Failed to load OTA config, using defaults: {e}", "OTA")
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

        log_info(f"Minimal OTA ready: {self.repo_owner}/{self.repo_name} (branch: {self.branch})", "OTA")

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

            # Determine release channel based on branch
            if self.branch == "dev":
                # For dev branch, get only the latest release and check if it's a pre-release
                url = f"{self.api_base}/releases?per_page=1"
                log_info("Checking for dev releases (pre-releases)", "OTA")
            else:
                # For main branch, use latest stable release
                url = f"{self.api_base}/releases/latest"
                log_info("Checking for stable releases", "OTA")

            success, response_or_error = self._make_request(url)

            if not success:
                log_error(f"Update check failed: {response_or_error}", "OTA")
                return False, None, None

            try:
                if self.branch == "dev":
                    # Parse releases list (only 1 release due to per_page=1)
                    releases_data = response_or_error.json()
                    response_or_error.close()

                    # Check if we got any releases
                    if not releases_data or len(releases_data) == 0:
                        log_info("No releases found", "OTA")
                        return False, None, None

                    # Get the first (and only) release
                    latest_release = releases_data[0]

                    # Check if it's a pre-release (dev release)
                    if not latest_release.get("prerelease", False):
                        log_info("Latest release is not a dev release", "OTA")
                        return False, None, None

                    release_data = latest_release
                    latest_version = release_data["tag_name"]
                    log_info(f"Found latest dev release: {latest_version}", "OTA")
                else:
                    # Parse single latest release
                    release_data = response_or_error.json()
                    response_or_error.close()
                    latest_version = release_data["tag_name"]
                    log_info(f"Found latest stable release: {latest_version}", "OTA")

            except Exception as e:
                log_error(f"JSON parse failed: {e}", "OTA")
                response_or_error.close()
                return False, None, None

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
                    # version.txt is optional since we use Git tags for versioning
                    if filename == "version.txt":
                        log_warn(f"Skipping optional file {filename}", "OTA")
                        continue
                    else:
                        log_error(f"Failed to download {filename}", "OTA")
                        return False

                log_info(f"Downloaded {filename} ({i}/{len(files_to_download)})", "OTA")
                time.sleep(0.5)  # Brief delay

            log_info(f"Downloaded all {len(files_to_download)} files", "OTA")
            return True

        except Exception as e:
            log_error(f"Download failed: {e}", "OTA")
            return False

    def create_backup(self, files_to_backup):
        """Create backup of critical files before update."""
        try:
            log_info("Creating backup of current files", "OTA")
            backup_count = 0

            for filename in files_to_backup:
                try:
                    # Check if original file exists
                    os.stat(filename)

                    # Create backup
                    backup_name = f"{filename}.bak"

                    # Read original file
                    with open(filename, "r") as src:
                        content = src.read()

                    # Write backup
                    with open(backup_name, "w") as dst:
                        dst.write(content)

                    backup_count += 1
                    log_info(f"Backed up {filename}", "OTA")

                except OSError:
                    log_warn(f"Could not backup {filename} (file not found)", "OTA")

            log_info(f"Created {backup_count} backup files", "OTA")
            return backup_count > 0

        except Exception as e:
            log_error(f"Backup creation failed: {e}", "OTA")
            return False

    def validate_update_files(self):
        """Validate that downloaded files can be imported."""
        try:
            log_info("Validating downloaded files", "OTA")

            # Test critical files for basic syntax
            critical_files = ["main.py", "web_interface.py", "config.py"]

            for filename in critical_files:
                temp_path = f"{self.temp_dir}/{filename}"
                try:
                    os.stat(temp_path)

                    # Basic validation - check file is not empty and not HTML error page
                    with open(temp_path, "r") as f:
                        content = f.read()

                    if len(content) < 100:  # Too small
                        log_error(f"{filename} too small ({len(content)} bytes)", "OTA")
                        return False

                    if content.strip().startswith('<!DOCTYPE html>'):
                        log_error(f"{filename} is HTML error page", "OTA")
                        return False

                    # Check for imports, but exclude configuration files that don't need them
                    if filename.endswith('.py') and filename not in ['config.py', 'secrets.py']:
                        if 'import' not in content:
                            log_error(f"{filename} missing imports", "OTA")
                            return False

                    log_info(f"Validated {filename} ({len(content)} bytes)", "OTA")

                except OSError:
                    log_warn(f"Could not validate {filename}", "OTA")

            log_info("File validation completed", "OTA")
            return True

        except Exception as e:
            log_error(f"Validation failed: {e}", "OTA")
            return False

    def apply_update(self, version):
        try:
            log_info(f"Applying update to {version}", "OTA")

            # Step 1: Create backups of existing files
            if not self.create_backup(self.update_files):
                log_warn("Backup creation failed, proceeding anyway", "OTA")

            # Step 2: Validate downloaded files
            if not self.validate_update_files():
                log_error("File validation failed, aborting update", "OTA")
                return False

            # Step 3: Apply updates with error handling
            updated_files = []
            for filename in self.update_files:
                temp_path = f"{self.temp_dir}/{filename}"
                try:
                    os.stat(temp_path)  # Check if file exists

                    # Copy file content
                    with open(temp_path, "r") as src:
                        content = src.read()
                    with open(filename, "w") as dst:
                        dst.write(content)

                    updated_files.append(filename)
                    log_info(f"Updated {filename}", "OTA")
                except OSError:
                    log_warn(f"Skipping missing {filename}", "OTA")

            # Step 4: Update version only if files were updated
            if updated_files:
                self.set_current_version(version)
                log_info(f"Updated {len(updated_files)} files to version {version}", "OTA")
            else:
                log_error("No files were updated", "OTA")
                return False

            # Step 5: Clean temp directory
            try:
                for filename in os.listdir(self.temp_dir):
                    filepath = f"{self.temp_dir}/{filename}"
                    os.remove(filepath)
            except OSError:
                pass

            log_info(f"Update to {version} completed successfully", "OTA")
            return True

        except Exception as e:
            log_error(f"Apply failed: {e}", "OTA")
            return False

    def rollback_update(self):
        """Rollback to backup files if available."""
        try:
            log_info("Rolling back to backup files", "OTA")
            rollback_count = 0

            # Find and restore backup files
            for filename in os.listdir():
                if filename.endswith('.bak'):
                    original_name = filename[:-4]  # Remove .bak extension
                    try:
                        # Read backup content
                        with open(filename, "r") as src:
                            content = src.read()

                        # Restore original file
                        with open(original_name, "w") as dst:
                            dst.write(content)

                        rollback_count += 1
                        log_info(f"Restored {original_name} from backup", "OTA")

                    except Exception as e:
                        log_error(f"Failed to restore {original_name}: {e}", "OTA")

            if rollback_count > 0:
                log_info(f"Rollback completed: restored {rollback_count} files", "OTA")
                return True
            else:
                log_warn("No backup files found for rollback", "OTA")
                return False

        except Exception as e:
            log_error(f"Rollback failed: {e}", "OTA")
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
