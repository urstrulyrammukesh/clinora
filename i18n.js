/* Clinora AI - website translations.
   Each entry: English text exactly as on the page -> translations.
   Missing translations fall back to English. Languages without hand-written entries here are translated by the AI (server.py) and saved in data/i18n/. */
/* Built-in, hand-written translations (instant, no AI needed) */
const BUILTIN = new Set(['en', 'hi', 'es', 'fr', 'ar', 'pt', 'de', 'zh', 'ru']);

/* 100+ languages: code -> [native name, English name, flags]. Flags: r = right-to-left, n = script that must not be letter-spaced.
   Languages that are not BUILTIN are translated by the AI the first time someone picks them, then saved on the server. */
const LANG_LIST = {
  af:['Afrikaans','Afrikaans'], ak:['Akan','Twi'], sq:['Shqip','Albanian'], am:['አማርኛ','Amharic','n'], ar:['العربية','Arabic','rn'],
  hy:['Հայերեն','Armenian','n'], as:['অসমীয়া','Assamese','n'], ay:['Aymar aru','Aymara'], az:['Azərbaycan','Azerbaijani'], bm:['Bamanankan','Bambara'],
  eu:['Euskara','Basque'], be:['Беларуская','Belarusian'], bn:['বাংলা','Bengali','n'], bho:['भोजपुरी','Bhojpuri','n'], bs:['Bosanski','Bosnian'],
  bg:['Български','Bulgarian'], my:['မြန်မာ','Burmese','n'], ca:['Català','Catalan'], ceb:['Cebuano','Cebuano'], ny:['Chichewa','Chichewa'],
  zh:['中文 (简体)','Chinese (Simplified)','n'], 'zh-TW':['中文 (繁體)','Chinese (Traditional)','n'], co:['Corsu','Corsican'], hr:['Hrvatski','Croatian'],
  cs:['Čeština','Czech'], da:['Dansk','Danish'], dv:['ދިވެހި','Dhivehi','rn'], nl:['Nederlands','Dutch'], dz:['རྫོང་ཁ','Dzongkha','n'],
  en:['English','English'], eo:['Esperanto','Esperanto'], et:['Eesti','Estonian'], ee:['Eʋegbe','Ewe'], fil:['Filipino','Filipino'],
  fi:['Suomi','Finnish'], fr:['Français','French'], fy:['Frysk','Frisian'], ff:['Fulfulde','Fula'], gl:['Galego','Galician'],
  ka:['ქართული','Georgian','n'], de:['Deutsch','German'], el:['Ελληνικά','Greek'], gn:["Avañe'ẽ",'Guarani'], gu:['ગુજરાતી','Gujarati','n'],
  ht:['Kreyòl ayisyen','Haitian Creole'], ha:['Hausa','Hausa'], haw:['ʻŌlelo Hawaiʻi','Hawaiian'], he:['עברית','Hebrew','rn'], hi:['हिन्दी','Hindi','n'],
  hmn:['Hmoob','Hmong'], hu:['Magyar','Hungarian'], is:['Íslenska','Icelandic'], ig:['Igbo','Igbo'], ilo:['Ilokano','Ilocano'],
  id:['Bahasa Indonesia','Indonesian'], ga:['Gaeilge','Irish'], it:['Italiano','Italian'], ja:['日本語','Japanese','n'], jv:['Basa Jawa','Javanese'],
  kn:['ಕನ್ನಡ','Kannada','n'], kk:['Қазақ тілі','Kazakh'], km:['ខ្មែរ','Khmer','n'], rw:['Kinyarwanda','Kinyarwanda'], kok:['कोंकणी','Konkani','n'],
  ko:['한국어','Korean','n'], kri:['Krio','Krio'], ku:['Kurdî','Kurdish (Kurmanji)'], ckb:['کوردی','Kurdish (Sorani)','rn'], ky:['Кыргызча','Kyrgyz'],
  lo:['ລາວ','Lao','n'], la:['Latina','Latin'], lv:['Latviešu','Latvian'], ln:['Lingála','Lingala'], lt:['Lietuvių','Lithuanian'],
  lg:['Luganda','Luganda'], lb:['Lëtzebuergesch','Luxembourgish'], mk:['Македонски','Macedonian'], mai:['मैथिली','Maithili','n'], mg:['Malagasy','Malagasy'],
  ms:['Bahasa Melayu','Malay'], ml:['മലയാളം','Malayalam','n'], mt:['Malti','Maltese'], mi:['Māori','Maori'], mr:['मराठी','Marathi','n'],
  'mni-Mtei':['ꯃꯤꯇꯩꯂꯣꯟ','Meitei (Manipuri)','n'], lus:['Mizo ṭawng','Mizo'], mn:['Монгол','Mongolian'], ne:['नेपाली','Nepali','n'], nso:['Sepedi','Northern Sotho'],
  no:['Norsk','Norwegian'], or:['ଓଡ଼ିଆ','Odia','n'], om:['Afaan Oromoo','Oromo'], ps:['پښتو','Pashto','rn'], fa:['فارسی','Persian','rn'],
  pl:['Polski','Polish'], pt:['Português','Portuguese'], pa:['ਪੰਜਾਬੀ','Punjabi','n'], qu:['Runa Simi','Quechua'], ro:['Română','Romanian'],
  ru:['Русский','Russian'], sm:['Gagana Samoa','Samoan'], sa:['संस्कृतम्','Sanskrit','n'], gd:['Gàidhlig','Scottish Gaelic'], sr:['Српски','Serbian'],
  st:['Sesotho','Sesotho'], tn:['Setswana','Setswana'], sn:['chiShona','Shona'], sd:['سنڌي','Sindhi','rn'], si:['සිංහල','Sinhala','n'],
  sk:['Slovenčina','Slovak'], sl:['Slovenščina','Slovenian'], so:['Soomaali','Somali'], es:['Español','Spanish'], su:['Basa Sunda','Sundanese'],
  sw:['Kiswahili','Swahili'], sv:['Svenska','Swedish'], tg:['Тоҷикӣ','Tajik'], ta:['தமிழ்','Tamil','n'], tt:['Татарча','Tatar'],
  te:['తెలుగు','Telugu','n'], th:['ไทย','Thai','n'], bo:['བོད་ཡིག','Tibetan','n'], ti:['ትግርኛ','Tigrinya','n'], ts:['Xitsonga','Tsonga'],
  tr:['Türkçe','Turkish'], tk:['Türkmençe','Turkmen'], uk:['Українська','Ukrainian'], ur:['اردو','Urdu','rn'], ug:['ئۇيغۇرچە','Uyghur','rn'],
  uz:['Oʻzbekcha','Uzbek'], vi:['Tiếng Việt','Vietnamese'], cy:['Cymraeg','Welsh'], wo:['Wolof','Wolof'], xh:['isiXhosa','Xhosa'],
  yi:['ייִדיש','Yiddish','rn'], yo:['Yorùbá','Yoruba'], zu:['isiZulu','Zulu'], fj:['Vosa Vakaviti','Fijian'], to:['Lea faka-Tonga','Tongan']
};
const LANGS = Object.fromEntries(Object.entries(LANG_LIST).map(([c, v]) => [c, v[0]]));
const RTL = new Set(Object.keys(LANG_LIST).filter(c => (LANG_LIST[c][2] || '').includes('r')));
const NONLATIN = new Set(Object.keys(LANG_LIST).filter(c => (LANG_LIST[c][2] || '').includes('n')));

/* Main language for each country */
const CC_LANG = (() => {
  const m = {IN:'hi', CN:'zh', TW:'zh-TW', HK:'zh-TW', MO:'zh-TW', SG:'en', RU:'ru', BY:'be', KZ:'kk', KG:'ky', UZ:'uz', TJ:'tg', TM:'tk', MN:'mn',
    DE:'de', AT:'de', LI:'de', CH:'de', LU:'lb', FR:'fr', MC:'fr', SN:'fr', CI:'fr', ML:'fr', BF:'fr', NE:'fr', GN:'fr', BJ:'fr', TG:'fr', CD:'fr', CG:'fr', GA:'fr', CM:'fr', HT:'ht',
    BR:'pt', PT:'pt', AO:'pt', MZ:'pt', CV:'pt', GW:'pt', ST:'pt', TL:'pt',
    BD:'bn', PK:'ur', AF:'ps', IR:'fa', IL:'he', TR:'tr', AZ:'az', GE:'ka', AM:'hy', ID:'id', MY:'ms', BN:'ms', VN:'vi', TH:'th', LA:'lo', KH:'km', MM:'my',
    JP:'ja', KR:'ko', KP:'ko', LK:'si', NP:'ne', BT:'dz', MV:'dv', PH:'fil', UA:'uk', PL:'pl', NL:'nl', BE:'nl', IT:'it', SM:'it', GR:'el', CY:'el',
    RO:'ro', MD:'ro', HU:'hu', CZ:'cs', SK:'sk', SE:'sv', NO:'no', DK:'da', FI:'fi', IS:'is', EE:'et', LV:'lv', LT:'lt', HR:'hr', RS:'sr', ME:'sr',
    BA:'bs', SI:'sl', BG:'bg', MK:'mk', AL:'sq', XK:'sq', MT:'mt', IE:'en', ET:'am', ER:'ti', SO:'so', KE:'sw', TZ:'sw', RW:'rw', MG:'mg', LS:'st', BW:'tn',
    MW:'ny', ZW:'sn', SS:'en', BI:'fr', DJ:'fr', KM:'fr', TD:'fr', CF:'fr', WS:'sm', TO:'to', FJ:'en', NZ:'en', PY:'es', PE:'es', BO:'es'};
  'ES MX AR CO CL VE EC GT CU DO HN SV NI CR PA UY PR GQ'.split(' ').forEach(c => m[c] = 'es');
  'SA AE EG QA KW BH OM JO LB IQ SY YE LY SD MA DZ TN PS MR'.split(' ').forEach(c => m[c] = 'ar');
  return m;
})();

