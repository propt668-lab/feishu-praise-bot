#!/usr/bin/env python3
"""
飞书成单夸奖机器人 — 一次性执行脚本
由 GitHub Actions 每 30 分钟触发一次。
从 state.json 加载状态（包含上次检查时间），拉取该时间之后的群消息，
检测成单卡片并发送夸奖，保存状态后退出。

改进：使用 last_check_time 记录上次检查时间点，避免因 cron 延迟导致漏检。
"""
from __future__ import annotations

import json
import logging
import os
import random
import re
import time
from collections import defaultdict

import requests

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
BASE_URL = "https://open.feishu.cn/open-apis"
CHAT_ID = "oc_dddb60097be21816a6cdaafbc5d9da59"

# 从环境变量读取密钥（GitHub Secrets 注入）
APP_ID = os.environ.get("FEISHU_APP_ID", "")
APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")

# 管理员 open_id（接收 @机器人 消息汇总）
ADMIN_OPEN_ID = os.environ.get("ADMIN_OPEN_ID", "ou_ab0e0fbb7083b3d10a7229627bbd467f")

# 首次运行或状态丢失时的默认回溯时间（6小时）
DEFAULT_LOOKBACK_SECONDS = 6 * 60 * 60

# 最大回溯时间（24小时），防止拉取太多历史消息
MAX_LOOKBACK_SECONDS = 24 * 60 * 60

STATE_FILE = os.environ.get("STATE_FILE", "state.json")

# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 话术模板（共 90 条）
# ---------------------------------------------------------------------------

# 热血鼓励型 - 带emoji，真诚有力
PRAISE_RELIE = [
    "🔥 好家伙 {name}，{amount} 拿下了！最近状态真的在线，继续冲！",
    "💪 {name} 又成了！{amount}，这个月势头很猛啊",
    "👏 漂亮！{name} 搞定 {amount}，看得出来这单跟得细致",
    "✅ {name} 稳稳拿下 {amount}，执行力没得说",
    "🎉 恭喜 {name}！{amount} 到手，最近真的很能打",
    "📈 {name} 又进账 {amount}，保持这个节奏，月底继续冲",
    "💰 不错不错，{name} 又下一城，{amount} 收入囊中",
    "🙌 {name} 成了！{amount}，功夫不负有心人",
    "👍 给 {name} 鼓掌，{amount} 漂亮收官",
    "⭐ {name} 拿下 {amount}，越来越稳了",
    "📣 好消息！{name} 又成单了，{amount}",
    "🚀 {name} 搞定 {amount}，效率可以的",
    "🎯 恭喜 {name}！{amount} 顺利成交",
    "💫 {name} 又传来好消息，{amount} 到账",
    "✨ 漂亮，{name} 再下一单 {amount}",
    "🔥 {name} 成单 {amount}，状态在线",
    "💪 不出所料，{name} 又成了，{amount}，靠谱",
    "👏 {name} 拿下 {amount}，恭喜恭喜",
    "🎊 给力！{name} 又一单 {amount} 落袋",
    "📈 {name} 持续输出中，{amount} 又到手了",
    "🙌 恭喜 {name} 成单 {amount}，继续冲",
    "✅ {name} 又赢了，{amount} 拿下，nice",
    "💰 稳！{name} 再收 {amount}，这个月有戏",
    "🔥 {name} 捷报频传，{amount} 又进了",
    "👍 佩服，{name} 又成一单 {amount}",
    "⭐ {name} 太稳了，{amount} 轻松拿下",
    "🎯 厉害了 {name}，{amount} 说成就成",
    "💫 {name} 这波操作很溜，{amount} 收下",
    "🎉 恭喜恭喜，{name} 又进账 {amount}",
    "🚀 {name} 再添 {amount}，保持这个势头",
]

