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
# 话术模板（共 90 条，更自然的表达）
# ---------------------------------------------------------------------------

# 热血鼓励型 - 真诚但不浮夸
PRAISE_RELIE = [
    "好家伙 {name}，{amount} 拿下了！最近状态真的很好啊，继续保持！",
    "{name} 又成了！{amount}，这个月势头很猛啊，期待你更多好消息",
    "漂亮！{name} 搞定 {amount}，看得出来这单跟得很细致",
    "{name} 稳稳拿下 {amount}，这执行力没得说，给你点赞",
    "恭喜 {name}！{amount} 到手，最近真的很能打",
    "{name} 又进账 {amount}，保持这个节奏，月底冲一波",
    "不错不错，{name} 又下一城，{amount} 收入囊中",
    "{name} 成了！{amount}，这单跟了多久？功夫不负有心人啊",
    "给 {name} 鼓掌，{amount} 漂亮收官！这个月还能再冲冲",
    "{name} 拿下 {amount}，越来越稳了，继续加油",
    "好消息！{name} 又成单了，{amount}，势头很好",
    "{name} 搞定 {amount}，这效率可以的，下一单继续",
    "恭喜 {name}！{amount} 顺利成交，看好你这个月的表现",
    "{name} 又传来好消息，{amount} 到账！稳扎稳打",
    "漂亮，{name} 再下一单 {amount}，保持这个手感",
    "{name} 成单 {amount}，最近状态在线啊",
    "不出所料，{name} 又成了，{amount}，靠谱！",
    "{name} 拿下 {amount}！这个客户跟得不容易吧，恭喜",
    "给力！{name} 又一单 {amount} 落袋",
    "{name} 持续输出中，{amount} 又到手了",
    "恭喜 {name} 成单 {amount}，继续冲！",
    "{name} 又赢了，{amount} 拿下，nice！",
    "稳！{name} 再收 {amount}，这个月有戏",
    "{name} 捷报频传啊，{amount} 又进了",
    "佩服，{name} 又成一单 {amount}，向你学习",
    "{name} 太稳了，{amount} 轻松拿捏",
    "厉害了 {name}，{amount} 说成就成",
    "{name} 这波操作很溜，{amount} 收下",
    "恭喜恭喜，{name} 又进账 {amount}",
    "{name} 再添 {amount}，保持这个势头",
]

# 轻松幽默型 - 像朋友间的调侃
PRAISE_QINGSONG = [
    "{name} 你是不是偷偷开挂了？{amount} 也太顺了",
    "救命，{name} 又成单了，{amount}，能不能给别人留点机会",
    "{name} 这是什么成单体质？{amount} 说来就来",
    "打扰了，{name} 又在秀 {amount}，我先酸为敬",
    "{name} 今天的KPI是不是已经完成了？{amount} 又进了",
    "好家伙 {name}，{amount}，你这是打算承包这个月吗",
    "{name} 请问成单秘籍考虑分享一下吗？{amount} 看馋了",
    "被 {name} 凡尔赛到了，又是轻松成单 {amount} 的一天",
    "{name} 你认真的吗？{amount} 就这么成了？",
    "等等，让我消化一下，{name} 又双叒成单了？{amount}",
    "{name} 是懂怎么让同事破防的，{amount} 直接拿下",
    "建议 {name} 出个教程，{amount} 这个手速教教我们",
    "{name} 你这样让别人怎么活？{amount} 又来",
    "合理怀疑 {name} 是机器人，{amount} 效率太离谱",
    "{name} 今天也在营业中，{amount} 轻松到手",
    "又被 {name} 内卷到了，{amount} 收得漂亮",
    "{name} 快说，{amount} 这单怎么谈的？速速交代",
    "好好好，{name} 又是领先的一天，{amount} 拿下",
    "{name} 请收下我的膝盖，{amount} 这波操作秀到我了",
    "得，{name} 又行了，{amount}，我服了",
    "{name} 你礼貌吗？{amount} 成单不提前说一声",
    "破案了，{name} 才是团队隐藏的大佬，{amount} 又来",
    "{name} 今天份的低调炫耀：{amount}",
    "求 {name} 传授一下，{amount} 到底怎么做到的",
    "确认过眼神，{name} 是要冲榜的人，{amount} 收好",
    "{name} 请问你是充了会员吗？{amount} 这也太顺",
    "有被 {name} 惊到，{amount}，可以的",
    "{name} 低调成单 {amount}，高调实力",
    "又是 {name} 的主场，{amount} 拿下",
    "所以 {name} 的秘诀到底是什么？{amount} 羡慕了",
]