const T = {
 /* ---- language suggestion toast (shown in the suggested language) ---- */
 "__ask": {hi:"यह वेबसाइट हिन्दी में देखें?", es:"¿Ver este sitio en español?", fr:"Voir ce site en français ?", ar:"هل تريد عرض الموقع بالعربية؟", pt:"Ver este site em português?", de:"Diese Website auf Deutsch anzeigen?", zh:"用中文浏览本网站？", ru:"Открыть сайт на русском?"},
 "__yes": {hi:"हाँ, बदलें", es:"Sí, cambiar", fr:"Oui", ar:"نعم", pt:"Sim, mudar", de:"Ja, wechseln", zh:"切换", ru:"Да"},
 "__greet": {en:"Hello! 🙏 I'm the AI receptionist for <b>Clinora Medical Center</b>.\nAsk me anything: appointments, video consultations, fees, or doctors and hospitals anywhere in the world.",
   hi:"नमस्ते! 🙏 मैं <b>Clinora Medical Center</b> की AI रिसेप्शनिस्ट हूँ।\nअपॉइंटमेंट, वीडियो कंसल्टेशन, फीस, या दुनिया में कहीं भी डॉक्टर और अस्पताल के बारे में पूछें।",
   es:"¡Hola! 🙏 Soy la recepcionista con IA de <b>Clinora Medical Center</b>.\nPregúntame lo que quieras: citas, videoconsultas, tarifas o médicos y hospitales en cualquier parte del mundo.",
   fr:"Bonjour ! 🙏 Je suis l'accueil IA de <b>Clinora Medical Center</b>.\nDemandez-moi ce que vous voulez : rendez-vous, téléconsultations, tarifs, ou médecins et hôpitaux partout dans le monde.",
   ar:"مرحباً! 🙏 أنا موظفة الاستقبال الذكية في <b>Clinora Medical Center</b>.\nاسألني عن المواعيد، أو الاستشارات بالفيديو، أو الأسعار، أو الأطباء والمستشفيات في أي مكان في العالم.",
   pt:"Olá! 🙏 Sou a recepcionista com IA do <b>Clinora Medical Center</b>.\nPergunte o que quiser: consultas, teleconsultas, valores, ou médicos e hospitais em qualquer lugar do mundo.",
   de:"Hallo! 🙏 Ich bin die KI-Rezeption des <b>Clinora Medical Center</b>.\nFragen Sie mich alles: Termine, Videosprechstunden, Preise oder Ärzte und Kliniken überall auf der Welt.",
   zh:"您好！🙏 我是 <b>Clinora Medical Center</b> 的 AI 前台。\n可以问我任何问题：预约、视频问诊、费用，或全球任何地方的医生和医院。",
   ru:"Здравствуйте! 🙏 Я ИИ-администратор <b>Clinora Medical Center</b>.\nСпрашивайте о чём угодно: запись, видеоконсультации, цены, врачи и больницы в любой точке мира."},

 /* ---- navigation ---- */
 "Home": {hi:"होम", es:"Inicio", fr:"Accueil", ar:"الرئيسية", pt:"Início", de:"Start", zh:"首页", ru:"Главная"},
 "Ask AI": {hi:"AI से पूछें", es:"Preguntar a la IA", fr:"Demander à l'IA", ar:"اسأل الذكاء الاصطناعي", pt:"Perguntar à IA", de:"KI fragen", zh:"问 AI", ru:"Спросить ИИ"},
 "💬 Ask AI": {hi:"💬 AI से पूछें", es:"💬 Preguntar", fr:"💬 Demander", ar:"💬 اسأل", pt:"💬 Perguntar", de:"💬 KI fragen", zh:"💬 问 AI", ru:"💬 Спросить"},
 "Nearby Doctors": {hi:"पास के डॉक्टर", es:"Médicos cercanos", fr:"Médecins à proximité", ar:"أطباء قريبون", pt:"Médicos próximos", de:"Ärzte in der Nähe", zh:"附近医生", ru:"Врачи рядом"},
 "Clinic Dashboard": {hi:"क्लिनिक डैशबोर्ड", es:"Panel de la clínica", fr:"Espace clinique", ar:"لوحة العيادة", pt:"Painel da clínica", de:"Praxis-Dashboard", zh:"诊所后台", ru:"Панель клиники"},
 "World Directory": {hi:"विश्व निर्देशिका", es:"Directorio mundial", fr:"Annuaire mondial", ar:"الدليل العالمي", pt:"Diretório mundial", de:"Weltverzeichnis", zh:"全球名录", ru:"Мировой каталог"},
 "CLINIC AI RECEPTIONIST": {hi:"क्लिनिक AI रिसेप्शनिस्ट", es:"RECEPCIÓN CON IA", fr:"ACCUEIL IA POUR CLINIQUES", ar:"استقبال ذكي للعيادات", pt:"RECEPÇÃO COM IA", de:"KI-PRAXISREZEPTION", zh:"诊所 AI 前台", ru:"ИИ-РЕГИСТРАТУРА"},

 /* ---- home ---- */
 "AI RECEPTIONIST FOR CLINICS WORLDWIDE": {hi:"दुनिया भर के क्लिनिकों के लिए AI रिसेप्शनिस्ट", es:"RECEPCIÓN CON IA PARA CLÍNICAS DE TODO EL MUNDO", fr:"ACCUEIL IA POUR LES CLINIQUES DU MONDE ENTIER", ar:"استقبال بالذكاء الاصطناعي للعيادات حول العالم", pt:"RECEPÇÃO COM IA PARA CLÍNICAS NO MUNDO TODO", de:"KI-REZEPTION FÜR PRAXEN WELTWEIT", zh:"面向全球诊所的 AI 前台", ru:"ИИ-РЕГИСТРАТУРА ДЛЯ КЛИНИК ПО ВСЕМУ МИРУ"},
 "💬 Talk to the live AI": {hi:"💬 AI से बात करें", es:"💬 Hablar con la IA", fr:"💬 Parler à l'IA", ar:"💬 تحدث مع الذكاء الاصطناعي", pt:"💬 Falar com a IA", de:"💬 Mit der KI sprechen", zh:"💬 与 AI 对话", ru:"💬 Поговорить с ИИ"},
 "📍 Nearby open doctors": {hi:"📍 पास के खुले डॉक्टर", es:"📍 Médicos abiertos cerca", fr:"📍 Médecins ouverts à proximité", ar:"📍 أطباء مفتوحون بالقرب منك", pt:"📍 Médicos abertos por perto", de:"📍 Geöffnete Ärzte in der Nähe", zh:"📍 附近营业中的医生", ru:"📍 Открытые врачи рядом"},
 "online · replies instantly": {hi:"ऑनलाइन · तुरंत जवाब", es:"en línea · responde al instante", fr:"en ligne · répond instantanément", ar:"متصل · يرد فوراً", pt:"online · responde na hora", de:"online · antwortet sofort", zh:"在线 · 即时回复", ru:"онлайн · отвечает сразу"},
 "NEVER MISS A CALL": {hi:"कोई कॉल न छूटे", es:"NUNCA PIERDAS UNA LLAMADA", fr:"PLUS AUCUN APPEL MANQUÉ", ar:"لا تفوّت أي اتصال", pt:"NUNCA PERCA UMA LIGAÇÃO", de:"KEIN ANRUF GEHT VERLOREN", zh:"不错过任何来电", ru:"НИ ОДНОГО ПРОПУЩЕННОГО ЗВОНКА"},
 "REPLY TIME": {hi:"जवाब का समय", es:"TIEMPO DE RESPUESTA", fr:"TEMPS DE RÉPONSE", ar:"وقت الرد", pt:"TEMPO DE RESPOSTA", de:"ANTWORTZEIT", zh:"响应时间", ru:"ВРЕМЯ ОТВЕТА"},
 "CHANNELS · WA · WEB · CALL": {hi:"चैनल · WA · वेब · कॉल", es:"CANALES · WA · WEB · LLAMADA", fr:"CANAUX · WA · WEB · APPEL", ar:"القنوات · واتساب · الويب · الاتصال", pt:"CANAIS · WA · WEB · LIGAÇÃO", de:"KANÄLE · WA · WEB · ANRUF", zh:"渠道 · WA · 网页 · 电话", ru:"КАНАЛЫ · WA · САЙТ · ЗВОНОК"},
 "🌍 ANY": {hi:"🌍 कोई भी", es:"🌍 CUALQUIER", fr:"🌍 TOUT", ar:"🌍 أي", pt:"🌍 QUALQUER", de:"🌍 JEDES", zh:"🌍 任何", ru:"🌍 ЛЮБАЯ"},
 "COUNTRY · TIME ZONE": {hi:"देश · टाइम ज़ोन", es:"PAÍS · ZONA HORARIA", fr:"PAYS · FUSEAU HORAIRE", ar:"دولة · منطقة زمنية", pt:"PAÍS · FUSO HORÁRIO", de:"LAND · ZEITZONE", zh:"国家 · 时区", ru:"СТРАНА · ЧАСОВОЙ ПОЯС"},
 "How it works": {hi:"यह कैसे काम करता है", es:"Cómo funciona", fr:"Comment ça marche", ar:"كيف يعمل", pt:"Como funciona", de:"So funktioniert's", zh:"工作原理", ru:"Как это работает"},
 "PATIENT MESSAGE → AI → BOOKING → REMINDER": {hi:"मरीज़ का संदेश → AI → बुकिंग → रिमाइंडर", es:"MENSAJE → IA → CITA → RECORDATORIO", fr:"MESSAGE → IA → RENDEZ-VOUS → RAPPEL", ar:"رسالة المريض ← الذكاء الاصطناعي ← الحجز ← التذكير", pt:"MENSAGEM → IA → AGENDAMENTO → LEMBRETE", de:"NACHRICHT → KI → TERMIN → ERINNERUNG", zh:"患者消息 → AI → 预约 → 提醒", ru:"СООБЩЕНИЕ → ИИ → ЗАПИСЬ → НАПОМИНАНИЕ"},
 "Patient message": {hi:"मरीज़ का संदेश", es:"Mensaje del paciente", fr:"Message du patient", ar:"رسالة المريض", pt:"Mensagem do paciente", de:"Nachricht des Patienten", zh:"患者发消息", ru:"Сообщение пациента"},
 "WhatsApp, website chat or a call: \"I need a dentist tomorrow\".": {hi:"WhatsApp, वेबसाइट चैट या कॉल: \"कल दांत दिखाना है\"।", es:"WhatsApp, chat web o llamada: \"Necesito un dentista mañana\".", fr:"WhatsApp, chat du site ou appel : « Il me faut un dentiste demain ».", ar:"واتساب أو دردشة الموقع أو اتصال: \"أحتاج طبيب أسنان غداً\".", pt:"WhatsApp, chat do site ou ligação: \"Preciso de um dentista amanhã\".", de:"WhatsApp, Website-Chat oder Anruf: „Ich brauche morgen einen Zahnarzt.“", zh:"WhatsApp、网站聊天或电话：“我明天要看牙医”。", ru:"WhatsApp, чат на сайте или звонок: «Мне нужен стоматолог завтра»."},
 "AI understands": {hi:"AI समझता है", es:"La IA entiende", fr:"L'IA comprend", ar:"الذكاء الاصطناعي يفهم", pt:"A IA entende", de:"Die KI versteht", zh:"AI 理解需求", ru:"ИИ понимает"},
 "Works out the doctor, day and time, and answers from the clinic's own information.": {hi:"डॉक्टर, दिन और समय समझता है, और क्लिनिक की अपनी जानकारी से जवाब देता है।", es:"Identifica el médico, el día y la hora, y responde con la información de la clínica.", fr:"Identifie le médecin, le jour et l'heure, et répond avec les informations de la clinique.", ar:"يحدد الطبيب واليوم والوقت، ويجيب من معلومات العيادة نفسها.", pt:"Identifica o médico, o dia e o horário e responde com as informações da clínica.", de:"Erkennt Arzt, Tag und Uhrzeit und antwortet mit den Informationen der Praxis.", zh:"识别医生、日期和时间，并根据诊所自己的信息回答。", ru:"Определяет врача, день и время и отвечает по данным самой клиники."},
 "Slot booked": {hi:"स्लॉट बुक", es:"Cita reservada", fr:"Créneau réservé", ar:"تم حجز الموعد", pt:"Horário reservado", de:"Termin gebucht", zh:"预约成功", ru:"Время забронировано"},
 "Shows free slots, takes name and number, confirms the booking.": {hi:"खाली स्लॉट दिखाता है, नाम और नंबर लेता है, बुकिंग पक्की करता है।", es:"Muestra horarios libres, toma nombre y teléfono y confirma la cita.", fr:"Propose les créneaux libres, prend le nom et le numéro, confirme le rendez-vous.", ar:"يعرض المواعيد المتاحة، ويأخذ الاسم والرقم، ويؤكد الحجز.", pt:"Mostra horários livres, pega nome e telefone e confirma o agendamento.", de:"Zeigt freie Zeiten, nimmt Name und Nummer auf, bestätigt den Termin.", zh:"显示空闲时段，记录姓名和电话，确认预约。", ru:"Показывает свободное время, записывает имя и номер, подтверждает запись."},
 "Reminder": {hi:"रिमाइंडर", es:"Recordatorio", fr:"Rappel", ar:"تذكير", pt:"Lembrete", de:"Erinnerung", zh:"提醒", ru:"Напоминание"},
 "A reminder one day before. Fewer no-shows, more revenue.": {hi:"एक दिन पहले रिमाइंडर। कम मरीज़ छूटते हैं, कमाई ज़्यादा।", es:"Un recordatorio el día antes. Menos ausencias, más ingresos.", fr:"Un rappel la veille. Moins d'absences, plus de revenus.", ar:"تذكير قبل يوم. غياب أقل ودخل أكثر.", pt:"Um lembrete no dia anterior. Menos faltas, mais receita.", de:"Eine Erinnerung am Vortag. Weniger Ausfälle, mehr Umsatz.", zh:"提前一天提醒。爽约更少，收入更多。", ru:"Напоминание за день. Меньше неявок, больше дохода."},
 "Features": {hi:"सुविधाएँ", es:"Funciones", fr:"Fonctionnalités", ar:"المزايا", pt:"Recursos", de:"Funktionen", zh:"功能", ru:"Возможности"},
 "PATIENT SIDE + CLINIC SIDE": {hi:"मरीज़ + क्लिनिक", es:"PACIENTES + CLÍNICA", fr:"PATIENTS + CLINIQUE", ar:"المرضى + العيادة", pt:"PACIENTES + CLÍNICA", de:"PATIENTEN + PRAXIS", zh:"患者端 + 诊所端", ru:"ПАЦИЕНТЫ + КЛИНИКА"},
 "👤 For patients": {hi:"👤 मरीज़ों के लिए", es:"👤 Para pacientes", fr:"👤 Pour les patients", ar:"👤 للمرضى", pt:"👤 Para pacientes", de:"👤 Für Patienten", zh:"👤 患者", ru:"👤 Для пациентов"},
 "Instant booking on WhatsApp or the website": {hi:"WhatsApp या वेबसाइट पर तुरंत बुकिंग", es:"Reserva al instante por WhatsApp o en la web", fr:"Réservation instantanée sur WhatsApp ou le site", ar:"حجز فوري عبر واتساب أو الموقع", pt:"Agendamento na hora pelo WhatsApp ou pelo site", de:"Sofort buchen per WhatsApp oder Website", zh:"通过 WhatsApp 或网站即时预约", ru:"Мгновенная запись в WhatsApp или на сайте"},
 "Answers about fees, timings and address": {hi:"फीस, समय और पते के जवाब", es:"Respuestas sobre tarifas, horarios y dirección", fr:"Réponses sur les tarifs, horaires et adresse", ar:"إجابات عن الأسعار والمواعيد والعنوان", pt:"Respostas sobre valores, horários e endereço", de:"Antworten zu Preisen, Zeiten und Adresse", zh:"解答费用、时间和地址问题", ru:"Ответы о ценах, часах работы и адресе"},
 "Self-service reschedule and cancel": {hi:"खुद से समय बदलें या रद्द करें", es:"Cambia o cancela tu cita tú mismo", fr:"Modifier ou annuler soi-même", ar:"تغيير الموعد أو إلغاؤه بنفسك", pt:"Remarque ou cancele sozinho", de:"Selbst verschieben oder absagen", zh:"自助改约和取消", ru:"Самостоятельный перенос и отмена"},
 "Nearby doctors: open or closed right now, on a 3D map": {hi:"पास के डॉक्टर: अभी खुले या बंद, 3D मैप पर", es:"Médicos cercanos: abiertos o cerrados ahora, en un mapa 3D", fr:"Médecins proches : ouverts ou fermés maintenant, sur une carte 3D", ar:"أطباء قريبون: مفتوح أو مغلق الآن، على خريطة ثلاثية الأبعاد", pt:"Médicos por perto: abertos ou fechados agora, em um mapa 3D", de:"Ärzte in der Nähe: jetzt geöffnet oder geschlossen, auf einer 3D-Karte", zh:"附近医生：当前是否营业，3D 地图展示", ru:"Врачи рядом: открыто или закрыто сейчас, на 3D-карте"},
 "🚨 Emergency detection → local emergency number + clinic alert": {hi:"🚨 इमरजेंसी पहचान → स्थानीय इमरजेंसी नंबर + क्लिनिक अलर्ट", es:"🚨 Detección de urgencias → número de emergencia local + aviso a la clínica", fr:"🚨 Détection d'urgence → numéro d'urgence local + alerte à la clinique", ar:"🚨 كشف الطوارئ ← رقم الطوارئ المحلي + تنبيه العيادة", pt:"🚨 Detecção de emergência → número de emergência local + alerta à clínica", de:"🚨 Notfallerkennung → lokale Notrufnummer + Alarm an die Praxis", zh:"🚨 识别紧急情况 → 当地急救电话 + 通知诊所", ru:"🚨 Распознавание экстренных случаев → местный номер экстренной помощи + сигнал клинике"},
 "📹 Video consultations from anywhere in the world": {hi:"📹 दुनिया में कहीं से भी वीडियो कंसल्टेशन", es:"📹 Videoconsultas desde cualquier lugar del mundo", fr:"📹 Téléconsultations depuis n'importe où dans le monde", ar:"📹 استشارات بالفيديو من أي مكان في العالم", pt:"📹 Teleconsultas de qualquer lugar do mundo", de:"📹 Videosprechstunden von überall auf der Welt", zh:"📹 全球任何地方都能视频问诊", ru:"📹 Видеоконсультации из любой точки мира"},
 "🏥 For clinics": {hi:"🏥 क्लिनिकों के लिए", es:"🏥 Para clínicas", fr:"🏥 Pour les cliniques", ar:"🏥 للعيادات", pt:"🏥 Para clínicas", de:"🏥 Für Praxen", zh:"🏥 诊所", ru:"🏥 Для клиник"},
 "Live dashboard: today's appointments": {hi:"लाइव डैशबोर्ड: आज के अपॉइंटमेंट", es:"Panel en vivo: citas de hoy", fr:"Tableau de bord en direct : rendez-vous du jour", ar:"لوحة مباشرة: مواعيد اليوم", pt:"Painel ao vivo: consultas de hoje", de:"Live-Dashboard: heutige Termine", zh:"实时后台：今日预约", ru:"Панель в реальном времени: записи на сегодня"},
 "Doctor available / not available toggle (live)": {hi:"डॉक्टर उपलब्ध / अनुपलब्ध स्विच (लाइव)", es:"Interruptor médico disponible / no disponible (en vivo)", fr:"Bouton médecin disponible / indisponible (en direct)", ar:"زر الطبيب متاح / غير متاح (مباشر)", pt:"Botão médico disponível / indisponível (ao vivo)", de:"Schalter Arzt verfügbar / nicht verfügbar (live)", zh:"医生在岗 / 不在岗开关（实时）", ru:"Переключатель «врач на месте / нет» (в реальном времени)"},
 "Patient status: arrived, done, no-show": {hi:"मरीज़ की स्थिति: आए, हो गया, नहीं आए", es:"Estado del paciente: llegó, atendido, no vino", fr:"Statut du patient : arrivé, terminé, absent", ar:"حالة المريض: وصل، انتهى، لم يحضر", pt:"Status do paciente: chegou, atendido, faltou", de:"Patientenstatus: da, fertig, nicht erschienen", zh:"患者状态：已到、已完成、爽约", ru:"Статус пациента: пришёл, принят, не явился"},
 "Instant emergency alerts": {hi:"तुरंत इमरजेंसी अलर्ट", es:"Alertas de urgencia al instante", fr:"Alertes d'urgence instantanées", ar:"تنبيهات طوارئ فورية", pt:"Alertas de emergência na hora", de:"Sofortige Notfallalarme", zh:"即时紧急提醒", ru:"Мгновенные экстренные оповещения"},
 "Reports: bookings, chats, no-shows": {hi:"रिपोर्ट: बुकिंग, चैट, न आने वाले", es:"Informes: citas, chats, ausencias", fr:"Rapports : rendez-vous, chats, absences", ar:"تقارير: الحجوزات، المحادثات، حالات الغياب", pt:"Relatórios: agendamentos, chats, faltas", de:"Berichte: Termine, Chats, Ausfälle", zh:"报表：预约、对话、爽约", ru:"Отчёты: записи, чаты, неявки"},
 "🌍 Works in any country and time zone": {hi:"🌍 हर देश और टाइम ज़ोन में काम करता है", es:"🌍 Funciona en cualquier país y zona horaria", fr:"🌍 Fonctionne dans tous les pays et fuseaux horaires", ar:"🌍 يعمل في أي دولة ومنطقة زمنية", pt:"🌍 Funciona em qualquer país e fuso horário", de:"🌍 Funktioniert in jedem Land und jeder Zeitzone", zh:"🌍 适用于任何国家和时区", ru:"🌍 Работает в любой стране и часовом поясе"},
 "📍 Try it": {hi:"📍 आज़माएँ", es:"📍 Pruébalo", fr:"📍 Essayer", ar:"📍 جرّبه", pt:"📍 Experimente", de:"📍 Ausprobieren", zh:"📍 试一试", ru:"📍 Попробовать"},
 "Pricing": {hi:"कीमत", es:"Precios", fr:"Tarifs", ar:"الأسعار", pt:"Preços", de:"Preise", zh:"价格", ru:"Цены"},
 "LESS THAN A RECEPTIONIST'S SALARY": {hi:"एक रिसेप्शनिस्ट की सैलरी से कम", es:"MENOS QUE EL SUELDO DE UNA RECEPCIONISTA", fr:"MOINS CHER QU'UN SALAIRE D'ACCUEIL", ar:"أقل من راتب موظف استقبال", pt:"MENOS QUE O SALÁRIO DE UMA RECEPCIONISTA", de:"GÜNSTIGER ALS EIN REZEPTIONSGEHALT", zh:"比雇一名前台还便宜", ru:"ДЕШЕВЛЕ ЗАРПЛАТЫ АДМИНИСТРАТОРА"},
 "/month": {hi:"/माह", es:"/mes", fr:"/mois", ar:"/شهرياً", pt:"/mês", de:"/Monat", zh:"/月", ru:"/мес."},
 "Website AI chat": {hi:"वेबसाइट AI चैट", es:"Chat con IA en la web", fr:"Chat IA sur le site", ar:"دردشة ذكية على الموقع", pt:"Chat com IA no site", de:"KI-Chat auf der Website", zh:"网站 AI 聊天", ru:"ИИ-чат на сайте"},
 "Online booking": {hi:"ऑनलाइन बुकिंग", es:"Reservas en línea", fr:"Réservation en ligne", ar:"حجز عبر الإنترنت", pt:"Agendamento online", de:"Online-Buchung", zh:"在线预约", ru:"Онлайн-запись"},
 "Clinic dashboard": {hi:"क्लिनिक डैशबोर्ड", es:"Panel de la clínica", fr:"Tableau de bord clinique", ar:"لوحة العيادة", pt:"Painel da clínica", de:"Praxis-Dashboard", zh:"诊所后台", ru:"Панель клиники"},
 "1 doctor": {hi:"1 डॉक्टर", es:"1 médico", fr:"1 médecin", ar:"طبيب واحد", pt:"1 médico", de:"1 Arzt", zh:"1 位医生", ru:"1 врач"},
 "See demo": {hi:"डेमो देखें", es:"Ver demo", fr:"Voir la démo", ar:"شاهد العرض", pt:"Ver demo", de:"Demo ansehen", zh:"查看演示", ru:"Смотреть демо"},
 "★ MOST POPULAR": {hi:"★ सबसे लोकप्रिय", es:"★ MÁS POPULAR", fr:"★ LE PLUS CHOISI", ar:"★ الأكثر طلباً", pt:"★ MAIS POPULAR", de:"★ AM BELIEBTESTEN", zh:"★ 最受欢迎", ru:"★ ПОПУЛЯРНЫЙ"},
 "Everything in Basic": {hi:"Basic की सभी सुविधाएँ", es:"Todo lo de Basic", fr:"Tout le forfait Basic", ar:"كل ما في Basic", pt:"Tudo do Basic", de:"Alles aus Basic", zh:"包含 Basic 全部功能", ru:"Всё из Basic"},
 "Auto reminders": {hi:"ऑटो रिमाइंडर", es:"Recordatorios automáticos", fr:"Rappels automatiques", ar:"تذكيرات تلقائية", pt:"Lembretes automáticos", de:"Automatische Erinnerungen", zh:"自动提醒", ru:"Автонапоминания"},
 "Google review requests": {hi:"Google रिव्यू अनुरोध", es:"Solicitudes de reseñas en Google", fr:"Demandes d'avis Google", ar:"طلبات تقييم على Google", pt:"Pedidos de avaliação no Google", de:"Google-Bewertungsanfragen", zh:"邀请 Google 评价", ru:"Запросы отзывов в Google"},
 "📹 Video consultations": {hi:"📹 वीडियो कंसल्टेशन", es:"📹 Videoconsultas", fr:"📹 Téléconsultations", ar:"📹 استشارات بالفيديو", pt:"📹 Teleconsultas", de:"📹 Videosprechstunden", zh:"📹 视频问诊", ru:"📹 Видеоконсультации"},
 "Up to 5 doctors": {hi:"5 डॉक्टर तक", es:"Hasta 5 médicos", fr:"Jusqu'à 5 médecins", ar:"حتى 5 أطباء", pt:"Até 5 médicos", de:"Bis zu 5 Ärzte", zh:"最多 5 位医生", ru:"До 5 врачей"},
 "Everything in Growth": {hi:"Growth की सभी सुविधाएँ", es:"Todo lo de Growth", fr:"Tout le forfait Growth", ar:"كل ما في Growth", pt:"Tudo do Growth", de:"Alles aus Growth", zh:"包含 Growth 全部功能", ru:"Всё из Growth"},
 "📞 Voice call AI": {hi:"📞 कॉल पर AI", es:"📞 IA por llamada", fr:"📞 IA au téléphone", ar:"📞 ذكاء اصطناعي للمكالمات", pt:"📞 IA por ligação", de:"📞 KI am Telefon", zh:"📞 语音电话 AI", ru:"📞 ИИ для звонков"},
 "Multi-branch": {hi:"कई ब्रांच", es:"Varias sedes", fr:"Multi-sites", ar:"عدة فروع", pt:"Várias unidades", de:"Mehrere Standorte", zh:"多分店", ru:"Несколько филиалов"},
 "\"Verified Live\" badge on map": {hi:"मैप पर \"वेरिफाइड लाइव\" बैज", es:"Insignia \"Verificado en vivo\" en el mapa", fr:"Badge « Vérifié en direct » sur la carte", ar:"شارة \"موثّق مباشر\" على الخريطة", pt:"Selo \"Verificado ao vivo\" no mapa", de:"„Live verifiziert“-Abzeichen auf der Karte", zh:"地图上的“实时认证”标识", ru:"Значок «Проверено» на карте"},
 "Clinora AI: demo build. The name and all data are placeholders.": {hi:"Clinora AI: डेमो संस्करण। नाम और सारा डेटा उदाहरण के लिए है।", es:"Clinora AI: versión de demostración. El nombre y los datos son de ejemplo.", fr:"Clinora AI : version de démonstration. Le nom et les données sont fictifs.", ar:"Clinora AI: نسخة تجريبية. الاسم وجميع البيانات للتوضيح فقط.", pt:"Clinora AI: versão de demonstração. O nome e os dados são exemplos.", de:"Clinora AI: Demoversion. Name und alle Daten sind Platzhalter.", zh:"Clinora AI：演示版本。名称和所有数据均为示例。", ru:"Clinora AI: демо-версия. Название и все данные условные."},

 /* ---- nearby ---- */
 "NEARBY DOCTORS": {hi:"पास के डॉक्टर", es:"MÉDICOS CERCANOS", fr:"MÉDECINS À PROXIMITÉ", ar:"أطباء قريبون", pt:"MÉDICOS PRÓXIMOS", de:"ÄRZTE IN DER NÄHE", zh:"附近医生", ru:"ВРАЧИ РЯДОМ"},
 "Who's open nearby?": {hi:"पास में अभी कौन खुला है?", es:"¿Quién está abierto cerca?", fr:"Qui est ouvert près de vous ?", ar:"من المفتوح بالقرب منك؟", pt:"Quem está aberto por perto?", de:"Wer hat in der Nähe geöffnet?", zh:"附近谁在营业？", ru:"Кто открыт рядом?"},
 "🚨 Emergency": {hi:"🚨 आपातकाल", es:"🚨 Emergencias", fr:"🚨 Urgences", ar:"🚨 الطوارئ", pt:"🚨 Emergência", de:"🚨 Notfall", zh:"🚨 紧急求助", ru:"🚨 Экстренная помощь"},
 "All emergencies": {hi:"सभी आपात स्थिति", es:"Todas las emergencias", fr:"Toutes urgences", ar:"جميع حالات الطوارئ", pt:"Todas as emergências", de:"Alle Notfälle", zh:"所有紧急情况", ru:"Все экстренные службы"},
 "Ambulance": {hi:"एम्बुलेंस", es:"Ambulancia", fr:"Ambulance", ar:"الإسعاف", pt:"Ambulância", de:"Rettungsdienst", zh:"救护车", ru:"Скорая помощь"},
 "Police": {hi:"पुलिस", es:"Policía", fr:"Police", ar:"الشرطة", pt:"Polícia", de:"Polizei", zh:"警察", ru:"Полиция"},
 "Mother & child": {hi:"माँ और बच्चा", es:"Madre e hijo", fr:"Mère et enfant", ar:"الأم والطفل", pt:"Mãe e filho", de:"Mutter & Kind", zh:"母婴", ru:"Мать и дитя"},
 "📍 The nearest hospital will appear here once we have your location.": {hi:"📍 आपकी लोकेशन मिलते ही सबसे नज़दीकी अस्पताल यहाँ दिखेगा।", es:"📍 El hospital más cercano aparecerá aquí cuando tengamos tu ubicación.", fr:"📍 L'hôpital le plus proche s'affichera ici dès que nous aurons votre position.", ar:"📍 سيظهر أقرب مستشفى هنا بمجرد معرفة موقعك.", pt:"📍 O hospital mais próximo aparecerá aqui quando tivermos sua localização.", de:"📍 Das nächste Krankenhaus erscheint hier, sobald wir Ihren Standort haben.", zh:"📍 获取您的位置后，这里会显示最近的医院。", ru:"📍 Ближайшая больница появится здесь, когда мы определим ваше местоположение."},
 "🆘 SOS: send my location to family": {hi:"🆘 SOS: परिवार को मेरी लोकेशन भेजें", es:"🆘 SOS: enviar mi ubicación a mi familia", fr:"🆘 SOS : envoyer ma position à ma famille", ar:"🆘 استغاثة: أرسل موقعي لعائلتي", pt:"🆘 SOS: enviar minha localização à família", de:"🆘 SOS: Standort an Familie senden", zh:"🆘 SOS：把我的位置发给家人", ru:"🆘 SOS: отправить моё местоположение семье"},
 "📍 My location": {hi:"📍 मेरी लोकेशन", es:"📍 Mi ubicación", fr:"📍 Ma position", ar:"📍 موقعي", pt:"📍 Minha localização", de:"📍 Mein Standort", zh:"📍 我的位置", ru:"📍 Моё местоположение"},
 "Search": {hi:"खोजें", es:"Buscar", fr:"Rechercher", ar:"بحث", pt:"Buscar", de:"Suchen", zh:"搜索", ru:"Найти"},
 "🔍 Search": {hi:"🔍 खोजें", es:"🔍 Buscar", fr:"🔍 Rechercher", ar:"🔍 بحث", pt:"🔍 Buscar", de:"🔍 Suchen", zh:"🔍 搜索", ru:"🔍 Найти"},
 "All": {hi:"सभी", es:"Todos", fr:"Tous", ar:"الكل", pt:"Todos", de:"Alle", zh:"全部", ru:"Все"},
 "🏥 Hospital": {hi:"🏥 अस्पताल", es:"🏥 Hospital", fr:"🏥 Hôpital", ar:"🏥 مستشفى", pt:"🏥 Hospital", de:"🏥 Krankenhaus", zh:"🏥 医院", ru:"🏥 Больница"},
 "Clinic": {hi:"क्लिनिक", es:"Clínica", fr:"Clinique", ar:"عيادة", pt:"Clínica", de:"Praxis", zh:"诊所", ru:"Клиника"},
 "🦷 Dentist": {hi:"🦷 दंत चिकित्सक", es:"🦷 Dentista", fr:"🦷 Dentiste", ar:"🦷 طبيب أسنان", pt:"🦷 Dentista", de:"🦷 Zahnarzt", zh:"🦷 牙医", ru:"🦷 Стоматолог"},
 "👨‍⚕️ Doctor": {hi:"👨‍⚕️ डॉक्टर", es:"👨‍⚕️ Médico", fr:"👨‍⚕️ Médecin", ar:"👨‍⚕️ طبيب", pt:"👨‍⚕️ Médico", de:"👨‍⚕️ Arzt", zh:"👨‍⚕️ 医生", ru:"👨‍⚕️ Врач"},
 "🟢 Open only": {hi:"🟢 सिर्फ़ खुले", es:"🟢 Solo abiertos", fr:"🟢 Ouverts seulement", ar:"🟢 المفتوح فقط", pt:"🟢 Só abertos", de:"🟢 Nur geöffnete", zh:"🟢 仅营业中", ru:"🟢 Только открытые"},
 "Waiting for location…": {hi:"लोकेशन का इंतज़ार…", es:"Esperando la ubicación…", fr:"En attente de la position…", ar:"بانتظار الموقع…", pt:"Aguardando a localização…", de:"Warte auf Standort…", zh:"正在获取位置…", ru:"Ожидание местоположения…"},
 "⌖ Recenter": {hi:"⌖ बीच में लाएँ", es:"⌖ Centrar", fr:"⌖ Recentrer", ar:"⌖ توسيط", pt:"⌖ Centralizar", de:"⌖ Zentrieren", zh:"⌖ 回到中心", ru:"⌖ По центру"},
 "📞 Call": {hi:"📞 कॉल करें", es:"📞 Llamar", fr:"📞 Appeler", ar:"📞 اتصال", pt:"📞 Ligar", de:"📞 Anrufen", zh:"📞 拨打", ru:"📞 Позвонить"},
 "🧭 Directions": {hi:"🧭 रास्ता", es:"🧭 Cómo llegar", fr:"🧭 Itinéraire", ar:"🧭 الاتجاهات", pt:"🧭 Como chegar", de:"🧭 Route", zh:"🧭 导航", ru:"🧭 Маршрут"},
 "👤 Profile": {hi:"👤 प्रोफ़ाइल", es:"👤 Perfil", fr:"👤 Profil", ar:"👤 الملف", pt:"👤 Perfil", de:"👤 Profil", zh:"👤 详情", ru:"👤 Профиль"},
 "🗺️ Map": {hi:"🗺️ मैप", es:"🗺️ Mapa", fr:"🗺️ Carte", ar:"🗺️ الخريطة", pt:"🗺️ Mapa", de:"🗺️ Karte", zh:"🗺️ 地图", ru:"🗺️ Карта"},
 "🗺️ Show on map": {hi:"🗺️ मैप पर दिखाएँ", es:"🗺️ Ver en el mapa", fr:"🗺️ Voir sur la carte", ar:"🗺️ اعرض على الخريطة", pt:"🗺️ Ver no mapa", de:"🗺️ Auf der Karte zeigen", zh:"🗺️ 在地图上查看", ru:"🗺️ Показать на карте"},
 "📅 Book with AI": {hi:"📅 AI से बुक करें", es:"📅 Reservar con la IA", fr:"📅 Réserver avec l'IA", ar:"📅 احجز عبر الذكاء الاصطناعي", pt:"📅 Agendar com a IA", de:"📅 Mit KI buchen", zh:"📅 用 AI 预约", ru:"📅 Записаться через ИИ"},

 /* ---- world directory ---- */
 "WORLD DIRECTORY": {hi:"विश्व निर्देशिका", es:"DIRECTORIO MUNDIAL", fr:"ANNUAIRE MONDIAL", ar:"الدليل العالمي", pt:"DIRETÓRIO MUNDIAL", de:"WELTVERZEICHNIS", zh:"全球名录", ru:"МИРОВОЙ КАТАЛОГ"},
 "Hospitals, clinics and doctors worldwide": {hi:"दुनिया भर के अस्पताल, क्लिनिक और डॉक्टर", es:"Hospitales, clínicas y médicos de todo el mundo", fr:"Hôpitaux, cliniques et médecins du monde entier", ar:"مستشفيات وعيادات وأطباء حول العالم", pt:"Hospitais, clínicas e médicos no mundo todo", de:"Krankenhäuser, Praxen und Ärzte weltweit", zh:"全球医院、诊所和医生", ru:"Больницы, клиники и врачи по всему миру"},
 "🏥 Hospitals": {hi:"🏥 अस्पताल", es:"🏥 Hospitales", fr:"🏥 Hôpitaux", ar:"🏥 مستشفيات", pt:"🏥 Hospitais", de:"🏥 Krankenhäuser", zh:"🏥 医院", ru:"🏥 Больницы"},
 "Clinics": {hi:"क्लिनिक", es:"Clínicas", fr:"Cliniques", ar:"عيادات", pt:"Clínicas", de:"Praxen", zh:"诊所", ru:"Клиники"},
 "👨‍⚕️ Doctors": {hi:"👨‍⚕️ डॉक्टर", es:"👨‍⚕️ Médicos", fr:"👨‍⚕️ Médecins", ar:"👨‍⚕️ أطباء", pt:"👨‍⚕️ Médicos", de:"👨‍⚕️ Ärzte", zh:"👨‍⚕️ 医生", ru:"👨‍⚕️ Врачи"},
 "🦷 Dentists": {hi:"🦷 दंत चिकित्सक", es:"🦷 Dentistas", fr:"🦷 Dentistes", ar:"🦷 أطباء أسنان", pt:"🦷 Dentistas", de:"🦷 Zahnärzte", zh:"🦷 牙医", ru:"🦷 Стоматологи"},
 "💊 Pharmacies": {hi:"💊 फ़ार्मेसी", es:"💊 Farmacias", fr:"💊 Pharmacies", ar:"💊 صيدليات", pt:"💊 Farmácias", de:"💊 Apotheken", zh:"💊 药店", ru:"💊 Аптеки"},
 "POPULAR": {hi:"लोकप्रिय", es:"POPULARES", fr:"POPULAIRES", ar:"الأكثر بحثاً", pt:"POPULARES", de:"BELIEBT", zh:"热门", ru:"ПОПУЛЯРНЫЕ"},
 "Pick a city above or type any place in the world.": {hi:"ऊपर कोई शहर चुनें या दुनिया की कोई भी जगह लिखें।", es:"Elige una ciudad arriba o escribe cualquier lugar del mundo.", fr:"Choisissez une ville ci-dessus ou tapez n'importe quel lieu.", ar:"اختر مدينة من الأعلى أو اكتب أي مكان في العالم.", pt:"Escolha uma cidade acima ou digite qualquer lugar do mundo.", de:"Wählen Sie oben eine Stadt oder geben Sie einen beliebigen Ort ein.", zh:"选择上方城市，或输入世界上任何地点。", ru:"Выберите город выше или введите любое место в мире."},
 "👨‍⚕️ Join as a doctor or clinic": {hi:"👨‍⚕️ डॉक्टर या क्लिनिक के रूप में जुड़ें", es:"👨‍⚕️ Únete como médico o clínica", fr:"👨‍⚕️ Rejoindre en tant que médecin ou clinique", ar:"👨‍⚕️ انضم كطبيب أو عيادة", pt:"👨‍⚕️ Cadastre-se como médico ou clínica", de:"👨‍⚕️ Als Arzt oder Praxis mitmachen", zh:"👨‍⚕️ 医生或诊所入驻", ru:"👨‍⚕️ Присоединиться как врач или клиника"},
 "Free listing on the world map and directory. Patients can call you, get directions, and book in-clinic or video visits.": {hi:"विश्व मैप और निर्देशिका पर मुफ़्त लिस्टिंग। मरीज़ आपको कॉल कर सकते हैं, रास्ता देख सकते हैं, और क्लिनिक या वीडियो विज़िट बुक कर सकते हैं।", es:"Aparece gratis en el mapa y el directorio mundial. Los pacientes pueden llamarte, ver cómo llegar y reservar citas presenciales o por video.", fr:"Fiche gratuite sur la carte et l'annuaire mondial. Les patients peuvent vous appeler, obtenir l'itinéraire et réserver en cabinet ou en vidéo.", ar:"إدراج مجاني على الخريطة والدليل العالمي. يمكن للمرضى الاتصال بك ومعرفة الاتجاهات وحجز زيارة في العيادة أو بالفيديو.", pt:"Cadastro grátis no mapa e no diretório mundial. Pacientes podem ligar, ver como chegar e agendar consultas presenciais ou por vídeo.", de:"Kostenloser Eintrag auf Weltkarte und Verzeichnis. Patienten können anrufen, die Route sehen und Praxis- oder Videotermine buchen.", zh:"免费入驻全球地图和名录。患者可以给您打电话、查看路线，并预约到诊或视频问诊。", ru:"Бесплатное размещение на мировой карте и в каталоге. Пациенты смогут позвонить, построить маршрут и записаться на очный или видеоприём."},
 "TYPE": {hi:"प्रकार", es:"TIPO", fr:"TYPE", ar:"النوع", pt:"TIPO", de:"ART", zh:"类型", ru:"ТИП"},
 "Doctor": {hi:"डॉक्टर", es:"Médico", fr:"Médecin", ar:"طبيب", pt:"Médico", de:"Arzt", zh:"医生", ru:"Врач"},
 "Hospital": {hi:"अस्पताल", es:"Hospital", fr:"Hôpital", ar:"مستشفى", pt:"Hospital", de:"Krankenhaus", zh:"医院", ru:"Больница"},
 "Dentist": {hi:"दंत चिकित्सक", es:"Dentista", fr:"Dentiste", ar:"طبيب أسنان", pt:"Dentista", de:"Zahnarzt", zh:"牙医", ru:"Стоматолог"},
 "SPECIALTY": {hi:"विशेषज्ञता", es:"ESPECIALIDAD", fr:"SPÉCIALITÉ", ar:"التخصص", pt:"ESPECIALIDADE", de:"FACHRICHTUNG", zh:"专科", ru:"СПЕЦИАЛЬНОСТЬ"},
 "FULL NAME / CLINIC NAME *": {hi:"पूरा नाम / क्लिनिक का नाम *", es:"NOMBRE COMPLETO / CLÍNICA *", fr:"NOM COMPLET / CLINIQUE *", ar:"الاسم الكامل / اسم العيادة *", pt:"NOME COMPLETO / CLÍNICA *", de:"VOLLER NAME / PRAXIS *", zh:"姓名 / 诊所名称 *", ru:"ФИО / НАЗВАНИЕ КЛИНИКИ *"},
 "PHONE (WITH COUNTRY CODE) *": {hi:"फ़ोन (देश कोड के साथ) *", es:"TELÉFONO (CON PREFIJO) *", fr:"TÉLÉPHONE (AVEC INDICATIF) *", ar:"الهاتف (مع رمز الدولة) *", pt:"TELEFONE (COM DDI) *", de:"TELEFON (MIT LÄNDERVORWAHL) *", zh:"电话（含国家区号）*", ru:"ТЕЛЕФОН (С КОДОМ СТРАНЫ) *"},
 "EMAIL": {hi:"ईमेल", es:"CORREO", fr:"E-MAIL", ar:"البريد الإلكتروني", pt:"E-MAIL", de:"E-MAIL", zh:"邮箱", ru:"ЭЛ. ПОЧТА"},
 "WEBSITE": {hi:"वेबसाइट", es:"SITIO WEB", fr:"SITE WEB", ar:"الموقع الإلكتروني", pt:"SITE", de:"WEBSITE", zh:"网站", ru:"САЙТ"},
 "ADDRESS *": {hi:"पता *", es:"DIRECCIÓN *", fr:"ADRESSE *", ar:"العنوان *", pt:"ENDEREÇO *", de:"ADRESSE *", zh:"地址 *", ru:"АДРЕС *"},
 "CITY *": {hi:"शहर *", es:"CIUDAD *", fr:"VILLE *", ar:"المدينة *", pt:"CIDADE *", de:"STADT *", zh:"城市 *", ru:"ГОРОД *"},
 "COUNTRY *": {hi:"देश *", es:"PAÍS *", fr:"PAYS *", ar:"الدولة *", pt:"PAÍS *", de:"LAND *", zh:"国家 *", ru:"СТРАНА *"},
 "Offers video consultations": {hi:"वीडियो कंसल्टेशन देते हैं", es:"Ofrece videoconsultas", fr:"Propose des téléconsultations", ar:"يقدم استشارات بالفيديو", pt:"Oferece teleconsultas", de:"Bietet Videosprechstunden an", zh:"提供视频问诊", ru:"Проводит видеоконсультации"},
 "I confirm these are my own professional details and I agree to show them publicly.": {hi:"मैं पुष्टि करता/करती हूँ कि ये मेरी अपनी पेशेवर जानकारी है और मैं इसे सार्वजनिक रूप से दिखाने के लिए सहमत हूँ।", es:"Confirmo que son mis propios datos profesionales y acepto que se muestren públicamente.", fr:"Je confirme qu'il s'agit de mes propres coordonnées professionnelles et j'accepte qu'elles soient publiques.", ar:"أؤكد أن هذه بياناتي المهنية وأوافق على عرضها للعامة.", pt:"Confirmo que estes são meus próprios dados profissionais e concordo em exibi-los publicamente.", de:"Ich bestätige, dass dies meine eigenen beruflichen Daten sind, und stimme der Veröffentlichung zu.", zh:"我确认这些是我本人的执业信息，并同意公开展示。", ru:"Подтверждаю, что это мои профессиональные данные, и согласен(на) на их публикацию."},
 "Add my listing": {hi:"मेरी लिस्टिंग जोड़ें", es:"Publicar mi ficha", fr:"Ajouter ma fiche", ar:"أضف إدراجي", pt:"Adicionar meu cadastro", de:"Eintrag hinzufügen", zh:"提交入驻", ru:"Добавить мою карточку"},

 /* ---- chat panel ---- */
 "CHANNEL": {hi:"चैनल", es:"CANAL", fr:"CANAL", ar:"القناة", pt:"CANAL", de:"KANAL", zh:"渠道", ru:"КАНАЛ"},
 "Website": {hi:"वेबसाइट", es:"Web", fr:"Site", ar:"الموقع", pt:"Site", de:"Website", zh:"网站", ru:"Сайт"},
 "Call": {hi:"कॉल", es:"Llamada", fr:"Appel", ar:"اتصال", pt:"Ligação", de:"Anruf", zh:"电话", ru:"Звонок"},
 "I need a dentist tomorrow": {hi:"कल दांत के डॉक्टर को दिखाना है", es:"Necesito un dentista mañana", fr:"Il me faut un dentiste demain", ar:"أحتاج طبيب أسنان غداً", pt:"Preciso de um dentista amanhã", de:"Ich brauche morgen einen Zahnarzt", zh:"我明天要看牙医", ru:"Мне нужен стоматолог завтра"},
 "Video consult for a skin rash": {hi:"त्वचा पर दाने के लिए वीडियो कंसल्टेशन", es:"Videoconsulta por una erupción en la piel", fr:"Téléconsultation pour une éruption cutanée", ar:"استشارة فيديو لطفح جلدي", pt:"Teleconsulta para uma alergia na pele", de:"Videosprechstunde wegen Hautausschlag", zh:"皮疹视频问诊", ru:"Видеоконсультация по поводу сыпи"},
 "Is the clinic open now?": {hi:"क्या क्लिनिक अभी खुला है?", es:"¿Está abierta la clínica ahora?", fr:"La clinique est-elle ouverte ?", ar:"هل العيادة مفتوحة الآن؟", pt:"A clínica está aberta agora?", de:"Hat die Praxis jetzt geöffnet?", zh:"诊所现在开门吗？", ru:"Клиника сейчас открыта?"},
 "Hospitals in Nairobi": {hi:"नैरोबी में अस्पताल", es:"Hospitales en Nairobi", fr:"Hôpitaux à Nairobi", ar:"مستشفيات في نيروبي", pt:"Hospitais em Nairóbi", de:"Krankenhäuser in Nairobi", zh:"内罗毕的医院", ru:"Больницы в Найроби"},
 "My child has a fever": {hi:"मेरे बच्चे को बुखार है", es:"Mi hijo tiene fiebre", fr:"Mon enfant a de la fièvre", ar:"طفلي مصاب بالحمى", pt:"Meu filho está com febre", de:"Mein Kind hat Fieber", zh:"我的孩子发烧了", ru:"У моего ребёнка температура"},
 "Cancel my booking": {hi:"मेरी बुकिंग रद्द करें", es:"Cancelar mi cita", fr:"Annuler mon rendez-vous", ar:"إلغاء حجزي", pt:"Cancelar meu agendamento", de:"Meinen Termin absagen", zh:"取消我的预约", ru:"Отменить мою запись"},
 "Send ➤": {hi:"भेजें ➤", es:"Enviar ➤", fr:"Envoyer ➤", ar:"إرسال ➤", pt:"Enviar ➤", de:"Senden ➤", zh:"发送 ➤", ru:"Отправить ➤"},

 /* ---- video call ---- */
 "VIDEO CONSULTATION": {hi:"वीडियो कंसल्टेशन", es:"VIDEOCONSULTA", fr:"TÉLÉCONSULTATION", ar:"استشارة بالفيديو", pt:"TELECONSULTA", de:"VIDEOSPRECHSTUNDE", zh:"视频问诊", ru:"ВИДЕОКОНСУЛЬТАЦИЯ"},
 "Ready to join?": {hi:"जुड़ने के लिए तैयार?", es:"¿Listo para entrar?", fr:"Prêt à rejoindre ?", ar:"جاهز للانضمام؟", pt:"Pronto para entrar?", de:"Bereit beizutreten?", zh:"准备好加入了吗？", ru:"Готовы подключиться?"},
 "📹 Join video call": {hi:"📹 वीडियो कॉल से जुड़ें", es:"📹 Entrar a la videollamada", fr:"📹 Rejoindre l'appel vidéo", ar:"📹 انضم إلى مكالمة الفيديو", pt:"📹 Entrar na videochamada", de:"📹 Videoanruf beitreten", zh:"📹 加入视频通话", ru:"📹 Присоединиться к видеозвонку"},
 "Your camera and microphone are only used during the call. The video goes directly between you and the doctor.": {hi:"आपका कैमरा और माइक सिर्फ़ कॉल के दौरान इस्तेमाल होता है। वीडियो सीधे आपके और डॉक्टर के बीच जाता है।", es:"La cámara y el micrófono solo se usan durante la llamada. El video va directamente entre tú y el médico.", fr:"La caméra et le micro ne servent que pendant l'appel. La vidéo passe directement entre vous et le médecin.", ar:"تُستخدم الكاميرا والميكروفون أثناء المكالمة فقط. ينتقل الفيديو مباشرة بينك وبين الطبيب.", pt:"A câmera e o microfone só são usados durante a chamada. O vídeo vai direto entre você e o médico.", de:"Kamera und Mikrofon werden nur während des Anrufs genutzt. Das Video geht direkt zwischen Ihnen und dem Arzt.", zh:"摄像头和麦克风仅在通话期间使用。视频直接在您和医生之间传输。", ru:"Камера и микрофон используются только во время звонка. Видео идёт напрямую между вами и врачом."},
 "Waiting for the doctor to join…": {hi:"डॉक्टर के जुड़ने का इंतज़ार…", es:"Esperando a que entre el médico…", fr:"En attente du médecin…", ar:"بانتظار انضمام الطبيب…", pt:"Aguardando o médico entrar…", de:"Warten auf den Arzt…", zh:"正在等待医生加入…", ru:"Ожидание врача…"},
 "Keep this page open. The call starts automatically when they join.": {hi:"यह पेज खुला रखें। उनके जुड़ते ही कॉल अपने आप शुरू हो जाएगी।", es:"Mantén esta página abierta. La llamada empieza sola cuando se conecten.", fr:"Gardez cette page ouverte. L'appel démarre automatiquement à leur arrivée.", ar:"أبقِ هذه الصفحة مفتوحة. ستبدأ المكالمة تلقائياً عند انضمامهم.", pt:"Mantenha esta página aberta. A chamada começa sozinha quando entrarem.", de:"Lassen Sie diese Seite offen. Der Anruf startet automatisch, sobald sie beitreten.", zh:"请保持此页面打开，对方加入后通话会自动开始。", ru:"Не закрывайте страницу. Звонок начнётся автоматически, когда собеседник подключится."},

 /* ---- placeholders ---- */
 "Or type any city / area, worldwide…": {hi:"या दुनिया का कोई भी शहर / इलाका लिखें…", es:"O escribe cualquier ciudad o zona del mundo…", fr:"Ou tapez une ville / un quartier, partout…", ar:"أو اكتب أي مدينة / منطقة في العالم…", pt:"Ou digite qualquer cidade / bairro do mundo…", de:"Oder beliebige Stadt / Gegend eingeben…", zh:"或输入全球任意城市 / 地区…", ru:"Или введите любой город / район в мире…"},
 "City or country, e.g. Dubai, Kenya, Toronto": {hi:"शहर या देश, जैसे दुबई, केन्या, टोरंटो", es:"Ciudad o país, p. ej. Dubái, Kenia, Toronto", fr:"Ville ou pays, ex. Dubaï, Kenya, Toronto", ar:"مدينة أو دولة، مثل دبي، كينيا، تورنتو", pt:"Cidade ou país, ex.: Dubai, Quênia, Toronto", de:"Stadt oder Land, z. B. Dubai, Kenia, Toronto", zh:"城市或国家，例如 迪拜、肯尼亚、多伦多", ru:"Город или страна, напр. Дубай, Кения, Торонто"},
 "Name (optional), e.g. St Mary's, Apollo, Mayo…": {hi:"नाम (वैकल्पिक), जैसे Apollo, AIIMS…", es:"Nombre (opcional), p. ej. Hospital General…", fr:"Nom (facultatif), ex. Pitié-Salpêtrière…", ar:"الاسم (اختياري)…", pt:"Nome (opcional), ex.: Albert Einstein…", de:"Name (optional), z. B. Charité…", zh:"名称（可选）…", ru:"Название (необязательно)…"},
 "Ask anything… e.g. kal daant dikhana hai": {hi:"कुछ भी पूछें… जैसे: कल दांत दिखाना है", es:"Pregunta lo que quieras…", fr:"Posez votre question…", ar:"اسأل أي شيء…", pt:"Pergunte o que quiser…", de:"Fragen Sie etwas…", zh:"随便问…", ru:"Задайте вопрос…"},
 "Street, area": {hi:"गली, इलाका", es:"Calle, zona", fr:"Rue, quartier", ar:"الشارع، المنطقة", pt:"Rua, bairro", de:"Straße, Gegend", zh:"街道、区域", ru:"Улица, район"},
 "City": {hi:"शहर", es:"Ciudad", fr:"Ville", ar:"المدينة", pt:"Cidade", de:"Stadt", zh:"城市", ru:"Город"},
 "Country": {hi:"देश", es:"País", fr:"Pays", ar:"الدولة", pt:"País", de:"Land", zh:"国家", ru:"Страна"},

 /* ---- paragraphs with formatting (data-i18n="key") ---- */
 "@h1": {
   hi:'आपके क्लिनिक का<br>रिसेप्शनिस्ट <span class="slash">//</span><br><span class="outline">24×7.</span> AI.',
   es:'La recepción<br>de tu clínica <span class="slash">//</span><br><span class="outline">24×7.</span> IA.',
   fr:'L\'accueil de<br>votre clinique <span class="slash">//</span><br><span class="outline">24h/24.</span> IA.',
   ar:'استقبال<br>عيادتك <span class="slash">//</span><br><span class="outline">24×7.</span> ذكي.',
   pt:'A recepção<br>da sua clínica <span class="slash">//</span><br><span class="outline">24×7.</span> IA.',
   de:'Die Rezeption<br>Ihrer Praxis <span class="slash">//</span><br><span class="outline">24/7.</span> KI.',
   zh:'您诊所的<br>前台接待 <span class="slash">//</span><br><span class="outline">24×7.</span> AI。',
   ru:'Регистратура<br>вашей клиники <span class="slash">//</span><br><span class="outline">24/7.</span> ИИ.'},
 "@lead": {
   hi:'दुनिया में कहीं भी मरीज़ WhatsApp, वेब चैट या फ़ोन पर 24×7 अपने क्लिनिक से जुड़ सकते हैं, क्लिनिक विज़िट या <b>वीडियो कंसल्टेशन</b> बुक कर सकते हैं, और देख सकते हैं कि पास में कौन से डॉक्टर <b class="teal">अभी खुले हैं</b>।',
   es:'Pacientes de cualquier parte del mundo pueden contactar con su clínica 24×7 por WhatsApp, chat web o teléfono, reservar una cita presencial o una <b>videoconsulta</b> y ver qué médicos cercanos están <b class="teal">abiertos ahora</b>.',
   fr:'Partout dans le monde, les patients joignent leur clinique 24h/24 par WhatsApp, chat web ou téléphone, réservent une visite au cabinet ou une <b>téléconsultation</b>, et voient quels médecins proches sont <b class="teal">ouverts maintenant</b>.',
   ar:'يستطيع المرضى في أي مكان في العالم التواصل مع عيادتهم على مدار الساعة عبر واتساب أو دردشة الموقع أو الهاتف، وحجز زيارة في العيادة أو <b>استشارة بالفيديو</b>، ومعرفة الأطباء القريبين <b class="teal">المفتوحين الآن</b>.',
   pt:'Pacientes de qualquer lugar do mundo falam com a clínica 24×7 pelo WhatsApp, chat do site ou telefone, agendam consulta presencial ou <b>teleconsulta</b> e veem quais médicos por perto estão <b class="teal">abertos agora</b>.',
   de:'Patienten überall auf der Welt erreichen ihre Praxis rund um die Uhr per WhatsApp, Web-Chat oder Telefon, buchen einen Praxistermin oder eine <b>Videosprechstunde</b> und sehen, welche Ärzte in der Nähe <b class="teal">jetzt geöffnet</b> haben.',
   zh:'全球任何地方的患者都能通过 WhatsApp、网页聊天或电话 24×7 联系诊所，预约到诊或<b>视频问诊</b>，并查看附近哪些医生<b class="teal">正在营业</b>。',
   ru:'Пациенты из любой точки мира связываются с клиникой круглосуточно через WhatsApp, чат на сайте или телефон, записываются на очный приём или <b>видеоконсультацию</b> и видят, какие врачи рядом <b class="teal">открыты сейчас</b>.'},
 "@h2open": {hi:'अभी कौन<br>खुला है?', es:'¿Quién está<br>abierto ahora?', fr:'Qui est<br>ouvert maintenant ?', ar:'من المفتوح<br>الآن؟', pt:'Quem está<br>aberto agora?', de:'Wer hat<br>jetzt geöffnet?', zh:'现在<br>谁在营业？', ru:'Кто открыт<br>прямо сейчас?'},
 "@popen": {
   hi:'मरीज़ की लोकेशन के पास, दुनिया में कहीं भी, क्लिनिक, अस्पताल और दंत चिकित्सक: <b>खुला / बंद</b> स्टेटस, पता, फ़ोन नंबर और रास्ता। <b class="red">मरीज़ के देश के इमरजेंसी नंबर</b> हमेशा सबसे ऊपर।',
   es:'Clínicas, hospitales y dentistas cerca del paciente, en cualquier lugar del mundo, con estado <b>abierto / cerrado</b>, dirección, teléfono e indicaciones. Los <b class="red">números de emergencia del país del paciente</b> siempre aparecen arriba.',
   fr:'Cliniques, hôpitaux et dentistes près du patient, partout dans le monde, avec statut <b>ouvert / fermé</b>, adresse, téléphone et itinéraire. Les <b class="red">numéros d\'urgence du pays du patient</b> restent toujours en haut.',
   ar:'عيادات ومستشفيات وأطباء أسنان قرب موقع المريض في أي مكان في العالم، مع حالة <b>مفتوح / مغلق</b> والعنوان ورقم الهاتف والاتجاهات. <b class="red">أرقام الطوارئ في بلد المريض</b> تظهر دائماً في الأعلى.',
   pt:'Clínicas, hospitais e dentistas perto do paciente, em qualquer lugar do mundo, com status <b>aberto / fechado</b>, endereço, telefone e rota. Os <b class="red">números de emergência do país do paciente</b> ficam sempre no topo.',
   de:'Praxen, Krankenhäuser und Zahnärzte in der Nähe des Patienten, überall auf der Welt, mit Status <b>geöffnet / geschlossen</b>, Adresse, Telefonnummer und Route. Die <b class="red">Notrufnummern des Landes</b> stehen immer ganz oben.',
   zh:'全球任何地方，显示患者附近的诊所、医院和牙医：<b>营业 / 休息</b>状态、地址、电话和路线。<b class="red">患者所在国家的急救电话</b>始终置顶。',
   ru:'Клиники, больницы и стоматологи рядом с пациентом в любой точке мира: статус <b>открыто / закрыто</b>, адрес, телефон и маршрут. <b class="red">Номера экстренных служб страны пациента</b> всегда наверху.'},
 "@foot2": {
   hi:'⚠️ AI चिकित्सा सलाह नहीं देता। आपात स्थिति में तुरंत अपने <b class="red">स्थानीय इमरजेंसी नंबर</b> पर कॉल करें।',
   es:'⚠️ La IA no da consejos médicos. En una emergencia, llama de inmediato a tu <b class="red">número de emergencia local</b>.',
   fr:'⚠️ L\'IA ne donne pas d\'avis médical. En cas d\'urgence, appelez immédiatement votre <b class="red">numéro d\'urgence local</b>.',
   ar:'⚠️ الذكاء الاصطناعي لا يقدم نصائح طبية. في حالات الطوارئ اتصل فوراً بـ<b class="red">رقم الطوارئ المحلي</b>.',
   pt:'⚠️ A IA não dá conselhos médicos. Em uma emergência, ligue imediatamente para o <b class="red">número de emergência local</b>.',
   de:'⚠️ Die KI gibt keinen medizinischen Rat. Rufen Sie im Notfall sofort die <b class="red">örtliche Notrufnummer</b> an.',
   zh:'⚠️ AI 不提供医疗建议。紧急情况下，请立即拨打<b class="red">当地急救电话</b>。',
   ru:'⚠️ ИИ не даёт медицинских советов. В экстренной ситуации сразу звоните по <b class="red">местному номеру экстренной помощи</b>.'},
 "@pnear": {
   hi:'OpenStreetMap से आपके आस-पास के असली क्लिनिक और अस्पताल। <b class="teal">हरे-नीले</b> निशान वाले Clinora पार्टनर क्लिनिक हैं, जिनका स्टेटस क्लिनिक डैशबोर्ड से <b>लाइव</b> आता है।',
   es:'Clínicas y hospitales reales a tu alrededor, de OpenStreetMap. Los de color <b class="teal">turquesa</b> son clínicas asociadas de Clinora con estado <b>en vivo</b> desde su panel.',
   fr:'De vraies cliniques et hôpitaux autour de vous, issus d\'OpenStreetMap. Ceux en <b class="teal">turquoise</b> sont des cliniques partenaires Clinora dont le statut vient <b>en direct</b> de leur tableau de bord.',
   ar:'عيادات ومستشفيات حقيقية حولك من OpenStreetMap. العلامات <b class="teal">الفيروزية</b> هي عيادات شريكة لـ Clinora تأتي حالتها <b>مباشرة</b> من لوحة العيادة.',
   pt:'Clínicas e hospitais reais ao seu redor, do OpenStreetMap. Os em <b class="teal">verde-água</b> são clínicas parceiras Clinora com status <b>ao vivo</b> do painel da clínica.',
   de:'Echte Praxen und Krankenhäuser in Ihrer Nähe aus OpenStreetMap. <b class="teal">Türkis</b> markierte sind Clinora-Partnerpraxen, deren Status <b>live</b> aus dem Praxis-Dashboard kommt.',
   zh:'来自 OpenStreetMap 的您周边真实诊所和医院。<b class="teal">青色</b>标记为 Clinora 合作诊所，其状态<b>实时</b>来自诊所后台。',
   ru:'Реальные клиники и больницы вокруг вас из OpenStreetMap. <b class="teal">Бирюзовые</b> — клиники-партнёры Clinora, их статус обновляется <b>в реальном времени</b> из панели клиники.'},
 "@pdir": {
   hi:'धरती का कोई भी देश या शहर खोजें। लिस्टिंग OpenStreetMap के सार्वजनिक डेटा से लाइव आती हैं। डॉक्टर और क्लिनिक अपनी जानकारी के साथ खुद भी <b class="teal">नेटवर्क से जुड़</b> सकते हैं।',
   es:'Busca cualquier país o ciudad del planeta. Los resultados vienen en vivo de los datos públicos de OpenStreetMap. Médicos y clínicas también pueden <b class="teal">unirse a la red</b> con sus propios datos de contacto.',
   fr:'Cherchez n\'importe quel pays ou ville. Les fiches viennent en direct des données publiques d\'OpenStreetMap. Médecins et cliniques peuvent aussi <b class="teal">rejoindre le réseau</b> avec leurs propres coordonnées.',
   ar:'ابحث عن أي دولة أو مدينة في العالم. النتائج تأتي مباشرة من بيانات OpenStreetMap العامة. ويمكن للأطباء والعيادات أيضاً <b class="teal">الانضمام إلى الشبكة</b> ببيانات الاتصال الخاصة بهم.',
   pt:'Pesquise qualquer país ou cidade do planeta. Os resultados vêm ao vivo dos dados públicos do OpenStreetMap. Médicos e clínicas também podem <b class="teal">entrar na rede</b> com seus próprios contatos.',
   de:'Suchen Sie jedes Land und jede Stadt der Welt. Die Einträge kommen live aus den öffentlichen Daten von OpenStreetMap. Ärzte und Praxen können sich auch selbst mit ihren Kontaktdaten <b class="teal">im Netzwerk eintragen</b>.',
   zh:'搜索地球上任何国家或城市。结果实时来自 OpenStreetMap 公开数据。医生和诊所也可以用自己的联系方式<b class="teal">加入网络</b>。',
   ru:'Ищите любую страну или город на Земле. Данные поступают в реальном времени из открытых данных OpenStreetMap. Врачи и клиники также могут сами <b class="teal">присоединиться к сети</b> со своими контактами.'},
};

