
sudo nano /etc/systemd/system/svc-deployment-manager.service


[Unit]
Description=svc-deployment-manager
After=network.target

[Service]
User=usr
WorkingDirectory=/home/usr/svc-deployment-manager
ExecStart=/usr/local/bin/python3 deployment_service.py
Restart=always

[Install]
WantedBy=multi-user.target


sudo ufw allow 1234/tcp
sudo ufw reload

sudo systemctl start svc-deployment-manager
sudo systemctl enable svc-deployment-manager
