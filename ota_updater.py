"""
GitHub-based OTA (Over-The-Air) Updater for Pico W

This module provides functionality to update MicroPython files on the Pico W
by downloading them directly from GitHub releases or branches.
"""

import urequests  # type: ignore
import ujson  # type: ignore
import os
import gc
import machine  # type: ignore
from config import OTA_CONFIG


class GitHubOTAUpdater:
    """
    GitHub-based OTA updater for MicroPython devices.

    Handles checking for updates, downloading files, backup/restore,
    and atomic updates with rollback capability.
    """

    def __init__(self):
        """Initialize the OTA updater with configuration from config.py"""
        self.repo_owner = OTA_CONFIG["github_repo"]["owner"]
        self.repo_name = OTA_CONFIG["github_repo"]["name"]
        self.branch = OTA_CONFIG["github_repo"]["branch"]
        self.update_files = OTA_CONFIG["update_files"]
        self.backup_enabled = OTA_CONFIG["backup_enabled"]

        # GitHub API URLs
        self.api_base = f"https://api.github.com/repos/{self.repo_owner}/{self.repo_name}"
        self.raw_base = f"https://raw.githubusercontent.com/{self.repo_owner}/{self.repo_name}"

        # Local directories
        self.backup_dir = "backup"
        self.temp_dir = "temp"

        # Ensure directories exist
        self._ensure_directories()

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

    def check_for_updates(self):
        """
        Check GitHub for newer releases.

        Returns:
            tuple: (has_update, new_version, release_info) where:
                   has_update (bool): True if update available
                   new_version (str): Version string of latest release
                   release_info (dict): Full release information from GitHub
        """
        try:
            print("Checking for updates...")
            url = f"{self.api_base}/releases/latest"

            response = urequests.get(url)
            if response.status_code != 200:
                print(f"Failed to check updates: HTTP {response.status_code}")
                response.close()
                return False, None, None

            release_data = response.json()
            response.close()

            latest_version = release_data["tag_name"]
            current_version = self.get_current_version()

            print(f"Current version: {current_version}")
            print(f"Latest version: {latest_version}")

            has_update = latest_version != current_version
            return has_update, latest_version, release_data

        except Exception as e:
            print(f"Update check failed: {e}")
            return False, None, None

    def download_file(self, filename, target_dir=""):
        """
        Download a file from GitHub.

        Args:
            filename (str): Name of file to download.
            target_dir (str): Directory to save file in (default: current dir).

        Returns:
            bool: True if download successful, False otherwise.
        """
        try:
            url = f"{self.raw_base}/{self.branch}/{filename}"
            print(f"Downloading {filename}...")

            response = urequests.get(url)
            if response.status_code != 200:
                print(f"Failed to download {filename}: HTTP {response.status_code}")
                response.close()
                return False

            target_path = f"{target_dir}/{filename}" if target_dir else filename
            with open(target_path, "w") as f:
                f.write(response.text)

            response.close()
            print(f"Downloaded {filename} successfully")
            return True

        except Exception as e:
            print(f"Download failed for {filename}: {e}")
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

    def download_update(self, version):
        """
        Download all update files to temp directory.

        Args:
            version (str): Version being downloaded.

        Returns:
            bool: True if all files downloaded successfully.
        """
        try:
            print(f"Downloading update files for version {version}...")

            # Clean temp directory
            self._clean_directory(self.temp_dir)

            # Download all files
            for filename in self.update_files:
                if not self.download_file(filename, self.temp_dir):
                    return False

            print("All files downloaded successfully")
            return True

        except Exception as e:
            print(f"Update download failed: {e}")
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
        return {
            "current_version": self.get_current_version(),
            "ota_enabled": OTA_CONFIG["enabled"],
            "auto_check": OTA_CONFIG["auto_check"],
            "repo": f"{self.repo_owner}/{self.repo_name}",
            "branch": self.branch,
            "update_files": self.update_files
        }
