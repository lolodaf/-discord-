import requests
import json
import os

# --- 核心增强逻辑 ---
def get_clean_ids():
    """读取并清洗 ID，自动处理中文逗号、空格、换行符"""
    raw_input = os.getenv("CHANNEL_ID", "")
    
    # 1. 自动把中文逗号换成英文逗号
    if "，" in raw_input:
        raw_input = raw_input.replace("，", ",")
    
    # 2. 分割后逐个清洗
    clean_ids = []
    for raw_id in raw_input.split(","):
        # 这一步会把 ID 里所有非数字的字符（空格、回车等）全部删掉
        clean_id = "".join(filter(str.isdigit, raw_id))
        if clean_id:
            clean_ids.append(clean_id)
            
    if not clean_ids:
        print("❌ 错误：没有检测到有效的数字 ID，请检查 Secrets 设置！")
    else:
        print(f"✅ 成功读取 {len(clean_ids)} 个有效频道 ID")
        
    return clean_ids

# 读取配置
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_IDS = get_clean_ids() # 使用增强版函数读取
DINGTALK_URL = os.getenv("DINGTALK_URL")
LAST_MSG_FILE = "last_msg_id.txt"

def get_latest_message(channel_id):
    url = f"https://discord.com/api/v9/channels/{channel_id}/messages?limit=1"
    headers = {"Authorization": DISCORD_TOKEN, "Content-Type": "application/json"}
    try:
        # 增加 timeout 防止卡死
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code == 200:
            return res.json()[0]
        elif res.status_code == 401:
            print(f"❌ 权限不足 (401)，请检查 DISCORD_TOKEN 是否过期")
        elif res.status_code == 404:
            print(f"❌ 频道不存在 (404)，ID: {channel_id} 可能填错了")
        else:
            print(f"⚠️ 获取失败 {channel_id}: {res.status_code}")
    except Exception as e:
        print(f"❌ 请求出错: {e}")
    return None

def send_dingtalk(content):
    headers = {"Content-Type": "application/json"}
    data = {
        "msgtype": "text",
        "text": {
            "content": f"[Discord监控]\n{content}"
        }
    }
    try:
        requests.post(DINGTALK_URL, headers=headers, data=json.dumps(data), timeout=10)
    except:
        pass

# --- 主逻辑 ---
history = {}
# 读取旧记录
if os.path.exists(LAST_MSG_FILE):
    try:
        with open(LAST_MSG_FILE, "r") as f:
            content = f.read().strip()
            if content.startswith("{"):
                history = json.loads(content)
    except:
        history = {}

has_update = False

# 循环检查
for channel_id in CHANNEL_IDS:
    msg = get_latest_message(channel_id)
    
    if msg:
        msg_id = msg['id']
        author = msg.get('author', {}).get('username', '未知')
        content = msg.get('content', '[图片/附件]')
        
        last_id = history.get(channel_id, "")
        
        if msg_id != last_id:
            print(f">>> 频道 {channel_id} 发现新消息！")
            send_dingtalk(f"频道: {channel_id}\n用户: {author}\n内容: {content}")
            history[channel_id] = msg_id
            has_update = True
        else:
            print(f"频道 {channel_id} 无新消息")

# 只有当发现更新时，或者文件不存在时，才写入文件
# 这能解决 'pathspec' 找不到文件的报错
if has_update or not os.path.exists(LAST_MSG_FILE):
    with open(LAST_MSG_FILE, "w") as f:
        json.dump(history, f)
    print("✅ 记录文件已更新")
