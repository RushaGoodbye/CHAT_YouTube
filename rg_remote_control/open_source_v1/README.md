# RG Auto Edit Studio - Open Source Integration V1

Дата аудита: 2026-10-08
Контур: `auto_edit`
Каталог: [catalog.json](catalog.json)

## Принцип внедрения

Не менять рабочий RG Auto Edit Studio без независимых GOLDEN-тестов. Python/Rust
зависимости, NVIDIA/CUDA, пакеты моделей и лицензии проверять раздельно.
Лицензия кода НЕ автоматически распространяется на веса модели.

Поддерживаемые состояния:

- `SHADOW_ADAPTER_COMMITTED`: адаптер есть в репозитории; в production не включён.
- `EVALUATE_ISOLATED`/`BENCHMARK_ONLY`: только отдельный runtime.
- `RESEARCH_ONLY`: требует проверки результатов и лицензии.
- `KEEP_EXISTING`: текущий проверенный механизм не менять.
- `DO_NOT_INTEGRATE_FOR_MONETIZED_PRODUCTION`: запрет для рабочего приложения.

## Приоритеты

1. **Cigarette blur:** SAM 2 (Apache-2.0) + Norfair (BSD-3-Clause) + GroundingDINO (Apache-2.0)
   как независимая экспериментальная ветка. В первую очередь измерить tracking
   маленьких объектов, пропуски и способность отслеживать сигарету на движущейся
   руке. Исходный YOLOWorld оставить в production пока не будет нового
   golden-подтверждения. Если нет подтверждённого трека - FAIL CLOSED.
2. **Границы сцен:** PySceneDetect 0.7.1 (BSD-3-Clause) как независимый advisory signal.
   Смена сцены != окончание разговора. При паузе ждать появления следующего
   собеседника справа или реплики ведущего после заглушки.
3. **Распознавание и цензура:** faster-whisper (MIT) и WhisperX (BSD-2-Clause)
   сравнивать только в копии рабочего аудиопайплайна. Не трогать исходную
   дорожку, не менять громкость и не ресемплировать файл источника.
4. **Надёжность и UI:** psutil (BSD-3) - диагностика; watchdog (Apache-2.0) - мониторинг CIFS только через PollingObserver; tenacity (Apache-2.0) - ограниченные повторы идемпотентных операций; pydantic (MIT) - схемы очередей; pyqtgraph (MIT) - быстрые графики внутри PySide6 без переворота меню.
5. **VAD/спикеры:** Silero VAD (MIT) и pyannote.audio (MIT code) не должны
   самостоятельно завершать диалог; условия лицензирования моделей отдельно.
6. **Premiere XML:** OpenTimelineIO + FCP7 adapter использовать только для
   независимого чтения/инспекции. Перезапись оригинального XML через адаптер
   запрещена: в матрице адаптера нет поддержки аудио/видеоэффектов.
7. **GPU/дизайн:** текущий FFmpeg и PySide6 сохранить, обновлять бинарники
   только после проверки CLI build flags и лицензий.

**Юридически значимый риск:** Ultralytics распространяется по AGPL-3.0 либо
отдельной Enterprise-лицензии. Текущий пакет используется в детекторе,
поэтому перед распространением/коммерческим развёртыванием необходимо
проверить соблюдение условий лицензии и лицензирования весов.
CoTracker преимущественно CC-BY-NC и не допускается в монетизированный production.

## Что технически уже подключено в репозитории

- `scene_suggest.py`: реальные вызовы API PySceneDetect 0.7.1, ограничение
  окна максимум 600 секунд, JSON с `SCENE_CHANGE_CANDIDATE` без автоматических
  монтажных решений. Пишет ТОЛЬКО в `F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_shadow`.
- `oss_audit.py`: только чтение версий пакетов, manifest и обязательных
  флагов blur. Не скачивает и не устанавливает ничего.
