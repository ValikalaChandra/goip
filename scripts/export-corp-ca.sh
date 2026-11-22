#!/bin/sh
# Export a corporate TLS-inspection root certificate (PUBLIC part only) from the macOS keychain.
# Usage: scripts/export-corp-ca.sh goskope        (any part of the certificate's common name)
set -e
name="${1:?usage: export-corp-ca.sh <part of the certificate name, e.g. goskope>}"
cd "$(dirname "$0")/.."
mkdir -p certs
security find-certificate -a -c "$name" -p > certs/corp-ca.pem
if grep -q "PRIVATE KEY" certs/corp-ca.pem; then rm -f certs/corp-ca.pem; echo "refusing: file contained a private key"; exit 1; fi
echo "exported $(grep -c 'BEGIN CERTIFICATE' certs/corp-ca.pem) certificate(s) to certs/corp-ca.pem"