# 真诚暖心型 - 走心但不煽情
PRAISE_ZHENXIN = [
    "{name} 辛苦了，{amount} 这单不容易，你的付出大家都看在眼里",
    "恭喜 {name}！{amount} 是对你专业和耐心最好的回报",
    "{name} 成单 {amount}，每一次成交都是你用心服务的结果",
    "为 {name} 高兴，{amount} 来之不易，你值得",
    "{name} 的努力终于开花结果了，{amount} 恭喜！",
    "一直很欣赏 {name} 的专业态度，{amount} 实至名归",
    "{name} 又帮一个家庭做了好的选择，{amount}，有意义",
    "知道 {name} 这单跟了很久，{amount} 终于成了，替你开心",
    "{name} 成单 {amount}，靠的是实力，不是运气",
    "看到 {name} 成单 {amount} 真的很开心，你一直很努力",
    "{name} 又收获了客户的信任，{amount}，这是最好的肯定",
    "恭喜 {name}，{amount} 的背后是你无数次的用心沟通",
    "{name} 这单 {amount} 谈得漂亮，专业度拉满",
    "为 {name} 点赞，{amount} 证明了认真做事的人不会被辜负",
    "{name} 的成长大家有目共睹，{amount} 是应得的",
    "真心替 {name} 高兴，{amount}，继续保持这份热情",
    "{name} 成单 {amount}，感谢你为团队带来的正能量",
    "每次看到 {name} 成单都很欣慰，{amount}，越来越好了",
    "{name} 用心服务的样子真的很棒，{amount} 是最好的证明",
    "恭喜 {name} 收获 {amount}，你的专业客户能感受到",
    "{name} 这个月进步很大，{amount} 又一个里程碑",
    "看好 {name}，{amount} 只是开始，后面会更好",
    "{name} 成单 {amount}，踏实做事的人运气不会差",
    "为 {name} 的 {amount} 鼓掌，每一单都是信任的积累",
    "{name} 又帮到一个家庭了，{amount}，很有成就感吧",
    "恭喜 {name}！{amount} 背后的努力，懂的人都懂",
    "{name} 越来越稳了，{amount} 水到渠成",
    "看到 {name} 成单 {amount}，团队也跟着开心",
    "{name} 的认真劲儿值得学习，{amount} 恭喜",
    "{name} 又一单 {amount}，期待你更多好消息",
]

ALL_PRAISE = PRAISE_RELIE + PRAISE_QINGSONG + PRAISE_ZHENXIN  # 90 条


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
    """为指定人选一条不重复的话术。"""
    total = len(ALL_PRAISE)
    used_set = used.get(clean_name, [])
    available = [i for i in range(total) if i not in used_set]
    if not available:
        # 所有话术用完，重置
        used[clean_name] = []
        available = list(range(total))
    idx = random.choice(available)
    used.setdefault(clean_name, []).append(idx)
    template = ALL_PRAISE[idx]
    return template.format(name=clean_name, amount=amount)


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

    # 2. 获取 token
    token = get_tenant_token()

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

    # 5. 检测成单卡片并发送夸奖
    new_processed = []
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

        new_processed.append(msg_id)

    # 6. 保存状态（记录本次检查时间）
    all_processed = list(processed_ids) + new_processed
    state = {
        "processed_ids": all_processed,
        "used_praise": used_praise,
        "members": member_map,
        "last_check_time": now,  # 记录本次检查时间，下次从这里开始
    }
    save_state(state)

    log.info("本次执行完毕: 检测到 %d 条新成单, 下次从 %s 开始检查",
             len(new_processed),
             time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)))


if __name__ == "__main__":
    run()
