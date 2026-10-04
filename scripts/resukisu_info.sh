#!/usr/bin/env bash
# Версия и UAPI ReSukiSU из скачанных исходников. Запуск: resukisu_info.sh <каталог ReSukiSU>
# Печатает две строки: "version=<код версии ядра или ?>" и "uapi=<число или ?>".
# Версия считается так же, как в kernel/Kbuild: <база> + число коммитов + <смещение> (читаем формулу оттуда).
# UAPI: KERNEL_SU_UAPI_VERSION в uapi/supercall.h (в старых версиях файла нет -> "?").
set -uo pipefail
d="${1:-KernelSU}"
ver="?"; uapi="?"

if [ -f "$d/kernel/Kbuild" ]; then
  f="$(grep -m1 -E 'expr[[:space:]]+[0-9]+[[:space:]]*\+[[:space:]]*\$\(KSU_LOCAL_VERSION\)[[:space:]]*\+[[:space:]]*[0-9]+' "$d/kernel/Kbuild" || true)"
  base="$(echo "$f" | sed -nE 's/.*expr[[:space:]]+([0-9]+)[[:space:]]*\+.*/\1/p')"
  off="$(echo "$f"  | sed -nE 's/.*KSU_LOCAL_VERSION\)[[:space:]]*\+[[:space:]]*([0-9]+).*/\1/p')"
  cnt="$(git -C "$d" rev-list --count HEAD 2>/dev/null || true)"
  if [ -n "$base" ] && [ -n "$off" ] && [ -n "$cnt" ]; then ver=$((base + cnt + off)); fi
fi
if [ -f "$d/uapi/supercall.h" ]; then
  u="$(sed -nE 's/.*KERNEL_SU_UAPI_VERSION[[:space:]]*=[[:space:]]*([0-9]+).*/\1/p' "$d/uapi/supercall.h" | head -1)"
  [ -n "$u" ] && uapi="$u"
fi
echo "version=$ver"
echo "uapi=$uapi"
