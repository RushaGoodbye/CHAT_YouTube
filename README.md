# RG YouTube Control

Отдельное Windows-приложение для управления YouTube-каналами проекта РАША ГУДБАЙ.

## MVP 0.1

- Desktop OAuth через системный браузер и localhost callback.
- Токен хранится через Windows Credential Manager.
- Синхронизация последних видео.
- Аудит описаний, ссылок, глав и тегов.
- Редактор названия, описания и тегов.
- Автозамена старых ссылок проекта.
- Загрузка комментариев.
- Очередь ручных ответов.
- Автоответы только на безопасные служебные категории.
- Политические и спорные комментарии всегда отправляются на ручную проверку.
- Фоновая проверка комментариев каждые 10 минут.
- Ограничение автоматических ответов в сутки.

## Правильные ссылки

УСІ АКТИВНІ ПОСИЛАННЯ ПРОЄКТУ:
https://links.rginfoua.pp.ua/

УСІ ВАРІАНТИ ВІДПРАВИТИ ДОНЕЙТ:
https://donate.rginfoua.pp.ua/

## OAuth

1. Создать проект в Google Cloud.
2. Включить YouTube Data API v3.
3. Создать OAuth client типа Desktop app.
4. Скачать JSON.
5. В программе выбрать JSON и нажать «Подключить YouTube».
6. Подтвердить доступ в открывшемся браузере.

Используется scope:
https://www.googleapis.com/auth/youtube.force-ssl

## Сборка Windows

GitHub Actions собирает PyInstaller onedir и затем установщик Inno Setup.

Локальный исходный код не содержит OAuth client JSON, refresh tokens или других пользовательских секретов.

## v0.1.3

- Improved comment queue filters, editable safe auto-reply templates, comment ignore/restore actions, and daily quota counters.


## v0.7.45 · vidIQ-first SEO

- SEO in the Optimization tab now uses an explicit vidIQ handoff and a reviewed manual package editor.
- Select one video and open vidIQ: the video's YouTube URL is copied to the clipboard.
- Legacy local AI SEO generation and batch SEO actions are disabled in the GUI. Their code is retained for rollback, but not available for production use.
- vidIQ operates in its own service. The desktop app does not use ChatGPT plugin credentials or silently spend vidIQ credits.
- Titles, A/B options, description and tags must be checked against the real SRT before applying via the existing manual review flow.
- YouTube publication remains gated by the existing approval and backup safeguards.


### Updating to 0.7.45

Install the signed-by-checksum (SHA-256 verified) Inno Setup release into the existing
RG YouTube Control location; the user-data directory is preserved. Back up
`%LOCALAPPDATA%\\RGYouTubeControl` first. If a rollback is necessary,
use the previous installer and restore the saved user-data archive.

The vidIQ handoff is a browser link, not a direct API connection from the
Windows program. vidIQ output must still be reviewed against the SRT in
the package editor before any manual YouTube metadata action.

## 0.7.47 · Редакторський контроль джерела SEO

- Старі локальні SEO-пакети не видаляються, але позначаються як непідтверджені.
- У вкладці «Оптимізація» є фільтр «Старі SEO-пакети».
- Редактор показує походження пакета: старий, vidIQ (перенесено вручну), ручний/SRT.
- Щоб позначити повний SEO-пакет «Готово», потрібно вибрати реальне походження і особисто підтвердити перевірку назви, опису, тегів та A/B за SRT.
- Старі статуси ready/editor_approved/safe більше не обходять нові вимоги.
- Заплановані повні SEO-пакети також потребують підтвердженого джерела.
- Безпечні виправлення лише метаданих продовжують працювати без A/B.
- Ніякої автоматичної публікації чи запитів до vidIQ у цьому випуску.
