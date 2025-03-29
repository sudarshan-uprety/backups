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
                        // SSH to create GitLab backup
                        def BACKUP_DIR = '/var/opt/gitlab/backups'
                        sh """
                            ssh -t -i "$SSH_KEY_PATH" -p "$SSH_PORT" \
                                -o StrictHostKeyChecking=no \
                                -o UserKnownHostsFile=/dev/null \
                                "$SERVER_USER@$SERVER_HOST" \
                                "cd backups && sudo -n python3 gitlab_backups.py"
                        """
                    }
                }
            }
        }
    }
}