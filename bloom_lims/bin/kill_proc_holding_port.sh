#!/bin/bash

# Function to kill processes by port
kill_processes_by_port() {
    local port=$1
    local pids=$(lsof -t -i:$port)

    if [ -z "$pids" ]; then
        echo "No processes found running on port $port."
        return
    fi

    echo "Found processes running on port $port: $pids"

    echo "Sending SIGTERM to processes..."
    for pid in $pids; do
        sudo kill -TERM $pid
    done

    # Wait for a moment to ensure processes receive the signal
    sleep 2

    echo "Sending SIGKILL to processes..."
    for pid in $pids; do
        sudo kill -KILL $pid
    done

    # Wait for a moment to ensure processes are killed
    sleep 2

    echo "Using fuser to release port $port..."
    sudo fuser -k $port/tcp

    # Verify if any processes are still running on the port
    remaining_pids=$(lsof -t -i:$port)
    if [ -z "$remaining_pids" ]; then
        echo "All processes on port $port have been terminated."
    else
        echo "Processes still running on port $port: $remaining_pids"
        echo "Attempting to kill remaining processes with SIGKILL..."
        for pid in $remaining_pids; do
            sudo kill -KILL $pid
        done
    fi

    # Final check
    final_pids=$(lsof -t -i:$port)
    if [ -z "$final_pids" ]; then
        echo "All processes on port $port have been terminated."
    else
        echo "Failed to terminate processes: $final_pids"
    fi
}

# Check if a port is provided
if [ -z "$1" ]; then
    echo "Usage: $0 <port>"
    exit 1
fi

# Run the function to kill processes on the specified port
kill_processes_by_port $1
