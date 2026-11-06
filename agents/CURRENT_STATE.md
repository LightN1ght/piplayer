# PiPlayer: точка продолжения

Обновлено 6 ноября 2026. Дедлайн: **16:00 МСК**. Обязательный сценарий принят на физической Pi; расширение Ethernet и прямого HLS проходит отдельную приёмку.

## Текущая работа

- Репозиторий [LightN1ght/piplayer](https://github.com/LightN1ght/piplayer), private. Базовая ветка `main`, рабочая `codex/ethernet-modes`. Новые изменения опубликованы: [PR #1](https://github.com/LightN1ght/piplayer/pull/1); main сохраняет базовую версию.
- Окончательный новый raw собран из исходников: **470810624 байта**, SHA256 `a111a19f1347ed81cf75625a5b08aae4ef1b4f7d01e9cb9833362152505e00cb`. Сборка `.build/hls-build.log` / `.build/build.log`; проверка разметки и kernel/DTB PASS. Чистая VM этого хеша прошла обычный, двухсетевой и прямой HLS smoke.
- Все **17 хостовых тестов PASS**, 54.225с, `.build/hls-host-tests.log`. Включают настоящий HTTP/FFmpeg-клиент, замену ролика, AAC, отказ неподходящему GOP/битрейту и восстановление publisher.
- Промежуточный Ethernet-only raw `1f2c346c…` прошёл двухсетевой и обычный smoke в чистой ARM VM. IAB подтвердил video → still → video. Эти сценарии повторно прошли и на окончательном HLS-образе a111a19f.

## Адреса и функции

- Браузер: `http://192.168.50.1:8080/`.
- Внешний HLS-клиент: `http://192.168.50.1:8080/stream.m3u8`. Одна общая трансляция, один активный ролик; служебный m3u8 необходим протоколу. Программа организатора неизвестна.
- SFTP: `player`, порт22, `/data/incoming/video.part` → `video.ready.mp4` после завершения передачи. Файлы не загружать прямо в current.mp4.
- MP4/H.264/yuv420p + AAC либо без аудио; GOP до4с, выбранные пакеты до6Мбит/с. Подготовка на компьютере `scripts/prepare-video.sh`. При свободном HLS tmpfs менее40MiB готовый файл ожидает; повторная загрузка не нужна.
- Отдельный `/etc/player/player.conf`: `INTERFACE_MODES=0` по умолчанию. При1 адреса `STILL_INTERFACES='eth0'` отдают картинку, остальные — видео. Выбор по локальному адресу назначения, не firewall по ingress. Новые USB NIC подключать до загрузки.
- Полные инструкции: [QUICKSTART](../docs/QUICKSTART.md), [HLS](../docs/HLS.md), [ETHERNET](../docs/ETHERNET.md).

## Проверенная аппаратная база

Исходный raw SHA256 `8f4d68e889ba43e24a93ca73bdbd167ea482a1bc237b70ba23cbcc83a27903fc`, xz `3e3e7442f03ac7eee153cb31e78c2d18f6ffe71d60cd1f8f63ac69b4d4392a61`. Копия сохранена в `dist/baseline-2026-11-05/`.

Pi4B Rev1.2 загрузилась с USB32GB. SSH/SFTP, цикл HLS/AAC, reject/recovery, reboot, сохранение файла и SSH host key — PASS. Пользователь подтвердил Wi-Fi AP без Интернета, звук/fullscreen, замену своим роликом по SFTP с Android и минимум60с просмотра ноутбук+телефон без остановок. Внутренний монитор901с/180проверок без перезапуска — PASS. Холодный старт без Ethernet и позднее подключение кабеля — PASS. Логи и точные границы: [VALIDATION](VALIDATION.md).

Физическая Pi сейчас остаётся на этой базовой версии. Новый прямой HLS и раздельные Ethernet-режимы на ней ещё не проверены. Физическую microSD512MB не тестировали; raw449MiB проходит программный предел480000000байт. Старую microSD Debian и EEPROM не меняли.

## Среда и правила продолжения

- Пользователь вне дома, Pi с собой, Ethernet-кабеля и второго адаптера нет. **Wi-Fi ноутбука инструментами не переключать**: теряется Интернет/Codex. Старый домашний IP192.168.0.126 не считать текущим.
- Buildroot2025.02.19 / Linux6.6.28-v8 / musl/BusyBox / OpenSSH / nginx / FFmpeg / hostapd/dnsmasq. Постоянная сборка `/home/light/.cache/piplayer-build`, staging `project`, output `output`; архивы `.build/downloads`.
- Сборка `PIPLAYER_SKIP_PACKAGE=1 JOBS=4 bash scripts/build.sh --configure`; перед упаковкой обязательно остановить проектные QEMU. Обновление исходного overlay требует повторного staging через build.sh.
- Основной тест: QEMU ARM virt/VirtIO с теми же Pi kernel/raw. Модель raspi4b тоже доступна, её USB NIC слишком медленна для плавного теста видео.
- Двухсетевой launcher: `--dual-network --reset`, SSH2224/HTTP8082=guest eth1; SSH2225/HTTP8083=guest eth0. QMP `.build/qemu-ethernet.qmp`; serial `.build/qemu-hls-final.log`. Запуск только после остановки прежней VM. Launcher защищает overlay flock и проверяет backing hash.
- `.local/`, приватные `dist/credentials.json`, `dist/admin_ed25519`, пользовательские видео не выводить и не коммитить. Source archive не включает их. Лицензия проекта отдельно не выбрана; ограничения upstream legal-info в THIRD_PARTY.
- Нерешённый частный случай Pixel6/Chrome не диагностирован (устройство стало недоступно). Успешный тест двух других клиентов не доказывает его исправление. Точная синхронизация кадров/максимальное число клиентов не заявляются.

## Итог программной приёмки и следующие шаги

- Новый xz:29121940байт, SHA256 `62dbe6c74f7167cbbb10bcedf006894b81a93d6a6825cc2b5fbd1a3377a94001`.
- `.build/smoke-interface-hls-final.log`: STILL SMOKE PASS; `.build/smoke-hls-regression-final.log`: SMOKE PASS с reboot; `.build/smoke-direct-hls-final.log`: DIRECT HLS SMOKE PASS. Один FFmpeg-клиент декодировал смену red→blue со звуком, старый URI сохранился. Runtime вручную не патчили.
- mpv8с с null audio/video — PASS, `.build/mpv-hls-final.log`. Это программное воспроизведение, не слышимость на физической Pi.
- `.build/smoke-buffer-hls-final.log`: BUFFER SMOKE PASS — при свободном tmpfs менее40MiB ready-файл ожидал, старый ролик оставался playing с прежним generation; после удаления тестового заполнителя файл активировался без повторной загрузки. Заполнитель удалён, VM оставлена с demo.
- Первый direct smoke дал timeout сравнения кадров; тест нормализован до320×180 и повторно прошёл после demo640×360. Первый журнал сохранён, точная исходная причина не установлена. Эта правка касается теста, target raw не менялся.

Git-индекс проверен:63файла, известных паролей/приватных ключей/token patterns/образов/личных видео нет. Ветка опубликована, PR открыт. Комплект и source archive обновлены без изменения raw; обе пары SHA256SUMS проверены, ссылки документов и состав source archive корректны. Следующий аппаратный шаг: по готовности пользователя обновить физическую Pi и проверить внешний HLS; два физических Ethernet требуют отдельного адаптера.

## Организация документации

Рабочие заметки, задачи и журнал проверок перенесены в `agents/`; пользовательские инструкции и архитектура находятся в `docs/`. Добавлена `docs/CONFIGURATION.md`. Скрипт `scripts/configure.py` уже готовит настройки для сборки; конфигурация работающей Pi меняется на устройстве. Runtime и raw-образ не изменялись.

README дополнен быстрым запуском от клонирования до записи и первого SFTP, с описанием индивидуальных учётных данных. Проверять ссылки и комплект; runtime и образ не менялись.

Проверка зависимостей scripts/build.sh выводит все отсутствующие команды одним списком; runtime и образ не менялись.
