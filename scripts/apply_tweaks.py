#!/usr/bin/env python3
"""KKNX builder: твики производительности. Запуск: apply_tweaks.py <корень ядра>

Каждый твик включается и выключается отдельным полем workflow (значения приходят через переменные окружения).
Принцип отбора: только то, что не режет энергосбережение (никакого governor performance, никаких
фиксированных частот и отключения сна CPU). CPU/GPU-частоты, напряжения и таблицы шины скрипт не трогает.

Переменные окружения (значение по умолчанию = то, что выставляет workflow):

  IO_SCHED      cfq | deadline | keep      планировщик I/O: собрать и сделать планировщиком по умолчанию (keep = noop, как было)
  DEFAULT_GOV   schedutil | keep           governor по умолчанию (keep = performance, как в defconfig)
  CPU_BOOST     true | false               драйвер cpu_boost: короткий подъём частоты при касании экрана
  ZRAM_COMP     lz4 | zstd | lzo | keep    алгоритм сжатия zram по умолчанию (keep = как после порта LOLZ)
  NET_CC        bbr | keep                 TCP BBR по умолчанию (+ fq как qdisc по умолчанию через runtime)
  LMK           kernel | psi               psi = PSI вместо встроенного LMK (под lmkd; зависит от прошивки)
  CC_OPT        inline | keep              inline = убрать -inline-threshold=1 / -unroll-threshold=1 (штатные пороги clang)
  SPF           true | false               Speculative Page Fault (в defconfig автора выключен)
  RUNTIME_TUNE  io,vm,sched,boost | ""     группы значений в init.kknx.rc (пусто = файла нет, кроме NET_CC=bbr: одна строка про fq)

Что делает скрипт:
  1. правит исходники (Makefile для CC_OPT, zram_drv.c и lib/zstd/Makefile для ZRAM_COMP);
  2. пишет в $TWEAKS_OUT (по умолчанию каталог выше ядра):
       tweaks.fragment  строки .config для merge_config.sh
       tweaks.need      опции, которые обязаны остаться в .config после olddefconfig
       tweaks.markers   строки, которые должны найтись в готовом образе (verify_image.py)
       tweaks-info.txt  что именно включено (попадает в build-info.txt)
       init.kknx.rc     runtime-значения (если RUNTIME_TUNE не пуст или нужен fq для BBR)

Строгий и идемпотентный: если ожидаемого места в исходниках нет, падает (дерево изменилось, нужна проверка).
"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
OUT = Path(os.environ.get("TWEAKS_OUT") or ROOT.parent).resolve()


def die(msg):
    print(f"[ОШИБКА] {msg}", file=sys.stderr)
    sys.exit(1)


def info(msg):
    print(f"[tweaks] {msg}")


def env_choice(name, default, allowed):
    v = (os.environ.get(name) or default).strip().lower()
    if v not in allowed:
        die(f"{name}={v!r}: допустимо {', '.join(allowed)}")
    return v


def env_bool(name, default):
    v = (os.environ.get(name) or default).strip().lower()
    if v not in ("true", "false", "1", "0", "yes", "no"):
        die(f"{name}={v!r}: ожидается true/false")
    return v in ("true", "1", "yes")


IO_SCHED = env_choice("IO_SCHED", "cfq", ("cfq", "deadline", "keep"))
DEFAULT_GOV = env_choice("DEFAULT_GOV", "schedutil", ("schedutil", "keep"))
CPU_BOOST = env_bool("CPU_BOOST", "true")
ZRAM_COMP = env_choice("ZRAM_COMP", "lz4", ("lz4", "zstd", "lzo", "keep"))
NET_CC = env_choice("NET_CC", "keep", ("bbr", "keep"))
LMK = env_choice("LMK", "kernel", ("kernel", "psi"))
CC_OPT = env_choice("CC_OPT", "keep", ("inline", "keep"))
SPF = env_bool("SPF", "false")

RT_ALL = ("io", "vm", "sched", "boost")
RT_RAW = os.environ.get("RUNTIME_TUNE", "io,vm,sched,boost")
RUNTIME = [g.strip().lower() for g in RT_RAW.split(",") if g.strip()]
for g in RUNTIME:
    if g not in RT_ALL:
        die(f"RUNTIME_TUNE: неизвестная группа {g!r}, допустимо: {', '.join(RT_ALL)}")

frag = []        # строки .config
need = []        # что обязано быть в .config после olddefconfig (точные строки)
markers = []     # что должно быть в образе
notes = []       # для build-info


def opt_on(name):
    frag.append(f"CONFIG_{name}=y")
    need.append(f"CONFIG_{name}=y")


def opt_off(name):
    frag.append(f"# CONFIG_{name} is not set")
    need.append(f"# CONFIG_{name} is not set")


# ======================================================================
#  Исходники
# ======================================================================
def patch_inline():
    """Makefile: для clang стоят -inline-threshold=1 / -inlinehint-threshold=1 / -unroll-threshold=1."""
    p = ROOT / "Makefile"
    s = p.read_text()
    lines = [
        "KBUILD_CFLAGS\t+= -mllvm -inline-threshold=1\n",
        "KBUILD_CFLAGS\t+= -mllvm -inlinehint-threshold=1\n",
        "KBUILD_CFLAGS   += -mllvm -unroll-threshold=1\n",
    ]
    block = "".join(lines)
    stub = "# KKNX tweaks: пороги inline/unroll не занижаются (штатные значения clang)\n"
    if stub in s:
        info("Makefile: пороги inline/unroll уже сняты")
        return
    if s.count(block) != 1:
        die("Makefile: не нашёл три строки с -inline-threshold=1 / -inlinehint-threshold=1 / -unroll-threshold=1 "
            "подряд (дерево изменилось)")
    p.write_text(s.replace(block, stub))
    info("Makefile: убраны -inline-threshold=1, -inlinehint-threshold=1, -unroll-threshold=1")


ZRAM_RE = re.compile(
    r'static const char \*default_compressor =\s*'
    r'(?:#if IS_ENABLED\(CONFIG_CRYPTO_ZSTD\)\s*"zstd";\s*#else\s*"lzo";\s*#endif\s*|"[a-z0-9]+";\s*)')


def patch_zram(alg):
    p = ROOT / "drivers/block/zram/zram_drv.c"
    s = p.read_text()
    want = f'static const char *default_compressor = "{alg}";\n'
    if want in s:
        info(f"zram_drv.c: компрессор по умолчанию уже {alg}")
        return
    m = list(ZRAM_RE.finditer(s))
    if len(m) != 1:
        die("zram_drv.c: не нашёл определение default_compressor (ни исходное, ни после порта LOLZ full)")
    p.write_text(s[:m[0].start()] + want + s[m[0].end():])
    info(f"zram_drv.c: компрессор по умолчанию {alg}")


def patch_zstd_makefile():
    """При встроенных compress+decompress lld падает на дублях символов в lib/zstd (то же исправление, что в apply_lolz_full.py)."""
    mk = ROOT / "lib/zstd/Makefile"
    m = mk.read_text()
    if "zstd_shared" in m:
        info("lib/zstd/Makefile: уже исправлен")
        return
    orig_tail = (
        "zstd_compress-y := fse_compress.o huf_compress.o compress.o \\\n"
        "\t\t   entropy_common.o fse_decompress.o zstd_common.o\n"
        "zstd_decompress-y := huf_decompress.o decompress.o \\\n"
        "\t\t     entropy_common.o fse_decompress.o zstd_common.o\n"
    )
    fixed_tail = (
        "ifeq ($(CONFIG_ZSTD_COMPRESS)$(CONFIG_ZSTD_DECOMPRESS),yy)\n"
        "# KKNX: оба встроены -> общие файлы линкуются один раз (иначе ld.lld: duplicate symbol)\n"
        "obj-y += zstd_shared.o\n"
        "zstd_shared-y := entropy_common.o fse_decompress.o zstd_common.o\n"
        "zstd_compress-y := fse_compress.o huf_compress.o compress.o\n"
        "zstd_decompress-y := huf_decompress.o decompress.o\n"
        "else\n" + orig_tail + "endif\n"
    )
    if m.count(orig_tail) != 1:
        die("lib/zstd/Makefile не такой, как ожидалось")
    mk.write_text(m.replace(orig_tail, fixed_tail))
    info("lib/zstd/Makefile: общие файлы zstd линкуются один раз")


# ======================================================================
#  Конфиг
# ======================================================================
def tweak_io():
    if IO_SCHED == "keep":
        return
    # CFQ_GROUP_IOSCHED нужен Android: blkio-группы (фон/передний план) получают вес только с ним
    for o in ("IOSCHED_CFQ", "CFQ_GROUP_IOSCHED", "IOSCHED_DEADLINE"):
        opt_on(o)
    for o in ("DEFAULT_CFQ", "DEFAULT_DEADLINE", "DEFAULT_NOOP"):
        (opt_on if o.endswith(IO_SCHED.upper()) else opt_off)(o)
    need.append(f'CONFIG_DEFAULT_IOSCHED="{IO_SCHED}"')
    markers.append("slice_idle")
    notes.append(f"io_sched: {IO_SCHED} (cfq+deadline собраны, CFQ_GROUP_IOSCHED)")


def tweak_gov():
    if DEFAULT_GOV == "keep":
        return
    opt_on("CPU_FREQ_DEFAULT_GOV_SCHEDUTIL")
    opt_off("CPU_FREQ_DEFAULT_GOV_PERFORMANCE")
    notes.append("default_gov: schedutil (вместо performance)")


def tweak_boost():
    if not CPU_BOOST:
        return
    opt_on("CPU_BOOST")
    markers.append("input_boost_freq")
    notes.append("cpu_boost: драйвер включён (значения: группа runtime 'boost')")


def tweak_net():
    if NET_CC == "keep":
        return
    for o in ("TCP_CONG_ADVANCED", "TCP_CONG_BBR", "DEFAULT_BBR", "NET_SCH_FQ"):
        opt_on(o)
    for o in ("DEFAULT_WESTWOOD", "DEFAULT_CUBIC", "DEFAULT_RENO"):
        opt_off(o)
    need.append('CONFIG_DEFAULT_TCP_CONG="bbr"')
    notes.append("net_cc: bbr; fq как qdisc по умолчанию ставит init.kknx.rc "
                 "(в этом дереве нет compile-time выбора qdisc)")


def tweak_lmk():
    if LMK == "kernel":
        return
    opt_on("PSI")
    opt_off("PSI_DEFAULT_DISABLED")
    opt_off("ANDROID_LOW_MEMORY_KILLER")
    notes.append("lmk: psi (встроенный LMK убран, нужен lmkd с PSI)")


def tweak_spf():
    if not SPF:
        return
    opt_on("SPECULATIVE_PAGE_FAULT")
    notes.append("spf: Speculative Page Fault включён")


def tweak_zram():
    if ZRAM_COMP == "keep":
        return
    if ZRAM_COMP == "zstd":
        opt_on("CRYPTO_ZSTD")
        patch_zstd_makefile()
    elif ZRAM_COMP == "lz4":
        opt_on("CRYPTO_LZ4")
    patch_zram(ZRAM_COMP)
    notes.append(f"zram_comp: {ZRAM_COMP}")


# ======================================================================
#  Runtime: init.kknx.rc (читается init после vendor.post_boot.parsed=1, как init.lolz.rc)
# ======================================================================
# Частоты input boost: значения есть в таблицах cpufreq обоих кластеров (sdm439-olive.dtsi).
BOOST_FREQS = {0: 1305600, 1: 1305600, 2: 1305600, 3: 1305600, 4: 1171200, 5: 1171200, 6: 1171200, 7: 1171200}


def build_rc():
    groups = list(RUNTIME)
    lines = []

    if "io" in groups:
        lines.append("    # --- I/O: eMMC (mmcblk0) ---")
        if IO_SCHED != "keep":
            lines.append(f"    write /sys/block/mmcblk0/queue/scheduler {IO_SCHED}")
        if IO_SCHED == "cfq":
            # без простоя между запросами одного процесса: на flash он только задерживает диспетчеризацию
            lines.append("    write /sys/block/mmcblk0/queue/iosched/slice_idle 0")
        lines.append("    write /sys/block/mmcblk0/queue/read_ahead_kb 256")
        lines.append("    write /sys/block/mmcblk0/queue/add_random 0")

    if "vm" in groups:
        lines.append("    # --- память: значения под zram ---")
        lines.append("    write /proc/sys/vm/swappiness 100")
        lines.append("    write /proc/sys/vm/page-cluster 0")

    if "sched" in groups:
        lines.append("    # --- schedutil: не прыгать по частотам каждый тик, быстрее подниматься при I/O ---")
        for cpu in (0, 4):
            base = f"/sys/devices/system/cpu/cpu{cpu}/cpufreq/schedutil"
            lines.append(f"    write {base}/up_rate_limit_us 500")
            lines.append(f"    write {base}/down_rate_limit_us 20000")
            lines.append(f"    write {base}/iowait_boost_enable 1")

    if "boost" in groups and CPU_BOOST:
        lines.append("    # --- cpu_boost: короткий подъём минимальной частоты при касании (по умолчанию 40 мс, ставим 80) ---")
        pairs = " ".join(f"{c}:{f}" for c, f in BOOST_FREQS.items())
        lines.append(f'    write /sys/module/cpu_boost/parameters/input_boost_freq "{pairs}"')
        lines.append("    write /sys/module/cpu_boost/parameters/input_boost_ms 80")
        # без SCHED_WALT sched_set_boost() только возвращает -EINVAL и пишет ошибку в лог при каждом нажатии питания
        lines.append("    write /sys/module/cpu_boost/parameters/sched_boost_on_powerkey_input N")

    if NET_CC == "bbr":
        lines.append("    # --- сеть: BBR в 4.9 без внутреннего pacing требует fq ---")
        lines.append("    write /proc/sys/net/core/default_qdisc fq")

    if not lines:
        return None
    head = [
        "# KKNX runtime tweaks (генерируется сборщиком scripts/apply_tweaks.py).",
        "# Выполняется после vendor.post_boot.parsed=1, то есть после скриптов прошивки. Недоступный узел sysfs/proc",
        "# init просто пропускает. Проверить применённое: cat по тем же путям.",
        "",
        "on property:vendor.post_boot.parsed=1",
    ]
    return "\n".join(head + lines) + "\n"


def main():
    if not (ROOT / "Makefile").exists() or not (ROOT / "drivers").is_dir():
        die(f"{ROOT}: это не корень дерева ядра")

    if CC_OPT == "inline":
        patch_inline()
        notes.append("cc_opt: inline (штатные пороги inline/unroll clang)")
    tweak_zram()
    tweak_io()
    tweak_gov()
    tweak_boost()
    tweak_net()
    tweak_lmk()
    tweak_spf()

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "tweaks.fragment").write_text("\n".join(frag) + ("\n" if frag else ""))
    (OUT / "tweaks.need").write_text("\n".join(need) + ("\n" if need else ""))
    (OUT / "tweaks.markers").write_text("\n".join(markers) + ("\n" if markers else ""))

    rc = build_rc()
    rc_path = OUT / "init.kknx.rc"
    if rc:
        rc_path.write_text(rc)
        notes.append(f"runtime: init.kknx.rc, группы: {','.join(RUNTIME) or '-'}"
                     + (" + fq для BBR" if NET_CC == "bbr" else ""))
    elif rc_path.exists():
        rc_path.unlink()
    (OUT / "tweaks-info.txt").write_text("\n".join(notes) + ("\n" if notes else ""))

    info(f"в .config: {len(frag)} строк, проверяется после olddefconfig: {len(need)}, маркеров образа: {len(markers)}")
    for n in notes:
        info(n)
    if not notes:
        info("все твики выключены: сборка идентична прежней")


if __name__ == "__main__":
    main()
