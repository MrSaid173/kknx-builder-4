#!/usr/bin/env bash
# Фиксы известных проблем дерева danya2271/kernel_xiaomi_sdm439 (1topaz). Запуск из корня ядра.
# Идемпотентен; падает, если ожидаемого места нет (дерево изменилось -> нужно перепроверить).
set -euo pipefail

# mm/Makefile: в дереве `obj-$(DEBUG_KERNEL) += debug.o` (опечатка: нет префикса CONFIG_).
# Условие должно совпадать с mm/internal.h и include/linux/mmdebug.h (там #ifdef CONFIG_DEBUG_KERNEL):
#   DEBUG_KERNEL=y  -> debug.o обязателен (иначе линковка падает на pageflag_names, dump_page и т. д.)
#   DEBUG_KERNEL=n  -> debug.o собирать нельзя (в заголовках static-заглушки, будет redefinition)
# Для kuro439_defconfig (DEBUG_KERNEL выключен) опечатка безвредна, для olive-stock_defconfig ломает линковку.
WANT='obj-$(CONFIG_DEBUG_KERNEL) += debug.o'
if grep -qxF "$WANT" mm/Makefile; then
  echo "[fix] mm/Makefile: уже исправлено"
elif grep -qE '^obj-(\$\(DEBUG_KERNEL\)|y)[[:space:]]*\+= debug\.o' mm/Makefile; then
  sed -i -E "s/^obj-(\\\$\\(DEBUG_KERNEL\\)|y)[[:space:]]*\\+= debug\\.o/${WANT//$/\\$}/" mm/Makefile
  grep -qxF "$WANT" mm/Makefile || { echo "[ОШИБКА] не удалось применить правку mm/Makefile" >&2; exit 1; }
  echo "[fix] mm/Makefile: debug.o зависит от CONFIG_DEBUG_KERNEL"
elif grep -qE '[[:space:]]debug\.o[[:space:]]' mm/Makefile; then
  echo "[fix] mm/Makefile: debug.o в общем obj-y (как в lolz), пропускаю"
else
  echo "[ОШИБКА] mm/Makefile: не нашёл строку с debug.o, проверьте дерево" >&2; exit 1
fi
grep -n 'debug\.o' mm/Makefile | head -2
