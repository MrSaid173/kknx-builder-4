#!/usr/bin/env bash
# Выбор коммита ReSukiSU (только он; SUSFS и NoMount по-прежнему идут через resolve_ref.sh).
#   resolve_resukisu.sh <repo-url> [ref]
#
# ref пусто или "latest" -> коммит ПОСЛЕДНЕГО РЕЛИЗА со страницы Releases (включая пре-релизы вроде v4.2.0-rc3),
#                           у которого есть APK менеджера. Ядро собирается под тот менеджер, который можно
#                           скачать сейчас в Releases; бета-канал и свежие коммиты main не используются.
# ref = "beta"           -> коммит, для которого CI собрал бета-менеджер (плашка "New beta version N" в приложении)
# ref = "head"           -> последний коммит основной ветки (менеджера для него может не быть)
# иначе                  -> тег / ветка / полный SHA, как в resolve_ref.sh
#
# В stdout только SHA; пояснения в stderr. Если узнать версию не удалось, сборка падает с подсказкой:
# молча брать HEAD нельзя, именно это давало "Manager update required".
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
url="$1"; ref="$(echo "${2:-}" | xargs)"

case "${ref,,}" in
  head) exec bash "$HERE/resolve_ref.sh" "$url" "" ;;
  ""|latest) mode=release ;;
  beta) mode=beta ;;
  *) exec bash "$HERE/resolve_ref.sh" "$url" "$ref" ;;
esac

repo="${url#https://github.com/}"; repo="${repo%.git}"
hdr=(-H "Accept: application/vnd.github+json" -H "X-GitHub-Api-Version: 2022-11-28")
[ -n "${GITHUB_TOKEN:-}" ] && hdr+=(-H "Authorization: Bearer $GITHUB_TOKEN")

api_get() {  # url -> stdout (3 попытки)
  local i out
  for i in 1 2 3; do
    if out="$(curl -fsS --max-time 30 "${hdr[@]}" "$1" 2>/dev/null)"; then printf '%s' "$out"; return 0; fi
    echo "[resukisu] GitHub API: попытка $i не удалась" >&2; sleep $((i * 5))
  done
  return 1
}

fail() {
  echo "[ОШИБКА] $1" >&2
  echo "         Повторите запуск или задайте resukisu_ref явно: тег релиза (например v4.2.0-rc3), полный SHA, beta или head." >&2
  exit 1
}

if [ "$mode" = beta ]; then
  json="$(api_get "https://api.github.com/repos/$repo/actions/workflows/build-manager.yml/runs?branch=main&status=success&event=push&per_page=1")" \
    || fail "GitHub API недоступен (бета-канал менеджера)."
  sha="$(printf '%s' "$json" | python3 -c '
import sys, json
try:
    sha = json.load(sys.stdin)["workflow_runs"][0]["head_sha"]
    assert len(sha) == 40
    print(sha)
except Exception:
    pass' 2>/dev/null || true)"
  [[ "$sha" =~ ^[0-9a-f]{40}$ ]] || fail "не нашёл успешной сборки менеджера в CI ReSukiSU."
  echo "[ref] $url: коммит бета-менеджера ${sha:0:12}" >&2
  echo "$sha"; exit 0
fi

# --- release: последний опубликованный релиз (пре-релизы считаются) с APK менеджера ---
tag=""
json="$(api_get "https://api.github.com/repos/$repo/releases?per_page=15" || true)"
if [ -n "$json" ]; then
  # имя APK как в менеджере: ReSukiSU_<имя>_<код версии>-<abi>-release.apk
  mapfile -t out < <(printf '%s' "$json" | python3 -c '
import sys, json, re
pat = re.compile(r"^ReSukiSU_(.+)_(\d+)-(arm64-v8a|armeabi-v7a|x86_64|universal)-release\.apk$")
try:
    rels = json.load(sys.stdin)
    for r in rels:
        if r.get("draft"):
            continue
        codes = sorted({m.group(2) for a in r.get("assets", []) for m in [pat.match(a.get("name", ""))] if m})
        if codes:
            print(r["tag_name"]); print(codes[-1]); print(r.get("published_at", "")); print("pre-release" if r.get("prerelease") else "stable")
            break
except Exception:
    pass' 2>/dev/null || true)
  tag="${out[0]:-}"
  if [ -n "$tag" ]; then
    echo "[ref] $url: последний релиз с менеджером: $tag (${out[3]:-?}, ${out[2]:-?}), в имени APK версия ${out[1]:-?}" >&2
  fi
fi

if [ -z "$tag" ]; then
  # запасной путь: лента релизов (без лимитов API). APK не проверяем, но релиз остаётся релизом.
  feed="$(curl -fsS --max-time 30 "$url/releases.atom" 2>/dev/null || true)"
  tag="$(printf '%s' "$feed" | python3 -c '
import sys, re
m = re.findall(r"<entry>.*?<title>([^<]+)</title>", sys.stdin.read(), re.S)
print(m[0].strip() if m else "")' 2>/dev/null || true)"
  [ -n "$tag" ] || fail "не удалось узнать последний релиз ReSukiSU (ни API, ни лента релизов)."
  echo "[ref] $url: API недоступен, по ленте релизов последний: $tag (наличие APK не проверено)" >&2
fi

exec bash "$HERE/resolve_ref.sh" "$url" "$tag"
