#!/usr/bin/env python3
"""
Simple ROCm-SMI GPU Monitor
Very basic GPU monitoring using only rocm-smi command
"""

import subprocess
import json
import time
import sys

def get_gpu_info():
    """Get basic GPU info using rocm-smi"""
    try:
        # Run rocm-smi with JSON output
        result = subprocess.run(['rocm-smi', '--showall', '--json'], 
                              capture_output=True, text=True, timeout=5)
        
        if result.returncode != 0:
            print(f"Error running rocm-smi: {result.stderr}")
            return None
        
        data = json.loads(result.stdout)
        return data
    except subprocess.TimeoutExpired:
        print("rocm-smi timed out")
        return None
    except FileNotFoundError:
        print("rocm-smi not found. Please install ROCm.")
        return None
    except json.JSONDecodeError:
        print("Failed to parse rocm-smi output")
        return None

def print_gpu_status(data):
    """Print basic GPU status"""
    if not data:
        return
    
    print("\n=== GPU Status ===")
    
    for card_key, gpu_data in data.items():
        if not card_key.startswith('card'):
            continue
            
        gpu_id = card_key.replace('card', '')
        
        # Extract basic info
        power = gpu_data.get('Current Socket Graphics Package Power (W)', 'N/A')
        temp = gpu_data.get('Temperature (Sensor junction) (C)', 'N/A')
        util = gpu_data.get('GPU use (%)', 'N/A')
        vram = gpu_data.get('GPU Memory Allocated (VRAM%)', 'N/A')
        
        print(f"GPU {gpu_id}: {power}W, {temp}°C, {util}% util, {vram}% VRAM")

def monitor_loop():
    """Simple monitoring loop"""
    print("Simple ROCm-SMI Monitor - Press Ctrl+C to stop")
    
    try:
        while True:
            data = get_gpu_info()
            print_gpu_status(data)
            time.sleep(2)  # Update every 2 seconds
            
    except KeyboardInterrupt:
        print("\nMonitoring stopped.")

if __name__ == "__main__":
    # Check if rocm-smi is available
    try:
        subprocess.run(['rocm-smi', '--version'], capture_output=True, timeout=2)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print("Error: rocm-smi not found or not working")
        sys.exit(1)
    
    # Single shot mode if argument provided
    if len(sys.argv) > 1 and sys.argv[1] == '--once':
        data = get_gpu_info()
        print_gpu_status(data)
    else:
        monitor_loop()

