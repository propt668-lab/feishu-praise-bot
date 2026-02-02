#!/usr/bin/env python3
"""
飞书成单夸奖机器人 — 一次性执行脚本
由 GitHub Actions 每 30 分钟触发一次。
从 state.json 加载状态，拉取最近 35 分钟群消息，检测成单卡片并发送夸奖，保存状态后退出。
"""

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

# 拉取最近 35 分钟的消息（留 5 分钟重叠防遗漏）
LOOKBACK_SECONDS = 35 * 60

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
# 话术模板（共 100 条）
# ---------------------------------------------------------------------------
PRAISE_JIXUE = [
    "🔥🔥🔥 {name} 杀疯了！{amount} 霸气到账！这就是冠军的节奏，继续冲冲冲！",
    "💪 {name} 势不可挡！一单 {amount}，直接起飞！下一单已经在路上了吧！🚀",
    "⚡ {name} 又双叒叕开单了！{amount} 收入囊中！你就是团队的业绩发动机！",
    "🏆 {name} 王者归来！{amount} 大单落袋！这气势，谁能挡得住！冲冲冲！",
    "🦁 {name} 虎虎生威！{amount} 手到擒来！保持这个状态，月度冠军稳了！",
    "🔥 {name} 火力全开！{amount} 强势入账！你的目标不是山顶，是星辰大海！",
    "💰 {name} 太炸了！{amount} 一击必杀！这份霸气，全场为你沸腾！",
    "🚀 {name} 直接封神！{amount} 帅气收割！团队因你而骄傲，继续拿下！",
    "⚔️ {name} 战力爆表！{amount} 强势斩获！这就是实力，无需多言！冲！",
    "🏅 {name} 就是传奇！{amount} 完美拿下！这个势头，谁与争锋！",
    "🔥 {name} 挡不住的节奏！{amount} 又进一单！这就是赢家的状态，持续输出！",
    "💪 {name} 干得漂亮！{amount} 完美成交！你的字典里只有「成交」两个字！",
    "⚡ {name} 闪电出击！{amount} 精准拿下！效率之王就是你！下一个目标在招手！",
    "🏆 {name} 一路狂飙！{amount} 势如破竹！这个月就是你的主场！",
    "🔥 {name} 业绩炸裂！{amount} 再下一城！你就是这条街最靓的仔！冲！",
    "💥 {name} 又爆单了！{amount} 强势出击！团队的MVP非你莫属！",
    "🚀 {name} 无人能敌！{amount} 征服全场！保持这个劲头，顶峰见！",
    "🔥 {name} 燃起来了！{amount} 完美收割！这把火越烧越旺，谁也灭不了！",
    "💪 {name} 绝对实力！{amount} 教科书级别成交！冠军之路，一往无前！",
    "⚡ {name} 效率拉满！{amount} 精准命中！这才是专业选手的风范！继续！",
    "🦅 {name} 一飞冲天！{amount} 高歌猛进！天花板在哪？不存在的！",
    "🏆 {name} 霸榜预定！{amount} 势在必得！你是团队的荣耀，冲击更高！",
    "🔥 {name} 全场最佳！{amount} 实至名归！下一单继续，目标只有更高！",
    "💰 {name} 提款机模式开启！{amount} 稳如磐石！这效率，无敌是多么寂寞！",
    "⚔️ {name} 一路碾压！{amount} 王者之姿！气势如虹，下一单继续收割！",
    "🔥 {name} 开挂了吧！{amount} 轻松拿捏！这个节奏，月度目标稳超！",
    "💪 {name} 太能打了！{amount} 连战连捷！你的战斗力，让人叹为观止！",
    "🚀 {name} 起步就是巅峰！{amount} 霸气侧漏！这才刚开始，后面更精彩！",
    "🏅 {name} 用实力说话！{amount} 一锤定音！最强顾问的称号，实至名归！",
    "⚡ {name} 秒杀全场！{amount} 完美操作！这就是专业的力量，继续碾压！",
    "🔥 {name} 你就是标杆！{amount} 强势领跑！所有人都在追赶你的步伐！",
    "💥 {name} 王炸出击！{amount} 一步到位！团队之光，冲击新高度！",
    "🏆 {name} 不可阻挡！{amount} 气吞万里！这个赛道上，你就是第一！",
    "🔥 {name} 狼王出击！{amount} 猛虎下山！这份狠劲，对手都要抖三抖！",
    "💪 {name} 永远的神！{amount} 再立新功！YYDS不是说说而已，是你的代名词！",
]

