import os
import subprocess
import logging
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import json

class GitLabBackupManager:
    def __init__(self,
                 backup_dir='/var/opt/gitlab/backups',
                 google_drive_folder_id=None):
        """
        Initialize GitLab Backup Manager

        :param backup_dir: Directory where GitLab stores backups
        :param google_drive_folder_id: Google Drive folder ID for uploads
        """
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)

        self.backup_dir = backup_dir
        self.google_drive_folder_id = google_drive_folder_id

    def create_gitlab_backup(self):
        """
        Create GitLab backup

        :return: Path to the latest backup file
        """
        try:
            # Run GitLab backup with sudo
            subprocess.run(['sudo', 'gitlab-backup', 'create'], check=True)

            # Find the most recent backup
            backups = [
                os.path.join(self.backup_dir, f)
                for f in os.listdir(self.backup_dir)
                if f.endswith('_gitlab_backup.tar')
            ]

            if not backups:
                raise ValueError("No backup files found")

            latest_backup = max(backups, key=os.path.getctime)
            self.logger.info(f"Backup created: {latest_backup}")

            return latest_backup

        except subprocess.CalledProcessError as e:
            self.logger.error(f"Backup creation failed: {e}")
            raise

    def upload_to_google_drive(self, file_path):
        """
        Upload file to Google Drive using environment variables

        :param file_path: Path to the file to upload
        :return: Uploaded file ID
        """
        try:
            google_credentials_json_path = 'cred.json'
            # Load credentials from the JSON file
            with open(google_credentials_json_path, 'r') as f:
                credentials_dict = json.load(f)

            # Create credentials object
            credentials = service_account.Credentials.from_service_account_info(
                credentials_dict,
                scopes=['https://www.googleapis.com/auth/drive.file']
            )

            # Create Drive service
            drive_service = build('drive', 'v3', credentials=credentials)

            # Prepare file metadata
            file_metadata = {
                'name': os.path.basename(file_path),
                'parents': [self.google_drive_folder_id] if self.google_drive_folder_id else []
            }

            # Create resumable media upload
            media = MediaFileUpload(
                file_path,
                resumable=True,
                chunksize=1024*1024  # 1 MB chunks
            )

            # Execute upload
            uploaded_file = drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()

            self.logger.info(f"File uploaded successfully. File ID: {uploaded_file.get('id')}")

            # List all files in the target folder
            query = f"'{self.google_drive_folder_id}' in parents and trashed=false"
            results = drive_service.files().list(q=query, fields="files(id, name, createdTime)").execute()
            files = results.get('files', [])

            # Sort files by createdTime (newest first)
            files.sort(key=lambda x: x['createdTime'], reverse=True)

            self.logger.info(f"Started deleting old backups.")

            self.logger.info(f"Skipping the deleting latest backup: {uploaded_file.get('id')})")
            for file in files[1:]:  # Skip index 0 (most recent)
                try:
                    drive_service.files().delete(fileId=file['id']).execute()
                    self.logger.info(f"Deleted old backup: {file['name']} (ID: {file['id']})")
                except Exception as e:
                    self.logger.warning(f"Failed to delete {file['name']}: {e}")

            return uploaded_file.get('id')

        except Exception as e:
            self.logger.error(f"Google Drive upload failed: {e}")
            raise

    def cleanup_old_backups(self, keep_last=1):
        """
        Remove old backup files

        :param keep_last: Number of recent backups to keep
        """
        try:
            # Get all backup files
            backups = [
                os.path.join(self.backup_dir, f)
                for f in os.listdir(self.backup_dir)
                if f.endswith('_gitlab_backup.tar')
            ]
            # Sort backups by creation time
            backups.sort(key=os.path.getctime, reverse=True)

            # Remove older backups
            for backup in backups[keep_last:]:
                try:
                    os.remove(backup)
                    self.logger.info(f"Removed old backup: {backup}")
                except PermissionError:
                    self.logger.warning(f"Permission denied when removing: {backup}")

        except Exception as e:
            self.logger.error(f"Backup cleanup failed: {e}")

    def run(self):
        """
        Execute complete backup process
        """
        try:
            # Create backup
            backup_file = self.create_gitlab_backup()

            # Upload to Google Drive
            self.upload_to_google_drive(backup_file)

            # Cleanup old backups
            self.cleanup_old_backups()

        except Exception as e:
            self.logger.error(f"Backup process failed: {e}")
            raise

def main():
    # Configuration via environment variables
    BACKUP_DIR = '/var/opt/gitlab/backups'
    GOOGLE_DRIVE_FOLDER_ID = '1SNuXyvSqpff3_U2uzDM9ZfVicwMfr8eV'

    # Initialize and run backup manager
    backup_manager = GitLabBackupManager(
        backup_dir=BACKUP_DIR,
        google_drive_folder_id=GOOGLE_DRIVE_FOLDER_ID
    )

    backup_manager.run()

if __name__ == '__main__':
    main()