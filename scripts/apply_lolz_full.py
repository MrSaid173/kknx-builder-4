#!/usr/bin/env python3
"""LOLZ-порт, режим full, исходники: zram по умолчанию сжимает zstd (как у LOLZ).

В этом дереве нет Kconfig ZRAM_DEF_COMP, алгоритм по умолчанию зашит в zram_drv.c ("lzo").
Правка условная: zstd только если CONFIG_CRYPTO_ZSTD включён, иначе остаётся lzo, чтобы zram не сломался.
Рантайм: алгоритм можно сменить до задания disksize: echo lz4 > /sys/block/zram0/comp_algorithm
Запуск: apply_lolz_full.py <корень ядра>. Идемпотентен.
"""
import pathlib
import sys

p = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".") / "drivers/block/zram/zram_drv.c"
s = p.read_text()
old = 'static const char *default_compressor = "lzo";\n'
new = ('static const char *default_compressor =\n'
       '#if IS_ENABLED(CONFIG_CRYPTO_ZSTD)\n'
       '\t"zstd";\n'
       '#else\n'
       '\t"lzo";\n'
       '#endif\n')
if new in s:
    print("[lolz-full] zram_drv.c: уже")
elif s.count(old) == 1:
    p.write_text(s.replace(old, new))
    print("[lolz-full] zram_drv.c: компрессор по умолчанию zstd (если CRYPTO_ZSTD)")
else:
    print("[ОШИБКА] zram_drv.c: не нашёл строку default_compressor", file=sys.stderr)
    sys.exit(1)


# --- lib/zstd: дубли символов при встроенных compress + decompress ---
# В этом дереве (zstd в стиле 4.14) общие файлы входят в ОБА составных объекта. Когда compress и decompress
# встроены (=y, так делает CRYPTO_ZSTD=y), lld при сборке lib/zstd/built-in.o падает: duplicate symbol.
# Решение: в этом случае общие файлы собираются один раз (zstd_shared.o). Для =m остаётся как было.
mk = p.parents[3] / "lib/zstd/Makefile"
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
m = mk.read_text()
if "zstd_shared" in m:
    print("[lolz-full] lib/zstd/Makefile: уже")
elif m.count(orig_tail) == 1:
    mk.write_text(m.replace(orig_tail, fixed_tail))
    print("[lolz-full] lib/zstd/Makefile: общие файлы zstd линкуются один раз")
else:
    print("[ОШИБКА] lib/zstd/Makefile не такой, как ожидалось", file=sys.stderr)
    sys.exit(1)
       
