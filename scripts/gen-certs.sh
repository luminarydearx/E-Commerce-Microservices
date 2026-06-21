#!/bin/bash
# Generate RSA keypair for JWT signing
# Usage: ./scripts/gen-certs.sh

set -e

KEY_DIR="${1:-./keys}"
mkdir -p "$KEY_DIR"

if [ -f "$KEY_DIR/private.pem" ] && [ -f "$KEY_DIR/public.pem" ]; then
    echo "Keys already exist in $KEY_DIR, skipping generation."
    echo "To regenerate, delete $KEY_DIR directory first."
    exit 0
fi

echo "Generating RSA 4096-bit keypair..."

# Private key (PEM, PKCS#8)
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 -out "$KEY_DIR/private.pem"

# Public key (PEM, PKIX)
openssl rsa -pubout -in "$KEY_DIR/private.pem" -out "$KEY_DIR/public.pem"

# Set restrictive permissions
chmod 600 "$KEY_DIR/private.pem"
chmod 644 "$KEY_DIR/public.pem"

echo "Keys generated:"
echo "  Private: $KEY_DIR/private.pem (chmod 600)"
echo "  Public:  $KEY_DIR/public.pem (chmod 644)"
echo ""
echo "IMPORTANT: Never commit private.pem to git!"
echo "           The .gitignore should already exclude it."