- `health_shadow.py`: psutil, только чтение загрузки CPU, ОЗУ, процессов и свободного места на F:/D:. Не останавливает процессы.
- `../bootstrap_auto_edit_oss_shadow_pilot_v1.ps1`: установщик двух OSS-пилотов в отдельное окружение на F:. Не меняет production runtime.
- `tests/test_oss_shadow_v1.py`: проверки fail-closed, защиты аудио,
  запрещённых путей для вывода и лицензионных ограничений.
- `catalog.json`: реестр репозиториев и план допуска в production.

**Это staged-код, а не изменение установленного на компьютере приложения.**
Установщик OSS-пилота подготовлен, но на AlexPC пока не запускался. Рабочий `venv` не менялся. Реальный Windows-smoke и GPU-smoke ещё не подтверждены.

## Status: real stream 886 integration checks

- 2026-10-08: PySceneDetect 0.7.1 / psutil 7.2.2 isolated F: environment installed (OSS_IMPORT_SMOKE=PASS).
- 2026-10-08: real 886 scene window 9554.0–9566.0s completed: SHADOW_PASS, SCENES=1, CANDIDATES=0. No video/XML/audio modification.
- Norfair 2.3.0 (BSD-3-Clause) adapter `norfair_saved_hits_8865.py` is committed and awaits Windows live test.
- `../bootstrap_auto_edit_norfair_8865_shadow_v1.ps1` installs Norfair in a SECOND isolated venv and runs a synthetic API safety test before reading existing 886_5 saved detections. Results go only into `oss_shadow/norfair_886_5_v1.json`. No render, model re-inference, Premiere/XML or audio modifications.
- Matching two detections is NOT proof of full-frame cigarette tracking, so production adoption remains disabled until multi-frame, occlusion, and frame-coverage tests pass.

## Как запускать независимые тесты

```powershell
python -m unittest discover -s rg_remote_control/open_source_v1/tests -v
```

Для реальной сцены понадобится отдельная среда (только когда будет одобрена
к установке). Пин проекта: `scenedetect==0.7.1`. Не устанавливать
напрямую в существующий RG Auto Edit Runtime. Изолированная среда должна
находиться на диске F:. В ней можно запустить:

```powershell
python rg_remote_control/open_source_v1/scene_suggest.py --video "\\Desktop-v7gg0en\record\886.mp4" --start-sec 9500 --duration-sec 120
```

Этот вызов лишь формирует отчёт о смене сцен для последующего сравнения
с главным детектором и не изменяет ни видео, ни XML.

## Когда можно включить модули в production

- реальные диалоги `886_2` и `886_5` не изменены;
- сигарета внутри `886_5` размыта объектно на всех подтверждённых интервалах;
- аудиодорожка не обработана;
- цензура и audio/video linkage у `901` прошли regression;
- длинный стрим >= 9 часов прошёл нагрузочный тест;
- XML в Premiere воспроизводится без потери фильтров/медиа;
- каждый новый компонент имеет очищенный лицензионный статус и тест rollback;
- интеграция имеет feature flag по умолчанию OFF.

## Первоисточники

- PySceneDetect https://github.com/Breakthrough/PySceneDetect
- PySceneDetect API https://www.scenedetect.com/docs/latest/api.html
- Norfair https://github.com/tryolabs/norfair
- SAM 2 https://github.com/facebookresearch/sam2
- GroundingDINO https://github.com/IDEA-Research/GroundingDINO
- Faster Whisper https://github.com/SYSTRAN/faster-whisper
- WhisperX https://github.com/m-bain/whisperX
- Silero VAD https://github.com/snakers4/silero-vad
- OpenTimelineIO FCP7 https://github.com/OpenTimelineIO/otio-fcp-adapter
- RF-DETR license https://github.com/roboflow/rf-detr
- Ultralytics https://www.ultralytics.com/license
- CoTracker https://github.com/facebookresearch/co-tracker
- FFmpeg https://github.com/FFmpeg/FFmpeg/blob/master/LICENSE.md
