import requests
import json
import os

# 从 Secrets 读取配置
# 注意：现在支持多个ID，用逗号分隔
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_IDS = os.getenv("CHANNEL_ID").split(",") 
DINGTALK_URL = os.getenv("DINGTALK_URL")
LAST_MSG_FILE = "last_msg_id.txt"

def get_latest_message(channel_id):
    """获取指定频道的最新一条消息"""
    url = f"https://discord.com/api/v9/channels/{channel_id}/messages?limit=1"
    headers = {"Authorization": DISCORD_TOKEN, "Content-Type": "application/json"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            return res.json()[0]
    except Exception as e:
        print(f"频道 {channel_id} 请求失败: {e}")
    return None

def send_dingtalk(content):
    """发送通知到钉钉"""
    headers = {"Content-Type": "application/json"}
    data = {
        "msgtype": "text",
        "text": {
            "content": f"[Discord监控]\n{content}"
        }
    }
    try:
        requests.post(DINGTALK_URL, headers=headers, data=json.dumps(data))
    except:
        pass

# --- 主程序逻辑 ---

# 1. 读取历史记录 (现在是一个字典，存了每个频道的最后一条ID)
history = {}
if os.path.exists(LAST_MSG_FILE):
    try:
        with open(LAST_MSG_FILE, "r") as f:
            content = f.read()
            # 兼容旧版本：如果以前存的是纯数字，就重置为空字典
            if content.startswith("{"):
                history = json.loads(content)
    except:
        history = {}

# 2. 循环检查每一个频道
has_update = False
print(f"开始检查 {len(CHANNEL_IDS)} 个频道...")

for channel_id in CHANNEL_IDS:
    channel_id = channel_id.strip() # 去除可能存在的空格
    if not channel_id: continue
    
    msg = get_latest_message(channel_id)
    
    if msg:
        msg_id = msg['id']
        author = msg.get('author', {}).get('username', '未知')
        content = msg.get('content', '[图片/附件]')
        
        # 获取该频道上一次记录的 ID
        last_id = history.get(channel_id, "")
        
        if msg_id != last_id:
            # 发现新消息！
            print(f">>> 频道 {channel_id} 发现更新！")
            
            # 这里的打印是为了让你在 Log 里看到进度，但隐藏具体内容保护隐私
            # 具体的策略只会发到钉钉
            send_dingtalk(f"频道: {channel_id}\n用户: {author}\n内容: {content}")
            
            # 更新记录
            history[channel_id] = msg_id
            has_update = True
        else:
            print(f"频道 {channel_id} 无新消息")

# 3. 如果有更新，保存新的记录文件
if has_update:
    with open(LAST_MSG_FILE, "w") as f:
        json.dump(history, f)
    print("历史记录已更新")
else:
    print("所有频道均无更新")
