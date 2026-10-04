#!/usr/bin/env python3
"""check_config.py <.config> <файл со строками>: каждая строка файла должна быть в .config.

  CONFIG_X=y / CONFIG_X="s"   строка должна совпасть точно
  # CONFIG_X is not set       допустимо и это, и полное отсутствие символа (olddefconfig убрал его по зависимостям);
                              недопустимо только CONFIG_X=y|m|значение
Выход 1, если хоть одна опция не применилась (olddefconfig молча отбрасывает неподходящее).
"""
import re
import sys

cfg = open(sys.argv[1]).read().splitlines()
have = set(cfg)
bad = 0
for line in open(sys.argv[2]).read().splitlines():
    line = line.strip()
    if not line or line in have:
        continue
    m = re.fullmatch(r"# (CONFIG_\w+) is not set", line)
    if m and not any(c.startswith(m.group(1) + "=") for c in cfg):
        continue
    print(f"[ОШИБКА] не применилось после olddefconfig: {line}")
    bad += 1
print(f"[ok] твики в .config: все на месте" if not bad else f"[ОШИБКА] не применилось опций: {bad}")
sys.exit(1 if bad else 0)
