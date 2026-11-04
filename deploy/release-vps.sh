#!/usr/bin/env bash
# Run from the production checkout with the requested commit already fetched.
set -euo pipefail
umask 077

if [[ $# != 1 || ! $1 =~ ^[0-9a-f]{40}$ ]]; then
    echo "Pemakaian: bash deploy/release-vps.sh SHA_COMMIT_LENGKAP" >&2
    exit 2
fi

target=$1
repo=$(git rev-parse --show-toplevel)
cd "$repo"
lock=$(git rev-parse --git-path mcp-release.lock)
exec 9>"$lock"
flock -n 9 || { echo "Deployment lain sedang berjalan." >&2; exit 1; }

service=mcp-satudataaceh.service
webroot=/var/www/mcpsatudataaceh.web.id
domain=www.mcpsatudataaceh.web.id
assets=(app.js styles.css logo.svg favicon.svg index.html)
base=$(git rev-parse HEAD)
test -n "$(git branch --show-current)"
test -z "$(git status --porcelain)"
git cat-file -e "$target^{commit}"
if [[ $base == "$target" ]]; then
    echo "Commit sudah aktif di checkout."
    exit 0
fi
git merge-base --is-ancestor "$base" "$target"
git diff --check "$base" "$target"
for asset in "${assets[@]}"; do
    test "$(git rev-parse "$target:public/$asset")" = "$(git rev-parse "$target:src/static/$asset")"
done
systemctl is-active --quiet "$service"
sudo -n nginx -t

backup_root=/var/backups/mcp-satudataaceh
sudo -n install -d -m 700 "$backup_root"
backup=$(sudo -n mktemp -d "$backup_root/release-${target:0:7}.XXXXXXXX")
pid=$(systemctl show -p MainPID --value "$service")
sudo -n python3 - "$pid" "$repo" "$backup/accounts.sqlite3" <<'PY'
from contextlib import closing
from pathlib import Path
import os
import sqlite3
import sys

pid, repo, backup = sys.argv[1:]
environment = dict(
    item.split(b"=", 1) for item in Path(f"/proc/{int(pid)}/environ").read_bytes().split(b"\0")
    if b"=" in item
)
source = Path(os.fsdecode(environment.get(b"ACCOUNTS_DB_PATH", b"var/accounts.sqlite3")))
if not source.is_absolute():
    source = Path(repo) / source
os.umask(0o077)
with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as database:
    with closing(sqlite3.connect(backup)) as copy:
        database.backup(copy)
        if copy.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise SystemExit("Cadangan SQLite gagal pemeriksaan integritas.")
PY
sudo -n install -d -m 700 "$backup/web"
for asset in "${assets[@]}"; do
    if sudo -n test -f "$webroot/$asset"; then
        sudo -n cp -a -- "$webroot/$asset" "$backup/web/$asset"
    fi
done
echo "Cadangan rilis tersimpan di $backup."

check_dir=$(mktemp -d)
changed=0
web_changed=0
swap_asset() {
    local source=$1 asset=$2 temporary
    temporary=$(sudo -n mktemp "$webroot/.mcp-asset.XXXXXXXX") || return
    if ! sudo -n install -m 644 "$source" "$temporary" || ! sudo -n mv -f -- "$temporary" "$webroot/$asset"; then
        sudo -n rm -f -- "$temporary"
        return 1
    fi
}
finish() {
    local status=$?
    trap - EXIT
    if ((status && changed)); then
        echo "Deployment gagal. Memulihkan commit $base dan aset sebelumnya." >&2
        if ((web_changed)); then
            for asset in "${assets[@]}"; do
                if sudo -n test -f "$backup/web/$asset"; then
                    swap_asset "$backup/web/$asset" "$asset" ||
                        echo "Gagal memulihkan aset $asset." >&2
                else
                    sudo -n rm -f -- "$webroot/$asset" ||
                        echo "Gagal menghapus aset baru $asset." >&2
                fi
            done
        fi
        if ! git reset --keep "$base" || ! sudo -n systemctl restart "$service"; then
            echo "Pemulihan backend gagal. Periksa layanan dan cadangan di $backup." >&2
        fi
    fi
    rm -rf -- "$check_dir"
    exit "$status"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

git merge --ff-only "$target"
changed=1
sudo -n systemctl restart "$service"
loopback=http://127.0.0.1:8000
for attempt in {1..20}; do
    if curl -fsS --max-time 2 "$loopback/health" > "$check_dir/health.json" 2>/dev/null; then
        break
    fi
    sleep 1
done
python3 -c 'import json,sys; assert json.load(open(sys.argv[1]))["status"]=="ok"' "$check_dir/health.json"
systemctl is-active --quiet "$service"
test "$(curl -sS --max-time 5 -X POST -o /dev/null -w '%{http_code}' "$loopback/api/bps/connection-test")" = 401

web_changed=1
for asset in "${assets[@]}"; do
    swap_asset "$repo/public/$asset" "$asset"
done

https=(curl -fsS --max-time 10 --resolve "$domain:443:127.0.0.1")
for asset in "${assets[@]}"; do
    path="/$asset"
    if [[ $asset == index.html ]]; then path=/; fi
    "${https[@]}" "https://$domain$path" > "$check_dir/$asset"
    cmp "$repo/public/$asset" "$check_dir/$asset"
done
"${https[@]}" "https://$domain/.well-known/oauth-protected-resource/mcp" |
    python3 -c 'import json,sys; assert json.load(sys.stdin)["resource"] == "https://" + sys.argv[1] + "/mcp"' "$domain"
echo "Deployment terverifikasi pada commit $target."
