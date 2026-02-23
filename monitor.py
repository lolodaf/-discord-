import requests
import json
import os
import time
import threading
import urllib.parse
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

# --- 核心辅助与解析模块 ---
def get_channel_name(channel_id):
    if channel_id in CHANNEL_NAMES_CACHE: return CHANNEL_NAMES_CACHE[channel_id] 
    url = f"https://discord.com/api/v9/channels/{channel_id}"
    headers = {"Authorization": DISCORD_TOKEN, "Content-Type": "application/json"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200 and res.json().get('name'):
            name = res.json().get('name')
            CHANNEL_NAMES_CACHE[channel_id] = name 
            return name
    except: pass
    return channel_id 

def get_recent_messages(channel_id, limit=20):
    url = f"https://discord.com/api/v9/channels/{channel_id}/messages?limit={limit}"
    headers = {"Authorization": DISCORD_TOKEN, "Content-Type": "application/json"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200: return res.json()
    except: pass
    return []

def send_dingtalk_markdown(webhook, title, md_content):
    if not webhook: return
    headers = {"Content-Type": "application/json"}
    data = {"msgtype": "markdown", "markdown": {"title": title, "text": f"### [Discord监控]\n{md_content}"}}
    try:
        requests.post(webhook, headers=headers, data=json.dumps(data), timeout=10)
    except Exception as e:
        print(f"发送钉钉失败: {e}")

def format_discord_time(raw_time_str):
    if not raw_time_str: return "未知时间"
    try:
        dt_utc = datetime.fromisoformat(raw_time_str.replace('Z', '+00:00'))
        return dt_utc.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    except: return raw_time_str

def get_proxied_image_url(discord_url):
    """利用全球公益代理突破钉钉无法访问Discord图片的问题"""
    if not discord_url: return ""
    encoded = urllib.parse.quote(discord_url, safe='')
    return f"https://wsrv.nl/?url={encoded}&n=-1"

def extract_readable_content(msg_obj):
    """深度提取文字：不仅提取普通文本，还能把复杂的灰色内嵌卡片（Embed）格式化出来"""
    text = msg_obj.get('content', '')
    embeds = msg_obj.get('embeds', [])
    for e in embeds:
        text += "\n\n" # 为卡片留出空行
        if e.get('title'): text += f"**【{e['title']}】**\n"
        if e.get('description'): text += f"{e['description']}\n"
        for field in e.get('fields', []):
            text += f"- **{field.get('name', '')}**: {field.get('value', '')}\n"
    return text.strip()

# --- 后台死循环任务 ---
def background_monitor():
    global history
    print(f"🚀 监控已启动！共加载了 {len(CONFIG_LIST)} 组配置。")
    
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
                            if msg['id'] == last_id: break
                            new_messages_to_send.append(msg)
                    else:
                        new_messages_to_send = [messages[0]]
                    
                    if new_messages_to_send:
                        channel_name = get_channel_name(channel_id)
                        
                        for msg in reversed(new_messages_to_send):
                            # 1. 发送者与时间
                            author = msg.get('member', {}).get('nick') or msg.get('author', {}).get('username', '未知')
                            formatted_time = format_discord_time(msg.get('timestamp', ''))
                            
                            md_text = f"**频道**: {channel_name}\n\n**时间**: {formatted_time}\n\n**用户**: {author}\n\n"

                            # 2. 深度解析回复内容 (回复某人)
                            if msg.get('referenced_message'):
                                ref_msg = msg['referenced_message']
                                ref_author = ref_msg.get('member', {}).get('nick') or ref_msg.get('author', {}).get('username', '未知')
                                ref_content = extract_readable_content(ref_msg)
                                if not ref_content: ref_content = "[图片/文件/特殊卡片]"
                                # 格式化为 Markdown 引用块
                                quoted = '> ' + '\n> '.join(ref_content.split('\n'))
                                md_text += f"**回复 {ref_author}**:\n\n{quoted}\n\n"
                            
                            # 3. 🎯 深度解析转发内容 (解决你的截图问题)
                            if msg.get('message_snapshots'):
                                for snap in msg['message_snapshots']:
                                    snap_msg = snap.get('message', {})
                                    snap_content = extract_readable_content(snap_msg)
                                    
                                    # 如果转发的内容里还带了图片，也一并抓出来！
                                    for att in snap_msg.get('attachments', []):
                                        url = att.get('url', '')
                                        if any(url.split('?')[0].lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                                            safe_img = get_proxied_image_url(url)
                                            snap_content += f"\n\n![转发的图片]({safe_img})"
                                    
                                    if not snap_content: snap_content = "[复杂多媒体卡片]"
                                    # 变成钉钉的灰色引用块
                                    quoted = '> ' + '\n> '.join(snap_content.split('\n'))
                                    md_text += f"**🔄 转发了消息**:\n\n{quoted}\n\n"

                            # 4. 用户自己打的字 (比如截图底部的那个 🫡 表情)
                            content_text = extract_readable_content(msg)
                            if content_text:
                                md_text += f"**内容**:\n{content_text}\n\n"

                            # 5. 用户自己发的附件/图片 (防裂图代理处理)
                            for att in msg.get('attachments', []):
                                url = att.get('url', '')
                                file_name = att.get('filename', '附件')
                                c_type = att.get('content_type', '')
                                
                                if c_type.startswith('image/') or any(url.split('?')[0].lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                                    safe_img = get_proxied_image_url(url)
                                    md_text += f"![图片]({safe_img})\n[🔗 点击查看原图]({url})\n\n"
                                else:
                                    md_text += f"[📁 文件下载: {file_name}]({url})\n\n"
                            
                            # 6. GIF 与内嵌预览图处理 (处理 Tenor 等表情包)
                            for e in msg.get('embeds', []):
                                pic_url = e.get('image', {}).get('url') or e.get('thumbnail', {}).get('url')
                                if pic_url:
                                    safe_img = get_proxied_image_url(pic_url)
                                    md_text += f"![GIF/预览图]({safe_img})\n[🔗 点击查看原图/动图]({pic_url})\n\n"

                            print(f">>> 频道 [{channel_name}] 有新消息！发往对应的钉钉。")
                            send_dingtalk_markdown(webhook, f"新消息: {channel_name}", md_text)
                            time.sleep(2) 
                    
                    history[channel_id] = messages[0]['id']
        time.sleep(60)

app = Flask(__name__)
@app.route('/')
def keep_alive(): return f"Bot is running! Total active groups: {len(CONFIG_LIST)} ✅"

if __name__ == '__main__':
    threading.Thread(target=background_monitor, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