# 诙谐无厘头型 - 搞笑但不尬
PRAISE_WULITOU = [
    "😱 {name} 你是不是偷偷开挂了？{amount} 也太顺了吧",
    "🆘 救命，{name} 又成单了，{amount}，能不能给别人留点",
    "❓ {name} 这是什么成单体质？{amount} 说来就来",
    "🍋 打扰了，{name} 又在秀 {amount}，我先酸为敬",
    "🤔 {name} 今天KPI是不是已经完成了？{amount} 又进了",
    "😮 好家伙 {name}，{amount}，你打算承包这个月吗",
    "📖 {name} 成单秘籍考虑出书吗？{amount} 看馋了",
    "🍵 被 {name} 凡尔赛到了，又是轻松成单 {amount} 的一天",
    "😳 {name} 你认真的吗？{amount} 就这么成了？",
    "🤯 等等让我消化一下，{name} 又双叒成单了？{amount}",
    "💔 {name} 是懂怎么让同事破防的，{amount} 直接拿下",
    "📹 建议 {name} 出个教程，{amount} 这手速教教我们",
    "😭 {name} 你这样让别人怎么活？{amount} 又来",
    "🤖 合理怀疑 {name} 是机器人，{amount} 效率太离谱",
    "🏪 {name} 今天也在正常营业，{amount} 轻松到手",
    "😤 又被 {name} 内卷到了，{amount} 收得漂亮",
    "🔍 {name} 快说，{amount} 这单怎么谈的？速速交代",
    "🏃 好好好，{name} 又是领先的一天，{amount} 拿下",
    "🧎 {name} 请收下我的膝盖，{amount} 秀到我了",
    "🏳️ 得，{name} 又行了，{amount}，我服",
    "😑 {name} 你礼貌吗？成单 {amount} 不提前说一声",
    "🔎 破案了，{name} 才是团队隐藏大佬，{amount} 又来",
    "📢 {name} 今天份的低调炫耀：{amount}",
    "🙏 求 {name} 传授一下，{amount} 怎么做到的",
    "👀 确认过眼神，{name} 是要冲榜的人，{amount} 收好",
    "💳 {name} 请问你是充了会员吗？{amount} 这也太顺",
    "😲 有被 {name} 惊到，{amount}，可以的",
    "🎭 {name} 低调成单 {amount}，高调实力",
    "🏆 又是 {name} 的主场，{amount} 拿下",
    "🤷 所以 {name} 的秘诀到底是什么？{amount} 羡慕了",
]


# 浮夸蠢萌型 - 夸张到离谱，但傻乎乎很可爱，活人感拉满
PRAISE_FUKUA = [
    "😭😭😭 {name} 你怎么又成单了啊啊啊啊！{amount}！我哭死！你是不是住在客户家了！",
    "救命啊啊啊啊 {name} 成单 {amount}！谁家顾问这么猛的啦！我要报警了！",
    "🫠 完了完了，{name} 又开始表演了，{amount} 说拿就拿，我精神状态已经不太好了",
    "天哪天哪天哪！{name} 你是吃了什么神仙药吗！{amount} 也太丝滑了吧！我不理解！",
    "😱 我的妈呀 {name}！{amount}！你是不是把成单按钮焊死了！一直按一直按！",
    "呜呜呜呜 {name} 你轻点卷行吗？{amount} 又进了，我膝盖已经跪麻了",
    "🤪 {name} 你清醒一点！你已经成单 {amount} 了你知道吗！不要再成了！（不是",
    "啊啊啊啊啊！全体起立！{name} 成单 {amount}！请接受我一个大大的拥抱（隔空的",
    "😵‍💫 {name} 你慢点啊，我记绩效的笔都冒烟了！{amount} 又来！",
    "💀 {name} 我真的会谢！{amount} 说成就成！你是不是有成单雷达啊！",
    "不是…{name}你是认真的吗…{amount}…我在地铁上看到这个消息差点叫出来",
    "🫣 偷偷说一句：{name} 你今天也太帅/美了吧！成单 {amount} 的人自带光环！",
    "好好好 {name} 又是你是吧！{amount}！我现在见到你就条件反射想鼓掌！",
    "😤 {name} ！你给我出来！成单 {amount} 不请喝奶茶说得过去吗！",
    "呜哇—— {name} 又双叒叕成单了！{amount}！这个人是不是有bug！",
    "🥺 {name} 你是我见过最能打的人没有之一！{amount} 拿下！我要把你写进简历里！",
    "裂开了家人们！{name} 又来了！{amount}！建议公司给ta配个专属BGM！",
    "😆 {name} 这是什么天选成单体质！{amount} 也太轻松了吧！不公平！我要投诉！",
    "妈妈问我为什么跪着看手机——因为 {name} 又成单 {amount} 了啊！",
    "🫡 向 {name} 同志致敬！{amount} 收入麾下！这战斗力建议申报吉尼斯！",
    "完蛋了 {name} 又在散发魅力了！{amount} 的客户肯定被你的真诚打动了吧！",
    "😳 等等等等…{name} 你再说一遍？{amount}？这么多？真的假的？截图给我看看！",
    "📢 紧急插播：{name} 成单 {amount}！建议全体成员起立鼓掌30秒！",
    "{name} 你是懂成单的！{amount} 拿捏得死死的！我已经词穷了只会说牛牛牛！",
    "🌋 {name} 的签单能力简直是核弹级别的！{amount} 轰一下就炸了！",
    "我去！{name} 你悄悄成单 {amount} 被我发现了！罚你分享成单心得一篇！",
    "🐮 好家伙，{name} 又来炸群了！{amount}！你是不是和客户有心灵感应啊！",
    "嘶—— {name} 你这个 {amount}，让我缓缓，我需要消化一下这个数字",
    "笑死了 {name} 今天又是元气满满成单的一天！{amount}！你的能量是核聚变吗！",
    "🤯 OH MY GOD！{name}！{amount}！买它！不对，签它！总之就是绝了！",
]