PRAISE_GAOXIAO = [
    "😱 {name} 又出单了？！{amount}！请问你是开了外挂还是自带BGM？🎵",
    "🤑 {name} 的钱包又鼓了！{amount} 到手！建议今晚请全组吃饭，不接受反驳！🍽️",
    "😎 {name} 一出手就是 {amount}！请问是在座的各位谁还不服？有请站出来！",
    "🐂 牛啊 {name}！{amount} 又来了！你是不是把客户的心理学教材背下来了？📚",
    "🎰 {name} 简直是行走的提款机！{amount} 到账！你的运气值已经溢出了！",
    "😏 {name} 又赢麻了！{amount}！别人还在起跑线，你已经到终点吃瓜了！🍉",
    "🤯 {name} 太离谱了！{amount} 说来就来！请问你的成单秘籍出书了吗？想预购！📖",
    "🐲 {name} 化身成单小龙人！{amount} 火焰喷射！建议给你配个专属庆功BGM！🎶",
    "😂 {name} 又偷偷成单了？{amount}！别藏了，你的实力已经藏不住了！",
    "🎪 {name} 今日份的表演：{amount} 完美成交！观众们，掌声在哪里！👏👏",
    "🍾 {name} 要不要考虑改名叫「成单侠」？{amount} 又一战成名！",
    "😎 {name} 一单 {amount}，别人在追月度目标，你在追年度纪录吧？",
    "🦸 {name} 的超能力又发动了！{amount}！这不是开单，这是变魔术！🎩",
    "🤣 {name} 的日常：起床、成单 {amount}、下班。就这么朴实无华且枯燥！",
    "🏎️ {name} 的成单速度比法拉利还快！{amount} 秒到！请问你的涡轮增压在哪买的？",
    "😱 {name} 又来了！{amount}！拜托，给别人也留点客户好吗（不是）！",
    "🧙 {name} 施展了成单魔法！{amount} 凭空出现！请问这个咒语能教教我们吗？",
    "🐯 {name} 今天又吃肉了！{amount} 大口吞！其他小伙伴连汤都没喝上 🥲",
    "🎯 {name} 是GPS定位成单吗？{amount} 精准锁定！这准头，比导弹还稳！",
    "😏 {name} 出单 {amount}，风轻云淡仿佛只是喝了杯咖啡！这份从容，我学不来！☕",
    "🤖 {name} 是不是偷偷接入了AI？{amount} 效率逆天！申请对你进行图灵测试！",
    "🎲 {name} 掷骰子都能掷出 {amount}！运气和实力双满分，太可怕了！",
    "🍕 {name} 出单比我吃午饭还快！{amount} 瞬间搞定！等等我，我饭还没吃完！",
    "🎬 {name} 的成单故事可以拍电影了！{amount} 大制作！片名就叫《不可阻挡》！",
    "🦄 {name} 简直是传说中的成单独角兽！{amount}！其稀有程度堪比中彩票！",
    "😂 {name} 对客户说了什么？{amount} 就这么成了？快录个教学视频！📹",
    "🎵 叮~{name} 的账户到账 {amount}！这个提示音，是全组最动听的旋律！",
    "🐧 {name} 走路都带风！{amount} 入账后的自信步伐，请脑补一下！",
    "📱 {name} 的手机是不是自带成单功能？{amount} 就这么打了个电话的事？",
    "🤩 {name} 出单 {amount}！建议公司给你颁发「最佳销售体验官」证书！",
    "🎁 {name} 又给团队送大礼了！{amount}！这份惊喜来得猝不及防！",
    "🌪️ {name} 简直是成单旋风！{amount} 卷走一切！请叫你「龙卷风顾问」！",
    "🧲 {name} 自带磁力吧？{amount} 的客户直接被你吸过来了！这体质太强！",
    "🎤 {name} 出单 {amount}！如果成单能参加比赛，你已经是全国总冠军了！",
    "😎 {name} 打了个哈欠，{amount} 就到账了。这叫什么？这叫降维打击！",
]