/* ---------------------------------------------------------------- engine */
let LANG = 'en';
let READY = new Set(BUILTIN);      // languages we can show right now
let AI_TRANSLATE = false;          // server can translate new languages (AI key present)
const SKIP = new Set(['SCRIPT', 'STYLE', 'TEXTAREA', 'INPUT', 'CODE']);
function tr(key, lang) { const e = T[key]; return e && (e[lang || LANG] || e.en) || null; }
function inChat(node) { const el = node.nodeType === 1 ? node : node.parentElement; return !!(el && el.closest && el.closest('#chat, .notranslate')); }

function translateText(node) {
  if (node.__en === undefined) node.__en = node.nodeValue;
  const src = node.__en, key = src.trim();
  if (!key || inChat(node)) return;
  const val = LANG === 'en' ? null : (T[key] && T[key][LANG]);
  const next = val ? src.replace(key, val) : src;
  if (node.nodeValue !== next) node.nodeValue = next;
}
function translateAttrs(el) {
  for (const attr of ['placeholder', 'title', 'aria-label']) {
    if (!el.hasAttribute || !el.hasAttribute(attr)) continue;
    const store = '__en_' + attr;
    if (el[store] === undefined) el[store] = el.getAttribute(attr);
    const key = el[store].trim(), val = LANG === 'en' ? null : (T[key] && T[key][LANG]);
    el.setAttribute(attr, val || el[store]);
  }
}
function translateTree(root) {
  if (!root) return;
  if (root.nodeType === 3) return translateText(root);
  if (root.nodeType !== 1 || SKIP.has(root.tagName) || inChat(root)) return;
  root.querySelectorAll && [root, ...root.querySelectorAll('[data-i18n]')].forEach(el => {
    if (!el.dataset || !el.dataset.i18n) return;
    if (el.__html === undefined) el.__html = el.innerHTML;
    const val = LANG === 'en' ? null : (T['@' + el.dataset.i18n] || {})[LANG];
    el.innerHTML = val || el.__html;
  });
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, {
    acceptNode: n => n.nodeType === 1 ? (SKIP.has(n.tagName) || (n.id === 'chat') || n.classList.contains('notranslate') ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_SKIP) : NodeFilter.FILTER_ACCEPT
  });
  if (root.nodeType === 1) translateAttrs(root);
  root.querySelectorAll('[placeholder],[title],[aria-label]').forEach(el => { if (!inChat(el)) translateAttrs(el); });
  let n; while ((n = walker.nextNode())) translateText(n);
}

