#!/bin/sh

git describe | sed 's/^v//' | tr - +
