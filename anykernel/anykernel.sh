# AnyKernel3 Ramdisk Mod Script
# osm0sis @ xda-developers

## AnyKernel setup
# begin properties
properties() { '
wlan.type=BUILT-IN
do.devicecheck=1
do.modules=0
do.systemless=0
do.cleanup=1
do.cleanuponabort=0
device.name1=olive
device.name2=olivelite
device.name3=olivewood
device.name4=olives
device.name5=pine
device.name6=mi439
device.name7=Mi439
supported.versions=10 - 14
supported.patchlevels=
'; } # end properties

# shell variables
block=/dev/block/by-name/boot;
is_slot_device=0;
ramdisk_compression=auto;
patch_vbmeta_flag=0;


## AnyKernel methods (DO NOT CHANGE)
# import patching functions/variables - see for reference
. tools/ak3-core.sh;

# KKNX extras: флаги пишет workflow (LOLZ-порт, LiveDisplay, FixLabels)
KK_LOLZ=off; KK_LIVEDISPLAY=0; KK_FIXLABELS=0; KK_TUNE=0;
[ -f $home/kknx-flags.sh ] && . $home/kknx-flags.sh;
. $home/tools/kknx-extras.sh;
ui_print "LOLZ-порт: $KK_LOLZ | LiveDisplay: $KK_LIVEDISPLAY | FixLabels: $KK_FIXLABELS | Tune: $KK_TUNE";

# AnyKernel install
split_boot;

# dynamic partitions changes
if dd if=/dev/block/by-name/system bs=256k count=1|strings|grep mi439_dynpart > /dev/null; then
    ui_print "Dynamic Partitions Detected!!";
    patch_cmdline "dynamic_partitions" "dynamic_partitions=1";
    blockdev --setrw /dev/block/mapper/system;
    blockdev --setrw /dev/block/mapper/vendor;
else
    patch_cmdline "dynamic_partitions" "dynamic_partitions=0";
    ui_print "Normal Partitions Detected!!";
fi;

# always mount this partitions
mount -o rw,remount /system;
mount -o rw,remount /vendor;

# patching cmdline for oss/prebuilt cam
if [[ ! -z "$(find /vendor/lib64 /vendor/lib -name '*lib2d*')" ]]; then
    ui_print "Prebuilt CAM HAL Detected!!";
    patch_cmdline "oss.cam_hal" "oss.cam_hal=0";
else
    ui_print "OSS Camera HAL Detected!!";
    patch_cmdline "oss.cam_hal" "oss.cam_hal=1";
fi;

if mountpoint -q /data; then
  # Optimize F2FS extension list (@arter97)
  for list_path in $(find /sys/fs/f2fs* -name extension_list); do

    ui_print "F2FS: Optimizing Extension List..."

    hot_count="$(grep -n 'hot file extens' $list_path | cut -d':' -f1)"
    list_len="$(cat $list_path | wc -l)"
    cold_count="$((list_len - hot_count))"

    cold_list="$(head -n$((hot_count - 1)) $list_path | grep -v ':')"
    hot_list="$(tail -n$cold_count $list_path)"

    for ext in $cold_list; do
      [ ! -z $ext ] && echo "[c]!$ext" > $list_path
    done

    for ext in $hot_list; do
      [ ! -z $ext ] && echo "[h]!$ext" > $list_path
    done

    for ext in $(cat $home/f2fs-cold.list | grep -v '#'); do
      [ ! -z $ext ] && echo "[c]$ext" > $list_path
    done

    for ext in $(cat $home/f2fs-hot.list); do
      [ ! -z $ext ] && echo "[h]$ext" > $list_path
    done
  done
fi

# LOLZ-порт (lite/full): init.lolz.rc, как в установщике LOLZ
if [ "$KK_LOLZ" != "off" ]; then
  kk_lolz_initrc;
fi

# KKNX-твики: init.kknx.rc (или удаление старого, если в этой сборке твики выключены)
kk_tune_initrc;

rm -rf /vendor/etc/init/hw/init.qcom.test.rc
ui_print "Cleaning /system/lib/modules..."
ui_print "Cleaning /vendor/lib/modules..."
rm -rf /system/lib/modules/*.ko
rm -rf /vendor/lib/modules/*.ko
ui_print "Cleaned Successfully!!"

flash_boot;
flash_dtbo;

# Как если бы вы прошивали zip по отдельности, в таком порядке:
#   ядро -> LiveDisplay (после чистки *.ko, иначе rdbg.ko/efivarfs.ko были бы удалены) -> FixLabels (последним)
kk_post_install;

ui_print "Enjoy Using Kuroneko KERNEL, Have fun :)"

## end install

# shell variables
#block=vendor_boot;
#is_slot_device=1;
#ramdisk_compression=auto;
#patch_vbmeta_flag=auto;

# reset for vendor_boot patching
#reset_ak;


## AnyKernel vendor_boot install
#split_boot; # skip unpack/repack ramdisk since we don't need vendor_ramdisk access

#flash_boot;
## end vendor_boot install