/* Ask the server for a language file (made by the AI the first time, then saved). */
async function loadLang(lang) {
  if (READY.has(lang)) return true;
  showLangBusy(`🌐 ${LANGS[lang]}: translating the website… (first time only)`);
  try {
    const r = await fetch('/api/i18n/' + encodeURIComponent(lang));
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || 'Translation not available');
    for (const [key, val] of Object.entries(j.strings || {})) { (T[key] = T[key] || {})[lang] = val; }
    READY.add(lang); showLangBusy(''); return true;
  } catch (e) {
    showLangBusy(`🌐 ${LANGS[lang]} isn't available yet: ${e.message}`, 7000); return false;
  }
}
function showLangBusy(text, hideAfter) {
  let el = document.getElementById('langBusy');
  if (!el) { el = document.createElement('div'); el.id = 'langBusy'; el.className = 'notranslate'; document.body.appendChild(el); }
  el.textContent = text; el.style.display = text ? 'block' : 'none';
  if (hideAfter) setTimeout(() => { if (el.textContent === text) el.style.display = 'none'; }, hideAfter);
}

let i18nObserver = null;
async function setLang(lang, remember) {
  if (!LANG_LIST[lang]) lang = 'en';
  if (!READY.has(lang) && !(await loadLang(lang))) return false;
  LANG = lang;
  if (remember) try { localStorage.setItem('sd_lang', lang); } catch (e) {}
  const html = document.documentElement;
  html.lang = lang; html.dir = RTL.has(lang) ? 'rtl' : 'ltr'; html.classList.toggle('nonlatin', NONLATIN.has(lang));
  translateTree(document.body);
  const btn = document.getElementById('langBtn'); if (btn) btn.textContent = '🌐 ' + lang.toUpperCase();
  document.querySelectorAll('[data-lang]').forEach(b => b.classList.toggle('on', b.dataset.lang === lang));
  if (!i18nObserver) {
    i18nObserver = new MutationObserver(muts => { if (LANG === 'en') return; for (const m of muts) m.addedNodes.forEach(translateTree); });
    i18nObserver.observe(document.body, {childList: true, subtree: true});
  }
  return true;
}

