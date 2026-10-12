#!/bin/sh
set -eu
# User identifier is configuration, never free-form SQL input.
case "$MYSQL_USER" in
  ''|*[!a-zA-Z0-9_]*) echo 'Invalid application user identifier' >&2; exit 1 ;;
esac
MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --protocol=socket --user=root <<SQL
CREATE DATABASE IF NOT EXISTS procureflow_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL PRIVILEGES ON procureflow_test.* TO '${MYSQL_USER}'@'%';
SQL
