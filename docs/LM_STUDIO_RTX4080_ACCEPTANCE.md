# RG YouTube Control — LM Studio, RTX 4080 (локально, без Ollama)

## Безопасность
- Провайдер по умолчанию: LM Studio, локально http://127.0.0.1:1234.
- RG YouTube Control обращается к OpenAI-совместимому /v1/chat/completions.
- Модуль src/rg_youtube_control/lm_studio_client.py разрешает только loopback, не использует HTTP-прокси. Внешний AI API исключён.
- На YouTube ничего не публикуется. Черновики и SRT остаются на AlexPC.
- Режим Ollama предусмотрен только как явно включаемая совместимость RG_LOCAL_AI_PROVIDER=ollama. Для нормальной работы его не использовать.
- Не разрешать LM Studio обслуживать LAN, CORS, удалённые MCP.

## Установка
1. Загрузить LM Studio для Windows: https://lmstudio.ai/download. Запустить один раз.
2. В Discover загрузить одну модель. Первый кандидат — google/gemma-3-12b, GGUF Q4. Второй — qwen/qwen3-14b, GGUF Q4. Не загружать обе модели в память одновременно.
3. Загрузить модель с GPU offload Auto/Max и контекстом 8192 на первом тесте. 16384 — только после успешного короткого прогона и проверки VRAM.
4. В Developer включить Start server. Привязка только к 127.0.0.1, стандартный порт 1234.
5. При одной модели выбор автоматический. При нескольких указать её точный API ID в переменной среды RG_LMSTUDIO_MODEL.
6. Платные API и Ollama не требуются.

## Тестовый план
Команды выполнять на AlexPC из приватного QA checkout; RG_SEO_SOURCE указывает на checkout приложения, RG_TRANSCRIPTS_ROOT — на локальные SRT.

A. Unit CI без установленной модели: tests/test_lm_studio_client.py, общая Windows-сборка. Проверка loopback, JSON, таймаутов, моделей, отсутствия сервера.
B. Preflight без SRT: python scripts/rg_lmstudio_acceptance.py --stage preflight. Проверка модели и NVIDIA VRAM через nvidia-smi.
C. Synthetic smoke без SRT: python scripts/rg_lmstudio_acceptance.py --stage smoke. Один искусственный текст, украинский JSON. Ошибки HTTP 500/тайм-аут/пустой ответ блокируют дальнейшую работу.
D. Одно видео: python scripts/rg_lmstudio_acceptance.py --stage one. Проверка привязки реального SRT к video ID, качественных A/B, языка и проверяемых деталей. Публикации нет.
E. Десять видео: python scripts/rg_lmstudio_acceptance.py --stage ten. Последовательная обработка фиксированного корпуса из 10 SRT, журнал времени, VRAM, повторов, языка и неподтверждённых фактов. Черновики только на AlexPC.
F. Сравнение: выгрузить первую модель, загрузить вторую и повторить стадии D и E на тех же SRT. Сначала оценивать содержательную точность и украинский язык, потом время и VRAM.

## Блокирующие критерии
- Сервер недоступен, модель отсутствует, API не на localhost, HTTP 5xx, невалидный JSON.
- Несоответствие публичного названия и реального SRT.
- Неподтверждённые имена/цифры/факты, русизмы, повторы предложений, одинаковые A/B.
- Меньше восьми релевантных уникальных тегов, шаблонный текст.
- Даже 10/10 технических PASS не означает редакторское APPROVED и не разрешает публикацию на YouTube.

## GPU и конфиденциальность
- Точный объём VRAM на RTX 4080 проверить командой nvidia-smi: desktop и laptop различаются.
- Сначала Q4, одна 12B/14B модель, контекст 8192, без одновременных стримов/vMix/OBS/Topaz/RG Auto Edit.
- Записывать VRAM, время, ошибки, качество SEO; не повышать контекст наугад.
- GitHub логирует только ID видео, результаты проверок и счётчики. Сами SRT и черновики хранятся исключительно на AlexPC в C:\RG_YT_AGENT_RUNNER\SEO_REVIEW.

## Код
- src/rg_youtube_control/lm_studio_client.py
- src/rg_youtube_control/free_tools.py
- tests/test_lm_studio_client.py
- QA: RushaGoodbye/RG_YouTube_Agent/scripts/rg_lmstudio_acceptance.py
- Документация: https://lmstudio.ai/docs/developer/openai-compat