/* Searchable menu of every language. ⚡ = ready now; others are translated by the AI on first use. */
function buildLangMenu() {
  const menu = document.getElementById('langMenu'); if (!menu) return;
  const items = Object.entries(LANG_LIST).sort((x, y) => x[1][1].localeCompare(y[1][1]));
  menu.innerHTML = `<input id="langSearch" placeholder="Search ${items.length} languages…" autocomplete="off">
    <div class="lang-list">${items.map(([c, v]) => `<button data-lang="${c}" data-q="${(v[0] + ' ' + v[1] + ' ' + c).toLowerCase()}" class="${READY.has(c) ? 'ready' : (AI_TRANSLATE ? '' : 'na')}">
      <span>${v[0]}<small>${v[1]}</small></span><em>${READY.has(c) ? '⚡' : (AI_TRANSLATE ? 'AI' : '')}</em></button>`).join('')}</div>
    <p class="lang-note">${AI_TRANSLATE ? '⚡ ready now · AI = translated the first time someone picks it' : '⚡ ready now · other languages turn on once the AI key is added'}</p>`;
  document.getElementById('langSearch').oninput = e => {
    const q = e.target.value.trim().toLowerCase();
    menu.querySelectorAll('[data-lang]').forEach(b => b.style.display = !q || b.dataset.q.includes(q) ? '' : 'none');
  };
  document.querySelectorAll('[data-lang]').forEach(b => b.classList.toggle('on', b.dataset.lang === LANG));
}
async function refreshLangInfo() {
  try {
    const j = await (await fetch('/api/i18n')).json();
    AI_TRANSLATE = !!j.ai; (j.ready || []).forEach(c => READY.add(c));
  } catch (e) {}
  buildLangMenu();
}

