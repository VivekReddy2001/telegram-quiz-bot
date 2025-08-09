# 🌐 PythonAnywhere Deployment Guide

## 🚀 Quick Setup

### **1. Get Bot Token from @BotFather**
1. Search `@BotFather` on Telegram
2. Send: `/newbot`
3. Name: "Your Quiz Bot"
4. Username: `yourquizbot_unique123`
5. Copy token: `123456789:ABCdef...`

### **2. PythonAnywhere Setup**

Upload main.py, requirements.txt to Files tab
Open Bash console:
pip3.10 install --user python-telegram-bot==21.6
pip3.10 install --user python-dotenv

Set environment:
echo 'TELEGRAM_BOT_TOKEN=YOUR_ACTUAL_TOKEN_HERE' > .env

Test run:
python3.10 main.py


### **3. Always-On Task (Paid)**
- Tasks → Create task
- Command: `python3.10 /home/username/main.py`
- Enable ✅

### **4. Free Account Alternative**
nohup python3.10 main.py &

## 🔍 Troubleshooting
Verify token:
curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getMe"

Check process:
ps aux | grep main.py

