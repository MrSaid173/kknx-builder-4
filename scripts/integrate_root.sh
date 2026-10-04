#!/usr/bin/env bash
# Root-часть для дерева kernel_xiaomi_sdm439 (1topaz). Запуск из корня дерева ядра.
#
#   ROOT_MODE=resukisu_susfs   ReSukiSU + SUSFS (порт 4.9) + (опц.) NoMount
#   ROOT_MODE=none             без root
#
# Версии (все необязательные; пусто = последний коммит ветки по умолчанию):
#   RESUKISU_REF   ReSukiSU/ReSukiSU           пусто/latest = последний релиз со страницы Releases (с APK менеджера)
#                                              beta = коммит бета-менеджера | head = последний коммит main | тег | ветка | SHA
#   SUSFS_REF      wxx9248/susfs4ksu           ветка | тег | SHA   (по умолчанию ветка kernel-4.9-v2)
#   NOMOUNT_REF    maxsteeel/nomount           ветка | тег | SHA
#
# Оригинальный KernelSU (tiann) больше не поддерживается: режима original_ksu нет.
set -euo pipefail

: "${ROOT_MODE:=resukisu_susfs}"
: "${WITH_NOMOUNT:=1}"
: "${RESUKISU_REF:=}"
: "${SUSFS_REF:=}"
: "${NOMOUNT_REF:=}"
: "${SUSFS_DEFAULT_BRANCH:=kernel-4.9-v2}"   # 4.9-порт SUSFS живёт в этой ветке, HEAD репозитория (master) другой
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RESUKISU_URL=https://github.com/ReSukiSU/ReSukiSU
SUSFS_URL=https://github.com/wxx9248/susfs4ksu
NOMOUNT_URL=https://github.com/maxsteeel/nomount

[ -f Makefile ] && [ -d fs ] || { echo "запускайте из корня дерева ядра"; exit 1; }

# fetch_at url sha dir [full]
#   full=1 -> вся история без блобов (нужна ReSukiSU: версия ядра считается как число коммитов, плюс git describe по тегам)
fetch_at() {
  rm -rf "$3"; mkdir -p "$3"
  git -C "$3" init -q
  git -C "$3" remote add origin "$1"
  if [ "${4:-0}" = "1" ]; then
    git -C "$3" fetch -q --filter=blob:none --tags origin '+refs/heads/*:refs/remotes/origin/*'
  elif ! git -C "$3" fetch -q --depth 1 origin "$2" 2>/dev/null; then
    git -C "$3" fetch -q origin '+refs/heads/*:refs/remotes/origin/*' --tags
  fi
  git -C "$3" checkout -q --detach "$2"
  echo "[+] $(basename "$3") @ $(git -C "$3" rev-parse --short=12 HEAD)"
}

