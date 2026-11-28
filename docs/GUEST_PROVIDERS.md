# مزوّدو الضيف المضافون: Gemini Web وDeepAI وGigaChat

إضافة منفصلة تمامًا عن بروتوكولات الحسابات الأصلية (ChatGPT وGemini وDeepSeek Telegram وQwen)؛ لم يُعدّل أي سلوك قائم. البروتوكولات منقولة بحرفية من ملفّي العميل المرفقين: «ضيف gemini.txt» و«AI.py»، ويُنفّذها `proxy/guest_providers.py`.

## Gemini Web (`gemini-web`)

وصول Gemini عبر واجهة الويب **بدون كوكيز ودون تسجيل دخول**.

- يجلب البروكسي توكن الإجراء من صفحة `gemini.google.com` (المفتاح `uS02ke` مع البدائل `SNlM0e` و`EOzIkf` و`zChJod` و`UUFaWc` و`hsFLT` و`u4g7r`) ومعرّف الجلسة من `FdrFJe`، تمامًا كما في الملف المرجعي.
- الطلب يُرسل إلى `assistant.lamda.BardFrontendService/StreamGenerate` مع ترويسة النموذج `x-goog-ext-525001261-jspb`.
- النماذج الثابتة: `gemini-3.5-flash` و`gemini-deep-research` بقيم الترويسة الأصلية نفسها.
- بيانات الحساب اختيارية: اتركها فارغة لجلسة ضيف، أو الصق كوكيز لتُضمَّن إلى الطلب.
- السياق (استمرار المحادثة) يُحفظ محليًا في البروكسي عبر معرفات `conversation_id` و`response_id` و`choice_id`؛ قوائم محادثات الحساب غير متاحة في هذا البروتوكول.

## DeepAI (`deepai`)

- الطلب بنفس حقول الـFormData الأصلية: `model` و`chat_style=chat` و`language=en` و`chatHistory` و`session_uuid` و`sensitivity_request_id` و`tool_activity_support` و`thinking_image_tool_support` و`enabled_tools` و`web_access_enabled` و`sandbox_enabled` و`memory_enabled` و`hacker_is_stinky`، وعلامة `thinking_support` عند تفعيل التفكير لنموذج يدعمه.
- يعمل **بدون مفتاح** بحصة مجانية محدودة. لصق مفتاح DeepAI Pro في بيانات الحساب يرسله بترويسة `api-key` ويفعّل توليد الصور عبر `POST /v1/images/generations` على مسار حساب DeepAI (بحجم `1:1` الافتراضي فقط).
- أخطاء الخدمة تُترجم كما في البوت: ردود Genius المدفوعة (402) والحصة المنتهية (429).
- سجل المحادثة (آخر 20 رسالة) يُرسل داخل `chatHistory` مع كل طلب لأن الخدمة بلا حالة بين الطلبات؛ مفتاح `session_uuid` ثابت لكل محادثة.
- النماذج: `glm-5.3-flash` (تفكير) و`standard` و`claude-haiku-5-5` و`qwen3.8-flash` و`deepseek-v4.1-flash` و`gpt-6-luna` و`tencent-hy3` و`gemma-4` و`llama-3.3-70b-instruct` و`llama-3.1-8b-instant`.

## GigaChat (`giga`)

- وضع **الضيف تلقائيًا**: دخول prelogin إلى `giga.chat` مع `X-Auth-Session-Id` المحسوب بمعادلة `6819.js module 90560` الأصلية و`X-Prelogin-User-Id`، وترويسات `X-Application-Name: gigachat-b2c-web-neo` و`X-Application-Version: 0.15.13` و`X-User-Timezone: Africa/Cairo` كما في المصدر.
- الوضع الموثّق: الصق قيمة كوكي `_sm_sess` في بيانات الحساب فيُستخدم أساس `api/giga-back-web` ومعرّفات الوكلاء الموثّقين.
- الأوضاع (تظهر كنماذج): `reasoning` (تفكير عميق مع `featureFlags: ["REASONING"]`) و`giga` و`deep-research` (مهلة 300 ثانية) و`education`، بمعرّفات الوكلاء الأصلية للضيف والموثّق.
- استجابة SSE تُقرأ كما في المصدر: `contentDelta` بأدوار `ASSISTANT/AI` و`LOG`، و`sessionId` يثبت محادثة البروكسي، و`status: ERROR` يرفع خطأ.
- مهلة الطلب 120 ثانية (300 للبحث العميق) كما في البوت، ولا يُعاد أي إرسال تلقائي.

## حدوس مشتركة

- كل الحسابات الثلاثة تعمل بدون بيانات دخول؛ تُولَّد بصمة فريدة لكل حساب عند ترك الحقل فارغًا حتى لا تُدمج الحسابات.
- المرفقات غير مدعومة في هذه البروتوكولات، والأدوات محاكاة كإخوة البروتوكولات.
- مدققات TLS مفعّلة دائمًا (المصدر المرجعي كان يعطّلها لـGemini Web فقط).
- روتات مزوّدو الضيف تُنشأ تلقائيًا عند الربط: `gemini-web/<نموذج>` و`deepai/<نموذج>` و`giga/<وضع>`.

## الاختبارات

`tests/test_guest_providers.py` يغطي شكل الطلبات الفعلي (الترويسات والحقول والمسارات) واستمرار السياق وأخطاء الخدمة وربط التسجيل والربط والتوليد الكامل عبر التطبيق، دون أي اتصال شبكي حقيقي.
