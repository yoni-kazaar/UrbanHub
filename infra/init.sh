set -eu
export MC_CONFIG_DIR=/tmp/.mc

until mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1; do
  sleep 1
done

for bucket in bronze silver gold; do
  mc mb --ignore-existing "local/$bucket"
done
mc version enable local/gold

create_account() {
  mc admin user add local "$1" "$2"
  mc admin policy create local "$1" "/policies/$1.json"
  mc admin policy attach local "$1" --user "$1" || true
}

create_account meteo "$MINIO_METEO_SECRET"
create_account velos "$MINIO_VELOS_SECRET"
create_account pollution "$MINIO_POLLUTION_SECRET"
create_account croise "$MINIO_CROISE_SECRET"
