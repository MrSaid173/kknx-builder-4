#!/usr/bin/env python3
"""Проверка собранного Image.gz-dtb.

1. GPU-таблица содержит честную запись (PLL = 2 x частота).
2. К образу приклеено ожидаемое число DTB (EXPECT_DTBS, по умолчанию 15) и ни в одном нет
   qcom,board-id: это признак режима DT overlay (CONFIG_BUILD_ARM64_DT_OVERLAY=y), с которым
   работает ваш dtbo.img. Если DTB 37 штук и с board-id, значит собрано не с тем defconfig,
   и загрузчик не найдёт подходящий DTB (телефон уходит в fastboot).
"""
import os, struct, subprocess, sys, tempfile, zlib

data = open(sys.argv[1], "rb").read()
o = zlib.decompressobj(31)
img = o.decompress(data)
rest = o.unused_data
fail = False

top = int(os.environ["GPU_FREQS"].split(",")[0]) * 1_000_000
pll = int(os.environ.get("GPU_TOP_PLL_MHZ") or 0) * 1_000_000 or 2 * top
pat = struct.pack("<QQ", top, pll)
pos = img.find(pat)
if pos < 0:
    print(f"[ОШИБКА] в Image нет записи GPU {top // 10**6} МГц с PLL {pll // 10**6} МГц")
    fail = True
else:
    print(f"[ok] GPU: запись {top // 10**6} МГц / PLL {pll // 10**6} МГц найдена (offset {pos:#x})")

dtbs, i = [], 0
while i + 8 <= len(rest) and rest[i:i + 4] == b"\xd0\x0d\xfe\xed":
    sz = struct.unpack(">I", rest[i + 4:i + 8])[0]
    dtbs.append(rest[i:i + sz])
    i += sz
expect = int(os.environ.get("EXPECT_DTBS", "15"))
with_board = sum(1 for d in dtbs if b"qcom,board-id" in d)
print(f"[info] DTB в образе: {len(dtbs)} (ожидается {expect}), из них с board-id: {with_board}")
if len(dtbs) != expect or with_board:
    print("[ОШИБКА] набор DTB не совпадает с режимом DT overlay. Проверьте defconfig (нужен kuro439_defconfig).")
    fail = True

# 3. Порт LOLZ (LOLZ_PORT = off | lite | full): проверяем DTB плат SDM439/SDA439 (msm-id 0x161 / 0x16b)
lolz = os.environ.get("LOLZ_PORT", "off")
FDTGET = os.environ.get("FDTGET", "fdtget")


def fdt(blob, node, prop, fmt=None):
    """fdtget: значение свойства из DTB в виде строки, None если узла/свойства нет."""
    with tempfile.NamedTemporaryFile(suffix=".dtb") as f:
        f.write(blob)
        f.flush()
        cmd = [FDTGET] + (["-t", fmt] if fmt else []) + [f.name, node, prop]
        r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


targets = []
for i, d in enumerate(dtbs):
    mid = fdt(d, "/", "qcom,msm-id", "x")
    if mid and mid.split()[0] in ("161", "16b"):
        targets.append((i, d))
if not targets:
    print("[ОШИБКА] в образе нет DTB SDM439/SDA439 (msm-id 0x161/0x16b)")
    fail = True
for i, d in targets:
    args = fdt(d, "/chosen", "bootargs")
    cma = fdt(d, "/reserved-memory/linux,cma", "size", "x")
    adsp = fdt(d, "/reserved-memory/adsp_region@0", "size", "x")
    dump = fdt(d, "/reserved-memory/mem_dump_region", "size", "x")
    if lolz == "off":
        ok = cma is None and dump is not None and args and "rcu_nocbs" not in args
    else:
        ok = (args == "quiet kpti=0 rcu_nocbs=0-7 noirqdebug" and cma == "0 4000000"
              and adsp == "0 1000000" and dump is None
              and b"qcom,mem-dump" not in d)
    print(f"[{'ok' if ok else 'ОШИБКА'}] DTB {i}: lolz={lolz} bootargs={args!r} cma={cma} adsp={adsp} mem_dump={'есть' if dump else 'нет'}")
    fail = fail or not ok

