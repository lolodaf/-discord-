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
CHANNEL_NAMES_CACHE = {} 

def clean_ids(raw_input):
    if not raw_input: return []
    if "，" in raw_input: raw_input = raw_input.replace("，", ",")
    clean_ids = ["".join(filter(str.isdigit, raw_id)) for raw_id in raw_input.split(",")]
    return [cid for cid in clean_ids if cid]

def load_config():
    config_list = []
    ch_env = os.getenv("CHANNEL_ID")
    webhook = os.getenv("DINGTALK_URL")
    if ch_env and webhook:
        config_list.append({"channels": clean_ids(ch_env), "webhook": webhook})
        
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
    if channel_id in CHANNEL_NAMES_CACHE:
        return CHANNEL_NAMES_CACHE[channel_id] 
        
    url = f"https://discord.com/api/v9/channels/{channel_id}"
    headers = {"Authorization": DISCORD_TOKEN, "Content-Type": "application/json"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            name = res.json().get('name')
            if name:
                CHANNEL_NAMES_CACHE[channel_id] = name 
                return name
    except Exception as e:
        pass
    return channel_id 

def get_recent_messages(channel_id, limit=20):
    url = f"https://discord.com/api/v9/channels/{channel_id}/messages?limit={limit}"
    headers = {"Authorization": DISCORD_TOKEN, "Content-Type": "application/json"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200: 
            return res.json()
    except Exception as e:
        pass
    return []

def send_dingtalk_markdown(webhook, title, md_content):
    if not webhook: return
    headers = {"Content-Type": "application/json"}
    data = {
        "msgtype": "markdown",
        "markdown": {
            "title": title, 
            "text": f"### [Discord监控]\n{md_content}" 
        }
    }
    try:
        requests.post(webhook, headers=headers, data=json.dumps(data), timeout=10)
    except Exception as e:
        print(f"发送钉钉失败: {e}")

def format_discord_time(raw_time_str):
    if not raw_time_str:
        return "未知时间"
    try:
        dt_utc = datetime.fromisoformat(raw_time_str.replace('Z', '+00:00'))
        tz_utc_8 = timezone(timedelta(hours=8))
        dt_local = dt_utc.astimezone(tz_utc_8)
        return dt_local.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return raw_time_str

# --- 后台死循环任务 ---
def background_monitor():
    global history
    print(f"🚀 监控已启动！共加载了 {len(CONFIG_LIST)} 组推送配置。每 60 秒检查一次...")
    
    while True:
        for item in CONFIG_LIST:
            webhook = item["webhook"]
            for channel_id in item["channels"]:
                messages = get_recent_messages(channel_id, limit=20)
                
                if messages:
                    last_id = history.get(channel_id, "")
                    new_messages_to_send = []
                    
                    if last_id:
                        for msg in messages:
                            if msg['id'] == last_id:
                                break
                            new_messages_to_send.append(msg)
                    else:
                        new_messages_to_send = [messages[0]]
                    
                    if new_messages_to_send:
                        channel_name = get_channel_name(channel_id)
                        
                        for msg in reversed(new_messages_to_send):
                            # 1. 提取昵称和时间
                            member_info = msg.get('member', {})
                            author_username = msg.get('author', {}).get('username', '未知')
                            author_nick = member_info.get('nick')
                            author = author_nick if author_nick else author_username
                            formatted_time = format_discord_time(msg.get('timestamp', ''))

                            # 2. 提取是否是【回复】或【转发】的消息
                            quote_text = ""
                            # 处理回复 (Reply)
                            if 'referenced_message' in msg and msg['referenced_message']:
                                ref_msg = msg['referenced_message']
                                ref_author = ref_msg.get('member', {}).get('nick') or ref_msg.get('author', {}).get('username', '未知')
                                ref_content = ref_msg.get('content', '')
                                if not ref_content: ref_content = "[图片/文件]"
                                if len(ref_content) > 100: ref_content = ref_content[:100] + "..."
                                quote_text += f"> **回复 {ref_author}**: {ref_content}\n\n"
                            
                            # 处理转发 (Forward)
                            if 'message_snapshots' in msg and msg['message_snapshots']:
                                snap_msg = msg['message_snapshots'][0].get('message', {})
                                snap_content = snap_msg.get('content', '')
                                if not snap_content: snap_content = "[图片/文件]"
                                if len(snap_content) > 100: snap_content = snap_content[:100] + "..."
                                quote_text += f"> **转发消息**: {snap_content}\n\n"

                            # 3. 提取主体文字内容
                            content = msg.get('content', '')
                            
                            # --- 组装 Markdown 基础消息 ---
                            md_text = f"**频道**: {channel_name}\n\n**时间**: {formatted_time}\n\n**用户**: {author}\n\n"
                            if quote_text:
                                md_text += quote_text
                            if content:
                                md_text += f"**内容**: \n{content}\n\n"
                            
                            # 4. 处理原生附件 (图片直接展示，避免裂图；文件给链接)
                            attachments = msg.get('attachments', [])
                            if attachments:
                                for att in attachments:
                                    # 重点修复：使用 proxy_url 替代原生 url，能大幅度解决钉钉裂图(灰块)问题
                                    url = att.get('proxy_url') or att.get('url', '')
                                    file_name = att.get('filename', '附件')
                                    content_type = att.get('content_type', '')
                                    
                                    if content_type.startswith('image/') or any(url.split('?')[0].lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                                        md_text += f"![图片]({url})\n\n"
                                    else:
                                        md_text += f"[📁 点击下载/查看文件: {file_name}]({url})\n\n"
                            
                            # 5. 处理网站内嵌预览 (解决 Tenor GIF 变文本链接的问题)
                            embeds = msg.get('embeds', [])
                            if embeds:
                                for embed in embeds:
                                    # 去找 embed 里面真实的图片/GIF地址
                                    pic_url = embed.get('thumbnail', {}).get('proxy_url') or embed.get('thumbnail', {}).get('url')
                                    if not pic_url:
                                        pic_url = embed.get('image', {}).get('proxy_url') or embed.get('image', {}).get('url')
                                        
                                    if pic_url:
                                        md_text += f"![GIF/预览图]({pic_url})\n\n"

                            print(f">>> 频道 [{channel_name}] 有新消息！发往对应的钉钉。")
                            
                            # 发送给钉钉
                            send_dingtalk_markdown(webhook, f"新消息: {channel_name}", md_text)
                            time.sleep(2) 
                    
                    history[channel_id] = messages[0]['id']
                    
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
