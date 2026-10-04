#!/usr/bin/env python3
"""Убирает старые ручные KSU-хуки (стиль tiann/KernelSU non-GKI) из fs/*.c.

Нужно потому, что SUSFS-патч для 4.9 ставит собственные inline su-compat хуки,
и дубли приводят к провалу патча / двойному вызову.
SELinux-блок (check_nnp_nosuid) НЕ трогаем: он нужен для перехода init -> su.
Идемпотентен: если хуков уже нет, ничего не делает.
"""
import re, sys, pathlib

root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")

# (файл, [(regex, замена)])
EDITS = {
    "fs/exec.c": [
        (r"extern bool ksu_execveat_hook __read_mostly;\n"
         r"extern int ksu_handle_execveat\(.*?\);\n"
         r"extern int ksu_handle_execveat_sucompat\(.*?\);\n", ""),
        (r"\tif \(unlikely\(ksu_execveat_hook\)\)\n"
         r"\t\tksu_handle_execveat\(.*?\);\n"
         r"\telse\n"
         r"\t\tksu_handle_execveat_sucompat\(.*?\);\n\n", ""),
    ],
    "fs/open.c": [
        (r"extern int ksu_handle_faccessat\(.*?\);\n", ""),
        (r"\tksu_handle_faccessat\(&dfd, &filename, &mode, NULL\);\n", ""),
    ],
    "fs/read_write.c": [
        (r"extern bool ksu_vfs_read_hook __read_mostly;\n"
         r"extern int ksu_handle_vfs_read\(.*?\);\n\n", ""),
        (r"\tif \(unlikely\(ksu_vfs_read_hook\)\)\n"
         r"\t\tksu_handle_vfs_read\(.*?\);\n\n", ""),
    ],
    "fs/stat.c": [
        (r"extern int ksu_handle_stat\(.*?\);\n\n", ""),
        (r"\tksu_handle_stat\(&dfd, &filename, &flag\);\n", ""),
    ],
}

rc = 0
for rel, subs in EDITS.items():
    p = root / rel
    if not p.exists():
        print(f"[!] нет файла {rel}"); rc = 1; continue
    s = p.read_text()
    for pat, rep in subs:
        s, n = re.subn(pat, rep, s, flags=re.S)
        print(f"[{'+' if n else '='}] {rel}: {'удалено' if n else 'уже чисто'}  ({pat[:38].strip()!r})")
    p.write_text(s)
left = [str(f) for f in root.glob("fs/*.c") if "ksu_" in f.read_text()]
if left:
    print("[!] остались ksu_ в:", left); rc = 1
sys.exit(rc)
