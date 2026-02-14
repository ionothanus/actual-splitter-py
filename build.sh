#!/bin/zsh
set -e

# Source build environment if it exists
if [ -f .env.build ]; then
  source .env.build
fi

# Extract version from sync.py if not provided
VERSION=$1
if [ -z "$VERSION" ]; then
  VERSION=$(grep -m1 '^__version__' sync.py | cut -d'"' -f2)
  if [ -z "$VERSION" ]; then
    echo "Error: Could not extract version from sync.py"
    echo "Usage: ./build.sh [version] [architecture]"
    exit 1
  fi
  echo "Using version $VERSION from sync.py"
fi

ARCH=$2
if [ -z "$ARCH" ]; then
  ARCH="linux/amd64"
fi

echo "Building actual-rule-py version $VERSION..."
OUTPUT_NAME="actual-rule-py-$VERSION"
docker buildx build --platform "$ARCH" -t actual-rule-py:"$VERSION" -t actual-rule-py:latest .
docker save -o ./build/"$OUTPUT_NAME".tar actual-rule-py:"$VERSION" actual-rule-py:latest

# Upload to Portainer if configured
if [ -n "$PORTAINER_URL" ] && [ -n "$PORTAINER_API_KEY" ] && [ -n "$PORTAINER_ENDPOINT_ID" ]; then
  echo "Uploading to Portainer..."

  HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST \
    -H "X-API-Key: $PORTAINER_API_KEY" \
    -H "Content-Type: application/x-tar" \
    --data-binary @./build/"$OUTPUT_NAME".tar \
    "$PORTAINER_URL/api/endpoints/$PORTAINER_ENDPOINT_ID/docker/images/load")

  if [ "$HTTP_STATUS" -eq 200 ]; then
    echo "Successfully uploaded image to Portainer"
  else
    echo "Failed to upload image to Portainer (HTTP $HTTP_STATUS)"
    exit 1
  fi
else
  echo "Portainer upload skipped (set PORTAINER_URL, PORTAINER_API_KEY, and PORTAINER_ENDPOINT_ID to enable)"
  gzip -f ./build/"$OUTPUT_NAME".tar
fi
