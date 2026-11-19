set -eu
export MC_CONFIG_DIR=/tmp/.mc

until mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1; do
  sleep 1
done

for bucket in bronze silver gold; do
  mc mb --ignore-existing "local/$bucket"
done
mc version enable local/gold

# create_account <nom du compte> <fichier de policy sans .json> <secret>
create_account() {
  mc admin user add local "$1" "$3"
  mc admin policy create local "$1" "/policies/$2.json"
  mc admin policy attach local "$1" --user "$1" || true
}

create_account urbanhub-meteo meteo "$MINIO_METEO_SECRET"
create_account urbanhub-velos velos "$MINIO_VELOS_SECRET"
create_account urbanhub-pollution pollution "$MINIO_POLLUTION_SECRET"
create_account urbanhub-croise croise "$MINIO_CROISE_SECRET"
