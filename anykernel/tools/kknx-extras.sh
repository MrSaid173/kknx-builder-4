# KKNX extras для AnyKernel3 (подключается из anykernel.sh, исполняется busybox ash в recovery).
#
# Что внутри (каждое действие повторяет отдельный zip/скрипт, который вы раньше прошивали руками):
#   kk_lolz_initrc   init.lolz.rc из LOLZ-V24 (настройка дисплея)
#   kk_tune_initrc   init.kknx.rc: runtime-значения твиков (I/O, память, schedutil, cpu_boost)
#   kk_livedisplay   Dummy-LiveDisplay-sysfs-HALcopy.zip
#   kk_fixlabels     fixlabels.sh fix (метки трёх каталогов /data)
# Флаги берутся из $home/kknx-flags.sh (его пишет workflow при упаковке).
#
# KK_ROOT: префикс путей. На устройстве пуст. Нужен только для автотестов установщика в песочнице.
R="${KK_ROOT:-}"

# --- chcon с запасными вариантами (в AK3-busybox нет chcon, берём из recovery) ---
# Обрабатывает ВСЕ переданные пути; возвращает 1, если хоть на одном метку поставить не удалось.
kk_chcon() {
  local ctx="$1" p rc=0; shift
  for p in "$@"; do
    if chcon "$ctx" "$p" 2>/dev/null \
      || toybox chcon "$ctx" "$p" 2>/dev/null \
      || /system/bin/toybox chcon "$ctx" "$p" 2>/dev/null \
      || /sbin/busybox chcon "$ctx" "$p" 2>/dev/null \
      || /system/bin/busybox chcon "$ctx" "$p" 2>/dev/null \
      || setfattr -n security.selinux -v "$ctx" "$p" 2>/dev/null; then
      :
    else
      ui_print "  ! не удалось поставить метку $ctx на $p"
      rc=1
    fi
  done
  return $rc
}

# --- показать метку каталога/файла (если recovery умеет ls -Z) ---
kk_showlabel() {
  local out
  out="$(toybox ls -ldZ "$1" 2>/dev/null | head -n1)"
  [ -n "$out" ] || out="$(/system/bin/toybox ls -ldZ "$1" 2>/dev/null | head -n1)"
  [ -n "$out" ] || out="$(ls -ldZ "$1" 2>/dev/null | head -n1)"
  ui_print "  ${out:-$1 (метку прочитать не удалось)}"
}

# --- LOLZ: init.lolz.rc ---
kk_lolz_initrc() {
  local src="$home/extras/lolz/init.lolz.rc" dst="$R/vendor/etc/init/init.lolz.rc"
  if [ ! -f "$src" ]; then ui_print "LOLZ init: нет файла в zip, пропуск"; return 0; fi
  if [ ! -d "$R/vendor/etc/init" ]; then ui_print "LOLZ init: нет /vendor/etc/init, пропуск"; return 0; fi
  cp -f "$src" "$dst"
  chmod 644 "$dst"
  chown 0:0 "$dst" 2>/dev/null
  kk_chcon u:object_r:vendor_configs_file:s0 "$dst"
  ui_print "LOLZ: init.lolz.rc установлен"
}

# --- KKNX: init.kknx.rc (runtime-твики; генерируется сборщиком, группы выбираются в workflow) ---
# KK_TUNE=1: ставим файл. KK_TUNE=0: убираем файл от прошлой прошивки, иначе старые значения остались бы навсегда.
kk_tune_initrc() {
  local src="$home/extras/kknx/init.kknx.rc" dst="$R/vendor/etc/init/init.kknx.rc"
  if [ "$KK_TUNE" != "1" ]; then
    [ -f "$dst" ] && { rm -f "$dst"; ui_print "KKNX tune: выключен, старый init.kknx.rc удалён"; }
    return 0
  fi
  if [ ! -f "$src" ]; then ui_print "KKNX tune: нет файла в zip, пропуск"; return 0; fi
  if [ ! -d "$R/vendor/etc/init" ]; then ui_print "KKNX tune: нет /vendor/etc/init, пропуск"; return 0; fi
  cp -f "$src" "$dst"
  chmod 644 "$dst"
  chown 0:0 "$dst" 2>/dev/null
  kk_chcon u:object_r:vendor_configs_file:s0 "$dst"
  ui_print "KKNX tune: init.kknx.rc установлен"
}

