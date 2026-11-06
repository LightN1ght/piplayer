# Компоненты и upstream-материалы

Состав, версии, исходные URL и обнаруженные лицензии записаны Buildroot в manifest.csv и host-manifest.csv. Host-пакеты нужны для сборки, target-пакеты входят в создаваемую систему; эти списки не следует смешивать.

`dist/upstream-sources-and-licenses.tar` содержит результат Buildroot legal-info, архив самой Buildroot 2025.02.19 и README поставщика toolchain. Это дополнительные материалы на компьютере, **не образ для microSD**; их размер не относится к ограничению 512 MB.

Исходный отчёт legal-info сохранён без правки. Он предупреждает, что Buildroot source не был автоматически сохранён (добавлен отдельным архивом) и что пакет внешнего Bootlin toolchain не определяет LICENSE_FILES. Поэтому manifest помечает лицензию toolchain как unknown; не выдавать генерацию legal-info за доказательство полноты всех лицензионных материалов.

Bootlin README указывает версии gcc 13.3.0, binutils 2.41, gdb 14.2 и musl 1.2.5 и официальные каталоги [исходников](https://toolchains.bootlin.com/downloads/releases/sources/) и [текстов лицензий](https://toolchains.bootlin.com/downloads/releases/licenses/). Эти сведения и README сохранены в upstream-extra. Toolchain tarball в legal-info — поставка внешнего toolchain; наличие этого файла само по себе не означает наличие всех его исходников и лицензий.

В `vendor/hls.LICENSE` сохранена лицензия hls.js; файл также устанавливается в образ. Наш архив `piplayer-source.tar.gz` содержит проектную конфигурацию, скрипты, UI и документацию, без приватных ключей/паролей и build cache. Для воспроизведения нужны публичные upstream-пакеты; build.sh фиксирует версии и проверяет хеши загрузок.
