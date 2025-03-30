import os
import subprocess
import logging
import json
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

class BackupManager:
    def __init__(self):
        logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
        self.logger = logging.getLogger(__name__)

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
            
            if not backups:
                raise FileNotFoundError("No GitLab backup files found after backup creation")
                
            # Sort backups by creation time
            backups.sort(key=os.path.getctime, reverse=True)
            latest_backup = backups[0]

            # Remove older backups locally
            for backup in backups[1:]:
                try:
                    subprocess.run(['sudo', 'rm', backup], check=True)
                    self.logger.info(f"Removed old backup: {backup}")
                except subprocess.CalledProcessError:
                    self.logger.warning(f"Permission denied when removing: {backup}")

            self.logger.info(f"Latest GitLab backup file: {latest_backup}")
            self.upload_to_google_drive(file_path=latest_backup, google_drive_folder_id='1SNuXyvSqpff3_U2uzDM9ZfVicwMfr8eV')
            
            return latest_backup

        except subprocess.CalledProcessError as e:
            self.logger.error(f"Backup creation failed: {e}")
            raise

    def create_directory_backup(self, backup_name, directories):
        """
        Creates a `.tar.gz` archive for the given directories.
        Stores backups in a dedicated subfolder.

        :param backup_name: Name of the service being backed up (e.g., 'jenkins')
        :param directories: List of directories to include in the archive
        :return: Path to the created backup file
        """
        try:
            # Create backup directory structure
            backup_dir = f"/var/backups/{backup_name}"
            os.makedirs(backup_dir, exist_ok=True)
            
            # Set proper permissions for the backup directory
            subprocess.run(["sudo", "chmod", "755", backup_dir], check=True)
            
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            backup_file = f"{backup_dir}/{backup_name}_backup_{timestamp}.tar.gz"

            # Ensure at least one valid directory exists
            existing_dirs = [d for d in directories if os.path.exists(d)]
            if not existing_dirs:
                raise FileNotFoundError(f"No valid directories found for {backup_name} backup.")
                
            self.logger.info(f"Creating backup for directories: {existing_dirs}")

            # Create the tar.gz archive with correct permissions
            cmd = ["sudo", "tar", "-czf", backup_file] + existing_dirs
            self.logger.info(f"Running command: {' '.join(cmd)}")
            subprocess.run(cmd, check=True)
            
            # Make sure the created file is readable by our process
            subprocess.run(["sudo", "chmod", "644", backup_file], check=True)
            
            self.logger.info(f"{backup_name.capitalize()} backup created: {backup_file}")

            # Cleanup of old backups (keep only the latest one)
            if os.path.exists(backup_dir):
                backups = [
                    os.path.join(backup_dir, f)
                    for f in os.listdir(backup_dir)
                    if f.startswith(f"{backup_name}_backup_") and f.endswith(".tar.gz")
                ]

                # Sort backups by creation time (newest first)
                backups.sort(key=os.path.getctime, reverse=True)
                
                if len(backups) > 1:
                    # Remove older backups (keep only the latest one)
                    for old_backup in backups[1:]:  # Skip index 0 (most recent)
                        try:
                            subprocess.run(["sudo", "rm", old_backup], check=True)
                            self.logger.info(f"Removed old backup: {old_backup}")
                        except subprocess.CalledProcessError as e:
                            self.logger.warning(f"Permission denied when removing: {old_backup} - {e}")
            
            self.logger.info(f"Uploading backup file: {backup_file}")
            self.upload_to_google_drive(file_path=backup_file, google_drive_folder_id='1roM3QbZJs2Ck2eQr3t7Zh5zSWd3Wfs5d')
            
            return backup_file
            
        except subprocess.CalledProcessError as e:
            self.logger.error(f"{backup_name.capitalize()} backup failed: {e}")
            raise

    def upload_to_google_drive(self, file_path, google_drive_folder_id):
        """
        Uploads a backup file to Google Drive and cleans up old backups.
        """
        try:
            self.logger.info(f"Starting Google Drive upload for {file_path}")
            google_credentials_json_path = "cred.json"

            with open(google_credentials_json_path, "r") as f:
                credentials_dict = json.load(f)

            credentials = service_account.Credentials.from_service_account_info(
                credentials_dict,
                scopes=["https://www.googleapis.com/auth/drive.file"]
            )
            drive_service = build("drive", "v3", credentials=credentials)

            # 1. Upload the new file
            file_metadata = {
                "name": os.path.basename(file_path),
                'parents': [google_drive_folder_id] if google_drive_folder_id else []
            }

            media = MediaFileUpload(
                file_path,
                resumable=True
            )

            uploaded_file = drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields="id,name,createdTime"
            ).execute()

            file_id = uploaded_file.get('id')
            file_name = uploaded_file.get('name')
            self.logger.info(f"File uploaded successfully. File ID: {file_id}, Name: {file_name}")
            
            # 2. Add a delay to ensure the file is indexed (3-5 seconds usually sufficient)
            import time
            time.sleep(5)
            
            # 3. Now handle cleanup separately
            self.clean_drive_folder(drive_service, google_drive_folder_id)
            
            return file_id

        except Exception as e:
            self.logger.error(f"Google Drive upload failed: {e}")
            raise


    def clean_drive_folder(self, drive_service, folder_id):
        """
        Separate function to clean up a Google Drive folder, keeping only the most recent file.
        """
        try:
            self.logger.info(f"Cleaning up old backups in Google Drive folder: {folder_id}")
            
            # Get all files in the folder
            query = f"'{folder_id}' in parents and trashed=false"
            results = drive_service.files().list(
                q=query, 
                fields="files(id, name, createdTime)",
                orderBy="createdTime desc"  # Request sorted by creation time (newest first)
            ).execute()
            
            files = results.get("files", [])
            
            if not files:
                self.logger.info("No backup files found in Google Drive.")
                return
                
            self.logger.info(f"Found {len(files)} backups in Google Drive")
            
            # Re-sort to ensure newest first (belt and suspenders approach)
            files.sort(key=lambda x: x['createdTime'], reverse=True)
            
            self.logger.info(f"Keeping latest backup: {files[0]['name']} (ID: {files[0]['id']}, Created: {files[0]['createdTime']})")
            
            # Delete all but the first (newest) file
            if len(files) > 1:
                self.logger.info(f"Deleting {len(files)-1} older backups from Google Drive")
                for file in files[1:]:
                    try:
                        drive_service.files().delete(fileId=file["id"]).execute()
                        self.logger.info(f"Deleted old backup from Drive: {file['name']} (ID: {file['id']}, Created: {file['createdTime']})")
                    except Exception as e:
                        self.logger.warning(f"Failed to delete {file['name']} from Drive: {e}")
        
        except Exception as e:
            self.logger.error(f"Error cleaning up Google Drive folder: {e}")

    def run_backup(self, backup_name, method, directories=None):
        """
        Runs the full backup process (backup + upload).

        :param backup_name: Name of the backup (e.g., 'gitlab' or 'jenkins')
        :param method: 'gitlab' for GitLab backups, 'directory' for directory-based backups
        :param directories: List of directories (only required for 'directory' method)
        """
        try:
            self.logger.info(f"Starting backup process for {backup_name} using {method} method")
            
            if method == "gitlab":
                backup_file = self.create_gitlab_backup()
                self.logger.info(f"GitLab backup completed successfully: {backup_file}")
                
            elif method == "directory":
                if not directories:
                    raise ValueError("No directories provided for directory backup.")
                backup_file = self.create_directory_backup(backup_name, directories)
                self.logger.info(f"Directory backup completed successfully: {backup_file}")
                
            else:
                raise ValueError("Invalid backup method. Use 'gitlab' or 'directory'.")

        except Exception as e:
            self.logger.error(f"{backup_name.capitalize()} backup process failed: {e}")
            raise