# --- Dummy LiveDisplay sysfs HAL (повтор updater-script из Dummy-LiveDisplay-sysfs-HALcopy.zip) ---
# Оригинал: если sysfs HAL в /vendor нет, прерывается ("патч не нужен"). Здесь вместо abort пропуск,
# потому что ядро к этому моменту уже прошито.
kk_livedisplay() {
  local src="$home/extras/livedisplay/vendor" v="$R/vendor"
  local hal="$v/bin/hw/vendor.lineage.livedisplay@2.0-service-sysfs" f d
  ui_print " "
  ui_print "Dummy LiveDisplay sysfs HAL..."
  if [ ! -d "$src" ]; then ui_print "  файлов нет в zip, пропуск"; return 0; fi
  if [ ! -e "$hal" ]; then
    ui_print "  sysfs HAL не найден в /vendor: патч не нужен, пропуск"
    return 0
  fi
  mount -o rw,remount "$v" 2>/dev/null
  ( cd "$src" && find . -type f ) | while read -r f; do
    f="${f#./}"
    d="$(dirname "$f")"
    mkdir -p "$v/$d"
    cp -f "$src/$f" "$v/$f" || ui_print "  ! не скопировался $f"
  done
  # права и метки: service как в updater-script (uid 0, gid 2000, 0755), остальное как обычные файлы /vendor
  chown 0:2000 "$hal" 2>/dev/null; chmod 755 "$hal"
  kk_chcon u:object_r:hal_lineage_livedisplay_sysfs_exec:s0 "$hal"
  for f in "$v/lib64/vendor.lineage.livedisplay@2.0.so" "$v"/lib/modules/rdbg.ko "$v"/lib/modules/efivarfs.ko; do
    [ -e "$f" ] || continue
    chown 0:0 "$f" 2>/dev/null; chmod 644 "$f"
    kk_chcon u:object_r:vendor_file:s0 "$f"
  done
  ui_print "  LiveDisplay: файлы установлены"
}

# --- fixlabels.sh fix: метки ТОЛЬКО трёх каталогов (не рекурсивно), содержимое не трогается ---
# Должен идти ПОСЛЕДНИМ: всё, что меняет /data или метки в recovery, уже сделано.
kk_fixlabels() {
  local D1="$R/data/data" D2="$R/data/user_de/0" D3="$R/data/misc/profiles/cur/0" d
  ui_print " "
  ui_print "FixLabels: метки каталогов /data..."
  if ! mountpoint -q "$R/data" 2>/dev/null; then
    ui_print "  /data не смонтирован, пропуск"
    return 0
  fi
  # /data мог быть смонтирован только что: даём до 5 секунд, чтобы каталоги появились
  local try=0
  while [ "$try" -lt 5 ]; do
    [ -d "$D1" ] && [ -d "$D2" ] && [ -d "$D3" ] && break
    try=$((try + 1)); sleep "${KK_WAIT:-1}"
  done
  for d in "$D1" "$D2" "$D3"; do
    if [ ! -d "$d" ]; then
      ui_print "  нет $d: /data не расшифрован или другая структура, пропуск"
      return 0
    fi
  done
  ui_print "  до:"
  for d in "$D1" "$D2" "$D3"; do kk_showlabel "$d"; done
  kk_chcon u:object_r:system_data_file:s0 "$D1" "$D2"
  kk_chcon u:object_r:user_profile_root_file:s0 "$D3"
  ui_print "  после:"
  for d in "$D1" "$D2" "$D3"; do kk_showlabel "$d"; done
}

# --- всё, что идёт ПОСЛЕ прошивки boot/dtbo, строго в этом порядке ---
# 0) sync: boot/dtbo и чистка *.ko дошли до диска, прежде чем трогать остальное
# 1) LiveDisplay: после чистки /vendor/lib/modules/*.ko (иначе rm удалил бы rdbg.ko и efivarfs.ko)
# 2) FixLabels: ПОСЛЕДНИМ, после sync: метки ставятся на состояние, в которое всё уже приведено
kk_post_install() {
  sync
  if [ "$KK_LIVEDISPLAY" = "1" ]; then kk_livedisplay; sync; fi
  if [ "$KK_FIXLABELS" = "1" ]; then kk_fixlabels; sync; fi
  return 0
}