/* First choice: what the visitor picked before. Otherwise the browser's language, otherwise the country's. */
function initialLang(countryCode) {
  let saved = null; try { saved = localStorage.getItem('sd_lang'); } catch (e) {}
  if (saved && LANG_LIST[saved]) return saved;
  for (const l of (navigator.languages || [navigator.language || 'en'])) {
    const full = String(l), code = full.slice(0, 2).toLowerCase();
    if (/^zh-(TW|HK|MO|Hant)/i.test(full)) return 'zh-TW';
    if (LANG_LIST[code] && READY.has(code)) return code;
  }
  const c = CC_LANG[countryCode];
  return c && READY.has(c) ? c : 'en';
}

/* When we learn the visitor's country, offer that country's language (once per language). */
function suggestLangFor(countryCode) {
  const l = CC_LANG[countryCode];
  if (!l || l === LANG || !(READY.has(l) || AI_TRANSLATE)) return;
  let saved = null, dismissed = '';
  try { saved = localStorage.getItem('sd_lang'); dismissed = localStorage.getItem('sd_lang_no') || ''; } catch (e) {}
  if (saved === l || dismissed.split(',').includes(l)) return;
  let box = document.getElementById('langToast');
  if (!box) { box = document.createElement('div'); box.id = 'langToast'; document.body.appendChild(box); }
  box.className = 'notranslate';
  const ask = (T.__ask && T.__ask[l]) || `View this website in ${LANG_LIST[l][1]}?`;
  const yes = (T.__yes && T.__yes[l]) || 'Yes';
  box.innerHTML = `<span>🌐 ${ask}</span><button class="btn primary sm" data-lang-yes="${l}">${yes} · ${LANGS[l]}</button><button class="btn ghost sm" data-lang-no="${l}">${LANGS[LANG]}</button>`;
  box.style.display = 'flex';
}
document.addEventListener('click', async e => {
  const y = e.target.closest('[data-lang-yes]'), n = e.target.closest('[data-lang-no]'), pick = e.target.closest('[data-lang]');
  if (y) { document.getElementById('langToast').style.display = 'none'; await setLang(y.dataset.langYes, true); buildLangMenu(); }
  if (n) { try { const d = localStorage.getItem('sd_lang_no') || ''; localStorage.setItem('sd_lang_no', d + ',' + n.dataset.langNo); } catch (err) {}
           document.getElementById('langToast').style.display = 'none'; }
  if (pick) { document.getElementById('langMenu').classList.remove('on'); await setLang(pick.dataset.lang, true); buildLangMenu(); }
  const btn = e.target.closest('#langBtn'); const menu = document.getElementById('langMenu');
  if (btn) { menu.classList.toggle('on'); const q = document.getElementById('langSearch'); if (q && menu.classList.contains('on')) setTimeout(() => q.focus(), 50); }
  else if (menu && !e.target.closest('#langMenu')) menu.classList.remove('on');
});
