#!/usr/bin/env python3
"""ReSukiSU: disable_seccomp() должен быть no-op при CONFIG_SECCOMP=n (так в kuro439_defconfig).

Без этого policy/app_profile.c не компилируется: у struct seccomp нет полей mode/filter.
Если seccomp в ядре выключен, отключать нечего, поведение для root-профилей не меняется.
Идемпотентен.
"""
import pathlib, sys

p = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "KernelSU") / "kernel/policy/app_profile.c"
s = p.read_text()
head = "void disable_seccomp(void)\n{\n"
tail = "}\n\nint escape_with_root_profile(void)"
MARK = "#ifndef CONFIG_SECCOMP"
if MARK in s:
    print("[=] app_profile.c: уже пропатчен"); sys.exit(0)
if s.count(head) != 1 or s.count(tail) != 1:
    print("[!] app_profile.c: структура disable_seccomp изменилась, проверьте патч", file=sys.stderr); sys.exit(1)
s = s.replace(head, head + MARK + "\n    return;\n#else\n", 1)
s = s.replace(tail, "#endif /* CONFIG_SECCOMP */\n" + tail, 1)
p.write_text(s)
print("[+] app_profile.c: disable_seccomp() обёрнут в #ifdef CONFIG_SECCOMP")
