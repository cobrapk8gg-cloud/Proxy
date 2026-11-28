"""بروتوكولات مزوّدين بدون حسابات (ضيف) المضافة من ملفّي العميل المرفقين:
« ضيف gemini.txt» (Gemini Web بلا كوكيز) و«AI.py» (DeepAI وGigaChat).

هذا الملف معزول تمامًا عن بروتوكولات الحسابات الأصلية في providers.py؛
لا يعدّل سلوكها ولا يُعاد إرسال أي POST تلقائيًا، وتبقى مدققات TLS مفعّلة
(الكود المرجعي كان يعطّلها لـGemini Web فقط، والبروكسي لا يعطّلها أبدًا).
"""

import asyncio
import json
import random
import re
import time
import uuid

import httpx

from .live import TextSnapshot
from .providers import ProviderError, nested

# ---------------------------------------------------------------- Gemini Web
# منقول من « ضيف gemini.txt»: وصول Gemini عبر واجهة الويب بدون كوكيز،
# باستخراج توكن الإجراء ومعرّف الجلسة من صفحة gemini.google.com نفسها.

GEMINI_WEB_PAGE = "https://gemini.google.com"
GEMINI_WEB_URL = (
    "https://gemini.google.com/_/BardChatUi/data/assistant.lamda."
    "BardFrontendService/StreamGenerate"
)
GEMINI_WEB_BUILD = "boq_assistant-bard-web-server_20240519.16_p0"
GEMINI_WEB_TOKEN_KEYS = (
    "uS02ke",
    "SNlM0e",
    "EOzIkf",
    "zChJod",
    "UUFaWc",
    "hsFLT",
    "u4g7r",
)
GEMINI_WEB_HEADERS = {
    "authority": "gemini.google.com",
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9",
    "origin": "https://gemini.google.com",
    "referer": "https://gemini.google.com/",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0 Safari/537.36"
    ),
    "x-same-domain": "1",
    "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
}
# (المعرّف، الاسم المعروض، ترويسة النموذج x-goog-ext-525001261-jspb)
GEMINI_WEB_MODELS = [
    (
        "gemini-3.5-flash",
        "Gemini 3.5 Flash (Web)",
        '[1,null,null,null,"35609594dbe934d8"]',
    ),
    (
        "gemini-deep-research",
        "Gemini Deep Research (Web)",
        '[1,null,null,null,"cd472a54d2abba7e"]',
    ),
]

# ---------------------------------------------------------------- DeepAI
# منقول من AI.py: شات DeepAI بنفس حقول الـFormData بالظبط، وتوليد الصور
# عبر /api/text2img بمفتاح Pro اختياري.

DEEPAI_CHAT_URL = "https://api.deepai.org/hacking_is_a_serious_crime"
DEEPAI_IMAGE_URL = "https://api.deepai.org/api/text2img"
DEEPAI_UA = "Mozilla/5.0"
# (المعرّف، الاسم المعروض، يدعم التفكير)
DEEPAI_MODELS = [
    ("glm-5.3-flash", "GLM 5.3 Flash", True),
    ("standard", "Standard", False),
    ("claude-haiku-5-5", "Claude Haiku 5.5", False),
    ("qwen3.8-flash", "Qwen 3.8 Flash", False),
    ("deepseek-v4.1-flash", "DeepSeek V4.1 Flash", False),
    ("gpt-6-luna", "GPT-6 Luna", False),
    ("tencent-hy3", "Tencent Hy3", False),
    ("gemma-4", "Gemma 4", False),
    ("llama-3.3-70b-instruct", "Llama 3.3 70B", False),
    ("llama-3.1-8b-instant", "Llama 3.1 8B Instant", False),
]
DEEPAI_PAID_MARKS = (
    "Only paid accounts can use genius",
    "only available to paid users",
)
DEEPAI_QUOTA_MARKS = (
    "try it exceeded",
    "try-it quota exceeded",
)

# ---------------------------------------------------------------- GigaChat
# منقول من AI.py: منصة giga.chat بوضع ضيف (دخول prelogin دون حساب) أو وضع
# موثّق عند لصق قيمة كوكي _sm_sess في بيانات الحساب.

