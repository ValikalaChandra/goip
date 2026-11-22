#!/bin/sh
# At run time, trust an optional corporate root certificate (mounted read-only) on top of the system roots.
set -e
if [ -s /etc/goip/corp-ca.pem ]; then
  cat /etc/ssl/certs/ca-certificates.crt /etc/goip/corp-ca.pem > /tmp/ca-bundle.pem
  export SSL_CERT_FILE=/tmp/ca-bundle.pem REQUESTS_CA_BUNDLE=/tmp/ca-bundle.pem CURL_CA_BUNDLE=/tmp/ca-bundle.pem
fi
exec "$@"