# 3a. Панели LOLZ (LOLZ_PANEL=true, второй аргумент = dtbo.img, собранный из исходников)
DTC = os.environ.get("DTC", "dtc")


def dts_of(blob):
    with tempfile.NamedTemporaryFile(suffix=".dtb") as f:
        f.write(blob)
        f.flush()
        r = subprocess.run([DTC, "-I", "dtb", "-O", "dts", "-q", f.name], capture_output=True, text=True)
    return r.stdout


def node_text(dts, name):
    """Текст узла с заданным именем (до парной закрывающей скобки), None если узла нет."""
    import re
    m = re.search(r"^\s*" + re.escape(name) + r"\s*\{", dts, re.M)
    if not m:
        return None
    i, depth = dts.index("{", m.start()), 0
    for j in range(i, len(dts)):
        depth += dts[j] == "{"
        depth -= dts[j] == "}"
        if depth == 0:
            return dts[m.start():j]
    return None


def panel_problems(dts):
    bad = []
    ili = node_text(dts, "qcom,mdss_dsi_ili9881h_hdplus_video_c3i")
    nvt = node_text(dts, "qcom,mdss_dsi_nvt36525b_hdplus_video_c3i")
    if ili is not None and "qcom,mdss-dsi-panel-framerate = <0x3c>;" not in ili:
        bad.append("ili9881h: частота кадров не 60 Гц")
    if nvt is not None:
        if "qcom,mdss-dsi-panel-framerate = <0x3c>;" not in nvt:
            bad.append("nvt36525b: частота кадров не 60 Гц")
        if "dynamic-fps" in nvt:
            bad.append("nvt36525b: остался dynamic fps")
        if "qcom,esd-check-enabled;" not in nvt:
            bad.append("nvt36525b: нет esd-check-enabled")
    return bad, (ili is not None or nvt is not None)


if lolz != "off" and os.environ.get("LOLZ_PANEL") == "true":
    if len(sys.argv) < 3:
        print("[ОШИБКА] LOLZ_PANEL=true, но не передан dtbo.img вторым аргументом")
        fail = True
    else:
        for i, d in targets:
            bad, found = panel_problems(dts_of(d))
            ok = found and not bad
            print(f"[{'ok' if ok else 'ОШИБКА'}] DTB {i}: панели LOLZ {'; '.join(bad) if bad else ('применены' if found else 'узлы панелей не найдены')}")
            fail = fail or not ok
        ob = open(sys.argv[2], "rb").read()
        magic, total, hdr, esz, cnt, eoff = struct.unpack(">6I", ob[:24])
        if magic != 0xD7B7AB1E or total != len(ob):
            print("[ОШИБКА] dtbo.img: неверный заголовок")
            fail = True
        n_checked = n_bad = 0
        for k in range(cnt):
            sz, off = struct.unpack(">2I", ob[eoff + k * esz: eoff + k * esz + 8])
            bad, found = panel_problems(dts_of(ob[off:off + sz]))
            n_checked += found
            if bad:
                n_bad += 1
                print(f"[ОШИБКА] dtbo запись {k}: " + "; ".join(bad))
        print(f"[{'ok' if n_bad == 0 and n_checked else 'ОШИБКА'}] dtbo.img: записей {cnt}, с панелями {n_checked}, с ошибками {n_bad}")
        fail = fail or n_bad > 0 or n_checked == 0

if lolz == "full":
    for marker, what in ((b"bpf_jit_enable", "BPF_JIT"), (b"zstd", "zstd"), (b"zram", "zram")):
        has = marker in img
        print(f"[{'ok' if has else 'ОШИБКА'}] образ содержит {what}")
        fail = fail or not has

# 4. Твики (TWEAK_MARKERS = файл со строками, которые обязаны быть в образе; пишет apply_tweaks.py)
mk = os.environ.get("TWEAK_MARKERS")
if mk and os.path.exists(mk):
    for marker in [m for m in open(mk).read().split() if m]:
        has = marker.encode() in img
        print(f"[{'ok' if has else 'ОШИБКА'}] образ содержит маркер твика {marker!r}")
        fail = fail or not has

ver = img.find(b"Linux version 4.9")
print("[info] версия:", img[ver:ver + 110].split(b"\n")[0].decode(errors="replace"))
sys.exit(1 if fail else 0)
