#!/usr/bin/env python3
"""LOLZ-порт, панели дисплея (опция lolz_panel). Запуск: apply_lolz_panel.py <корень ядра>

В исходниках KKNX разогнан сам экран. LOLZ-V24 держит те же две панели на штатных 60 Гц:

  dsi-panel-ili9881h-hdplus-video_c3i.dtsi   framerate 76 -> 60
  dsi-panel-nvt36525b-hdplus-video_c3i.dtsi  framerate 65 -> 60; убирается dynamic fps (30..65 Гц);
                                             h-sync-pulse 0 -> 1; включается ESD-контроль
                                             (esd-check-enabled + status-valid-params 1)

  sdm439-olive.dtsi                          DSI PLL ssc-frequency-hz 35500 -> 31500 (спектр. разброс под 60 Гц)

Правится исходник панели, поэтому и базовые DTB, и оверлеи (dtbo) получаются согласованными.
Не трогает ни частоты CPU/GPU, ни напряжения. Строгий (падает, если файл не такой, как ожидалось)
и идемпотентный.
"""
import pathlib
import re
import sys

DTS = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".") / "arch/arm64/boot/dts/qcom"


def die(msg):
    print(f"[ОШИБКА] {msg}", file=sys.stderr)
    sys.exit(1)


def sub_once(text, old, new, what, name):
    """old -> new ровно один раз; если уже new, ничего не делаем; иначе падаем."""
    if text.count(old) == 1:
        return text.replace(old, new), f"{what}: изменено"
    if text.count(new) >= 1 and old not in text:
        return text, f"{what}: уже"
    die(f"{name}: не нашёл ожидаемую строку для «{what}» ({old.strip()})")


def patch(fname, edits):
    p = DTS / fname
    if not p.exists():
        die(f"нет {p}")
    t = p.read_text()
    log = []
    for e in edits:
        t, msg = e(t, fname)
        log.append(msg)
    p.write_text(t)
    print(f"[lolz-panel] {fname}: " + "; ".join(log))


# --- ili9881h: только частота кадров ---
patch("dsi-panel-ili9881h-hdplus-video_c3i.dtsi", [
    lambda t, n: sub_once(t, "qcom,mdss-dsi-panel-framerate = <76>;",
                          "qcom,mdss-dsi-panel-framerate = <60>;", "framerate 76 -> 60", n),
])


# --- nvt36525b ---
def drop_dynamic_fps(t, n):
    block = ("\t\tqcom,mdss-dsi-min-refresh-rate = <30>;\n"
             "\t\tqcom,mdss-dsi-max-refresh-rate = <65>;\n"
             "\t\tqcom,mdss-dsi-pan-enable-dynamic-fps;\n")
    if t.count(block) == 1:
        return t.replace(block, ""), "dynamic fps 30..65 Гц: убран"
    if "qcom,mdss-dsi-pan-enable-dynamic-fps" not in t:
        return t, "dynamic fps: уже убран"
    die(f"{n}: блок dynamic fps не такой, как ожидалось")


def add_esd(t, n):
    if "qcom,esd-check-enabled;" in t:
        return t, "esd-check: уже"
    anchor = "\t\tqcom,mdss-dsi-panel-status-command = [06 01 00 01 05 00 01 0A];\n"
    if t.count(anchor) != 1:
        die(f"{n}: не нашёл panel-status-command для вставки esd-check-enabled")
    return t.replace(anchor, "\t\tqcom,esd-check-enabled;\n" + anchor), "esd-check-enabled: добавлен"


patch("dsi-panel-nvt36525b-hdplus-video_c3i.dtsi", [
    lambda t, n: sub_once(t, "qcom,mdss-dsi-panel-framerate = <65>;",
                          "qcom,mdss-dsi-panel-framerate = <60>;", "framerate 65 -> 60", n),
    drop_dynamic_fps,
    lambda t, n: sub_once(t, "qcom,mdss-dsi-h-sync-pulse = <0>;",
                          "qcom,mdss-dsi-h-sync-pulse = <1>;", "h-sync-pulse 0 -> 1", n),
    add_esd,
    lambda t, n: sub_once(t, "qcom,mdss-dsi-panel-status-valid-params = <0>;",
                          "qcom,mdss-dsi-panel-status-valid-params = <1>;", "status-valid-params 0 -> 1", n),
])


# --- тактовый генератор DSI (spread-spectrum) ---
patch("sdm439-olive.dtsi", [
    lambda t, n: sub_once(t, "qcom,ssc-frequency-hz = <35500>;",
                          "qcom,ssc-frequency-hz = <31500>;", "DSI PLL ssc 35500 -> 31500", n),
])