# 浮夸蠢萌专属期截止日期（2026-03-03），此期间只用 PRAISE_FUKUA
FUKUA_ONLY_UNTIL = "2026-03-03"

ALL_PRAISE = PRAISE_RELIE + PRAISE_WULITOU + PRAISE_FUKUA  # 90 条


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------
def get_tenant_token() -> str:
    """获取飞书 tenant_access_token。"""
    resp = requests.post(
        f"{BASE_URL}/auth/v3/tenant_access_token/internal",
        json={"app_id": APP_ID, "app_secret": APP_SECRET},
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取 token 失败: {data}")
    token = data["tenant_access_token"]
    log.info("获取 tenant_access_token 成功")
    return token


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def fetch_members(token: str) -> dict:
    """获取群成员列表，返回 {name: open_id}。"""
    members = {}
    url = f"{BASE_URL}/im/v1/chats/{CHAT_ID}/members"
    params = {"member_id_type": "open_id", "page_size": 100}
    resp = requests.get(url, headers=auth_headers(token), params=params)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        log.error("获取群成员失败: %s", data)
        return members
    for item in data.get("data", {}).get("items", []):
        name = item.get("name", "")
        open_id = item.get("member_id", "")
        if name and open_id:
            members[name] = open_id
    log.info("获取群成员 %d 人", len(members))
    return members


def fetch_messages(token: str, start_time: str) -> list:
    """拉取指定时间之后的群消息。"""
    url = f"{BASE_URL}/im/v1/messages"
    end_time = str(int(time.time()))
    params = {
        "container_id_type": "chat",
        "container_id": CHAT_ID,
        "start_time": start_time,
        "end_time": end_time,
        "sort_type": "ByCreateTimeAsc",
        "page_size": 50,
    }
    all_messages = []
    page_token = None
    while True:
        if page_token:
            params["page_token"] = page_token
        resp = requests.get(url, headers=auth_headers(token), params=params)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            log.error("拉取消息失败: %s", data)
            break
        items = data.get("data", {}).get("items", [])
        all_messages.extend(items)
        if not data.get("data", {}).get("has_more"):
            break
        page_token = data["data"].get("page_token")
    log.info("拉取到 %d 条消息", len(all_messages))
    return all_messages


def match_member(raw_name: str, member_map: dict) -> tuple:
    """
    三层匹配：精确原名 → 精确去尾号名 → 模糊包含。
    返回 (clean_name, open_id or None)。
    """
    clean_name = re.sub(r"\d+$", "", raw_name).strip()
    # 1) 精确匹配原名
    if raw_name in member_map:
        return clean_name, member_map[raw_name]
    # 2) 精确匹配去尾号名
    if clean_name in member_map:
        return clean_name, member_map[clean_name]
    # 3) 模糊包含
    for mname, oid in member_map.items():
        if clean_name in mname or mname in clean_name:
            return clean_name, oid
    return clean_name, None


def extract_amount(content_obj: dict) -> tuple[str, float]:
    """从卡片内容中提取金额。

    Returns:
        (显示文本, 数值金额)
        - 金额 >= 20000: ("X元大单", 数值)
        - 金额 < 20000: ("X元", 数值)
        - 未找到金额: ("这一单", 0)
    """
    full_text = json.dumps(content_obj, ensure_ascii=False)
    m = re.search(r"(\d[\d,]*\.?\d*)\s*元", full_text)
    if not m:
        return "这一单", 0

    raw = m.group(1).replace(",", "")
    try:
        value = float(raw)
    except ValueError:
        return "这一单", 0

    # 格式化显示金额
    if value >= 10000:
        wan = value / 10000
        if wan == int(wan):
            display = f"{int(wan)}万"
        else:
            display = f"{wan:.1f}万"
    else:
        display = f"{int(value)}"

    # 超过2万才叫"大单"
    if value >= 20000:
        return f"{display}大单", value
    return display, value


def pick_praise(clean_name: str, amount: str, used: dict) -> str:
    """为指定人选一条不重复的话术。

    在 FUKUA_ONLY_UNTIL 日期之前，只使用浮夸蠢萌风格；
    之后恢复全部风格随机。
    """
    from datetime import date

    today = date.today().isoformat()
    if today < FUKUA_ONLY_UNTIL:
        pool = PRAISE_FUKUA
    else:
        pool = ALL_PRAISE

    total = len(pool)
    used_set = used.get(clean_name, [])
    available = [i for i in range(total) if i not in used_set]
    if not available:
        used[clean_name] = []
        available = list(range(total))
    idx = random.choice(available)
    used.setdefault(clean_name, []).append(idx)
    template = pool[idx]
    return template.format(name=clean_name, amount=amount)


def get_bot_info(token: str) -> dict:
    """获取机器人自身信息，返回 {open_id, app_name}。"""
    resp = requests.get(
        f"{BASE_URL}/bot/v3/info",
        headers=auth_headers(token),
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        log.error("获取机器人信息失败: %s", data)
        return {}
    bot = data.get("bot", {})
    log.info("机器人信息: %s (open_id=%s)", bot.get("app_name"), bot.get("open_id"))
    return bot


def detect_at_bot_messages(
    messages: list, bot_open_id: str, processed_ids: set, member_map: dict
) -> list[dict]:
    """检测 @机器人 的消息。

    Returns:
        list of {msg_id, sender_name, sender_id, content, create_time}
    """
    at_messages = []

    for msg in messages:
        msg_id = msg.get("message_id", "")
        if msg_id in processed_ids:
            continue

        msg_type = msg.get("msg_type", "")
        sender = msg.get("sender", {})
        sender_type = sender.get("sender_type", "")

        # 只处理用户发送的消息
        if sender_type != "user":
            continue

        # 检查消息内容中是否 @了机器人
        try:
            content_str = msg.get("body", {}).get("content", "{}")
            content = json.loads(content_str)
        except json.JSONDecodeError:
            continue

        # 检测 @机器人
        has_at_bot = False
        text_content = ""

        if msg_type == "text":
            # 文本消息格式: {"text": "@_user_1 xxx", "mentions": [{"key": "@_user_1", "id": {"open_id": "xxx"}}]}
            text_content = content.get("text", "")
            mentions = content.get("mentions", [])
            for mention in mentions:
                mention_id = mention.get("id", {})
                if isinstance(mention_id, dict):
                    if mention_id.get("open_id") == bot_open_id:
                        has_at_bot = True
                        break
                elif mention_id == bot_open_id:
                    has_at_bot = True
                    break

        elif msg_type == "post":
            # 富文本消息，遍历内容查找 at 标签
            def extract_post_content(post_content):
                texts = []
                at_bot = False
                for lang_content in post_content.values():
                    for line in lang_content.get("content", []):
                        for elem in line:
                            if elem.get("tag") == "text":
                                texts.append(elem.get("text", ""))
                            elif elem.get("tag") == "at":
                                if elem.get("user_id") == bot_open_id:
                                    at_bot = True
                return " ".join(texts), at_bot

            text_content, has_at_bot = extract_post_content(content)

        if not has_at_bot:
            continue

        # 清理 @标记，提取纯文本
        clean_text = re.sub(r"@_user_\d+\s*", "", text_content).strip()

        # 获取发送者信息
        sender_id = sender.get("id", "")
        sender_name = "未知用户"
        # 从 member_map 反查名字
        for name, oid in member_map.items():
            if oid == sender_id:
                sender_name = name
                break

        # 获取消息时间
        create_time = msg.get("create_time", "")
        if create_time:
            try:
                ts = int(create_time) // 1000 if len(create_time) > 10 else int(create_time)
                time_str = time.strftime("%H:%M", time.localtime(ts))
            except (ValueError, OSError):
                time_str = "未知时间"
        else:
            time_str = "未知时间"

        at_messages.append({
            "msg_id": msg_id,
            "sender_name": sender_name,
            "sender_id": sender_id,
            "content": clean_text if clean_text else "(无文字内容)",
            "time": time_str,
        })

        log.info("检测到 @机器人 消息: %s 说: %s", sender_name, clean_text[:50])

    return at_messages


def send_at_summary(token: str, at_messages: list[dict]):
    """发送 @消息汇总给管理员。"""
    if not at_messages:
        return

    if not ADMIN_OPEN_ID:
        log.warning("未配置 ADMIN_OPEN_ID，无法发送 @消息汇总")
        return

    # 构建汇总消息
    lines = [f"📬 收到 {len(at_messages)} 条 @消息：\n"]
    for i, msg in enumerate(at_messages, 1):
        lines.append(f"{i}. 【{msg['time']}】{msg['sender_name']}：")
        lines.append(f"   {msg['content']}\n")

    lines.append("\n💡 请回复对应序号+内容来回复用户")
    lines.append("例如：1 好的，收到！")

    text = "\n".join(lines)

    # 发送私聊消息给管理员
    url = f"{BASE_URL}/im/v1/messages"
    params = {"receive_id_type": "open_id"}
    body = {
        "receive_id": ADMIN_OPEN_ID,
        "msg_type": "text",
        "content": json.dumps({"text": text}, ensure_ascii=False),
    }

    resp = requests.post(url, headers=auth_headers(token), params=params, json=body)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        log.error("发送 @消息汇总失败: %s", data)
    else:
        log.info("@消息汇总已发送给管理员，共 %d 条", len(at_messages))


def send_praise(token: str, clean_name: str, open_id: str | None, praise_text: str):
    """发送夸奖消息到群聊。"""
    url = f"{BASE_URL}/im/v1/messages"
    params = {"receive_id_type": "chat_id"}

    if open_id:
        # 富文本 @mention
        msg_content = {
            "zh_cn": {
                "title": "",
                "content": [
                    [
                        {"tag": "at", "user_id": open_id},
                        {"tag": "text", "text": "伙伴 "},
                    ],
                    [
                        {"tag": "text", "text": praise_text},
                    ],
                ],
            }
        }
        body = {
            "receive_id": CHAT_ID,
            "msg_type": "post",
            "content": json.dumps(msg_content, ensure_ascii=False),
        }
    else:
        # 纯文本回退
        body = {
            "receive_id": CHAT_ID,
            "msg_type": "text",
            "content": json.dumps(
                {"text": f"{clean_name}伙伴 {praise_text}"}, ensure_ascii=False
            ),
        }

    resp = requests.post(url, headers=auth_headers(token), params=params, json=body)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        log.error("发送消息失败: %s", data)
    else:
        log.info("夸奖已发送: %s -> %s", clean_name, praise_text[:40])


# ---------------------------------------------------------------------------
# 状态管理
# ---------------------------------------------------------------------------
def load_state() -> dict:
    """从 state.json 加载状态。"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
            log.info("加载状态: %d 条已处理消息, %d 人话术记录, last_check_time=%s",
                     len(state.get("processed_ids", [])),
                     len(state.get("used_praise", {})),
                     state.get("last_check_time", "未设置"))
            return state
        except (json.JSONDecodeError, IOError) as e:
            log.warning("加载 state.json 失败，使用空状态: %s", e)
    return {"processed_ids": [], "used_praise": {}, "members": {}, "last_check_time": None}


def save_state(state: dict):
    """保存状态到 state.json。"""
    # 限制已处理消息 ID 数量
    ids = state.get("processed_ids", [])
    if len(ids) > 1000:
        state["processed_ids"] = ids[-500:]
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    log.info("状态已保存")


# ---------------------------------------------------------------------------
# 主逻辑
# ---------------------------------------------------------------------------
def run():
    if not APP_ID or not APP_SECRET:
        log.error("缺少环境变量 FEISHU_APP_ID 或 FEISHU_APP_SECRET")
        return

    # 1. 加载状态
    state = load_state()
    processed_ids = set(state.get("processed_ids", []))
    used_praise = state.get("used_praise", {})  # {clean_name: [idx, ...]}
    member_map = state.get("members", {})
    last_check_time = state.get("last_check_time")

    # 2. 获取 token 和机器人信息
    token = get_tenant_token()
    bot_info = get_bot_info(token)
    bot_open_id = bot_info.get("open_id", "")

    # 3. 刷新群成员（每次都刷新，因为是每 30 分钟才执行一次）
    member_map = fetch_members(token)
    if not member_map:
        log.warning("群成员为空，使用缓存")
        member_map = state.get("members", {})

    # 4. 计算消息拉取起始时间
    now = int(time.time())
    if last_check_time:
        # 从上次检查时间开始，但不超过最大回溯时间
        start_ts = max(last_check_time, now - MAX_LOOKBACK_SECONDS)
        log.info("从上次检查时间开始: %s (距今 %.1f 分钟)",
                 time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start_ts)),
                 (now - start_ts) / 60)
    else:
        # 首次运行，使用默认回溯时间
        start_ts = now - DEFAULT_LOOKBACK_SECONDS
        log.info("首次运行，回溯 %.1f 小时", DEFAULT_LOOKBACK_SECONDS / 3600)

    messages = fetch_messages(token, str(start_ts))

    # 5. 检测 @机器人 的消息并汇总发送给管理员
    at_messages = []
    if bot_open_id:
        at_messages = detect_at_bot_messages(messages, bot_open_id, processed_ids, member_map)
        if at_messages:
            send_at_summary(token, at_messages)
            # 记录已处理的 @消息
            for msg in at_messages:
                if msg["msg_id"] not in processed_ids:
                    processed_ids.add(msg["msg_id"])
    else:
        log.warning("无法获取机器人 open_id，跳过 @消息检测")

    # 6. 检测成单卡片并发送夸奖
    new_praise_processed = []
    for msg in messages:
        msg_id = msg.get("message_id", "")
        if msg_id in processed_ids:
            continue

        msg_type = msg.get("msg_type", "")
        sender_type = msg.get("sender", {}).get("sender_type", "")

        if msg_type != "interactive" or sender_type != "app":
            continue

        # 解析卡片内容
        try:
            content = json.loads(msg.get("body", {}).get("content", "{}"))
        except json.JSONDecodeError:
            continue

        # 从 header.title 或顶层 title 取标题
        title = ""
        if "header" in content:
            title_obj = content["header"].get("title", {})
            if isinstance(title_obj, dict):
                title = title_obj.get("content", "")
            elif isinstance(title_obj, str):
                title = title_obj
        if not title:
            title = content.get("title", "")
        if not title and isinstance(content.get("header"), dict):
            title = content["header"].get("title", "")
            if isinstance(title, dict):
                title = title.get("content", "")

        # 匹配 "恭喜XXX成单"
        m = re.search(r"恭喜(.+?)成单", title)
        if not m:
            continue

        raw_name = m.group(1).strip()
        clean_name, open_id = match_member(raw_name, member_map)
        amount_text, amount_value = extract_amount(content)

        log.info("检测到成单: %s (raw=%s), 金额=%s (%.0f元), open_id=%s",
                 clean_name, raw_name, amount_text, amount_value, open_id)

        # 选话术并发送
        praise_text = pick_praise(clean_name, amount_text, used_praise)
        send_praise(token, clean_name, open_id, praise_text)

        new_praise_processed.append(msg_id)

    # 7. 保存状态（记录本次检查时间）
    all_processed = list(processed_ids) + new_praise_processed
    state = {
        "processed_ids": all_processed,
        "used_praise": used_praise,
        "members": member_map,
        "last_check_time": now,  # 记录本次检查时间，下次从这里开始
    }
    save_state(state)

    log.info("本次执行完毕: 成单 %d 条, @消息 %d 条, 下次从 %s 开始检查",
             len(new_praise_processed), len(at_messages),
             time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)))


if __name__ == "__main__":
    run()