PRAISE_ZOUXIN = [
    "🌟 {name} 辛苦了！{amount} 的背后是你日复一日的专业和坚持，这份努力大家都看在眼里！",
    "❤️ {name} 真的很棒！{amount} 不只是数字，更是你对每一位家长用心服务的证明！",
    "🌸 {name} 又一次用实力证明了自己！{amount} 来之不易，你值得所有的掌声和认可！",
    "💫 {name} 每一单的背后都有你默默的付出和准备，{amount} 是最好的回报！为你骄傲！",
    "🌿 {name} 你的坚持终于开花结果！{amount} 是你专业态度的最好注脚，继续加油！",
    "💝 {name} 用心对待每一位客户，{amount} 是客户对你信任的证明！你的真诚，无可替代！",
    "🌻 {name} 你是团队的榜样！{amount} 的背后是无数次耐心的沟通和专业的引导，谢谢你！",
    "✨ {name} 了不起！{amount} 成交的不只是金额，是家长对你的信赖，是孩子成长的开始！",
    "🌈 {name} 的付出从不会被辜负！{amount} 证明了只要用心，好的结果一定会来！",
    "💖 {name} 你的专业和温度打动了客户！{amount} 是最好的回报，你值得！",
    "🌹 {name} 为你鼓掌！{amount} 的成交源于你对教育的热忱和对家庭的关怀，了不起！",
    "🍀 {name} 每一步都走得很扎实，{amount} 是水到渠成的结果！继续保持这份初心！",
    "💐 {name} 真心为你高兴！{amount} 不仅是业绩，更是你对这份工作热爱的体现！",
    "🌟 {name} 默默耕耘终有收获！{amount} 是对你最好的肯定，团队以你为荣！",
    "🤝 {name} 赢得客户的信任是最难的事，而你做到了！{amount} 实至名归！",
    "💫 {name} 你的努力和认真，大家有目共睹！{amount} 只是开始，未来可期！",
    "🌷 {name} 总是能给团队带来惊喜！{amount} 的成交背后，是你对专业的不懈追求！",
    "❤️ {name} 每一单都凝聚着你的心血！{amount} 这份沉甸甸的成绩，你应该为自己骄傲！",
    "🌟 {name} 你让我们看到了什么叫真正的用心服务！{amount} 是最美好的回馈！",
    "💪 {name} 困难从来打不倒你！{amount} 又一次证明了你的韧劲和实力！",
    "🌺 {name} 从沟通到成交，每一步都体现了你的专业素养！{amount} 当之无愧！",
    "💝 {name} 客户选择你，因为你值得信赖！{amount} 是信任的重量，好好珍惜！",
    "🌟 {name} 你今天的成绩来自昨天的积累！{amount} 背后是一个个认真准备的夜晚！",
    "🍃 {name} 脚踏实地，仰望星空！{amount} 只是你成长路上的一个里程碑，继续闪耀！",
    "💖 {name} 你用行动诠释了什么叫专业！{amount} 成交的那一刻，整个团队都为你自豪！",
    "🌟 {name} 你的温柔和坚定同样打动人心！{amount} 的成绩是你最好的名片！",
    "🤗 {name} 谢谢你为团队带来的正能量！{amount} 的好消息让所有人都充满干劲！",
    "💫 {name} 在这条路上你一直很努力！{amount} 是你应得的，未来会更好！相信自己！",
    "🌸 {name} 你总是能把不可能变成可能！{amount} 再次证明了你的非凡能力！",
    "❤️ {name} 你不只是在卖课，你是在帮助每个家庭找到最好的选择！{amount} 是最好的证明！",
]

ALL_PRAISE = PRAISE_JIXUE + PRAISE_GAOXIAO + PRAISE_ZOUXIN  # 100 条


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
    params = {
        "container_id_type": "chat",
        "container_id": CHAT_ID,
        "start_time": start_time,
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


def extract_amount(content_obj: dict) -> str:
    """从卡片内容中提取金额，未找到则返回 '一笔大单'。"""
    full_text = json.dumps(content_obj, ensure_ascii=False)
    m = re.search(r"(\d[\d,]*\.?\d*)\s*元", full_text)
    return f"{m.group(1)}元" if m else "一笔大单"


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
            log.info("加载状态: %d 条已处理消息, %d 人话术记录",
                     len(state.get("processed_ids", [])),
                     len(state.get("used_praise", {})))
            return state
        except (json.JSONDecodeError, IOError) as e:
            log.warning("加载 state.json 失败，使用空状态: %s", e)
    return {"processed_ids": [], "used_praise": {}, "members": {}}


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

    # 2. 获取 token
    token = get_tenant_token()

    # 3. 刷新群成员（每次都刷新，因为是每 30 分钟才执行一次）
    member_map = fetch_members(token)
    if not member_map:
        log.warning("群成员为空，使用缓存")
        member_map = state.get("members", {})

    # 4. 拉取最近 35 分钟的消息
    start_ts = str(int(time.time()) - LOOKBACK_SECONDS)
    messages = fetch_messages(token, start_ts)

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
        amount = extract_amount(content)

        log.info("检测到成单: %s (raw=%s), 金额=%s, open_id=%s",
                 clean_name, raw_name, amount, open_id)

        # 选话术并发送
        praise_text = pick_praise(clean_name, amount, used_praise)
        send_praise(token, clean_name, open_id, praise_text)

        new_processed.append(msg_id)

    # 6. 保存状态
    all_processed = list(processed_ids) + new_processed
    state = {
        "processed_ids": all_processed,
        "used_praise": used_praise,
        "members": member_map,
    }
    save_state(state)

    log.info("本次执行完毕: 检测到 %d 条新成单", len(new_processed))


if __name__ == "__main__":
    run()
