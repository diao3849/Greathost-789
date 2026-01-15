const EMAIL = process.env.GREATHOST_EMAIL || '';
const PASSWORD = process.env.GREATHOST_PASSWORD || '';
const CHAT_ID = process.env.CHAT_ID || '';
const BOT_TOKEN = process.env.BOT_TOKEN || '';
const PROXY_URL = (process.env.PROXY_URL || "").trim();

const { firefox } = require("playwright");
const https = require('https');

async function sendTelegramMessage(message) {
    return new Promise((resolve) => {
        const url = `https://api.telegram.org/bot${BOT_TOKEN}/sendMessage`;
        const data = JSON.stringify({ chat_id: CHAT_ID, text: message, parse_mode: 'HTML' });
        const options = { method: 'POST', headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) } };
        const req = https.request(url, options, (res) => {
            res.on('data', () => {});
            res.on('end', () => resolve());
        });
        req.on('error', () => resolve());
        req.write(data);
        req.end();
    });
}

(async () => {
    const GREATHOST_URL = "https://greathost.es";    
    const LOGIN_URL = `${GREATHOST_URL}/login`;
    const HOME_URL = `${GREATHOST_URL}/dashboard`;
    
    let proxyStatusTag = "🌐 直连模式";
    let serverStarted = false;

    let proxyData = null;
    if (PROXY_URL) {
        try {
            const cleanUrl = PROXY_URL.startsWith('socks') ? PROXY_URL : `socks5://${PROXY_URL}`;
            proxyData = new URL(cleanUrl);
            proxyStatusTag = `🔒 代理模式 (${proxyData.host})`;
        } catch (e) { console.error("代理格式错"); }
    }

    let browser;
    try {
        console.log(`🚀 启动任务 | ${proxyStatusTag}`);
        
        browser = await firefox.launch({
            headless: true,
            proxy: proxyData ? { server: `socks5://${proxyData.host}` } : undefined
        });

        const context = await browser.newContext({
            userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',
            viewport: { width: 1280, height: 720 },
            locale: 'es-ES'
        });

        // ⭐ 修正后的 API：是 setCredentials 而不是 setHttpCredentials
        if (proxyData && proxyData.username) {
            await context.setCredentials({
                username: proxyData.username,
                password: proxyData.password
            });
            console.log("🔑 凭据注入成功");
        }

        const page = await context.newPage();

        await page.addInitScript(() => {
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
        });

        if (proxyData) {
            try {
                await page.goto("https://api.ipify.org?format=json", { timeout: 20000 });
                console.log(`✅ 出口 IP: ${await page.innerText('body')}`);
            } catch (e) { console.log("⚠️ IP 检测超时..."); }
        }

        // --- 核心业务逻辑 (原汁原味) ---
        await page.goto(LOGIN_URL, { waitUntil: "domcontentloaded" });
        await page.fill('input[name="email"]', EMAIL);
        await page.fill('input[name="password"]', PASSWORD);
        await Promise.all([
            page.click('button[type="submit"]'),
            page.waitForNavigation({ waitUntil: "networkidle" }),
        ]);

        await page.goto(HOME_URL, { waitUntil: "networkidle" });
        const offline = page.locator('span.badge-danger, .status-offline').first();
        if (await offline.isVisible()) {
            const startBtn = page.locator('button.btn-start, button:has-text("Start")').first();
            if (await startBtn.isVisible()) {
                await startBtn.click();
                serverStarted = true;
                await page.waitForTimeout(3000);
            }
        }

        await page.locator('.btn-billing-compact').first().click();
        await page.waitForNavigation({ waitUntil: "networkidle" });

        await page.getByRole('link', { name: 'View Details' }).first().click();
        await page.waitForNavigation({ waitUntil: "networkidle" });
        
        const serverId = page.url().split('/').pop() || 'unknown';
        const beforeHoursText = await page.textContent('#accumulated-time');
        const beforeHours = parseInt(beforeHoursText.replace(/[^0-9]/g, '')) || 0;

        const renewBtn = page.locator('#renew-free-server-btn');
        const btnContent = await renewBtn.innerHTML();

        if (btnContent.includes('Wait')) {
            const waitTime = btnContent.match(/\d+/)?.[0] || "??";
            await sendTelegramMessage(`⏳ 服务器 ${serverId} 冷却中，剩余 ${waitTime} 分钟。`);
            return;
        }

        await page.mouse.wheel(0, 300);
        await page.waitForTimeout(1000);
        await renewBtn.click({ force: true });

        await page.waitForTimeout(15000);
        await page.reload();
        const afterHoursText = await page.textContent('#accumulated-time');
        const afterHours = parseInt(afterHoursText.replace(/[^0-9]/g, '')) || 0;
        
        await sendTelegramMessage(`🎉 <b>GreatHost 续期结果</b>\nID: ${serverId}\n状态: ${beforeHours}h -> ${afterHours}h`);

    } catch (err) {
        console.error("❌ 崩溃:", err.message);
        await sendTelegramMessage(`🚨 <b>GreatHost 异常</b>\n${err.message}`);
    } finally {
        if (browser) await browser.close();
    }
})();
