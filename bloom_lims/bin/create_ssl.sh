#!/bin/bash

# Fetch the IMDSv2 token
TOKEN=$(curl -X PUT 'http://169.254.169.254/latest/api/token' \
  -H 'X-aws-ec2-metadata-token-ttl-seconds: 21600')

# Get the public IP using the token
PUBLIC_IP=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" \
  http://169.254.169.254/latest/meta-data/public-ipv4)

# Fallback to internal IP if public IP is unavailable
if [[ -z "$PUBLIC_IP" ]]; then
  PUBLIC_IP=$(hostname -I | awk '{print $1}')
  echo "Using internal IP: $PUBLIC_IP"
else
  echo "Using public IP: $PUBLIC_IP"
fi

# Generate the self-signed certificate with the appropriate IP
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout selfsigned.key -out selfsigned.crt \
  -subj "/C=US/ST=State/L=City/O=Organization/OU=Unit/CN=$PUBLIC_IP"

echo "Certificate generated with CN=$PUBLIC_IP"

echo "checking validity"
openssl x509 -in selfsigned.crt -text -noout
