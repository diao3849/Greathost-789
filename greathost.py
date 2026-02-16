##### greathost.py 优化版 - 修复 Telegram 推送 #####
import os, re, time, json, requests
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from seleniumwire import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# 环境变量读取
EMAIL = os.getenv("GREATHOST_EMAIL", "")
PASSWORD = os.getenv("GREATHOST_PASSWORD", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
PROXY_URL = os.getenv("PROXY_URL", "")  # socks5代理，可留空
TARGET_NAME = os.getenv("TARGET_NAME", "xyz666")  # 目标服务器名

STATUS_MAP = {
    "running": ["🟢", "Running"],
    "starting": ["🟡", "Starting"],
    "stopped": ["🔴", "Stopped"],
    "offline": ["⚪", "Offline"],
    "suspended": ["🚫", "Suspended"]
}

def now_shanghai():
    """返回上海时区当前时间字符串"""
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime('%Y/%m/%d %H:%M:%S')

def calculate_hours(date_str):
    """计算从当前UTC到到期时间的剩余小时数"""
    try:
        if not date_str:
            return 0
        clean = re.sub(r'\.\d+Z$', 'Z', date_str)
        expiry = datetime.fromisoformat(clean.replace('Z', '+00:00'))
        diff = (expiry - datetime.now(timezone.utc)).total_seconds() / 3600
        return max(0, int(diff))
    except Exception as e:
        print(f"⚠️ 时间解析失败: {e}")
        return 0

def send_notice(kind, fields):
    """
    发送 Telegram 通知，并写入 README.md
    kind: 通知类型（用于标题）
    fields: 列表，每个元素为 (emoji, label, value)
    """
    titles = {
        "renew_success": "🎉 <b>GreatHost 续期成功</b>",
        "maxed_out": "🈵 <b>GreatHost 已达上限</b>",
        "cooldown": "⏳ <b>GreatHost 还在冷却中</b>",
        "renew_failed": "⚠️ <b>GreatHost 续期未生效</b>",
        "error": "🚨 <b>GreatHost 脚本报错</b>"
    }
    # 组装消息体
    body = "\n".join([f"{emoji} {label}: {value}" for emoji, label, value in fields])
    msg = f"{titles.get(kind, '📢 通知')}\n\n{body}\n📅 时间: {now_shanghai()}"

    # ----- Telegram 推送（强制直连）-----
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            print(f"📤 尝试发送 Telegram 消息: {msg[:50]}...")  # 调试输出
            # 使用空字典 proxies={} 强制不使用任何代理
            resp = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": msg,
                    "parse_mode": "HTML"
                },
                proxies={},      # 关键修复：不经过代理
                timeout=10
            )
            resp.raise_for_status()  # 抛出 HTTP 错误
            print("✅ Telegram 推送成功")
        except Exception as e:
            print(f"❌ Telegram 推送失败: {e}")
    else:
        print("⚠️ Telegram 环境变量未设置，跳过推送")

    # ----- 写入 README.md（可选）-----
    try:
        # 将 HTML 标签转为 Markdown 粗体/代码
        md = msg.replace("<b>", "**").replace("</b>", "**").replace("<code>", "`").replace("</code>", "`")
        with open("README.md", "w", encoding="utf-8") as f:
            f.write(f"# GreatHost 自动续期状态\n\n{md}\n\n> 最近更新: {now_shanghai()}")
    except Exception as e:
        print(f"⚠️ 写入 README.md 失败: {e}")

