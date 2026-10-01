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
