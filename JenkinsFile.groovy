pipeline {
    agent any
    
    stages {
        stage('Create GitLab Backup') {
            steps {
                script {
                    withCredentials([
                        string(credentialsId: 'BACKUP_HOST_IP', variable: 'SERVER_HOST'),
                        string(credentialsId: 'BACKUP_SERVER_USER', variable: 'SERVER_USER'),
                        file(credentialsId: 'BACKUP_SERVER_KEY', variable: 'SSH_KEY_PATH'),
                        string(credentialsId: 'BACKUP_SERVER_PORT', variable: 'SSH_PORT')
                    ]) {
                        // First check if the directory and script exist
                        def checkDirCmd = """
                            ssh -i "$SSH_KEY_PATH" -p "$SSH_PORT" \
                                -o StrictHostKeyChecking=no \
                                -o UserKnownHostsFile=/dev/null \
                                "$SERVER_USER@$SERVER_HOST" \
                                "[ -d /home/$SERVER_USER/backups ] && [ -f /home/$SERVER_USER/backups/main.py ] && echo 'EXISTS' || echo 'NOT_EXISTS'"
                        """
                        
                        def dirExists = sh(script: checkDirCmd, returnStdout: true).trim()
                        
                        if (dirExists == 'NOT_EXISTS') {
                            // If directory or script doesn't exist, rsync the files
                            echo "Backup directory or scripts not found. Copying files with rsync..."
                            sh """
                                rsync -avz --delete --exclude='.git/' --exclude='.github/' \
                                -e "ssh -i \$SSH_KEY_PATH -p \$SSH_PORT -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null" \
                                ./backup_scripts/ \
                                \${SERVER_USER}@\${SERVER_HOST}:/home/\${SERVER_USER}/backups/
                            """
                            
                            // Execute the backup script with full path after copying
                            sh """
                                ssh -i "$SSH_KEY_PATH" -p "$SSH_PORT" \
                                    -o StrictHostKeyChecking=no \
                                    -o UserKnownHostsFile=/dev/null \
                                    "$SERVER_USER@$SERVER_HOST" \
                                    "cd /home/$SERVER_USER/backups && sudo -n python3 main.py"
                            """
                        } else {
                            // If directory exists, use the original command format
                            echo "Backup directory and scripts found. Executing backup..."
                            sh """
                                ssh -i "$SSH_KEY_PATH" -p "$SSH_PORT" \
                                    -o StrictHostKeyChecking=no \
                                    -o UserKnownHostsFile=/dev/null \
                                    "$SERVER_USER@$SERVER_HOST" \
                                    "cd backups && sudo python3 main.py"
                            """
                        }
                    }
                }
            }
        }
    }
}