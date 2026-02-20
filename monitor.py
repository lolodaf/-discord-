import requests
import json
import os
import time
import threading
from flask import Flask

# --- 配置加载与清洗模块 ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
history = {}

def clean_ids(raw_input):
    """清洗频道ID字符串，处理中文逗号和空格"""
    if not raw_input: return []
    if "，" in raw_input: raw_input = raw_input.replace("，", ",")
    clean_ids = ["".join(filter(str.isdigit, raw_id)) for raw_id in raw_input.split(",")]
    return [cid for cid in clean_ids if cid]

def load_config():
    """动态加载多组频道和对应的钉钉机器人"""
    config_list = []
    
    # 兼容老的写法（如果没有数字后缀）
    ch_env = os.getenv("CHANNEL_ID")
    webhook = os.getenv("DINGTALK_URL")
    if ch_env and webhook:
        config_list.append({"channels": clean_ids(ch_env), "webhook": webhook})
        
    # 自动扫描带数字的变量名 1 到 10 (例如 CHANNEL_ID1, DINGTALK_URL1)
    for i in range(1, 11):
        ch_env = os.getenv(f"CHANNEL_ID{i}")
        webhook = os.getenv(f"DINGTALK_URL{i}")
        
        if ch_env and webhook:
            config_list.append({
                "group_name": f"第{i}组",
                "channels": clean_ids(ch_env), 
                "webhook": webhook
            })
            
    return config_list

# 载入配置
CONFIG_LIST = load_config()

# --- 核心网络请求模块 ---
def get_latest_message(channel_id):
    url = f"https://discord.com/api/v9/channels/{channel_id}/messages?limit=1"
    headers = {"Authorization": DISCORD_TOKEN, "Content-Type": "application/json"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200: return res.json()[0]
    except Exception as e:
        pass
    return None

def send_dingtalk(webhook, content):
    if not webhook: return
    headers = {"Content-Type": "application/json"}
    data = {"msgtype": "text", "text": {"content": f"[Discord监控]\n{content}"}}
    try:
        requests.post(webhook, headers=headers, data=json.dumps(data), timeout=10)
    except:
        pass

# --- 后台死循环任务 ---
def background_monitor():
    global history
    print(f"🚀 监控已启动！共加载了 {len(CONFIG_LIST)} 组推送配置。每 60 秒检查一次...")
    while True:
        # 遍历每一组配置
        for item in CONFIG_LIST:
            webhook = item["webhook"]
            # 遍历这组配置下的所有频道ID
            for channel_id in item["channels"]:
                msg = get_latest_message(channel_id)
                if msg:
                    msg_id = msg['id']
                    author = msg.get('author', {}).get('username', '未知')
                    content = msg.get('content', '[图片/附件]')
                    
                    last_id = history.get(channel_id, "")
                    if last_id and msg_id != last_id: # 发现新消息且不是第一次启动
                        print(f">>> 频道 {channel_id} 有新消息！发往对应的钉钉。")
                        send_dingtalk(webhook, f"频道: {channel_id}\n用户: {author}\n内容: {content}")
                    
                    # 更新历史记录
                    history[channel_id] = msg_id
                    
        # 检查完所有组，休息 60 秒
        time.sleep(60)

# --- 假网站防休眠模块 (Render 必备) ---
app = Flask(__name__)

@app.route('/')
def keep_alive():
    return f"Bot is running! Total active groups: {len(CONFIG_LIST)} ✅"

if __name__ == '__main__':
    # 启动后台监控线程
    t = threading.Thread(target=background_monitor)
    t.daemon = True
    t.start()
    
    # 启动假网站监听
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
