#!/bin/zsh

VERSION=$1
ARCH=$2

if [ -z $ARCH ]; then
  ARCH="linux/amd64"
fi

if [ -z "$VERSION" ]; then
  echo "Usage: ./build.sh <version> [architecture]"
  echo "default to linux/amd64: ./build.sh 0.2"
  echo "multiple architectures: ./build.sh 0.2 linux/amd64,linux/arm64"
  exit 1
fi

echo "Building actual-rule-py version $VERSION..."
OUTPUT_NAME="actual-rule-py-$VERSION"
docker buildx build --platform "$ARCH" -t actual-rule-py:"$VERSION" .
docker save -o ./build/"$OUTPUT_NAME".tar actual-rule-py:"$VERSION"

gzip build/"$OUTPUT_NAME".tar build/"$OUTPUT_NAME".tar.gz   
