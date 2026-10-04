#!/usr/bin/env python3
"""LOLZ-порт, часть DT (режимы lite и full). Запуск: apply_lolz_port.py <корень ядра>

Правит исходники DTS так же, как отличаются DTB LOLZ-V24 и KKNX-800Mhz_v2 для SDM439/SDA439:

  1. chosen/bootargs            -> "quiet kpti=0 rcu_nocbs=0-7 noirqdebug"  (строка LOLZ-V24 как есть)
  2. adsp_region@0 size         -> 16 МБ (у KKNX 4 МБ)
  3. mem_dump_region (4 МБ)     -> linux,cma 64 МБ, linux,cma-default (как у LOLZ)
  4. узел mem_dump              -> удаляется (у LOLZ его нет; на него ссылался только dump_mem)

Не трогает: частоты CPU/GPU, напряжения CPR, шину, всё остальное.
Строго: если ожидаемое место в файле не найдено, скрипт падает (дерево изменилось, нужна проверка).
Идемпотентен: повторный запуск ничего не меняет.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
DTS = ROOT / "arch/arm64/boot/dts/qcom"
FILES = ["msm8937.dtsi", "msm8937-olive.dtsi"]

NEW_BOOTARGS = 'bootargs = "quiet kpti=0 rcu_nocbs=0-7 noirqdebug";'
CMA_NODE = (
    "\t\tlinux,cma {\n"
    '\t\t\tcompatible = "shared-dma-pool";\n'
    "\t\t\talloc-ranges = <0x0 0x0 0x0 0xffffffff>;\n"
    "\t\t\treusable;\n"
    "\t\t\talignment = <0x0 0x400000>;\n"
    "\t\t\tsize = <0x0 0x4000000>;\n"
    "\t\t\tlinux,cma-default;\n"
    "\t\t};\n"
)


def die(msg):
    print(f"[ОШИБКА] {msg}", file=sys.stderr)
    sys.exit(1)


def find_block(text, header_re, start=0):
    """Возвращает (начало_строки, конец_после_}; ) блока, у которого заголовок совпал с header_re."""
    m = re.compile(header_re, re.M).search(text, start)
    if not m:
        return None
    i = text.index("{", m.start())
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                end = text.index(";", j) + 1
                if text[end:end + 1] == "\n":
                    end += 1
                return m.start(), end
    die(f"не закрыта скобка блока {header_re}")


def patch(path):
    t = path.read_text()
    name = path.name
    log = []

    # 1) bootargs
    if NEW_BOOTARGS in t:
        log.append("bootargs: уже")
    else:
        t, n = re.subn(r'bootargs = "[^"]*";', NEW_BOOTARGS, t)
        if n != 1:
            die(f"{name}: ожидалось ровно одно bootargs, найдено {n}")
        log.append("bootargs: заменён")

    # 2) adsp_region size
    blk = find_block(t, r"^\t\tadsp_mem: adsp_region@0 \{")
    if not blk:
        die(f"{name}: нет adsp_mem: adsp_region@0")
    b = t[blk[0]:blk[1]]
    if "size = <0 0x1000000>;" in b:
        log.append("adsp: уже 16 МБ")
    else:
        if b.count("size = <0 0x400000>;") != 1:
            die(f"{name}: в adsp_region не нашёл size = <0 0x400000>;")
        t = t[:blk[0]] + b.replace("size = <0 0x400000>;", "size = <0 0x1000000>;") + t[blk[1]:]
        log.append("adsp: 4 МБ -> 16 МБ")

    # 3) mem_dump_region -> linux,cma
    if "linux,cma {" in t:
        log.append("cma: уже")
    else:
        blk = find_block(t, r"^\t\tdump_mem: mem_dump_region \{")
        if not blk:
            die(f"{name}: нет dump_mem: mem_dump_region")
        t = t[:blk[0]] + CMA_NODE + t[blk[1]:]
        log.append("cma: mem_dump_region -> linux,cma 64 МБ")

    # 4) узел mem_dump (внутри &soc, одна табуляция)
    blk = find_block(t, r"^\tmem_dump \{")
    if not blk:
        if "<&dump_mem>" in t:
            die(f"{name}: узла mem_dump нет, но ссылка на dump_mem осталась")
        log.append("mem_dump: уже удалён")
    else:
        t = t[:blk[0]] + t[blk[1]:]
        if "dump_mem" in t:
            die(f"{name}: после удаления mem_dump остались ссылки на dump_mem")
        log.append("mem_dump: удалён")

    path.write_text(t)
    print(f"[lolz-dt] {name}: " + "; ".join(log))


for f in FILES:
    p = DTS / f
    if not p.exists():
        die(f"нет {p}")
    patch(p)
