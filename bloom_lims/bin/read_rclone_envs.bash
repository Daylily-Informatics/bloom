#!/bin/bash

# Set the path to your .aws directory
AWS_DIR="$HOME/.aws"
CREDENTIALS_FILE="$AWS_DIR/credentials"
CONFIG_FILE="$AWS_DIR/config"

# Function to read the AWS credentials
read_aws_credentials() {
    local profile=$1
    local aws_access_key_id aws_secret_access_key

    aws_access_key_id=$(grep -A 2 "\[$profile\]" "$CREDENTIALS_FILE" | grep aws_access_key_id | awk '{print $3}')
    aws_secret_access_key=$(grep -A 2 "\[$profile\]" "$CREDENTIALS_FILE" | grep aws_secret_access_key | awk '{print $3}')

    export AWS_ACCESS_KEY_ID=$aws_access_key_id
    export AWS_SECRET_ACCESS_KEY=$aws_secret_access_key
}

# Function to read the AWS config
read_aws_config() {
    local profile=$1
    local region

    region=$(grep -A 2 "\[$profile\]" "$CONFIG_FILE" | grep region | awk '{print $3}')

    export AWS_REGION=$region
}

# Read the default profile by default, or use the AWS_PROFILE environment variable if set
PROFILE="${AWS_PROFILE:-default}"

# Read and export the AWS credentials and config
read_aws_credentials $PROFILE
read_aws_config $PROFILE

# Print out the values to confirm
echo "AWS_ACCESS_KEY_ID: $AWS_ACCESS_KEY_ID"
echo "AWS_SECRET_ACCESS_KEY: $AWS_SECRET_ACCESS_KEY"
echo "AWS_REGION: $AWS_REGION"

# Example usage of rclone with the set environment variables
# rclone ls s3:your-bucket-name
