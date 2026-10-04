#!/usr/bin/env bash
# Превращает "версию" в полный SHA коммита.
#   resolve_ref.sh <repo-url> [ref]
# ref пустой  -> HEAD репозитория (последний коммит ветки по умолчанию)
# ref = 40 hex -> берётся как есть
# иначе ветка или тег (тег с ^{} = коммит под аннотированным тегом)
# В stdout только SHA; пояснения идут в stderr.
set -euo pipefail
url="$1"; ref="${2:-}"
ref="$(echo "$ref" | xargs)"   # trim

if [ -z "$ref" ] || [ "${ref,,}" = "latest" ]; then
  sha="$(git ls-remote "$url" HEAD | awk 'NR==1{print $1}')"
  [ -n "$sha" ] || { echo "[ОШИБКА] $url: не удалось получить HEAD" >&2; exit 1; }
  echo "[ref] $url: последний коммит ${sha:0:12}" >&2
  echo "$sha"; exit 0
fi

if [[ "$ref" =~ ^[0-9a-fA-F]{40}$ ]]; then
  echo "[ref] $url: коммит ${ref:0:12} (задан явно)" >&2
  echo "${ref,,}"; exit 0
fi

# ветка -> peeled-тег -> тег. Берём первое совпадение.
out="$(git ls-remote "$url" "refs/heads/$ref" "refs/tags/$ref^{}" "refs/tags/$ref")"
sha="$(echo "$out" | awk -v r="refs/tags/$ref^{}" '$2==r{print $1; f=1} END{}' | head -1)"
[ -n "$sha" ] || sha="$(echo "$out" | awk -v r="refs/heads/$ref" '$2==r{print $1}' | head -1)"
[ -n "$sha" ] || sha="$(echo "$out" | awk -v r="refs/tags/$ref" '$2==r{print $1}' | head -1)"
if [ -z "$sha" ]; then
  # короткий SHA нельзя разрешить через ls-remote
  echo "[ОШИБКА] $url: не нашёл ветку/тег '$ref'. Укажите полный 40-символьный SHA, ветку или тег." >&2
  exit 1
fi
echo "[ref] $url: '$ref' -> ${sha:0:12}" >&2
echo "$sha"
