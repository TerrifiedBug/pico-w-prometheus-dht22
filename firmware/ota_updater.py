"""
GitHub-based OTA (Over-The-Air) Updater for Pico W

This module provides functionality to update MicroPython files on the Pico W
by downloading them directly from GitHub releases or branches.
"""

import urequests  # type: ignore
import ujson  # type: ignore
import os
import gc
import time
import machine  # type: ignore
from logger import log_info, log_warn, log_error, log_debug


class GitHubOTAUpdater:
    """
    GitHub-based OTA updater for MicroPython devices.

    Handles checking for updates, downloading files, backup/restore,
    and atomic updates with rollback capability.
    """

    def __init__(self):
        """Initialize the OTA updater with dynamic configuration"""
        log_info("Initializing OTA updater", "OTA")

        # Load dynamic configuration
        self._load_dynamic_config()

        # GitHub API URLs
        self.api_base = f"https://api.github.com/repos/{self.repo_owner}/{self.repo_name}"
        self.raw_base = f"https://raw.githubusercontent.com/{self.repo_owner}/{self.repo_name}"

        # Local directories
        self.backup_dir = "backup"
        self.temp_dir = "temp"

        # Ensure directories exist
        self._ensure_directories()

        log_info(f"OTA updater ready: {self.repo_owner}/{self.repo_name} ({self.branch})", "OTA")

    def _load_dynamic_config(self):
        """Load configuration from device_config.py"""
        try:
            from device_config import get_ota_config
            ota_config = get_ota_config()

            self.repo_owner = ota_config["github_repo"]["owner"]
            self.repo_name = ota_config["github_repo"]["name"]
            self.branch = ota_config["github_repo"]["branch"]
            self.backup_enabled = ota_config["backup_enabled"]

            # Get firmware files dynamically
            self.update_files = self._get_firmware_files()

        except Exception as e:
            log_error(f"Failed to load dynamic config: {e}", "OTA")
            # Use safe defaults if dynamic config fails
            self.repo_owner = "TerrifiedBug"
            self.repo_name = "pico-w-prometheus-dht22"
            self.branch = "main"
            self.backup_enabled = True
            self.update_files = ["main.py", "config.py", "ota_updater.py", "device_config.py", "logger.py", "version.txt"]
            log_warn("Using default OTA configuration", "OTA")

    def _get_firmware_files(self):
        """
        Get list of firmware files to update.
        This will be populated dynamically from the firmware package.
        """
        # This will be populated when we download the firmware package
        # NOTE: secrets.py is intentionally excluded to preserve WiFi credentials
        return []

    def _ensure_directories(self):
        """Create backup and temp directories if they don't exist"""
        try:
            os.mkdir(self.backup_dir)
        except OSError:
            pass  # Directory already exists

        try:
            os.mkdir(self.temp_dir)
        except OSError:
            pass  # Directory already exists

    def get_current_version(self):
        """
        Get the current version from version.txt file.

        Returns:
            str: Current version string, or "unknown" if file doesn't exist.
        """
        try:
            with open("version.txt", "r") as f:
                return f.read().strip()
        except OSError:
            return "unknown"

    def set_current_version(self, version):
        """
        Set the current version in version.txt file.

        Args:
            version (str): Version string to write.
        """
        with open("version.txt", "w") as f:
            f.write(version)

    def _get_headers(self):
        """
        Get HTTP headers for GitHub API requests.

        Returns:
            dict: Headers to include in requests.
        """
        return {
            'User-Agent': 'Pico-W-OTA-Client/1.0',
            'Accept': 'application/vnd.github.v3+json',
            'Accept-Encoding': 'identity'  # Avoid compression issues
        }

    def _make_request(self, url, headers=None, timeout=30, retries=3):
        """
        Make HTTP request with proper error handling and logging.

        Args:
            url (str): URL to request
            headers (dict): Optional headers
            timeout (int): Request timeout in seconds
            retries (int): Number of retry attempts

        Returns:
            tuple: (success, response_or_error)
        """
        if headers is None:
            headers = self._get_headers()

        for attempt in range(retries):
            try:
                log_debug(f"Request attempt {attempt + 1}/{retries}: {url}", "OTA")

                # Force garbage collection before request
                gc.collect()
                free_mem_before = gc.mem_free()
                log_debug(f"Free memory before request: {free_mem_before}", "OTA")

                response = urequests.get(url, headers=headers)

                log_debug(f"Response status: {response.status_code}", "OTA")
                if hasattr(response, 'headers'):
                    log_debug(f"Response headers: {dict(response.headers)}", "OTA")

                if response.status_code == 200:
                    return True, response
                else:
                    error_text = ""
                    try:
                        error_text = response.text[:200]  # First 200 chars of error
                    except:
                        error_text = "Unable to read error response"

                    log_error(f"HTTP {response.status_code} error: {error_text}", "OTA")
                    response.close()

                    # Don't retry on client errors (4xx)
                    if 400 <= response.status_code < 500:
                        return False, f"HTTP {response.status_code}: {error_text}"

                    # Retry on server errors (5xx) and other issues
                    if attempt < retries - 1:
                        log_warn(f"Retrying request in 2 seconds...", "OTA")
                        time.sleep(2)
                        continue
                    else:
                        return False, f"HTTP {response.status_code}: {error_text}"

            except Exception as e:
                log_error(f"Request attempt {attempt + 1} failed: {e}", "OTA")

                # Retry on network errors
                if attempt < retries - 1:
                    log_warn(f"Retrying request in 2 seconds...", "OTA")
                    time.sleep(2)
                    continue
                else:
                    return False, str(e)

        return False, "All retry attempts failed"

    def check_for_updates(self):
        """
        Check GitHub for newer releases with fallback mechanisms.

        Returns:
            tuple: (has_update, new_version, release_info) where:
                   has_update (bool): True if update available
                   new_version (str): Version string of latest release
                   release_info (dict): Full release information from GitHub
        """
        try:
            log_info("Starting update check", "OTA")
            current_version = self.get_current_version()
            log_info(f"Current version: {current_version}", "OTA")

            # For dev branch, check all releases including prereleases
            if self.branch == "dev":
                url = f"{self.api_base}/releases"
                log_debug(f"Checking dev releases from: {url}", "OTA")

                success, response_or_error = self._make_request(url)

                if not success:
                    log_error(f"API request failed: {response_or_error}", "OTA")
                    return self._check_updates_fallback()

                try:
                    releases_data = response_or_error.json()
                    response_or_error.close()
                    log_debug(f"Found {len(releases_data)} releases", "OTA")
                except Exception as e:
                    log_error(f"Failed to parse JSON response: {e}", "OTA")
                    response_or_error.close()
                    return self._check_updates_fallback()

                # Find the latest dev release (prerelease with dev- prefix)
                latest_dev_release = None
                for release in releases_data:
                    if release["prerelease"] and release["tag_name"].startswith("dev-"):
                        latest_dev_release = release
                        break  # Releases are ordered by date, so first match is latest

                if not latest_dev_release:
                    log_info("No dev releases found", "OTA")
                    return False, None, None

                latest_version = latest_dev_release["tag_name"]
                log_info(f"Latest dev version: {latest_version}", "OTA")

                has_update = latest_version != current_version
                if has_update:
                    log_info(f"Update available: {current_version} -> {latest_version}", "OTA")
                else:
                    log_info("No update needed - already on latest version", "OTA")
                return has_update, latest_version, latest_dev_release

            else:
                # For main branch, use latest stable release
                url = f"{self.api_base}/releases/latest"
                log_debug(f"Checking latest release from: {url}", "OTA")

                success, response_or_error = self._make_request(url)

                if not success:
                    log_error(f"API request failed: {response_or_error}", "OTA")
                    return self._check_updates_fallback()

                try:
                    release_data = response_or_error.json()
                    response_or_error.close()
                except Exception as e:
                    log_error(f"Failed to parse JSON response: {e}", "OTA")
                    response_or_error.close()
                    return self._check_updates_fallback()

                latest_version = release_data["tag_name"]
                log_info(f"Latest stable version: {latest_version}", "OTA")

                has_update = latest_version != current_version
                if has_update:
                    log_info(f"Update available: {current_version} -> {latest_version}", "OTA")
                else:
                    log_info("No update needed - already on latest version", "OTA")
                return has_update, latest_version, release_data

        except Exception as e:
            log_error(f"Update check failed: {e}", "OTA")
            return self._check_updates_fallback()

    def _check_updates_fallback(self):
        """
        Fallback method to check for updates using raw GitHub files.

        Returns:
            tuple: (has_update, new_version, None)
        """
        try:
            print("Trying fallback update check using raw files...")

            # Try to get version from raw GitHub file
            version_url = f"{self.raw_base}/{self.branch}/version.txt"

            success, response_or_error = self._make_request(version_url)

            if not success:
                print(f"Fallback also failed: {response_or_error}")
                return False, None, None

            try:
                latest_version = response_or_error.text.strip()
                response_or_error.close()
            except Exception as e:
                print(f"Failed to read version from raw file: {e}")
                response_or_error.close()
                return False, None, None

            current_version = self.get_current_version()

            print(f"Fallback - Current version: {current_version}")
            print(f"Fallback - Latest version: {latest_version}")

            # Add 'v' prefix if not present for comparison
            if not latest_version.startswith('v'):
                latest_version = f"v{latest_version}"
            if not current_version.startswith('v'):
                current_version = f"v{current_version}"

            has_update = latest_version != current_version
            return has_update, latest_version, None

        except Exception as e:
            print(f"Fallback update check failed: {e}")
            return False, None, None

    def download_file(self, filename, target_dir=""):
        """
        Download a file from GitHub with improved error handling and memory management.
        Uses streaming download for large files to prevent memory allocation failures.

        Args:
            filename (str): Name of file to download.
            target_dir (str): Directory to save file in (default: current dir).

        Returns:
            bool: True if download successful, False otherwise.
        """
        try:
            # Construct the correct URL for firmware files
            if filename in ["main.py", "config.py", "ota_updater.py", "device_config.py", "logger.py", "version.txt"]:
                url = f"{self.raw_base}/{self.branch}/firmware/{filename}"
            else:
                url = f"{self.raw_base}/{self.branch}/{filename}"

            log_info(f"Downloading {filename} from {url}", "OTA")

            # Check memory before download
            gc.collect()
            free_mem_before = gc.mem_free()
            log_debug(f"Free memory before download: {free_mem_before}", "OTA")

            # First, get file size using HEAD request to determine download strategy
            file_size = self._get_file_size(url)

            # Use streaming download for files larger than 20KB or if size unknown
            use_streaming = file_size is None or file_size > 20480

            if use_streaming:
                log_info(f"Using streaming download for {filename} (size: {file_size or 'unknown'})", "OTA")
                return self._download_file_streaming(url, filename, target_dir)
            else:
                log_debug(f"Using standard download for {filename} ({file_size} bytes)", "OTA")
                return self._download_file_standard(url, filename, target_dir)

        except Exception as e:
            log_error(f"Download failed for {filename}: {e}", "OTA")
            return False

    def _get_file_size(self, url):
        """
        Get file size using HEAD request to determine download strategy.

        Args:
            url (str): URL to check

        Returns:
            int or None: File size in bytes, or None if unable to determine
        """
        try:
            # Make HEAD request to get content length
            import urequests
            response = urequests.head(url, headers=self._get_headers())

            if response.status_code == 200:
                content_length = response.headers.get('content-length')
                response.close()
                if content_length:
                    return int(content_length)
            else:
                response.close()
        except:
            pass  # Fall back to streaming if HEAD request fails

        return None

    def _download_file_streaming(self, url, filename, target_dir=""):
        """
        Download a file using streaming to handle large files with limited memory.

        Args:
            url (str): URL to download from
            filename (str): Name of file to download
            target_dir (str): Directory to save file in

        Returns:
            bool: True if download successful, False otherwise
        """
        try:
            # Use improved request method with proper headers and retries
            success, response_or_error = self._make_request(url)

            if not success:
                log_error(f"Failed to download {filename}: {response_or_error}", "OTA")
                return False

            try:
                target_path = f"{target_dir}/{filename}" if target_dir else filename
                temp_path = f"{target_path}.tmp"

                # Stream download in chunks
                chunk_size = 2048  # 2KB chunks to minimize memory usage
                total_bytes = 0

                log_debug(f"Starting streaming download of {filename} in {chunk_size} byte chunks", "OTA")

                with open(temp_path, "w") as f:
                    # Read response content in chunks
                    content = response_or_error.text

                    # For text content, we still need to handle it as a whole
                    # but we can write it in chunks to reduce memory pressure
                    content_size = len(content)

                    # Validate content is not empty or error page
                    if content_size == 0:
                        log_error(f"Downloaded {filename} is empty", "OTA")
                        response_or_error.close()
                        return False

                    # Check if content looks like an error page
                    if content.strip().startswith('<!DOCTYPE html>') or content.strip().startswith('<html'):
                        log_error(f"Downloaded {filename} appears to be an error page", "OTA")
                        response_or_error.close()
                        return False

                    # Write content in chunks to reduce memory pressure
                    for i in range(0, content_size, chunk_size):
                        chunk = content[i:i + chunk_size]
                        f.write(chunk)
                        total_bytes += len(chunk)

                        # Force garbage collection every few chunks
                        if i % (chunk_size * 4) == 0:  # Every 8KB
                            gc.collect()
                            free_mem = gc.mem_free()
                            log_debug(f"Streaming progress: {total_bytes}/{content_size} bytes, free memory: {free_mem}", "OTA")

                response_or_error.close()

                # Force garbage collection after download
                gc.collect()

                # Atomic rename
                try:
                    os.rename(temp_path, target_path)
                except OSError:
                    # On some systems, need to remove target first
                    try:
                        os.remove(target_path)
                    except OSError:
                        pass
                    os.rename(temp_path, target_path)

                # Verify file was written correctly
                if not self._file_exists(target_path):
                    log_error(f"File {target_path} was not created successfully", "OTA")
                    return False

                # Check memory after download
                gc.collect()
                free_mem_after = gc.mem_free()
                log_debug(f"Free memory after streaming download: {free_mem_after}", "OTA")

                log_info(f"Downloaded {filename} successfully using streaming ({total_bytes} bytes)", "OTA")
                return True

            except Exception as e:
                log_error(f"Failed to write {filename} during streaming: {e}", "OTA")
                response_or_error.close()

                # Clean up temp file if it exists
                temp_path = f"{target_dir}/{filename}.tmp" if target_dir else f"{filename}.tmp"
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

                return False

        except Exception as e:
            log_error(f"Streaming download failed for {filename}: {e}", "OTA")
            return False

    def _download_file_standard(self, url, filename, target_dir=""):
        """
        Download a small file using the standard method (load entire content into memory).

        Args:
            url (str): URL to download from
            filename (str): Name of file to download
            target_dir (str): Directory to save file in

        Returns:
            bool: True if download successful, False otherwise
        """
        try:
            # Use improved request method with proper headers and retries
            success, response_or_error = self._make_request(url)

            if not success:
                log_error(f"Failed to download {filename}: {response_or_error}", "OTA")
                return False

            try:
                # Check response content
                if not hasattr(response_or_error, 'text'):
                    log_error(f"Invalid response for {filename}: no text content", "OTA")
                    response_or_error.close()
                    return False

                content = response_or_error.text
                content_size = len(content)
                log_debug(f"Downloaded {filename}: {content_size} bytes", "OTA")

                # Validate content is not empty or error page
                if content_size == 0:
                    log_error(f"Downloaded {filename} is empty", "OTA")
                    response_or_error.close()
                    return False

                # Check if content looks like an error page (GitHub 404 returns HTML)
                if content.strip().startswith('<!DOCTYPE html>') or content.strip().startswith('<html'):
                    log_error(f"Downloaded {filename} appears to be an error page", "OTA")
                    response_or_error.close()
                    return False

                # Write file atomically
                target_path = f"{target_dir}/{filename}" if target_dir else filename
                temp_path = f"{target_path}.tmp"

                with open(temp_path, "w") as f:
                    f.write(content)

                # Atomic rename
                try:
                    os.rename(temp_path, target_path)
                except OSError:
                    # On some systems, need to remove target first
                    try:
                        os.remove(target_path)
                    except OSError:
                        pass
                    os.rename(temp_path, target_path)

                response_or_error.close()

                # Verify file was written correctly
                if not self._file_exists(target_path):
                    log_error(f"File {target_path} was not created successfully", "OTA")
                    return False

                # Check memory after download
                gc.collect()
                free_mem_after = gc.mem_free()
                log_debug(f"Free memory after download: {free_mem_after}", "OTA")

                log_info(f"Downloaded {filename} successfully ({content_size} bytes)", "OTA")
                return True

            except Exception as e:
                log_error(f"Failed to write {filename}: {e}", "OTA")
                response_or_error.close()

                # Clean up temp file if it exists
                temp_path = f"{target_dir}/{filename}.tmp" if target_dir else f"{filename}.tmp"
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

                return False

        except Exception as e:
            log_error(f"Standard download failed for {filename}: {e}", "OTA")
            return False

    def backup_files(self):
        """
        Backup current files before update.

        Returns:
            bool: True if backup successful, False otherwise.
        """
        if not self.backup_enabled:
            return True

        try:
            print("Backing up current files...")
            for filename in self.update_files:
                if self._file_exists(filename):
                    backup_path = f"{self.backup_dir}/{filename}.bak"
                    self._copy_file(filename, backup_path)
                    print(f"Backed up {filename}")
            return True

        except Exception as e:
            print(f"Backup failed: {e}")
            return False

    def restore_backup(self):
        """
        Restore files from backup.

        Returns:
            bool: True if restore successful, False otherwise.
        """
        if not self.backup_enabled:
            return False

        try:
            print("Restoring from backup...")
            for filename in self.update_files:
                backup_path = f"{self.backup_dir}/{filename}.bak"
                if self._file_exists(backup_path):
                    self._copy_file(backup_path, filename)
                    print(f"Restored {filename}")
            return True

        except Exception as e:
            print(f"Restore failed: {e}")
            return False

    def download_firmware_package(self, version, release_info):
        """
        Download complete firmware package from GitHub release.

        Args:
            version (str): Version being downloaded.
            release_info (dict): Release information from GitHub API.

        Returns:
            bool: True if firmware package downloaded and extracted successfully.
        """
        try:
            log_info(f"Downloading firmware package for version {version}", "OTA")

            # Clean temp directory
            self._clean_directory(self.temp_dir)

            # Find firmware package in release assets
            firmware_asset = None
            if release_info and "assets" in release_info:
                for asset in release_info["assets"]:
                    if asset["name"].startswith("firmware-") and asset["name"].endswith(".zip"):
                        firmware_asset = asset
                        break

            if not firmware_asset:
                log_error("No firmware package found in release assets", "OTA")
                return False

            # Download firmware package
            package_url = firmware_asset["browser_download_url"]
            log_info(f"Downloading firmware package from: {package_url}", "OTA")

            success, response_or_error = self._make_request(package_url)
            if not success:
                log_error(f"Failed to download firmware package: {response_or_error}", "OTA")
                return False

            # Save zip file
            zip_path = f"{self.temp_dir}/firmware.zip"
            try:
                with open(zip_path, "wb") as f:
                    f.write(response_or_error.content)
                response_or_error.close()
                log_info("Firmware package downloaded successfully", "OTA")
            except Exception as e:
                log_error(f"Failed to save firmware package: {e}", "OTA")
                response_or_error.close()
                return False

            # Extract firmware package
            if not self._extract_firmware_package(zip_path):
                return False

            log_info("Firmware package extracted successfully", "OTA")
            return True

        except Exception as e:
            log_error(f"Firmware package download failed: {e}", "OTA")
            return False

    def _extract_firmware_package(self, zip_path):
        """
        Extract firmware package and discover files to update.

        Args:
            zip_path (str): Path to firmware zip file.

        Returns:
            bool: True if extraction successful.
        """
        try:
            log_info("Extracting firmware package", "OTA")

            # Simple zip extraction for MicroPython
            # Note: MicroPython doesn't have zipfile module, so we'll use a basic approach
            # For now, we'll fall back to individual file downloads if zip extraction fails

            # Try to use uzlib if available for zip extraction
            try:
                import uzlib
                # Basic zip extraction logic would go here
                # For simplicity, we'll fall back to the file-by-file approach
                log_warn("Zip extraction not implemented, falling back to file-by-file download", "OTA")
                return self._download_files_individually()
            except ImportError:
                log_warn("uzlib not available, falling back to file-by-file download", "OTA")
                return self._download_files_individually()

        except Exception as e:
            log_error(f"Firmware package extraction failed: {e}", "OTA")
            return False

    def _download_files_individually(self):
        """
        Fallback method to download files individually from GitHub raw.

        Returns:
            bool: True if all files downloaded successfully.
        """
        try:
            log_info("Downloading firmware files individually", "OTA")

            # Get list of files from GitHub repository
            files_to_download = self._discover_firmware_files()
            if not files_to_download:
                log_error("No firmware files discovered", "OTA")
                return False

            # Update our file list for backup/restore
            self.update_files = files_to_download

            log_info(f"Starting download of {len(files_to_download)} files", "OTA")

            # Download each file with progress tracking
            downloaded_count = 0
            for i, filename in enumerate(files_to_download, 1):
                log_info(f"Downloading file {i}/{len(files_to_download)}: {filename}", "OTA")

                # Force garbage collection before each download
                gc.collect()
                free_mem = gc.mem_free()
                log_debug(f"Free memory before downloading {filename}: {free_mem}", "OTA")

                if not self.download_file(filename, self.temp_dir):
                    log_error(f"Failed to download {filename} (file {i}/{len(files_to_download)})", "OTA")
                    return False

                downloaded_count += 1
                log_info(f"Successfully downloaded {filename} ({downloaded_count}/{len(files_to_download)})", "OTA")

                # Small delay between downloads to avoid overwhelming the network/GitHub
                if i < len(files_to_download):  # Don't delay after the last file
                    time.sleep(0.5)

            log_info(f"Successfully downloaded all {downloaded_count} firmware files", "OTA")
            return True

        except Exception as e:
            log_error(f"Individual file download failed: {e}", "OTA")
            return False

    def _discover_firmware_files(self):
        """
        Discover firmware files from GitHub repository.

        Returns:
            list: List of firmware files to download (excluding secrets.py).
        """
        try:
            log_debug("Discovering firmware files from repository", "OTA")

            # Get repository contents for firmware directory
            contents_url = f"{self.api_base}/contents/firmware"
            success, response_or_error = self._make_request(contents_url)

            if not success:
                log_warn(f"Failed to get repository contents: {response_or_error}", "OTA")
                # Fallback to known essential files
                return ["main.py", "config.py", "ota_updater.py", "device_config.py", "logger.py", "version.txt"]

            try:
                contents_data = response_or_error.json()
                response_or_error.close()
            except Exception as e:
                log_error(f"Failed to parse contents response: {e}", "OTA")
                response_or_error.close()
                return ["main.py", "config.py", "ota_updater.py", "device_config.py", "logger.py", "version.txt"]

            # Extract firmware files (exclude secrets.py for security)
            firmware_files = []
            for item in contents_data:
                if item["type"] == "file":
                    filename = item["name"]
                    # Include .py files and version.txt, but exclude secrets.py
                    if (filename.endswith(".py") or filename == "version.txt") and filename != "secrets.py":
                        firmware_files.append(filename)

            log_info(f"Discovered {len(firmware_files)} firmware files: {firmware_files}", "OTA")
            return firmware_files

        except Exception as e:
            log_error(f"File discovery failed: {e}", "OTA")
            # Return essential files as fallback
            return ["main.py", "config.py", "ota_updater.py", "device_config.py", "logger.py", "version.txt"]

    def download_update(self, version, release_info=None):
        """
        Download firmware update using package-based approach.

        Args:
            version (str): Version being downloaded.
            release_info (dict): Release information from GitHub API.

        Returns:
            bool: True if all files downloaded successfully.
        """
        try:
            log_info(f"Starting firmware download for version {version}", "OTA")

            # Try package-based download first
            if release_info and self.download_firmware_package(version, release_info):
                return True

            # Fallback to individual file download
            log_warn("Package download failed, trying individual file download", "OTA")
            return self._download_files_individually()

        except Exception as e:
            log_error(f"Update download failed: {e}", "OTA")
            return False

    def apply_update(self, version):
        """
        Apply the downloaded update atomically.

        Args:
            version (str): Version being applied.

        Returns:
            bool: True if update applied successfully.
        """
        try:
            print(f"Applying update to version {version}...")

            # Backup current files
            if not self.backup_files():
                print("Backup failed, aborting update")
                return False

            # Move temp files to main location
            for filename in self.update_files:
                temp_path = f"{self.temp_dir}/{filename}"
                if self._file_exists(temp_path):
                    self._copy_file(temp_path, filename)
                    print(f"Updated {filename}")

            # Update version
            self.set_current_version(version)

            # Clean temp directory
            self._clean_directory(self.temp_dir)

            print(f"Update to version {version} completed successfully")
            return True

        except Exception as e:
            print(f"Update application failed: {e}")
            print("Attempting to restore backup...")
            self.restore_backup()
            return False

    def perform_update(self):
        """
        Perform complete update process: check, download, and apply.

        Returns:
            bool: True if update completed successfully.
        """
        try:
            # Check for updates
            has_update, new_version, release_info = self.check_for_updates()

            if not has_update:
                print("No updates available")
                return False

            print(f"Update available: {new_version}")

            # Download update
            if not self.download_update(new_version):
                print("Failed to download update")
                return False

            # Apply update
            if not self.apply_update(new_version):
                print("Failed to apply update")
                return False

            print("Update completed successfully. Restarting...")
            gc.collect()  # Clean up memory before restart
            machine.reset()  # Restart device

        except Exception as e:
            print(f"Update process failed: {e}")
            return False

    def _file_exists(self, filepath):
        """Check if a file exists"""
        try:
            os.stat(filepath)
            return True
        except OSError:
            return False

    def _copy_file(self, src, dst):
        """Copy a file from src to dst"""
        with open(src, "r") as src_file:
            content = src_file.read()
        with open(dst, "w") as dst_file:
            dst_file.write(content)

    def _clean_directory(self, directory):
        """Remove all files from a directory"""
        try:
            for filename in os.listdir(directory):
                filepath = f"{directory}/{filename}"
                os.remove(filepath)
        except OSError:
            pass  # Directory might not exist or be empty

    def get_update_status(self):
        """
        Get current update status information.

        Returns:
            dict: Status information including current version, last check, etc.
        """
        try:
            from device_config import get_ota_config
            ota_config = get_ota_config()
            ota_enabled = ota_config.get("enabled", True)
            auto_check = ota_config.get("auto_update", True)
        except Exception:
            # Fallback if dynamic config fails
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
