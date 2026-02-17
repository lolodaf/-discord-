import requests
import json
import os

# 从 GitHub Secrets 读取配置
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
DINGTALK_URL = os.getenv("DINGTALK_URL")
LAST_MSG_FILE = "last_msg_id.txt"

def get_discord_msg():
    # 获取最新一条消息
    url = f"https://discord.com/api/v9/channels/{CHANNEL_ID}/messages?limit=1"
    headers = {"Authorization": DISCORD_TOKEN, "Content-Type": "application/json"}
    try:
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            return res.json()[0]
        else:
            print(f"获取失败，状态码: {res.status_code}, 响应: {res.text}")
    except Exception as e:
        print(f"请求报错: {e}")
    return None

def send_dingtalk(content):
    headers = {"Content-Type": "application/json"}
    # 关键词必须包含你在钉钉设置的词，这里用了 "监控"
    data = {
        "msgtype": "text",
        "text": {
            "content": f"[Discord监控]\n{content}"
        }
    }
    requests.post(DINGTALK_URL, headers=headers, data=json.dumps(data))

# 主程序
msg = get_discord_msg()
if msg:
    msg_id = msg['id']
    content = msg.get('content', '[图片/文件]')
    author = msg.get('author', {}).get('username', '未知')
    
    # 检查是否是新消息
    if os.path.exists(LAST_MSG_FILE):
        with open(LAST_MSG_FILE, "r") as f:
            last_id = f.read().strip()
    else:
        last_id = ""

    if msg_id != last_id:
        print(f"新消息: {content}")
        send_dingtalk(f"用户: {author}\n内容: {content}")
        # 保存 ID
        with open(LAST_MSG_FILE, "w") as f:
            f.write(msg_id)
    else:
        print("无新消息")
