from backups import BackupManager

def main():
    backup_manager = BackupManager()

    # GitLab Backup (Runs `gitlab-backup create` Automatically)
    backup_manager.run_backup(backup_name="gitlab", method="gitlab")

    # Jenkins Backup (Creates a `.tar.gz` of Jenkins directories)
    JENKINS_DIRECTORIES = [
        "/var/lib/jenkins"
    ]
    backup_manager.run_backup("jenkins", method="directory", directories=JENKINS_DIRECTORIES)

if __name__ == "__main__":
    main()