case "$ROOT_MODE" in
  none)
    # drivers/Kconfig безусловно делает source "drivers/kernelsu/Kconfig": нужна заглушка.
    echo "[root] без root: заглушка KernelSU + удаление старых хуков (иначе линковка упадёт на ksu_*)"
    rm -rf KernelSU && mkdir -p KernelSU/kernel
    echo "# KernelSU disabled by builder" > KernelSU/kernel/Kconfig
    echo "# empty" > KernelSU/kernel/Makefile
    ln -sfn ../KernelSU/kernel drivers/kernelsu
    python3 "$HERE/strip_old_ksu_hooks.py" .
    ;;

  resukisu_susfs)
    [ -L drivers/kernelsu ] || { echo "нет symlink drivers/kernelsu: другое дерево?"; exit 1; }

    RS_SHA="$(bash "$HERE/resolve_resukisu.sh" "$RESUKISU_URL" "$RESUKISU_REF")"
    SF_SHA="$(bash "$HERE/resolve_ref.sh" "$SUSFS_URL" "${SUSFS_REF:-$SUSFS_DEFAULT_BRANCH}")"

    fetch_at "$RESUKISU_URL" "$RS_SHA" KernelSU 1
    [ -f drivers/kernelsu/Kbuild ] || { echo "drivers/kernelsu не указывает на ReSukiSU"; exit 1; }
    echo "[resukisu] коммитов в истории: $(git -C KernelSU rev-list --count HEAD)  тег: $(git -C KernelSU describe --abbrev=0 --tags 2>/dev/null || echo нет)"

    # ReSukiSU при CONFIG_SECCOMP=n (так в kuro439_defconfig): disable_seccomp() -> no-op
    python3 "$HERE/patch_resukisu_seccomp.py" KernelSU
    # ReSukiSU при CONFIG_KALLSYMS_ALL=n (так в kuro439_defconfig) требует нестатических символов SELinux
    python3 "$HERE/export_selinux_symbols.py" .
    # Старые ручные хуки в fs/ мешают SUSFS-патчу (у него свои inline-хуки)
    python3 "$HERE/strip_old_ksu_hooks.py" .

    fetch_at "$SUSFS_URL" "$SF_SHA" .susfs-src
    PATCH=.susfs-src/kernel_patches/50_add_susfs_in_kernel-4.9.patch
    [ -f "$PATCH" ] || { echo "[ОШИБКА] в этой версии SUSFS нет $PATCH. Для ядра 4.9 нужна ветка kernel-4.9-v2 (или её коммит/тег)"; exit 1; }
    cp .susfs-src/kernel_patches/fs/susfs.c fs/
    cp .susfs-src/kernel_patches/include/linux/susfs*.h include/linux/
    patch -p1 --no-backup-if-mismatch < "$PATCH"
    echo "[susfs] $(grep -m1 -E 'SUSFS_VERSION' include/linux/susfs.h 2>/dev/null || echo 'версия: см. include/linux/susfs.h')"
    rm -rf .susfs-src

    if [ "$WITH_NOMOUNT" = "1" ]; then
      NM_SHA="$(bash "$HERE/resolve_ref.sh" "$NOMOUNT_URL" "$NOMOUNT_REF")"
      fetch_at "$NOMOUNT_URL" "$NM_SHA" NoMount
      [ -d NoMount/kernel/src ] || { echo "[ОШИБКА] в этой версии NoMount нет kernel/src"; exit 1; }
      ln -sfn ../NoMount/kernel/src fs/nomount
      grep -q nomount fs/Makefile || printf '\nobj-$(CONFIG_NOMOUNT) += nomount/\n' >> fs/Makefile
      grep -q 'fs/nomount/Kconfig' fs/Kconfig || awk '/^endmenu/{last=NR} {l[NR]=$0}
        END{for(i=1;i<=NR;i++){if(i==last)print "source \"fs/nomount/Kconfig\""; print l[i]}}' \
        fs/Kconfig > fs/Kconfig.tmp && mv fs/Kconfig.tmp fs/Kconfig
    fi

    # итоговые версии: попадут в build-info.txt
    {
      echo "resukisu: $RS_SHA"
      echo "susfs: $SF_SHA"
      [ "$WITH_NOMOUNT" = "1" ] && echo "nomount: $NM_SHA"
    } > "${ROOT_INFO_FILE:-/dev/null}"

    # совместимость менеджера: версия ядра и UAPI берутся из скачанных исходников ReSukiSU
    eval "$(bash "$HERE/resukisu_info.sh" KernelSU | sed -E 's/^(version|uapi)=/RS_\1=/')"
    RS_TAG="$(git -C KernelSU describe --tags --exact-match HEAD 2>/dev/null || true)"
    case "$(echo "${RESUKISU_REF:-}" | tr 'A-Z' 'a-z' | xargs)" in
      ""|latest) RS_HOW="ядро собрано под последний релиз ${RS_TAG:-?}: ставьте APK этого релиза со страницы Releases (в имени файла версия $RS_version)" ;;
      beta)      RS_HOW="ядро собрано под бета-менеджер: плашка \"New beta version $RS_version\" в приложении" ;;
      *)         RS_HOW="менеджер нужен из той же версии/коммита, что и ядро (коммит ${RS_SHA:0:7}${RS_TAG:+, тег $RS_TAG})" ;;
    esac
    {
      echo "resukisu_version: $RS_version  uapi: $RS_uapi"
      echo "manager: нужен менеджер ReSukiSU с UAPI $RS_uapi (версия $RS_version); $RS_HOW"
    } >> "${ROOT_INFO_FILE:-/dev/null}"
    echo "[resukisu] версия ядра $RS_version, UAPI $RS_uapi"
    ;;

  original_ksu)
    echo "[ОШИБКА] original_ksu отключён: поддерживаются только resukisu_susfs и none"; exit 1;;
  *) echo "неизвестный ROOT_MODE=$ROOT_MODE"; exit 1;;
esac
echo "[root] готово (режим: $ROOT_MODE)"