class GH:
    """GreatHost 自动化操作类"""
    def __init__(self):
        opts = Options()
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        # 配置代理（如果提供了 PROXY_URL）
        seleniumwire_options = {'proxy': {'http': PROXY_URL, 'https': PROXY_URL}} if PROXY_URL else None
        self.d = webdriver.Chrome(options=opts, seleniumwire_options=seleniumwire_options)
        self.w = WebDriverWait(self.d, 25)

    def api(self, url, method="GET"):
        """通过 JavaScript 执行 API 请求"""
        print(f"📡 API 调用 [{method}] {url}")
        script = f"return fetch('{url}',{{method:'{method}'}}).then(r=>r.json()).catch(e=>({{success:false,message:e.toString()}}))"
        return self.d.execute_script(script)

    def get_ip(self):
        """获取当前出口 IP（用于调试）"""
        try:
            self.d.get("https://api.ipify.org?format=json")
            ip = json.loads(self.d.find_element(By.TAG_NAME, "body").text).get("ip", "Unknown")
            print(f"🌐 落地 IP: {ip}")
            return ip
        except Exception as e:
            print(f"🌐 无法获取 IP: {e}")
            return "Unknown"

    def login(self):
        """登录 GreatHost"""
        print(f"🔑 正在登录: {EMAIL[:3]}***...")
        self.d.get("https://greathost.es/login")
        self.w.until(EC.presence_of_element_located((By.NAME, "email"))).send_keys(EMAIL)
        self.d.find_element(By.NAME, "password").send_keys(PASSWORD)
        self.d.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        self.w.until(EC.url_contains("/dashboard"))

    def get_server(self):
        """获取目标服务器信息"""
        servers = self.api("/api/servers").get("servers", [])
        return next((s for s in servers if s.get("name") == TARGET_NAME), None)

    def get_status(self, sid):
        """获取服务器状态（带图标）"""
        info = self.api(f"/api/servers/{sid}/information")
        st = info.get("status", "unknown").lower()
        icon, name = STATUS_MAP.get(st, ["❓", st])
        print(f"📋 状态核对: {TARGET_NAME} | {icon} {name}")
        return icon, name

    def get_renew_info(self, sid):
        """获取续期信息"""
        data = self.api(f"/api/renewal/contracts/{sid}")
        print(f"DEBUG: 原始合同数据 -> {str(data)[:100]}...")
        return data.get("contract", {}).get("renewalInfo") or data.get("renewalInfo", {})

    def get_btn(self, sid):
        """获取续期按钮文本（用于判断冷却）"""
        self.d.get(f"https://greathost.es/contracts/{sid}")
        btn = self.w.until(EC.presence_of_element_located((By.ID, "renew-free-server-btn")))
        self.w.until(lambda d: btn.text.strip() != "")
        btn_text = btn.text.strip()
        print(f"🔘 按钮状态: '{btn_text}'")
        return btn_text

    def renew(self, sid):
        """执行续期 POST 请求"""
        print(f"🚀 正在执行续期 POST...")
        return self.api(f"/api/renewal/contracts/{sid}/renew-free", "POST")

    def close(self):
        """关闭浏览器"""
        self.d.quit()

def run():
    gh = None
    try:
        gh = GH()
        ip = gh.get_ip()
        gh.login()
        srv = gh.get_server()
        if not srv:
            raise Exception(f"未找到服务器 {TARGET_NAME}")
        sid = srv["id"]
        print(f"✅ 已锁定目标服务器: {TARGET_NAME} (ID: {sid})")

        icon, stname = gh.get_status(sid)
        status_disp = f"{icon} {stname}"

        info = gh.get_renew_info(sid)
        before = calculate_hours(info.get("nextRenewalDate"))

        btn = gh.get_btn(sid)
        print(f"🔘 按钮状态: '{btn}' | 剩余: {before}h")

        # 判断是否在冷却中
        if "Wait" in btn:
            m = re.search(r"Wait\s+(\d+\s+\w+)", btn)
            send_notice("cooldown", [
                ("📛", "服务器名称", TARGET_NAME),
                ("🆔", "ID", f"<code>{sid}</code>"),
                ("⏳", "冷却时间", m.group(1) if m else btn),
                ("📊", "当前累计", f"{before}h"),
                ("🚀", "服务器状态", status_disp)
            ])
            return

        # 执行续期
        res = gh.renew(sid)
        ok = res.get("success", False)
        msg = res.get("message", "无返回消息")
        after = calculate_hours(res.get("details", {}).get("nextRenewalDate")) if ok else before
        print(f"📡 续期响应结果: {ok} | Date='{res.get('details',{}).get('nextRenewalDate')}' | Message='{msg}'")

        if ok and after > before:
            send_notice("renew_success", [
                ("📛", "服务器名称", TARGET_NAME),
                ("🆔", "ID", f"<code>{sid}</code>"),
                ("⏰", "增加时间", f"{before} ➔ {after}h"),
                ("🚀", "服务器状态", status_disp),
                ("💡", "提示", msg),
                ("🌐", "落地 IP", f"<code>{ip}</code>")
            ])
        elif "5 d" in msg or before > 108:
            send_notice("maxed_out", [
                ("📛", "服务器名称", TARGET_NAME),
                ("🆔", "ID", f"<code>{sid}</code>"),
                ("⏰", "剩余时间", f"{after}h"),
                ("🚀", "服务器状态", status_disp),
                ("💡", "提示", msg),
                ("🌐", "落地 IP", f"<code>{ip}</code>")
            ])
        else:
            send_notice("renew_failed", [
                ("📛", "服务器名称", TARGET_NAME),
                ("🆔", "ID", f"<code>{sid}</code>"),
                ("🚀", "服务器状态", status_disp),
                ("⏰", "剩余时间", f"{before}h"),
                ("💡", "提示", msg),
                ("🌐", "落地 IP", f"<code>{ip}</code>")
            ])
    except Exception as e:
        print(f"🚨 运行异常: {e}")
        send_notice("error", [
            ("📛", "服务器名称", TARGET_NAME),
            ("❌", "故障", f"<code>{str(e)[:200]}</code>"),
            ("🌐", "代理状态", "已尝试直连")
        ])
    finally:
        if gh:
            try:
                gh.close()
            except:
                pass

if __name__ == "__main__":
    run()