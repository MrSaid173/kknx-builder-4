#!/usr/bin/env python3
"""Снимает `static` с символов SELinux, которые нужны ReSukiSU при CONFIG_KALLSYMS_ALL=n.

kuro439_defconfig не включает KALLSYMS_ALL (он требует DEBUG_KERNEL), а ReSukiSU в этом случае
линкуется с символами напрямую через extern и проверяет (tools/static_export_check.mk), что `static` снят.
Идемпотентен: если `static` уже снят, строка остаётся как есть.
"""
import pathlib, sys

root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
EDITS = {
    "security/selinux/selinuxfs.c": [
        ("static ssize_t (*write_op[])", "ssize_t (*write_op[])"),
        ("static const struct file_operations sel_handle_status_ops", "const struct file_operations sel_handle_status_ops"),
        ("static DEFINE_MUTEX(sel_mutex)", "DEFINE_MUTEX(sel_mutex)"),
    ],
    "security/selinux/ss/status.c": [
        ("static struct page *selinux_status_page", "struct page *selinux_status_page"),
        ("static DEFINE_MUTEX(selinux_status_lock)", "DEFINE_MUTEX(selinux_status_lock)"),
    ],
    "security/selinux/ss/services.c": [
        ("static DEFINE_RWLOCK(policy_rwlock)", "DEFINE_RWLOCK(policy_rwlock)"),
    ],
}
rc = 0
for rel, subs in EDITS.items():
    p = root / rel
    s = p.read_text()
    for old, new in subs:
        if s.count(old) == 1:
            s = s.replace(old, new)
            print(f"[+] {rel}: {old.split('(')[0].replace('static ', '').strip()[:48]} -> не static")
        elif new in s and old not in s:
            print(f"[=] {rel}: уже без static ({new[:40]})")
        else:
            print(f"[!] {rel}: не нашёл ровно одно вхождение {old!r}", file=sys.stderr)
            rc = 1
    p.write_text(s)
sys.exit(rc)