GIGA_BASE = "https://giga.chat"
GIGA_APP = "gigachat-b2c-web-neo"
GIGA_VERSION = "0.15.13"
GIGA_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
GIGA_LOGIN_URL = GIGA_BASE + "/api/smartproxy/api/prelogin/api/v0/prelogin/login"
GIGA_TIMEZONE = "Africa/Cairo"
# (المعرّف، الاسم المعروض، الوصف)
GIGA_MODELS = [
    ("reasoning", "تفكير عميق", "GigaChat-3.5-432B-A28B — رياضيات ومنطق خطوة بخطوة"),
    ("giga", "جيجا", "رد سريع عام"),
    ("deep-research", "بحث عميق", "بحث عميق بخطوات LOG — قد يستغرق دقائق"),
    ("education", "تعليم", "شرح وتعليم"),
]
GIGA_AGENTS = {
    "giga": {
        "guest": "cc540466-dc61-403f-8836-ab4c630ad228",
        "authed": "019a5d95-ab99-7c86-a31c-610dad03b054",
    },
    "reasoning": {
        "guest": "cc540466-dc61-403f-8836-ab4c630ad228",
        "authed": "019a5d95-ab99-7c86-a31c-610dad03b054",
    },
    "deep-research": {
        "guest": "019e20bb-666d-753a-a91c-6375e175e7e7",
        "authed": "9384a8fd-39e0-4da9-9bc4-da143487449f",
    },
    "education": {
        "guest": "019e9310-695a-7cd2-8f90-3c06bda7722d",
        "authed": "019df879-c311-708b-a82c-04d73566fe02",
    },
}


def _giga_bytes_from_uuid(s):
    h = s.replace("-", "")
    return bytearray(int(h[i : i + 2], 16) for i in range(0, 32, 2))


def _giga_sum_except(b, skip=None):
    return sum(v for i, v in enumerate(b) if i != skip)


def derive_auth_session_id(device_id):
    """معادلة الجافاسكربت (6819.js module 90560) كما وردت في AI.py بالظبط."""
    r = _giga_bytes_from_uuid(str(uuid.uuid4()))
    i = random.randrange(9)
    r[6] = (0xF0 & r[6]) | i
    a = 7 + i
    n = (
        _giga_sum_except(_giga_bytes_from_uuid(device_id))
        + _giga_sum_except(r, a)
    ) % 256
    r[a] = n
    o = "".join(f"{b:02x}" for b in r)
    return f"{o[0:8]}-{o[8:12]}-{o[12:16]}-{o[16:20]}-{o[20:]}"


def _valid_gemini_token(value):
    """توكن إجراء حقيقي (حروف/أرقام/شرطات فقط). قيم الإعداد العامة مثل
    «%.@.]» و«%.@.null,1000,2]» تُصادف بنفس المفاتيح وتجعل الطلبات
    يفشلها الخادم، لذا تُرفض هنا بدل إرسالها."""
    return bool(value) and bool(re.fullmatch(r"[A-Za-z0-9_\-]{10,}", value))


def _is_guest_placeholder(credential):
    return not credential or credential.startswith("guest-")


def _cookie_string(cookie_map):
    return "; ".join(k + "=" + v for k, v in cookie_map.items() if k and v)


