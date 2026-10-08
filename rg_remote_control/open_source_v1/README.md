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

## Norfair и движение на реальных кадрах (следующий тест)

- Norfair 2.3.0 установлен на F: в отдельную среду. Synthetic API safety PASS, archived 886_5 two-hit shadow CONSISTENT. Смещение между оригинальными двумя боксами 0,5 px: это **не** достаточный тест движения.
- Добавлен `norfair_real_motion_8865_v1.py` и синтетическая проверка движения на кадрах `norfair_real_motion_synthetic.py`.
- Одноразовый вход: `../bootstrap_auto_edit_norfair_real_frames_8865_v1.ps1`. Он устанавливает `opencv-python==4.11.0.86` только в **отдельный Norfair venv** и перед видео запускает synthetic test.
- Тест читается из исходного `\\Desktop-v7gg0en\record\886.mp4`. Начальная отметка и bbox - из архивного файла детектора, не из предположений. FFmpeg извлекает на F: до 25 JPEG кадров, а затем временные кадры удаляются.
- Результат `F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_shadow\norfair_886_5_real_motion_v1.json`. Для него `production_approval=NOT_GRANTED` независимо от числа совпавших кадров: OpenCV template-matching - не независимый детектор сигареты. Наибольшее полезное значение - измерить пропуски, дрейф и проверить работу трекера без исходного монтажа.
- Перед SAM 2: официальный репозиторий рекомендует WSL на Windows и отдельный PyTorch/CUDA runtime. Нельзя устанавливать его внутрь стабильной среды обработки.

## 2026-10-08: Norfair real pilot and SAM2 readiness

Real Windows shadow run on 886_5 passed: 15/15 sampled template frames,
0 unmatched, ~1 px max estimated displacement and one Norfair ID.
This is **not** independently verified cigarette segmentation or moving
cigarette coverage. Production must stay on the verified existing blur.

SAM2 read-only preflight on AlexPC: RTX 4080, 16376 MB total, 7125 MB free VRAM,
F: 675.94 GB free, WSL executable present but no registered WSL distribution,
WSL CUDA/torch not tested. SAM2 not installed. Defer full SAM2 until an isolated
environment is justified; do not change production CUDA or ask to install WSL
during an unrelated Auto Edit run.

Next: `norfair_motion_challenge_v1.py` with deterministic ground truth for
slow/fast motion, temporary occlusion, and an identical-looking distractor.
Wrapper `../bootstrap_auto_edit_norfair_motion_challenge_v1.ps1` uses the
existing F: Norfair+OpenCV environment without pip installs or video access.
Output JSON in `F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_shadow`.
Even perfect synthetic tracking is **not** authorization to replace cigarette blur.
Any bad match or false positive is recorded instead of being silently accepted.

## 2026-10-08: Norfair challenging-motion findings and safety gate V2

Actual Windows synthetic benchmark provided by the user:

| Scenario | Visible matched | Missed | False positive | Outcome |
| --- | ---: | ---: | ---: | --- |
| Slow motion | 24 / 24 | 0 | 0 | PASS |
| Fast motion | 24 / 24 | 0 | 0 | PASS |
| Temporary occlusion | 11 / 20 | 9 | 0 | NEEDS REVIEW |
| Identical-looking distractor | 11 / 11 | 0 | 13 | BLOCK PRODUCTION |

The reported `false_matches_when_absent=13` is unacceptable for mandatory
localized cigarette blur. It shows that Norfair continuity and static appearance
matching cannot safely verify identity after a cigarette disappears.
Those experimental output boxes are NEVER integrated into a production XML.

Added `norfair_motion_safety_gate_v2.py`:
- uses a known-seed appearance template to generate candidate observations and
  rejects high prediction error rather than silently attaching a new identity;
- abstains when no matching object is visible (rather than fabricating its
  position), then allows tentative reacquisition on a plausible trajectory;
- rejects the identical-looking distractor displaced by 25 pixels in the
  known synthetic benchmark; this is NOT robust to all distractor positions;
- `automatic_blur_release` and `production_approved` are ALWAYS false:
  appearance/motion evidence is not independent semantic cigarette evidence;
- tests are deterministic, isolated to F: `oss_shadow` and never read videos,
  change audio or XML, or install more packages.

Local development verification of the V2 gate against a parallel copy of the
four deterministic scenarios: slow=24/24 visible, fast=24/24 visible,
occlusion=20/20 visible plus 4 abstentions, distractor=11/11 visible plus
13 ambiguous abstentions, zero accepted false positives. **The exact GitHub
V2 script still requires the Windows pinned-run regression** before being
considered verified on AlexPC. Even after that, real annotated videos and a
second independent cigarette detector are required before any production usage.

Read-only runner:
`../bootstrap_auto_edit_norfair_motion_safety_gate_v2.ps1`.

## 2026-10-08: V2 safety pass on AlexPC, next review real cigarette frames

User's Windows execution of the V2 synthetic safety gate reported:
- slow 24/24 correct, 0 abstentions, 0 known false positives;
- fast 24/24 correct, 0 abstentions, 0 known false positives;
- intermittent occlusion 20/20 visible frames correct and 4 abstentions;
- lookalike distractor 11/11 visible frames correct and 13 abstentions;
- `automatic_release=false` in EVERY case, `production_approved=false`.

This only validates synthetic geometry/continuity. To obtain material for
independent evaluation of a **real** cigarette in stream 886_5, use the
read-only review pack generator:
`../bootstrap_auto_edit_real_cigarette_review_8865_v1.ps1`.

This needs no new pip packages and uses the existing isolated Norfair +
OpenCV environment. It checks the archived two raw detections and verified
886_5 repair QA; extracts about 24 ORIGINAL frames near the evidence time
with the existing FFmpeg binary; then creates four JPEG contact sheets (6
frames each) with an overview and a *fixed ROI based on original bbox*.
The fixed ROI is a crop hint ONLY, NOT a dynamic detection or GT label.
Decoded temporary frames are removed. All output is only under
`F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_shadow\review_886_5\`.

A 1920x1080 synthetic frame-layout/source-immutability smoke is mandatory
before any real-stream decode. Production XML, audio, video and the existing
cigarette blur remain untouched. Do not assume all sheet crops contain a
visible cigarette; inspect them visually first. Next step is explicit
human-label or an independent detector benchmark against visible frames,
not production adoption.

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
