import os
import subprocess
import logging
import json
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

class JenkinsBackupManager:
    def __init__(self, backup_dir="/var/backups/jenkins", google_drive_folder_id=None):
        """
        Initialize Jenkins Backup Manager
        :param backup_dir: Local directory to store backups
        :param google_drive_folder_id: Google Drive folder ID for uploads
        """
        logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
        self.logger = logging.getLogger(__name__)

        self.jenkins_dir = "/var/lib/jenkins"
        self.backup_dir = backup_dir
        self.google_drive_folder_id = google_drive_folder_id

        # Ensure backup directory exists
        os.makedirs(self.backup_dir, exist_ok=True)

    def create_backup(self):
        """
        Create a compressed tar backup of Jenkins data
        :return: Path to the backup file
        """
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            backup_file = os.path.join(self.backup_dir, f"jenkins_backup_{timestamp}.tar.gz")

            # Run tar command to create a backup
            subprocess.run(["sudo", "tar", "-czf", backup_file, self.jenkins_dir], check=True)

            self.logger.info(f"Backup created: {backup_file}")
            return backup_file

        except subprocess.CalledProcessError as e:
            self.logger.error(f"Backup creation failed: {e}")
            raise

    def upload_to_google_drive(self, file_path):
        """
        Upload backup file to Google Drive
        :param file_path: Path to the backup file
        :return: Uploaded file ID
        """
        try:
            google_credentials_json_path = "cred.json"

            # Load credentials from the JSON file
            with open(google_credentials_json_path, "r") as f:
                credentials_dict = json.load(f)

            # Create credentials object
            credentials = service_account.Credentials.from_service_account_info(
                credentials_dict,
                scopes=["https://www.googleapis.com/auth/drive.file"]
            )

            # Create Google Drive service
            drive_service = build("drive", "v3", credentials=credentials)

            # # Delete old backups before uploading a new one
            # self.delete_old_drive_backups(drive_service)

            # Prepare metadata for new file upload
            file_metadata = {
                "name": os.path.basename(file_path),
                'parents': [self.google_drive_folder_id] if self.google_drive_folder_id else []
            }

            # Upload file
            media = MediaFileUpload(
                file_path,
                resumable=True,
                chunksize=1024*1024  # 1 MB chunks
                )
            uploaded_file = drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields="id"
            ).execute()

            self.logger.info(f"File uploaded successfully. File ID: {uploaded_file.get('id')}")
            return uploaded_file.get("id")

        except Exception as e:
            self.logger.error(f"Google Drive upload failed: {e}")
            raise

    def delete_old_drive_backups(self, drive_service):
        """
        Delete all but the latest backup file from Google Drive
        :param drive_service: Google Drive service instance
        """
        try:
            query = f"'{self.google_drive_folder_id}' in parents and trashed=false"
            results = drive_service.files().list(q=query, fields="files(id, name, createdTime)", pageSize=1000).execute()
            files = results.get("files", [])

            if not files:
                self.logger.info("No backup files found in Google Drive.")
                return

            # Sort files by creation time (newest first)
            files.sort(key=lambda x: x["createdTime"], reverse=True)

            # Keep only the latest file, delete the rest
            self.logger.info(f"Keeping latest backup: {files[0]['name']} (ID: {files[0]['id']})")

            for file in files[1:]:  # Skip the newest file
                try:
                    drive_service.files().delete(fileId=file["id"]).execute()
                    self.logger.info(f"✅ Deleted old backup: {file['name']} (ID: {file['id']})")
                except Exception as e:
                    self.logger.warning(f"⚠️ Failed to delete {file['name']}: {e}")

        except Exception as e:
            self.logger.error(f"❌ Error deleting old backups from Google Drive: {e}")

    def run(self):
        """
        Execute the complete backup process
        """
        try:
            # Create Jenkins backup
            backup_file = self.create_backup()

            # Upload to Google Drive
            # self.upload_to_google_drive(backup_file)

        except Exception as e:
            self.logger.error(f"Backup process failed: {e}")
            raise

def main():
    GOOGLE_DRIVE_FOLDER_ID = "1roM3QbZJs2Ck2eQr3t7Zh5zSWd3Wfs5d"
    # Initialize and run the backup manager
    backup_manager = JenkinsBackupManager(google_drive_folder_id=GOOGLE_DRIVE_FOLDER_ID)
    backup_manager.run()

if __name__ == "__main__":
    main()
