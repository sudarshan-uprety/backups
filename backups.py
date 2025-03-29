import os
import subprocess
import logging
import json
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

class BackupManager:
    def __init__(self, google_drive_folder_id):
        logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
        self.logger = logging.getLogger(__name__)
        self.google_drive_folder_id = google_drive_folder_id

    def create_gitlab_backup(self):
        """
        Runs `gitlab-backup create` to generate a backup.
        Finds and returns the latest GitLab backup file.
        """
        try:
            backup_directory = '/var/opt/gitlab/backups'
            # Run GitLab backup with sudo
            subprocess.run(['sudo', 'gitlab-backup', 'create'], check=True)

            # Find the most recent backup
            backups = [
                os.path.join(backup_directory, f)
                for f in os.listdir(backup_directory)
                if f.endswith('_gitlab_backup.tar')
            ]
            # Sort backups by creation time
            backups.sort(key=os.path.getctime, reverse=True)

            # Remove older backups
            for backup in backups[1:]:
                try:
                    os.remove(backup)
                    self.logger.info(f"Removed old backup: {backup}")
                except PermissionError:
                    self.logger.warning(f"Permission denied when removing: {backup}")

            return backups[0] # returning the latest backup

        except subprocess.CalledProcessError as e:
            self.logger.error(f"Backup creation failed: {e}")
            raise

    def create_directory_backup(self, backup_name, directories):
        """
        Creates a `.tar.gz` archive for the given directories.

        :param backup_name: Name of the service being backed up (e.g., 'jenkins')
        :param directories: List of directories to include in the archive
        :return: Path to the created backup file
        """
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            backup_file = f"/var/backups/{backup_name}_backup_{timestamp}.tar.gz"
            os.makedirs(os.path.dirname(backup_file), exist_ok=True)

            # Ensure at least one valid directory exists
            existing_dirs = [d for d in directories if os.path.exists(d)]
            if not existing_dirs:
                raise FileNotFoundError(f"No valid directories found for {backup_name} backup.")

            # Create the tar.gz archive
            subprocess.run(["sudo", "tar", "-czf", backup_file] + existing_dirs, check=True)
            self.logger.info(f"{backup_name.capitalize()} backup created: {backup_file}")

            # 🔥 Inline cleanup of old backups (keep only the latest one)
            backups = [
                os.path.join("/var/backups", f)
                for f in os.listdir("/var/backups")
                if f.startswith(f"{backup_name}_backup_") and f.endswith(".tar.gz")
            ]

            # Sort backups by creation time (newest first)
            backups.sort(key=os.path.getctime, reverse=True)

            # Remove older backups (keep only the latest one)
            for old_backup in backups[1:]:  # Skip index 0 (most recent)
                try:
                    os.remove(old_backup)
                    self.logger.info(f"Removed old backup: {old_backup}")
                except PermissionError:
                    self.logger.warning(f"Permission denied when removing: {old_backup}")

            return backup_file
        except subprocess.CalledProcessError as e:
            self.logger.error(f"{backup_name.capitalize()} backup failed: {e}")
            raise

    def upload_to_google_drive(self, file_path):
        """
        Uploads a backup file to Google Drive.

        :param file_path: Path to the backup file
        :return: Google Drive file ID
        """
        try:
            google_credentials_json_path = "cred.json"

            with open(google_credentials_json_path, "r") as f:
                credentials_dict = json.load(f)

            credentials = service_account.Credentials.from_service_account_info(
                credentials_dict,
                scopes=["https://www.googleapis.com/auth/drive.file"]
            )
            drive_service = build("drive", "v3", credentials=credentials)

            self.delete_old_drive_backups(drive_service)

            file_metadata = {
                "name": os.path.basename(file_path),
                "parents": [self.google_drive_folder_id]
            }

            media = MediaFileUpload(file_path, resumable=True)
            file = drive_service.files().create(body=file_metadata, media_body=media, fields="id").execute()

            self.logger.info(f"File uploaded successfully. File ID: {file.get('id')}")
            return file.get("id")
        except Exception as e:
            self.logger.error(f"Google Drive upload failed: {e}")
            raise

    def delete_old_drive_backups(self, drive_service):
        """
        Deletes all old backups from Google Drive, keeping only the latest one.
        """
        try:
            query = f"'{self.google_drive_folder_id}' in parents and trashed=false"
            results = drive_service.files().list(q=query, fields="files(id, name, createdTime)", pageSize=1000).execute()
            files = results.get("files", [])

            if not files:
                self.logger.info("No backup files found in Google Drive.")
                return

            files.sort(key=lambda x: x["createdTime"], reverse=True)
            self.logger.info(f"Keeping latest backup: {files[0]['name']} (ID: {files[0]['id']})")

            for file in files[1:]:
                try:
                    drive_service.files().delete(fileId=file["id"]).execute()
                    self.logger.info(f"Deleted old backup: {file['name']} (ID: {file['id']})")
                except Exception as e:
                    self.logger.warning(f"Failed to delete {file['name']}: {e}")

        except Exception as e:
            self.logger.error(f"Error deleting old backups from Google Drive: {e}")

    def cleanup_old_local_backups(self, backup_dir, backup_name, pattern=None):
        """
        Deletes old backup files, keeping only the most recent one.

        :param backup_dir: Directory where backups are stored
        :param backup_name: Prefix of the backup files to filter them
        :param pattern: Optional custom pattern for backup files (e.g., '_gitlab_backup.tar')
        """
        try:
            # Default pattern for Jenkins: "{backup_name}_backup_YYYY-MM-DD_HH-MM-SS.tar.gz"
            if not pattern:
                pattern = f"{backup_name}_backup_"

            # Find all matching backups
            backups = [
                os.path.join(backup_dir, f) for f in os.listdir(backup_dir)
                if f.startswith(pattern) and (f.endswith(".tar.gz") or f.endswith("_gitlab_backup.tar"))
            ]

            # Sort backups by creation time (newest first)
            backups.sort(key=os.path.getctime, reverse=True)

            # Delete all except the latest one
            for backup in backups[1:]:  # Keep only the first (most recent)
                try:
                    os.remove(backup)
                    self.logger.info(f"Deleted old backup: {backup}")
                except PermissionError:
                    self.logger.warning(f"Permission denied when removing: {backup}")

        except Exception as e:
            self.logger.error(f"Failed to clean up old backups: {e}")

    def run_backup(self, backup_name, method, directories=None):
        """
        Runs the full backup process (backup + upload).

        :param backup_name: Name of the backup (e.g., 'gitlab' or 'jenkins')
        :param method: 'gitlab' for GitLab backups, 'directory' for directory-based backups
        :param directories: List of directories (only required for 'directory' method)
        """
        try:
            if method == "gitlab":
                backup_file = self.create_gitlab_backup()
            elif method == "directory":
                if not directories:
                    raise ValueError("No directories provided for directory backup.")
                backup_file = self.create_directory_backup(backup_name, directories)
            else:
                raise ValueError("Invalid backup method. Use 'gitlab' or 'directory'.")

            # Upload backup file to Google Drive
            self.upload_to_google_drive(backup_file)

        except Exception as e:
            self.logger.error(f"{backup_name.capitalize()} backup process failed: {e}")
            raise
