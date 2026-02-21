import requests
import json
import os
import time
import threading
from datetime import datetime, timezone, timedelta
from flask import Flask

# --- 配置加载与清洗模块 ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
history = {}
CHANNEL_NAMES_CACHE = {} # 用来存查到的频道名字，查过一次就不查了

def clean_ids(raw_input):
    """清洗频道ID字符串，处理中文逗号和空格"""
    if not raw_input: return []
    if "，" in raw_input: raw_input = raw_input.replace("，", ",")
    clean_ids = ["".join(filter(str.isdigit, raw_id)) for raw_id in raw_input.split(",")]
    return [cid for cid in clean_ids if cid]

def load_config():
    """动态加载多组频道和对应的钉钉机器人"""
    config_list = []
    
    # 兼容老的写法
    ch_env = os.getenv("CHANNEL_ID")
    webhook = os.getenv("DINGTALK_URL")
    if ch_env and webhook:
        config_list.append({"channels": clean_ids(ch_env), "webhook": webhook})
        
    # 自动扫描带数字的变量名 1 到 10
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

CONFIG_LIST = load_config()

# --- 核心网络请求模块 ---
def get_channel_name(channel_id):
    """自动拿着 ID 去问 Discord 这个频道叫什么名字"""
    if channel_id in CHANNEL_NAMES_CACHE:
        return CHANNEL_NAMES_CACHE[channel_id] # 脑子里有就直接用
        
    url = f"https://discord.com/api/v9/channels/{channel_id}"
    headers = {"Authorization": DISCORD_TOKEN, "Content-Type": "application/json"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            name = res.json().get('name')
            if name:
                CHANNEL_NAMES_CACHE[channel_id] = name # 查到了就记在脑子里
                return name
    except Exception as e:
        pass
    
    return channel_id # 如果万一查失败了，就先用数字 ID 顶替

def get_recent_messages(channel_id, limit=20):
    """获取最近的多条消息，默认拉取20条"""
    url = f"https://discord.com/api/v9/channels/{channel_id}/messages?limit={limit}"
    headers = {"Authorization": DISCORD_TOKEN, "Content-Type": "application/json"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200: 
            return res.json()
    except Exception as e:
        pass
    return []

def send_dingtalk(webhook, content):
    if not webhook: return
    headers = {"Content-Type": "application/json"}
    data = {"msgtype": "text", "text": {"content": f"[Discord监控]\n{content}"}}
    try:
        requests.post(webhook, headers=headers, data=json.dumps(data), timeout=10)
    except Exception as e:
        print(f"发送钉钉失败: {e}")

def format_discord_time(raw_time_str):
    """将 Discord 的 UTC 时间转换为东八区（北京/新加坡）时间字符串"""
    if not raw_time_str:
        return "未知时间"
    try:
        # Discord 返回格式如 "2023-10-24T12:00:00.000000+00:00"
        dt_utc = datetime.fromisoformat(raw_time_str.replace('Z', '+00:00'))
        tz_utc_8 = timezone(timedelta(hours=8))
        dt_local = dt_utc.astimezone(tz_utc_8)
        return dt_local.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        # 如果解析失败，原样返回
        return raw_time_str

# --- 后台死循环任务 ---
def background_monitor():
    global history
    print(f"🚀 监控已启动！共加载了 {len(CONFIG_LIST)} 组推送配置。每 60 秒检查一次...")
    
    while True:
        for item in CONFIG_LIST:
            webhook = item["webhook"]
            for channel_id in item["channels"]:
                # 1. 获取最近的多条消息 (默认20条)
                messages = get_recent_messages(channel_id, limit=20)
                
                if messages:
                    last_id = history.get(channel_id, "")
                    new_messages_to_send = []
                    
                    # 2. 如果之前有记录 last_id，则开始筛选新消息
                    if last_id:
                        for msg in messages:
                            # 遍历直到遇到上次记录的最后一条消息ID
                            if msg['id'] == last_id:
                                break
                            new_messages_to_send.append(msg)
                    else:
                        # 如果是第一次运行（没有历史记录），为了防止刷屏，只发送最新的一条
                        new_messages_to_send = [messages[0]]
                    
                    # 3. 按时间顺序（从旧到新）发送新消息
                    if new_messages_to_send:
                        channel_name = get_channel_name(channel_id)
                        
                        # reversed() 将列表倒序，变成 [旧, 较新, 最新]
                        for msg in reversed(new_messages_to_send):
                            # --- 提取信息：昵称、时间、内容 ---
                            
                            # 优先获取服务器昵称 (nick)，如果为空则回退到全局用户名 (username)
                            member_info = msg.get('member', {})
                            author_username = msg.get('author', {}).get('username', '未知')
                            author_nick = member_info.get('nick')
                            
                            # 考虑到 author_nick 可能存在但值为 None 的情况
                            author = author_nick if author_nick else author_username
                            
                            # 格式化时间为东八区
                            formatted_time = format_discord_time(msg.get('timestamp', ''))

                            content = msg.get('content', '')
                            # 处理可能存在的附件或图片
                            if not content and msg.get('attachments'):
                                content = '[图片/附件]'
                                
                            print(f">>> 频道 [{channel_name}] 有新消息！发往对应的钉钉。")
                            
                            # 发送给钉钉，包含时间
                            dingtalk_msg = f"频道: {channel_name}\n时间: {formatted_time}\n用户: {author}\n内容: {content}"
                            send_dingtalk(webhook, dingtalk_msg)
                            
                            # 每次发送后停顿 2 秒，防止触发钉钉限流
                            time.sleep(2) 
                    
                    # 4. 更新历史记录为这批消息中绝对最新的一条（即列表的第 0 项）
                    history[channel_id] = messages[0]['id']
                    
        # 5. 整个大循环结束后，等待 60 秒再次检查
        time.sleep(60)

# --- 假网站防休眠模块 ---
app = Flask(__name__)

@app.route('/')
def keep_alive():
    return f"Bot is running! Total active groups: {len(CONFIG_LIST)} ✅"

if __name__ == '__main__':
    t = threading.Thread(target=background_monitor)
    t.daemon = True
    t.start()
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