class GuestProtocols:
    """تنفيذ البروتوكولات الثلاثة. يُنشأ مرة واحدة داخل Providers ويعيد
    استخدام client() وchecked() منها فقط لاتساق سياسة المهلات والأخطاء."""

    def __init__(self, base):
        self.base = base
        self.gemini_web_sessions = {}
        self.giga_sessions = {}

    def client(self, **kw):
        return self.base.client(**kw)

    async def checked(self, client, method, url, **kw):
        return await self.base.checked(client, method, url, **kw)

    def clear(self, account_id):
        self.gemini_web_sessions.pop(account_id, None)
        self.giga_sessions.pop(account_id, None)

    # ------------------------------------------------------------ الاكتشاف
    async def discover(self, account):
        provider = account["provider"]
        if provider == "gemini-web":
            return {
                "models": [
                    {"id": mid, "name": name} for mid, name, _ in GEMINI_WEB_MODELS
                ],
                "projects": [],
                "chats": [],
                "capabilities": {
                    "projects": False,
                    "attachments": False,
                    "tools": "emulated",
                },
                "warnings": [
                    "بروتوكول Gemini Web بلا كوكيز: قوائم محادثات الحساب غير متاحة، والسياق يُحفظ محليًا في البروكسي.",
                ],
            }
        if provider == "deepai":
            return {
                "models": [
                    {"id": mid, "name": name} for mid, name, _ in DEEPAI_MODELS
                ],
                "projects": [],
                "chats": [],
                "capabilities": {
                    "projects": False,
                    "attachments": False,
                    "tools": "emulated",
                },
                "warnings": [
                    "DeepAI يعمل بدون مفتاح بحصة مجانية محدودة؛ الصق مفتاح DeepAI Pro في بيانات الحساب لرفع الحدود وتوليد الصور.",
                ],
            }
        return {
            "models": [
                {"id": mid, "name": name} for mid, name, _ in GIGA_MODELS
            ],
            "projects": [],
            "chats": [],
            "capabilities": {
                "projects": False,
                "attachments": False,
                "tools": "emulated",
            },
            "warnings": [
                "GigaChat يعمل بجلسة ضيف تلقائية دون حساب؛ الصق قيمة كوكي _sm_sess في بيانات الحساب للوضع الموثّق.",
            ],
        }

    async def chats(self, account):
        # بروتوكولات الضيف لا تعرض قوائم محادثات من الخدمة.
        return {"items": []}

    async def conversation(self, account, cid):
        # المحادثة الثابتة تعتمد على الحالة المحفوظة محليًا (remote_state).
        return {"conversation_id": cid}

    # ------------------------------------------------------------ Gemini Web
    def _gemini_web_cookies(self, account, session):
        cookies = {}
        credential = account["credential"]
        if "=" in credential:
            for part in credential.split(";"):
                if "=" in part:
                    k, v = part.strip().split("=", 1)
                    cookies[k] = v
        cookies.update(session.get("cookies", {}))
        return _cookie_string(cookies)

    async def gemini_web_session(self, account, refresh=False):
        cached = self.gemini_web_sessions.get(account["id"])
        if cached and cached["expires"] > time.time() and not refresh:
            return cached
        headers = dict(GEMINI_WEB_HEADERS)
        credential = account["credential"]
        if "=" in credential:
            headers["Cookie"] = credential
        # جلب الصفحة مع محاولة ثانية واحدة عند رفض مؤقت من Google
        # (429/5xx مثل 503) لأن جلب الصفحة GET آمن ولا يكرّر رسالة.
        last_status = 0
        for attempt in range(2):
            async with self.client(follow_redirects=True) as client:
                try:
                    response = await self.checked(
                        client, "GET", GEMINI_WEB_PAGE, headers=headers
                    )
                except ProviderError as exc:
                    last_status = getattr(exc, "status", 0)
                    if attempt == 0 and last_status in (429, 502, 503):
                        await asyncio.sleep(2)
                        continue
                    raise ProviderError(
                        "تعذّر جلب صفحة Gemini Web "
                        + (
                            f"(HTTP {last_status}) "
                            if last_status in (429, 502, 503)
                            else ""
                        )
                        + "— قد يكون Google يقيّد عنوان الخادم مؤقتًا؛ أعد المحاولة بعد لحظات."
                    ) from None
                page = response.text
                cookies = {c.name: c.value for c in client.cookies.jar}
            break
        at = None
        # الصفحة الجديدة لم تعد تحمل SNlM0e دائمًا؛ توكن الإجراء في uS02ke
        # مع بدائل أخرى كما في الملف المرجعي، مع رفض قيم الإعداد العامة
        # التالفة (مثل «%.@.]») التي تُفشل الطلبات لاحقًا.
        for key in GEMINI_WEB_TOKEN_KEYS:
            found = re.search(r'"%s":"([^"]{3,80})"' % key, page)
            if found and _valid_gemini_token(found.group(1)):
                at = found.group(1)
                break
        if not at:
            raise ProviderError(
                "لم يُعثر على توكن إجراء Gemini Web صالح في الصفحة؛ أعد المحاولة لاحقًا."
            )
        fsid = re.search(r'"FdrFJe":"([\d-]+)"', page)
        session = {
            "at": at,
            "sid": fsid.group(1) if fsid else "",
            "cookies": cookies,
            "expires": time.time() + 540,
        }
        if len(self.gemini_web_sessions) >= 128:
            self.gemini_web_sessions.pop(next(iter(self.gemini_web_sessions)))
        self.gemini_web_sessions[account["id"]] = session
        return session

    def _gemini_web_payload(self, prompt, state, at):
        if state.get("conversation_id"):
            context = [
                state.get("conversation_id", ""),
                state.get("response_id", ""),
                state.get("choice_id", ""),
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            ]
        else:
            context = [None, None, None, None, None, []]
        data = [
            ["\n \n" + prompt, 0, None, [], None, None, 0],
            ["en"],
            context,
            None,
            None,
            None,
            [],
            0,
            [],
            [],
            1,
            0,
        ]
        return {"at": at, "f.req": json.dumps([None, json.dumps(data)])}

    async def _gemini_web_stream_once(
        self, account, prompt, state, settings, model_x, session, snapshot, timeout
    ):
        """طلب StreamGenerate واحد بقراءة متدفقة حقيقية: إطارات Google
        تصل تراكميًا عبر chunked encoding، والنص ينمو في كل إطار، فيُبث
        ما يصل لحظيًا عبر TextSnapshot بدل انتظار اكتمال الطلب."""
        headers = dict(GEMINI_WEB_HEADERS)
        headers["x-goog-ext-525001261-jspb"] = model_x
        cookies = self._gemini_web_cookies(account, session)
        if cookies:
            headers["Cookie"] = cookies
        body = self._gemini_web_payload(prompt, state, session["at"])
        params = {
            "bl": GEMINI_WEB_BUILD,
            "hl": "en",
            "_reqid": random.randint(10000, 99999),
            "rt": "c",
        }
        if session["sid"]:
            params["f.sid"] = session["sid"]
        text = ""
        async with self.client() as client, client.stream(
            "POST", GEMINI_WEB_URL, headers=headers, params=params, data=body, timeout=timeout
        ) as response:
            if response.status_code >= 400:
                status = response.status_code
                raise ProviderError(
                    "رفض Gemini Web الطلب (HTTP "
                    + str(status)
                    + ")"
                    + ("؛ الخدمة مشغولة مؤقتًا، أعد المحاولة بعد لحظات." if status in (429, 500, 502, 503) else "؛ تحقق من بيانات الحساب."),
                    status if status in (429, 503) else 502,
                )
            buf_len = 0
            try:
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("["):
                        continue
                    # أخطاء Google الداخلية (مثل BardErrorInfo 1097) تصل في
                    # إطار لا يحمل نص JSON قابلًا للتفسير، فتُفحص هنا مباشرة
                    # لتفادي «إجابة فارغة» صامتة.
                    if "BardErrorInfo" in line:
                        code = re.search(r'BardErrorInfo",\s*\[(\d+)', line)
                        raise ProviderError(
                            "أبلغ Gemini Web عن خطأ داخلي"
                            + (f" (رمز {code.group(1)})." if code else ".")
                        )
                    try:
                        frames = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(frames, list):
                        continue
                    for frame in frames:
                        if not isinstance(frame, list) or len(frame) < 3:
                            continue
                        if frame[0] == "er":
                            code = frame[5] if len(frame) > 5 and isinstance(frame[5], int) else ""
                            raise ProviderError(
                                "أبلغ Gemini Web عن خطأ في التوليد"
                                + (f" (رمز {code})." if code != "" else ".")
                            )
                        if not isinstance(frame[2], str):
                            continue
                        try:
                            payload = json.loads(frame[2])
                        except ValueError:
                            continue
                        if nested(payload, 1, 0):
                            state["conversation_id"] = payload[1][0]
                        if nested(payload, 1, 1):
                            state["response_id"] = payload[1][1]
                        if nested(payload, 4, 0, 0):
                            state["choice_id"] = payload[4][0][0]
                        value = nested(payload, 4, 0, 1, 0)
                        if isinstance(value, str) and value:
                            # الإطارات تراكمية؛ انشر الزيادة فقط إذا التزمت
                            # بالبادئة المنشورة حتى لا يظهر نص مشوّه للعميل.
                            if text and not value.startswith(text):
                                continue
                            text = value
                            if len(text) > buf_len:
                                await snapshot.update(text)
                                buf_len = len(text)
            except httpx.HTTPError:
                raise ProviderError(
                    "انقطع الاتصال بـ Gemini Web؛ لم نعد إرسال الرسالة تلقائيًا."
                ) from None
        return text

    async def gemini_web_send(self, account, prompt, state, settings):
        model_x = GEMINI_WEB_MODELS[0][2]
        if settings.get("model"):
            selected = next(
                (m for m in GEMINI_WEB_MODELS if m[0] == settings["model"]), None
            )
            if not selected:
                raise ProviderError(
                    "النموذج المحدد غير متاح في بروتوكول Gemini Web.", 400
                )
            model_x = selected[2]
        # مهلة أطول للبحث العميق وقد يستغرق دقائق.
        timeout = httpx.Timeout(300, connect=30)
        continuing = bool(state.get("conversation_id"))
        session = await self.gemini_web_session(account)
        # Google يرفض استمرار المحادثة بجلسة مختلفة عن التي أنشأتها
        # (خطأ داخلي 1097)، فالجلسة المرتبطة بالمحادثة (توكن وكوكيز
        # إنشائها) تُحفظ مع الحالة وتُعاد استخدامها في كل دورة.
        bound = state.get("_gemini_session")
        if (
            continuing
            and isinstance(bound, dict)
            and bound.get("cookies")
        ):
            session = {
                "at": bound.get("at") or session["at"],
                "sid": bound.get("sid") or session["sid"],
                "cookies": bound["cookies"],
                "expires": 0,
            }
        snapshot = TextSnapshot()
        try:
            text = await self._gemini_web_stream_once(
                account, prompt, state, settings, model_x, session, snapshot, timeout
            )
        except ProviderError:
            # فشل قبل وصول أي نص للعميل: لا إعادة إذا سبق بث نص حتى لا
            # يتكرر النص للعميل.
            if snapshot.published != "":
                raise
            if continuing:
                # جرّب الجلسة الحالية للحساب مرة واحدة؛ المحادثات القديمة
                # المحفوظة قبل إضافة ربط الجلسة لا تحمل جلسة أصلية.
                session = await self.gemini_web_session(account, refresh=True)
                try:
                    text = await self._gemini_web_stream_once(
                        account,
                        prompt,
                        state,
                        settings,
                        model_x,
                        session,
                        TextSnapshot(),
                        timeout,
                    )
                except ProviderError as exc:
                    raise ProviderError(
                        "تعذّر استمرار محادثة Gemini Web: "
                        + exc.message
                        + " الجلسة التي أنشأت المحادثة لم تعد صالحة لدى Google؛ ابدأ محادثة جديدة."
                    ) from None
            else:
                # محادثة جديدة: حدّث الجلسة (توكن وكوكيز جديدان) وأعد مرة
                # واحدة فقط عند رفض مؤقت من Google.
                session = await self.gemini_web_session(account, refresh=True)
                text = await self._gemini_web_stream_once(
                    account,
                    prompt,
                    state,
                    settings,
                    model_x,
                    session,
                    TextSnapshot(),
                    timeout,
                )
        if not text.strip():
            raise ProviderError("أعاد Gemini Web إجابة فارغة؛ أعد المحاولة بعد لحظات.")
        # احفظ الجلسة التي أنشأت/أكملت المحادثة مع الحالة لتستمر الدورات
        # القادمة على الجلسة نفسها.
        state["_gemini_session"] = {
            "at": session["at"],
            "sid": session["sid"],
            "cookies": session["cookies"],
        }
        return text

    # ------------------------------------------------------------ DeepAI
    async def deepai_send(self, account, prompt, state, settings):
        model_id = settings.get("model") or DEEPAI_MODELS[0][0]
        info = next((m for m in DEEPAI_MODELS if m[0] == model_id), None)
        if settings.get("model") and info is None:
            raise ProviderError("النموذج المحدد غير متاح لدى DeepAI.", 400)
        thinking_supported = bool(info[2]) if info else False
        thinking = thinking_supported and bool(settings.get("thinking_enabled"))
        if not state.get("session_uuid"):
            state["session_uuid"] = str(uuid.uuid4())
        # نفس ريكوست شات الموقع بالظبط (FormData) كما في AI.py؛ السياق
        # يُرسل داخل chatHistory لأن الخدمة بلا حالة بين الطلبات.
        history = list(state.get("deepai_history", []))
        history.append({"role": "user", "content": prompt})
        data = {
            "model": model_id,
            "chat_style": "chat",
            "language": "en",
            "chatHistory": json.dumps(history[-20:], ensure_ascii=False),
            "session_uuid": state["session_uuid"],
            "sensitivity_request_id": str(uuid.uuid4()),
            "tool_activity_support": "1",
            "thinking_image_tool_support": "1",
            "enabled_tools": '["image_generator","image_editor"]',
            "web_access_enabled": "true" if settings.get("search_enabled") else "false",
            "sandbox_enabled": "false",
            "memory_enabled": "false",
            "hacker_is_stinky": "very_stinky",
        }
        if thinking:
            data["thinking_support"] = "1"
        headers = {"User-Agent": DEEPAI_UA}
        credential = account["credential"]
        if not _is_guest_placeholder(credential):
            headers["api-key"] = credential
        # بث حقيقي: استجابة DeepAI نص متدفق chunked ينمو لحظيًا؛ نقرأه
        # بنمو ونبثه عبر TextSnapshot بدل انتظار اكتمال الطلب. مهلة أطول
        # (300 ثانية) حتى تكتمل الردود الطويلة التي كانت تُقطع عند 180.
        snapshot = TextSnapshot()
        timeout = httpx.Timeout(300, connect=30)
        body = ""
        status = 0
        async with self.client() as client:
            # البوت المرجعي يقرأ نص استجابة أخطاء HTTP لكشف PAID/QUOTA؛
            # لا نستخدم checked هنا حتى لا يُرفع خطأ عام قبل فحص النص.
            try:
                async with client.stream(
                    "POST", DEEPAI_CHAT_URL, data=data, headers=headers, timeout=timeout
                ) as response:
                    status = response.status_code
                    if status >= 400:
                        body = (await response.aread()).decode("utf-8", "ignore")
                    else:
                        seen = ""
                        published = 0
                        async for chunk in response.aiter_text():
                            seen += chunk
                            # كشف أخطاء الحصة/المدفوع من أول وصول قبل
                            # بث أي شيء للعميل، كما يفحص البوت المرجعي
                            # النص الكامل.
                            if any(mark in seen for mark in DEEPAI_PAID_MARKS):
                                raise ProviderError(
                                    "هذا النموذج مدفوع لدى DeepAI (Genius) ويحتاج مفتاح Pro في بيانات الحساب.",
                                    402,
                                )
                            if any(mark in seen for mark in DEEPAI_QUOTA_MARKS):
                                raise ProviderError(
                                    "انتهت الحصة المجانية المؤقتة لدى DeepAI؛ أعد المحاولة لاحقًا أو أضف مفتاح Pro.",
                                    429,
                                )
                            if len(seen) > published:
                                await snapshot.update(seen)
                                published = len(seen)
                        body = seen
            except httpx.HTTPError:
                raise ProviderError(
                    "انقطع الاتصال بـ DeepAI؛ لم نعد إرسال الرسالة تلقائيًا."
                ) from None
        if any(mark in body for mark in DEEPAI_PAID_MARKS):
            raise ProviderError(
                "هذا النموذج مدفوع لدى DeepAI (Genius) ويحتاج مفتاح Pro في بيانات الحساب.",
                402,
            )
        if any(mark in body for mark in DEEPAI_QUOTA_MARKS):
            raise ProviderError(
                "انتهت الحصة المجانية المؤقتة لدى DeepAI؛ أعد المحاولة لاحقًا أو أضف مفتاح Pro.",
                429,
            )
        if status >= 400:
            raise ProviderError(
                f"رفض DeepAI الطلب (HTTP {status}).",
                429 if status == 429 else 502,
            )
        if not body.strip():
            raise ProviderError("أعاد DeepAI إجابة فارغة.")
        history.append({"role": "assistant", "content": body})
        state["deepai_history"] = history[-20:]
        state["conversation_id"] = state["session_uuid"]
        return body

    async def deepai_image(self, account, prompt):
        credential = account["credential"]
        if _is_guest_placeholder(credential):
            raise ProviderError(
                "توليد صور DeepAI يحتاج مفتاح DeepAI Pro في بيانات الحساب.", 400
            )
        headers = {"User-Agent": DEEPAI_UA, "api-key": credential}
        async with self.client() as client:
            response = await self.checked(
                client,
                "POST",
                DEEPAI_IMAGE_URL,
                data={"text": prompt},
                headers=headers,
            )
        try:
            payload = response.json()
        except ValueError:
            raise ProviderError("لم يعد DeepAI رابط صورة صالحًا.") from None
        url = payload.get("output_url") if isinstance(payload, dict) else None
        if not url:
            raise ProviderError("لم يعد DeepAI رابط صورة صالحًا.")
        return url

    # ------------------------------------------------------------ GigaChat
    def giga_base(self, session):
        return (
            GIGA_BASE + "/api/giga-back-web"
            if session["authed"]
            else GIGA_BASE + "/api/smartproxy/api/prelogin"
        )

    def giga_headers(self, session, stream=False):
        headers = {
            "User-Agent": GIGA_UA,
            "Accept": "text/event-stream, application/json"
            if stream
            else "application/json",
            "Content-Type": "application/json",
            "X-Application-Name": GIGA_APP,
            "X-Application-Version": GIGA_VERSION,
            "X-Request-Id": str(uuid.uuid4()),
            "X-User-Timezone": GIGA_TIMEZONE,
        }
        if not session["authed"]:
            headers["x-device-id"] = session["device_id"]
            headers["x-sm-user-id"] = session["sd_user_id"] or session["device_id"]
            if session["sd_user_id"]:
                headers["x-project-id"] = session["sd_user_id"]
        return headers

    def giga_cookie_header(self, session):
        parts = []
        if session["authed"] and session.get("sm_sess"):
            parts.append("_sm_sess=" + session["sm_sess"])
        for k, v in session["cookies"].items():
            if k == "_sm_sess":
                continue
            parts.append(f"{k}={v}")
        return "; ".join(parts)

    def giga_absorb_cookies(self, session, response):
        for raw in response.headers.get_list("set-cookie"):
            kv = raw.split(";", 1)[0]
            if "=" in kv:
                k, v = kv.split("=", 1)
                session["cookies"][k.strip()] = v.strip()
                if k.strip() == "_sd_user_id":
                    session["sd_user_id"] = v.strip()

    async def giga_guest_login(self, session):
        headers = self.giga_headers(session)
        headers["X-Auth-Session-Id"] = derive_auth_session_id(session["device_id"])
        headers["X-Prelogin-User-Id"] = session["device_id"]
        cookie = self.giga_cookie_header(session)
        if cookie:
            headers["Cookie"] = cookie
        async with self.client() as client:
            response = await self.checked(client, "POST", GIGA_LOGIN_URL, headers=headers)
        self.giga_absorb_cookies(session, response)
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if payload.get("status") != "ok":
            raise ProviderError("فشل تسجيل دخول الضيف لدى GigaChat.")

    async def giga_ensure(self, account):
        session = self.giga_sessions.get(account["id"])
        if session:
            return session
        credential = account["credential"]
        authed = not _is_guest_placeholder(credential)
        session = {
            "device_id": str(uuid.uuid4()),
            "cookies": {},
            "sd_user_id": "",
            "authed": authed,
            "sm_sess": credential if authed else "",
        }
        if not authed:
            await self.giga_guest_login(session)
        if len(self.giga_sessions) >= 128:
            self.giga_sessions.pop(next(iter(self.giga_sessions)))
        self.giga_sessions[account["id"]] = session
        return session

    async def giga_send(self, account, prompt, state, settings):
        mode = settings.get("model") or GIGA_MODELS[0][0]
        if mode not in GIGA_AGENTS:
            raise ProviderError("وضع GigaChat المحدد غير معروف.", 400)
        session = await self.giga_ensure(account)
        agent = GIGA_AGENTS[mode]["authed" if session["authed"] else "guest"]
        body = {"text": prompt, "agent": agent}
        if mode == "reasoning":
            body["featureFlags"] = ["REASONING"]
        sid = state.get("giga_session") or ""
        if sid:
            url = f"{self.giga_base(session)}/api/v0/sessions/{sid}/request"
        else:
            url = f"{self.giga_base(session)}/api/v0/sessions/request"
        headers = self.giga_headers(session, stream=True)
        cookie = self.giga_cookie_header(session)
        if cookie:
            headers["Cookie"] = cookie
        timeout = httpx.Timeout(300, connect=30) if mode == "deep-research" else httpx.Timeout(120, connect=30)
        answer, logs = "", []
        snapshot = TextSnapshot()
        sid_out = sid or None
        async with self.client() as client:
            async with client.stream(
                "POST", url, json=body, headers=headers, timeout=timeout
            ) as response:
                if response.status_code >= 400:
                    raw = (await response.aread()).decode("utf-8", "ignore")
                    raise ProviderError(
                        f"رفض GigaChat الطلب (HTTP {response.status_code}). "
                        + raw[:200]
                    )
                buf = ""
                async for line in response.aiter_lines():
                    if line.startswith(":"):
                        continue
                    if line.startswith("data:"):
                        buf += line[5:].strip() + "\n"
                        continue
                    if line.strip() == "" and buf.strip():
                        try:
                            event = json.loads(buf)
                        except json.JSONDecodeError:
                            buf = ""
                            continue
                        buf = ""
                        sid_out = event.get("sessionId") or sid_out
                        status = event.get("status")
                        if status == "ERROR":
                            raise ProviderError(
                                "أبلغ GigaChat عن خطأ: "
                                + json.dumps(event, ensure_ascii=False)[:300]
                            )
                        for block in event.get("contentDelta", []) or []:
                            role = block.get("role")
                            txt = block.get("delta") or block.get("value") or ""
                            if role == "LOG":
                                logs.append(txt)
                            elif role in ("ASSISTANT", "AI"):
                                answer += txt
                                # بث مباشر للنص أثناء وصوله (تدفق SSE).
                                await snapshot.update(answer)
                        if status == "READY":
                            message = event.get("message") or {}
                            if not answer:
                                for block in message.get("content", []) or []:
                                    if block.get("role") in ("ASSISTANT", "AI"):
                                        answer += block.get("value") or ""
                            break
        if not answer.strip():
            if logs:
                answer = "\n".join("- " + x for x in logs[-20:])
                await snapshot.update(answer)
                if sid_out:
                    state["giga_session"] = sid_out
                    state["conversation_id"] = sid_out
                return answer
            raise ProviderError("أعاد GigaChat إجابة فارغة.")
        if sid_out:
            state["giga_session"] = sid_out
            state["conversation_id"] = sid_out
        return answer

    # ------------------------------------------------------------ التوجيه
    async def send(self, account, prompt, state, settings, attachments=None):
        if attachments:
            raise ProviderError(
                "بروتوكولات الضيف (Gemini Web وDeepAI وGigaChat) لا تدعم المرفقات.", 400
            )
        provider = account["provider"]
        if provider == "gemini-web":
            return await self.gemini_web_send(account, prompt, state, settings)
        if provider == "deepai":
            return await self.deepai_send(account, prompt, state, settings)
        return await self.giga_send(account, prompt, state, settings)

    async def image(self, account, prompt, size):
        provider = account["provider"]
        if provider == "deepai":
            return await self.deepai_image(account, prompt)
        raise ProviderError("هذا المزوّد لا يدعم توليد الصور.", 400)
